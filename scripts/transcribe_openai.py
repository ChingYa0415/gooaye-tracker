#!/usr/bin/env python3
"""Transcribe an audio chunk with OpenAI Speech-to-Text.

Requires OPENAI_API_KEY in the environment. Raw transcript text is written to
data/raw/transcripts/ and is intentionally ignored by Git.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import ssl
import urllib.request
import uuid


OPENAI_TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def load_dotenv(path: pathlib.Path = pathlib.Path(".env")) -> None:
    """Load simple KEY=VALUE lines from .env without overriding the environment."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe one audio chunk via OpenAI.")
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--chunk-index", type=int, default=0)
    parser.add_argument("--model", default="gpt-4o-mini-transcribe")
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


def multipart_body(fields: dict[str, str], file_field: str, file_path: pathlib.Path) -> tuple[bytes, str]:
    boundary = f"----gooaye-tracker-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    parts.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_path.name}"\r\n'
            ).encode(),
            b"Content-Type: audio/mpeg\r\n\r\n",
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(parts), boundary


def transcribe(file_path: pathlib.Path, model: str, api_key: str) -> str:
    if file_path.stat().st_size > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"Audio chunk is larger than 25 MB: {file_path.stat().st_size} bytes"
        )
    body, boundary = multipart_body(
        fields={"model": model, "response_format": "text"},
        file_field="file",
        file_path=file_path,
    )
    request = urllib.request.Request(
        OPENAI_TRANSCRIPTIONS_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300, context=ssl.create_default_context()) as response:
        return response.read().decode("utf-8")


def validate_api_key(api_key: str) -> None:
    if not api_key.isascii():
        raise RuntimeError("OPENAI_API_KEY contains non-ASCII characters. Replace the placeholder with the real key.")
    if not api_key.startswith("sk-"):
        raise RuntimeError("OPENAI_API_KEY should start with sk-. Replace the placeholder with the real key.")


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
    load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set. Set it in the shell or local .env file.")
    validate_api_key(api_key)

    chunk = find_chunk(pathlib.Path(args.chunks_csv), args.episode_id, args.chunk_index)
    chunk_path = pathlib.Path(chunk["chunk_path"])
    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = output_dir / f"{args.episode_id}_{args.chunk_index:03d}.txt"

    text = transcribe(chunk_path, model=args.model, api_key=api_key)
    transcript_path.write_text(text, encoding="utf-8")
    append_run(
        pathlib.Path(args.transcripts_csv),
        {
            "episode_id": args.episode_id,
            "chunk_index": str(args.chunk_index),
            "chunk_path": str(chunk_path),
            "transcript_path": str(transcript_path),
            "model": args.model,
            "transcription_status": "generated",
            "notes": "raw transcript file is gitignored",
        },
    )
    print(json.dumps({"transcript_path": str(transcript_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
