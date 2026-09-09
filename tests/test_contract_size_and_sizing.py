"""
پوشش تست Contract Size + Position Sizing + Liquidity Capacity —
طبق چک‌لیست بخش ۲۶ سند «ATLAS Comprehensive Fix».
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from core import strategy as strat
from core import opportunity as opp
from core.opportunity_config import DEFAULT_CONTRACT_SIZE


# ===========================================================================
# Contract Size — Leg / Premium / Payoff / Net Premium / Max P&L / Strategy
# ===========================================================================
def test_leg_default_contract_size_is_1000():
    leg = strat.Leg("call", "buy", 1000, 40, 1)
    assert leg.contract_size == DEFAULT_CONTRACT_SIZE == 1000.0


def test_stock_leg_forces_contract_size_1_regardless_of_input():
    leg = strat.Leg("stock", "buy", 0, 1000, 1, contract_size=1000)
    assert leg.contract_size == 1.0, "پایه سهام هرگز نباید ضریب ۱۰۰۰ بگیرد"


def test_premium_scales_with_contract_size():
    leg_1000 = strat.Leg("call", "buy", 1000, 40, 1, contract_size=1000)
    leg_1 = strat.Leg("call", "buy", 1000, 40, 1, contract_size=1)
    premium_1000 = strat.net_premium([leg_1000])
    premium_1 = strat.net_premium([leg_1])
    assert premium_1000 == premium_1 * 1000


def test_custom_contract_size_from_provider_used_when_valid():
    """Contract Size واقعی Provider (مثلاً ۱۰) باید به‌جای ۱۰۰۰ استفاده شود."""
    leg = strat.Leg("call", "buy", 1000, 40, 1, contract_size=10)
    assert strat.net_premium([leg]) == -400.0  # 40 * 10 * 1، نه 40*1000


def test_missing_or_invalid_contract_size_falls_back_to_default():
    """اگر contract_size نامعتبر (۰ یا منفی) پاس داده نشود، dataclass با پیش‌فرض ۱۰۰۰ مقداردهی می‌شود."""
    leg = strat.Leg("call", "buy", 1000, 40, 1)  # contract_size پاس داده نشده
    assert leg.contract_size == 1000.0


def test_payoff_curve_scales_with_contract_size():
    legs_1000 = [strat.Leg("call", "buy", 1000, 40, 1, contract_size=1000)]
    legs_1 = [strat.Leg("call", "buy", 1000, 40, 1, contract_size=1)]
    S = [1100]
    p1000 = strat.payoff_curve(legs_1000, S)[0]
    p1 = strat.payoff_curve(legs_1, S)[0]
    assert p1000 == p1 * 1000


def test_max_profit_loss_scales_with_contract_size():
    legs_1000 = [strat.Leg("call", "buy", 950, 60, 1, contract_size=1000),
                 strat.Leg("call", "sell", 1050, 20, 1, contract_size=1000)]
    legs_1 = [strat.Leg("call", "buy", 950, 60, 1, contract_size=1),
              strat.Leg("call", "sell", 1050, 20, 1, contract_size=1)]
    mpl_1000 = strat.max_profit_loss(legs_1000, 1000)
    mpl_1 = strat.max_profit_loss(legs_1, 1000)
    assert abs(mpl_1000["max_profit"] - mpl_1["max_profit"] * 1000) < 0.01
    assert abs(mpl_1000["max_loss"] - mpl_1["max_loss"] * 1000) < 0.01


def test_breakeven_price_unaffected_by_contract_size():
    """محل قیمتیِ سربه‌سر نباید با تغییر Contract Size جابه‌جا شود؛ فقط مقیاس $ P&L تغییر می‌کند."""
    legs_1000 = [strat.Leg("call", "buy", 1000, 40, 1, contract_size=1000)]
    legs_1 = [strat.Leg("call", "buy", 1000, 40, 1, contract_size=1)]
    be_1000 = strat.breakevens(legs_1000, 1000.0)
    be_1 = strat.breakevens(legs_1, 1000.0)
    assert abs(be_1000[0] - be_1[0]) < 1e-6


def test_expected_value_scales_with_contract_size():
    legs_1000 = [strat.Leg("call", "buy", 1000, 40, 1, contract_size=1000)]
    legs_1 = [strat.Leg("call", "buy", 1000, 40, 1, contract_size=1)]
    sim_1000 = strat.simulate_outcome(legs_1000, 1000.0, 0.3, 30 / 365, 0.2, seed=42)
    sim_1 = strat.simulate_outcome(legs_1, 1000.0, 0.3, 30 / 365, 0.2, seed=42)
    assert abs(sim_1000["expected_value"] - sim_1["expected_value"] * 1000) < 1e-6
    assert sim_1000["pop"] == sim_1["pop"], "POP یک احتمال است و نباید با Contract Size تغییر کند"


def test_multi_leg_strategy_uses_per_leg_contract_size():
    """اگر پایه‌های یک استراتژی Contract Size متفاوت داشته باشند (نادر ولی ممکن)، هرکدام جدا اعمال شود."""
    legs = [
        strat.Leg("call", "buy", 950, 60, 1, contract_size=1000),
        strat.Leg("call", "sell", 1050, 20, 1, contract_size=500),
    ]
    premium = strat.net_premium(legs)
    expected = -(60 * 1000) + (20 * 500)
    assert premium == expected


# ===========================================================================
# Liquidity Capacity (بخش ۶ سند)
# ===========================================================================
def test_liquidity_capacity_uses_worst_leg_volume():
    leg_rows = [pd.Series({"volume": 500, "open_interest": 3000}),
                pd.Series({"volume": 30, "open_interest": 1000})]
    cap = opp._strategy_liquidity_capacity(leg_rows)
    assert cap == 30


def test_liquidity_capacity_falls_back_to_oi_when_volume_missing():
    leg_rows = [pd.Series({"volume": None, "open_interest": 200}),
                pd.Series({"volume": 500, "open_interest": 3000})]
    cap = opp._strategy_liquidity_capacity(leg_rows)
    assert cap == 200


def test_liquidity_capacity_unavailable_not_zero_when_all_missing():
    leg_rows = [pd.Series({"volume": None, "open_interest": None}),
                pd.Series({"volume": 500, "open_interest": 3000})]
    cap = opp._strategy_liquidity_capacity(leg_rows)
    assert cap is None, "نبود داده باید None باشد، نه صفر یا نادیده‌گرفتن پایه ناقص"


# ===========================================================================
# Position Sizing (بخش ۵ سند)
# ===========================================================================
def test_recommended_position_size_basic():
    units, reason = opp.recommended_position_size(max_loss_per_unit=-40_000, account_capital=100_000_000, risk_budget_pct=2.0)
    # بودجه ریسک = ۲٪ از ۱۰۰ میلیون = ۲ میلیون؛ هر واحد ۴۰ هزار زیان => ۵۰ واحد
    assert units == 50
    assert reason is None


def test_recommended_position_size_unbounded_risk_returns_none_with_reason():
    units, reason = opp.recommended_position_size(max_loss_per_unit=None, account_capital=100_000_000, risk_budget_pct=2.0)
    assert units is None
    assert reason is not None


def test_recommended_position_size_insufficient_budget_returns_zero_not_fake():
    units, reason = opp.recommended_position_size(max_loss_per_unit=-50_000_000, account_capital=100_000_000, risk_budget_pct=2.0)
    assert units == 0
    assert reason is not None


def test_recommended_position_size_invalid_capital():
    units, reason = opp.recommended_position_size(max_loss_per_unit=-1000, account_capital=0, risk_budget_pct=2.0)
    assert units is None and reason is not None


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
