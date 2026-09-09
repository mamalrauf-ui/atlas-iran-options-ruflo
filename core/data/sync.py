"""
core/data/sync.py

هر بار کاربر روی «دریافت آخرین اطلاعات بازار» کلیک می‌کند (Manual-only،
طبق بخش ۱۴ سند)، این تابع اجرا و در sync_log ثبت می‌شود.
"""
from __future__ import annotations

import datetime as dt

from core import database
from core.data.providers.base import ProviderError
from core.data.snapshot import save_snapshot


def run_manual_sync(provider, dataset_name: str, underlying: str = None):
    """
    provider: نمونه‌ای از OptionsDataProvider (مثلاً TSETMCProvider())
    خروجی: dict گزارش کامل (برای نمایش مستقیم در UI)
    """
    started = dt.datetime.now()
    try:
        options_df, underlying_df, fetch_report = provider.get_option_chain(underlying=underlying)
    except ProviderError as exc:
        finished = dt.datetime.now()
        database.record_sync(
            provider=provider.name, started_at=started.isoformat(timespec="seconds"),
            finished_at=finished.isoformat(timespec="seconds"), status="FAILED",
            records_received=0, records_valid=0, records_rejected=0, error=str(exc),
        )
        return {"status": "FAILED", "error": str(exc)}

    snap_report = save_snapshot(options_df, underlying_df, dataset_name)
    finished = dt.datetime.now()

    status = "SUCCESS" if snap_report["records_valid"] > 0 else "PARTIAL"
    database.record_sync(
        provider=provider.name, started_at=started.isoformat(timespec="seconds"),
        finished_at=finished.isoformat(timespec="seconds"), status=status,
        records_received=snap_report["records_received"],
        records_valid=snap_report["records_valid"],
        records_rejected=snap_report["records_rejected"],
        warnings=snap_report["warnings"], error=None,
    )
    return {"status": status, "fetch_report": fetch_report, "snapshot_report": snap_report}


def save_previewed_snapshot(provider_name: str, options_df, underlying_df, dataset_name: str):
    """
    ذخیره‌ی دقیقاً همان داده‌ای که در Preview به کاربر نشان داده شده — بدون
    دریافت دوباره از Provider (بخش ۲۱ سند: عدم‌تطابق Preview و Save، چون
    بین این دو کلیک ممکن است بازار حرکت کرده باشد و «تأیید» کاربر برای
    داده‌ی دیگری بوده است).
    """
    started = dt.datetime.now()
    snap_report = save_snapshot(options_df, underlying_df, dataset_name)
    finished = dt.datetime.now()
    status = "SUCCESS" if snap_report["records_valid"] > 0 else "PARTIAL"
    database.record_sync(
        provider=provider_name, started_at=started.isoformat(timespec="seconds"),
        finished_at=finished.isoformat(timespec="seconds"), status=status,
        records_received=snap_report["records_received"],
        records_valid=snap_report["records_valid"],
        records_rejected=snap_report["records_rejected"],
        warnings=snap_report["warnings"], error=None,
    )
    return {"status": status, "snapshot_report": snap_report}
