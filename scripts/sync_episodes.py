#!/usr/bin/env python3
"""Sync Gooaye RSS episode metadata without overwriting processing status."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import pathlib
import re
import urllib.request
import xml.etree.ElementTree as ET


DEFAULT_FEED_URL = (
    "https://feeds.soundon.fm/podcasts/"
    "954689a5-3096-43a4-a80b-7810b219cef3.xml"
)
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"


@dataclass(frozen=True)
class FeedEpisode:
    episode_id: str
    title: str
    published_at: str
    url: str
    audio_url: str
    duration_seconds: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely sync latest Gooaye RSS episodes into processed CSVs."
    )
    parser.add_argument("--feed-url", default=DEFAULT_FEED_URL)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--episodes-csv", default="data/processed/episodes.csv")
    parser.add_argument("--transcript-inputs-csv", default="data/processed/transcript_inputs.csv")
    parser.add_argument("--transcript-dir", default="data/raw/transcripts")
    parser.add_argument("--report", default="reports/new_episodes.csv")
    parser.add_argument(
        "--include-backfill",
        action="store_true",
        help="Also add older RSS episodes that are absent from episodes.csv.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without writing CSV files.",
    )
    return parser.parse_args()


def fetch_feed(feed_url: str) -> bytes:
    request = urllib.request.Request(
        feed_url,
        headers={"User-Agent": "Mozilla/5.0 gooaye-tracker/0.1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def read_csv(path: pathlib.Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: pathlib.Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


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


def build_existing_url_map(rows: list[dict[str, str]], url_field: str, id_field: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rows:
        url = row.get(url_field, "")
        episode_id = row.get(id_field, "")
        if url and episode_id:
            result[url] = episode_id
    return result


def parse_feed(feed_xml: bytes, existing_url_to_id: dict[str, str], limit: int) -> list[FeedEpisode]:
    root = ET.fromstring(feed_xml)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("RSS feed is missing channel")

    rows: list[FeedEpisode] = []
    for index, item in enumerate(channel.findall("item")[:limit], start=1):
        title = item_text(item, "title")
        url = item_text(item, "link")
        published_at = iso_date(item_text(item, "pubDate"))
        duration = item_text(item, f"{{{ITUNES_NS}}}duration")
        enclosure = item.find("enclosure")
        audio_url = enclosure.attrib.get("url", "") if enclosure is not None else ""
        episode_id = existing_url_to_id.get(url) or fallback_episode_id(published_at, title, index)
        rows.append(
            FeedEpisode(
                episode_id=episode_id,
                title=title,
                published_at=published_at,
                url=url,
                audio_url=audio_url,
                duration_seconds=duration,
            )
        )
    return rows


def upsert_episodes(
    existing_rows: list[dict[str, str]],
    feed_rows: list[FeedEpisode],
    include_backfill: bool,
) -> tuple[list[dict[str, str]], list[FeedEpisode]]:
    by_id = {row["episode_id"]: dict(row) for row in existing_rows}
    sample_rows = [row for row in existing_rows if row.get("episode_id", "").startswith("sample_")]
    new_rows: list[FeedEpisode] = []
    existing_dates = [
        row.get("published_at", "")
        for row in existing_rows
        if not row.get("episode_id", "").startswith("sample_") and row.get("published_at", "")
    ]
    latest_existing_date = max(existing_dates) if existing_dates else ""

    for feed_row in feed_rows:
        existing = by_id.get(feed_row.episode_id)
        if existing is None:
            if not include_backfill and latest_existing_date and feed_row.published_at <= latest_existing_date:
                continue
            new_rows.append(feed_row)
            by_id[feed_row.episode_id] = {
                "episode_id": feed_row.episode_id,
                "source_name": "股癌 Gooaye",
                "source_type": "podcast",
                "title": feed_row.title,
                "published_at": feed_row.published_at,
                "url": feed_row.url,
                "duration_seconds": feed_row.duration_seconds,
                "transcript_status": "missing",
                "notes": f"synced from SoundOn RSS latest {len(feed_rows)}",
            }
            continue

        existing["source_name"] = existing.get("source_name") or "股癌 Gooaye"
        existing["source_type"] = existing.get("source_type") or "podcast"
        existing["title"] = feed_row.title
        existing["published_at"] = feed_row.published_at
        existing["url"] = feed_row.url
        existing["duration_seconds"] = feed_row.duration_seconds
        by_id[feed_row.episode_id] = existing

    sample_ids = {row["episode_id"] for row in sample_rows}
    formal_rows = [row for episode_id, row in by_id.items() if episode_id not in sample_ids]
    formal_rows.sort(key=lambda row: (row.get("published_at", ""), row.get("episode_id", "")), reverse=True)
    return sample_rows + formal_rows, new_rows


def upsert_transcript_inputs(
    existing_rows: list[dict[str, str]],
    feed_rows: list[FeedEpisode],
    new_rows: list[FeedEpisode],
    transcript_dir: pathlib.Path,
) -> list[dict[str, str]]:
    by_id = {row["episode_id"]: dict(row) for row in existing_rows}
    new_ids = {row.episode_id for row in new_rows}

    for feed_row in feed_rows:
        existing = by_id.get(feed_row.episode_id)
        if existing is None and feed_row.episode_id not in new_ids:
            continue
        transcript_path = str(transcript_dir / f"{safe_stem(feed_row.episode_id)}.txt")
        if existing is None:
            by_id[feed_row.episode_id] = {
                "episode_id": feed_row.episode_id,
                "source_name": "股癌 Gooaye",
                "title": feed_row.title,
                "published_at": feed_row.published_at,
                "episode_url": feed_row.url,
                "audio_url": feed_row.audio_url,
                "duration_seconds": feed_row.duration_seconds,
                "transcript_path": transcript_path,
                "transcript_status": "missing",
                "notes": "audio enclosure from SoundOn RSS; ASR not run yet",
            }
            continue

        existing["source_name"] = existing.get("source_name") or "股癌 Gooaye"
        existing["title"] = feed_row.title
        existing["published_at"] = feed_row.published_at
        existing["episode_url"] = feed_row.url
        existing["audio_url"] = feed_row.audio_url
        existing["duration_seconds"] = feed_row.duration_seconds
        existing["transcript_path"] = existing.get("transcript_path") or transcript_path
        existing["transcript_status"] = existing.get("transcript_status") or "missing"
        existing["notes"] = existing.get("notes") or "audio enclosure from SoundOn RSS; ASR not run yet"
        by_id[feed_row.episode_id] = existing

    rows = list(by_id.values())
    rows.sort(key=lambda row: (row.get("published_at", ""), row.get("episode_id", "")), reverse=True)
    return rows


def report_rows(new_rows: list[FeedEpisode]) -> list[dict[str, str]]:
    return [
        {
            "episode_id": row.episode_id,
            "published_at": row.published_at,
            "title": row.title,
            "url": row.url,
            "audio_url": row.audio_url,
            "duration_seconds": row.duration_seconds,
            "next_action": "download_audio",
        }
        for row in new_rows
    ]


def main() -> int:
    args = parse_args()
    episodes_path = pathlib.Path(args.episodes_csv)
    transcript_inputs_path = pathlib.Path(args.transcript_inputs_csv)

    episode_fields, episode_rows = read_csv(episodes_path)
    transcript_fields, transcript_rows = read_csv(transcript_inputs_path)
    existing_url_to_id = build_existing_url_map(episode_rows, "url", "episode_id")
    existing_url_to_id.update(build_existing_url_map(transcript_rows, "episode_url", "episode_id"))
    feed_rows = parse_feed(fetch_feed(args.feed_url), existing_url_to_id, args.limit)
    updated_episodes, new_rows = upsert_episodes(episode_rows, feed_rows, args.include_backfill)
    updated_transcript_inputs = upsert_transcript_inputs(
        transcript_rows,
        feed_rows,
        new_rows,
        pathlib.Path(args.transcript_dir),
    )
    new_report_rows = report_rows(new_rows)

    if not args.dry_run:
        write_csv(episodes_path, episode_fields, updated_episodes)
        write_csv(transcript_inputs_path, transcript_fields, updated_transcript_inputs)
        write_csv(
            pathlib.Path(args.report),
            ["episode_id", "published_at", "title", "url", "audio_url", "duration_seconds", "next_action"],
            new_report_rows,
        )

    newest = feed_rows[0] if feed_rows else None
    newest_text = f"{newest.episode_id} {newest.title} {newest.published_at}" if newest else "(none)"
    action = "Would sync" if args.dry_run else "Synced"
    print(f"{action} {len(feed_rows)} RSS episodes; new={len(new_rows)}; newest={newest_text}")
    if new_rows:
        print("New episodes:")
        for row in new_rows:
            print(f"- {row.episode_id} {row.published_at} {row.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
