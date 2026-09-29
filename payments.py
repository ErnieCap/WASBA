import logging
import os
import stripe

from db import mark_paid

logger = logging.getLogger(__name__)


# Required env vars:
# STRIPE_SECRET_KEY
# STRIPE_PRICE_ID        (create a £3 Price in Stripe dashboard)
# STRIPE_WEBHOOK_SECRET  (webhook signing secret)
# STRIPE_PUBLISHABLE_KEY (used by Stripe.js on the frontend)

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


def verify_and_mark_paid(case_id: str, session_id: str) -> bool:
    """Directly verify a Stripe checkout session and mark the case paid.

    Called on the success redirect as a fallback for when the webhook hasn't
    arrived yet (common race condition).
    """
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as e:
        logger.error("Failed to retrieve Stripe session %s: %s", session_id, e)
        return False

    if session.get("payment_status") != "paid":
        logger.warning("Session %s payment_status=%s, not marking paid", session_id, session.get("payment_status"))
        return False

    meta_case_id = (session.get("metadata") or {}).get("case_id")
    if meta_case_id != case_id:
        logger.error("Session %s case_id mismatch: expected %s got %s", session_id, case_id, meta_case_id)
        return False

    result = mark_paid(case_id)
    logger.info("verify_and_mark_paid: mark_paid(%s) returned %s", case_id, result)
    return result


def check_payment_intent_succeeded(pi_id: str) -> bool:
    """Directly verify a PaymentIntent status with Stripe.

    Used as a fallback in the polling endpoint when the webhook is delayed
    or hasn't arrived yet — mirrors the verify_and_mark_paid pattern used
    by the existing ASB/noise checkout flow.
    """
    try:
        intent = stripe.PaymentIntent.retrieve(pi_id)
        return intent.get("status") == "succeeded"
    except Exception as e:
        logger.error("Failed to retrieve PaymentIntent %s: %s", pi_id, e)
        return False


