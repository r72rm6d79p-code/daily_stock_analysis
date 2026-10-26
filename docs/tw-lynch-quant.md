# 台股林奇量化篩選

此功能以兩階段方式處理全體上市、上櫃普通股：先以交易所官方全市場資料計算林奇代理基本面分與流動性門檻，再只對前段候選抓取日線，計算趨勢與突破分。最後加入三大法人買賣超評分，把少量候選交給既有 DSA 深度分析與 Telegram 通知。

## 資料源與覆蓋率

| 資料 | 來源 | 失敗語意 |
| --- | --- | --- |
| 上市／上櫃公司清單 | TWSE `t187ap03_L`、TPEx `mopsfin_t187ap03_O` | 無法建立股票池則整次失敗 |
| 收盤價、量、成交值 | TWSE `STOCK_DAY_ALL`、TPEx `tpex_mainboard_quotes` | 缺資料股票不進第二階段 |
| 本益比、股價淨值比、殖利率 | TWSE `BWIBBU_ALL`、TPEx `tpex_mainboard_peratio_analysis` | 欄位視為未知，不補零 |
| 月營收年增 | TWSE `t187ap05_L`、TPEx `mopsfin_t187ap05_O` | 欄位視為未知，不補零 |
| 趨勢／突破日線 | Yahoo Finance | 該股票排除，計入 history coverage 缺口 |
| 三大法人 | TWSE T86、TPEx `tpex_3insti_daily_trading` | 籌碼分為 0 並顯示覆蓋缺口 |

每次報告都包含 `universe`、`official_snapshot`、`liquid_and_fundamental`、`history_requested`、`history_received`、`institutional_received` 與 `selected`。這些數字是驗收全市場範圍與資料源退化的依據。

## 策略規則

- 林奇代理基本面 40 分：合理 PE、PB、殖利率、單月與累計營收年增。
- 趨勢／突破 40 分：收盤站上 MA20、MA20 高於 MA60、20 日動能、接近 55 日高點、量能放大。
- 三大法人 20 分：當日買賣超股數相對成交量。
- 總分、成交值、第二階段數量與輸出數量在 `config/tw_lynch_quant.json` 管理。

第一階段不是完整 Peter Lynch 財報模型。PEG、負債比、自由現金流與盈餘品質需由入選候選的既有 DSA 基本面深度分析補齊。

## 休市與排程

GitHub Actions cron 預設使用 UTC；台北 18:00 是 `0 10 * * 1-5`。工作日不等於交易日，因此程式要求 TWSE／TPEx 官方快照的交易日期等於台北當日；週末、國定假日、颱風或臨時休市都會回傳 `skipped_non_trading_day`。手動驗證才使用 `--force`。

GitHub-hosted job 最長 360 分鐘；原工作流預設 `ANALYSIS_TIMEOUT_MINUTES=30`。啟用本功能後建議將 Repository variable 調為 `90`，同時維持有界第二階段。不可把約 1,800–2,000 檔全部送入逐檔 LLM 分析。

部署時在 Repository variables 設定 `TW_LYNCH_SCREEN_ENABLED=true`；不設定或设为 `false` 時，原本的 `STOCK_LIST`、排程與所有通知行為完全不變。Telegram 的 `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` 以及任一 LLM 金鑰放在 Repository Secrets。Actions 先執行預篩，若為休市或沒有候選就結束；有候選才把產出的 `stock_list` 交給既有 `main.py`，沿用原 Telegram 發送器。

## 本地驗證

```bash
python scripts/tw_lynch_screen.py --date 2026-10-22 --output reports/tw_lynch_screen.json
python main.py --stocks "$(python -c 'import json; print(json.load(open("reports/tw_lynch_screen.json"))["stock_list"])')"
```

API 金鑰、Telegram token 與 chat ID 只放在 `.env`（本地）或 GitHub Actions Secrets，不得寫入設定檔、報告、log 或 commit。
