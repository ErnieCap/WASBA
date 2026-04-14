import logging
import os
import secrets
import time
import uuid

logging.basicConfig(level=logging.INFO)

print("RUNNING APP.PY FROM:", os.path.abspath(__file__))

from flask import Flask, render_template, request, redirect, url_for, abort, Response, make_response, flash
from werkzeug.middleware.proxy_fix import ProxyFix

from service import assess_case_free, assess_case_premium
from payments import (
    create_checkout_session, handle_stripe_webhook,
    create_letter_payment_intent, create_donation_intent,
    check_payment_intent_succeeded,
)

from datetime import datetime, timezone

# DB imports (Postgres)
from db import (
    count_noise_cases_for_owner, count_noise_entries_for_case,
    init_db,
    create_case, get_case,
    create_noise_case, list_noise_cases, get_noise_case,
    create_noise_entry, list_noise_entries, get_noise_entry,
    update_noise_entry, delete_noise_entry, delete_noise_case, get_noise_case_for_owner,
    delete_expired_noise_cases, get_active_noise_case_for_owner, update_noise_case,
    touch_noise_case_activity, get_noise_case_by_ref_code,
    create_letter_session, mark_letter_session_paid,
    get_letter_session_status, consume_letter_session_text,
    purge_expired_letter_sessions,
)

# --- Noise limits / pricing policy ---
FREE_MAX_DIARIES = 1
FREE_MAX_ENTRIES = 10
PAID_MAX_ENTRIES = 50
RETENTION_DAYS = 60
MAX_NOTE_CHARS = 200

def noise_entry_cap(case: dict) -> int:
    """Return max entries allowed for this noise diary case."""
    return PAID_MAX_ENTRIES if case.get("paid") else FREE_MAX_ENTRIES



app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")

# On Render, TLS is terminated at the edge; ProxyFix makes _external URLs HTTPS.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# ---------- Letter payment session store ----------
# Keyed by one-time UUID token.  Holds pre-generated letter text until
# payment_intent.succeeded webhook confirms payment.  No DB required.
# Template-agnostic: every letter type uses the same mechanism.
_LETTER_SESSIONS = {}   # token -> {text, paid, pi_id, expires}

_LETTER_SESSION_TTL = 3600  # 1 hour


def _purge_expired_letter_sessions():
    """Remove sessions older than TTL to avoid unbounded memory growth."""
    now = time.time()
    expired = [t for t, s in _LETTER_SESSIONS.items() if s.get("expires", 0) < now]
    for t in expired:
        _LETTER_SESSIONS.pop(t, None)


# ---------- Local dev fallback ----------
USE_DB = bool(os.environ.get("DATABASE_URL"))
CASE_STORE = {}  # local-only fallback store
NOISE_CASE_STORE = {}     # case_id -> {case fields..., entries:[...]}
NOISE_ENTRY_STORE = {}    # entry_id -> {entry fields...} (optional, but handy)


if USE_DB:
    init_db()
else:
    print("DATABASE_URL not set — running in LOCAL DEV mode using in-memory storage.")
# --------------------------------------

#this is a cookie that creates a uuid fir the user and sets up the uid on the users browser 
COOKIE_NAME = "wasba_uid"

_REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I

def _gen_ref_code() -> str:
    return "".join(secrets.choice(_REF_ALPHABET) for _ in range(8))


def get_owner_uid() -> str:
    uid = request.cookies.get(COOKIE_NAME)
    return uid if uid else str(uuid.uuid4())

def attach_owner_cookie(resp, owner_uid: str):
    if not request.cookies.get(COOKIE_NAME):
        resp.set_cookie(
            COOKIE_NAME,
            owner_uid,
            max_age=60 * 60 * 24 * 365 * 2,
            httponly=True,
            samesite="Lax",
            secure=bool(os.environ.get("RENDER")),
        )
    return resp


@app.route("/", methods=["GET"])
def landing():
    return render_template("landing.html")

@app.route("/letters", methods=["GET"])
def letters():
    return render_template(
        "letters.html",
        stripe_pk=os.environ.get("STRIPE_PUBLISHABLE_KEY", ""),
    )


@app.route("/letters/generate", methods=["POST"])
def letters_generate():
    import anthropic
    data = request.get_json()
    prompt = (data or {}).get("prompt", "").strip()
    if not prompt:
        return {"error": "No prompt provided"}, 400
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return {"text": message.content[0].text}


