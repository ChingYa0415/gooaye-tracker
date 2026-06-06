#!/usr/bin/env python3
"""Combine per-chunk transcript text files into one episode transcript."""

from __future__ import annotations

import argparse
import csv
import pathlib


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Combine chunk transcripts.")
    parser.add_argument("--episode-id", required=True)
    parser.add_argument(
        "--runs-csv",
        default="data/processed/transcription_runs.csv",
        help="Transcription run metadata produced by transcribe_openai.py.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/raw/transcripts",
        help="Directory for combined transcript text files.",
    )
    return parser.parse_args()


def load_runs(path: pathlib.Path, episode_id: str) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["episode_id"] == episode_id and row["transcription_status"] == "generated"
        ]
    return sorted(rows, key=lambda row: int(row["chunk_index"]))


def main() -> int:
    args = parse_args()
    runs = load_runs(pathlib.Path(args.runs_csv), args.episode_id)
    if not runs:
        raise ValueError(f"No generated transcript runs found for {args.episode_id}")

    parts: list[str] = []
    for run in runs:
        transcript_path = pathlib.Path(run["transcript_path"])
        if not transcript_path.exists():
            raise FileNotFoundError(transcript_path)
        parts.append(f"[chunk {int(run['chunk_index']):03d}]\n")
        parts.append(transcript_path.read_text(encoding="utf-8").strip())
        parts.append("\n\n")

    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{args.episode_id}.txt"
    output_path.write_text("".join(parts).strip() + "\n", encoding="utf-8")
    print(f"Wrote combined transcript to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
