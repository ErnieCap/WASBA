import os
import stripe

from db import mark_paid, mark_noise_case_paid



# Required env vars:
# STRIPE_SECRET_KEY
# STRIPE_PRICE_ID        (create a £3 Price in Stripe dashboard)
# STRIPE_WEBHOOK_SECRET  (webhook signing secret)

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")


from typing import Optional, Dict

def create_checkout_session(
    case_id: str,
    success_url: str,
    cancel_url: str,
    metadata: Optional[Dict[str, str]] = None,
):
    price_id = os.environ.get("STRIPE_PRICE_ID")
    if not stripe.api_key:
        raise RuntimeError("STRIPE_SECRET_KEY is not set")
    if not price_id:
        raise RuntimeError("STRIPE_PRICE_ID is not set")

    md = {"case_id": case_id}
    if metadata:
        md.update(metadata)

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=md,
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
        metadata = session.get("metadata") or {}

        product = metadata.get("product")  # we'll set this in checkout creation
        case_id = metadata.get("case_id")

        # ASB unlock (existing)
        if (product == "asb_unlock" or product is None) and case_id:
            # Backward-compatible: if you didn't set product before,
            # treat it as ASB unlock.
            return mark_paid(case_id)

        # Noise diary unlock (new)
        if product == "noise_unlock" and case_id:
            owner_uid = metadata.get("owner_uid")
            if not owner_uid:
                return False
            return mark_noise_case_paid(case_id, owner_uid)

    return False
