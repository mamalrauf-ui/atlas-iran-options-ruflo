"""
Data Provider Layer (بخش ۷، ۸ و ۸۶ سند).

هدف این لایه معرفی یک Interface یکسان روی منابع داده موجود است، بدون
اینکه core/live_data.py یا core/importer.py بازنویسی شوند — آن‌ها
Implementation واقعی هستند؛ این فایل فقط آن‌ها را پشت یک قرارداد مشترک
قرار می‌دهد تا در آینده (Scanner، Opportunity Engine، Data Center)
به یک Provider خاص Hard-code نشویم.

Provider اصلی (Primary): TSETMC زنده
Provider دستی (Manual/Fallback): Excel Import

فعلاً هیچ Provider ثانویه‌ی خودکار (fima یا Adapter دیگر) اضافه نشده،
چون در تصمیم‌گیری قبلی این پروژه، دسترسی مستقیم TSETMC ترجیح داده شد و
تست عملی نشان داد در دسترس و پایدار است.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from core import live_data
from core.schema import DataSource


class OptionsDataProvider:
    """Interface پایه؛ هر Provider واقعی باید این متدها را پیاده‌سازی کند."""

    name: str = "base"
    is_live: bool = False

    def get_option_chain(self, underlying: Optional[str] = None):
        """
        Returns: (options_df, underlying_df, report)
        options_df/underlying_df در Canonical Schema (core/schema.py) هستند.
        """
        raise NotImplementedError

    def health_check(self) -> dict:
        """برای UI بخش «Advanced Data Diagnostics» — بخش ۸۵ سند."""
        raise NotImplementedError


class TSETMCProvider(OptionsDataProvider):
    """Provider اصلی (Primary) — دسترسی مستقیم به API رسمی TSETMC."""

    name = DataSource.TSETMC_LIVE
    is_live = True

    def get_option_chain(self, underlying: Optional[str] = None):
        return live_data.fetch_option_chain(underlying_filter=underlying)

    def list_underlyings(self) -> list:
        return live_data.list_available_underlyings()

    def health_check(self) -> dict:
        import time
        started = time.time()
        try:
            records = live_data.fetch_raw_option_chain()
            return {
                "name": self.name,
                "status": "OK",
                "latency_seconds": round(time.time() - started, 2),
                "rows_received": len(records),
                "error": None,
            }
        except live_data.LiveDataError as exc:
            return {
                "name": self.name,
                "status": "UNAVAILABLE",
                "latency_seconds": round(time.time() - started, 2),
                "rows_received": 0,
                "error": str(exc),
            }


class ExcelProvider(OptionsDataProvider):
    """
    Provider دستی/Fallback — طبق بخش ۱۲ سند: وقتی TSETMC یک Metric را
    نمی‌تواند فراهم کند یا کاربر می‌خواهد داده تاریخی/آفلاین وارد کند.

    برخلاف TSETMCProvider این Provider مستقیماً فایل نمی‌خواند — چون
    ورودی آن مسیر یک فایل روی دیسک کاربر است، نه یک Endpoint بدون‌پارامتر؛
    بنابراین متدهای import_* را همان core/importer.py فراخوانی می‌کند و
    اینجا فقط برای یکنواختی Interface ثبت شده است.
    """

    name = DataSource.EXCEL_IMPORT
    is_live = False

    def get_option_chain(self, underlying: Optional[str] = None):
        raise NotImplementedError(
            "ExcelProvider به یک مسیر فایل نیاز دارد؛ مستقیماً از "
            "core.importer.import_excel(...) استفاده کنید."
        )

    def health_check(self) -> dict:
        return {"name": self.name, "status": "N/A", "note": "Provider دستی، وضعیت Live ندارد."}


# ---------------------------------------------------------------------------
# Registry مرکزی (بخش ۸۶ سند) — ترتیب یعنی اولویت Primary → Fallback → Manual
# ---------------------------------------------------------------------------
DATA_SOURCES: dict[str, OptionsDataProvider] = {
    "tsetmc": TSETMCProvider(),
    "excel": ExcelProvider(),
}


def get_provider(name: str) -> OptionsDataProvider:
    if name not in DATA_SOURCES:
        raise ValueError(f"Provider ناشناخته: {name}. گزینه‌های موجود: {list(DATA_SOURCES)}")
    return DATA_SOURCES[name]
