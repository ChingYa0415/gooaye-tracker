#!/usr/bin/env python3
"""Split a downloaded episode MP3 into API-friendly chunks with ffmpeg."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import pathlib
import shutil
import subprocess


@dataclass(frozen=True)
class AudioDownload:
    episode_id: str
    title: str
    audio_path: str
    duration_seconds: str


@dataclass(frozen=True)
class AudioChunk:
    episode_id: str
    title: str
    chunk_index: int
    chunk_path: str
    chunk_bytes: int
    split_seconds: int
    chunk_status: str
    created_at: str
    notes: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Split a downloaded MP3 into chunks.")
    parser.add_argument("--episode-id", required=True)
    parser.add_argument(
        "--downloads-csv",
        default="data/processed/audio_downloads.csv",
        help="Download metadata CSV produced by download_audio.py.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/raw/audio_chunks",
        help="Directory for local chunk files.",
    )
    parser.add_argument(
        "--chunks-csv",
        default="data/processed/audio_chunks.csv",
        help="Chunk metadata CSV to create or update.",
    )
    parser.add_argument(
        "--segment-seconds",
        type=int,
        default=900,
        help="Chunk duration in seconds. 900 seconds keeps this feed under 25 MB.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def load_downloads(path: pathlib.Path) -> dict[str, AudioDownload]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {
            row["episode_id"]: AudioDownload(
                episode_id=row["episode_id"],
                title=row["title"],
                audio_path=row["audio_path"],
                duration_seconds=row.get("duration_seconds", ""),
            )
            for row in csv.DictReader(handle)
        }


def run_ffmpeg(audio_path: pathlib.Path, output_pattern: pathlib.Path, segment_seconds: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required. Install it with: brew install ffmpeg")
    output_pattern.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(audio_path),
        "-f",
        "segment",
        "-segment_time",
        str(segment_seconds),
        "-c",
        "copy",
        str(output_pattern),
    ]
    subprocess.run(command, check=True)


def read_existing_chunks(path: pathlib.Path) -> dict[tuple[str, int], AudioChunk]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        chunks = {}
        for row in csv.DictReader(handle):
            key = (row["episode_id"], int(row["chunk_index"]))
            chunks[key] = AudioChunk(
                episode_id=row["episode_id"],
                title=row["title"],
                chunk_index=int(row["chunk_index"]),
                chunk_path=row["chunk_path"],
                chunk_bytes=int(row["chunk_bytes"] or 0),
                split_seconds=int(row["split_seconds"] or 0),
                chunk_status=row["chunk_status"],
                created_at=row["created_at"],
                notes=row.get("notes", ""),
            )
        return chunks


def write_chunks(path: pathlib.Path, chunks: dict[tuple[str, int], AudioChunk]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "episode_id",
        "title",
        "chunk_index",
        "chunk_path",
        "chunk_bytes",
        "split_seconds",
        "chunk_status",
        "created_at",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for chunk in sorted(chunks.values(), key=lambda item: (item.episode_id, item.chunk_index)):
            writer.writerow(chunk.__dict__)


def main() -> int:
    args = parse_args()
    downloads = load_downloads(pathlib.Path(args.downloads_csv))
    if args.episode_id not in downloads:
        raise ValueError(f"Episode has not been downloaded: {args.episode_id}")

    download = downloads[args.episode_id]
    audio_path = pathlib.Path(download.audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(audio_path)

    output_dir = pathlib.Path(args.output_dir)
    output_pattern = output_dir / f"{args.episode_id}_%03d.mp3"
    existing_files = sorted(output_dir.glob(f"{args.episode_id}_*.mp3"))
    if existing_files and not args.force:
        chunk_files = existing_files
    else:
        for path in existing_files:
            path.unlink()
        run_ffmpeg(audio_path, output_pattern, args.segment_seconds)
        chunk_files = sorted(output_dir.glob(f"{args.episode_id}_*.mp3"))

    existing_chunks = read_existing_chunks(pathlib.Path(args.chunks_csv))
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for index, path in enumerate(chunk_files):
        existing_chunks[(args.episode_id, index)] = AudioChunk(
            episode_id=args.episode_id,
            title=download.title,
            chunk_index=index,
            chunk_path=str(path),
            chunk_bytes=path.stat().st_size,
            split_seconds=args.segment_seconds,
            chunk_status="ready",
            created_at=created_at,
            notes="local chunk file is gitignored",
        )

    write_chunks(pathlib.Path(args.chunks_csv), existing_chunks)
    print(f"Wrote {len(chunk_files)} chunks for {args.episode_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

