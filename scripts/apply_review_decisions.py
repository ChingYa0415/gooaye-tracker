#!/usr/bin/env python3
"""Apply completed mention review decisions back to mentions.csv."""

from __future__ import annotations

import argparse
import csv
import pathlib


ALLOWED_REVIEW_DECISIONS = {"approved", "rejected", "needs_context", "pending"}
ALLOWED_STANCES = {"bullish", "bearish", "neutral", "watch", "past_review", "unclear"}
ALLOWED_CONVICTIONS = {"low", "medium", "high"}
ALLOWED_TIME_HORIZONS = {"short", "medium", "long", "unclear"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply non-blank review_decision rows to mentions.csv."
    )
    parser.add_argument(
        "--mentions-csv",
        default="data/processed/mentions.csv",
        help="Mention table to update.",
    )
    parser.add_argument(
        "--review-csv",
        default="reports/pending_mentions_review.csv",
        help="Completed review queue CSV.",
    )
    parser.add_argument(
        "--output",
        default="data/processed/mentions.csv",
        help="Updated mentions CSV path.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report changes without writing output.",
    )
    return parser.parse_args()


def load_csv(path: pathlib.Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def validate_choice(value: str, allowed: set[str], field: str, mention_id: str) -> None:
    if value and value not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValueError(f"{mention_id}: invalid {field}={value!r}; allowed: {allowed_values}")


def completed_review_rows(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    reviews: dict[str, dict[str, str]] = {}
    for row in rows:
        mention_id = row["mention_id"]
        decision = row.get("review_decision", "").strip()
        if not decision:
            continue
        validate_choice(decision, ALLOWED_REVIEW_DECISIONS, "review_decision", mention_id)
        validate_choice(row.get("corrected_stance", "").strip(), ALLOWED_STANCES, "corrected_stance", mention_id)
        validate_choice(
            row.get("corrected_conviction", "").strip(),
            ALLOWED_CONVICTIONS,
            "corrected_conviction",
            mention_id,
        )
        validate_choice(
            row.get("corrected_time_horizon", "").strip(),
            ALLOWED_TIME_HORIZONS,
            "corrected_time_horizon",
            mention_id,
        )
        reviews[mention_id] = row
    return reviews


def append_note(existing: str, addition: str) -> str:
    addition = addition.strip()
    if not addition:
        return existing
    if not existing:
        return addition
    return f"{existing}; review: {addition}"


def apply_reviews(
    mentions: list[dict[str, str]],
    reviews: dict[str, dict[str, str]],
) -> tuple[list[dict[str, str]], int]:
    applied = 0
    updated_rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for mention in mentions:
        mention_id = mention["mention_id"]
        review = reviews.get(mention_id)
        if review is None:
            updated_rows.append(mention)
            continue

        updated = dict(mention)
        updated["review_status"] = review["review_decision"].strip()
        for review_field, mention_field in [
            ("corrected_stance", "stance"),
            ("corrected_conviction", "conviction"),
            ("corrected_time_horizon", "time_horizon"),
            ("corrected_evidence_text", "evidence_text"),
        ]:
            value = review.get(review_field, "").strip()
            if value:
                updated[mention_field] = value
        updated["reviewer_note"] = append_note(
            updated.get("reviewer_note", ""),
            review.get("review_comment", ""),
        )

        updated_rows.append(updated)
        seen.add(mention_id)
        applied += 1

    missing = sorted(set(reviews) - seen)
    if missing:
        raise ValueError(f"Review rows reference unknown mention_id values: {', '.join(missing)}")
    return updated_rows, applied


def write_csv(path: pathlib.Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    fieldnames, mentions = load_csv(pathlib.Path(args.mentions_csv))
    _, review_rows = load_csv(pathlib.Path(args.review_csv))
    reviews = completed_review_rows(review_rows)
    updated_rows, applied = apply_reviews(mentions, reviews)

    if args.dry_run:
        print(f"Validated {len(reviews)} completed review rows; would apply {applied} updates.")
        return 0

    write_csv(pathlib.Path(args.output), fieldnames, updated_rows)
    print(f"Applied {applied} review decisions to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
