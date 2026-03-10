import os
from typing import Optional, Dict, Any

import psycopg2

from psycopg2.extras import RealDictCursor, Json




def get_conn():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(dsn)


def init_db() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    case_data JSONB NOT NULL,
                    free_result JSONB NOT NULL,
                    paid BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            # Noise Diary tables
            cur.execute ( 
                """               
                CREATE TABLE IF NOT EXISTS noise_diary_cases (
                   id UUID PRIMARY KEY,
                   title TEXT NOT NULL,
                   address_text TEXT,
                   start_date DATE NOT NULL,
                   status TEXT NOT NULL DEFAULT 'open',
                   submitted_at TIMESTAMPTZ,
                   created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
               );
               """
            )
                                
            cur.execute("ALTER TABLE noise_diary_cases ADD COLUMN IF NOT EXISTS owner_uid TEXT;")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_noise_cases_owner_uid ON noise_diary_cases(owner_uid);")
            cur.execute("ALTER TABLE noise_diary_cases ADD COLUMN IF NOT EXISTS paid BOOLEAN NOT NULL DEFAULT FALSE;")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_noise_cases_paid ON noise_diary_cases(paid);")
            cur.execute("ALTER TABLE noise_diary_cases ADD COLUMN IF NOT EXISTS last_active_at TIMESTAMPTZ;")
            cur.execute("ALTER TABLE noise_diary_cases ADD COLUMN IF NOT EXISTS ref_code TEXT;")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_noise_cases_ref_code ON noise_diary_cases(ref_code) WHERE ref_code IS NOT NULL;")
       

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS noise_diary_entries (
                    id UUID PRIMARY KEY,
                    case_id UUID NOT NULL REFERENCES noise_diary_cases(id) ON DELETE CASCADE,
                    occurred_at TIMESTAMPTZ NOT NULL,
                    noise_type TEXT NOT NULL,
                    duration_minutes INTEGER,
                    volume_level SMALLINT,
                    impact_level SMALLINT,
                    location TEXT,
                    notes TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            cur.execute("CREATE INDEX IF NOT EXISTS idx_noise_cases_created ON noise_diary_cases(created_at DESC);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_noise_entries_case_time ON noise_diary_entries(case_id, occurred_at DESC);")
            cur.execute("ALTER TABLE noise_diary_cases ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ;")

        conn.commit()


def create_case(case_id: str, case_data: Dict[str, Any], free_result: Dict[str, Any]) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cases (case_id, case_data, free_result, paid)
                VALUES (%s, %s, %s, FALSE)
                """,
                (case_id, Json(case_data), Json(free_result)),
            )
        conn.commit()


def get_case(case_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT case_id, case_data, free_result, paid FROM cases WHERE case_id=%s",
                (case_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def mark_paid(case_id: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE cases SET paid=TRUE WHERE case_id=%s", (case_id,))
            updated = cur.rowcount
        conn.commit()
    return updated == 1



from datetime import datetime, timezone

def _parse_dt(dt_str: str) -> datetime:
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        # Treat client-entered local time as UTC for consistency
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def create_noise_case(case_id: str, owner_uid: str, case: dict, paid: bool = False):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO noise_diary_cases (id, owner_uid, title, address_text, start_date, status, paid, ref_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                case_id,
                owner_uid,
                case["title"],
                case.get("address_text"),
                case["start_date"],
                case.get("status", "open"),
                paid,
                case.get("ref_code"),
            ))
        conn.commit()



def list_noise_cases(owner_uid: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id::text, title, address_text, start_date::text, status,
                       submitted_at::text, created_at::text, paid, ref_code
                FROM noise_diary_cases
                WHERE owner_uid = %s
                ORDER BY created_at DESC
                LIMIT 200
            """, (owner_uid,))
            rows = cur.fetchall()

    return [
        {
            "id": r[0],
            "title": r[1],
            "address_text": r[2],
            "start_date": r[3],
            "status": r[4] or "open",
            "submitted_at": r[5],
            "created_at": r[6],
            "paid": bool(r[7]),
            "ref_code": r[8],
        }
        for r in rows
    ]
    



def get_noise_case(case_id: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id::text, title, address_text, start_date::text, status,
                       submitted_at::text, created_at::text
                FROM noise_diary_cases
                WHERE id = %s
            """, (case_id,))
            r = cur.fetchone()
    if not r:
        return None
    return {
        "id": r[0],
        "title": r[1],
        "address_text": r[2],
        "start_date": r[3],
        "status": r[4] or "open",
        "submitted_at": r[5],      # <-- new
        "created_at": r[6],
    }


def create_noise_entry(entry_id: str, case_id: str, entry: dict):
    occurred_at = entry["occurred_at"]
    # If occurred_at is datetime-local string, parse it
    # If you want zero deps: datetime.fromisoformat(occurred_at) and assume UTC if naive.
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO noise_diary_entries (
                    id, case_id, occurred_at, noise_type, duration_minutes,
                    volume_level, impact_level, location, notes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                entry_id, case_id,
                _parse_dt(occurred_at),
                entry["noise_type"],
                entry.get("duration_minutes"),
                entry.get("volume_level"),
                entry.get("impact_level"),
                entry.get("location"),
                entry["notes"],
            ))
        conn.commit()


def count_noise_cases_for_owner(owner_uid: str) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) 
                FROM noise_diary_cases
                WHERE owner_uid = %s
            """, (owner_uid,))
            return cur.fetchone()[0]
        
