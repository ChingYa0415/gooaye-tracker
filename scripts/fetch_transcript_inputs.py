#!/usr/bin/env python3
"""Build a transcript input manifest from the Gooaye RSS feed.

The manifest maps each selected episode to its audio enclosure URL and the
local transcript path that later ASR steps should produce.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import pathlib
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET


DEFAULT_FEED_URL = (
    "https://feeds.soundon.fm/podcasts/"
    "954689a5-3096-43a4-a80b-7810b219cef3.xml"
)

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"


@dataclass(frozen=True)
class EpisodeRef:
    episode_id: str
    title: str
    published_at: str
    url: str


@dataclass(frozen=True)
class TranscriptInput:
    episode_id: str
    source_name: str
    title: str
    published_at: str
    episode_url: str
    audio_url: str
    duration_seconds: str
    transcript_path: str
    transcript_status: str
    notes: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create data/processed/transcript_inputs.csv from RSS metadata."
    )
    parser.add_argument("--feed-url", default=DEFAULT_FEED_URL)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--episodes-csv",
        default="data/processed/episodes.csv",
        help="Existing episode table used to preserve episode_id values.",
    )
    parser.add_argument(
        "--output",
        default="data/processed/transcript_inputs.csv",
        help="CSV manifest to write.",
    )
    parser.add_argument(
        "--transcript-dir",
        default="data/raw/transcripts",
        help="Directory where transcript text files should be produced later.",
    )
    return parser.parse_args()


def fetch_feed(feed_url: str) -> bytes:
    request = urllib.request.Request(
        feed_url,
        headers={"User-Agent": "Mozilla/5.0 gooaye-tracker/0.1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def load_episode_refs(path: pathlib.Path) -> dict[str, EpisodeRef]:
    if not path.exists():
        return {}

    refs: dict[str, EpisodeRef] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            url = row.get("url", "")
            episode_id = row.get("episode_id", "")
            if not url or not episode_id:
                continue
            refs[url] = EpisodeRef(
                episode_id=episode_id,
                title=row.get("title", ""),
                published_at=row.get("published_at", ""),
                url=url,
            )
    return refs


def iso_date(pub_date: str) -> str:
    if not pub_date:
        return ""
    return parsedate_to_datetime(pub_date).date().isoformat()


def safe_stem(episode_id: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", episode_id).strip("_")
    return stem or "transcript"


def fallback_episode_id(published_at: str, title: str, index: int) -> str:
    date_part = published_at.replace("-", "") or "unknown_date"
    number_match = re.search(r"EP\s*(\d+)", title, flags=re.IGNORECASE)
    if number_match:
        return f"ep_{date_part}_{number_match.group(1)}"
    return f"ep_{date_part}_{index:03d}"


def item_text(item: ET.Element, tag: str) -> str:
    return item.findtext(tag) or ""


def build_manifest(
    feed_xml: bytes,
    episode_refs: dict[str, EpisodeRef],
    limit: int,
    transcript_dir: pathlib.Path,
) -> list[TranscriptInput]:
    root = ET.fromstring(feed_xml)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("RSS feed is missing channel")

    rows: list[TranscriptInput] = []
    for index, item in enumerate(channel.findall("item")[:limit], start=1):
        title = item_text(item, "title")
        episode_url = item_text(item, "link")
        published_at = iso_date(item_text(item, "pubDate"))
        duration = item_text(item, f"{{{ITUNES_NS}}}duration")
        enclosure = item.find("enclosure")
        audio_url = enclosure.attrib.get("url", "") if enclosure is not None else ""

        episode_ref = episode_refs.get(episode_url)
        episode_id = (
            episode_ref.episode_id
            if episode_ref is not None
            else fallback_episode_id(published_at, title, index)
        )
        transcript_path = transcript_dir / f"{safe_stem(episode_id)}.txt"

        rows.append(
            TranscriptInput(
                episode_id=episode_id,
                source_name="股癌 Gooaye",
                title=title,
                published_at=published_at,
                episode_url=episode_url,
                audio_url=audio_url,
                duration_seconds=duration,
                transcript_path=str(transcript_path),
                transcript_status="missing",
                notes="audio enclosure from SoundOn RSS; ASR not run yet",
            )
        )

    return rows


def write_manifest(path: pathlib.Path, rows: list[TranscriptInput]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "episode_id",
        "source_name",
        "title",
        "published_at",
        "episode_url",
        "audio_url",
        "duration_seconds",
        "transcript_path",
        "transcript_status",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def main() -> int:
    args = parse_args()
    feed_xml = fetch_feed(args.feed_url)
    episode_refs = load_episode_refs(pathlib.Path(args.episodes_csv))
    rows = build_manifest(
        feed_xml=feed_xml,
        episode_refs=episode_refs,
        limit=args.limit,
        transcript_dir=pathlib.Path(args.transcript_dir),
    )
    write_manifest(pathlib.Path(args.output), rows)
    print(f"Wrote {len(rows)} transcript input rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
