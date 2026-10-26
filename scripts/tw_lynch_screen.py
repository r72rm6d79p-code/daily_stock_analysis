#!/usr/bin/env python3
"""Two-stage Taiwan listed/OTC Lynch + quant screening.

Stage 1 evaluates the complete TWSE/TPEx common-stock universe with official
exchange data. Stage 2 downloads daily history only for a bounded, liquid
shortlist. The script prints no credentials and writes an auditable JSON report.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import requests

TWSE = "https://openapi.twse.com.tw/v1"
TPEX = "https://www.tpex.org.tw/openapi/v1"
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "tw_lynch_quant.json"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
HEADERS = {"User-Agent": "daily-stock-analysis/tw-lynch-screen"}


@dataclass(frozen=True)
class Stock:
    code: str
    name: str
    market: str

    @property
    def symbol(self) -> str:
        return f"{self.code}.{'TW' if self.market == 'twse' else 'TWO'}"


def _number(value: Any) -> float | None:
    text = str(value or "").replace(",", "").strip()
    if text in {"", "-", "--", "N/A", "nan"}:
        return None
    try:
        parsed = float(text)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def roc_to_iso(value: Any) -> str | None:
    text = str(value or "").replace("/", "").replace("-", "").strip()
    if len(text) != 7 or not text.isdigit():
        return None
    try:
        return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:])).isoformat()
    except ValueError:
        return None


def _get_json(session: requests.Session, url: str, timeout: int = 25) -> Any:
    response = session.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.json()


def load_universe(session: requests.Session) -> list[Stock]:
    sources = (
        ("twse", f"{TWSE}/opendata/t187ap03_L", "公司代號", "公司簡稱"),
        ("tpex", f"{TPEX}/mopsfin_t187ap03_O", "SecuritiesCompanyCode", "CompanyAbbreviation"),
    )
    stocks: dict[str, Stock] = {}
    for market, url, code_key, name_key in sources:
        for row in _get_json(session, url):
            code = str(row.get(code_key, "")).strip()
            # Listed companies/common stocks only. Excludes ETFs, warrants and ETNs.
            if not (len(code) == 4 and code.isdigit()):
                continue
            stock = Stock(code=code, name=str(row.get(name_key, "")).strip(), market=market)
            stocks[stock.symbol] = stock
    return sorted(stocks.values(), key=lambda item: item.symbol)


def _index_rows(rows: Iterable[dict[str, Any]], code_key: str) -> dict[str, dict[str, Any]]:
    return {str(row.get(code_key, "")).strip(): row for row in rows if row.get(code_key)}


def load_official_snapshot(session: requests.Session) -> tuple[dict[str, dict[str, Any]], set[str]]:
    twse_quotes = _get_json(session, f"{TWSE}/exchangeReport/STOCK_DAY_ALL")
    tpex_quotes = _get_json(session, f"{TPEX}/tpex_mainboard_quotes")
    twse_value = _index_rows(_get_json(session, f"{TWSE}/exchangeReport/BWIBBU_ALL"), "Code")
    tpex_value = _index_rows(_get_json(session, f"{TPEX}/tpex_mainboard_peratio_analysis"), "SecuritiesCompanyCode")
    twse_rev = _index_rows(_get_json(session, f"{TWSE}/opendata/t187ap05_L"), "公司代號")
    tpex_rev = _index_rows(_get_json(session, f"{TPEX}/mopsfin_t187ap05_O"), "公司代號")

    records: dict[str, dict[str, Any]] = {}
    dates: set[str] = set()
    for market, quotes, code_key, volume_key, value_key, close_key in (
        ("twse", twse_quotes, "Code", "TradeVolume", "TradeValue", "ClosingPrice"),
        ("tpex", tpex_quotes, "SecuritiesCompanyCode", "TradingShares", "TransactionAmount", "Close"),
    ):
        valuations = twse_value if market == "twse" else tpex_value
        revenues = twse_rev if market == "twse" else tpex_rev
        for row in quotes:
            code = str(row.get(code_key, "")).strip()
            if not (len(code) == 4 and code.isdigit()):
                continue
            trading_date = roc_to_iso(row.get("Date"))
            if trading_date:
                dates.add(trading_date)
            valuation = valuations.get(code, {})
            revenue = revenues.get(code, {})
            records[f"{code}.{'TW' if market == 'twse' else 'TWO'}"] = {
                "trade_date": trading_date,
                "close": _number(row.get(close_key)),
                "volume": _number(row.get(volume_key)),
                "trade_value": _number(row.get(value_key)),
                "pe": _number(valuation.get("PEratio") if market == "twse" else valuation.get("PriceEarningRatio")),
                "pb": _number(valuation.get("PBratio") if market == "twse" else valuation.get("PriceBookRatio")),
                "dividend_yield": _number(valuation.get("DividendYield") if market == "twse" else valuation.get("YieldRatio")),
                "revenue_yoy": _number(revenue.get("營業收入-去年同月增減(%)")),
                "revenue_ytd_yoy": _number(revenue.get("累計營業收入-前期比較增減(%)")),
            }
    return records, dates


def is_current_trading_day(snapshot_dates: set[str], expected: date) -> bool:
    """Treat exchange publication date as authoritative, including ad-hoc closures."""
    return expected.isoformat() in snapshot_dates


def fundamental_score(row: dict[str, Any]) -> float:
    score = 0.0
    pe, pb = row.get("pe"), row.get("pb")
    dividend = row.get("dividend_yield")
    monthly, cumulative = row.get("revenue_yoy"), row.get("revenue_ytd_yoy")
    if pe is not None and pe > 0:
        score += 12.0 if pe <= 15 else 9.0 if pe <= 22 else 5.0 if pe <= 30 else 0.0
    if pb is not None and pb > 0:
        score += 8.0 if pb <= 1.5 else 5.0 if pb <= 3 else 2.0 if pb <= 5 else 0.0
    if dividend is not None:
        score += 6.0 if dividend >= 4 else 4.0 if dividend >= 2 else 2.0 if dividend > 0 else 0.0
    if monthly is not None:
        score += 8.0 if monthly >= 15 else 6.0 if monthly >= 5 else 3.0 if monthly >= 0 else 0.0
    if cumulative is not None:
        score += 6.0 if cumulative >= 15 else 4.0 if cumulative >= 5 else 2.0 if cumulative >= 0 else 0.0
    return round(score, 2)


def trend_score(closes: list[float], volumes: list[float], breakout: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    if len(closes) < 60 or len(volumes) < 21:
        return 0.0, {"reason": "insufficient_history"}
    close = closes[-1]
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60
    high = max(closes[-int(breakout["lookback_days"]):])
    avg_volume = sum(volumes[-21:-1]) / 20
    volume_ratio = volumes[-1] / avg_volume if avg_volume > 0 else 0.0
    distance_high = (high - close) / high * 100 if high > 0 else 100.0
    score = 0.0
    score += 10.0 if close > ma20 else 0.0
    score += 10.0 if ma20 > ma60 else 0.0
    ret20 = (close / closes[-21] - 1) * 100
    score += 8.0 if ret20 >= 5 else 5.0 if ret20 > 0 else 0.0
    if distance_high <= float(breakout["near_high_pct"]):
        score += 7.0
    if volume_ratio >= float(breakout["minimum_volume_ratio"]):
        score += 5.0
    return round(score, 2), {
        "close": round(close, 2), "ma20": round(ma20, 2), "ma60": round(ma60, 2),
        "return_20d_pct": round(ret20, 2), "distance_55d_high_pct": round(distance_high, 2),
        "volume_ratio": round(volume_ratio, 2),
    }


def institutional_score(net_shares: float | None, volume: float | None) -> float:
    if net_shares is None or not volume or volume <= 0:
        return 0.0
    ratio = net_shares / volume * 100
    return round(20.0 if ratio >= 10 else 16.0 if ratio >= 5 else 12.0 if ratio >= 1 else 7.0 if ratio > 0 else 0.0, 2)


def load_institutional(session: requests.Session, trade_date: str) -> dict[str, float]:
    result: dict[str, float] = {}
    try:
        response = session.get(
            "https://www.twse.com.tw/rwd/zh/fund/T86",
            params={"response": "json", "date": trade_date.replace("-", ""), "selectType": "ALLBUT0999"},
            headers=HEADERS,
            timeout=25,
        )
        response.raise_for_status()
        payload = response.json()
        fields = payload.get("fields", [])
        code_index = fields.index("證券代號")
        net_index = fields.index("三大法人買賣超股數")
        for row in payload.get("data", []):
            code, value = str(row[code_index]).strip(), _number(row[net_index])
            if len(code) == 4 and code.isdigit() and value is not None:
                result[f"{code}.TW"] = value
    except (requests.RequestException, ValueError, IndexError, TypeError):
        pass
    try:
        for row in _get_json(session, f"{TPEX}/tpex_3insti_daily_trading"):
            code = str(row.get("SecuritiesCompanyCode", "")).strip()
            served_date = roc_to_iso(row.get("Date"))
            value = _number(row.get("TotalDifference"))
            if served_date == trade_date and len(code) == 4 and code.isdigit() and value is not None:
                result[f"{code}.TWO"] = value
    except (requests.RequestException, TypeError):
        pass
    return result


def load_history(symbols: list[str]) -> dict[str, tuple[list[float], list[float]]]:
    import yfinance as yf

    if not symbols:
        return {}
    frame = yf.download(symbols, period="6mo", group_by="ticker", auto_adjust=True, progress=False, threads=True)
    output: dict[str, tuple[list[float], list[float]]] = {}
    for symbol in symbols:
        try:
            item = frame[symbol] if len(symbols) > 1 else frame
            clean = item[["Close", "Volume"]].dropna()
            output[symbol] = (clean["Close"].astype(float).tolist(), clean["Volume"].astype(float).tolist())
        except (KeyError, TypeError, ValueError):
            continue
    return output


def run(config: dict[str, Any], expected_date: date, force: bool = False) -> dict[str, Any]:
    session = requests.Session()
    universe = load_universe(session)
    snapshot, dates = load_official_snapshot(session)
    if not force and not is_current_trading_day(dates, expected_date):
        return {"status": "skipped_non_trading_day", "expected_date": expected_date.isoformat(), "exchange_dates": sorted(dates), "coverage": {"universe": len(universe)}}

    eligible: list[tuple[Stock, dict[str, Any], float]] = []
    minimum_value = float(config["minimum_trade_value_twd"])
    for stock in universe:
        row = snapshot.get(stock.symbol)
        if not row or not row.get("close") or (row.get("trade_value") or 0) < minimum_value:
            continue
        eligible.append((stock, row, fundamental_score(row)))
    eligible.sort(key=lambda item: (item[2], item[1].get("trade_value") or 0), reverse=True)
    bounded = eligible[: int(config["max_history_candidates"])]
    history = load_history([item[0].symbol for item in bounded])
    trade_date = max(dates) if dates else expected_date.isoformat()
    institutions = load_institutional(session, trade_date)

    candidates = []
    for stock, row, base_score in bounded:
        series = history.get(stock.symbol)
        if not series:
            continue
        technical, technical_detail = trend_score(*series, config["breakout"])
        chip = institutional_score(institutions.get(stock.symbol), row.get("volume"))
        total = round(base_score + technical + chip, 2)
        if total < float(config["minimum_total_score"]):
            continue
        candidates.append({
            **asdict(stock), "symbol": stock.symbol, "total_score": total,
            "fundamental_score": base_score, "trend_breakout_score": technical,
            "institutional_score": chip, "fundamental": row, "technical": technical_detail,
            "institutional_net_shares": institutions.get(stock.symbol),
        })
    candidates.sort(key=lambda item: (item["total_score"], item["symbol"]), reverse=True)
    selected = candidates[: int(config["max_output"])]
    return {
        "status": "ok", "strategy_version": config["version"], "trade_date": trade_date,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "coverage": {
            "universe": len(universe), "official_snapshot": len(snapshot), "liquid_and_fundamental": len(eligible),
            "history_requested": len(bounded), "history_received": len(history), "institutional_received": len(institutions),
            "selected": len(selected),
        },
        "selected": selected,
        "stock_list": ",".join(item["symbol"] for item in selected),
        "limitations": [
            "全市場基本面為官方估值、股息與月營收成長的林奇代理分；PEG、負債比與自由現金流留待候選股深度分析。",
            "技術日線由 Yahoo Finance 提供，失敗股票會從技術階段排除並反映於覆蓋率。",
            "分數是研究排序，不構成投資建議。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output", type=Path, default=Path("reports/tw_lynch_screen.json"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    report = run(config, args.date, force=args.force)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "coverage": report.get("coverage", {}), "stock_list": report.get("stock_list", "")}, ensure_ascii=False))
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"status={report['status']}\n")
            handle.write(f"stock_list={report.get('stock_list', '')}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