@app.route("/letters/create-session", methods=["POST"])
def letters_create_session():
    """Generate letter text and create a £1 Stripe PaymentIntent.

    Returns {token, client_secret} to the frontend.  The token unlocks the
    pre-generated letter once the webhook confirms payment.  Works for every
    letter template type — payment logic is entirely template-agnostic.
    """
    import anthropic
    data = request.get_json()
    prompt = (data or {}).get("prompt", "").strip()
    if not prompt:
        return {"error": "No prompt provided"}, 400

    # Generate letter text first so the spinner runs before the payment step
    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text
    except Exception as e:
        return {"error": f"Letter generation failed: {e}"}, 500

    token = str(uuid.uuid4())

    try:
        client_secret, pi_id = create_letter_payment_intent(token)
    except RuntimeError as e:
        return {"error": str(e)}, 503
    except Exception as e:
        return {"error": f"Payment setup failed: {e}"}, 500

    if USE_DB:
        from datetime import datetime, timezone, timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=_LETTER_SESSION_TTL)
        purge_expired_letter_sessions()
        create_letter_session(token, text, pi_id, expires_at)
    else:
        _purge_expired_letter_sessions()
        _LETTER_SESSIONS[token] = {
            "text": text,
            "paid": False,
            "pi_id": pi_id,
            "expires": time.time() + _LETTER_SESSION_TTL,
        }

    return {"token": token, "client_secret": client_secret}


@app.route("/letters/session-status/<token>")
def letters_session_status(token):
    """Poll endpoint: returns {paid: bool}.  Frontend polls until paid=true.

    Falls back to a direct Stripe API check if the webhook hasn't arrived yet,
    mirroring the verify_and_mark_paid pattern used by the checkout flow.
    """
    if USE_DB:
        from datetime import datetime, timezone
        row = get_letter_session_status(token)
        logging.info("[poll] token=%s db_row=%s", token, row)
        if not row:
            logging.warning("[poll] token not found: %s", token)
            return {"error": "Session not found"}, 404
        if row["expires_at"] < datetime.now(timezone.utc):
            logging.warning("[poll] token expired: %s", token)
            return {"error": "Session expired"}, 410
        if row["paid"]:
            logging.info("[poll] token already paid in DB: %s", token)
            return {"paid": True}
        # Webhook may not have arrived yet — check Stripe directly
        pi_id = row.get("pi_id", "")
        logging.info("[poll] not yet paid, checking Stripe directly — pi_id=%s", pi_id)
        if pi_id and check_payment_intent_succeeded(pi_id):
            logging.info("[poll] Stripe confirms succeeded — marking paid: %s", token)
            mark_letter_session_paid(token)
            return {"paid": True}
        logging.info("[poll] Stripe says not yet succeeded: %s", token)
        return {"paid": False}
    else:
        entry = _LETTER_SESSIONS.get(token)
        if not entry:
            return {"error": "Session not found"}, 404
        if time.time() > entry.get("expires", 0):
            _LETTER_SESSIONS.pop(token, None)
            return {"error": "Session expired"}, 410
        if entry["paid"]:
            return {"paid": True}
        # Local dev fallback — check Stripe directly
        pi_id = entry.get("pi_id", "")
        if pi_id and check_payment_intent_succeeded(pi_id):
            entry["paid"] = True
            return {"paid": True}
        return {"paid": False}


@app.route("/letters/session-text/<token>")
def letters_session_text(token):
    """Return the pre-generated letter text for a confirmed-paid token.

    Consumes the token on read — one-time use.
    """
    if USE_DB:
        text = consume_letter_session_text(token)
        if text is None:
            # Either not found or not paid yet
            row = get_letter_session_status(token)
            if not row:
                return {"error": "Session not found or already used"}, 404
            return {"error": "Payment not yet confirmed"}, 403
        return {"text": text}
    else:
        entry = _LETTER_SESSIONS.get(token)
        if not entry:
            return {"error": "Session not found or already used"}, 404
        if not entry["paid"]:
            return {"error": "Payment not yet confirmed"}, 403
        text = entry["text"]
        _LETTER_SESSIONS.pop(token, None)
        return {"text": text}


