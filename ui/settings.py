"""
Settings — تنظیمات (بخش ۶۱ Master Prompt).

Settings عمداً کوچک می‌ماند و محل تخلیه کنترل‌های تحلیلی نیست. فقط مقادیری
که واقعاً روی محاسبات یا نمایش اثر دارند و کاربر باید بتواند تغییرشان دهد.
"""
from __future__ import annotations

import streamlit as st

from core import database
from core.opportunity_config import CONTRACT_WEIGHTS, STRATEGY_WEIGHTS
from ui import common
from ui import components as c
from ui.common import JD

APP_VERSION = "2.0 — بازطراحی"


def render():
    c.page_header("تنظیمات", "پیکربندی ATLAS")

    # ---------------- پارامترهای محاسباتی ----------------
    c.section("پارامترهای محاسبه", "این مقادیر مستقیماً روی اعداد همه صفحات اثر دارند")
    g1, g2, _ = st.columns([1.2, 1.2, 2])
    with g1:
        new_r = st.number_input(
            "نرخ بدون ریسک", 0.0, 1.0, float(st.session_state.risk_free_rate), 0.01,
            format="%.2f", key="set_rfr",
            help="در قیمت‌گذاری، Greeks و احتمال سودآوری استفاده می‌شود.",
        )
    with g2:
        new_band = st.number_input(
            "باند ATM (٪)", 0.1, 10.0, float(st.session_state.atm_band_pct), 0.5,
            format="%.1f", key="set_band",
            help="قراردادهایی که قیمت اعمالشان در این فاصله از قیمت دارایی پایه است، ATM شمرده می‌شوند.",
        )

    changed = (new_r != st.session_state.risk_free_rate or new_band != st.session_state.atm_band_pct)
    if changed:
        st.session_state.risk_free_rate = new_r
        st.session_state.atm_band_pct = new_band
        # این دو پارامتر بخشی از کلید Cache هستند، ولی نتایج قدیمی را
        # پاک می‌کنیم تا حافظه با نسخه‌های متعدد پر نشود.
        common.clear_caches()
        st.markdown('<div class="chips"><span class="chip pos">تنظیمات اعمال شد — '
                    'محاسبات صفحات با مقدار جدید بازسازی می‌شوند.</span></div>',
                    unsafe_allow_html=True)

    c.helper("نرخ بدون ریسک روی Delta، Gamma، Theta، Vega و POP اثر دارد. "
             "باند ATM فقط طبقه‌بندی نمایشی ITM/ATM/OTM را تغییر می‌دهد و هیچ قیمتی را جابه‌جا نمی‌کند.")

    # ---------------- وزن‌های امتیازدهی ----------------
    c.spacer(24)
    c.section("وزن‌های امتیاز فرصت", "پیش‌فرض کل برنامه — در خود صفحه فرصت‌ها هم قابل تغییر است")

    c.helper("Contract و Strategy از دو مدل امتیازدهی کاملاً مستقل استفاده می‌کنند "
             "(بخش ۱۵ سند بازطراحی) — وزن‌هایشان هم جدا مدیریت می‌شود.")

    wc = st.session_state.opportunity_weights_contract
    rows_c = [[c.esc(k), c.num(f"{v:.2f}"),
               c.num(f"{v / sum(wc.values()) * 100:.0f}%" if sum(wc.values()) else "—")]
              for k, v in wc.items()]
    st.markdown("**وزن‌های Contract Opportunity**")
    c.table(["مؤلفه", "وزن", "سهم نسبی"], rows_c, numeric_cols={1, 2})

    ws = st.session_state.opportunity_weights_strategy
    rows_s = [[c.esc(k), c.num(f"{v:.2f}"),
               c.num(f"{v / sum(ws.values()) * 100:.0f}%" if sum(ws.values()) else "—")]
              for k, v in ws.items()]
    st.markdown("**وزن‌های Strategy Opportunity**")
    c.table(["مؤلفه", "وزن", "سهم نسبی"], rows_s, numeric_cols={1, 2})

    if st.button("بازگردانی هر دو به پیش‌فرض", type="secondary", key="set_reset_w"):
        st.session_state.opportunity_weights_contract = dict(CONTRACT_WEIGHTS)
        st.session_state.opportunity_weights_strategy = dict(STRATEGY_WEIGHTS)
        st.rerun()
    c.helper("وزن‌ها فقط روی مؤلفه‌های قابل‌محاسبه اعمال و سپس بازتوزیع می‌شوند؛ "
             "مؤلفه بدون داده هرگز با صفر جایگزین نمی‌شود.")

    # ---------------- وضعیت داده ----------------
    c.spacer(24)
    c.section("داده")
    datasets = database.list_datasets()
    if datasets.empty:
        c.empty_state("داده‌ای وارد نشده", "از «مرکز داده» شروع کنید.")
    else:
        total_rows = int(datasets["rows"].sum())
        c.kpi_strip([
            {"label": "مجموعه‌ها", "value": c.fmt_int(len(datasets)), "na": False},
            {"label": "کل ردیف‌ها", "value": c.fmt_compact(total_rows), "na": False},
            {"label": "آخرین Snapshot", "value": JD(datasets["to_date"].max()), "na": False},
            {"label": "قدیمی‌ترین", "value": JD(datasets["from_date"].min()), "na": False},
            {"label": "استراتژی ذخیره‌شده",
             "value": c.fmt_int(len(database.list_strategies())), "na": False},
            {"label": "نسخه داده", "value": "EOD", "na": False},
        ])
        if st.button("پاک‌کردن حافظه موقت (Cache)", type="secondary", key="set_clear_cache"):
            common.clear_caches()
            st.success("حافظه موقت پاک شد. صفحات با داده تازه از دیتابیس بازسازی می‌شوند.")

    # ---------------- درباره ----------------
    c.spacer(24)
    c.section("درباره")
    rows = [
        ["ATLAS", c.esc(APP_VERSION)],
        ["نوع داده", "پایان روز معاملاتی (End-of-Day) — بدون داده لحظه‌ای"],
        ["زبان", "فارسی"],
        ["پوسته", "تیره"],
    ]
    c.table(["", ""], rows)
    c.helper("Atlas داده لحظه‌ای ندارد و هیچ عددی در آن به‌عنوان قیمت زنده نمایش داده نمی‌شود. "
             "همه ارقام مربوط به Snapshot انتخاب‌شده هستند.")
