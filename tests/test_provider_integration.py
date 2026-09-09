"""
tests/test_provider_integration.py

Regression tests برای مواردی که در این مرحله از پروژه ATLAS اصلاح شد:

  A. Registry مرکزی Provider واقعاً tsetmc و fima را می‌شناسد (core/data/providers/__init__.py)
  B. Provider Identity (FimaProvider.name) از Data Source (FIMA_CURRENT/FIMA_HISTORICAL)
     جدا است و هرگز با هم قاطی نمی‌شوند (بخش ۱۳ سند)
  C. End-to-End واقعی: FIMA (Mock دقیقاً منطبق با ساختار واقعی) -> run_manual_sync
     -> Database -> database.load_data(...) همان مسیری که Data Center/Chain/
     Historical Analysis/Backtest/Strategy Opportunities از آن می‌خوانند.
  D. previous_open_interest/oi_change mapping از طریق همین مسیر کامل (نه فقط
     مستقیم روی Provider) هم درست باقی می‌ماند.
  E. sync_log از provider واقعی ("FIMA") ثبت می‌شود، نه "FIMA_HISTORICAL"
     صرف‌نظر از این‌که Current بوده یا Historical.

بدون نیاز به pytest یا شبکه واقعی (طبق محدودیت محیط این پروژه).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jdatetime
import pandas as pd

# --- Database را روی یک فایل موقت جدا اجرا می‌کنیم تا داده واقعی کاربر
#     دست‌نخورده بماند و تست‌ها Idempotent/ایزوله باشند.
import core.database as database
_TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
database.DB_PATH = Path(_TMP_DB.name)

from core.data.providers import get_provider, PROVIDERS, list_providers
from core.data.providers.fima import FimaProvider
from core.data.providers.tsetmc import TSETMCProvider
from core.data.providers import fima as fima_provider_module
from core.data.sync import run_manual_sync
from core.schema import DataSource


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


# ---------------------------------------------------------------------------
# A) Registry
# ---------------------------------------------------------------------------
def test_registry_knows_tsetmc_and_fima():
    assert "tsetmc" in PROVIDERS and "fima" in PROVIDERS
    assert isinstance(get_provider("tsetmc"), TSETMCProvider)
    assert isinstance(get_provider("fima"), FimaProvider)
    assert set(list_providers()) == {"tsetmc", "fima"}


def test_registry_rejects_unknown_provider():
    try:
        get_provider("does_not_exist")
        assert False, "باید ValueError بدهد"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# B) Provider Identity vs Data Source
# ---------------------------------------------------------------------------
def test_fima_provider_identity_is_stable_and_separate_from_source():
    provider = get_provider("fima")
    # هویت Provider باید همیشه یکسان باشد - نه FIMA_CURRENT، نه FIMA_HISTORICAL
    assert provider.name == "FIMA"
    assert provider.name not in (DataSource.FIMA_CURRENT, DataSource.FIMA_HISTORICAL)


def test_current_chain_report_has_correct_source():
    raw = pd.DataFrame([_mock_chain_row()])
    provider = FimaProvider()
    with patch.object(fima_provider_module, "HAS_FIMA", True), \
         patch.object(fima_provider_module, "fima_options") as mock_fima:
        mock_fima.download_chain_contracts.return_value = raw
        options_df, underlying_df, report = provider.get_option_chain(underlying="اهرم")

    assert report["provider"] == "FIMA"
    assert report["source"] == DataSource.FIMA_CURRENT
    assert (options_df["source"] == DataSource.FIMA_CURRENT).all()


def test_historical_report_has_correct_source():
    dates = [(1405, 6, 1), (1405, 6, 5)]
    meta = pd.DataFrame(columns=["UATicker", "StrikePrice", "MaturityDate", "DaysToMaturity", "Type"], index=[0])
    meta.loc[0] = ["اهرم", 26000, jdatetime.date(1405, 6, 25), 8, "Call"]
    hist = pd.DataFrame({
        "Date": [jdatetime.date(*d) for d in dates],
        "Quantity": [10, 12], "Volume": [100, 120], "Value": [1e6, 1.2e6],
        "MinPrice": [95, 105], "MaxPrice": [105, 115],
        "FirstPrice": [100, 110], "LastPrice": [100, 110], "ClosePrice": [100, 110],
    })
    provider = FimaProvider()
    with patch.object(fima_provider_module, "HAS_FIMA", True), \
         patch.object(fima_provider_module, "fima_options") as mock_fima:
        mock_fima.ticker_info.return_value = meta
        mock_fima.download_historical_data.return_value = (hist, hist)
        _opt, _ua, report = provider.get_historical("ضهرم6040")

    assert report["provider"] == "FIMA"
    assert report["source"] == DataSource.FIMA_HISTORICAL


# ---------------------------------------------------------------------------
# C/D/E) End-to-End: FIMA -> run_manual_sync -> Database -> load_data
#         دقیقاً همان مسیری که Data Center تب «دریافت بازار (FIMA)» می‌رود.
# ---------------------------------------------------------------------------
def test_fima_current_chain_reaches_database_end_to_end():
    raw = pd.DataFrame([_mock_chain_row()])
    provider = get_provider("fima")
    dataset_name = "TEST_FIMA_E2E"

    with patch.object(fima_provider_module, "HAS_FIMA", True), \
         patch.object(fima_provider_module, "fima_options") as mock_fima:
        mock_fima.download_chain_contracts.return_value = raw
        result = run_manual_sync(provider, dataset_name, underlying="اهرم")

    assert result["status"] == "SUCCESS"
    assert result["fetch_report"]["provider"] == "FIMA"
    assert result["fetch_report"]["source"] == DataSource.FIMA_CURRENT

    # همان مسیری که Dashboard/Option Chain/Opportunities/Backtest/Analytics
    # با آن Database را می‌خوانند (ui/common.py::load_dataset -> database.load_data)
    loaded = database.load_data(dataset_name=dataset_name, underlying="اهرم")
    assert len(loaded) == 2  # یک Call + یک Put

    call_row = loaded[loaded["option_type"] == "call"].iloc[0]
    assert call_row["symbol"] == "ضهرم6040"
    assert call_row["source"] == DataSource.FIMA_CURRENT
    assert call_row["data_quality"] == "LIVE"

    # previous_open_interest / oi_change باید از طریق کل مسیر (نه فقط
    # مستقیم روی Provider) هم درست از Database برگردد.
    assert float(call_row["open_interest"]) == 27671.0
    assert float(call_row["previous_open_interest"]) == 27828.0
    assert float(call_row["oi_change"]) == 27671.0 - 27828.0

    # sync_log باید provider="FIMA" ثبت کرده باشد، نه "FIMA_HISTORICAL"
    log = database.list_sync_log(limit=5)
    fima_entries = log[log["provider"] == "FIMA"]
    assert not fima_entries.empty, "sync_log باید provider=FIMA (نه FIMA_HISTORICAL) ثبت کند"

    database.delete_dataset(dataset_name)


def test_fima_provider_error_recorded_as_failed_sync_not_crash():
    provider = get_provider("fima")
    with patch.object(fima_provider_module, "HAS_FIMA", False):
        result = run_manual_sync(provider, "TEST_FIMA_FAIL", underlying="اهرم")
    assert result["status"] == "FAILED"
    assert "error" in result


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
