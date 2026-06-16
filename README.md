# 股癌追蹤

這個專案用來追蹤 Podcast、YouTube 或社群內容中提到的投資觀點，並把公司、產業、立場、原文證據與後續股價表現整理成可追蹤的資料。

第一階段目標：

1. 週期性同步股癌新集數。
2. 下載、切段、轉錄並合併逐字稿。
3. 自動整理逐字稿中提到的單一股票，判斷股癌看法。
4. 追蹤單一公司與概念 proxy basket 的 7 / 30 / 90 / 180 天報酬與相對 benchmark 表現。

主要文件：

- `股癌追蹤系統規劃與設計.txt`：完整規劃、實作清單與每日實作紀錄。
- `docs/操作流程.txt`：日常資料更新、驗證、逐字稿、審核與報表流程。
- `docs/`：標註規則、資料字典與資料來源。
- `data/processed/`：整理後的 CSV 資料。
- `data/prices/`：價格資料。
- `scripts/`：資料抓取、抽取與回測腳本。
- `reports/`：統計報表與輸出結果。
- `reports/dashboard.html`：靜態測試版 Dashboard，可直接用瀏覽器開啟。

常用命令：

```bash
python3 scripts/sync_episodes.py
python3 scripts/auto_extract_stock_mentions.py
python3 scripts/run_daily_update.py --skip-price-fetch
python3 scripts/validate_data.py
python3 scripts/build_return_report.py
python3 scripts/build_summary_report.py
python3 scripts/build_concept_proxy_review.py
python3 scripts/build_dashboard.py
```

需要更新價格時：

```bash
python3 scripts/run_daily_update.py
```

新集數完整處理時，依序使用：

```bash
python3 scripts/download_audio.py --episode-id ep_YYYYMMDD_XXX
python3 scripts/split_audio.py --episode-id ep_YYYYMMDD_XXX
python3 scripts/transcribe_whisper_cpp.py --episode-id ep_YYYYMMDD_XXX
python3 scripts/combine_transcripts.py --episode-id ep_YYYYMMDD_XXX
python3 scripts/auto_extract_stock_mentions.py
python3 scripts/run_daily_update.py
```
