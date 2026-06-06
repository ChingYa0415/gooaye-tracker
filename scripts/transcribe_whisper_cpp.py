#!/usr/bin/env python3
"""Transcribe an audio chunk locally with whisper.cpp."""

from __future__ import annotations

import argparse
import csv
import pathlib
import shutil
import subprocess


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe one audio chunk with whisper.cpp.")
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--chunk-index", type=int, default=0)
    parser.add_argument("--model", default="data/models/ggml-base.bin")
    parser.add_argument("--language", default="zh")
    parser.add_argument(
        "--chunks-csv",
        default="data/processed/audio_chunks.csv",
        help="Chunk metadata CSV produced by split_audio.py.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/raw/transcripts",
        help="Directory for local transcript text files.",
    )
    parser.add_argument(
        "--transcripts-csv",
        default="data/processed/transcription_runs.csv",
        help="Transcription run metadata CSV to create or update.",
    )
    return parser.parse_args()


def find_chunk(path: pathlib.Path, episode_id: str, chunk_index: int) -> dict[str, str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["episode_id"] == episode_id and int(row["chunk_index"]) == chunk_index:
                return row
    raise ValueError(f"Chunk not found: {episode_id} #{chunk_index}")


def append_run(path: pathlib.Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    fieldnames = [
        "episode_id",
        "chunk_index",
        "chunk_path",
        "transcript_path",
        "model",
        "transcription_status",
        "notes",
    ]
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def main() -> int:
    args = parse_args()
    whisper_cli = shutil.which("whisper-cli")
    if not whisper_cli:
        raise RuntimeError("whisper-cli is required. Install it with: brew install whisper-cpp")

    model_path = pathlib.Path(args.model)
    if not model_path.exists():
        raise FileNotFoundError(f"Whisper model not found: {model_path}")

    chunk = find_chunk(pathlib.Path(args.chunks_csv), args.episode_id, args.chunk_index)
    chunk_path = pathlib.Path(chunk["chunk_path"])
    if not chunk_path.exists():
        raise FileNotFoundError(chunk_path)

    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_prefix = output_dir / f"{args.episode_id}_{args.chunk_index:03d}"
    transcript_path = output_prefix.with_suffix(".txt")

    command = [
        whisper_cli,
        "-m",
        str(model_path),
        "-f",
        str(chunk_path),
        "-l",
        args.language,
        "-otxt",
        "-of",
        str(output_prefix),
        "-np",
    ]
    subprocess.run(command, check=True)

    append_run(
        pathlib.Path(args.transcripts_csv),
        {
            "episode_id": args.episode_id,
            "chunk_index": str(args.chunk_index),
            "chunk_path": str(chunk_path),
            "transcript_path": str(transcript_path),
            "model": f"whisper.cpp:{model_path.name}",
            "transcription_status": "generated",
            "notes": "local whisper.cpp transcript file is gitignored",
        },
    )
    print(f"Wrote transcript to {transcript_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
