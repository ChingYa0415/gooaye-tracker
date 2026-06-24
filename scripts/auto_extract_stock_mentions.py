#!/usr/bin/env python3
"""Automatically extract stock mentions from local combined transcripts."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
import pathlib
import re


SUPPORTED_MARKETS = {"TWSE", "TPEx", "US"}

STANCE_KEYWORDS = {
    "bullish": [
        "看好",
        "受惠",
        "轉強",
        "突破",
        "順風",
        "極好",
        "買回",
        "buyback",
        "上去",
        "推上去",
        "成長",
        "漲價",
        "缺貨",
        "機會",
        "有興趣",
        "加分",
        "改善",
        "很好",
    ],
    "bearish": [
        "看壞",
        "小心",
        "風險",
        "轉弱",
        "不好",
        "躺在地上",
        "下去",
        "壓力",
        "危險",
        "扣分",
    ],
    "watch": [
        "觀察",
        "看一下",
        "有沒有可能",
        "等",
        "不確定",
        "可能要",
        "先看",
        "再看",
    ],
    "past_review": [
        "那時候",
        "之前",
        "前面",
        "已經噴",
        "翻倍",
        "噴到",
        "回顧",
        "過去",
    ],
}

EXCLUDED_CONTEXT_KEYWORDS = [
    "本集節目由",
    "贊助",
    "檔期",
    "優惠",
    "馬卡",
    "火星生技",
    "火星升機",
]


@dataclass(frozen=True)
class Alias:
    instrument_id: str
    name: str
    ticker: str
    market: str
    alias: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-add approved company mentions from generated transcripts."
    )
    parser.add_argument("--episodes-csv", default="data/processed/episodes.csv")
    parser.add_argument("--mentions-csv", default="data/processed/mentions.csv")
    parser.add_argument("--instruments-csv", default="data/processed/instruments.csv")
    parser.add_argument("--transcript-dir", default="data/raw/transcripts")
    parser.add_argument("--output", default="data/processed/mentions.csv")
    parser.add_argument("--report", default="reports/auto_stock_mentions.csv")
    parser.add_argument("--context-lines", type=int, default=2)
    parser.add_argument(
        "--include-low-confidence",
        action="store_true",
        help="Also add neutral/low-confidence hits to mentions.csv.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def read_csv(path: pathlib.Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: pathlib.Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


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


def load_company_aliases(path: pathlib.Path) -> list[Alias]:
    _, rows = read_csv(path)
    aliases: list[Alias] = []
    for row in rows:
        if row.get("is_active", "true").lower() != "true":
            continue
        if not row.get("ticker") or row.get("market") not in SUPPORTED_MARKETS:
            continue
        for alias in split_aliases(row):
            aliases.append(
                Alias(
                    instrument_id=row["instrument_id"],
                    name=row["name"],
                    ticker=row["ticker"],
                    market=row["market"],
                    alias=alias,
                )
            )
    return aliases


def contains_alias(line: str, alias: str) -> bool:
    if alias.isascii() and re.fullmatch(r"[A-Za-z0-9._-]+", alias):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])"
        flags = 0 if alias.isupper() and len(alias) <= 5 else re.IGNORECASE
        return re.search(pattern, line, flags=flags) is not None
    flags = re.IGNORECASE if alias.isascii() else 0
    return re.search(re.escape(alias), line, flags=flags) is not None


def context_for(lines: list[str], line_index: int, context_lines: int) -> str:
    start = max(0, line_index - context_lines)
    end = min(len(lines), line_index + context_lines + 1)
    return " / ".join(line.strip() for line in lines[start:end] if line.strip())


def combined_transcript_paths(transcript_dir: pathlib.Path, episode_ids: set[str]) -> list[pathlib.Path]:
    paths: list[pathlib.Path] = []
    for episode_id in sorted(episode_ids):
        path = transcript_dir / f"{episode_id}.txt"
        if path.exists():
            paths.append(path)
    return paths


def compact(value: str, limit: int = 220) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def score_stance(context: str) -> tuple[str, int]:
    scores: dict[str, int] = {}
    context_folded = context.casefold()
    for stance, keywords in STANCE_KEYWORDS.items():
        scores[stance] = sum(1 for keyword in keywords if keyword.casefold() in context_folded)
    best_stance, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score <= 0:
        return "neutral", 0
    if scores["bullish"] and scores["bearish"] and abs(scores["bullish"] - scores["bearish"]) <= 1:
        return "watch", max(scores["bullish"], scores["bearish"])
    return best_stance, best_score


def is_excluded_context(context: str) -> bool:
    return any(keyword in context for keyword in EXCLUDED_CONTEXT_KEYWORDS)


def evidence_context(contexts: list[str]) -> str:
    candidates = [context for context in contexts if not is_excluded_context(context)]
    if not candidates:
        candidates = contexts
    if not candidates:
        return ""
    return max(candidates, key=lambda context: score_stance(context)[1])


def classify_time_horizon(context: str) -> str:
    if any(keyword in context for keyword in ["短期", "最近", "這波", "後面", "接下來"]):
        return "short"
    if any(keyword in context for keyword in ["長期", "未來", "幾年", "長線"]):
        return "long"
    return "medium"


def conviction_from_score(score: int) -> str:
    if score >= 3:
        return "high"
    if score >= 1:
        return "medium"
    return "low"


def mention_id_for(episode_id: str, ticker: str) -> str:
    suffix = episode_id.removeprefix("ep_")
    safe_ticker = re.sub(r"[^A-Za-z0-9]+", "_", ticker.lower()).strip("_")
    return f"auto_{suffix}_{safe_ticker}"


def existing_episode_tickers(mentions: list[dict[str, str]]) -> set[tuple[str, str, str]]:
    return {
        (row["episode_id"], row.get("ticker", ""), row.get("market", ""))
        for row in mentions
        if not row["mention_id"].startswith(("sample_", "auto_")) and row.get("ticker")
    }


def scan_transcripts(
    paths: list[pathlib.Path],
    aliases: list[Alias],
    context_lines: int,
) -> dict[tuple[str, str, str], dict[str, object]]:
    grouped: dict[tuple[str, str, str], dict[str, object]] = {}
    for path in paths:
        episode_id = path.stem
        lines = path.read_text(encoding="utf-8").splitlines()
        for line_index, line in enumerate(lines):
            for alias in aliases:
                if not contains_alias(line, alias.alias):
                    continue
                key = (episode_id, alias.ticker, alias.market)
                entry = grouped.setdefault(
                    key,
                    {
                        "episode_id": episode_id,
                        "name": alias.name,
                        "ticker": alias.ticker,
                        "market": alias.market,
                        "aliases": set(),
                        "contexts": [],
                        "line_numbers": [],
                    },
                )
                entry["aliases"].add(alias.alias)  # type: ignore[index, union-attr]
                entry["line_numbers"].append(str(line_index + 1))  # type: ignore[index, union-attr]
                contexts: list[str] = entry["contexts"]  # type: ignore[assignment]
                if len(contexts) < 3:
                    contexts.append(context_for(lines, line_index, context_lines))
    return grouped


def build_new_mentions(
    grouped_hits: dict[tuple[str, str, str], dict[str, object]],
    episodes_by_id: dict[str, dict[str, str]],
    existing_keys: set[tuple[str, str, str]],
    include_low_confidence: bool,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    new_mentions: list[dict[str, str]] = []
    report_rows: list[dict[str, str]] = []
    for key in sorted(grouped_hits):
        episode_id, ticker, market = key
        hit = grouped_hits[key]
        contexts: list[str] = hit["contexts"]  # type: ignore[assignment]
        aliases: set[str] = hit["aliases"]  # type: ignore[assignment]
        if key in existing_keys:
            report_rows.append(
                {
                    "episode_id": episode_id,
                    "ticker": ticker,
                    "market": market,
                    "company_or_theme": str(hit["name"]),
                    "matched_aliases": ";".join(sorted(aliases)),
                    "line_numbers": ";".join(hit["line_numbers"]),  # type: ignore[arg-type]
                    "auto_stance": "",
                    "auto_conviction": "",
                    "auto_time_horizon": "",
                    "evidence_text": compact(contexts[0] if contexts else ""),
                    "action": "skipped_existing_mention",
                }
            )
            continue
        usable_contexts = [context for context in contexts if not is_excluded_context(context)]
        context = " / ".join(usable_contexts or contexts)
        stance, score = score_stance(context)
        evidence = compact(evidence_context(contexts))
        if score <= 0 and not include_low_confidence:
            report_rows.append(
                {
                    "episode_id": episode_id,
                    "ticker": ticker,
                    "market": market,
                    "company_or_theme": str(hit["name"]),
                    "matched_aliases": ";".join(sorted(aliases)),
                    "line_numbers": ";".join(hit["line_numbers"]),  # type: ignore[arg-type]
                    "auto_stance": stance,
                    "auto_conviction": conviction_from_score(score),
                    "auto_time_horizon": classify_time_horizon(context),
                    "evidence_text": evidence,
                    "action": "skipped_low_confidence",
                }
            )
            continue
        episode = episodes_by_id.get(episode_id, {})
        mention = {
            "mention_id": mention_id_for(episode_id, ticker),
            "episode_id": episode_id,
            "published_at": episode.get("published_at", ""),
            "company_or_theme": str(hit["name"]),
            "ticker": ticker,
            "market": market,
            "mention_type": "company",
            "stance": stance,
            "conviction": conviction_from_score(score),
            "time_horizon": classify_time_horizon(context),
            "evidence_text": evidence,
            "rationale": f"Auto extracted stock mention from transcript aliases: {';'.join(sorted(aliases))}.",
            "review_status": "approved",
            "reviewer_note": "auto-generated from transcript alias scan; no manual review",
        }
        new_mentions.append(mention)
        report_rows.append(
            {
                "episode_id": episode_id,
                "ticker": ticker,
                "market": market,
                "company_or_theme": str(hit["name"]),
                "matched_aliases": ";".join(sorted(aliases)),
                "line_numbers": ";".join(hit["line_numbers"]),  # type: ignore[arg-type]
                "auto_stance": stance,
                "auto_conviction": mention["conviction"],
                "auto_time_horizon": mention["time_horizon"],
                "evidence_text": evidence,
                "action": "added_approved_auto_mention",
            }
        )
    return new_mentions, report_rows


def main() -> int:
    args = parse_args()
    mentions_path = pathlib.Path(args.mentions_csv)
    fieldnames, mentions = read_csv(mentions_path)
    _, episodes = read_csv(pathlib.Path(args.episodes_csv))
    generated_episode_ids = {
        row["episode_id"]
        for row in episodes
        if not row["episode_id"].startswith("sample_") and row.get("transcript_status") == "generated"
    }
    episodes_by_id = {row["episode_id"]: row for row in episodes}
    paths = combined_transcript_paths(pathlib.Path(args.transcript_dir), generated_episode_ids)
    grouped_hits = scan_transcripts(
        paths=paths,
        aliases=load_company_aliases(pathlib.Path(args.instruments_csv)),
        context_lines=args.context_lines,
    )
    new_mentions, report_rows = build_new_mentions(
        grouped_hits=grouped_hits,
        episodes_by_id=episodes_by_id,
        existing_keys=existing_episode_tickers(mentions),
        include_low_confidence=args.include_low_confidence,
    )

    report_fields = [
        "episode_id",
        "ticker",
        "market",
        "company_or_theme",
        "matched_aliases",
        "line_numbers",
        "auto_stance",
        "auto_conviction",
        "auto_time_horizon",
        "evidence_text",
        "action",
    ]
    if not args.dry_run:
        write_csv(pathlib.Path(args.report), report_fields, report_rows)
        manual_mentions = [row for row in mentions if not row["mention_id"].startswith("auto_")]
        if new_mentions:
            write_csv(pathlib.Path(args.output), fieldnames, manual_mentions + new_mentions)
        elif len(manual_mentions) != len(mentions):
            write_csv(pathlib.Path(args.output), fieldnames, manual_mentions)

    action = "Would add" if args.dry_run else "Added"
    print(
        f"{action} {len(new_mentions)} auto stock mentions "
        f"from {len(paths)} transcripts; hits={len(grouped_hits)}; report_rows={len(report_rows)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
