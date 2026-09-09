"""
تست core/data/providers/fima.py با Mock دقیقاً منطبق با ساختار واقعی
ticker_info() / download_historical_data() / download_chain_contracts()
(از خواندن کد نصب‌شده fima، نه حدسی). بدون نیاز به اینترنت.
"""
import datetime as dt
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jdatetime
import pandas as pd

from core.data.providers import fima as fima_provider_module
from core.data.providers.fima import FimaProvider
from core.data.providers.base import ProviderError
from core.data.historical import HISTORICAL_START_DATE


# ---------------------------------------------------------------------------
# Mock ticker_info() -- خروجی واقعی یک DataFrame تک‌ردیفه است
# ---------------------------------------------------------------------------
def _mock_ticker_info():
    df = pd.DataFrame(columns=["UATicker", "StrikePrice", "MaturityDate", "DaysToMaturity", "Type"], index=[0])
    df.loc[0, "UATicker"] = "اهرم"
    df.loc[0, "StrikePrice"] = 26000
    df.loc[0, "MaturityDate"] = jdatetime.date(1405, 6, 25)  # -> میلادی 2026-09-16
    df.loc[0, "DaysToMaturity"] = 8  # نسبت به "امروزِ" fima؛ نباید مستقیم استفاده شود
    df.loc[0, "Type"] = "Call"
    return df


def _mock_price_history(jalali_dates, closes):
    return pd.DataFrame({
        "Date": [jdatetime.date(*d) for d in jalali_dates],
        "Quantity": [10] * len(jalali_dates),
        "Volume": [1000] * len(jalali_dates),
        "Value": [1e7] * len(jalali_dates),
        "MinPrice": [c - 5 for c in closes],
        "MaxPrice": [c + 5 for c in closes],
        "FirstPrice": closes,
        "LastPrice": closes,
        "ClosePrice": closes,
    })


def test_get_historical_injects_metadata_and_computes_dte_per_record():
    dates = [(1405, 6, 1), (1405, 6, 5), (1405, 6, 10)]
    opt_df = _mock_price_history(dates, [100, 110, 120])
    ua_df = _mock_price_history(dates, [58000, 59000, 60000])

    provider = FimaProvider()
    with patch.object(fima_provider_module, "HAS_FIMA", True), \
         patch.object(fima_provider_module, "fima_options") as mock_fima:
        mock_fima.ticker_info.return_value = _mock_ticker_info()
        mock_fima.download_historical_data.return_value = (opt_df, ua_df)
        option_hist, underlying_hist, report = provider.get_historical("ضهرم6040")

    assert len(option_hist) == 3
    row = option_hist.iloc[0]
    assert row["symbol"] == "ضهرم6040"
    assert row["underlying"] == "اهرم"
    assert row["option_type"] == "call"
    assert row["strike"] == 26000.0
    assert row["expiry"] == "2026-09-16"
    # quote_date ردیف اول -> 1405/06/01 == میلادی 2026-08-23؛ DTE باید نسبت
    # به همین quote_date محاسبه شود، نه نسبت به "امروز" fima (که ۸ بود).
    expected_dte = (dt.date(2026, 9, 16) - dt.date.fromisoformat(row["quote_date"])).days
    assert row["dte"] == expected_dte
    assert row["dte"] != 8, "DTE نباید مقدار امروزِ ticker_info (نسبت به روز اجرا) باشد"

    assert report["underlying"] == "اهرم" and report["strike"] == 26000.0


def test_get_historical_never_fabricates_oi_contract_size_or_ids():
    dates = [(1405, 6, 1), (1405, 6, 5)]
    opt_df = _mock_price_history(dates, [100, 110])
    ua_df = _mock_price_history(dates, [58000, 59000])

    provider = FimaProvider()
    with patch.object(fima_provider_module, "HAS_FIMA", True), \
         patch.object(fima_provider_module, "fima_options") as mock_fima:
        mock_fima.ticker_info.return_value = _mock_ticker_info()
        mock_fima.download_historical_data.return_value = (opt_df, ua_df)
        option_hist, underlying_hist, report = provider.get_historical("ضهرم6040")

    for col in ["open_interest", "previous_open_interest", "previous_close",
                "contract_size", "instrument_id", "underlying_id", "iv"]:
        assert option_hist[col].isna().all(), f"{col} باید کاملاً None/NaN بماند، نه صفر یا حدسی"
    assert option_hist["source"].iloc[0] == "FIMA_HISTORICAL"
    assert option_hist["data_quality"].iloc[0] == "HISTORICAL"


def test_underlying_history_never_has_none_underlying_name():
    dates = [(1405, 6, 1)]
    opt_df = _mock_price_history(dates, [100])
    ua_df = _mock_price_history(dates, [58000])

    provider = FimaProvider()
    with patch.object(fima_provider_module, "HAS_FIMA", True), \
         patch.object(fima_provider_module, "fima_options") as mock_fima:
        mock_fima.ticker_info.return_value = _mock_ticker_info()
        mock_fima.download_historical_data.return_value = (opt_df, ua_df)
        _opt, underlying_hist, _report = provider.get_historical("ضهرم6040")

    assert not underlying_hist.empty
    assert underlying_hist["underlying"].iloc[0] == "اهرم"
    assert underlying_hist["underlying"].notna().all()