@app.route("/letters/donate", methods=["POST"])
def letters_donate():
    """Create a voluntary donation PaymentIntent. Amount in pence."""
    data = request.get_json()
    try:
        amount = int((data or {}).get("amount", 0))
    except (ValueError, TypeError):
        amount = 0
    if amount < 50 or amount > 10000:
        return {"error": "Amount must be between 50p and £100"}, 400
    try:
        client_secret = create_donation_intent(amount)
    except RuntimeError as e:
        return {"error": str(e)}, 503
    except Exception as e:
        return {"error": str(e)}, 500
    return {"client_secret": client_secret}


@app.route("/asb", methods=["GET"])
def asb():
    return render_template("asb/form.html")


def _collect_case_from_form() -> dict:
    # Mirrors your templates/form.html fields
    case = {
        "notes": request.form.get("notes", "").strip(),
        "num_previous_incidents": int(request.form.get("num_previous_incidents", "0") or 0),
        "vulnerable_tenant": request.form.get("vulnerable_tenant", "").strip(),
        "incident_type": request.form.get("incident_type", "").strip(),
        "has_criminal_history": request.form.get("has_criminal_history", "").strip(),
    }

    # Matrix questions
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

    # In local dev (no DB), Stripe flow is not reliable/meaningful, so block it clearly.
    if not USE_DB:
        abort(400, "Payments disabled in local dev. Deploy to Render (with DATABASE_URL) to test Stripe.")

    success_url = url_for("premium", case_id=case_id, _external=True) + "?session_id={CHECKOUT_SESSION_ID}"
    cancel_url = url_for("premium", case_id=case_id, _external=True)

    session = create_checkout_session(case_id, success_url, cancel_url, metadata={"product": "asb_unlock"},)
    return redirect(session.url, code=303)

@app.route("/noise/pay/<case_id>", methods=["POST"])
def noise_pay(case_id):
    case = _get_noise_case_or_404(case_id)

    if case.get("paid"):
        return redirect(url_for("noise_case_detail", case_id=case_id))

    owner_uid = request.cookies.get(COOKIE_NAME)
    if not owner_uid:
        abort(403, "Owner not identified.")

    if not USE_DB:
        abort(400, "Payments disabled in local dev. Deploy to Render (with DATABASE_URL) to test Stripe.")

    success_url = url_for("noise_case_detail", case_id=case_id, _external=True)
    cancel_url = url_for("noise_case_detail", case_id=case_id, _external=True)

    session = create_checkout_session(
        case_id,
        success_url,
        cancel_url,
        metadata={
            "product": "noise_unlock",
            "owner_uid": owner_uid,
        },
    )

    return redirect(session.url, code=303)


@app.route("/premium/<case_id>", methods=["GET"])
def premium(case_id: str):
    row = _get_case_record(case_id)
    if not row:
        abort(404, "Case not found (maybe expired).")

    if not row["paid"]:
        # Stripe redirects back before the webhook fires — verify directly if
        # we have a session_id from the success URL.
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

    # Verify signature synchronously — must happen before returning 200
    try:
        event = _stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as e:
        logging.error("[webhook] signature verification failed: %s", e)
        return (str(e), 400)

    logging.info("[webhook] signature OK — type=%s id=%s", event["type"], event.get("id", ""))

    # All processing happens in a background thread so 200 goes back to
    # Stripe immediately — prevents Stripe from treating slow DB writes
    # as failures and retrying unnecessarily
    def _process(ev):
        etype = ev["type"]
        logging.info("[webhook] _process started: %s", etype)

        if etype == "payment_intent.succeeded":
            pi = ev["data"]["object"]
            pi_id = pi.get("id", "")
            meta = pi.get("metadata") or {}
            product = meta.get("product", "")
            logging.info("[webhook] PI succeeded — pi_id=%s product=%s metadata=%s",
                         pi_id, product, meta)

            if product == "letter":
                token = meta.get("letter_token", "")
                logging.info("[webhook] letter payment — token=%s USE_DB=%s", token, USE_DB)
                if not token:
                    logging.error("[webhook] letter payment missing letter_token in metadata")
                    return
                if USE_DB:
                    result = mark_letter_session_paid(token)
                    logging.info("[webhook] mark_letter_session_paid(%s) -> %s", token, result)
                else:
                    if token in _LETTER_SESSIONS:
                        _LETTER_SESSIONS[token]["paid"] = True
                        logging.info("[webhook] in-memory session marked paid: %s", token)
                    else:
                        logging.warning("[webhook] token not found in _LETTER_SESSIONS: %s", token)
            else:
                logging.info("[webhook] PI succeeded but product=%r — not a letter, ignoring", product)

        elif etype == "checkout.session.completed":
            session = ev["data"]["object"]
            metadata = session.get("metadata") or {}
            product = metadata.get("product")
            case_id = metadata.get("case_id")
            logging.info("[webhook] checkout completed — product=%s case_id=%s", product, case_id)
            if not USE_DB:
                logging.info("[webhook] no DB in local dev, skipping checkout event")
                return
            from db import mark_paid as _mark_paid, mark_noise_case_paid as _mark_noise_paid
            if (product == "asb_unlock" or product is None) and case_id:
                result = _mark_paid(case_id)
                logging.info("[webhook] mark_paid(%s) -> %s", case_id, result)
            elif product == "noise_unlock" and case_id:
                result = _mark_noise_paid(case_id)
                logging.info("[webhook] mark_noise_case_paid(%s) -> %s", case_id, result)
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
    return render_template("Cookie Policy \u2014 ASB Guide.html")


