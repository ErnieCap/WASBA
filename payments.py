import os
import stripe

# Required environment variables:
# STRIPE_SECRET_KEY
# STRIPE_PRICE_ID   (a £1 Price you create in Stripe dashboard)
# STRIPE_WEBHOOK_SECRET (for webhook signature verification)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


def create_checkout_session(case_id: str, success_url: str, cancel_url: str):
    price_id = os.getenv("STRIPE_PRICE_ID")
    if not price_id:
        raise RuntimeError("STRIPE_PRICE_ID is not set")

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"case_id": case_id},
    )
    return session


def handle_stripe_webhook(payload: bytes, sig_header: str, case_store: dict) -> bool:
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is not set")

    event = stripe.Webhook.construct_event(
        payload=payload,
        sig_header=sig_header,
        secret=webhook_secret,
    )

    # Checkout completed
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        case_id = (session.get("metadata") or {}).get("case_id")

        if case_id and case_id in case_store:
            case_store[case_id]["paid"] = True
            return True

    return False
