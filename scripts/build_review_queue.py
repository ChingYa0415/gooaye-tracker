#!/usr/bin/env python3
"""Build a CSV queue for manual review of pending mentions."""

from __future__ import annotations

import argparse
import csv
import difflib
import pathlib
import re


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a manual review queue for mentions.")
    parser.add_argument(
        "--mentions-csv",
        default="data/processed/mentions.csv",
        help="Mention table to read.",
    )
    parser.add_argument(
        "--episodes-csv",
        default="data/processed/episodes.csv",
        help="Episode metadata table to read.",
    )
    parser.add_argument(
        "--transcript-dir",
        default="data/raw/transcripts",
        help="Directory containing local combined transcripts.",
    )
    parser.add_argument(
        "--output",
        default="reports/pending_mentions_review.csv",
        help="Review queue CSV to write.",
    )
    parser.add_argument(
        "--status",
        default="pending",
        help="Mention review_status to include.",
    )
    parser.add_argument(
        "--context-chars",
        type=int,
        default=220,
        help="Maximum characters of transcript context to include.",
    )
    return parser.parse_args()


def load_csv(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize_text(value: str) -> str:
    return re.sub(r"\W+", "", value.casefold())


def compact(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def transcript_lines(transcript_dir: pathlib.Path, episode_id: str) -> list[str]:
    path = transcript_dir / f"{episode_id}.txt"
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def windows(lines: list[str]) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("[chunk "):
            continue
        previous_line = lines[index - 1].strip() if index > 0 else ""
        next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
        context = " / ".join(part for part in [previous_line, stripped, next_line] if part)
        result.append((index + 1, context))
    return result


def locate_evidence(lines: list[str], evidence_text: str, context_chars: int) -> tuple[str, str]:
    if not lines or not evidence_text:
        return "", ""

    evidence_norm = normalize_text(evidence_text)
    best_line = ""
    best_context = ""
    best_score = 0.0

    for line_number, context in windows(lines):
        context_norm = normalize_text(context)
        if evidence_norm and evidence_norm in context_norm:
            return str(line_number), compact(context, context_chars)
        score = difflib.SequenceMatcher(None, evidence_norm, context_norm).ratio()
        if score > best_score:
            best_score = score
            best_line = str(line_number)
            best_context = context

    if best_score < 0.28:
        return "", ""
    return best_line, compact(best_context, context_chars)


def build_rows(
    mentions: list[dict[str, str]],
    episodes: dict[str, dict[str, str]],
    transcript_dir: pathlib.Path,
    status: str,
    context_chars: int,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    transcript_cache: dict[str, list[str]] = {}

    for mention in mentions:
        if mention["mention_id"].startswith("sample_"):
            continue
        if mention.get("review_status") != status:
            continue

        episode_id = mention["episode_id"]
        if episode_id not in transcript_cache:
            transcript_cache[episode_id] = transcript_lines(transcript_dir, episode_id)
        line_number, context = locate_evidence(
            transcript_cache[episode_id],
            mention["evidence_text"],
            context_chars,
        )

        episode = episodes.get(episode_id, {})
        rows.append(
            {
                "mention_id": mention["mention_id"],
                "episode_id": episode_id,
                "published_at": mention["published_at"],
                "episode_title": episode.get("title", ""),
                "company_or_theme": mention["company_or_theme"],
                "ticker": mention["ticker"],
                "market": mention["market"],
                "mention_type": mention["mention_type"],
                "current_stance": mention["stance"],
                "current_conviction": mention["conviction"],
                "current_time_horizon": mention["time_horizon"],
                "evidence_text": mention["evidence_text"],
                "rationale": mention["rationale"],
                "reviewer_note": mention["reviewer_note"],
                "transcript_line": line_number,
                "transcript_context": context,
                "review_decision": "",
                "corrected_stance": "",
                "corrected_conviction": "",
                "corrected_time_horizon": "",
                "corrected_evidence_text": "",
                "review_comment": "",
            }
        )
    return rows


def write_rows(path: pathlib.Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "mention_id",
        "episode_id",
        "published_at",
        "episode_title",
        "company_or_theme",
        "ticker",
        "market",
        "mention_type",
        "current_stance",
        "current_conviction",
        "current_time_horizon",
        "evidence_text",
        "rationale",
        "reviewer_note",
        "transcript_line",
        "transcript_context",
        "review_decision",
        "corrected_stance",
        "corrected_conviction",
        "corrected_time_horizon",
        "corrected_evidence_text",
        "review_comment",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    mentions = load_csv(pathlib.Path(args.mentions_csv))
    episodes = {row["episode_id"]: row for row in load_csv(pathlib.Path(args.episodes_csv))}
    rows = build_rows(
        mentions=mentions,
        episodes=episodes,
        transcript_dir=pathlib.Path(args.transcript_dir),
        status=args.status,
        context_chars=args.context_chars,
    )
    write_rows(pathlib.Path(args.output), rows)
    print(f"Wrote {len(rows)} review rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
