from scripts.tw_lynch_screen import (
    format_telegram_report,
    fundamental_score,
    institutional_score,
    roc_to_iso,
    trend_score,
)


def test_roc_to_iso():
    assert roc_to_iso("1151022") == "2026-10-22"
    assert roc_to_iso("bad") is None


def test_fundamental_score_is_bounded():
    row = {"pe": 12, "pb": 1.2, "dividend_yield": 4.5, "revenue_yoy": 18, "revenue_ytd_yoy": 16}
    assert fundamental_score(row) == 40.0
    assert fundamental_score({}) == 0.0


def test_trend_breakout_score():
    closes = [float(value) for value in range(40, 101)]
    volumes = [100.0] * 60 + [200.0]
    score, detail = trend_score(closes, volumes, {"lookback_days": 55, "near_high_pct": 3, "minimum_volume_ratio": 1.35})
    assert score == 40.0
    assert detail["volume_ratio"] == 2.0


def test_institutional_score_uses_share_volume_ratio():
    assert institutional_score(100_000, 1_000_000) == 20.0
    assert institutional_score(-1, 1_000_000) == 0.0
    assert institutional_score(None, 1_000_000) == 0.0


def test_format_telegram_report_is_deterministic_without_llm():
    report = {
        "status": "ok",
        "trade_date": "2026-10-26",
        "coverage": {"universe": 1900, "history_requested": 300, "history_received": 288, "selected": 1},
        "selected": [{
            "code": "2330", "name": "台積電", "total_score": 78,
            "fundamental_score": 32, "trend_breakout_score": 31,
            "institutional_score": 15, "technical": {"return_20d_pct": 8.5},
        }],
    }

    text = format_telegram_report(report)

    assert "全市場 1900 檔" in text
    assert "2330 台積電｜總分 78" in text
    assert "純規則摘要" in text
