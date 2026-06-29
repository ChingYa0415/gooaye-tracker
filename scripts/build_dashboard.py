#!/usr/bin/env python3
"""Build a static HTML dashboard from generated CSV reports."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import html
import json
import pathlib


HORIZONS = [7, 30, 90, 180]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create reports/dashboard.html.")
    parser.add_argument("--summary-csv", default="reports/summary.csv")
    parser.add_argument("--return-report", default="reports/approved_company_bullish_returns.csv")
    parser.add_argument("--concept-proxy-review", default="reports/concept_proxy_review.csv")
    parser.add_argument("--output", default="reports/dashboard.html")
    parser.add_argument(
        "--pages-output",
        default="docs/index.html",
        help="GitHub Pages entry file to write. Pass an empty value to skip.",
    )
    return parser.parse_args()


def load_csv(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def summary_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {f"{row['section']}.{row['metric']}": row for row in rows}


def metric(summary: dict[str, dict[str, str]], key: str, default: str = "0") -> str:
    return summary.get(key, {}).get("display_value") or default


def numeric(value: str) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def pct(value: str) -> str:
    parsed = numeric(value)
    if parsed is None:
        return ""
    return f"{parsed * 100:.2f}%"


def row_kind(row: dict[str, str]) -> str:
    return "concept" if row.get("ticker", "").startswith("concept_proxy:") else "company"


def enriched_returns(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    enriched: list[dict[str, str]] = []
    for row in rows:
        item = dict(row)
        item["kind"] = row_kind(row)
        item["kind_label"] = "概念 proxy" if item["kind"] == "concept" else "公司"
        item["best_horizon"] = row.get("available_horizons") or "pending"
        item["available_horizon_count"] = str(
            sum(1 for horizon in HORIZONS if row.get(f"return_{horizon}d"))
        )
        item["has_any_return"] = "true" if item["available_horizon_count"] != "0" else "false"
        current_return = numeric(row.get("current_return", ""))
        current_excess = numeric(row.get("excess_current_return", ""))
        item["current_return_display"] = row.get("current_return_pct") or "等待"
        item["excess_current_display"] = row.get("excess_current_return_pct") or "等待"
        item["current_return_value"] = current_return if current_return is not None else 0
        item["excess_current_return_value"] = current_excess if current_excess is not None else 0
        item["has_current_return"] = "true" if current_return is not None else "false"
        for horizon in HORIZONS:
            return_value = numeric(row.get(f"return_{horizon}d", ""))
            excess_value = numeric(row.get(f"excess_return_{horizon}d", ""))
            item[f"return_{horizon}d_display"] = row.get(f"return_{horizon}d_pct") or "等待"
            item[f"excess_{horizon}d_display"] = row.get(f"excess_return_{horizon}d_pct") or "等待"
            item[f"return_{horizon}d_value"] = return_value if return_value is not None else 0
            item[f"excess_return_{horizon}d_value"] = excess_value if excess_value is not None else 0
        enriched.append(item)
    return enriched


def enriched_proxy_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    enriched: list[dict[str, str]] = []
    for row in rows:
        item = dict(row)
        issue = row.get("concept_issue", "")
        if issue == "ok":
            priority = "ok"
            priority_label = "OK"
        elif "no_active_proxy" in issue or "single_name_proxy" in issue:
            priority = "high"
            priority_label = "優先"
        else:
            priority = "watch"
            priority_label = "檢查"
        item["priority"] = priority
        item["priority_label"] = priority_label
        enriched.append(item)
    return enriched


def json_script(name: str, data: object) -> str:
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f"<script id=\"{name}\" type=\"application/json\">{payload}</script>"


def escape(value: str) -> str:
    return html.escape(value, quote=True)


def build_html(
    summary_rows: list[dict[str, str]],
    return_rows: list[dict[str, str]],
    proxy_rows: list[dict[str, str]],
) -> str:
    summary = summary_map(summary_rows)
    generated_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    returns = enriched_returns(return_rows)
    proxies = enriched_proxy_rows(proxy_rows)

    stat_cards = [
        ("Episodes", metric(summary, "episodes.formal_total"), "formal sources"),
        ("Mentions", metric(summary, "mentions.formal_total"), f"{metric(summary, 'mentions.approved_total')} approved"),
        ("Trackable", metric(summary, "returns.total_return_candidates"), f"{metric(summary, 'returns.concept_proxy_return_candidates')} concept proxy"),
        ("Current Avg", metric(summary, "performance.current.avg_return", "-"), f"{metric(summary, 'performance.current.available_count')} ready"),
        ("Current Excess", metric(summary, "performance.current.avg_excess_return", "-"), "vs benchmark"),
        ("7d Ready", metric(summary, "performance.7d.available_count"), f"{metric(summary, 'performance.7d.hit_rate')} hit rate"),
        ("7d Avg", metric(summary, "performance.7d.avg_return", "-"), "stance-adjusted"),
        ("7d Excess", metric(summary, "performance.7d.avg_excess_return", "-"), "vs benchmark"),
    ]
    stat_html = "\n".join(
        f"""
        <section class="stat">
          <div class="stat-label">{escape(label)}</div>
          <div class="stat-value">{escape(value)}</div>
          <div class="stat-note">{escape(note)}</div>
        </section>
        """
        for label, value, note in stat_cards
    )

    issue_counts: dict[str, int] = {}
    for row in proxies:
        issue_counts[row["concept_issue"]] = issue_counts.get(row["concept_issue"], 0) + 1
    issue_html = "\n".join(
        f"<span class=\"issue-chip\">{escape(issue)} <strong>{count}</strong></span>"
        for issue, count in sorted(issue_counts.items(), key=lambda item: (-item[1], item[0]))
    )

    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>股癌追蹤 Dashboard</title>
  <style>
    :root {{
      --bg: #f6f7f4;
      --panel: #ffffff;
      --panel-soft: #f0f3ef;
      --ink: #1c2420;
      --muted: #66716a;
      --line: #dce2dc;
      --accent: #0f766e;
      --accent-weak: #d7f0eb;
      --amber: #b7791f;
      --amber-weak: #f7e8c8;
      --rose: #b42318;
      --rose-weak: #f8d8d4;
      --green: #147a43;
      --green-weak: #d9f1df;
      --shadow: 0 1px 2px rgba(28, 36, 32, 0.06);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
      line-height: 1.45;
    }}
    .shell {{
      width: min(1440px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 24px 0 40px;
    }}
    header {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 16px;
      padding: 0 0 16px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0;
      font-size: 24px;
      line-height: 1.15;
      letter-spacing: 0;
    }}
    .subtle {{ color: var(--muted); font-size: 13px; }}
    .generated {{ text-align: right; min-width: 220px; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(6, minmax(120px, 1fr));
      gap: 10px;
      margin: 16px 0;
    }}
    .stat, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }}
    .stat {{ padding: 12px 14px; min-height: 92px; }}
    .stat-label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    .stat-value {{
      margin-top: 8px;
      font-size: 26px;
      font-weight: 720;
      line-height: 1;
      letter-spacing: 0;
    }}
    .stat-note {{ margin-top: 8px; color: var(--muted); font-size: 12px; }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.8fr) minmax(320px, 0.95fr);
      gap: 14px;
      align-items: start;
    }}
    .panel {{ overflow: hidden; }}
    .panel-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel-soft);
    }}
    h2 {{ margin: 0; font-size: 16px; letter-spacing: 0; }}
    .toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }}
    .quick-filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .quick-filter {{
      width: auto;
      min-width: 0;
      height: 30px;
      padding: 0 10px;
      border-radius: 999px;
      font-size: 12px;
      background: #fff;
    }}
    .quick-filter.active {{
      color: #07524c;
      background: var(--accent-weak);
      border-color: #8fd5cc;
      font-weight: 700;
    }}
    .sort-control {{
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 220px;
    }}
    .sort-control label {{
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }}
    .filters {{
      display: grid;
      grid-template-columns: minmax(180px, 1.4fr) repeat(4, minmax(120px, 0.8fr)) 40px;
      gap: 8px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfa;
    }}
    input, select, button {{
      width: 100%;
      height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 10px;
      background: #fff;
      color: var(--ink);
      font: inherit;
    }}
    button {{
      display: grid;
      place-items: center;
      padding: 0;
      cursor: pointer;
      color: var(--muted);
    }}
    button:hover {{ border-color: #b8c4bc; color: var(--ink); }}
    .table-wrap {{ overflow: auto; max-height: 690px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 1320px;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      white-space: nowrap;
    }}
    th {{
      position: sticky;
      top: 0;
      z-index: 1;
      background: #eef2ec;
      color: #334139;
      font-size: 12px;
      font-weight: 700;
    }}
    td.wrap {{ white-space: normal; min-width: 260px; max-width: 420px; }}
    td.date-cell {{ min-width: 110px; }}
    .name-cell strong {{ display: block; font-size: 14px; }}
    .name-cell span {{ display: block; color: var(--muted); font-size: 12px; margin-top: 2px; }}
    .mention-cell {{
      min-width: 116px;
    }}
    .mention-control {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      height: 28px;
    }}
    .mention-count {{
      min-width: 38px;
      color: #334139;
      font-weight: 700;
    }}
    .date-button {{
      width: auto;
      min-width: 44px;
      height: 28px;
      padding: 0 8px;
      border: 1px solid var(--line);
      border-radius: 5px;
      background: #fff;
      color: #07524c;
      font-size: 11px;
      font-weight: 700;
      line-height: 1.2;
    }}
    .date-button:hover {{ border-color: #8fd5cc; background: var(--accent-weak); }}
    .badge {{
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 650;
      border: 1px solid transparent;
    }}
    .badge-company {{ color: #075985; background: #dff0fb; border-color: #bee3f8; }}
    .badge-concept {{ color: #6b4e00; background: var(--amber-weak); border-color: #efd08f; }}
    .badge-status {{ color: #445047; background: #edf1ed; border-color: var(--line); }}
    .badge-bullish {{ color: var(--green); background: var(--green-weak); border-color: #b6e2c0; }}
    .badge-bearish {{ color: var(--rose); background: var(--rose-weak); border-color: #efb5ad; }}
    .badge-neutral {{ color: #445047; background: #edf1ed; border-color: var(--line); }}
    .badge-past {{ color: #6b4e00; background: var(--amber-weak); border-color: #efd08f; }}
    .badge-ready {{ color: var(--green); background: var(--green-weak); border-color: #b6e2c0; }}
    .badge-high {{ color: var(--rose); background: var(--rose-weak); border-color: #efb5ad; }}
    .badge-watch {{ color: var(--amber); background: var(--amber-weak); border-color: #efd08f; }}
    .badge-ok {{ color: var(--green); background: var(--green-weak); border-color: #b6e2c0; }}
    .bar-cell {{ min-width: 170px; }}
    .bar-track {{
      position: relative;
      height: 24px;
      width: 150px;
      background: #edf0eb;
      border: 1px solid var(--line);
      border-radius: 5px;
      overflow: hidden;
    }}
    .bar-zero {{
      position: absolute;
      left: 50%;
      top: 0;
      bottom: 0;
      width: 1px;
      background: #a9b2aa;
    }}
    .bar-fill {{
      position: absolute;
      top: 3px;
      bottom: 3px;
      border-radius: 3px;
      min-width: 2px;
    }}
    .bar-fill.pos {{ left: 50%; background: var(--green); }}
    .bar-fill.neg {{ right: 50%; background: var(--rose); }}
    .bar-label {{
      position: absolute;
      inset: 0;
      display: grid;
      place-items: center;
      font-size: 11px;
      font-weight: 700;
      color: var(--ink);
    }}
    .horizon-list {{
      display: grid;
      grid-template-columns: repeat(4, minmax(52px, 1fr));
      gap: 4px;
      min-width: 236px;
    }}
    .horizon-pill {{
      display: grid;
      gap: 2px;
      min-height: 38px;
      padding: 4px 6px;
      border-radius: 6px;
      border: 1px solid var(--line);
      background: #f7f9f6;
      font-size: 11px;
      line-height: 1.1;
    }}
    .horizon-pill.ready {{
      background: #eef8f1;
      border-color: #b6e2c0;
    }}
    .horizon-pill strong {{ font-size: 11px; }}
    .horizon-pill span {{ color: var(--muted); }}
    .empty {{
      display: none;
      padding: 24px;
      color: var(--muted);
      text-align: center;
    }}
    .proxy-summary {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfa;
    }}
    .issue-chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 8px;
      border-radius: 6px;
      background: #eef2ec;
      color: #334139;
      font-size: 12px;
      border: 1px solid var(--line);
    }}
    .proxy-table table {{ min-width: 760px; }}
    .proxy-table .table-wrap {{ max-height: 520px; }}
    .footer-note {{
      margin-top: 14px;
      color: var(--muted);
      font-size: 12px;
    }}
    .modal-backdrop {{
      position: fixed;
      inset: 0;
      z-index: 20;
      display: grid;
      place-items: center;
      padding: 18px;
      background: rgba(28, 36, 32, 0.34);
    }}
    .modal-backdrop[hidden] {{ display: none; }}
    .modal {{
      width: min(720px, 100%);
      max-height: min(680px, calc(100vh - 36px));
      overflow: hidden;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 18px 48px rgba(28, 36, 32, 0.24);
    }}
    .modal-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel-soft);
    }}
    .modal-title strong {{ display: block; font-size: 16px; }}
    .modal-title span {{ display: block; margin-top: 2px; color: var(--muted); font-size: 12px; }}
    .modal-close {{
      width: 32px;
      height: 32px;
      flex: 0 0 auto;
      font-size: 18px;
    }}
    .mention-date-list {{
      display: grid;
      gap: 0;
      max-height: 540px;
      overflow: auto;
    }}
    .mention-date-row {{
      display: grid;
      grid-template-columns: 108px minmax(0, 1fr) 86px;
      gap: 10px;
      align-items: center;
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
    }}
    .mention-date-row:last-child {{ border-bottom: 0; }}
    .mention-date-main strong {{ display: block; }}
    .mention-date-main span {{ display: block; margin-top: 2px; color: var(--muted); font-size: 12px; }}
    .evidence-list {{
      display: grid;
      max-height: 560px;
      overflow: auto;
    }}
    .evidence-row {{
      display: grid;
      grid-template-columns: 150px minmax(0, 1fr);
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
    }}
    .evidence-row:last-child {{ border-bottom: 0; }}
    .evidence-meta strong {{ display: block; }}
    .evidence-meta span {{ display: block; margin-top: 2px; color: var(--muted); font-size: 12px; }}
    .evidence-text {{
      white-space: normal;
      color: #28342d;
    }}
    @media (max-width: 1100px) {{
      .stats {{ grid-template-columns: repeat(3, minmax(120px, 1fr)); }}
      .grid {{ grid-template-columns: 1fr; }}
      .generated {{ text-align: left; }}
      header {{ align-items: flex-start; flex-direction: column; }}
    }}
    @media (max-width: 720px) {{
      .shell {{ width: min(100vw - 20px, 1440px); padding-top: 14px; }}
      .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .filters {{ grid-template-columns: 1fr; }}
      .toolbar {{ align-items: stretch; flex-direction: column; }}
      .sort-control {{ min-width: 0; }}
      .stat-value {{ font-size: 22px; }}
      h1 {{ font-size: 21px; }}
      .mention-date-row {{ grid-template-columns: 1fr; gap: 4px; }}
      .evidence-row {{ grid-template-columns: 1fr; gap: 8px; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div>
        <h1>股癌追蹤 Dashboard</h1>
        <div class="subtle">公司訊號、概念 proxy、回測進度與代理籃子審核</div>
      </div>
      <div class="generated subtle">Generated<br>{escape(generated_at)}</div>
    </header>

    <main>
      <section class="stats" aria-label="summary">
        {stat_html}
      </section>

      <section class="grid">
        <div class="panel">
          <div class="panel-head">
            <h2>追蹤明細</h2>
            <span class="subtle" id="signalCount"></span>
          </div>
          <div class="toolbar">
            <div class="quick-filters" aria-label="quick filters">
              <button class="quick-filter active" type="button" data-quick-filter="all">全部</button>
              <button class="quick-filter" type="button" data-quick-filter="ready">已有報酬</button>
              <button class="quick-filter" type="button" data-quick-filter="positive_excess">正超額</button>
              <button class="quick-filter" type="button" data-quick-filter="pending">待價格</button>
            </div>
            <div class="sort-control">
              <label for="sortSelect">排序</label>
              <select id="sortSelect" aria-label="sort">
                <option value="latest_desc">最近提及新到舊</option>
                <option value="latest_asc">最近提及舊到新</option>
                <option value="first_desc">首次提及新到舊</option>
                <option value="first_asc">首次提及舊到新</option>
                <option value="return_7d_desc">7d 報酬高到低</option>
                <option value="return_7d_asc">7d 報酬低到高</option>
                <option value="excess_7d_desc">7d 超額高到低</option>
                <option value="excess_7d_asc">7d 超額低到高</option>
                <option value="current_return_desc">至今報酬高到低</option>
                <option value="current_return_asc">至今報酬低到高</option>
                <option value="current_excess_desc">至今超額高到低</option>
                <option value="current_excess_asc">至今超額低到高</option>
                <option value="name_asc">標的名稱</option>
              </select>
            </div>
          </div>
          <div class="filters">
            <input id="searchInput" type="search" placeholder="搜尋標的、ticker、集數">
            <select id="kindFilter" aria-label="kind">
              <option value="">全部類型</option>
              <option value="company">公司</option>
              <option value="concept">概念 proxy</option>
            </select>
            <select id="marketFilter" aria-label="market">
              <option value="">全部市場</option>
            </select>
            <select id="statusFilter" aria-label="status">
              <option value="">全部狀態</option>
            </select>
            <select id="horizonFilter" aria-label="horizon">
              <option value="">全部 horizon</option>
              <option value="7d">已有 7d</option>
              <option value="pending">等待價格</option>
            </select>
            <button id="clearSignalFilters" type="button" aria-label="清除篩選" title="清除篩選">×</button>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>標的</th>
                  <th>類型</th>
                  <th>看法</th>
                  <th>首次提及</th>
                  <th>提及</th>
                  <th>基準日</th>
                  <th>狀態</th>
                  <th>Horizon</th>
                  <th>至今報酬</th>
                  <th>至今超額</th>
                  <th>7d 報酬</th>
                  <th>7d 超額</th>
                  <th>證據</th>
                </tr>
              </thead>
              <tbody id="signalsBody"></tbody>
            </table>
          </div>
          <div class="empty" id="signalsEmpty">沒有符合篩選條件的追蹤項目。</div>
        </div>

        <aside class="panel proxy-table">
          <div class="panel-head">
            <h2>Proxy 審核</h2>
            <span class="subtle" id="proxyCount"></span>
          </div>
          <div class="proxy-summary">{issue_html}</div>
          <div class="filters" style="grid-template-columns: minmax(160px, 1fr) minmax(120px, .7fr) 40px;">
            <input id="proxySearchInput" type="search" placeholder="搜尋概念、成分股、issue">
            <select id="proxyPriorityFilter" aria-label="priority">
              <option value="">全部</option>
              <option value="high">優先</option>
              <option value="watch">檢查</option>
              <option value="ok">OK</option>
            </select>
            <button id="clearProxyFilters" type="button" aria-label="清除 proxy 篩選" title="清除篩選">×</button>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>概念</th>
                  <th>優先度</th>
                  <th>成分</th>
                  <th>權重</th>
                  <th>Issue</th>
                </tr>
              </thead>
              <tbody id="proxyBody"></tbody>
            </table>
          </div>
          <div class="empty" id="proxyEmpty">沒有符合篩選條件的 proxy 成分。</div>
        </aside>
      </section>

      <div class="footer-note">資料來源：reports/summary.csv、reports/approved_company_bullish_returns.csv、reports/concept_proxy_review.csv。更新請執行 python3 scripts/run_daily_update.py。</div>
    </main>
  </div>

  <div class="modal-backdrop" id="mentionModal" hidden>
    <section class="modal" role="dialog" aria-modal="true" aria-labelledby="mentionModalTitle">
      <div class="modal-head">
        <div class="modal-title">
          <strong id="mentionModalTitle"></strong>
          <span id="mentionModalSubtitle"></span>
        </div>
        <button class="modal-close" id="closeMentionModal" type="button" aria-label="關閉提及日期">×</button>
      </div>
      <div class="mention-date-list" id="mentionModalBody"></div>
    </section>
  </div>

  <div class="modal-backdrop" id="evidenceModal" hidden>
    <section class="modal" role="dialog" aria-modal="true" aria-labelledby="evidenceModalTitle">
      <div class="modal-head">
        <div class="modal-title">
          <strong id="evidenceModalTitle"></strong>
          <span id="evidenceModalSubtitle"></span>
        </div>
        <button class="modal-close" id="closeEvidenceModal" type="button" aria-label="關閉證據內容">×</button>
      </div>
      <div class="evidence-list" id="evidenceModalBody"></div>
    </section>
  </div>

  {json_script("return-data", returns)}
  {json_script("proxy-data", proxies)}
  <script>
    const returns = JSON.parse(document.getElementById("return-data").textContent);
    const proxies = JSON.parse(document.getElementById("proxy-data").textContent);
    const maxAbsReturn = Math.max(0.01, ...returns.flatMap(row => [
      Math.abs(Number(row.return_7d_value || 0)),
      Math.abs(Number(row.excess_return_7d_value || 0)),
      Math.abs(Number(row.current_return_value || 0)),
      Math.abs(Number(row.excess_current_return_value || 0))
    ]));

    const searchInput = document.getElementById("searchInput");
    const kindFilter = document.getElementById("kindFilter");
    const marketFilter = document.getElementById("marketFilter");
    const statusFilter = document.getElementById("statusFilter");
    const horizonFilter = document.getElementById("horizonFilter");
    const sortSelect = document.getElementById("sortSelect");
    const clearSignalFilters = document.getElementById("clearSignalFilters");
    const signalsBody = document.getElementById("signalsBody");
    const signalsEmpty = document.getElementById("signalsEmpty");
    const signalCount = document.getElementById("signalCount");
    const mentionModal = document.getElementById("mentionModal");
    const mentionModalTitle = document.getElementById("mentionModalTitle");
    const mentionModalSubtitle = document.getElementById("mentionModalSubtitle");
    const mentionModalBody = document.getElementById("mentionModalBody");
    const closeMentionModal = document.getElementById("closeMentionModal");
    const evidenceModal = document.getElementById("evidenceModal");
    const evidenceModalTitle = document.getElementById("evidenceModalTitle");
    const evidenceModalSubtitle = document.getElementById("evidenceModalSubtitle");
    const evidenceModalBody = document.getElementById("evidenceModalBody");
    const closeEvidenceModal = document.getElementById("closeEvidenceModal");

    const proxySearchInput = document.getElementById("proxySearchInput");
    const proxyPriorityFilter = document.getElementById("proxyPriorityFilter");
    const clearProxyFilters = document.getElementById("clearProxyFilters");
    const proxyBody = document.getElementById("proxyBody");
    const proxyEmpty = document.getElementById("proxyEmpty");
    const proxyCount = document.getElementById("proxyCount");
    let activeQuickFilter = "all";

    function unique(values) {{
      return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-Hant"));
    }}

    function addOptions(select, values) {{
      for (const value of values) {{
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
      }}
    }}

    function escapeHtml(value) {{
      return String(value ?? "").replace(/[&<>"']/g, char => ({{
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }}[char]));
    }}

    function badge(text, cls) {{
      return `<span class="badge ${{cls}}">${{escapeHtml(text)}}</span>`;
    }}

    function stanceBadge(row) {{
      const stance = row.stance || "neutral";
      const cls = stance === "bullish"
        ? "badge-bullish"
        : stance === "bearish"
          ? "badge-bearish"
          : stance === "past_review"
            ? "badge-past"
            : "badge-neutral";
      return badge(stance, cls);
    }}

    function returnBar(value, label) {{
      const numeric = Number(value || 0);
      const width = Math.min(50, Math.abs(numeric) / maxAbsReturn * 50);
      const cls = numeric >= 0 ? "pos" : "neg";
      const shown = label && label !== "等待" ? label : "等待";
      return `
        <div class="bar-track">
          <div class="bar-zero"></div>
          ${{label && label !== "等待" ? `<div class="bar-fill ${{cls}}" style="width:${{width}}%;"></div>` : ""}}
          <div class="bar-label">${{escapeHtml(shown)}}</div>
        </div>
      `;
    }}

    function horizonPills(row) {{
      return [7, 30, 90, 180].map(horizon => {{
        const label = row[`return_${{horizon}}d_display`] || "等待";
        const ready = label !== "等待";
        return `
          <span class="horizon-pill ${{ready ? "ready" : ""}}">
            <strong>${{horizon}}d</strong>
            <span>${{escapeHtml(label)}}</span>
          </span>
        `;
      }}).join("");
    }}

    function splitCsvList(value) {{
      return String(value || "").split(";").map(item => item.trim()).filter(Boolean);
    }}

    function stanceByDate(row) {{
      const output = new Map();
      for (const item of splitCsvList(row.stance_timeline)) {{
        const [date, stance] = item.split(":");
        if (!date || !stance) continue;
        const current = output.get(date) || [];
        if (!current.includes(stance)) current.push(stance);
        output.set(date, current);
      }}
      return output;
    }}

    function episodeByDate(row) {{
      const dates = splitCsvList(row.all_published_dates);
      const episodeIds = splitCsvList(row.episode_ids);
      const output = new Map();
      dates.forEach((date, index) => {{
        output.set(date, episodeIds[index] || "");
      }});
      return output;
    }}

    function mentionButton(row) {{
      return `
        <div class="mention-control">
          <span class="mention-count">${{escapeHtml(row.mention_count || "1")}} 次</span>
          <button class="date-button" type="button" data-tracking-id="${{escapeHtml(row.tracking_id)}}" aria-label="查看 ${{escapeHtml(row.company_or_theme)}} 提及日期">日期</button>
        </div>
      `;
    }}

    function parseEvidenceItems(row) {{
      try {{
        const items = JSON.parse(row.evidence_items || "[]");
        if (Array.isArray(items) && items.length) return items;
      }} catch (_error) {{}}
      return [{{
        mention_id: row.first_mention_id || "",
        episode_id: row.first_episode_id || "",
        episode_title: row.first_episode_title || "",
        published_at: row.first_published_at || "",
        stance: row.stance || "",
        evidence_text: row.evidence_text || ""
      }}];
    }}

    function evidenceButton(row) {{
      const count = parseEvidenceItems(row).length;
      return `
        <div class="mention-control">
          <span class="mention-count">${{count}} 段</span>
          <button class="date-button" type="button" data-evidence-id="${{escapeHtml(row.tracking_id)}}" aria-label="查看 ${{escapeHtml(row.company_or_theme)}} 證據內容">內容</button>
        </div>
      `;
    }}

    function openMentionModal(row) {{
      const dates = splitCsvList(row.all_published_dates);
      const stances = stanceByDate(row);
      const episodes = episodeByDate(row);
      mentionModalTitle.textContent = `${{row.company_or_theme}} 提及日期`;
      mentionModalSubtitle.textContent = `${{row.ticker}} · ${{row.market}} · ${{row.mention_count || "1"}} 次提及`;
      mentionModalBody.innerHTML = dates.map((date, index) => {{
        const label = index === 0 ? "首次" : "後續";
        const dateStances = stances.get(date) || [];
        return `
          <div class="mention-date-row">
            <div class="mention-date-main">
              <strong>${{escapeHtml(date)}}</strong>
              <span>${{escapeHtml(label)}}</span>
            </div>
            <div>${{escapeHtml(episodes.get(date) || "-")}}</div>
            <div>${{dateStances.map(stance => stanceBadge({{ stance }})).join("") || badge("unclear", "badge-neutral")}}</div>
          </div>
        `;
      }}).join("");
      mentionModal.hidden = false;
    }}

    function hideMentionModal() {{
      mentionModal.hidden = true;
    }}

    function openEvidenceModal(row) {{
      const items = parseEvidenceItems(row);
      evidenceModalTitle.textContent = `${{row.company_or_theme}} 證據`;
      evidenceModalSubtitle.textContent = `${{row.ticker}} · ${{row.market}} · ${{items.length}} 段來源`;
      evidenceModalBody.innerHTML = items.map((item, index) => `
        <div class="evidence-row">
          <div class="evidence-meta">
            <strong>${{escapeHtml(item.episode_title || item.episode_id || "-")}}</strong>
            <span>${{escapeHtml(item.published_at || "-")}} · ${{index === 0 ? "首次" : "後續"}}</span>
            <span>${{stanceBadge({{ stance: item.stance || "unclear" }})}}</span>
          </div>
          <div class="evidence-text">${{escapeHtml(item.evidence_text || "-")}}</div>
        </div>
      `).join("");
      evidenceModal.hidden = false;
    }}

    function hideEvidenceModal() {{
      evidenceModal.hidden = true;
    }}

    function compareSignals(a, b) {{
      const sortValue = sortSelect.value;
      const byName = a.company_or_theme.localeCompare(b.company_or_theme, "zh-Hant");
      if (sortValue === "first_asc") return a.first_published_at.localeCompare(b.first_published_at) || byName;
      if (sortValue === "first_desc") return b.first_published_at.localeCompare(a.first_published_at) || byName;
      if (sortValue === "latest_asc") return a.latest_published_at.localeCompare(b.latest_published_at) || byName;
      if (sortValue === "latest_desc") return b.latest_published_at.localeCompare(a.latest_published_at) || byName;
      if (sortValue === "return_7d_desc") return Number(b.return_7d_value || 0) - Number(a.return_7d_value || 0) || byName;
      if (sortValue === "return_7d_asc") return Number(a.return_7d_value || 0) - Number(b.return_7d_value || 0) || byName;
      if (sortValue === "excess_7d_desc") return Number(b.excess_return_7d_value || 0) - Number(a.excess_return_7d_value || 0) || byName;
      if (sortValue === "excess_7d_asc") return Number(a.excess_return_7d_value || 0) - Number(b.excess_return_7d_value || 0) || byName;
      if (sortValue === "current_return_desc") return Number(b.current_return_value || 0) - Number(a.current_return_value || 0) || byName;
      if (sortValue === "current_return_asc") return Number(a.current_return_value || 0) - Number(b.current_return_value || 0) || byName;
      if (sortValue === "current_excess_desc") return Number(b.excess_current_return_value || 0) - Number(a.excess_current_return_value || 0) || byName;
      if (sortValue === "current_excess_asc") return Number(a.excess_current_return_value || 0) - Number(b.excess_current_return_value || 0) || byName;
      if (sortValue === "name_asc") return byName || b.latest_published_at.localeCompare(a.latest_published_at);
      return b.latest_published_at.localeCompare(a.latest_published_at) || byName;
    }}

    function matchesSignal(row) {{
      const query = searchInput.value.trim().toLowerCase();
      const haystack = [
        row.company_or_theme,
        row.ticker,
        row.first_episode_title,
        row.episode_titles,
        row.evidence_text,
        row.evidence_items,
        row.mention_timeline,
        row.tracking_id,
        row.first_mention_id,
        row.mention_ids
      ].join(" ").toLowerCase();
      if (query && !haystack.includes(query)) return false;
      if (kindFilter.value && row.kind !== kindFilter.value) return false;
      if (marketFilter.value && row.market !== marketFilter.value) return false;
      if (statusFilter.value && row.calculation_status !== statusFilter.value) return false;
      if (horizonFilter.value === "7d" && !String(row.available_horizons || "").includes("7d")) return false;
      if (horizonFilter.value === "pending" && row.available_horizons) return false;
      if (activeQuickFilter === "ready" && row.has_any_return !== "true") return false;
      if (activeQuickFilter === "positive_excess" && Number(row.excess_return_7d_value || 0) <= 0) return false;
      if (activeQuickFilter === "pending" && row.has_any_return === "true") return false;
      return true;
    }}

    function renderSignals() {{
      const rows = returns.filter(matchesSignal).sort(compareSignals);
      signalsBody.innerHTML = rows.map(row => `
        <tr>
          <td class="name-cell">
            <strong>${{escapeHtml(row.company_or_theme)}}</strong>
            <span>${{escapeHtml(row.ticker)}} · ${{escapeHtml(row.market)}} · ${{escapeHtml(row.mention_count || "1")}} 次提及</span>
          </td>
          <td>${{badge(row.kind_label, row.kind === "concept" ? "badge-concept" : "badge-company")}}</td>
          <td>${{stanceBadge(row)}}</td>
          <td class="date-cell" title="${{escapeHtml(row.first_episode_title || "")}}">${{escapeHtml(row.first_published_at)}}</td>
          <td class="mention-cell" title="${{escapeHtml(row.mention_timeline || "")}}">${{mentionButton(row)}}</td>
          <td>${{escapeHtml(row.base_trade_date || "等待")}}</td>
          <td>${{badge(row.available_horizons || row.calculation_status, row.available_horizons ? "badge-ready" : "badge-status")}}</td>
          <td><div class="horizon-list">${{horizonPills(row)}}</div></td>
          <td class="bar-cell" title="最新價格日：${{escapeHtml(row.current_trade_date || "等待")}}">${{returnBar(row.current_return_value, row.current_return_display)}}</td>
          <td class="bar-cell" title="最新價格日：${{escapeHtml(row.current_trade_date || "等待")}}">${{returnBar(row.excess_current_return_value, row.excess_current_display)}}</td>
          <td class="bar-cell">${{returnBar(row.return_7d_value, row.return_7d_display)}}</td>
          <td class="bar-cell">${{returnBar(row.excess_return_7d_value, row.excess_7d_display)}}</td>
          <td class="mention-cell">${{evidenceButton(row)}}</td>
        </tr>
      `).join("");
      signalCount.textContent = `${{rows.length}} / ${{returns.length}}`;
      signalsEmpty.style.display = rows.length ? "none" : "block";
    }}

    function matchesProxy(row) {{
      const query = proxySearchInput.value.trim().toLowerCase();
      const haystack = [
        row.concept_name,
        row.concept_issue,
        row.proxy_id,
        row.ticker,
        row.market,
        row.name,
        row.current_notes
      ].join(" ").toLowerCase();
      if (query && !haystack.includes(query)) return false;
      if (proxyPriorityFilter.value && row.priority !== proxyPriorityFilter.value) return false;
      return true;
    }}

    function renderProxies() {{
      const rows = proxies.filter(matchesProxy);
      proxyBody.innerHTML = rows.map(row => `
        <tr>
          <td class="name-cell">
            <strong>${{escapeHtml(row.concept_name)}}</strong>
            <span>${{escapeHtml(row.directional_mention_count)}} mentions · ${{escapeHtml(row.return_status_counts || "no returns")}}</span>
          </td>
          <td>${{badge(row.priority_label, row.priority === "high" ? "badge-high" : row.priority === "watch" ? "badge-watch" : "badge-ok")}}</td>
          <td class="name-cell">
            <strong>${{escapeHtml(row.name || "未啟用")}}</strong>
            <span>${{escapeHtml(row.ticker || "-")}} · ${{escapeHtml(row.market || "-")}}</span>
          </td>
          <td>${{escapeHtml(row.weight)}} / ${{escapeHtml(row.active_weight_total)}}</td>
          <td class="wrap">${{escapeHtml(row.concept_issue)}}</td>
        </tr>
      `).join("");
      proxyCount.textContent = `${{rows.length}} / ${{proxies.length}}`;
      proxyEmpty.style.display = rows.length ? "none" : "block";
    }}

    addOptions(marketFilter, unique(returns.map(row => row.market)));
    addOptions(statusFilter, unique(returns.map(row => row.calculation_status)));

    [searchInput, kindFilter, marketFilter, statusFilter, horizonFilter, sortSelect].forEach(input => {{
      input.addEventListener("input", renderSignals);
      input.addEventListener("change", renderSignals);
    }});
    [proxySearchInput, proxyPriorityFilter].forEach(input => {{
      input.addEventListener("input", renderProxies);
      input.addEventListener("change", renderProxies);
    }});
    clearSignalFilters.addEventListener("click", () => {{
      searchInput.value = "";
      kindFilter.value = "";
      marketFilter.value = "";
      statusFilter.value = "";
      horizonFilter.value = "";
      activeQuickFilter = "all";
      document.querySelectorAll("[data-quick-filter]").forEach(button => {{
        button.classList.toggle("active", button.dataset.quickFilter === "all");
      }});
      renderSignals();
    }});
    document.querySelectorAll("[data-quick-filter]").forEach(button => {{
      button.addEventListener("click", () => {{
        activeQuickFilter = button.dataset.quickFilter;
        document.querySelectorAll("[data-quick-filter]").forEach(item => {{
          item.classList.toggle("active", item === button);
        }});
        renderSignals();
      }});
    }});
    signalsBody.addEventListener("click", event => {{
      const mentionButton = event.target.closest("[data-tracking-id]");
      if (mentionButton) {{
        const row = returns.find(item => item.tracking_id === mentionButton.dataset.trackingId);
        if (row) openMentionModal(row);
        return;
      }}
      const evidenceButton = event.target.closest("[data-evidence-id]");
      if (evidenceButton) {{
        const row = returns.find(item => item.tracking_id === evidenceButton.dataset.evidenceId);
        if (row) openEvidenceModal(row);
      }}
    }});
    closeMentionModal.addEventListener("click", hideMentionModal);
    closeEvidenceModal.addEventListener("click", hideEvidenceModal);
    mentionModal.addEventListener("click", event => {{
      if (event.target === mentionModal) hideMentionModal();
    }});
    evidenceModal.addEventListener("click", event => {{
      if (event.target === evidenceModal) hideEvidenceModal();
    }});
    document.addEventListener("keydown", event => {{
      if (event.key === "Escape" && !mentionModal.hidden) hideMentionModal();
      if (event.key === "Escape" && !evidenceModal.hidden) hideEvidenceModal();
    }});
    clearProxyFilters.addEventListener("click", () => {{
      proxySearchInput.value = "";
      proxyPriorityFilter.value = "";
      renderProxies();
    }});

    renderSignals();
    renderProxies();
  </script>
</body>
</html>
"""


def write_dashboard(path: pathlib.Path, html_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = "\n".join(line.rstrip() for line in html_text.splitlines()) + "\n"
    path.write_text(normalized, encoding="utf-8")


def main() -> int:
    args = parse_args()
    html_text = build_html(
        summary_rows=load_csv(pathlib.Path(args.summary_csv)),
        return_rows=load_csv(pathlib.Path(args.return_report)),
        proxy_rows=load_csv(pathlib.Path(args.concept_proxy_review)),
    )
    write_dashboard(pathlib.Path(args.output), html_text)
    print(f"Wrote dashboard to {args.output}")
    if args.pages_output:
        write_dashboard(pathlib.Path(args.pages_output), html_text)
        print(f"Wrote GitHub Pages dashboard to {args.pages_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
