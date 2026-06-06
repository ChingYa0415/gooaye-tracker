#!/usr/bin/env python3
"""Fetch daily prices and calculate first-pass mention returns."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import pathlib
import time
import urllib.parse
import urllib.request


YAHOO_SYMBOLS = {
    "TWSE": lambda ticker: f"{ticker}.TW",
    "TPEx": lambda ticker: f"{ticker}.TWO",
    "US": lambda ticker: ticker,
}

BENCHMARK_SYMBOLS = {
    "TWSE": "^TWII",
    "TPEx": "^TWOII",
    "US": "^IXIC",
}

HORIZONS = [7, 30, 90, 180]


@dataclass(frozen=True)
class PriceRow:
    trade_date: date
    close: float
    adj_close: float
    volume: int


@dataclass(frozen=True)
class ConceptProxy:
    concept_name: str
    proxy_id: str
    ticker: str
    market: str
    name: str
    weight: float
    benchmark_market: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Yahoo daily prices and update mention_returns.csv."
    )
    parser.add_argument("--mentions-csv", default="data/processed/mentions.csv")
    parser.add_argument("--concept-proxies-csv", default="data/processed/concept_proxies.csv")
    parser.add_argument("--returns-csv", default="data/processed/mention_returns.csv")
    parser.add_argument("--prices-dir", default="data/prices")
    parser.add_argument(
        "--start-date",
        default="2026-01-01",
        help="Fetch prices from this date.",
    )
    parser.add_argument(
        "--end-date",
        default=date.today().isoformat(),
        help="Fetch prices through this date. Defaults to today.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.2,
        help="Delay between Yahoo requests.",
    )
    return parser.parse_args()


def load_csv(path: pathlib.Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def load_concept_proxies(path: pathlib.Path) -> dict[str, list[ConceptProxy]]:
    if not path.exists():
        return {}
    _, rows = load_csv(path)
    proxies_by_concept: dict[str, list[ConceptProxy]] = {}
    for row in rows:
        if row.get("is_active") != "true":
            continue
        if not row.get("ticker") or row.get("market") not in YAHOO_SYMBOLS:
            continue
        proxy = ConceptProxy(
            concept_name=row["concept_name"],
            proxy_id=row["proxy_id"],
            ticker=row["ticker"],
            market=row["market"],
            name=row["name"],
            weight=float(row["weight"]),
            benchmark_market=row["benchmark_market"],
        )
        proxies_by_concept.setdefault(proxy.concept_name, []).append(proxy)
    return proxies_by_concept


def yahoo_symbol(ticker: str, market: str) -> str:
    try:
        return YAHOO_SYMBOLS[market](ticker)
    except KeyError as exc:
        raise ValueError(f"Unsupported market for Yahoo symbol: {market}") from exc


def yahoo_url(symbol: str, start_date: date, end_date: date) -> str:
    period1 = int(datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    period2 = int(
        datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp()
    )
    encoded_symbol = urllib.parse.quote(symbol, safe="")
    return (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}"
        f"?period1={period1}&period2={period2}&interval=1d&events=history"
    )


def fetch_yahoo_prices(symbol: str, start_date: date, end_date: date) -> list[PriceRow]:
    request = urllib.request.Request(
        yahoo_url(symbol, start_date, end_date),
        headers={"User-Agent": "Mozilla/5.0 gooaye-tracker/0.1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)

    chart = payload.get("chart", {})
    error = chart.get("error")
    if error:
        raise ValueError(f"Yahoo chart error for {symbol}: {error}")

    results = chart.get("result") or []
    if not results:
        return []

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    adjclose_rows = result.get("indicators", {}).get("adjclose") or [{}]
    adjcloses = adjclose_rows[0].get("adjclose") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    rows: list[PriceRow] = []
    for index, timestamp in enumerate(timestamps):
        close = closes[index] if index < len(closes) else None
        adj_close = adjcloses[index] if index < len(adjcloses) else close
        if close is None and adj_close is None:
            continue
        volume = volumes[index] if index < len(volumes) and volumes[index] is not None else 0
        rows.append(
            PriceRow(
                trade_date=datetime.fromtimestamp(timestamp, tz=timezone.utc).date(),
                close=float(close if close is not None else adj_close),
                adj_close=float(adj_close if adj_close is not None else close),
                volume=int(volume),
            )
        )
    return rows


def price_path(prices_dir: pathlib.Path, symbol: str) -> pathlib.Path:
    safe_symbol = symbol.replace("^", "INDEX_").replace(".", "_").replace("/", "_")
    return prices_dir / f"{safe_symbol}.csv"


def write_prices(path: pathlib.Path, symbol: str, rows: list[PriceRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["symbol", "trade_date", "close", "adj_close", "volume"],
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "symbol": symbol,
                    "trade_date": row.trade_date.isoformat(),
                    "close": format_number(row.close),
                    "adj_close": format_number(row.adj_close),
                    "volume": row.volume,
                }
            )


def format_number(value: float | str | None) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    return f"{value:.10g}"


def approved_mentions(mentions: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in mentions
        if not row["mention_id"].startswith("sample_") and row["review_status"] == "approved"
    ]


def needed_symbols(
    mentions: list[dict[str, str]],
    concept_proxies: dict[str, list[ConceptProxy]],
) -> set[str]:
    symbols: set[str] = set()
    for mention in mentions:
        ticker = mention.get("ticker", "")
        market = mention.get("market", "")
        if mention.get("stance") not in {"bullish", "bearish"}:
            continue
        if mention.get("mention_type") == "company":
            if not ticker or market not in YAHOO_SYMBOLS:
                continue
            symbols.add(yahoo_symbol(ticker, market))
            benchmark_symbol = BENCHMARK_SYMBOLS.get(market)
            if benchmark_symbol:
                symbols.add(benchmark_symbol)
            continue

        proxies = concept_proxies.get(mention.get("company_or_theme", ""), [])
        for proxy in proxies:
            symbols.add(yahoo_symbol(proxy.ticker, proxy.market))
        benchmark_market = concept_benchmark_market(proxies)
        benchmark_symbol = BENCHMARK_SYMBOLS.get(benchmark_market, "")
        if benchmark_symbol:
            symbols.add(benchmark_symbol)
    return symbols


def concept_benchmark_market(proxies: list[ConceptProxy]) -> str:
    for proxy in proxies:
        if proxy.benchmark_market:
            return proxy.benchmark_market
    return ""


def load_price_map(rows: list[PriceRow]) -> dict[date, float]:
    return {row.trade_date: row.adj_close for row in rows}


def first_trade_on_or_after(prices: dict[date, float], target: date) -> tuple[date, float] | None:
    for trade_date in sorted(prices):
        if trade_date >= target:
            return trade_date, prices[trade_date]
    return None


def calc_return(base_price: float, target_price: float, stance: str) -> float:
    raw_return = target_price / base_price - 1
    if stance == "bearish":
        return -raw_return
    return raw_return


def weighted_average(values: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for weight, _ in values)
    if total_weight <= 0:
        raise ValueError("Cannot calculate weighted average with non-positive total weight")
    return sum(weight * value for weight, value in values) / total_weight


def empty_return_row(mention: dict[str, str], status: str, notes: str) -> dict[str, str]:
    row = {
        "mention_id": mention["mention_id"],
        "ticker": mention.get("ticker", ""),
        "market": mention.get("market", ""),
        "stance": mention.get("stance", ""),
        "base_trade_date": "",
        "base_price": "",
        "calculation_status": status,
        "notes": notes,
    }
    for horizon in HORIZONS:
        row[f"return_{horizon}d"] = ""
        row[f"benchmark_return_{horizon}d"] = ""
        row[f"excess_return_{horizon}d"] = ""
    return row


def calculate_company_return_row(
    mention: dict[str, str],
    prices_by_symbol: dict[str, dict[date, float]],
) -> dict[str, str]:
    if not mention["ticker"]:
        return empty_return_row(mention, "not_applicable", "approved company mention has no ticker")
    if mention["market"] not in YAHOO_SYMBOLS:
        return empty_return_row(mention, "not_applicable", "market is not supported by first price fetcher")

    symbol = yahoo_symbol(mention["ticker"], mention["market"])
    benchmark_symbol = BENCHMARK_SYMBOLS.get(mention["market"], "")
    prices = prices_by_symbol.get(symbol, {})
    benchmark_prices = prices_by_symbol.get(benchmark_symbol, {}) if benchmark_symbol else {}
    published_at = date.fromisoformat(mention["published_at"])
    base = first_trade_on_or_after(prices, published_at + timedelta(days=1))
    if base is None:
        return empty_return_row(mention, "missing_price", f"missing base price for {symbol}")

    base_date, base_price = base
    benchmark_base = first_trade_on_or_after(benchmark_prices, base_date) if benchmark_prices else None

    row = empty_return_row(mention, "calculated", f"price source Yahoo chart symbol={symbol}")
    row["base_trade_date"] = base_date.isoformat()
    row["base_price"] = format_number(base_price)
    pending_targets = 0

    for horizon in HORIZONS:
        target = first_trade_on_or_after(prices, base_date + timedelta(days=horizon))
        if target is None:
            pending_targets += 1
            continue
        _, target_price = target
        mention_return = calc_return(base_price, target_price, mention["stance"])
        row[f"return_{horizon}d"] = format_number(mention_return)

        if benchmark_base is None:
            continue
        benchmark_target = first_trade_on_or_after(benchmark_prices, base_date + timedelta(days=horizon))
        if benchmark_target is None:
            continue
        benchmark_return = benchmark_target[1] / benchmark_base[1] - 1
        row[f"benchmark_return_{horizon}d"] = format_number(benchmark_return)
        row[f"excess_return_{horizon}d"] = format_number(mention_return - benchmark_return)

    if pending_targets:
        row["calculation_status"] = "pending_price"
        row["notes"] = f"price source Yahoo chart symbol={symbol}; {pending_targets} horizon target prices unavailable"
    return row


def calculate_concept_return_row(
    mention: dict[str, str],
    prices_by_symbol: dict[str, dict[date, float]],
    proxies: list[ConceptProxy],
) -> dict[str, str]:
    if not proxies:
        return empty_return_row(mention, "not_applicable", "approved concept mention has no active proxy basket")

    published_at = date.fromisoformat(mention["published_at"])
    base_target = published_at + timedelta(days=1)
    component_bases: list[tuple[ConceptProxy, date, float]] = []
    missing_base_symbols: list[str] = []
    for proxy in proxies:
        symbol = yahoo_symbol(proxy.ticker, proxy.market)
        base = first_trade_on_or_after(prices_by_symbol.get(symbol, {}), base_target)
        if base is None:
            missing_base_symbols.append(symbol)
            continue
        base_date, base_price = base
        component_bases.append((proxy, base_date, base_price))

    if missing_base_symbols:
        return empty_return_row(
            mention,
            "missing_price",
            f"missing concept proxy base prices: {';'.join(sorted(missing_base_symbols))}",
        )
    if not component_bases:
        return empty_return_row(mention, "missing_price", "missing all concept proxy base prices")

    base_date = min(component_base[1] for component_base in component_bases)
    benchmark_market = concept_benchmark_market(proxies)
    benchmark_symbol = BENCHMARK_SYMBOLS.get(benchmark_market, "")
    benchmark_prices = prices_by_symbol.get(benchmark_symbol, {}) if benchmark_symbol else {}
    benchmark_base = first_trade_on_or_after(benchmark_prices, base_date) if benchmark_prices else None

    proxy_symbols = [yahoo_symbol(proxy.ticker, proxy.market) for proxy, _, _ in component_bases]
    row = empty_return_row(
        mention,
        "calculated",
        f"concept proxy basket={mention['company_or_theme']}; symbols={';'.join(proxy_symbols)}",
    )
    row["ticker"] = f"concept_proxy:{mention['company_or_theme']}"
    row["market"] = "concept"
    row["base_trade_date"] = base_date.isoformat()
    row["base_price"] = "1"
    pending_targets = 0

    for horizon in HORIZONS:
        component_returns: list[tuple[float, float]] = []
        missing_target = False
        for proxy, component_base_date, component_base_price in component_bases:
            symbol = yahoo_symbol(proxy.ticker, proxy.market)
            target = first_trade_on_or_after(
                prices_by_symbol.get(symbol, {}),
                component_base_date + timedelta(days=horizon),
            )
            if target is None:
                missing_target = True
                break
            _, target_price = target
            component_returns.append(
                (proxy.weight, calc_return(component_base_price, target_price, mention["stance"]))
            )
        if missing_target:
            pending_targets += 1
            continue

        mention_return = weighted_average(component_returns)
        row[f"return_{horizon}d"] = format_number(mention_return)

        if benchmark_base is None:
            continue
        benchmark_target = first_trade_on_or_after(benchmark_prices, base_date + timedelta(days=horizon))
        if benchmark_target is None:
            continue
        benchmark_return = benchmark_target[1] / benchmark_base[1] - 1
        row[f"benchmark_return_{horizon}d"] = format_number(benchmark_return)
        row[f"excess_return_{horizon}d"] = format_number(mention_return - benchmark_return)

    if pending_targets:
        row["calculation_status"] = "pending_price"
        row["notes"] = (
            f"concept proxy basket={mention['company_or_theme']}; "
            f"symbols={';'.join(proxy_symbols)}; {pending_targets} horizon target prices unavailable"
        )
    return row


def calculate_return_row(
    mention: dict[str, str],
    prices_by_symbol: dict[str, dict[date, float]],
    concept_proxies: dict[str, list[ConceptProxy]],
) -> dict[str, str]:
    if mention["stance"] not in {"bullish", "bearish"}:
        return empty_return_row(mention, "not_applicable", "approved mention stance is not bullish/bearish")
    if mention["mention_type"] == "company":
        return calculate_company_return_row(mention, prices_by_symbol)
    return calculate_concept_return_row(
        mention,
        prices_by_symbol,
        concept_proxies.get(mention.get("company_or_theme", ""), []),
    )


def output_fieldnames(existing_fieldnames: list[str]) -> list[str]:
    if existing_fieldnames:
        return existing_fieldnames
    return [
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
    ]


def write_returns(path: pathlib.Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)
    _, mentions = load_csv(pathlib.Path(args.mentions_csv))
    concept_proxies = load_concept_proxies(pathlib.Path(args.concept_proxies_csv))
    return_fieldnames, existing_returns = load_csv(pathlib.Path(args.returns_csv))

    mentions_to_process = approved_mentions(mentions)
    symbols = sorted(needed_symbols(mentions_to_process, concept_proxies))
    prices_dir = pathlib.Path(args.prices_dir)
    price_rows_by_symbol: dict[str, list[PriceRow]] = {}

    for symbol in symbols:
        rows = fetch_yahoo_prices(symbol, start_date, end_date)
        price_rows_by_symbol[symbol] = rows
        write_prices(price_path(prices_dir, symbol), symbol, rows)
        print(f"Wrote {len(rows)} price rows for {symbol}")
        time.sleep(args.sleep_seconds)

    prices_by_symbol = {
        symbol: load_price_map(rows)
        for symbol, rows in price_rows_by_symbol.items()
    }

    sample_rows = [
        row for row in existing_returns if row.get("mention_id", "").startswith("sample_")
    ]
    calculated_rows = [
        calculate_return_row(mention, prices_by_symbol, concept_proxies)
        for mention in mentions_to_process
    ]
    write_returns(
        pathlib.Path(args.returns_csv),
        output_fieldnames(return_fieldnames),
        sample_rows + calculated_rows,
    )
    print(f"Wrote {len(calculated_rows)} return rows to {args.returns_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
