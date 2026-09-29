import logging
import os
import uuid

logging.basicConfig(level=logging.INFO)

print("RUNNING APP.PY FROM:", os.path.abspath(__file__))

from flask import Flask, render_template, request, redirect, url_for, abort
from werkzeug.middleware.proxy_fix import ProxyFix

from service import assess_case_free, assess_case_premium
from payments import (
    create_checkout_session,
    check_payment_intent_succeeded,
)

from datetime import datetime, timezone

from db import (
    init_db,
    create_case, get_case,
)

USE_DB = bool(os.environ.get("DATABASE_URL"))
CASE_STORE = {}  # local-only fallback store

if USE_DB:
    init_db()
else:
    print("DATABASE_URL not set — running in LOCAL DEV mode using in-memory storage.")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")

# On Render, TLS is terminated at the edge; ProxyFix makes _external URLs HTTPS.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)


@app.route("/", methods=["GET"])
def landing():
    return render_template("landing.html")


@app.route("/asb", methods=["GET"])
def asb():
    return render_template("asb/form.html")


def _collect_case_from_form() -> dict:
    case = {
        "notes": request.form.get("notes", "").strip(),
        "num_previous_incidents": int(request.form.get("num_previous_incidents", "0") or 0),
        "vulnerable_tenant": request.form.get("vulnerable_tenant", "").strip(),
        "incident_type": request.form.get("incident_type", "").strip(),
        "has_criminal_history": request.form.get("has_criminal_history", "").strip(),
    }

    for i in range(1, 15):
        key = f"matrix_q{i}"
        val = request.form.get(key)
        if val is not None and val != "":
            try:
                case[key] = int(val)
            except ValueError:
                case[key] = val

    return case


def _get_case_record(case_id: str):
    return get_case(case_id) if USE_DB else CASE_STORE.get(case_id)


@app.route("/assess", methods=["POST"])
def assess():
    case = _collect_case_from_form()
    if not case.get("notes"):
        abort(400, "Case notes are required.")

    case_id = str(uuid.uuid4())
    free_result = assess_case_free(case)

    if USE_DB:
        create_case(case_id, case, free_result)
    else:
        CASE_STORE[case_id] = {"case_data": case, "free_result": free_result, "paid": False}

    return render_template("asb/result.html", result=free_result, case_id=case_id, paid=False)


@app.route("/pay/<case_id>", methods=["POST"])
def pay(case_id: str):
    row = _get_case_record(case_id)
    if not row:
        abort(404, "Case not found (maybe expired).")

    if not USE_DB:
        abort(400, "Payments disabled in local dev. Deploy to Render (with DATABASE_URL) to test Stripe.")

    success_url = url_for("premium", case_id=case_id, _external=True) + "?session_id={CHECKOUT_SESSION_ID}"
    cancel_url = url_for("premium", case_id=case_id, _external=True)

    session = create_checkout_session(case_id, success_url, cancel_url, metadata={"product": "asb_unlock"})
    return redirect(session.url, code=303)


@app.route("/premium/<case_id>", methods=["GET"])
def premium(case_id: str):
    row = _get_case_record(case_id)
    if not row:
        abort(404, "Case not found (maybe expired).")

    if not row["paid"]:
        session_id = request.args.get("session_id")
        if session_id and USE_DB:
            from payments import verify_and_mark_paid
            row["paid"] = verify_and_mark_paid(case_id, session_id)

    if not row["paid"]:
        return render_template("asb/result.html", result=row["free_result"], case_id=case_id, paid=False)

    premium_result = assess_case_premium(row["case_data"])
    return render_template("asb/result.html", result=premium_result, case_id=case_id, paid=True)


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    import stripe as _stripe
    import threading

    logging.info("[webhook] request received")

    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

    if not webhook_secret:
        logging.warning("[webhook] STRIPE_WEBHOOK_SECRET not set")
        if os.environ.get("RENDER"):
            return ("STRIPE_WEBHOOK_SECRET not configured", 400)
        return ("IGNORED (no webhook secret in local dev)", 200)

    try:
        event = _stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as e:
        logging.error("[webhook] signature verification failed: %s", e)
        return (str(e), 400)

    logging.info("[webhook] signature OK — type=%s id=%s", event["type"], event.get("id", ""))

    def _process(ev):
        etype = ev["type"]
        logging.info("[webhook] _process started: %s", etype)

        if etype == "checkout.session.completed":
            session = ev["data"]["object"]
            metadata = session.get("metadata") or {}
            product = metadata.get("product")
            case_id = metadata.get("case_id")
            logging.info("[webhook] checkout completed — product=%s case_id=%s", product, case_id)
            if not USE_DB:
                logging.info("[webhook] no DB in local dev, skipping checkout event")
                return
            from db import mark_paid as _mark_paid
            if (product == "asb_unlock" or product is None) and case_id:
                result = _mark_paid(case_id)
                logging.info("[webhook] mark_paid(%s) -> %s", case_id, result)
            else:
                logging.warning("[webhook] checkout.session.completed unhandled — product=%s", product)
        else:
            logging.info("[webhook] unhandled event type: %s — ignoring", etype)

        logging.info("[webhook] _process complete: %s", etype)

    threading.Thread(target=_process, args=(event,), daemon=True).start()
    logging.info("[webhook] 200 returned, background thread started")
    return ("OK", 200)


@app.route("/privacy-policy")
def privacy_policy():
    return render_template("privacy-policy.html")

@app.route("/terms-of-service")
def terms_of_service():
    return render_template("terms-of-service.html")

@app.route("/cookie-policy")
def cookie_policy():
    return render_template("cookies.html")


@app.route("/health")
def health():
    return {
        "status": "ok",
        "use_db": USE_DB,
        "environment": "render" if os.environ.get("RENDER") else "local",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


if __name__ == "__main__":
    app.run(debug=True)
