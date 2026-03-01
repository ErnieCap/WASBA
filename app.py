import os
import uuid

print("RUNNING APP.PY FROM:", os.path.abspath(__file__))

from flask import Flask, render_template, request, redirect, url_for, abort, Response, make_response
from werkzeug.middleware.proxy_fix import ProxyFix

from service import assess_case_free, assess_case_premium
from payments import create_checkout_session, handle_stripe_webhook

from datetime import datetime, timezone

# DB imports (Postgres)
from db import (
    count_noise_cases_for_owner, count_noise_entries_for_case,
    init_db,
    create_case, get_case,
    create_noise_case, list_noise_cases, get_noise_case,
    create_noise_entry, list_noise_entries, get_noise_entry,
    update_noise_entry, delete_noise_entry, get_noise_case_for_owner, delete_expired_noise_cases, get_active_noise_case_for_owner,
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
            secure=False,  # change to True in production HTTPS
        )
    return resp


@app.route("/", methods=["GET"])
def landing():
    return render_template("landing.html")

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

    success_url = url_for("premium", case_id=case_id, _external=True)
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
        
    

    return redirect(session.url, code=303)


@app.route("/premium/<case_id>", methods=["GET"])
def premium(case_id: str):
    row = _get_case_record(case_id)
    if not row:
        abort(404, "Case not found (maybe expired).")

    if not row["paid"]:
        return render_template("asb/result.html", result=row["free_result"], case_id=case_id, paid=False)

    premium_result = assess_case_premium(row["case_data"])
    return render_template("asb/result.html", result=premium_result, case_id=case_id, paid=True)


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    # In local dev without DB, ignore webhooks.
    if not USE_DB:
        return ("IGNORED (local dev without DB)", 200)

    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    ok = handle_stripe_webhook(payload, sig_header)
    return ("OK" if ok else "IGNORED", 200)


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
    if USE_DB:
        # Retention cleanup (free tier)
        delete_expired_noise_cases(RETENTION_DAYS)

        owner_uid = request.cookies.get(COOKIE_NAME)
        if not owner_uid:
            cases = []  # no cookie yet → show empty list rather than everyone’s diaries
        else:
            cases = list_noise_cases(owner_uid)
    else:
        # local: sort by created_at (string ISO) if present
        cases = sorted(
            NOISE_CASE_STORE.values(),
            key=lambda c: c.get("created_at", ""),
            reverse=True
        )

    return render_template("noise/index.html", cases=cases, use_db=USE_DB)



@app.route("/noise/new", methods=["GET", "POST"])
def noise_new():
    """Create a new noise diary case."""
    if request.method == "GET":
        return render_template("noise/case_new.html")
    
    owner_uid = request.cookies.get(COOKIE_NAME)
    if not owner_uid:
       abort(400, "Device ID missing.")

    if USE_DB:
        existing_case_id = get_active_noise_case_for_owner(owner_uid)
    if existing_case_id:
        Flask("You already have an active diary.")
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
    }

    if USE_DB:
        owner_uid = get_owner_uid()
        existing_count = count_noise_cases_for_owner(owner_uid)

    if existing_count >= FREE_MAX_DIARIES:
        abort(403, "Free tier allows 1 diary per device.")

        create_noise_case(case_id, owner_uid, case)

        resp = make_response(redirect(url_for("noise_case_detail", case_id=case_id)))
        return attach_owner_cookie(resp, owner_uid)

    else:
        case["entries"] = []
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
        # OPTIONAL but recommended: touch last_active_at here (cheap, helps 60-day retention)
        # touch_noise_case_activity(case_id)
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




if __name__ == "__main__":
    app.run(debug=True)