def count_noise_entries_for_case(case_id: str) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) 
                FROM noise_diary_entries
                WHERE case_id = %s
            """, (case_id,))
            return cur.fetchone()[0]        
      

def list_noise_entries(case_id: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id::text, case_id::text,
                    occurred_at::text,
                    noise_type, duration_minutes, volume_level, impact_level,
                    location, notes, created_at::text
                FROM noise_diary_entries
                WHERE case_id = %s
                ORDER BY occurred_at DESC
                LIMIT 2000
            """, (case_id,))
            rows = cur.fetchall()

    return [
        {
            "id": r[0],
            "case_id": r[1],
            "occurred_at": r[2],
            "noise_type": r[3],
            "duration_minutes": r[4],
            "volume_level": r[5],
            "impact_level": r[6],
            "location": r[7],
            "notes": r[8],
            "created_at": r[9],
        }
        for r in rows
    ]

def mark_noise_case_paid(case_id: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE noise_diary_cases SET paid=TRUE WHERE id=%s",
                (case_id,)
            )
            updated = cur.rowcount
        conn.commit()
    return updated == 1


# stops people guessing a uuid

def get_noise_case_for_owner(case_id: str, owner_uid: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id::text, title, address_text, start_date::text, status,
                       submitted_at::text, created_at::text, paid, last_active_at::text, ref_code
                FROM noise_diary_cases
                WHERE id = %s AND owner_uid = %s
            """, (case_id, owner_uid))
            r = cur.fetchone()
    if not r:
        return None
    return {
        "id": r[0],
        "title": r[1],
        "address_text": r[2],
        "start_date": r[3],
        "status": r[4] or "open",
        "submitted_at": r[5],
        "created_at": r[6],
        "paid": bool(r[7]),
        "last_active_at": r[8],
        "ref_code": r[9],
    }

def get_active_noise_case_for_owner(owner_uid: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id::text
                FROM noise_diary_cases
                WHERE owner_uid = %s
                AND status NOT IN ('submitted', 'closed')
                LIMIT 1
            """, (owner_uid,))
            r = cur.fetchone()
    if not r:
        return None
    return r[0]


def get_noise_entry(case_id: str, entry_id: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id::text, case_id::text,
                    occurred_at::text,
                    noise_type, duration_minutes, volume_level, impact_level,
                    location, notes, created_at::text
                FROM noise_diary_entries
                WHERE case_id = %s AND id = %s
            """, (case_id, entry_id))
            r = cur.fetchone()
    if not r:
        return None
    return {
        "id": r[0],
        "case_id": r[1],
        "occurred_at": r[2],
        "noise_type": r[3],
        "duration_minutes": r[4],
        "volume_level": r[5],
        "impact_level": r[6],
        "location": r[7],
        "notes": r[8],
        "created_at": r[9],
    }

def update_noise_entry(case_id: str, entry_id: str, updates: dict):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE noise_diary_entries
                SET
                    occurred_at = %s,
                    noise_type = %s,
                    duration_minutes = %s,
                    volume_level = %s,
                    impact_level = %s,
                    location = %s,
                    notes = %s
                WHERE case_id = %s AND id = %s
            """, (
                _parse_dt(updates["occurred_at"]),
                updates["noise_type"],
                updates.get("duration_minutes"),
                updates.get("volume_level"),
                updates.get("impact_level"),
                updates.get("location"),
                updates["notes"],
                case_id, entry_id
            ))
        conn.commit()

def delete_noise_entry(case_id: str, entry_id: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM noise_diary_entries
                WHERE case_id = %s AND id = %s
            """, (case_id, entry_id))
        conn.commit()

def delete_expired_noise_cases(retention_days: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM noise_diary_cases
                WHERE paid = FALSE
                AND COALESCE(last_active_at, created_at) < NOW() - INTERVAL '%s days'
            """ % retention_days)
        conn.commit()


def touch_noise_case_activity(case_id: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE noise_diary_cases SET last_active_at = NOW() WHERE id = %s",
                (case_id,)
            )
        conn.commit()


def get_noise_case_by_ref_code(ref_code: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id::text, owner_uid, title, address_text, start_date::text, status,
                       submitted_at::text, created_at::text, paid, last_active_at::text, ref_code
                FROM noise_diary_cases
                WHERE ref_code = %s
            """, (ref_code,))
            r = cur.fetchone()
    if not r:
        return None, None
    case = {
        "id": r[0],
        "title": r[2],
        "address_text": r[3],
        "start_date": r[4],
        "status": r[5] or "open",
        "submitted_at": r[6],
        "created_at": r[7],
        "paid": bool(r[8]),
        "last_active_at": r[9],
        "ref_code": r[10],
    }
    return case, r[1]  # case, owner_uid

def update_noise_case(case_id: str, updates: dict) -> bool:
    allowed = {"title", "address_text", "start_date", "status", "submitted_at"}
    safe = {k: v for k, v in updates.items() if k in allowed}
    if not safe:
        return False

    fields = ", ".join([f"{k} = %s" for k in safe.keys()])
    values = list(safe.values()) + [case_id]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE noise_diary_cases SET {fields} WHERE id = %s",
                values
            )
            updated = cur.rowcount
        conn.commit()

    return updated == 1

    
      
