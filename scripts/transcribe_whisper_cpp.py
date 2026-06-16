#!/usr/bin/env python3
"""Transcribe local audio chunks with whisper.cpp."""

from __future__ import annotations

import argparse
import csv
import pathlib
import shutil
import subprocess


FIELDNAMES = [
    "episode_id",
    "chunk_index",
    "chunk_path",
    "transcript_path",
    "model",
    "transcription_status",
    "notes",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe episode audio chunks with whisper.cpp.")
    parser.add_argument("--episode-id", required=True)
    parser.add_argument(
        "--chunk-index",
        type=int,
        help="Transcribe one chunk only. Defaults to all chunks for the episode.",
    )
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
    parser.add_argument("--force", action="store_true", help="Re-transcribe chunks with existing text files.")
    return parser.parse_args()


def load_chunks(path: pathlib.Path, episode_id: str, chunk_index: int | None) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["episode_id"] == episode_id
            and (chunk_index is None or int(row["chunk_index"]) == chunk_index)
        ]
    if not rows:
        suffix = "" if chunk_index is None else f" #{chunk_index}"
        raise ValueError(f"Chunk not found: {episode_id}{suffix}")
    return sorted(rows, key=lambda row: int(row["chunk_index"]))


def read_runs(path: pathlib.Path) -> dict[tuple[str, int], dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {
            (row["episode_id"], int(row["chunk_index"])): row
            for row in csv.DictReader(handle)
        }


def write_runs(path: pathlib.Path, runs: dict[tuple[str, int], dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        for row in sorted(runs.values(), key=lambda item: (item["episode_id"], int(item["chunk_index"]))):
            writer.writerow({field: row.get(field, "") for field in FIELDNAMES})


def transcribe_chunk(
    whisper_cli: str,
    model_path: pathlib.Path,
    language: str,
    chunk: dict[str, str],
    output_dir: pathlib.Path,
    force: bool,
) -> dict[str, str]:
    chunk_index = int(chunk["chunk_index"])
    chunk_path = pathlib.Path(chunk["chunk_path"])
    if not chunk_path.exists():
        raise FileNotFoundError(chunk_path)

    output_prefix = output_dir / f"{chunk['episode_id']}_{chunk_index:03d}"
    transcript_path = output_prefix.with_suffix(".txt")
    if transcript_path.exists() and not force:
        return {
            "episode_id": chunk["episode_id"],
            "chunk_index": str(chunk_index),
            "chunk_path": str(chunk_path),
            "transcript_path": str(transcript_path),
            "model": f"whisper.cpp:{model_path.name}",
            "transcription_status": "generated",
            "notes": "existing local whisper.cpp transcript file reused",
        }

    command = [
        whisper_cli,
        "-m",
        str(model_path),
        "-f",
        str(chunk_path),
        "-l",
        language,
        "-otxt",
        "-of",
        str(output_prefix),
        "-np",
    ]
    subprocess.run(command, check=True)
    return {
        "episode_id": chunk["episode_id"],
        "chunk_index": str(chunk_index),
        "chunk_path": str(chunk_path),
        "transcript_path": str(transcript_path),
        "model": f"whisper.cpp:{model_path.name}",
        "transcription_status": "generated",
        "notes": "local whisper.cpp transcript file is gitignored",
    }


def main() -> int:
    args = parse_args()
    whisper_cli = shutil.which("whisper-cli")
    if not whisper_cli:
        raise RuntimeError("whisper-cli is required. Install it with: brew install whisper-cpp")

    model_path = pathlib.Path(args.model)
    if not model_path.exists():
        raise FileNotFoundError(f"Whisper model not found: {model_path}")

    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks = load_chunks(pathlib.Path(args.chunks_csv), args.episode_id, args.chunk_index)
    runs = read_runs(pathlib.Path(args.transcripts_csv))
    for chunk in chunks:
        row = transcribe_chunk(whisper_cli, model_path, args.language, chunk, output_dir, args.force)
        runs[(row["episode_id"], int(row["chunk_index"]))] = row

    write_runs(pathlib.Path(args.transcripts_csv), runs)
    print(f"Recorded {len(chunks)} transcript chunk(s) for {args.episode_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
