"""
core/data/providers/fima.py

Provider fima — هم Historical (بخش ۳-۱۳ سند) و هم Current Option Chain
(بخش ۱۴-۱۶ سند).

نکات فنی که از خواندن مستقیم کد نصب‌شده fima تأیید شدند (نه حدسی):

  - `download_historical_data(ticker)` یک **نماد اختیار معامله مشخص** لازم
    دارد (مثل «ضهرم6040»)، نه نماد دارایی پایه؛ و فقط قیمت/حجم برمی‌گرداند
    (Date/Quantity/Volume/Value/MinPrice/MaxPrice/FirstPrice/LastPrice/
    ClosePrice) — هیچ Metadata (Strike/Expiry/Type/Underlying) و هیچ Open
    Interest ندارد.
  - `ticker_info(ticker)` یک DataFrame تک‌ردیفه برمی‌گرداند (نه dict) با
    ستون‌های UATicker/StrikePrice/MaturityDate/DaysToMaturity/Type —
    Metadata واقعی باید از همینجا بیاید، نه با Parse حدسی نام نماد.
    `MaturityDate` از نوع jdatetime.date است و `DaysToMaturity` نسبت به
    **امروز** محاسبه می‌شود (نه نسبت به هر رکورد تاریخی).
  - `download_chain_contracts(underlying_ticker)` مستقیماً همان Endpoint
    `GetInstrumentOptionMarketWatch` را می‌خواند و یک ردیف به‌ازای هر Strike
    با ستون‌های `-C`/`-P` برمی‌گرداند (OI جاری و OI دیروز هر دو موجودند).

اصل معماری ATLAS که این Provider هم رعایت می‌کند: IV/Greeks اینجا محاسبه
نمی‌شوند — فقط داده خام Provider، محاسبات در core/pricing.py انجام می‌شود.

⚠️ هشدار صادقانه: امکان تست شبکه واقعی (cdn.tsetmc.com) در این محیط توسعه
وجود ندارد. تمام نگاشت‌ها از خواندن دقیق کد fima نوشته شده‌اند و با داده
Mock ساختگی (منطبق دقیق با ساختار واقعی) تست شده‌اند، اما تست Live روی
شبکه واقعی هنوز باید توسط کاربر انجام شود.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import pandas as pd

from core.data.historical import apply_historical_floor
from core.data.providers.base import OptionsDataProvider, ProviderError
from core.schema import DataSource, DataQuality

try:
    import fima.Options as fima_options
    import jdatetime
    HAS_FIMA = True
except ImportError:
    HAS_FIMA = False


def _gregorian_to_jalali_str(d: dt.date) -> str:
    j = jdatetime.date.fromgregorian(date=d)
    return f"{j.year:04d}-{j.month:02d}-{j.day:02d}"


def _jalali_col_to_gregorian_str(series: pd.Series) -> pd.Series:
    """ستون Date خروجی fima از نوع jdatetime.date است؛ به رشته میلادی ISO تبدیل می‌شود."""
    return series.apply(lambda jd: str(jd.togregorian()) if jd is not None else None)


def _jalali_to_gregorian_str(value) -> Optional[str]:
    if value is None:
        return None
    try:
        return str(value.togregorian())
    except AttributeError:
        return None


class FimaProvider(OptionsDataProvider):
    """
    هویت این Provider «FIMA» است — مستقل از source هر رکورد.

    قبلاً name روی DataSource.FIMA_HISTORICAL ثابت بود، در نتیجه حتی وقتی
    get_option_chain (که source=FIMA_CURRENT تولید می‌کند) فراخوانی می‌شد،
    sync_log و health_check مقدار «FIMA_HISTORICAL» را گزارش می‌کردند —
    یک ناسازگاری واقعی بین Provider Identity و Data Source (بخش ۱۳ سند).

    از این پس:
      - name = هویت ثابت Provider ("FIMA")
      - source هر رکورد (FIMA_CURRENT / FIMA_HISTORICAL) همچنان جدا و
        دقیقاً همان‌جایی تعیین می‌شود که بوده (سطح رکورد)، دست‌نخورده.
      - هر متد (get_option_chain / get_historical) مقدار «source» درست
        خودش را در report برمی‌گرداند تا مصرف‌کننده (Data Center/sync_log)
        هم Provider و هم Source واقعی را ببیند.
    """
    name = "FIMA"
    is_live = False
    is_historical = True

    def _require_fima(self):
        if not HAS_FIMA:
            raise ProviderError(
                "پکیج fima نصب نیست. اجرا کنید: pip install fima"
            )

    # -----------------------------------------------------------------
    # Current Option Chain — بخش ۱۴-۱۶ سند
    # -----------------------------------------------------------------
    def get_option_chain(self, underlying: Optional[str] = None):
        """
        زنجیره جاری یک دارایی پایه، از طریق fima.download_chain_contracts.
        underlying الزامی است (بر خلاف TSETMCProvider که کل بازار را هم
        می‌تواند بدهد) — چون این تابع fima ذاتاً برای یک Underlying مشخص
        طراحی شده.

        Returns: (options_df, underlying_df, report) در Canonical Schema
        """
        self._require_fima()
        if not underlying:
            raise ProviderError("fima.download_chain_contracts به یک نام دارایی پایه مشخص نیاز دارد.")

        try:
            raw = fima_options.download_chain_contracts(
                underlying, j_date=True, bsm=False, greeks=False, implied_volatility=False,
            )
        except Exception as exc:  # noqa: BLE001 - خطای شبکه/Parsing پکیج شخص‌ثالث
            raise ProviderError(f"دریافت زنجیره جاری از fima ممکن نشد: {exc}") from exc

        if raw is None or raw.empty:
            raise ProviderError(f"fima هیچ زنجیره‌ای برای «{underlying}» برنگرداند.")

        quote_date_str = str(dt.date.today())
        option_rows, underlying_row = [], None

        for _, r in raw.iterrows():
            expiry_str = _jalali_to_gregorian_str(r.get("EndDate"))
            if expiry_str is None or pd.isna(r.get("StrikePrice")):
                continue

            if underlying_row is None and pd.notna(r.get("ClosePrice-UA")):
                underlying_row = {
                    "quote_date": quote_date_str, "underlying": r.get("Ticker-UA"),
                    "instrument_id": r.get("InstrumentCode-UA"),
                    "close": float(r["ClosePrice-UA"]),
                    "previous_close": float(r["YesterdayPrice-UA"]) if pd.notna(r.get("YesterdayPrice-UA")) else None,
                    "source": DataSource.FIMA_CURRENT,
                }

            common = {
                "quote_date": quote_date_str, "underlying": r.get("Ticker-UA"),
                "underlying_id": r.get("InstrumentCode-UA"),
                "strike": float(r["StrikePrice"]), "expiry": expiry_str,
                "dte": int(r["DaysToMaturity"]) if pd.notna(r.get("DaysToMaturity")) else None,
                "contract_size": float(r["ContractSize"]) if pd.notna(r.get("ContractSize")) else None,
                "source": DataSource.FIMA_CURRENT, "data_quality": DataQuality.LIVE,
                "snapshot_timestamp": dt.datetime.now().isoformat(timespec="seconds"),
                "iv": None, "delta": None, "gamma": None, "theta": None, "vega": None,
            }

            if pd.notna(r.get("Ticker-C")):
                oi_c = float(r["OpenPositions-C"]) if pd.notna(r.get("OpenPositions-C")) else None
                prev_oi_c = float(r["YesterdayOpenPositions-C"]) if pd.notna(r.get("YesterdayOpenPositions-C")) else None
                option_rows.append({
                    **common, "symbol": r.get("Ticker-C"), "option_type": "call",
                    "instrument_id": r.get("InstrumentCode-C"),
                    "close": float(r["ClosePrice-C"]) if pd.notna(r.get("ClosePrice-C")) else None,
                    "previous_close": float(r["YesterdayPrice-C"]) if pd.notna(r.get("YesterdayPrice-C")) else None,
                    "bid": float(r["BidPrice-C"]) if pd.notna(r.get("BidPrice-C")) else None,
                    "ask": float(r["AskPrice-C"]) if pd.notna(r.get("AskPrice-C")) else None,
                    "bid_size": float(r["BidVolume-C"]) if pd.notna(r.get("BidVolume-C")) else None,
                    "ask_size": float(r["AskVolume-C"]) if pd.notna(r.get("AskVolume-C")) else None,
                    "volume": float(r["Volume-C"]) if pd.notna(r.get("Volume-C")) else None,
                    "trade_count": float(r["Quantity-C"]) if pd.notna(r.get("Quantity-C")) else None,
                    "turnover": float(r["Value-C"]) if pd.notna(r.get("Value-C")) else None,
                    "open_interest": oi_c, "previous_open_interest": prev_oi_c,
                    "oi_change": (oi_c - prev_oi_c) if (oi_c is not None and prev_oi_c is not None) else None,
                })

            if pd.notna(r.get("Ticker-P")):
                oi_p = float(r["OpenPositions-P"]) if pd.notna(r.get("OpenPositions-P")) else None
                prev_oi_p = float(r["YesterdayOpenPositions-P"]) if pd.notna(r.get("YesterdayOpenPositions-P")) else None
                option_rows.append({
                    **common, "symbol": r.get("Ticker-P"), "option_type": "put",
                    "instrument_id": r.get("InstrumentCode-P"),
                    "close": float(r["ClosePrice-P"]) if pd.notna(r.get("ClosePrice-P")) else None,
                    "previous_close": float(r["YesterdayPrice-P"]) if pd.notna(r.get("YesterdayPrice-P")) else None,
                    "bid": float(r["BidPrice-P"]) if pd.notna(r.get("BidPrice-P")) else None,
                    "ask": float(r["AskPrice-P"]) if pd.notna(r.get("AskPrice-P")) else None,
                    "bid_size": float(r["BidVolume-P"]) if pd.notna(r.get("BidVolume-P")) else None,
                    "ask_size": float(r["AskVolume-P"]) if pd.notna(r.get("AskVolume-P")) else None,
                    "volume": float(r["Volume-P"]) if pd.notna(r.get("Volume-P")) else None,
                    "trade_count": float(r["Quantity-P"]) if pd.notna(r.get("Quantity-P")) else None,
                    "turnover": float(r["Value-P"]) if pd.notna(r.get("Value-P")) else None,
                    "open_interest": oi_p, "previous_open_interest": prev_oi_p,
                    "oi_change": (oi_p - prev_oi_p) if (oi_p is not None and prev_oi_p is not None) else None,
                })

        options_df = pd.DataFrame(option_rows)
        underlying_df = pd.DataFrame([underlying_row] if underlying_row else [])
        report = {
            "provider": self.name, "source": DataSource.FIMA_CURRENT, "underlying": underlying,
            "rows_option": len(options_df), "rows_underlying": len(underlying_df),
        }
        return options_df, underlying_df, report

    # -----------------------------------------------------------------
    # Historical — بخش ۳-۱۳ سند
    # -----------------------------------------------------------------
    def get_historical(self, option_symbol: str,
                        start_date: Optional[dt.date] = None,
                        end_date: Optional[dt.date] = None):
        """
        دریافت تاریخچه یک **قرارداد اختیار معامله مشخص** (نه نماد دارایی
        پایه — بخش ۳ سند) از طریق fima.

        Returns
        -------
        (option_history_df, underlying_history_df, report) در Canonical Schema
        """
        self._require_fima()

        try:
            meta = fima_options.ticker_info(option_symbol)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"دریافت Metadata قرارداد «{option_symbol}» از fima ممکن نشد: {exc}") from exc
        if meta is None or meta.empty:
            raise ProviderError(f"fima هیچ Metadata‌ای برای «{option_symbol}» برنگرداند.")

        underlying_ticker = meta.loc[0, "UATicker"]
        strike = float(meta.loc[0, "StrikePrice"])
        expiry_str = _jalali_to_gregorian_str(meta.loc[0, "MaturityDate"])
        option_type = "call" if str(meta.loc[0, "Type"]).lower() == "call" else "put"
        if expiry_str is None:
            raise ProviderError(f"سررسید «{option_symbol}» از fima قابل تفسیر نبود.")

        kwargs = {}
        if start_date is not None and end_date is not None:
            kwargs["start_date"] = _gregorian_to_jalali_str(start_date)
            kwargs["end_date"] = _gregorian_to_jalali_str(end_date)

        try:
            opt_raw, ua_raw = fima_options.download_historical_data(option_symbol, **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"دریافت تاریخچه از fima ممکن نشد: {exc}") from exc
        if opt_raw is None or ua_raw is None:
            raise ProviderError(f"fima هیچ داده تاریخی قیمتی برای «{option_symbol}» برنگرداند.")

        option_df = self._map_option_history(
            opt_raw, symbol=option_symbol, underlying=underlying_ticker,
            option_type=option_type, strike=strike, expiry_str=expiry_str,
        )
        underlying_df = self._map_underlying_history(ua_raw, underlying=underlying_ticker)

        option_df = apply_historical_floor(option_df, "quote_date")
        underlying_df = apply_historical_floor(underlying_df, "quote_date")

        report = {
            "provider": self.name, "source": DataSource.FIMA_HISTORICAL,
            "symbol": option_symbol, "underlying": underlying_ticker,
            "option_type": option_type, "strike": strike, "expiry": expiry_str,
            "rows_option": len(option_df), "rows_underlying": len(underlying_df),
            "note": ("Open Interest، Previous Close، Contract Size و Instrument IDهای تاریخی "
                     "در این منبع موجود نیستند (Missing، نه صفر/حدسی)."),
        }
        return option_df, underlying_df, report

    @staticmethod
    def _map_option_history(raw: pd.DataFrame, symbol: str, underlying: str,
                             option_type: str, strike: float, expiry_str: str) -> pd.DataFrame:
        """
        نگاشت تاریخچه قیمت + تزریق Metadata واقعی (از ticker_info، نه حدس)
        به هر ردیف. DTE برای هر ردیف نسبت به quote_date همان ردیف محاسبه
        می‌شود، نه نسبت به امروز (بخش ۶ سند).
        """
        out = pd.DataFrame()
        out["quote_date"] = _jalali_col_to_gregorian_str(raw["Date"])
        out["open"] = pd.to_numeric(raw.get("FirstPrice"), errors="coerce")
        out["high"] = pd.to_numeric(raw.get("MaxPrice"), errors="coerce")
        out["low"] = pd.to_numeric(raw.get("MinPrice"), errors="coerce")
        out["close"] = pd.to_numeric(raw.get("ClosePrice"), errors="coerce")
        out["volume"] = pd.to_numeric(raw.get("Volume"), errors="coerce")
        out["trade_count"] = pd.to_numeric(raw.get("Quantity"), errors="coerce")
        out["turnover"] = pd.to_numeric(raw.get("Value"), errors="coerce")

        out["symbol"] = symbol
        out["underlying"] = underlying
        out["option_type"] = option_type
        out["strike"] = strike
        out["expiry"] = expiry_str
        expiry_date = dt.date.fromisoformat(expiry_str)
        out["dte"] = pd.to_datetime(out["quote_date"]).apply(lambda d: (expiry_date - d.date()).days)

        # طبق بخش ۷، ۸، ۹، ۱۰ سند: هیچ‌کدام از این‌ها را حدس نمی‌زنیم؛
        # عمداً None می‌مانند تا بعداً Layer محاسباتی/Provider دیگری پرشان کند.
        out["open_interest"] = None
        out["previous_open_interest"] = None
        out["previous_close"] = None
        out["contract_size"] = None
        out["instrument_id"] = None
        out["underlying_id"] = None
        out["iv"] = None
        out["delta"] = out["gamma"] = out["theta"] = out["vega"] = None

        out["source"] = DataSource.FIMA_HISTORICAL
        out["data_quality"] = DataQuality.HISTORICAL
        out["snapshot_timestamp"] = None
        return out

    @staticmethod
    def _map_underlying_history(raw: pd.DataFrame, underlying: str) -> pd.DataFrame:
        out = pd.DataFrame()
        out["quote_date"] = _jalali_col_to_gregorian_str(raw["Date"])
        out["open"] = pd.to_numeric(raw.get("FirstPrice"), errors="coerce")
        out["high"] = pd.to_numeric(raw.get("MaxPrice"), errors="coerce")
        out["low"] = pd.to_numeric(raw.get("MinPrice"), errors="coerce")
        out["close"] = pd.to_numeric(raw.get("ClosePrice"), errors="coerce")
        out["volume"] = pd.to_numeric(raw.get("Volume"), errors="coerce")
        out["underlying"] = underlying  # بخش ۱۱ سند: هرگز underlying=None ذخیره نشود
        out["previous_close"] = None
        out["instrument_id"] = None
        out["source"] = DataSource.FIMA_HISTORICAL
        out["snapshot_timestamp"] = None
        return out

    def health_check(self) -> dict:
        if not HAS_FIMA:
            return {"name": self.name, "status": "NOT_INSTALLED",
                    "error": "pip install fima"}
        return {"name": self.name, "status": "OK (نصب شده - Health واقعی نیازمند تست شبکه است)",
                "error": None}
