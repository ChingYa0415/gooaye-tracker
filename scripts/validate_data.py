#!/usr/bin/env python3
"""Validate core CSV data and generated reports."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import dataclass
from datetime import date
import pathlib


HORIZONS = [7, 30, 90, 180]

EXPECTED_FIELDS = {
    "data/processed/episodes.csv": [
        "episode_id",
        "source_name",
        "source_type",
        "title",
        "published_at",
        "url",
        "duration_seconds",
        "transcript_status",
        "notes",
    ],
    "data/processed/mentions.csv": [
        "mention_id",
        "episode_id",
        "published_at",
        "company_or_theme",
        "ticker",
        "market",
        "mention_type",
        "stance",
        "conviction",
        "time_horizon",
        "evidence_text",
        "rationale",
        "review_status",
        "reviewer_note",
    ],
    "data/processed/instruments.csv": [
        "instrument_id",
        "ticker",
        "market",
        "name",
        "aliases",
        "industry",
        "benchmark",
        "is_active",
        "notes",
    ],
    "data/processed/concept_proxies.csv": [
        "concept_name",
        "proxy_id",
        "ticker",
        "market",
        "name",
        "weight",
        "benchmark_market",
        "is_active",
        "notes",
    ],
    "data/processed/mention_returns.csv": [
        "mention_id",
        "ticker",
        "market",
        "stance",
        "base_trade_date",
        "base_price",
        "return_7d",
        "return_30d",
        "return_90d",
        "return_180d",
        "benchmark_return_7d",
        "benchmark_return_30d",
        "benchmark_return_90d",
        "benchmark_return_180d",
        "excess_return_7d",
        "excess_return_30d",
        "excess_return_90d",
        "excess_return_180d",
        "calculation_status",
        "notes",
    ],
    "data/processed/transcript_inputs.csv": [
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
    ],
    "data/processed/audio_downloads.csv": [
        "episode_id",
        "title",
        "audio_path",
        "audio_bytes",
        "sha256",
        "duration_seconds",
        "download_status",
        "downloaded_at",
        "notes",
    ],
    "data/processed/audio_chunks.csv": [
        "episode_id",
        "title",
        "chunk_index",
        "chunk_path",
        "chunk_bytes",
        "split_seconds",
        "chunk_status",
        "created_at",
        "notes",
    ],
    "data/processed/transcription_runs.csv": [
        "episode_id",
        "chunk_index",
        "chunk_path",
        "transcript_path",
        "model",
        "transcription_status",
        "notes",
    ],
    "reports/pending_mentions_review.csv": [
        "mention_id",
        "episode_id",
        "published_at",
        "episode_title",
        "company_or_theme",
        "ticker",
        "market",
        "mention_type",
        "current_stance",
        "current_conviction",
        "current_time_horizon",
        "evidence_text",
        "rationale",
        "reviewer_note",
        "transcript_line",
        "transcript_context",
        "review_decision",
        "corrected_stance",
        "corrected_conviction",
        "corrected_time_horizon",
        "corrected_evidence_text",
        "review_comment",
    ],
    "reports/concept_proxy_review.csv": [
        "concept_name",
        "concept_issue",
        "directional_mention_count",
        "active_proxy_count",
        "active_weight_total",
        "return_status_counts",
        "proxy_id",
        "ticker",
        "market",
        "name",
        "weight",
        "benchmark_market",
        "is_active",
        "current_notes",
        "review_decision",
        "corrected_weight",
        "corrected_benchmark_market",
        "corrected_is_active",
        "replacement_ticker",
        "replacement_market",
        "replacement_name",
        "review_comment",
    ],
    "reports/new_episodes.csv": [
        "episode_id",
        "published_at",
        "title",
        "url",
        "audio_url",
        "duration_seconds",
        "next_action",
    ],
    "reports/auto_stock_mentions.csv": [
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
    ],
}


ALLOWED = {
    "source_type": {"podcast", "youtube", "threads", "article", "manual"},
    "transcript_status": {"missing", "manual", "imported", "generated", "reviewed", "downloaded", "error"},
    "market": {"TWSE", "TPEx", "US", "HK", "concept", "unknown"},
    "mention_type": {"company", "industry", "theme", "index", "commodity"},
    "stance": {"bullish", "bearish", "neutral", "watch", "past_review", "unclear"},
    "conviction": {"low", "medium", "high"},
    "time_horizon": {"short", "medium", "long", "unclear"},
    "review_status": {"pending", "approved", "rejected", "needs_context"},
    "calculation_status": {"pending_price", "calculated", "missing_price", "not_applicable", "error"},
}


@dataclass
class Table:
    fieldnames: list[str]
    rows: list[dict[str, str]]


class ValidationError(Exception):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate gooaye tracker CSV data.")
    parser.add_argument("--root", default=".", help="Project root directory.")
    return parser.parse_args()


def read_table(path: pathlib.Path) -> Table:
    if not path.exists():
        raise ValidationError(f"Missing required CSV: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    if not rows:
        raise ValidationError(f"Empty CSV: {path}")
    expected_count = len(rows[0])
    bad_rows = [
        f"line {line_no} has {len(row)} fields"
        for line_no, row in enumerate(rows, start=1)
        if len(row) != expected_count
    ]
    if bad_rows:
        raise ValidationError(f"{path}: inconsistent field counts: {bad_rows[:5]}")

    with path.open("r", encoding="utf-8", newline="") as handle:
        dict_reader = csv.DictReader(handle)
        return Table(list(dict_reader.fieldnames or []), list(dict_reader))


def require_fields(path: pathlib.Path, table: Table, expected: list[str]) -> None:
    if table.fieldnames != expected:
        raise ValidationError(
            f"{path}: unexpected fields\nexpected={expected}\nactual={table.fieldnames}"
        )


def validate_date(value: str, label: str) -> None:
    if not value:
        return
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{label}: invalid date {value}") from exc


def validate_float(value: str, label: str) -> None:
    if not value:
        return
    try:
        float(value)
    except ValueError as exc:
        raise ValidationError(f"{label}: invalid number {value}") from exc


def require_unique(rows: list[dict[str, str]], field: str, table_name: str) -> None:
    values = [row[field] for row in rows if row.get(field)]
    duplicates = sorted(value for value, count in Counter(values).items() if count > 1)
    if duplicates:
        raise ValidationError(f"{table_name}: duplicate {field}: {duplicates[:10]}")


def validate_allowed(rows: list[dict[str, str]], field: str, allowed: set[str], table_name: str) -> None:
    invalid = sorted({row.get(field, "") for row in rows if row.get(field, "") not in allowed})
    if invalid:
        raise ValidationError(f"{table_name}: invalid {field}: {invalid}")


def is_formal(row: dict[str, str], id_field: str) -> bool:
    return not row[id_field].startswith("sample_")


def active_proxy_concepts(rows: list[dict[str, str]]) -> set[str]:
    return {
        row["concept_name"]
        for row in rows
        if row.get("is_active") == "true" and row.get("ticker") and row.get("market") in {"TWSE", "TPEx", "US"}
    }


def is_return_candidate(mention: dict[str, str], proxy_concepts: set[str]) -> bool:
    if (
        not is_formal(mention, "mention_id")
        or mention["review_status"] != "approved"
    ):
        return False
    if mention["mention_type"] == "company":
        return bool(mention["ticker"])
    return mention["stance"] in {"bullish", "bearish"} and mention["company_or_theme"] in proxy_concepts


def validate_price_files(root: pathlib.Path) -> int:
    price_paths = sorted((root / "data/prices").glob("*.csv"))
    expected = ["symbol", "trade_date", "close", "adj_close", "volume"]
    for path in price_paths:
        table = read_table(path)
        require_fields(path, table, expected)
        if not table.rows:
            raise ValidationError(f"{path}: price file has no data rows")
        for row in table.rows:
            validate_date(row["trade_date"], f"{path}:{row.get('symbol', '')}")
            validate_float(row["close"], f"{path}:close")
            validate_float(row["adj_close"], f"{path}:adj_close")
    return len(price_paths)


def validate_dashboard(root: pathlib.Path) -> None:
    path = root / "reports/dashboard.html"
    if not path.exists():
        raise ValidationError("Missing dashboard report: reports/dashboard.html")
    text = path.read_text(encoding="utf-8")
    required_fragments = [
        "<title>股癌追蹤 Dashboard</title>",
        'id="return-data"',
        'id="proxy-data"',
        'id="signalsBody"',
        'id="proxyBody"',
    ]
    missing = [fragment for fragment in required_fragments if fragment not in text]
    if missing:
        raise ValidationError(f"reports/dashboard.html missing fragments: {missing}")


def validate(root: pathlib.Path) -> list[str]:
    tables: dict[str, Table] = {}
    for relative_path, expected_fields in EXPECTED_FIELDS.items():
        path = root / relative_path
        table = read_table(path)
        require_fields(path, table, expected_fields)
        tables[relative_path] = table

    episodes = tables["data/processed/episodes.csv"].rows
    mentions = tables["data/processed/mentions.csv"].rows
    instruments = tables["data/processed/instruments.csv"].rows
    concept_proxies = tables["data/processed/concept_proxies.csv"].rows
    returns = tables["data/processed/mention_returns.csv"].rows
    report = read_table(root / "reports/approved_company_bullish_returns.csv")
    require_fields(root / "reports/approved_company_bullish_returns.csv", report, return_report_fields())
    concept_proxy_review = tables["reports/concept_proxy_review.csv"].rows
    new_episodes = tables["reports/new_episodes.csv"].rows
    auto_stock_mentions = tables["reports/auto_stock_mentions.csv"].rows
    summary = read_table(root / "reports/summary.csv")
    require_fields(root / "reports/summary.csv", summary, summary_fields())

    require_unique(episodes, "episode_id", "episodes.csv")
    require_unique(mentions, "mention_id", "mentions.csv")
    require_unique(instruments, "instrument_id", "instruments.csv")
    require_unique(concept_proxies, "proxy_id", "concept_proxies.csv")
    require_unique(returns, "mention_id", "mention_returns.csv")

    validate_allowed(episodes, "source_type", ALLOWED["source_type"], "episodes.csv")
    validate_allowed(mentions, "market", ALLOWED["market"], "mentions.csv")
    validate_allowed(mentions, "mention_type", ALLOWED["mention_type"], "mentions.csv")
    validate_allowed(mentions, "stance", ALLOWED["stance"], "mentions.csv")
    validate_allowed(mentions, "conviction", ALLOWED["conviction"], "mentions.csv")
    validate_allowed(mentions, "time_horizon", ALLOWED["time_horizon"], "mentions.csv")
    validate_allowed(mentions, "review_status", ALLOWED["review_status"], "mentions.csv")
    validate_allowed(returns, "calculation_status", ALLOWED["calculation_status"], "mention_returns.csv")

    episode_ids = {row["episode_id"] for row in episodes}
    mention_ids = {row["mention_id"] for row in mentions}
    proxy_concepts = active_proxy_concepts(concept_proxies)
    approved_ids = {
        row["mention_id"]
        for row in mentions
        if is_formal(row, "mention_id") and row["review_status"] == "approved"
    }
    candidate_ids = {row["mention_id"] for row in mentions if is_return_candidate(row, proxy_concepts)}

    for row in concept_proxies:
        if row["is_active"] not in {"true", "false"}:
            raise ValidationError(f"concept_proxies.csv:{row['proxy_id']} invalid is_active")
        validate_float(row["weight"], f"concept_proxies.csv:{row['proxy_id']}:weight")
        if row["is_active"] == "true":
            if not row["concept_name"] or not row["ticker"] or not row["name"]:
                raise ValidationError(f"concept_proxies.csv:{row['proxy_id']} active row is incomplete")
            if row["market"] not in {"TWSE", "TPEx", "US"}:
                raise ValidationError(f"concept_proxies.csv:{row['proxy_id']} unsupported market")
            if row["benchmark_market"] not in {"TWSE", "TPEx", "US"}:
                raise ValidationError(f"concept_proxies.csv:{row['proxy_id']} unsupported benchmark_market")
            if float(row["weight"]) <= 0:
                raise ValidationError(f"concept_proxies.csv:{row['proxy_id']} active weight must be positive")

    proxy_ids = {row["proxy_id"] for row in concept_proxies}
    review_proxy_ids = {row["proxy_id"] for row in concept_proxy_review}
    if review_proxy_ids != proxy_ids:
        missing = sorted(proxy_ids - review_proxy_ids)
        extra = sorted(review_proxy_ids - proxy_ids)
        raise ValidationError(f"concept_proxy_review.csv mismatch: missing={missing}, extra={extra}")
    for row in concept_proxy_review:
        validate_float(row["directional_mention_count"], f"concept_proxy_review.csv:{row['proxy_id']}:directional_mention_count")
        validate_float(row["active_proxy_count"], f"concept_proxy_review.csv:{row['proxy_id']}:active_proxy_count")
        validate_float(row["active_weight_total"], f"concept_proxy_review.csv:{row['proxy_id']}:active_weight_total")
        validate_float(row["weight"], f"concept_proxy_review.csv:{row['proxy_id']}:weight")
    for row in new_episodes:
        validate_date(row["published_at"], f"new_episodes.csv:{row['episode_id']}")
        if row["episode_id"] not in mention_ids and row["episode_id"] not in episode_ids:
            raise ValidationError(f"new_episodes.csv:{row['episode_id']} references missing episode")
        if row["next_action"] != "download_audio":
            raise ValidationError(f"new_episodes.csv:{row['episode_id']} unexpected next_action")
    for row in auto_stock_mentions:
        if row["episode_id"] not in episode_ids:
            raise ValidationError(f"auto_stock_mentions.csv:{row['episode_id']} references missing episode")
        if row["market"] not in {"TWSE", "TPEx", "US"}:
            raise ValidationError(f"auto_stock_mentions.csv:{row['episode_id']} unsupported market")
        if row["auto_stance"]:
            validate_allowed([row], "auto_stance", ALLOWED["stance"], "auto_stock_mentions.csv")
        if row["auto_conviction"]:
            validate_allowed([row], "auto_conviction", ALLOWED["conviction"], "auto_stock_mentions.csv")
        if row["auto_time_horizon"]:
            validate_allowed([row], "auto_time_horizon", ALLOWED["time_horizon"], "auto_stock_mentions.csv")
        if row["action"] not in {
            "added_approved_auto_mention",
            "skipped_existing_mention",
            "skipped_low_confidence",
        }:
            raise ValidationError(f"auto_stock_mentions.csv:{row['episode_id']} unexpected action")

    for row in episodes:
        validate_date(row["published_at"], f"episodes.csv:{row['episode_id']}")
    for row in mentions:
        validate_date(row["published_at"], f"mentions.csv:{row['mention_id']}")
        if row["episode_id"] not in episode_ids:
            raise ValidationError(f"mentions.csv:{row['mention_id']} references missing episode")
        if is_formal(row, "mention_id") and row["review_status"] == "approved":
            if not row["evidence_text"]:
                raise ValidationError(f"mentions.csv:{row['mention_id']} approved row has no evidence_text")
            if row["stance"] in {"bullish", "bearish"} and row["mention_type"] == "company" and not row["ticker"]:
                raise ValidationError(f"mentions.csv:{row['mention_id']} company return candidate has no ticker")

    formal_return_ids = {row["mention_id"] for row in returns if is_formal(row, "mention_id")}
    if formal_return_ids != approved_ids:
        missing = sorted(approved_ids - formal_return_ids)
        extra = sorted(formal_return_ids - approved_ids)
        raise ValidationError(f"mention_returns.csv mismatch: missing={missing}, extra={extra}")

    for row in returns:
        if row["mention_id"] not in mention_ids and not row["mention_id"].startswith("sample_"):
            raise ValidationError(f"mention_returns.csv:{row['mention_id']} references missing mention")
        if is_formal(row, "mention_id") and row["calculation_status"] in {"pending_price", "calculated"}:
            if not row["base_trade_date"] or not row["base_price"]:
                raise ValidationError(f"mention_returns.csv:{row['mention_id']} missing base price fields")
        validate_date(row["base_trade_date"], f"mention_returns.csv:{row['mention_id']}")
        validate_float(row["base_price"], f"mention_returns.csv:{row['mention_id']}:base_price")
        for horizon in HORIZONS:
            validate_float(row[f"return_{horizon}d"], f"mention_returns.csv:{row['mention_id']}:return_{horizon}d")
            validate_float(
                row[f"benchmark_return_{horizon}d"],
                f"mention_returns.csv:{row['mention_id']}:benchmark_return_{horizon}d",
            )
            validate_float(
                row[f"excess_return_{horizon}d"],
                f"mention_returns.csv:{row['mention_id']}:excess_return_{horizon}d",
            )

    report_ids = {row["mention_id"] for row in report.rows}
    if report_ids != candidate_ids:
        missing = sorted(candidate_ids - report_ids)
        extra = sorted(report_ids - candidate_ids)
        raise ValidationError(f"return report mismatch: missing={missing}, extra={extra}")

    for row in report.rows:
        if row["calculation_status"] == "missing_return_row":
            raise ValidationError(f"return report:{row['mention_id']} is missing return row")

    validate_summary(summary.rows)

    price_file_count = validate_price_files(root)
    validate_dashboard(root)
    formal_mentions = [row for row in mentions if is_formal(row, "mention_id")]
    review_counts = Counter(row["review_status"] for row in formal_mentions)
    return_counts = Counter(row["calculation_status"] for row in returns if is_formal(row, "mention_id"))
    available_counts = Counter(row["available_horizons"] or "(none)" for row in report.rows)

    return [
        "OK data validation passed",
        f"episodes={len([row for row in episodes if is_formal(row, 'episode_id')])} formal",
        f"mentions={len(formal_mentions)} formal review_status={dict(sorted(review_counts.items()))}",
        f"mention_returns={len(formal_return_ids)} formal calculation_status={dict(sorted(return_counts.items()))}",
        f"return_report={len(report.rows)} rows available_horizons={dict(sorted(available_counts.items()))}",
        f"summary={len(summary.rows)} rows",
        "dashboard=reports/dashboard.html",
        f"price_files={price_file_count}",
    ]


def return_report_fields() -> list[str]:
    fields = [
        "mention_id",
        "episode_id",
        "episode_title",
        "published_at",
        "company_or_theme",
        "ticker",
        "market",
        "stance",
        "conviction",
        "time_horizon",
        "base_trade_date",
        "base_price",
        "available_horizons",
        "calculation_status",
        "evidence_text",
        "return_notes",
    ]
    for horizon in HORIZONS:
        fields.extend(
            [
                f"return_{horizon}d",
                f"return_{horizon}d_pct",
                f"benchmark_return_{horizon}d",
                f"benchmark_return_{horizon}d_pct",
                f"excess_return_{horizon}d",
                f"excess_return_{horizon}d_pct",
            ]
        )
    return fields


def summary_fields() -> list[str]:
    return ["section", "metric", "value", "display_value", "notes"]


def validate_summary(rows: list[dict[str, str]]) -> None:
    required_metrics = {
        "episodes.formal_total",
        "mentions.formal_total",
        "mentions.approved_total",
        "mentions.needs_context_total",
        "returns.formal_total",
        "returns.company_return_candidates",
        "returns.concept_proxy_return_candidates",
        "returns.total_return_candidates",
        "reports.approved_company_bullish_returns_rows",
    }
    actual_metrics = {f"{row['section']}.{row['metric']}" for row in rows}
    missing = sorted(required_metrics - actual_metrics)
    if missing:
        raise ValidationError(f"summary.csv missing metrics: {missing}")

    for row in rows:
        if not row["section"] or not row["metric"]:
            raise ValidationError("summary.csv has blank section or metric")
        validate_float(row["value"], f"summary.csv:{row['section']}.{row['metric']}")


def main() -> int:
    args = parse_args()
    try:
        lines = validate(pathlib.Path(args.root))
    except ValidationError as exc:
        print(f"ERROR {exc}")
        return 1
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
