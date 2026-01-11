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
