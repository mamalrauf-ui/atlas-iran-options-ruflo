"""
core/data/historical.py

بخش ۱۱-۱۲ سند: محدودیت سخت‌گیرانه تاریخ شروع Historical Data + Sync تدریجی
(فقط تاریخ‌های غایب دریافت شوند، نه کل تاریخچه هر بار).
"""
from __future__ import annotations

import datetime as dt

# طبق دستور صریح سند: هیچ داده تاریخی قبل از این تاریخ دریافت/وارد نشود.
# ۱۴۰۵/۰۱/۰۱ (شمسی) = ۲۰۲۶-۰۳-۲۱ (میلادی)
HISTORICAL_START_DATE_JALALI = "1405/01/01"
HISTORICAL_START_DATE = dt.date(2026, 3, 21)


def apply_historical_floor(df, date_column: str = "quote_date"):
    """
    هر ردیفی با تاریخ قبل از HISTORICAL_START_DATE را حذف می‌کند (Filter Out
    طبق بخش ۱۱ سند) — نه اینکه صرفاً هشدار بدهد؛ سند صراحتاً می‌گوید
    داده قدیمی‌تر نباید وارد سیستم شود.
    """
    import pandas as pd
    if df is None or df.empty or date_column not in df.columns:
        return df
    dates = pd.to_datetime(df[date_column], errors="coerce").dt.date
    mask = dates >= HISTORICAL_START_DATE
    return df[mask].copy()


def find_missing_dates(existing_dates: list, available_dates: list) -> list:
    """
    برای Sync تدریجی (بخش ۱۲ سند): فقط تاریخ‌هایی که در Provider موجودند
    ولی در Database نیستند را برمی‌گرداند. idempotent و duplicate-safe —
    اگر existing_dates خالی باشد، همه available_dates (که از سقف تاریخی
    فیلتر نشده باشند) برگردانده می‌شوند.
    """
    existing = {str(d) for d in existing_dates}
    floor = HISTORICAL_START_DATE
    missing = []
    for d in available_dates:
        d_obj = d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d))
        if d_obj < floor:
            continue
        if str(d_obj) not in existing:
            missing.append(str(d_obj))
    return sorted(missing)