def test_get_historical_applies_historical_floor():
    dates = [(1404, 12, 20), (1405, 1, 5)]  # اولی قبل از سقف، دومی بعدش
    opt_df = _mock_price_history(dates, [100, 110])
    ua_df = _mock_price_history(dates, [58000, 59000])

    provider = FimaProvider()
    with patch.object(fima_provider_module, "HAS_FIMA", True), \
         patch.object(fima_provider_module, "fima_options") as mock_fima:
        mock_fima.ticker_info.return_value = _mock_ticker_info()
        mock_fima.download_historical_data.return_value = (opt_df, ua_df)
        option_hist, underlying_hist, _report = provider.get_historical("ضهرم6040")

    assert len(option_hist) == 1
    assert pd.to_datetime(option_hist["quote_date"]).iloc[0].date() >= HISTORICAL_START_DATE


# ---------------------------------------------------------------------------
# Current Option Chain
# ---------------------------------------------------------------------------
def _mock_chain_row():
    return {
        "EndDate": jdatetime.date(1405, 6, 25), "StrikePrice": 26000,
        "DaysToMaturity": 8, "ContractSize": 1000,
        "Ticker-UA": "اهرم", "InstrumentCode-UA": "17914401175772326",
        "ClosePrice-UA": 58889, "YesterdayPrice-UA": 56762,
        "Ticker-C": "ضهرم6040", "InstrumentCode-C": "2",
        "ClosePrice-C": 33006, "YesterdayPrice-C": 32346,
        "BidPrice-C": 32001, "AskPrice-C": 33132,
        "BidVolume-C": 2, "AskVolume-C": 10,
        "Volume-C": 425, "Quantity-C": 53, "Value-C": 14027608000.0,
        "OpenPositions-C": 27671, "YesterdayOpenPositions-C": 27828,
        "Ticker-P": "طهرم6040", "InstrumentCode-P": "1",
        "ClosePrice-P": 9, "YesterdayPrice-P": 10,
        "BidPrice-P": 8, "AskPrice-P": 13,
        "BidVolume-P": 3643, "AskVolume-P": 203,
        "Volume-P": 22055, "Quantity-P": 67, "Value-P": 193549000.0,
        "OpenPositions-P": 129517, "YesterdayOpenPositions-P": 128351,
    }


def test_get_option_chain_maps_call_put_and_oi_change():
    raw = pd.DataFrame([_mock_chain_row()])
    provider = FimaProvider()
    with patch.object(fima_provider_module, "HAS_FIMA", True), \
         patch.object(fima_provider_module, "fima_options") as mock_fima:
        mock_fima.download_chain_contracts.return_value = raw
        options_df, underlying_df, report = provider.get_option_chain(underlying="اهرم")

    assert len(options_df) == 2
    call_row = options_df[options_df["option_type"] == "call"].iloc[0]
    put_row = options_df[options_df["option_type"] == "put"].iloc[0]

    assert call_row["symbol"] == "ضهرم6040"
    assert call_row["expiry"] == "2026-09-16"
    assert call_row["strike"] == 26000.0
    assert call_row["dte"] == 8  # 18E: DTE mapping از DaysToMaturity
    assert call_row["open_interest"] == 27671.0
    assert call_row["previous_open_interest"] == 27828.0
    assert call_row["oi_change"] == 27671.0 - 27828.0
    assert call_row["source"] == "FIMA_CURRENT"
    assert call_row["data_quality"] == "LIVE"  # 18L: Data Quality برای Current
    assert call_row["iv"] is None  # Greeks/IV هرگز اینجا محاسبه نمی‌شوند

    assert put_row["symbol"] == "طهرم6040"
    assert put_row["bid"] == 8.0 and put_row["ask"] == 13.0

    assert not underlying_df.empty
    assert underlying_df.iloc[0]["underlying"] == "اهرم"
    assert underlying_df.iloc[0]["close"] == 58889.0


def test_get_option_chain_requires_underlying():
    provider = FimaProvider()
    with patch.object(fima_provider_module, "HAS_FIMA", True):
        try:
            provider.get_option_chain(underlying=None)
            assert False, "باید ProviderError بدهد"
        except ProviderError:
            pass


# ---------------------------------------------------------------------------
# Not Installed
# ---------------------------------------------------------------------------
def test_not_installed_raises_provider_error_not_crash():
    provider = FimaProvider()
    with patch.object(fima_provider_module, "HAS_FIMA", False):
        try:
            provider.get_historical("اهرم")
            assert False, "باید ProviderError پرتاب شود"
        except ProviderError:
            pass
        health = provider.health_check()
        assert health["status"] == "NOT_INSTALLED"


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
