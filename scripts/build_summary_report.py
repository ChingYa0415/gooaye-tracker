#!/usr/bin/env python3
"""Build a compact summary report for the current data pipeline state."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import dataclass
import pathlib


HORIZONS = [7, 30, 90, 180]


@dataclass(frozen=True)
class SummaryRow:
    section: str
    metric: str
    value: str
    display_value: str
    notes: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create reports/summary.csv.")
    parser.add_argument("--episodes-csv", default="data/processed/episodes.csv")
    parser.add_argument("--mentions-csv", default="data/processed/mentions.csv")
    parser.add_argument("--concept-proxies-csv", default="data/processed/concept_proxies.csv")
    parser.add_argument("--returns-csv", default="data/processed/mention_returns.csv")
    parser.add_argument(
        "--return-report",
        default="reports/approved_company_bullish_returns.csv",
    )
    parser.add_argument("--output", default="reports/summary.csv")
    return parser.parse_args()


def load_csv(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def is_formal(row: dict[str, str], id_field: str) -> bool:
    return not row[id_field].startswith("sample_")


def count_row(section: str, metric: str, count: int, notes: str = "") -> SummaryRow:
    return SummaryRow(section, metric, str(count), str(count), notes)


def percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def number(value: float) -> str:
    return f"{value:.10g}"


def non_empty_floats(rows: list[dict[str, str]], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(field, "")
        if value:
            values.append(float(value))
    return values


def add_counter_rows(
    rows: list[SummaryRow],
    section: str,
    prefix: str,
    counter: Counter[str],
    notes: str = "",
) -> None:
    for key in sorted(counter):
        label = key or "(empty)"
        rows.append(count_row(section, f"{prefix}.{label}", counter[key], notes))


def active_proxy_concepts(rows: list[dict[str, str]]) -> set[str]:
    return {
        row["concept_name"]
        for row in rows
        if row.get("is_active") == "true" and row.get("ticker") and row.get("market")
    }


def build_summary(
    episodes: list[dict[str, str]],
    mentions: list[dict[str, str]],
    concept_proxies: list[dict[str, str]],
    returns: list[dict[str, str]],
    return_report: list[dict[str, str]],
) -> list[SummaryRow]:
    rows: list[SummaryRow] = []
    formal_episodes = [row for row in episodes if is_formal(row, "episode_id")]
    formal_mentions = [row for row in mentions if is_formal(row, "mention_id")]
    formal_returns = [row for row in returns if is_formal(row, "mention_id")]

    approved_mentions = [
        row for row in formal_mentions if row["review_status"] == "approved"
    ]
    return_candidates = [
        row
        for row in approved_mentions
        if row["mention_type"] == "company"
        and bool(row["ticker"])
    ]
    proxy_concepts = active_proxy_concepts(concept_proxies)
    concept_proxy_return_candidates = [
        row
        for row in approved_mentions
        if row["mention_type"] != "company"
        and row["stance"] in {"bullish", "bearish"}
        and row["company_or_theme"] in proxy_concepts
    ]
    needs_context = [
        row for row in formal_mentions if row["review_status"] == "needs_context"
    ]

    rows.extend(
        [
            count_row("episodes", "formal_total", len(formal_episodes)),
            count_row("mentions", "formal_total", len(formal_mentions)),
            count_row("mentions", "approved_total", len(approved_mentions)),
            count_row("mentions", "needs_context_total", len(needs_context)),
            count_row("returns", "formal_total", len(formal_returns)),
            count_row("returns", "company_return_candidates", len(return_candidates)),
            count_row("returns", "concept_proxy_return_candidates", len(concept_proxy_return_candidates)),
            count_row(
                "returns",
                "total_return_candidates",
                len(return_candidates) + len(concept_proxy_return_candidates),
            ),
            count_row("reports", "approved_company_bullish_returns_rows", len(return_report)),
        ]
    )

    add_counter_rows(
        rows,
        "mentions",
        "review_status",
        Counter(row["review_status"] for row in formal_mentions),
    )
    add_counter_rows(
        rows,
        "mentions",
        "mention_type",
        Counter(row["mention_type"] for row in formal_mentions),
    )
    add_counter_rows(
        rows,
        "mentions",
        "stance",
        Counter(row["stance"] for row in formal_mentions),
    )
    add_counter_rows(
        rows,
        "returns",
        "calculation_status",
        Counter(row["calculation_status"] for row in formal_returns),
    )
    add_counter_rows(
        rows,
        "reports",
        "available_horizons",
        Counter(row["available_horizons"] or "(none)" for row in return_report),
    )

    for horizon in HORIZONS:
        mention_returns = non_empty_floats(return_report, f"return_{horizon}d")
        benchmark_returns = non_empty_floats(return_report, f"benchmark_return_{horizon}d")
        excess_returns = non_empty_floats(return_report, f"excess_return_{horizon}d")
        hit_count = sum(1 for value in mention_returns if value > 0)
        count = len(mention_returns)

        rows.append(
            count_row(
                "performance",
                f"{horizon}d.available_count",
                count,
                "rows with available mention return",
            )
        )
        if count:
            avg_return = sum(mention_returns) / count
            hit_rate = hit_count / count
            rows.append(
                SummaryRow(
                    "performance",
                    f"{horizon}d.avg_return",
                    number(avg_return),
                    percent(avg_return),
                    "stance-adjusted mention return",
                )
            )
            rows.append(
                SummaryRow(
                    "performance",
                    f"{horizon}d.hit_rate",
                    number(hit_rate),
                    percent(hit_rate),
                    "share of available returns above zero",
                )
            )
        if benchmark_returns:
            avg_benchmark = sum(benchmark_returns) / len(benchmark_returns)
            rows.append(
                SummaryRow(
                    "performance",
                    f"{horizon}d.avg_benchmark_return",
                    number(avg_benchmark),
                    percent(avg_benchmark),
                    "benchmark return over the same horizon",
                )
            )
        if excess_returns:
            avg_excess = sum(excess_returns) / len(excess_returns)
            rows.append(
                SummaryRow(
                    "performance",
                    f"{horizon}d.avg_excess_return",
                    number(avg_excess),
                    percent(avg_excess),
                    "mention return minus benchmark return",
                )
            )

    return rows


def write_summary(path: pathlib.Path, rows: list[SummaryRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["section", "metric", "value", "display_value", "notes"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def main() -> int:
    args = parse_args()
    rows = build_summary(
        episodes=load_csv(pathlib.Path(args.episodes_csv)),
        mentions=load_csv(pathlib.Path(args.mentions_csv)),
        concept_proxies=load_csv(pathlib.Path(args.concept_proxies_csv)),
        returns=load_csv(pathlib.Path(args.returns_csv)),
        return_report=load_csv(pathlib.Path(args.return_report)),
    )
    write_summary(pathlib.Path(args.output), rows)
    print(f"Wrote {len(rows)} summary rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
