# 股癌追蹤

這個專案用來追蹤 Podcast、YouTube 或社群內容中提到的投資觀點，並把公司、產業、立場、原文證據與後續股價表現整理成可回測的資料。

第一階段目標：

1. 建立人工可操作的資料流程。
2. 手動整理第一批節目與 mention。
3. 串接台股價格資料。
4. 計算單一公司與概念 proxy basket 的 7 / 30 / 90 / 180 天報酬與相對 benchmark 表現。

主要文件：

- `股癌追蹤系統規劃與設計.txt`：完整規劃、實作清單與每日實作紀錄。
- `docs/操作流程.txt`：日常資料更新、驗證、逐字稿、審核與報表流程。
- `docs/`：標註規則、資料字典與資料來源。
- `data/processed/`：整理後的 CSV 資料。
- `data/prices/`：價格資料。
- `scripts/`：資料抓取、抽取與回測腳本。
- `reports/`：統計報表與輸出結果。

常用命令：

```bash
python3 scripts/run_daily_update.py --skip-price-fetch
python3 scripts/validate_data.py
python3 scripts/build_return_report.py
python3 scripts/build_summary_report.py
python3 scripts/build_concept_proxy_review.py
```

需要更新價格時：

```bash
python3 scripts/run_daily_update.py
```
