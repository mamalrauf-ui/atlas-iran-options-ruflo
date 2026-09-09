"""
کامپوننت‌های قابل‌استفاده مجدد ATLAS (بخش ۶۲ Master Prompt).

هیچ منطق تحلیلی اینجا نیست — فقط Rendering. همه رنگ‌ها از core.design می‌آیند.
قاعده RTL/LTR (بخش ۱۳): هر عدد/نماد لاتین داخل کلاس .num قرار می‌گیرد تا
جهت آن LTR و ایزوله بماند و در متن فارسی به‌هم نریزد.
"""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from core.design import TOKENS

# ---------------------------------------------------------------------------
# فرمت‌دهی اعداد — یک قاعده در کل محصول (بخش ۶۷)
# ---------------------------------------------------------------------------
NA = "—"


def _is_na(v) -> bool:
    if v is None:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def fmt_int(v) -> str:
    if _is_na(v):
        return NA
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return NA


def fmt_compact(v) -> str:
    """1.24B / 8.42M / 12.3K — برای اعداد بزرگ در KPI و جدول."""
    if _is_na(v):
        return NA
    try:
        v = float(v)
    except (TypeError, ValueError):
        return NA
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:.2f}B"
    if a >= 1e6:
        return f"{v / 1e6:.2f}M"
    if a >= 1e3:
        return f"{v / 1e3:.1f}K"
    return f"{v:,.0f}"


def fmt_pct(v, decimals: int = 1, already_pct: bool = False) -> str:
    """v نسبتی (0.384) یا درصدی (38.4) بسته به already_pct."""
    if _is_na(v):
        return NA
    try:
        x = float(v) if already_pct else float(v) * 100
    except (TypeError, ValueError):
        return NA
    return f"{x:.{decimals}f}%"


def fmt_change(v, decimals: int = 1) -> str:
    if _is_na(v):
        return NA
    return f"{float(v):+.{decimals}f}%"


def fmt_ratio(v, decimals: int = 2) -> str:
    if _is_na(v):
        return NA
    try:
        return f"{float(v):.{decimals}f}"
    except (TypeError, ValueError):
        return NA


def fmt_price(v) -> str:
    return fmt_int(v)


def num(text: str) -> str:
    """پیچیدن یک مقدار عددی/لاتین در span ایزوله LTR."""
    return f'<span class="num">{html.escape(str(text))}</span>'


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


# ---------------------------------------------------------------------------
# هدر صفحه + وضعیت داده (بخش ۱۸ و ۶)
# ---------------------------------------------------------------------------
def page_header(title: str, subtitle: str = "", snapshot_label: str | None = None,
                status: str = "ok", status_text: str | None = None):
    """
    هدر فشرده. هرگز «Live/Real-time» نمایش داده نمی‌شود (بخش ۶).
    status: ok | warn | err
    """
    meta = ""
    if snapshot_label:
        meta += f'<div class="snap">Snapshot: {esc(snapshot_label)}</div>'
    if status_text:
        meta += f'<div class="status {esc(status)}"><span class="dot"></span>{esc(status_text)}</div>'

    st.markdown(
        f"""
        <div class="page-head">
          <div>
            <div class="page-title">{esc(title)}</div>
            <div class="page-sub">{esc(subtitle)}</div>
          </div>
          <div class="meta">{meta}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section(title: str, note: str = ""):
    """عنوان بخش — بدون Card، فقط تایپوگرافی (بخش ۱۵/۱۶)."""
    note_html = f'<div class="section-note">{esc(note)}</div>' if note else ""
    st.markdown(
        f'<div class="sec-head"><div><div class="section-title">{esc(title)}</div>{note_html}</div></div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# نوار KPI ثابت (بخش ۲۵)
# ---------------------------------------------------------------------------
def kpi_strip(items: list[dict]):
    """
    items: [{"label", "value" (str آماده), "change" (str یا None),
             "tone": "pos"|"neg"|"neu", "na": bool}]
    یک نوار واحد رندر می‌شود، نه چند کارت شناور.
    """
    cells = []
    for it in items:
        val_cls = "kpi-value na" if it.get("na") else "kpi-value"
        change = ""
        if it.get("change"):
            change = f'<div class="kpi-change {it.get("tone", "neu")}">{esc(it["change"])}</div>'
        cells.append(
            f'<div class="kpi"><div class="kpi-label">{esc(it["label"])}</div>'
            f'<div class="{val_cls}">{esc(it["value"])}</div>{change}</div>'
        )
    st.markdown(f'<div class="kpi-strip">{"".join(cells)}</div>', unsafe_allow_html=True)


def change_tone(change_pct, meaningful: bool = True) -> str:
    """سبز/قرمز فقط وقتی جهت واقعاً معنای مالی دارد (بخش ۱۰)."""
    if change_pct is None or not meaningful:
        return "neu"
    return "pos" if change_pct > 0 else ("neg" if change_pct < 0 else "neu")


# ---------------------------------------------------------------------------
# Badgeها
# ---------------------------------------------------------------------------
def moneyness_badge(bucket: str | None) -> str:
    """رنگ + برچسب متنی — نه فقط رنگ (بخش ۶۶)."""
    if not bucket:
        return f'<span class="muted">{NA}</span>'
    cls = {"ITM": "itm", "ATM": "atm", "OTM": "otm"}.get(bucket, "atm")
    return f'<span class="badge {cls}">{bucket}</span>'


def signal_badge(text: str) -> str:
    return f'<span class="badge sig">{esc(text)}</span>'


def type_label(option_type: str) -> str:
    return {"call": "Call", "put": "Put", "stock": "سهم"}.get(option_type, "—")


# ---------------------------------------------------------------------------
# جدول (بخش ۲۲)
# ---------------------------------------------------------------------------
def table(headers: list[str], rows: list[list[str]], numeric_cols: set[int] | None = None):
    """
    جدول سبک ATLAS. مقادیر سلول‌ها باید از قبل با esc/num آماده شده باشند
    (اجازه HTML عمدی برای Badge). ستون‌های numeric_cols چپ‌چین و مونواسپیس.
    """
    numeric_cols = numeric_cols or set()
    th = "".join(
        f'<th class="{"num" if i in numeric_cols else ""}">{esc(h)}</th>'
        for i, h in enumerate(headers)
    )
    trs = []
    for r in rows:
        tds = "".join(
            f'<td class="{"num" if i in numeric_cols else ""}">{c}</td>'
            for i, c in enumerate(r)
        )
        trs.append(f"<tr>{tds}</tr>")
    st.markdown(
        f'<div class="table-wrap"><table class="atlas-table">'
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table></div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# حالت‌های خالی / خطا / بارگذاری (بخش ۶۹–۷۱)
# ---------------------------------------------------------------------------
def empty_state(title: str, description: str = ""):
    st.markdown(
        f'<div class="state-box"><div class="t">{esc(title)}</div>'
        f'<div class="d">{esc(description)}</div></div>',
        unsafe_allow_html=True,
    )


def error_state(title: str, description: str = ""):
    st.markdown(
        f'<div class="state-box err"><div class="t">{esc(title)}</div>'
        f'<div class="d">{esc(description)}</div></div>',
        unsafe_allow_html=True,
    )


def helper(text: str):
    st.markdown(f'<div class="helper">{esc(text)}</div>', unsafe_allow_html=True)


def spacer(px: int = 24):
    st.markdown(f'<div style="height:{int(px)}px"></div>', unsafe_allow_html=True)
