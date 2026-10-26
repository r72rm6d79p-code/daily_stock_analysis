from scripts.tw_lynch_screen import fundamental_score, institutional_score, roc_to_iso, trend_score


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
