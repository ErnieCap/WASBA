
import os
print ("RUNNING APP.PY FROM:",os.path.abspath(__file__))
import uuid
from flask import Flask, render_template, request, redirect, url_for, abort

from service import assess_case_free, assess_case_premium
from payments import create_checkout_session, handle_stripe_webhook

app = Flask(__name__)

# DEV-ONLY storage (resets when app restarts)
CASE_STORE = {}
# CASE_STORE[case_id] = {"case": {...}, "free_result": {...}, "paid": bool}


@app.route("/", methods=["GET"])
def index():
    return render_template("form.html")


@app.route("/assess", methods=["POST"])
def assess():
    # --- existing fields ---
    notes = request.form.get("notes", "")
    num_previous_incidents_raw = request.form.get("num_previous_incidents", "0")
    vulnerable_raw = request.form.get("vulnerable_tenant", "no")
    incident_type = request.form.get("incident_type", "")
    criminal_history_raw = request.form.get("has_criminal_history", "no")

    try:
        num_previous_incidents = int(num_previous_incidents_raw)
    except ValueError:
        num_previous_incidents = 0

    vulnerable_tenant = (vulnerable_raw.lower() == "yes")
    has_criminal_history = (criminal_history_raw.lower() == "yes")

    case = {
        "notes": notes,
        "num_previous_incidents": num_previous_incidents,
        "vulnerable_tenant": vulnerable_tenant,
        "incident_type": incident_type,
        "has_criminal_history": has_criminal_history,
    }

    # --- matrix fields (optional) ---
    matrix_scores = {}
    all_answered = True
    for i in range(1, 15):
        raw = request.form.get(f"matrix_q{i}", "")
        if raw == "":
            all_answered = False
            break
        try:
            matrix_scores[f"matrix_q{i}"] = int(raw)
        except ValueError:
            all_answered = False
            break

    if all_answered:
        case["matrix_scores"] = matrix_scores

    # Create a case_id for paywall flow
    case_id = str(uuid.uuid4())

    # FREE assessment (no LLM cost)
    free_result = assess_case_free(case)

    # Store for later checkout/premium
    CASE_STORE[case_id] = {"case": case, "free_result": free_result, "paid": False}

    # Render free result, with a pay button
    return render_template("result.html", result=free_result, case_id=case_id, paid=False)


@app.route("/create-checkout-session", methods=["POST"])
def create_checkout():
    """
    User clicks 'Unlock full report (£1)'.
    We create a Stripe Checkout session linked to case_id.
    """
    case_id = request.form.get("case_id", "")
    if not case_id or case_id not in CASE_STORE:
        abort(400, "Unknown or expired case_id")

    # The URL Stripe should return the user to after payment
    success_url = url_for("premium", case_id=case_id, _external=True) + "?session_id={CHECKOUT_SESSION_ID}"
    cancel_url = url_for("free_result", case_id=case_id, _external=True)

    session = create_checkout_session(
        case_id=case_id,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return redirect(session.url, code=303)


@app.route("/case/<case_id>", methods=["GET"])
def free_result(case_id: str):
    """
    Show the free result again (e.g. if user cancels Stripe checkout).
    """
    record = CASE_STORE.get(case_id)
    if not record:
        abort(404, "Case not found (maybe expired).")

    return render_template(
        "result.html",
        result=record["free_result"],
        case_id=case_id,
        paid=record["paid"],
    )


@app.route("/premium/<case_id>", methods=["GET"])
def premium(case_id: str):
    """
    Premium page: only works once Stripe webhook has marked paid=True.
    """
    record = CASE_STORE.get(case_id)
    if not record:
        abort(404, "Case not found (maybe expired).")

    if not record["paid"]:
        # Payment not confirmed yet (webhook is the source of truth)
        return render_template(
            "result.html",
            result=record["free_result"],
            case_id=case_id,
            paid=False,
            payment_pending=True,
        )

    # Paid: now we can do the expensive call (LLM)
    premium_result = assess_case_premium(record["case"])
    return render_template(
        "result.html",
        result=premium_result,
        case_id=case_id,
        paid=True,
    )


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """
    Stripe will POST events here. We verify signature and, if payment completed,
    mark CASE_STORE[case_id]["paid"] = True.
    """
    payload = request.get_data(as_text=False)
    sig_header = request.headers.get("Stripe-Signature", "")
    handled = handle_stripe_webhook(payload, sig_header, CASE_STORE)
    return ("OK" if handled else "IGNORED", 200)


if __name__ == "__main__":
    app.run(debug=True)
