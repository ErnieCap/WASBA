"""
knowledge/evaluate.py
Retrieval evaluation — hit-rate-at-k scoring.

Usage (PowerShell):
    python knowledge/evaluate.py --db postgresql://... --questions knowledge/eval/questions.jsonl

Scores:
  Hit-rate-at-k: fraction of questions for which at least one of the top-k
  retrieved chunks comes from a document tagged with an expected tag.
  Reported for each k in EVAL_K_VALUES (default: 1, 3, 5, 10).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

from config import EVAL_K_VALUES, OLLAMA_EMBED_MODEL
from embed import OllamaEmbedProvider, retrieve


def load_questions(path: Path) -> List[dict]:
    questions = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return questions


def evaluate(
    questions: List[dict],
    db: str,
    model: str = OLLAMA_EMBED_MODEL,
    k_values: List[int] = None,
) -> dict:
    if k_values is None:
        k_values = EVAL_K_VALUES

    provider = OllamaEmbedProvider(model=model)
    max_k = max(k_values)

    hits_at_k = {k: 0 for k in k_values}
    results = []

    for q in questions:
        qid = q["id"]
        question = q["question"]
        expected_tags = set(q.get("expected_tags", []))
        jurisdiction = q.get("jurisdiction")

        try:
            rows = retrieve(
                query=question,
                provider=provider,
                conn_string=db,
                k=max_k,
                jurisdiction_filter=jurisdiction if jurisdiction != "UK-wide" else None,
            )
        except Exception as exc:
            print(f"  ERROR {qid}: {exc}")
            results.append({"id": qid, "error": str(exc)})
            continue

        # Check hit at each k
        q_hits = {}
        for k in k_values:
            top_k = rows[:k]
            hit = any(
                bool(set(json.loads(r.get("topic_tags", "[]"))) & expected_tags)
                for r in top_k
            )
            q_hits[f"hit@{k}"] = hit
            if hit:
                hits_at_k[k] += 1

        results.append({
            "id": qid,
            "question": question[:80],
            **q_hits,
            "top_source": rows[0]["source_file"] if rows else None,
            "top_similarity": round(float(rows[0]["similarity"]), 3) if rows else None,
        })
        print(f"  {qid}  " + "  ".join(
            f"@{k}={'Y' if q_hits[f'hit@{k}'] else 'N'}" for k in k_values
        ))

    n = len(questions)
    summary = {
        f"hit_rate@{k}": round(hits_at_k[k] / n, 3) if n else 0.0
        for k in k_values
    }
    return {"summary": summary, "results": results, "n_questions": n}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate retrieval quality using held-out questions."
    )
    parser.add_argument("--db", required=True, help="PostgreSQL connection string")
    parser.add_argument(
        "--questions", type=Path,
        default=Path(__file__).parent / "eval" / "questions.jsonl",
        help="Path to JSONL questions file",
    )
    parser.add_argument(
        "--model", default=OLLAMA_EMBED_MODEL,
        help=f"Ollama embedding model (default: {OLLAMA_EMBED_MODEL})",
    )
    parser.add_argument(
        "--out", type=Path,
        help="Optional path to write JSON results",
    )
    args = parser.parse_args()

    if not args.questions.exists():
        print(f"Questions file not found: {args.questions}")
        sys.exit(1)

    questions = load_questions(args.questions)
    print(f"Evaluating {len(questions)} questions…")

    report = evaluate(questions, db=args.db, model=args.model)

    print("\n── Hit-rate summary ──────────────────────────────")
    for metric, score in report["summary"].items():
        print(f"  {metric}: {score:.1%}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nFull results written to {args.out}")


if __name__ == "__main__":
    main()
