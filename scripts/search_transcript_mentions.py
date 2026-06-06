#!/usr/bin/env python3
"""Search local transcripts for instrument names and aliases."""

from __future__ import annotations

import argparse
import csv
import pathlib
import re
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find instrument alias hits in generated transcript text files."
    )
    parser.add_argument(
        "--episode-id",
        action="append",
        help="Episode ID to scan. Can be passed more than once. Defaults to all transcripts.",
    )
    parser.add_argument(
        "--transcript-dir",
        default="data/raw/transcripts",
        help="Directory containing combined transcript text files.",
    )
    parser.add_argument(
        "--instruments-csv",
        default="data/processed/instruments.csv",
        help="Instrument table containing names and aliases.",
    )
    parser.add_argument(
        "--context-lines",
        type=int,
        default=2,
        help="Number of lines before and after each hit to include.",
    )
    parser.add_argument(
        "--limit-per-alias",
        type=int,
        default=5,
        help="Maximum hits to emit for the same episode and alias.",
    )
    return parser.parse_args()


def split_aliases(row: dict[str, str]) -> list[str]:
    aliases = [row.get("name", ""), row.get("ticker", "")]
    aliases.extend(row.get("aliases", "").split(";"))
    cleaned: list[str] = []
    for alias in aliases:
        alias = alias.strip()
        if len(alias) < 2:
            continue
        if alias not in cleaned:
            cleaned.append(alias)
    return cleaned


def load_aliases(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    terms: list[dict[str, str]] = []
    for row in rows:
        if row.get("is_active", "true").lower() != "true":
            continue
        for alias in split_aliases(row):
            terms.append(
                {
                    "instrument_id": row["instrument_id"],
                    "name": row["name"],
                    "ticker": row["ticker"],
                    "market": row["market"],
                    "alias": alias,
                }
            )
    return terms


def transcript_paths(transcript_dir: pathlib.Path, episode_ids: list[str] | None) -> list[pathlib.Path]:
    if episode_ids:
        return [transcript_dir / f"{episode_id}.txt" for episode_id in episode_ids]
    return sorted(transcript_dir.glob("ep_*.txt"))


def contains_alias(line: str, alias: str) -> bool:
    if alias.isascii() and re.fullmatch(r"[A-Za-z0-9._-]+", alias):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])"
        return re.search(pattern, line, flags=re.IGNORECASE) is not None
    flags = re.IGNORECASE if alias.isascii() else 0
    return re.search(re.escape(alias), line, flags=flags) is not None


def context_for(lines: list[str], line_index: int, context_lines: int) -> str:
    start = max(0, line_index - context_lines)
    end = min(len(lines), line_index + context_lines + 1)
    return " / ".join(line.strip() for line in lines[start:end] if line.strip())


def scan_transcript(
    path: pathlib.Path,
    aliases: list[dict[str, str]],
    context_lines: int,
    limit_per_alias: int,
) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)

    episode_id = path.stem
    lines = path.read_text(encoding="utf-8").splitlines()
    emitted_counts: dict[tuple[str, str, str], int] = {}
    rows: list[dict[str, str]] = []

    for line_index, line in enumerate(lines):
        for alias_row in aliases:
            alias = alias_row["alias"]
            key = (episode_id, alias_row["instrument_id"], alias)
            if emitted_counts.get(key, 0) >= limit_per_alias:
                continue
            if not contains_alias(line, alias):
                continue

            emitted_counts[key] = emitted_counts.get(key, 0) + 1
            rows.append(
                {
                    "episode_id": episode_id,
                    "line_number": str(line_index + 1),
                    "instrument_id": alias_row["instrument_id"],
                    "name": alias_row["name"],
                    "ticker": alias_row["ticker"],
                    "market": alias_row["market"],
                    "matched_alias": alias,
                    "context": context_for(lines, line_index, context_lines),
                }
            )
    return rows


def main() -> int:
    args = parse_args()
    aliases = load_aliases(pathlib.Path(args.instruments_csv))
    paths = transcript_paths(pathlib.Path(args.transcript_dir), args.episode_id)

    fieldnames = [
        "episode_id",
        "line_number",
        "instrument_id",
        "name",
        "ticker",
        "market",
        "matched_alias",
        "context",
    ]
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    for path in paths:
        for row in scan_transcript(
            path=path,
            aliases=aliases,
            context_lines=args.context_lines,
            limit_per_alias=args.limit_per_alias,
        ):
            writer.writerow(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
