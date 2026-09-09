"""
لایه دیتابیس - ذخیره‌سازی ساده روی SQLite (بدون نیاز به سرور جدا)

Migration: از نسخه Canonical Schema (core/schema.py) به بعد، ستون‌های
جدید با ALTER TABLE به جدول‌های موجود اضافه می‌شوند (_migrate_schema).
این کار Data-Preserving است — هیچ رکورد یا ستون قبلی حذف/تغییرنام
نمی‌شود؛ فقط ستون جدید با مقدار NULL برای رکوردهای قدیمی اضافه می‌شود.
"""
import sqlite3
import pandas as pd
from pathlib import Path

from core.schema import (
    LEGACY_OPTION_COLUMNS, LEGACY_UNDERLYING_COLUMNS,
    RAW_OPTION_FIELDS, DERIVED_OPTION_FIELDS, RAW_UNDERLYING_FIELDS,
)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "database.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS options_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset TEXT NOT NULL,
    quote_date TEXT NOT NULL,
    symbol TEXT,
    underlying TEXT NOT NULL,
    option_type TEXT NOT NULL,      -- 'call' یا 'put'
    strike REAL NOT NULL,
    expiry TEXT NOT NULL,
    dte INTEGER,
    close REAL,
    bid REAL,
    ask REAL,
    volume INTEGER,
    open_interest INTEGER,
    iv REAL,
    delta REAL,
    gamma REAL,
    theta REAL,
    vega REAL,
    rho REAL
);
CREATE INDEX IF NOT EXISTS idx_underlying ON options_data(underlying);
CREATE INDEX IF NOT EXISTS idx_dataset ON options_data(dataset);
CREATE INDEX IF NOT EXISTS idx_quote_date ON options_data(quote_date);

CREATE TABLE IF NOT EXISTS underlying_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset TEXT NOT NULL,
    quote_date TEXT NOT NULL,
    underlying TEXT NOT NULL,
    close REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_u_underlying ON underlying_data(underlying);
CREATE INDEX IF NOT EXISTS idx_u_quote_date ON underlying_data(quote_date);

-- استراتژی‌های ذخیره‌شده کاربر. legs به‌صورت JSON نگهداری می‌شود چون تعداد
-- و ترکیب پایه‌ها متغیر است و هیچ Query تحلیلی روی تک‌تک پایه‌ها لازم نداریم.
CREATE TABLE IF NOT EXISTS saved_strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    template TEXT,
    dataset TEXT,
    underlying TEXT,
    quote_date TEXT,
    expiry TEXT,
    spot REAL,
    legs_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- گزارش هر Sync دستی از یک Provider (بخش ۳۴ سند) — برای Debugging و
-- شفافیت منبع داده در Data Center.
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT,                  -- SUCCESS / FAILED / PARTIAL
    records_received INTEGER,
    records_valid INTEGER,
    records_rejected INTEGER,
    warnings_json TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_sync_started ON sync_log(started_at);
