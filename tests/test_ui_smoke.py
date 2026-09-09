"""
Smoke Test واقعی صفحات UI (نه فقط منطق core).

تست‌های دیگر (test_opportunity_v2.py و ...) مستقیم توابع core/opportunity.py
را صدا می‌زنند و هرگز ui/*.py را واقعاً اجرا نمی‌کنند - برای همین باگی مثل
`NameError: name 'match' is not defined` که فقط داخل تابع render صفحه بود،
از دستشان در رفت. این فایل دقیقاً همان مسیر واقعی کاربر (باز کردن صفحه،
انتخاب اولین Dataset/Snapshot، دیدن اولین ردیف در پنل «چرا این فرصت؟») را
با Stub استریم‌لیت اجرا می‌کند.

اجرا: python tests/test_ui_smoke.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "stub"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402  - همان Stub
import pandas as pd  # noqa: E402

import core.database as db  # noqa: E402
db.DB_PATH = Path(tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

from core.schema import DataSource, DataQuality, ExerciseStyle  # noqa: E402
from ui import common  # noqa: E402


def _seed_dataset(name="SMOKE"):
    rows = []
    for strike in [900, 950, 980, 1000, 1020, 1050, 1080]:
        for opt_type, close in [("call", max(5, 1000 - strike + 40)),
                                 ("put", max(5, strike - 1000 + 40))]:
            rows.append({
                "quote_date": "2026-09-01", "symbol": f"{opt_type[0].upper()}{strike}",
                "underlying": "تست", "option_type": opt_type, "strike": float(strike),
                "expiry": "2026-12-01", "dte": 90, "close": float(close),
                "bid": close - 2, "ask": close + 2, "volume": 200, "open_interest": 1500,
                "previous_open_interest": 1400, "iv": 0.30, "delta": 0.5, "gamma": 0.01,
                "theta": -0.3, "vega": 1.0, "instrument_id": f"{opt_type[0]}{strike}",
                "contract_size": 1000, "exercise_style": ExerciseStyle.EUROPEAN,
                "source": DataSource.TSETMC_LIVE, "data_quality": DataQuality.LIVE,
                "bid_size": 10, "ask_size": 10,
            })
    options_df = pd.DataFrame(rows)
    underlying_df = pd.DataFrame([{"quote_date": "2026-09-01", "underlying": "تست", "close": 1000.0}])
    db.save_dataframe(options_df, name)
    db.save_underlying_dataframe(underlying_df, name)


def _init_session():
    st.session_state.clear()
    common.init_session_state()
    st.session_state["opp_dataset"] = "SMOKE"
    st.session_state["opp_qdate"] = "2026-09-01"


def test_opportunities_page_renders_without_error():
    _seed_dataset()
    _init_session()
    from ui import opportunities
    opportunities.render()  # اگر NameError/AttributeError باشد، همینجا Exception می‌دهد


def test_dashboard_page_renders_without_error():
    _init_session()
    from ui import dashboard
    dashboard.render()


def test_data_center_page_renders_without_error():
    _init_session()
    from ui import data_center
    data_center.render()


def test_settings_page_renders_without_error():
    _init_session()
    from ui import settings
    settings.render()


def test_strategy_lab_page_renders_without_error():
    _init_session()
    from ui import strategy_lab
    strategy_lab.render()


def test_strategy_lab_full_leg_transfer_from_opportunities():
    """
    رگرسیون یک باگ واقعی: «باز کردن در استراتژی لب» فقط پایه اول را منتقل
    می‌کرد و همیشه حالت «ترکیب دستی» (Manual) انتخاب می‌شد. این تست با
    Spy کردن روی st.selectbox تأیید می‌کند که با پیام جدید (چند پایه +
    template)، خود همان قالب استراتژی (نه Manual) پیش‌انتخاب می‌شود.
    """
    from unittest.mock import patch
    _init_session()
    st.session_state.pending_strategy_legs = {
        "dataset": "SMOKE", "underlying": "تست", "quote_date": "2026-09-01",
        "expiry": "2026-12-01", "template": "Bull Call Spread (اسپرد صعودی با Call)",
        "legs": [
            {"option_type": "call", "side": "buy", "strike": 950.0, "close": 60.0, "qty": 1, "contract_size": 1000},
            {"option_type": "call", "side": "sell", "strike": 1050.0, "close": 20.0, "qty": 1, "contract_size": 1000},
        ],
    }
    from ui import strategy_lab

    calls = []
    real_selectbox = st.selectbox

    def spy_selectbox(label, opts, index=0, **kw):
        calls.append((label, list(opts), index))
        return real_selectbox(label, opts, index=index, **kw)

    with patch.object(st, "selectbox", side_effect=spy_selectbox):
        strategy_lab.render()

    template_calls = [c for c in calls if c[0] == "قالب"]
    assert template_calls, "انتخاب‌گر قالب اصلاً رندر نشد"
    label, opts, index = template_calls[0]
    selected = opts[index]
    assert selected == "Bull Call Spread (اسپرد صعودی با Call)", (
        f"باید همان قالب منتقل‌شده پیش‌انتخاب شود، نه «{selected}» (باگ قبلی: همیشه Manual بود)"
    )


if __name__ == "__main__":
    import traceback
    tests = [test_opportunities_page_renders_without_error, test_dashboard_page_renders_without_error,
             test_data_center_page_renders_without_error, test_settings_page_renders_without_error,
             test_strategy_lab_page_renders_without_error, test_strategy_lab_full_leg_transfer_from_opportunities]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"✅ {t.__name__}")
        except Exception:
            failed += 1
            print(f"❌ {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} صفحه بدون خطا رندر شد")
    if failed:
        sys.exit(1)
