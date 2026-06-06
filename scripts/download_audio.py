#!/usr/bin/env python3
"""Download an episode audio file from transcript_inputs.csv.

Downloaded MP3 files are local raw artifacts and are intentionally ignored by
Git. Metadata about successful downloads is written to audio_downloads.csv.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import pathlib
import shutil
import tempfile
import urllib.request


@dataclass(frozen=True)
class TranscriptInput:
    episode_id: str
    title: str
    audio_url: str
    duration_seconds: str


@dataclass(frozen=True)
class AudioDownload:
    episode_id: str
    title: str
    audio_path: str
    audio_bytes: int
    sha256: str
    duration_seconds: str
    download_status: str
    downloaded_at: str
    notes: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download one episode audio file.")
    parser.add_argument(
        "--episode-id",
        help="Episode id to download. Defaults to the first row in transcript_inputs.csv.",
    )
    parser.add_argument(
        "--input",
        default="data/processed/transcript_inputs.csv",
        help="Transcript input manifest.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/raw/audio",
        help="Directory for local audio files.",
    )
    parser.add_argument(
        "--downloads-csv",
        default="data/processed/audio_downloads.csv",
        help="Download metadata CSV to create or update.",
    )
    parser.add_argument("--force", action="store_true", help="Re-download if file exists.")
    return parser.parse_args()


def load_inputs(path: pathlib.Path) -> list[TranscriptInput]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = []
        for row in csv.DictReader(handle):
            rows.append(
                TranscriptInput(
                    episode_id=row["episode_id"],
                    title=row["title"],
                    audio_url=row["audio_url"],
                    duration_seconds=row.get("duration_seconds", ""),
                )
            )
        return rows


def select_input(rows: list[TranscriptInput], episode_id: str | None) -> TranscriptInput:
    if not rows:
        raise ValueError("No transcript input rows found")
    if episode_id is None:
        return rows[0]
    for row in rows:
        if row.episode_id == episode_id:
            return row
    raise ValueError(f"Episode id not found: {episode_id}")


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: pathlib.Path, force: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        return

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 gooaye-tracker/0.1"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        with tempfile.NamedTemporaryFile(delete=False, dir=destination.parent) as tmp:
            tmp_path = pathlib.Path(tmp.name)
            shutil.copyfileobj(response, tmp)
    tmp_path.replace(destination)


def read_existing_downloads(path: pathlib.Path) -> dict[str, AudioDownload]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {
            row["episode_id"]: AudioDownload(
                episode_id=row["episode_id"],
                title=row["title"],
                audio_path=row["audio_path"],
                audio_bytes=int(row["audio_bytes"] or 0),
                sha256=row["sha256"],
                duration_seconds=row.get("duration_seconds", ""),
                download_status=row["download_status"],
                downloaded_at=row["downloaded_at"],
                notes=row.get("notes", ""),
            )
            for row in csv.DictReader(handle)
        }


def write_downloads(path: pathlib.Path, downloads: dict[str, AudioDownload]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "episode_id",
        "title",
        "audio_path",
        "audio_bytes",
        "sha256",
        "duration_seconds",
        "download_status",
        "downloaded_at",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(downloads.values(), key=lambda item: item.episode_id):
            writer.writerow(row.__dict__)


def main() -> int:
    args = parse_args()
    rows = load_inputs(pathlib.Path(args.input))
    selected = select_input(rows, args.episode_id)
    output_path = pathlib.Path(args.output_dir) / f"{selected.episode_id}.mp3"

    download(selected.audio_url, output_path, force=args.force)

    audio_bytes = output_path.stat().st_size
    sha256 = sha256_file(output_path)
    downloads = read_existing_downloads(pathlib.Path(args.downloads_csv))
    downloads[selected.episode_id] = AudioDownload(
        episode_id=selected.episode_id,
        title=selected.title,
        audio_path=str(output_path),
        audio_bytes=audio_bytes,
        sha256=sha256,
        duration_seconds=selected.duration_seconds,
        download_status="downloaded",
        downloaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        notes="local audio file is gitignored",
    )
    write_downloads(pathlib.Path(args.downloads_csv), downloads)
    print(f"Downloaded {selected.episode_id} to {output_path} ({audio_bytes} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

