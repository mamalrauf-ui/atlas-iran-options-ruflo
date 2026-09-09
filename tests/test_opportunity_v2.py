"""
تست core/opportunity.py نسخه ۲ (Contract Engine بازطراحی‌شده).
داده Synthetic، بدون نیاز به شبکه یا Database.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from core import opportunity
from core.opportunity_config import CONTRACT_WEIGHTS


def _base_row(strike, close, bid, ask, volume, oi, iv, moneyness, dte=30, prev_oi=None,
              instrument_id=None, symbol=None):
    return {
        "underlying": "تست", "expiry": "2026-12-01", "option_type": "call",
        "quote_date": "2026-09-01", "dte": dte, "strike": strike, "close": close,
        "bid": bid, "ask": ask, "volume": volume, "open_interest": oi,
        "previous_open_interest": prev_oi, "iv": iv, "underlying_close": 1000.0,
        "moneyness": moneyness, "time_value": max(0.0, close - max(0.0, 1000.0 - strike)),
        "delta": 0.5, "gamma": 0.01, "theta": -0.5, "vega": 1.2,
        "instrument_id": instrument_id, "symbol": symbol or f"OPT{strike}",
        "bid_size": 10, "ask_size": 10,
    }


def _make_chain():
    rows = [
        _base_row(900, 130, 128, 132, 500, 2000, 0.35, "ITM", prev_oi=1500, instrument_id="1"),
        _base_row(950, 90, 87, 93, 300, 1200, 0.33, "ITM", prev_oi=1300, instrument_id="2"),
        _base_row(980, 60, 55, 65, 100, 400, 0.34, "ITM", prev_oi=420, instrument_id="3"),
        _base_row(1000, 40, 38, 42, 800, 3000, 0.30, "ATM", prev_oi=2000, instrument_id="4"),
        _base_row(1020, 25, 20, 30, 150, 900, 0.31, "ATM", prev_oi=850, instrument_id="5"),
        _base_row(1050, 15, 12, 18, 50, 300, 0.32, "ATM", prev_oi=310, instrument_id="6"),
        # این یکی باید توسط Eligibility Gate رد شود: نه Volume نه OI
        _base_row(1100, 5, None, None, None, None, None, "OTM", instrument_id="7"),
    ]
    return pd.DataFrame(rows)


def test_eligibility_gate_excludes_no_participation_row():
    chain = _make_chain()
    result = opportunity.detect_contract_opportunities(chain)
    assert "OPT1100" not in result["symbol"].values, "قرارداد بدون Volume/OI نباید امتیاز بگیرد"
    assert result.attrs.get("ineligible_count", 0) >= 1


def test_scores_within_bounds_and_have_coverage_confidence():
    chain = _make_chain()
    result = opportunity.detect_contract_opportunities(chain)
    assert not result.empty
    assert (result["score"] >= 0).all() and (result["score"] <= 100).all()
    assert result["coverage"].notna().all()
    assert result["confidence"].isin(["High", "Moderate", "Low", "Very Low", "Unknown"]).all()
    assert result["grade"].isin(["A", "B", "C", "D", "F"]).all()


def test_no_permanently_none_components_remain():
    """risk_reward/probability/momentum نباید اصلاً در ستون‌های خروجی باشند."""
    chain = _make_chain()
    result = opportunity.detect_contract_opportunities(chain)
    for banned in ["risk_reward", "probability", "momentum"]:
        assert banned not in result.columns
        for sub in result["subscores"]:
            assert banned not in sub


def test_legacy_incompatible_weights_fallback_no_crash():
    """دیکشنری وزن قدیمی UI (که هنوز جایگزین نشده) نباید Crash کند."""
    chain = _make_chain()
    old_style_weights = {
        "liquidity": 0.20, "risk_reward": 0.20, "iv": 0.15,
        "probability": 0.15, "open_interest": 0.10, "mispricing": 0.10, "momentum": 0.10,
    }
    result = opportunity.detect_contract_opportunities(chain, weights=old_style_weights)
    assert not result.empty  # باید بی‌صدا به CONTRACT_WEIGHTS پیش‌فرض برگردد


def test_relative_iv_requires_min_peers_same_moneyness():
    """فقط یک ITM با IV واقعی و بقیه ITM بدون IV -> Relative IV باید None/Unavailable شود."""
    rows = [
        _base_row(900, 130, 128, 132, 500, 2000, 0.35, "ITM"),
        _base_row(950, 90, 87, 93, 300, 1200, None, "ITM"),
        _base_row(980, 60, 55, 65, 100, 400, None, "ITM"),
        _base_row(1000, 40, 38, 42, 800, 3000, 0.30, "ATM"),
        _base_row(1020, 25, 20, 30, 150, 900, 0.31, "ATM"),
        _base_row(1050, 15, 12, 18, 50, 300, 0.32, "ATM"),
    ]
    chain = pd.DataFrame(rows)
    result = opportunity.detect_contract_opportunities(chain)
    row = result[result["symbol"] == "OPT900"].iloc[0]
    assert row["subscores"]["relative_iv"] is None, "با کمتر از حداقل هم‌گروه هم‌سطح Moneyness، باید Unavailable باشد"


def test_oi_build_up_category_detected():
    chain = _make_chain()
    result = opportunity.detect_contract_opportunities(chain)
    # OPT900: oi=2000 prev=1500 => +33% => باید OI Build-up تگ بخورد
    row = result[result["symbol"] == "OPT900"].iloc[0]
    assert "OI Build-up" in row["categories"]


if __name__ == "__main__":
    test_eligibility_gate_excludes_no_participation_row()
    test_scores_within_bounds_and_have_coverage_confidence()
    test_no_permanently_none_components_remain()
    test_legacy_incompatible_weights_fallback_no_crash()
    test_relative_iv_requires_min_peers_same_moneyness()
    test_oi_build_up_category_detected()
    print("همه تست‌های Opportunity Engine v2 موفق بودند ✅")
