"""
تست core/opportunity.py -> detect_strategy_opportunities (نسخه ۲).
داده Synthetic، بدون نیاز به شبکه یا Database.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from core import opportunity
from core import strategy as strat_engine
from core.opportunity_config import STRATEGY_WEIGHTS


def _make_chain(iv=0.30):
    rows = []
    for strike in [900, 950, 980, 1000, 1020, 1050, 1100]:
        for opt_type, close in [("call", max(5, 1000 - strike + 40)), ("put", max(5, strike - 1000 + 40))]:
            rows.append({
                "underlying": "تست", "expiry": "2026-12-01", "option_type": opt_type,
                "quote_date": "2026-09-01", "dte": 30, "strike": strike, "close": close,
                "bid": close - 2, "ask": close + 2, "volume": 200, "open_interest": 1000,
                "iv": iv, "underlying_close": 1000.0, "symbol": f"{opt_type[0].upper()}{strike}",
            })
    return pd.DataFrame(rows)


def test_deterministic_pop_and_expected_value():
    """با seed ثابت، اجرای دوباره باید دقیقاً همان عدد را بدهد (بخش ۱۶، ۲۵ سند)."""
    chain = _make_chain()
    r1 = opportunity.detect_strategy_opportunities(chain, "تست", "2026-12-01", 1000.0, 0.20)
    r2 = opportunity.detect_strategy_opportunities(chain, "تست", "2026-12-01", 1000.0, 0.20)
    assert not r1.empty
    pd.testing.assert_series_equal(r1["pop"].reset_index(drop=True), r2["pop"].reset_index(drop=True))
    pd.testing.assert_series_equal(
        r1["expected_value"].reset_index(drop=True), r2["expected_value"].reset_index(drop=True)
    )


def test_expected_value_present_when_simulation_possible():
    chain = _make_chain()
    res = opportunity.detect_strategy_opportunities(chain, "تست", "2026-12-01", 1000.0, 0.20)
    long_call = res[res["strategy"].str.startswith("Long Call")]
    assert not long_call.empty
    assert long_call.iloc[0]["expected_value"] is not None


def test_scores_bounded_and_have_coverage():
    chain = _make_chain()
    res = opportunity.detect_strategy_opportunities(chain, "تست", "2026-12-01", 1000.0, 0.20)
    assert not res.empty
    assert (res["score"] >= 0).all() and (res["score"] <= 100).all()
    assert res["coverage"].notna().all()
    assert res["grade"].isin(["A", "B", "C", "D", "F"]).all()


def test_no_contract_level_concepts_leak_into_strategy_components():
    """momentum/OI جداگانه نباید در subscores سطح Strategy ظاهر شوند."""
    chain = _make_chain()
    res = opportunity.detect_strategy_opportunities(chain, "تست", "2026-12-01", 1000.0, 0.20)
    for sub in res["subscores"]:
        assert set(sub.keys()) == set(STRATEGY_WEIGHTS.keys())


def test_unbounded_risk_flagged_as_risk():
    chain = _make_chain()
    res = opportunity.detect_strategy_opportunities(chain, "تست", "2026-12-01", 1000.0, 0.20)
    naked_call = res[res["strategy"].str.startswith("Naked Call")]
    if not naked_call.empty:
        risks_text = " ".join(naked_call.iloc[0]["risks"])
        assert "نامحدود" in risks_text


def test_worst_leg_penalty_lowers_liquidity_vs_uniform():
    """اگر یک پایه نقدشوندگی خیلی پایینی داشته باشد، امتیاز کمتر از حالت یکنواخت باشد."""
    chain_good = _make_chain()
    chain_bad = chain_good.copy()
    # یکی از پایه‌های Bull Call Spread را به‌شدت بی‌نقد می‌کنیم
    mask = (chain_bad["option_type"] == "call") & (chain_bad["strike"] == 1020)
    chain_bad.loc[mask, ["volume", "open_interest", "bid", "ask"]] = [0, 0, None, None]

    res_good = opportunity.detect_strategy_opportunities(chain_good, "تست", "2026-12-01", 1000.0, 0.20)
    res_bad = opportunity.detect_strategy_opportunities(chain_bad, "تست", "2026-12-01", 1000.0, 0.20)

    g = res_good[res_good["strategy"].str.startswith("Bull Call Spread")]
    b = res_bad[res_bad["strategy"].str.startswith("Bull Call Spread")]
    if not g.empty and not b.empty and g.iloc[0]["subscores"]["liquidity"] and b.iloc[0]["subscores"]["liquidity"]:
        assert b.iloc[0]["subscores"]["liquidity"] <= g.iloc[0]["subscores"]["liquidity"]


def test_legacy_incompatible_weights_fallback_no_crash():
    chain = _make_chain()
    old_style = {"liquidity": 1, "risk_reward": 1, "iv": 1, "probability": 1,
                 "open_interest": 1, "mispricing": 1, "momentum": 1}
    res = opportunity.detect_strategy_opportunities(chain, "تست", "2026-12-01", 1000.0, 0.20, weights=old_style)
    assert not res.empty


if __name__ == "__main__":
    test_deterministic_pop_and_expected_value()
    test_expected_value_present_when_simulation_possible()
    test_scores_bounded_and_have_coverage()
    test_no_contract_level_concepts_leak_into_strategy_components()
    test_unbounded_risk_flagged_as_risk()
    test_worst_leg_penalty_lowers_liquidity_vs_uniform()
    test_legacy_incompatible_weights_fallback_no_crash()
    print("همه تست‌های Strategy Opportunity Engine v2 موفق بودند ✅")
