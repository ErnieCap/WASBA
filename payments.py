import os
import stripe

from db import mark_paid

# Required env vars:
# STRIPE_SECRET_KEY
# STRIPE_PRICE_ID        (create a £3 Price in Stripe dashboard)
# STRIPE_WEBHOOK_SECRET  (webhook signing secret)

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")


def create_checkout_session(case_id: str, success_url: str, cancel_url: str):
    price_id = os.environ.get("STRIPE_PRICE_ID")
    if not stripe.api_key:
        raise RuntimeError("STRIPE_SECRET_KEY is not set")
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


def handle_stripe_webhook(payload: bytes, sig_header: str) -> bool:
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is not set")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=webhook_secret,
        )
    except Exception:
        # invalid signature or invalid payload
        return False

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        case_id = (session.get("metadata") or {}).get("case_id")
        if case_id:
            return mark_paid(case_id)

    return False