@app.route("/health")
def health():
    return {
        "status": "ok",
        "use_db": USE_DB,
        "environment": "render" if os.environ.get("RENDER") else "local",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# -------------------------
# Tool #2: Noise Diary (MVP)
# -------------------------

@app.route("/noise", methods=["GET"])
def noise_index():
    """List noise diary cases."""
    owner_uid = get_owner_uid()  # <-- ALWAYS defined (cookie read or new UID)

    if USE_DB:
        # Retention cleanup (free tier)
        delete_expired_noise_cases(RETENTION_DAYS)

        cases = list_noise_cases(owner_uid)
    else:
        # local: show only this user's cases (not everyone’s)
        cases = [
            c for c in NOISE_CASE_STORE.values()
            if c.get("owner_uid") == owner_uid
        ]
        cases = sorted(
            cases,
            key=lambda c: c.get("created_at", ""),
            reverse=True
        )

    resp = make_response(
        render_template("noise/index.html", cases=cases, use_db=USE_DB)
    )
    return attach_owner_cookie(resp, owner_uid)



@app.route("/noise/new", methods=["GET", "POST"])
def noise_new():
    """Create a new noise diary case."""
    if request.method == "GET":
        return render_template("noise/case_new.html")
    
    owner_uid = request.cookies.get(COOKIE_NAME)
    if not owner_uid:
       abort(400, "Device ID missing.")

    existing_case_id = None
    if USE_DB:
        existing_case_id = get_active_noise_case_for_owner(owner_uid)
    if existing_case_id:
        flash("You already have an active diary.")
        return redirect(url_for("noise_case_detail", case_id=existing_case_id))

    title = request.form.get("title", "").strip()
    address_text = request.form.get("address_text", "").strip()
    start_date = request.form.get("start_date", "").strip()

    if not title:
        abort(400, "Title is required.")
    if not start_date:
        abort(400, "Start date is required.")

    case_id = str(uuid.uuid4())

    case = {
        "id": case_id,
        "title": title,
        "address_text": address_text,
        "start_date": start_date,
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ref_code": _gen_ref_code(),
    }

    existing_count = 0

    if USE_DB:
        existing_count = count_noise_cases_for_owner(owner_uid)

    if existing_count >= FREE_MAX_DIARIES:
        abort(403, "Free tier allows 1 diary per device.")

    if USE_DB:
        create_noise_case(case_id, owner_uid, case)
        resp = make_response(redirect(url_for("noise_case_detail", case_id=case_id)))
        return attach_owner_cookie(resp, owner_uid)
    else:
        case["entries"] = []
        case["owner_uid"] = owner_uid
        NOISE_CASE_STORE[case_id] = case

    return redirect(url_for("noise_case_detail", case_id=case_id))


def _get_noise_case_or_404(case_id: str):
    if USE_DB:
        owner_uid = request.cookies.get(COOKIE_NAME)
        if not owner_uid:
            abort(404, "Noise diary case not found.")
        row = get_noise_case_for_owner(case_id, owner_uid)

    else:
        row = NOISE_CASE_STORE.get(case_id)
    if not row:
        abort(404, "Noise diary case not found.")
    return row


def _get_noise_entry_or_404(case_id: str, entry_id: str):
    if USE_DB:
        entry = get_noise_entry(case_id, entry_id)
    else:
        entry = NOISE_ENTRY_STORE.get(entry_id)
    if not entry:
        abort(404, "Noise diary entry not found.")
    return entry





@app.route("/noise/<case_id>", methods=["GET"])
def noise_case_detail(case_id: str):
    """Case dashboard + entries list."""
    case = _get_noise_case_or_404(case_id)

    if USE_DB:
        entries = list_noise_entries(case_id)
    else:
        entries = sorted(case.get("entries", []), key=lambda e: e.get("occurred_at", ""), reverse=True)

    return render_template("noise/case_detail.html", case=case, entries=entries)


@app.route("/noise/<case_id>/entries/new", methods=["GET", "POST"])
def noise_entry_new(case_id: str):
    """Add an entry to a diary case."""
    case = _get_noise_case_or_404(case_id)

    # prevent edits if submitted/closed (simple rule)
    if case.get("status") in ("submitted", "closed"):
        abort(400, "This diary is locked and can’t be edited.")

    if request.method == "GET":
        now_local = datetime.now().strftime("%Y-%m-%dT%H:%M")
        return render_template("noise/entry_form.html", case=case, entry=None, default_dt=now_local)

    occurred_at = request.form.get("occurred_at", "").strip()
    noise_type = request.form.get("noise_type", "").strip()
    duration_minutes = request.form.get("duration_minutes", "").strip()
    volume_level = request.form.get("volume_level", "").strip()
    impact_level = request.form.get("impact_level", "").strip()
    location = request.form.get("location", "").strip()
    notes = request.form.get("notes", "").strip()

    if not occurred_at:
        abort(400, "Date/time is required.")
    if not noise_type:
        abort(400, "Noise type is required.")
    if not notes:
        abort(400, "Notes are required (what happened and how it affected you).")

    # Enforce note length server-side
    if len(notes) > MAX_NOTE_CHARS:
        abort(400, f"Notes must be {MAX_NOTE_CHARS} characters or fewer.")

    # Enforce entry cap BEFORE writing anything
    cap = noise_entry_cap(case)

    if USE_DB:
        entry_count = count_noise_entries_for_case(case_id)
    else:
        # local store: count current entries already saved
        entry_count = len(NOISE_CASE_STORE.get(case_id, {}).get("entries", []))

    if entry_count >= cap:
        abort(403, f"Entry limit reached ({cap}).")

    entry_id = str(uuid.uuid4())

    def _int_or_none(x):
        x = (x or "").strip()
        if x == "":
            return None
        try:
            return int(x)
        except ValueError:
            return None

    entry = {
        "id": entry_id,
        "case_id": case_id,
        "occurred_at": occurred_at,
        "noise_type": noise_type,
        "duration_minutes": _int_or_none(duration_minutes),
        "volume_level": _int_or_none(volume_level),
        "impact_level": _int_or_none(impact_level),
        "location": location,
        "notes": notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if USE_DB:
        create_noise_entry(entry_id, case_id, entry)
        touch_noise_case_activity(case_id)
    else:
        NOISE_ENTRY_STORE[entry_id] = entry
        NOISE_CASE_STORE[case_id]["entries"].append(entry)

    return redirect(url_for("noise_case_detail", case_id=case_id))

@app.route("/noise/<case_id>/entries/<entry_id>/edit", methods=["GET", "POST"])
def noise_entry_edit(case_id: str, entry_id: str):
    case = _get_noise_case_or_404(case_id)

    if case.get("status") in ("submitted", "closed"):
        abort(400, "This diary is locked and can’t be edited.")

    entry = _get_noise_entry_or_404(case_id, entry_id)

    if request.method == "GET":
        return render_template("noise/entry_form.html", case=case, entry=entry, default_dt=None)

    occurred_at = request.form.get("occurred_at", "").strip()
    noise_type = request.form.get("noise_type", "").strip()
    duration_minutes = request.form.get("duration_minutes", "").strip()
    volume_level = request.form.get("volume_level", "").strip()
    impact_level = request.form.get("impact_level", "").strip()
    location = request.form.get("location", "").strip()
    notes = request.form.get("notes", "").strip()

    if not occurred_at:
        abort(400, "Date/time is required.")
    if not noise_type:
        abort(400, "Noise type is required.")
    if not notes:
        abort(400, "Notes are required.")

    def _int_or_none(x):
        x = (x or "").strip()
        if x == "":
            return None
        try:
            return int(x)
        except ValueError:
            return None

    updates = {
        "occurred_at": occurred_at,
        "noise_type": noise_type,
        "duration_minutes": _int_or_none(duration_minutes),
        "volume_level": _int_or_none(volume_level),
        "impact_level": _int_or_none(impact_level),
        "location": location,
        "notes": notes,
    }

    if USE_DB:
        update_noise_entry(case_id, entry_id, updates)
        touch_noise_case_activity(case_id)
    else:
        # update local store
        NOISE_ENTRY_STORE[entry_id].update(updates)
        # also update embedded list in case
        for i, e in enumerate(NOISE_CASE_STORE[case_id]["entries"]):
            if e["id"] == entry_id:
                NOISE_CASE_STORE[case_id]["entries"][i].update(updates)
                break

    return redirect(url_for("noise_case_detail", case_id=case_id))


@app.route("/noise/<case_id>/entries/<entry_id>/delete", methods=["POST"])
def noise_entry_delete(case_id: str, entry_id: str):
    case = _get_noise_case_or_404(case_id)

    if case.get("status") in ("submitted", "closed"):
        abort(400, "This diary is locked and can’t be edited.")

    # ensure exists
    _ = _get_noise_entry_or_404(case_id, entry_id)

    if USE_DB:
        delete_noise_entry(case_id, entry_id)
        touch_noise_case_activity(case_id)
    else:
        NOISE_ENTRY_STORE.pop(entry_id, None)
        NOISE_CASE_STORE[case_id]["entries"] = [
            e for e in NOISE_CASE_STORE[case_id]["entries"] if e["id"] != entry_id
        ]

    return redirect(url_for("noise_case_detail", case_id=case_id))

@app.route("/noise/<case_id>/submit", methods=["POST"])
def noise_case_submit(case_id: str):
    case = _get_noise_case_or_404(case_id)

    # already locked?
    if case.get("status") in ("submitted", "closed"):
        return redirect(url_for("noise_case_detail", case_id=case_id))

    # optional: prevent empty submission
    if USE_DB:
        entries = list_noise_entries(case_id)
    else:
        entries = case.get("entries", [])

    if not entries:
        abort(400, "You can’t submit an empty diary.")

    updates = {
        "status": "submitted",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }

    if USE_DB:
        update_noise_case(case_id, updates)
    else:
        NOISE_CASE_STORE[case_id].update(updates)

    return redirect(url_for("noise_case_detail", case_id=case_id))


@app.route("/noise/<case_id>/delete", methods=["POST"])
def noise_case_delete(case_id: str):
    owner_uid = get_owner_uid()
    _get_noise_case_or_404(case_id)  # validates ownership

    if USE_DB:
        delete_noise_case(case_id, owner_uid)
    else:
        NOISE_CASE_STORE.pop(case_id, None)
        to_remove = [k for k, v in NOISE_ENTRY_STORE.items() if v.get("case_id") == case_id]
        for k in to_remove:
            NOISE_ENTRY_STORE.pop(k, None)

    return redirect(url_for("noise_index"))


@app.route("/noise/<case_id>/export.csv", methods=["GET"])
def noise_export_csv(case_id: str):
    case = _get_noise_case_or_404(case_id)
    if USE_DB:
        entries = list_noise_entries(case_id)
    else:
        entries = sorted(case.get("entries", []), key=lambda e: e.get("occurred_at", ""))

    # Build CSV manually (simple, dependency-free)
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["CASE DETAILS"])
    writer.writerow(["case_id", case.get("id", "")])
    writer.writerow(["title", case.get("title", "")])
    writer.writerow(["address_text", case.get("address_text", "")])
    writer.writerow(["start_date", case.get("start_date", "")])
    writer.writerow(["status", case.get("status", "")])
    writer.writerow(["submitted_at", case.get("submitted_at", "")])
    writer.writerow([])
    writer.writerow(["ENTRIES"])
    writer.writerow([
        "occurred_at", "noise_type", "duration_minutes", "volume_level", "impact_level", "location", "notes"
    ])
    for e in entries:
        writer.writerow([
            e.get("occurred_at", ""),
            e.get("noise_type", ""),
            e.get("duration_minutes", ""),
            e.get("volume_level", ""),
            e.get("impact_level", ""),
            e.get("location", ""),
            e.get("notes", ""),
        ])

    csv_data = output.getvalue()
    filename = f"noise-diary-{case_id}.csv"

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.route("/noise/<case_id>/export.pdf", methods=["GET"])
def noise_export_pdf(case_id: str):
    from fpdf import FPDF

    case = _get_noise_case_or_404(case_id)
    if USE_DB:
        entries = list_noise_entries(case_id)
    else:
        entries = sorted(case.get("entries", []), key=lambda e: e.get("occurred_at", ""))

    pdf = FPDF()
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    # ---- Header ----
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Noise Diary", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 7, f"Exported: {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    # ---- Case details ----
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Case Details", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(200, 200, 200)
    pdf.line(15, pdf.get_y(), pdf.w - 15, pdf.get_y())
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 10)
    details = [
        ("Title", case.get("title", "")),
        ("Address", case.get("address_text", "") or "—"),
        ("Start date", case.get("start_date", "")),
        ("Status", case.get("status", "open").capitalize()),
        ("Submitted", case.get("submitted_at", "") or "—"),
    ]
    for label, value in details:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(38, 7, label + ":")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 7, str(value), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # ---- Entries ----
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, f"Entries ({len(entries)})", new_x="LMARGIN", new_y="NEXT")
    pdf.line(15, pdf.get_y(), pdf.w - 15, pdf.get_y())
    pdf.ln(3)

    if not entries:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 7, "No entries recorded.", new_x="LMARGIN", new_y="NEXT")
    else:
        for i, e in enumerate(entries, 1):
            # Entry heading
            pdf.set_fill_color(245, 245, 245)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 7, f"  {i}.  {e.get('occurred_at', '')}  —  {e.get('noise_type', '')}",
                     fill=True, new_x="LMARGIN", new_y="NEXT")

            pdf.set_font("Helvetica", "", 9)
            meta_parts = []
            if e.get("location"):
                meta_parts.append(f"Location: {e['location']}")
            if e.get("duration_minutes"):
                meta_parts.append(f"Duration: {e['duration_minutes']} mins")
            if e.get("volume_level"):
                meta_parts.append(f"Volume: {e['volume_level']}/5")
            if e.get("impact_level"):
                meta_parts.append(f"Impact: {e['impact_level']}/5")
            if meta_parts:
                pdf.set_text_color(100, 100, 100)
                pdf.cell(0, 6, "  " + "   |   ".join(meta_parts), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)

            if e.get("notes"):
                pdf.set_font("Helvetica", "", 9)
                pdf.set_x(15)
                pdf.multi_cell(0, 5, "  " + e["notes"], new_x="LMARGIN", new_y="NEXT")

            pdf.ln(3)

    filename = f"noise-diary-{case_id}.pdf"
    pdf_bytes = bytes(pdf.output())
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.route("/noise/recover", methods=["GET", "POST"])
def noise_recover():
    if request.method == "GET":
        return render_template("noise/recover.html")

    raw = request.form.get("ref_code", "").strip().upper().replace("-", "").replace(" ", "")
    if not raw:
        flash("Please enter a reference code.")
        return render_template("noise/recover.html")

    if USE_DB:
        case, owner_uid = get_noise_case_by_ref_code(raw)
        if not case:
            flash("No diary found with that reference code. Please check and try again.")
            return render_template("noise/recover.html")
        resp = make_response(redirect(url_for("noise_case_detail", case_id=case["id"])))
    else:
        case = next((c for c in NOISE_CASE_STORE.values() if c.get("ref_code") == raw), None)
        if not case:
            flash("No diary found with that reference code. Please check and try again.")
            return render_template("noise/recover.html")
        owner_uid = case.get("owner_uid", str(uuid.uuid4()))
        resp = make_response(redirect(url_for("noise_case_detail", case_id=case["id"])))

    resp.set_cookie(
        COOKIE_NAME,
        owner_uid,
        max_age=60 * 60 * 24 * 365 * 2,
        httponly=True,
        samesite="Lax",
        secure=bool(os.environ.get("RENDER")),
    )
    return resp


if __name__ == "__main__":
    app.run(debug=True)