"""


# ---------------------------------------------------------------------------
# ستون‌های جدید Canonical Schema که با ALTER TABLE اضافه می‌شوند (Migration
# تدریجی — بدون بازطراحی کامل جدول‌ها، بدون از دست رفتن داده موجود).
# نوع SQLite برای هرکدام: بیشتر TEXT/REAL چون SQLite Type-Affinity آزاد دارد.
# ---------------------------------------------------------------------------
_NEW_OPTION_COLUMNS = {
    "instrument_id": "TEXT", "underlying_id": "TEXT",
    "contract_size": "REAL", "exercise_style": "TEXT",
    "open": "REAL", "high": "REAL", "low": "REAL",
    "previous_close": "REAL", "bid_size": "REAL", "ask_size": "REAL",
    "trade_count": "REAL", "turnover": "REAL", "previous_open_interest": "REAL",
    "source": "TEXT", "data_quality": "TEXT", "snapshot_timestamp": "TEXT",
    "oi_change": "REAL", "iv_source": "TEXT", "iv_price_source": "TEXT",
    "iv_confidence": "TEXT", "intrinsic_value": "REAL", "time_value": "REAL",
    "moneyness": "TEXT",
}

_NEW_UNDERLYING_COLUMNS = {
    "instrument_id": "TEXT", "open": "REAL", "high": "REAL", "low": "REAL",
    "previous_close": "REAL", "volume": "REAL",
    "source": "TEXT", "snapshot_timestamp": "TEXT",
}


def _migrate_schema(conn: sqlite3.Connection):
    """
    ستون‌های جدید Canonical Schema را در صورت نبودن اضافه می‌کند.
    Idempotent است — هر بار اجرا فقط ستون‌های واقعاً غایب را اضافه می‌کند.
    هیچ ستون یا رکورد موجودی حذف یا تغییرنام داده نمی‌شود.
    """
    for table, new_cols in (
        ("options_data", _NEW_OPTION_COLUMNS),
        ("underlying_data", _NEW_UNDERLYING_COLUMNS),
    ):
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for col, sql_type in new_cols.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {sql_type}")
    conn.commit()
    _ensure_duplicate_protection(conn)


def _ensure_duplicate_protection(conn: sqlite3.Connection):
    """
    Duplicate Protection سطح Database (خط دفاعی دوم، مکمل منطق Delete-then-Insert
    در save_dataframe). چون داده‌ی قدیمی کاربر ممکن است از قبل تکراری داشته
    باشد، قبل از ساخت UNIQUE INDEX ابتدا این تکراری‌ها با نگه‌داشتن اولین
    رکورد پاک می‌شوند — این تنها موردی است که این ماژول رکورد حذف می‌کند و
    فقط برای رکوردهای صددرصد یکسان (همان dataset+quote_date+symbol+نوع+
    Strike+سررسید) است، نه داده متفاوت.
    """
    try:
        conn.execute("""
            DELETE FROM options_data WHERE id NOT IN (
                SELECT MIN(id) FROM options_data
                GROUP BY dataset, quote_date, symbol, option_type, strike, expiry
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_option_snapshot
            ON options_data(dataset, quote_date, symbol, option_type, strike, expiry)
        """)
        conn.execute("""
            DELETE FROM underlying_data WHERE id NOT IN (
                SELECT MIN(id) FROM underlying_data
                GROUP BY dataset, quote_date, underlying
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_underlying_snapshot
            ON underlying_data(dataset, quote_date, underlying)
        """)
        conn.commit()
    except sqlite3.Error as exc:
        # هرگز اجرای برنامه را به‌خاطر این محافظت اضافه متوقف نمی‌کنیم؛
        # منطق Delete-then-Insert در save_dataframe همچنان خط دفاعی اصلی است.
        print(f"[WARN] ایجاد Unique Index محافظتی ممکن نشد (غیربحرانی): {exc}")


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    _migrate_schema(conn)
    return conn


def all_option_columns() -> list:
    """لیست کامل ستون‌های جدول options_data (Legacy + Canonical جدید)."""
    seen, cols = set(), []
    for c in LEGACY_OPTION_COLUMNS + list(_NEW_OPTION_COLUMNS.keys()):
        if c not in seen:
            seen.add(c)
            cols.append(c)
    return cols


def all_underlying_columns() -> list:
    seen, cols = set(), []
    for c in LEGACY_UNDERLYING_COLUMNS + list(_NEW_UNDERLYING_COLUMNS.keys()):
        if c not in seen:
            seen.add(c)
            cols.append(c)
    return cols


def save_dataframe(df: pd.DataFrame, dataset_name: str, replace_existing: bool = True):
    """
    ذخیره یک DataFrame تمیزشده در دیتابیس تحت یک نام Dataset مشخص.

    Duplicate Protection: اگر replace_existing=False باشد (مسیر Snapshot
    زنده - core/data/snapshot.py)، به‌جای Append خام که با هر بار
    «دریافت و ذخیره» مجدد همان روز، ردیف‌های تکراری می‌ساخت، ابتدا هر
    ردیف قدیمی مربوط به همان (dataset, quote_date) پاک و جایگزین می‌شود.
    تاریخ‌های دیگر (تاریخچه گذشته) دست‌نخورده می‌مانند.
    """
    conn = get_connection()
    try:
        if replace_existing:
            conn.execute("DELETE FROM options_data WHERE dataset = ?", (dataset_name,))
        elif "quote_date" in df.columns:
            for qd in df["quote_date"].dropna().unique().tolist():
                conn.execute(
                    "DELETE FROM options_data WHERE dataset = ? AND quote_date = ?",
                    (dataset_name, qd),
                )
        df = df.copy()
        df["dataset"] = dataset_name
        cols = all_option_columns()
        for c in cols:
            if c not in df.columns:
                df[c] = None
        df[cols].to_sql("options_data", conn, if_exists="append", index=False)
        conn.commit()
        return len(df)
    finally:
        conn.close()


def save_underlying_dataframe(df: pd.DataFrame, dataset_name: str, replace_existing: bool = True):
    """ذخیره قیمت دارایی پایه (برای استفاده در محاسبه Greeks و Backtest). همان قاعده Duplicate Protection بالا."""
    conn = get_connection()
    try:
        if replace_existing:
            conn.execute("DELETE FROM underlying_data WHERE dataset = ?", (dataset_name,))
        elif "quote_date" in df.columns:
            for qd in df["quote_date"].dropna().unique().tolist():
                conn.execute(
                    "DELETE FROM underlying_data WHERE dataset = ? AND quote_date = ?",
                    (dataset_name, qd),
                )
        df = df.copy()
        df["dataset"] = dataset_name
        cols = all_underlying_columns()
        for c in cols:
            if c not in df.columns:
                df[c] = None
        df[cols].to_sql("underlying_data", conn, if_exists="append", index=False)
        conn.commit()
        return len(df)
    finally:
        conn.close()


def load_underlying_data(dataset_name: str = None, underlying: str = None) -> pd.DataFrame:
    conn = get_connection()
    try:
        q = "SELECT * FROM underlying_data WHERE 1=1"
        params = []
        if dataset_name:
            q += " AND dataset = ?"
            params.append(dataset_name)
        if underlying:
            q += " AND underlying = ?"
            params.append(underlying)
        return pd.read_sql(q, conn, params=params)
    finally:
        conn.close()


def list_datasets():
    conn = get_connection()
    try:
        q = """
        SELECT dataset,
               COUNT(*) AS rows,
               MIN(quote_date) AS from_date,
               MAX(quote_date) AS to_date,
               COUNT(DISTINCT underlying) AS underlyings
        FROM options_data
        GROUP BY dataset
        ORDER BY to_date DESC
        """
        return pd.read_sql(q, conn)
    finally:
        conn.close()


def delete_dataset(dataset_name: str):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM options_data WHERE dataset = ?", (dataset_name,))
        conn.commit()
    finally:
        conn.close()


def list_underlyings(dataset_name: str = None):
    conn = get_connection()
    try:
        if dataset_name:
            q = "SELECT DISTINCT underlying FROM options_data WHERE dataset = ? ORDER BY underlying"
            return pd.read_sql(q, conn, params=(dataset_name,))["underlying"].tolist()
        q = "SELECT DISTINCT underlying FROM options_data ORDER BY underlying"
        return pd.read_sql(q, conn)["underlying"].tolist()
    finally:
        conn.close()


def load_data(dataset_name: str = None, underlying: str = None,
              quote_date: str = None, expiry: str = None) -> pd.DataFrame:
    conn = get_connection()
    try:
        q = "SELECT * FROM options_data WHERE 1=1"
        params = []
        if dataset_name:
            q += " AND dataset = ?"
            params.append(dataset_name)
        if underlying:
            q += " AND underlying = ?"
            params.append(underlying)
        if quote_date:
            q += " AND quote_date = ?"
            params.append(quote_date)
        if expiry:
            q += " AND expiry = ?"
            params.append(expiry)
        return pd.read_sql(q, conn, params=params)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# استراتژی‌های ذخیره‌شده
# ---------------------------------------------------------------------------
def save_strategy(name: str, legs: list, template: str = None, dataset: str = None,
                  underlying: str = None, quote_date: str = None, expiry: str = None,
                  spot: float = None) -> bool:
    """
    ذخیره یک استراتژی. legs لیستی از dict با کلیدهای
    option_type/side/strike/premium/qty است (نه شیء Leg، تا وابستگی
    لایه داده به لایه محاسبات ایجاد نشود).
    اگر نامی تکراری باشد، رکورد قبلی جایگزین می‌شود.
    """
    import json
    from datetime import datetime

    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO saved_strategies
               (name, template, dataset, underlying, quote_date, expiry, spot, legs_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                 template=excluded.template, dataset=excluded.dataset,
                 underlying=excluded.underlying, quote_date=excluded.quote_date,
                 expiry=excluded.expiry, spot=excluded.spot,
                 legs_json=excluded.legs_json, created_at=excluded.created_at""",
            (name, template, dataset, underlying, quote_date, expiry, spot,
             json.dumps(legs, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def list_strategies() -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql("SELECT * FROM saved_strategies ORDER BY created_at DESC", conn)
    finally:
        conn.close()


def load_strategy(name: str):
    """خروجی: dict با legs از قبل decode‌شده، یا None."""
    import json
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT * FROM saved_strategies WHERE name = ?", conn, params=(name,))
        if df.empty:
            return None
        rec = df.iloc[0].to_dict()
        rec["legs"] = json.loads(rec.pop("legs_json"))
        return rec
    finally:
        conn.close()


def delete_strategy(name: str):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM saved_strategies WHERE name = ?", (name,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sync Log — بخش ۳۴ سند: ثبت هر بار دریافت دستی داده از یک Provider
# ---------------------------------------------------------------------------
def record_sync(provider: str, started_at: str, finished_at: str, status: str,
                 records_received: int = None, records_valid: int = None,
                 records_rejected: int = None, warnings: list = None, error: str = None):
    import json
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO sync_log
               (provider, started_at, finished_at, status, records_received,
                records_valid, records_rejected, warnings_json, error)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (provider, started_at, finished_at, status, records_received,
             records_valid, records_rejected,
             json.dumps(warnings or [], ensure_ascii=False), error),
        )
        conn.commit()
    finally:
        conn.close()


def list_sync_log(limit: int = 20) -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql(
            "SELECT * FROM sync_log ORDER BY started_at DESC LIMIT ?", conn, params=(limit,)
        )
    finally:
        conn.close()
