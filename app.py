
import os
print ("RUNNING APP.PY FROM:",os.path.abspath(__file__))
import uuid

from flask import Flask, render_template, request, redirect, url_for, abort
from werkzeug.middleware.proxy_fix import ProxyFix

from service import assess_case_free, assess_case_premium
from payments import create_checkout_session, handle_stripe_webhook
from db import init_db, create_case, get_case

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")

# On Render, TLS is terminated at the edge; ProxyFix makes _external URLs HTTPS.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Create DB table(s)
init_db()


@app.route("/", methods=["GET"])
def index():
    return render_template("form.html")


def _collect_case_from_form() -> dict:
    # Mirrors your templates/form.html fields
    case = {
        "notes": request.form.get("notes", "").strip(),
        "num_previous_incidents": int(request.form.get("num_previous_incidents", "0") or 0),
        "vulnerable_tenant": request.form.get("vulnerable_tenant", "").strip(),
        "incident_type": request.form.get("incident_type", "").strip(),
        "has_criminal_history": request.form.get("has_criminal_history", "").strip(),
    }

    # Matrix questions (0.. etc) come in as strings; store as ints where possible
    for i in range(1, 15):
        key = f"matrix_q{i}"
        val = request.form.get(key)
        if val is not None and val != "":
            try:
                case[key] = int(val)
            except ValueError:
                case[key] = val  # fall back

    return case


@app.route("/assess", methods=["POST"])
def assess():
    case = _collect_case_from_form()
    if not case.get("notes"):
        abort(400, "Case notes are required.")

    case_id = str(uuid.uuid4())
    free_result = assess_case_free(case)

    create_case(case_id, case, free_result)

    # Show free result + pay button
    return render_template("result.html", result=free_result, case_id=case_id, paid=False)


@app.route("/pay/<case_id>", methods=["POST"])
def pay(case_id: str):
    row = get_case(case_id)
    if not row:
        abort(404, "Case not found (maybe expired).")

    success_url = url_for("premium", case_id=case_id, _external=True)
    cancel_url = url_for("premium", case_id=case_id, _external=True)

    session = create_checkout_session(case_id, success_url, cancel_url)
    return redirect(session.url, code=303)


@app.route("/premium/<case_id>", methods=["GET"])
def premium(case_id: str):
    row = get_case(case_id)
    if not row:
        abort(404, "Case not found (maybe expired).")

    if not row["paid"]:
        # Payment not confirmed yet (webhook is the source of truth)
        return render_template("result.html", result=row["free_result"], case_id=case_id, paid=False)

    premium_result = assess_case_premium(row["case_data"])
    return render_template("result.html", result=premium_result, case_id=case_id, paid=True)


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    ok = handle_stripe_webhook(payload, sig_header)
    return ("OK" if ok else "IGNORED", 200)
