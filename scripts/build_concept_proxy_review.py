#!/usr/bin/env python3
"""Build a manual review worksheet for concept proxy baskets."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
import pathlib


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a concept proxy review worksheet.")
    parser.add_argument("--concept-proxies-csv", default="data/processed/concept_proxies.csv")
    parser.add_argument("--mentions-csv", default="data/processed/mentions.csv")
    parser.add_argument("--returns-csv", default="data/processed/mention_returns.csv")
    parser.add_argument(
        "--output",
        default="reports/concept_proxy_review.csv",
        help="Review worksheet CSV to write.",
    )
    return parser.parse_args()


def load_csv(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def is_formal(row: dict[str, str], id_field: str) -> bool:
    return not row[id_field].startswith("sample_")


def is_directional_concept_mention(row: dict[str, str]) -> bool:
    return (
        is_formal(row, "mention_id")
        and row["review_status"] == "approved"
        and row["mention_type"] != "company"
        and row["stance"] in {"bullish", "bearish"}
    )


def is_active_proxy(row: dict[str, str]) -> bool:
    return row.get("is_active") == "true" and bool(row.get("ticker")) and bool(row.get("market"))


def concept_issue(
    concept_name: str,
    active_rows: list[dict[str, str]],
    all_rows: list[dict[str, str]],
    directional_mentions: int,
) -> str:
    issues: list[str] = []
    if not active_rows:
        issues.append("no_active_proxy")
    elif len(active_rows) == 1:
        issues.append("single_name_proxy")

    active_weight_total = sum(float(row["weight"] or 0) for row in active_rows)
    if active_rows and abs(active_weight_total - 1) > 0.0001:
        issues.append(f"active_weight_total={active_weight_total:.6g}")

    active_markets = {row["market"] for row in active_rows}
    if len(active_markets) > 1:
        issues.append("mixed_component_markets")

    benchmark_markets = {row["benchmark_market"] for row in active_rows if row.get("benchmark_market")}
    if len(benchmark_markets) > 1:
        issues.append("mixed_benchmark_markets")

    if directional_mentions and not active_rows:
        issues.append("mentioned_but_not_trackable")
    if not directional_mentions and active_rows:
        issues.append("proxy_defined_before_mentions")
    if any(row.get("is_active") == "false" for row in all_rows):
        issues.append("has_inactive_rows")
    if concept_name in {"功率元件", "功率半導體"} and len(active_rows) == 1:
        issues.append("needs_sector_expansion")
    return ";".join(issues) or "ok"


def return_status_by_concept(returns: list[dict[str, str]]) -> dict[str, Counter[str]]:
    result: dict[str, Counter[str]] = defaultdict(Counter)
    for row in returns:
        ticker = row.get("ticker", "")
        if not ticker.startswith("concept_proxy:"):
            continue
        concept_name = ticker.split(":", 1)[1]
        result[concept_name][row.get("calculation_status", "")] += 1
    return result


def build_rows(
    proxies: list[dict[str, str]],
    mentions: list[dict[str, str]],
    returns: list[dict[str, str]],
) -> list[dict[str, str]]:
    proxies_by_concept: dict[str, list[dict[str, str]]] = defaultdict(list)
    for proxy in proxies:
        proxies_by_concept[proxy["concept_name"]].append(proxy)

    mention_counts = Counter(
        row["company_or_theme"]
        for row in mentions
        if is_directional_concept_mention(row)
    )
    return_status = return_status_by_concept(returns)

    rows: list[dict[str, str]] = []
    for concept_name in sorted(proxies_by_concept):
        concept_rows = proxies_by_concept[concept_name]
        active_rows = [row for row in concept_rows if is_active_proxy(row)]
        active_weight_total = sum(float(row["weight"] or 0) for row in active_rows)
        issue = concept_issue(
            concept_name,
            active_rows,
            concept_rows,
            mention_counts[concept_name],
        )
        status_counts = return_status.get(concept_name, Counter())
        concept_status = ";".join(
            f"{status}:{count}" for status, count in sorted(status_counts.items()) if status
        )

        for proxy in sorted(concept_rows, key=lambda row: (row["is_active"] != "true", row["proxy_id"])):
            rows.append(
                {
                    "concept_name": concept_name,
                    "concept_issue": issue,
                    "directional_mention_count": str(mention_counts[concept_name]),
                    "active_proxy_count": str(len(active_rows)),
                    "active_weight_total": f"{active_weight_total:.10g}",
                    "return_status_counts": concept_status,
                    "proxy_id": proxy["proxy_id"],
                    "ticker": proxy["ticker"],
                    "market": proxy["market"],
                    "name": proxy["name"],
                    "weight": proxy["weight"],
                    "benchmark_market": proxy["benchmark_market"],
                    "is_active": proxy["is_active"],
                    "current_notes": proxy["notes"],
                    "review_decision": "",
                    "corrected_weight": "",
                    "corrected_benchmark_market": "",
                    "corrected_is_active": "",
                    "replacement_ticker": "",
                    "replacement_market": "",
                    "replacement_name": "",
                    "review_comment": "",
                }
            )
    return rows


def fieldnames() -> list[str]:
    return [
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
    ]


def write_rows(path: pathlib.Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    rows = build_rows(
        proxies=load_csv(pathlib.Path(args.concept_proxies_csv)),
        mentions=load_csv(pathlib.Path(args.mentions_csv)),
        returns=load_csv(pathlib.Path(args.returns_csv)),
    )
    write_rows(pathlib.Path(args.output), rows)
    print(f"Wrote {len(rows)} concept proxy review rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
