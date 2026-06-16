#!/usr/bin/env python3
"""Build a readable report for approved company and concept-proxy returns."""

from __future__ import annotations

import argparse
import csv
import pathlib


HORIZONS = [7, 30, 90, 180]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a report for approved company and concept-proxy mention returns."
    )
    parser.add_argument("--mentions-csv", default="data/processed/mentions.csv")
    parser.add_argument("--episodes-csv", default="data/processed/episodes.csv")
    parser.add_argument("--concept-proxies-csv", default="data/processed/concept_proxies.csv")
    parser.add_argument("--returns-csv", default="data/processed/mention_returns.csv")
    parser.add_argument(
        "--output",
        default="reports/approved_company_bullish_returns.csv",
        help="Report CSV to write.",
    )
    return parser.parse_args()


def load_csv(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def pct(value: str) -> str:
    if not value:
        return ""
    return f"{float(value) * 100:.2f}%"


def available_horizons(return_row: dict[str, str]) -> str:
    horizons = [
        f"{horizon}d"
        for horizon in HORIZONS
        if return_row.get(f"return_{horizon}d")
    ]
    return ";".join(horizons)


def active_proxy_concepts(rows: list[dict[str, str]]) -> set[str]:
    return {
        row["concept_name"]
        for row in rows
        if row.get("is_active") == "true" and row.get("ticker") and row.get("market")
    }


def is_report_candidate(mention: dict[str, str], proxy_concepts: set[str]) -> bool:
    if (
        mention["mention_id"].startswith("sample_")
        or mention["review_status"] != "approved"
    ):
        return False
    if mention["mention_type"] == "company":
        return bool(mention["ticker"])
    return mention["stance"] in {"bullish", "bearish"} and mention["company_or_theme"] in proxy_concepts


def build_rows(
    mentions: list[dict[str, str]],
    episodes_by_id: dict[str, dict[str, str]],
    returns_by_mention_id: dict[str, dict[str, str]],
    proxy_concepts: set[str],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for mention in mentions:
        if not is_report_candidate(mention, proxy_concepts):
            continue

        return_row = returns_by_mention_id.get(mention["mention_id"], {})
        episode = episodes_by_id.get(mention["episode_id"], {})
        row = {
            "mention_id": mention["mention_id"],
            "episode_id": mention["episode_id"],
            "episode_title": episode.get("title", ""),
            "published_at": mention["published_at"],
            "company_or_theme": mention["company_or_theme"],
            "ticker": return_row.get("ticker", mention["ticker"]),
            "market": return_row.get("market", mention["market"]),
            "stance": mention["stance"],
            "conviction": mention["conviction"],
            "time_horizon": mention["time_horizon"],
            "base_trade_date": return_row.get("base_trade_date", ""),
            "base_price": return_row.get("base_price", ""),
            "current_trade_date": return_row.get("current_trade_date", ""),
            "current_price": return_row.get("current_price", ""),
            "current_return": return_row.get("current_return", ""),
            "current_return_pct": pct(return_row.get("current_return", "")),
            "benchmark_current_return": return_row.get("benchmark_current_return", ""),
            "benchmark_current_return_pct": pct(return_row.get("benchmark_current_return", "")),
            "excess_current_return": return_row.get("excess_current_return", ""),
            "excess_current_return_pct": pct(return_row.get("excess_current_return", "")),
            "available_horizons": available_horizons(return_row),
            "calculation_status": return_row.get("calculation_status", "missing_return_row"),
            "evidence_text": mention["evidence_text"],
            "return_notes": return_row.get("notes", ""),
        }
        for horizon in HORIZONS:
            row[f"return_{horizon}d"] = return_row.get(f"return_{horizon}d", "")
            row[f"return_{horizon}d_pct"] = pct(return_row.get(f"return_{horizon}d", ""))
            row[f"benchmark_return_{horizon}d"] = return_row.get(f"benchmark_return_{horizon}d", "")
            row[f"benchmark_return_{horizon}d_pct"] = pct(
                return_row.get(f"benchmark_return_{horizon}d", "")
            )
            row[f"excess_return_{horizon}d"] = return_row.get(f"excess_return_{horizon}d", "")
            row[f"excess_return_{horizon}d_pct"] = pct(return_row.get(f"excess_return_{horizon}d", ""))
        rows.append(row)
    return sorted(rows, key=lambda row: (row["published_at"], row["mention_id"]))


def fieldnames() -> list[str]:
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
        "current_trade_date",
        "current_price",
        "current_return",
        "current_return_pct",
        "benchmark_current_return",
        "benchmark_current_return_pct",
        "excess_current_return",
        "excess_current_return_pct",
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


def write_report(path: pathlib.Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    mentions = load_csv(pathlib.Path(args.mentions_csv))
    episodes = {row["episode_id"]: row for row in load_csv(pathlib.Path(args.episodes_csv))}
    proxy_concepts = active_proxy_concepts(load_csv(pathlib.Path(args.concept_proxies_csv)))
    returns = {
        row["mention_id"]: row
        for row in load_csv(pathlib.Path(args.returns_csv))
    }
    rows = build_rows(mentions, episodes, returns, proxy_concepts)
    write_report(pathlib.Path(args.output), rows)
    print(f"Wrote {len(rows)} return report rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
