"""
پوشش کامل چک‌لیست تست بخش ۲۵ سند «ATLAS Opportunity Engine Redesign».
برخلاف test_opportunity_v2.py / test_strategy_opportunity_v2.py (که بیشتر
End-to-End هستند)، این فایل مستقیماً توابع داخلی (_prefixed) را تست می‌کند
تا هر مؤلفه به‌صورت مجزا و دقیق پوشش داده شود.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from core import opportunity as opp
from core import strategy as strat
from core import analytics
from core.opportunity_config import (
    SPREAD_ABSOLUTE_BANDS, RISK_REWARD_BANDS, band_score,
)

pd.set_option("mode.chained_assignment", None)


def _group(rows):
    return pd.DataFrame(rows)


# ===========================================================================
# CONTRACT — ۱. Liquidity Normalization
# ===========================================================================
def test_liquidity_normalization_bounds_and_direction():
    group = _group([
        {"bid": 98, "ask": 100, "close": 100, "volume": 500, "open_interest": 3000, "bid_size": 50, "ask_size": 50},
        {"bid": 50, "ask": 100, "close": 100, "volume": 10, "open_interest": 50, "bid_size": 1, "ask_size": 1},
        {"bid": 95, "ask": 105, "close": 100, "volume": 200, "open_interest": 1000, "bid_size": 10, "ask_size": 10},
    ])
    tight = group.iloc[0]
    wide = group.iloc[1]
    score_tight, _ = opp._liquidity_score(tight, group)
    score_wide, _ = opp._liquidity_score(wide, group)
    for s in (score_tight, score_wide):
        assert 0 <= s <= 100
    assert score_tight > score_wide, "اسپرد تنگ‌تر و حجم/OI بالاتر باید امتیاز نقدشوندگی بالاتری بدهد"


# ===========================================================================
# CONTRACT — ۲. Spread Scoring
# ===========================================================================
def test_spread_pct_calculation():
    assert opp._spread_pct(98, 100, 100) == pytest_approx(2.0)
    assert opp._spread_pct(None, 100, 100) is None
    assert opp._spread_pct(100, 90, 100) is None  # ask < bid = نامعتبر، نه صفر
    assert opp._spread_pct(0, 100, 100) is None   # bid<=0 = تک‌طرفه


def pytest_approx(x, tol=1e-6):
    class _A:
        def __eq__(self, other):
            return abs(other - x) < tol
    return _A()


def test_spread_band_score_monotonic():
    tight = band_score(2.0, SPREAD_ABSOLUTE_BANDS)
    medium = band_score(8.0, SPREAD_ABSOLUTE_BANDS)
    wide = band_score(30.0, SPREAD_ABSOLUTE_BANDS)
    assert tight > medium > wide, "اسپرد تنگ‌تر باید همیشه امتیاز بالاتر بگیرد"
    assert band_score(None, SPREAD_ABSOLUTE_BANDS) is None


# ===========================================================================
# CONTRACT — ۳. Volume Scoring / ۴. OI Scoring (هر دو از _pct_rank مشترک)
# ===========================================================================
def test_volume_and_oi_percentile_scoring():
    s = pd.Series([10, 50, 100, 500, 1000])
    assert opp._pct_rank(s, 1000) == 100.0
    assert opp._pct_rank(s, 10) == 20.0
    assert opp._pct_rank(s, None) is None
    assert opp._pct_rank(pd.Series([], dtype=float), 5) is None


# ===========================================================================
# CONTRACT — ۵. OI Change
# ===========================================================================
def test_oi_change_signal_present_and_missing():
    group = _group([
        {"open_interest": 1000, "volume": 100},
        {"open_interest": 2000, "volume": 200},
        {"open_interest": 500, "volume": 50},
    ])
    row_with_change = pd.Series({"open_interest": 1000, "previous_open_interest": 500, "volume": 100})
    score, detail = opp._oi_participation_score(row_with_change, group)
    assert detail["oi_change_pct"] == pytest_approx(100.0)  # +۱۰۰٪ رشد

    row_missing_prev = pd.Series({"open_interest": 1000, "previous_open_interest": None, "volume": 100})
    score2, detail2 = opp._oi_participation_score(row_missing_prev, group)
    assert detail2["oi_change_pct"] is None, "بدون OI روز قبل، oi_change نباید صفر یا فرض شود"


# ===========================================================================
# CONTRACT — ۶، ۷، ۸. IV/HV، IV Rank، IV Percentile
# ===========================================================================
def _underlying_hist_for_hv(n=30, vol=0.02, seed=1):
    rng = np.random.default_rng(seed)
    price = 1000.0
    rows = []
    for i in range(n):
        price *= float(np.exp(rng.normal(0, vol)))
        rows.append({"underlying": "تست", "quote_date": f"2026-08-{i+1:02d}", "close": price})
    return pd.DataFrame(rows)


def test_iv_hv_component_reacts_to_deviation():
    """
    جهت‌دار (بخش ۱۵ سند): IV ارزان‌تر از HV باید امتیاز بالاتر بگیرد، IV
    گران‌تر امتیاز پایین‌تر — نه اینکه |انحراف| هر دو جهت را یکسان نشان دهد.
    """
    hist = _underlying_hist_for_hv()
    hv = analytics.underlying_hv(hist, "تست")
    assert hv is not None and hv > 0

    row_expensive = pd.Series({"iv": hv * 3, "underlying": "تست", "symbol": "X", "instrument_id": None})
    row_cheap = pd.Series({"iv": hv * 0.4, "underlying": "تست", "symbol": "X", "instrument_id": None})
    row_neutral = pd.Series({"iv": hv * 1.0, "underlying": "تست", "symbol": "X", "instrument_id": None})
    score_expensive, d_exp = opp._iv_value_score(row_expensive, hist, None)
    score_cheap, d_cheap = opp._iv_value_score(row_cheap, hist, None)
    score_neutral, d_neu = opp._iv_value_score(row_neutral, hist, None)

    assert score_cheap > score_neutral > score_expensive, (
        "ترتیب باید: ارزان‌تر از HV > نزدیک HV > گران‌تر از HV باشد"
    )
    assert "ارزان" in d_cheap["iv_hv_direction"]
    assert "گران" in d_exp["iv_hv_direction"]


def test_iv_rank_and_percentile_require_min_history():
    # کمتر از MIN_SNAPSHOTS_FOR_HISTORY (۵) => Unavailable
    short_hist = pd.DataFrame({
        "instrument_id": ["A"] * 3, "quote_date": ["2026-08-01", "2026-08-02", "2026-08-03"],
        "iv": [0.30, 0.31, 0.29], "symbol": ["X"] * 3,
    })
    row = pd.Series({"iv": 0.35, "instrument_id": "A", "symbol": "X", "underlying": "تست", "quote_date": "2026-08-04"})
    score, detail = opp._iv_value_score(row, None, short_hist)
    assert detail["iv_rank"] is None and detail["iv_percentile"] is None

    long_hist = pd.DataFrame({
        "instrument_id": ["A"] * 6,
        "quote_date": [f"2026-08-0{i}" for i in range(1, 7)],
        "iv": [0.20, 0.22, 0.24, 0.26, 0.28, 0.30], "symbol": ["X"] * 6,
    })
    row2 = pd.Series({"iv": 0.40, "instrument_id": "A", "symbol": "X", "underlying": "تست", "quote_date": "2026-08-07"})
    score2, detail2 = opp._iv_value_score(row2, None, long_hist)
    assert detail2["iv_rank"] is not None
    assert 0 <= detail2["iv_rank"] <= 250  # rank فرمول (current-min)/(max-min)*100، می‌تواند از ۱۰۰ فراتر رود اگر current>max
    assert 0 <= detail2["iv_percentile"] <= 100


def test_iv_history_excludes_current_snapshot_self_reference():
    """رگرسیون یک باگ واقعی: مقدار امروز نباید در تاریخچه‌ی خودش دیده شود."""
    hist = pd.DataFrame({
        "instrument_id": ["A"] * 5,
        "quote_date": ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04", "2026-09-01"],
        "iv": [0.20, 0.21, 0.19, 0.20, 0.99],  # ردیف آخر = امروز، مقدار پرت
    })
    series = analytics.contract_iv_history(hist, instrument_id="A", exclude_quote_date="2026-09-01")
    assert 0.99 not in series.values
    assert len(series) == 4


# ===========================================================================
# CONTRACT — ۹، ۱۰. Relative IV + Peer Minimum Requirement
# ===========================================================================
def test_relative_iv_direction_labels():
    """جهت‌دار (بخش ۱۶ سند): ارزان‌تر = امتیاز بالا، گران‌تر = امتیاز پایین."""
    group = _group([
        {"iv": 0.30, "moneyness": "ATM"}, {"iv": 0.31, "moneyness": "ATM"},
        {"iv": 0.29, "moneyness": "ATM"}, {"iv": 0.20, "moneyness": "ATM"},  # ارزان
        {"iv": 0.45, "moneyness": "ATM"},  # گران
    ])
    cheap_score, cheap_detail = opp._relative_iv_score(group.iloc[3], group)
    expensive_score, expensive_detail = opp._relative_iv_score(group.iloc[4], group)
    assert "ارزان" in cheap_detail["direction"]
    assert "گران" in expensive_detail["direction"]
    assert cheap_score > 50 > expensive_score, (
        "IV ارزان باید امتیاز بالای میانه و IV گران امتیاز پایین میانه بگیرد"
    )


def test_relative_iv_peer_minimum_enforced():
    group = _group([{"iv": 0.30, "moneyness": "ATM"}, {"iv": 0.31, "moneyness": "OTM"}])
    score, detail = opp._relative_iv_score(group.iloc[0], group)
    assert score is None and detail["peers"] < 3


# ===========================================================================
# CONTRACT — ۱۱. Premium Efficiency
# ===========================================================================
def test_premium_efficiency_ranks_within_group_and_handles_missing():
    group = _group([
        {"time_value": 10, "close": 50, "dte": 10},
        {"time_value": 2, "close": 50, "dte": 10},
        {"time_value": 30, "close": 50, "dte": 10},
    ])
    high_eff, _ = opp._premium_efficiency_score(group.iloc[2], group)
    low_eff, _ = opp._premium_efficiency_score(group.iloc[1], group)
    assert high_eff > low_eff

    missing_row = pd.Series({"time_value": None, "close": 50, "dte": 10})
    score_missing, detail_missing = opp._premium_efficiency_score(missing_row, group)
    assert score_missing is None


def test_premium_efficiency_short_dte_floor_prevents_fake_boost():
    """DTE بسیار کوتاه نباید صرفاً به‌خاطر مخرج کوچک امتیاز کاذب بگیرد."""
    group = _group([
        {"time_value": 5, "close": 50, "dte": 1},
        {"time_value": 5, "close": 50, "dte": 3},
        {"time_value": 5, "close": 50, "dte": 30},
    ])
    s_dte1, _ = opp._premium_efficiency_score(group.iloc[0], group)
    s_dte3, _ = opp._premium_efficiency_score(group.iloc[1], group)
    # با کف MAX_DTE_ANNUALIZE_FLOOR_DAYS، DTE=1 و DTE=3 باید مخرج یکسان (کف) بگیرند و امتیاز برابر شوند
    assert s_dte1 == s_dte3


# ===========================================================================
# CONTRACT — ۱۲. Breakeven Quality
# ===========================================================================
def test_breakeven_quality_ratio_and_missing_vol():
    row = pd.Series({"close": 40, "strike": 1000, "underlying_close": 1000,
                      "dte": 30, "option_type": "call", "iv": 0.30, "underlying": "تست"})
    score, detail = opp._breakeven_quality_score(row, None)
    assert detail["breakeven"] == 1040
    assert score is not None and 0 <= score <= 100

    row_no_vol = pd.Series({"close": 40, "strike": 1000, "underlying_close": 1000,
                             "dte": 30, "option_type": "call", "iv": None, "underlying": "تست"})
    score2, detail2 = opp._breakeven_quality_score(row_no_vol, None)
    assert score2 is None, "بدون IV و بدون HV، کیفیت سربه‌سر باید Unavailable باشد نه حدسی"


# ===========================================================================
# CONTRACT — ۱۳. Eligibility Gate (هر دلیل رد به‌طور مجزا)
# ===========================================================================
def test_eligibility_each_rejection_reason():
    base = dict(close=100, underlying_close=1000, dte=30, bid=95, ask=105, volume=10, open_interest=10)

    ok, reason = opp._is_eligible(pd.Series(base))
    assert ok is True and reason is None

    bad_price = pd.Series({**base, "close": None})
    assert opp._is_eligible(bad_price)[0] is False

    bad_spot = pd.Series({**base, "underlying_close": 0})
    assert opp._is_eligible(bad_spot)[0] is False

    bad_dte = pd.Series({**base, "dte": 0})
    assert opp._is_eligible(bad_dte)[0] is False

    bad_quote = pd.Series({**base, "bid": 110, "ask": 105})
    assert opp._is_eligible(bad_quote)[0] is False

    no_participation = pd.Series({**base, "volume": None, "open_interest": None})
    assert opp._is_eligible(no_participation)[0] is False

    wide_spread = pd.Series({**base, "bid": 10, "ask": 190, "close": 100})
    assert opp._is_eligible(wide_spread)[0] is False


# ===========================================================================
# CONTRACT — ۱۴. Missing Data ≠ Zero (سطح ترکیب کل امتیاز)
# ===========================================================================
def test_missing_component_not_treated_as_zero():
    components_full = {
        "a": {"score": 80, "weight": 0.5},
        "b": {"score": 80, "weight": 0.5},
    }
    components_partial = {
        "a": {"score": 80, "weight": 0.5},
        "b": {"score": None, "weight": 0.5},
    }
    score_full, cov_full = opp._renormalize(components_full)
    score_partial, cov_partial = opp._renormalize(components_partial)
    assert score_full == score_partial == 80.0, (
        "اگر مؤلفه غایب صفر فرض می‌شد، امتیاز partial باید ۴۰ می‌شد نه ۸۰"
    )
    assert cov_full == 100.0
    assert cov_partial == 50.0


# ===========================================================================
# CONTRACT — ۱۵، ۱۶، ۱۷. Score Bounds + Deterministic Ranking (End-to-End)
# ===========================================================================
def _full_chain_for_e2e():
    rows = []
    for i, strike in enumerate([900, 950, 980, 1000, 1020, 1050, 1080]):
        rows.append({
            "underlying": "تست", "expiry": "2026-12-01", "option_type": "call",
            "quote_date": "2026-09-01", "dte": 30, "strike": strike,
            "close": max(5, 1000 - strike + 60), "bid": max(1, 1000 - strike + 58),
            "ask": max(3, 1000 - strike + 62), "volume": 50 + i * 30,
            "open_interest": 500 + i * 100, "previous_open_interest": 480 + i * 90,
            "iv": 0.28 + i * 0.01, "underlying_close": 1000.0,
            "moneyness": "ITM" if strike < 1000 else ("ATM" if strike == 1000 else "OTM"),
            "time_value": 10 + i, "instrument_id": f"C{strike}", "symbol": f"C{strike}",
            "bid_size": 10, "ask_size": 10,
        })
    return pd.DataFrame(rows)


def test_scores_bounded_0_100_e2e():
    chain = _full_chain_for_e2e()
    result = opp.detect_contract_opportunities(chain)
    assert not result.empty
    assert (result["score"] >= 0).all() and (result["score"] <= 100).all()


def test_deterministic_ranking_contract():
    chain = _full_chain_for_e2e()
    r1 = opp.detect_contract_opportunities(chain)
    r2 = opp.detect_contract_opportunities(chain)
    pd.testing.assert_frame_equal(
        r1[["symbol", "score"]].reset_index(drop=True),
        r2[["symbol", "score"]].reset_index(drop=True),
    )


# ===========================================================================
# STRATEGY — ۱، ۲، ۳، ۴. Payoff / Max Profit / Max Loss / Breakeven
# ===========================================================================
def test_payoff_curve_long_call():
    legs = [strat.Leg("call", "buy", 1000, 40, 1, contract_size=1)]
    S = np.array([900, 1000, 1040, 1100])
    payoff = strat.payoff_curve(legs, S)
    # زیر Strike: زیان کامل Premium. بالای Strike+Premium: سود مثبت.
    assert payoff[0] == -40
    assert payoff[2] == 0
    assert payoff[3] == 60


def test_max_profit_loss_bull_call_spread():
    legs = [strat.Leg("call", "buy", 950, 60, 1, contract_size=1), strat.Leg("call", "sell", 1050, 20, 1, contract_size=1)]
    mpl = strat.max_profit_loss(legs, 1000)
    assert not mpl["max_profit_is_unbounded"]
    assert not mpl["max_loss_is_unbounded"]
    assert mpl["max_profit"] == pytest_approx(60.0)   # (1050-950) - (60-20)
    assert mpl["max_loss"] == pytest_approx(-40.0)     # -(60-20)


def test_breakevens_long_call():
    legs = [strat.Leg("call", "buy", 1000, 40, 1)]
    bes = strat.breakevens(legs, 1000)
    assert any(abs(b - 1040) < 2 for b in bes)


# ===========================================================================
# STRATEGY — ۵، ۶، ۱۳. POP / Expected Value / Deterministic Monte Carlo
# ===========================================================================
def test_pop_bounds_and_matches_simulate_outcome():
    legs = [strat.Leg("call", "buy", 1000, 40, 1)]
    pop = strat.probability_of_profit(legs, 1000, 0.30, 30 / 365, 0.20)
    sim = strat.simulate_outcome(legs, 1000, 0.30, 30 / 365, 0.20)
    assert 0 <= pop <= 1
    assert pop == sim["pop"], "POP جداگانه باید دقیقاً با POP همان شبیه‌سازی یکسان باشد"
    assert sim["expected_value"] is not None


def test_monte_carlo_deterministic_same_seed():
    legs = [strat.Leg("put", "sell", 950, 25, 1)]
    r1 = strat.simulate_outcome(legs, 1000, 0.25, 20 / 365, 0.20, seed=42)
    r2 = strat.simulate_outcome(legs, 1000, 0.25, 20 / 365, 0.20, seed=42)
    assert r1["pop"] == r2["pop"]
    assert r1["expected_value"] == r2["expected_value"]


# ===========================================================================
# STRATEGY — ۷. Risk/Reward بندی پله‌ای
# ===========================================================================
def test_risk_reward_band_score_diminishing():
    poor = band_score(0.4, RISK_REWARD_BANDS, higher_is_better=True)
    moderate = band_score(1.0, RISK_REWARD_BANDS, higher_is_better=True)
    good = band_score(1.5, RISK_REWARD_BANDS, higher_is_better=True)
    capped1 = band_score(2.5, RISK_REWARD_BANDS, higher_is_better=True)
    capped2 = band_score(10.0, RISK_REWARD_BANDS, higher_is_better=True)
    assert poor < moderate < good < capped1
    assert capped1 == capped2 == 100, "بالاتر از ۲٫۵ نباید بی‌نهایت رشد کند (Diminishing/Capped)"


# ===========================================================================
# STRATEGY — ۸، ۹. Multi-leg Liquidity (میانگین) + Worst-Leg Penalty
# ===========================================================================
def test_strategy_liquidity_avg_and_worst_leg_weighting():
    good_leg = pd.Series({"bid": 98, "ask": 100, "close": 100, "volume": 500, "open_interest": 3000})
    bad_leg = pd.Series({"bid": None, "ask": None, "close": 100, "volume": 0, "open_interest": 0})
    score, detail = opp._strategy_liquidity_score([good_leg, bad_leg])
    assert detail["worst_leg"] < detail["avg_leg"]
    # ترکیب باید نزدیک به ۰٫۶*avg + ۰٫۴*worst باشد
    expected = detail["avg_leg"] * 0.60 + detail["worst_leg"] * 0.40
    assert abs(score - expected) < 0.5


# ===========================================================================
# STRATEGY — ۱۰. IV Context جهت‌دار
# ===========================================================================
def test_iv_context_direction_flips_for_long_vs_short_premium():
    hist = _underlying_hist_for_hv()
    hv = analytics.underlying_hv(hist, "تست")
    leg_rows = [pd.Series({"iv": hv * 1.5})]  # IV نسبتاً گران نسبت به HV

    # Long Premium (credit منفی): IV گران باید امتیاز پایین بدهد
    score_long, detail_long = opp._strategy_iv_context_score(leg_rows, credit=-50, underlying_hist=hist, underlying_name="تست")
    # Short Premium (credit مثبت): همان IV گران باید امتیاز بالا بدهد
    score_short, detail_short = opp._strategy_iv_context_score(leg_rows, credit=50, underlying_hist=hist, underlying_name="تست")

    assert score_short > score_long, "برای همان IV گران، فروشنده Premium باید امتیاز بهتری بگیرد تا خریدار"


def test_iv_context_unavailable_without_hv():
    leg_rows = [pd.Series({"iv": 0.30})]
    score, detail = opp._strategy_iv_context_score(leg_rows, credit=-10, underlying_hist=None, underlying_name="تست")
    assert score is None
    assert detail["avg_iv"] == 0.30 and detail["iv_hv_ratio"] is None


# ===========================================================================
# STRATEGY — ۱۱، ۱۲. Missing Data + Coverage (End-to-End)
# ===========================================================================
def test_strategy_missing_iv_context_reduces_coverage_not_score_to_zero():
    chain = _full_chain_for_e2e()
    chain_no_iv = chain.copy()
    chain_no_iv["iv"] = np.nan
    res = opp.detect_strategy_opportunities(chain_no_iv, "تست", "2026-12-01", 1000.0, 0.20)
    assert not res.empty
    assert (res["coverage"] < 100).all(), "بدون IV، Coverage باید کمتر از ۱۰۰٪ باشد"
    assert (res["score"] > 0).any(), "نبود یک مؤلفه نباید کل امتیاز را صفر کند"


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"✅ {t.__name__}")
        except Exception:
            failed += 1
            print(f"❌ {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} تست موفق")
    if failed:
        sys.exit(1)
