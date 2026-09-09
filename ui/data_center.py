"""
Data Center — مدیریت داده (بخش ۵۹ و ۶۰ Master Prompt).

پرسش اصلی صفحه: «داده‌های Atlas چه وضعیتی دارند و چگونه مدیریت می‌شوند؟»

این صفحه مدیریتی است، نه تحلیلی. جریان ورود داده به‌صورت پلکانی است:
    ۱ بارگذاری → ۲ تشخیص → ۳ بررسی → ۴ ثبت
منطق قدرتمند importer دست‌نخورده می‌ماند و فقط پشت یک UI ساده قرار می‌گیرد.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile

import pandas as pd
import streamlit as st

from core import analytics, database, importer, live_data
from core.data.providers import get_provider, ProviderError
from core.data.sync import run_manual_sync, save_previewed_snapshot
from ui import common
from ui import components as c
from ui.common import JD, _jalali_date_cols

KIND_SCREENER = "خروجی مستقیم سایت آپشن‌گر"
KIND_OPTIONS = "اطلاعات اختیار معامله"
KIND_UNDERLYING = "فقط قیمت دارایی پایه"


def render():
    datasets = database.list_datasets()
    status, text = ("ok", "داده به‌روز است") if not datasets.empty else ("err", "داده‌ای موجود نیست")
    last = JD(datasets["to_date"].max()) if not datasets.empty else None

    c.page_header("مرکز داده", "دریافت، مدیریت و بررسی کیفیت داده‌های بازار",
                  snapshot_label=last, status=status, status_text=text)

    # طبق تصمیم معماری جدید: TSETMC مسیر اصلی زنده است و FIMA مسیر دوم
    # (Current + Historical) — هر دو از همان core.data.providers Registry
    # می‌آیند (بخش ۵ سند: نقطه واحد انتخاب Provider). Excel/ورود دستی
    # همچنان کار می‌کند، اما فقط به‌عنوان مسیر دستی/اضطراری، در آخرین تب.
    tab_live, tab_fima, tab_sets, tab_quality, tab_manual = st.tabs(
        ["دریافت بازار (TSETMC)", "دریافت بازار (FIMA)", "مجموعه‌ها", "کیفیت داده", "ورود دستی (اضطراری)"]
    )
    with tab_live:
        _live_flow()
    with tab_fima:
        _fima_flow()
    with tab_sets:
        _datasets(datasets)
    with tab_quality:
        _quality(datasets)
    with tab_manual:
        _import_flow()


# ===========================================================================
# دریافت زنده از API رسمی TSETMC
# ===========================================================================
def _live_flow():
    c.section(
        "دریافت زنده از TSETMC",
        "یک Snapshot لحظه‌ای از API رسمی بورس گرفته می‌شود و به‌عنوان یک "
        "مجموعه (Dataset) جدید ذخیره می‌گردد. فایل‌های اکسل موجود دست‌نخورده می‌مانند.",
    )
    c.helper(
        "این داده فقط شامل قیمت، حجم، بهترین خرید/فروش و موقعیت باز است. "
        "Greeks و نوسان ضمنی مثل همیشه توسط موتور داخلی ATLAS محاسبه می‌شود، نه توسط این منبع."
    )

    scope = st.radio(
        "دامنه دریافت",
        ["فقط یک دارایی پایه", "کل بازار"],
        key="dc_live_scope",
        horizontal=True,
        captions=["سریع‌تر و پیشنهادی برای شروع", "همه دارایی‌های پایه — ممکن است حجیم باشد"],
    )

    underlying_filter = None
    if scope == "فقط یک دارایی پایه":
        col1, col2 = st.columns([2, 1])
        with col2:
            fetch_list = st.button("بارگذاری لیست نمادها از بازار", key="dc_live_list_btn")
        if fetch_list:
            try:
                with st.spinner("در حال دریافت لیست دارایی‌های پایه از TSETMC..."):
                    st.session_state["dc_live_underlyings"] = live_data.list_available_underlyings()
            except live_data.LiveDataError as exc:
                st.session_state.pop("dc_live_underlyings", None)
                c.error_state("دریافت لیست نمادها ممکن نشد", str(exc))

        options_list = st.session_state.get("dc_live_underlyings", [])
        with col1:
            if options_list:
                underlying_filter = st.selectbox("دارایی پایه", options_list, key="dc_live_ua")
            else:
                underlying_filter = st.text_input(
                    "دارایی پایه (نام دقیق فارسی، مثل «اهرم»)", key="dc_live_ua_text",
                    help="یا روی «بارگذاری لیست نمادها» کلیک کنید تا از یک لیست انتخاب کنید.",
                )

    dataset_name = st.text_input(
        "نام مجموعه (Dataset)", key="dc_live_name",
        placeholder=f"مثلاً: زنده {JD(str(dt.date.today()))}",
    )

    if st.button("دریافت و پیش‌نمایش", type="primary", key="dc_live_fetch_btn"):
        if scope == "فقط یک دارایی پایه" and not (underlying_filter or "").strip():
            c.error_state("دارایی پایه لازم است", "یک دارایی پایه انتخاب یا وارد کنید.")
        else:
            try:
                with st.spinner("در حال دریافت داده زنده از TSETMC..."):
                    options_df, underlying_df, report = get_provider("tsetmc").get_option_chain(
                        underlying=underlying_filter if scope == "فقط یک دارایی پایه" else None
                    )
            except Exception as exc:
                st.session_state.pop("dc_live_fetched", None)
                c.error_state("دریافت داده زنده ممکن نشد", str(exc))
            else:
                if options_df.empty:
                    st.session_state.pop("dc_live_fetched", None)
                    c.error_state(
                        "هیچ قرارداد معتبری یافت نشد",
                        "دارایی پایه را بررسی کنید یا «کل بازار» را امتحان کنید.",
                    )
                else:
                    # ذخیره در session_state تا با رفرش بعدی (مثلاً کلیک دکمه ذخیره) از دست نرود؛
                    # Streamlit با هر تعامل کل اسکریپت را دوباره اجرا می‌کند و هیچ متغیر محلی
                    # بین دو اجرا زنده نمی‌ماند.
                    st.session_state["dc_live_fetched"] = {
                        "options_df": options_df, "underlying_df": underlying_df,
                        "report": report, "underlying_filter": underlying_filter,
                        "scope": scope,
                    }

    fetched = st.session_state.get("dc_live_fetched")
    if not fetched:
        return

    options_df, underlying_df, report = fetched["options_df"], fetched["underlying_df"], fetched["report"]

    c.spacer(16)
    c.kpi_strip([
        {"label": "دارایی‌های پایه", "value": c.fmt_int(report["underlyings_found"]), "na": False},
        {"label": "Call", "value": c.fmt_int(report["call_count"]), "na": False},
        {"label": "Put", "value": c.fmt_int(report["put_count"]), "na": False},
        {"label": "ردیف نادیده‌گرفته‌شده", "value": c.fmt_int(report["skipped_rows"]), "na": False},
        {"label": "زمان دریافت", "value": report["fetched_at"][11:19], "na": False},
    ])

    with st.expander(f"پیش‌نمایش {min(len(options_df), 20)} ردیف اول"):
        st.dataframe(_jalali_date_cols(options_df.head(20), ["quote_date", "expiry"]),
                     use_container_width=True, hide_index=True)

    c.spacer(16)
    if not dataset_name.strip():
        st.info("برای ذخیره، یک نام برای مجموعه (Dataset) در بالا وارد کنید.")
    elif st.button("تأیید و ذخیره به‌عنوان مجموعه جدید", type="primary", key="dc_live_save_btn"):
        # دقیقاً همان داده‌ی Preview ذخیره می‌شود، نه یک دریافت تازه از
        # TSETMC (بخش ۲۱ سند) — چون بین کلیک Preview و کلیک Save ممکن است
        # بازار حرکت کرده باشد و «تأیید» کاربر برای داده‌ی دیگری بی‌معنا شود.
        result = save_previewed_snapshot(
            get_provider("tsetmc").name, options_df, underlying_df, dataset_name.strip(),
        )
        common.clear_caches()
        snap = result.get("snapshot_report", {})
        if result["status"] == "FAILED":
            c.error_state("Sync ناموفق بود", result.get("error", ""))
        else:
            msg = (f"{snap.get('records_valid', 0):,} ردیف معتبر ذخیره شد "
                   f"({snap.get('records_rejected', 0)} ردیف نامعتبر رد شد). "
                   f"مجموعه: «{dataset_name.strip()}»")
            if snap.get("underlying_rows_saved"):
                msg += f" + {snap['underlying_rows_saved']:,} ردیف قیمت دارایی پایه."
            st.success(msg)
            if snap.get("warnings"):
                with st.expander("جزئیات اعتبارسنجی"):
                    for w in snap["warnings"]:
                        st.write("• " + w)
            # بعد از ذخیره موفق، Snapshot از حافظه پاک شود تا کاربر دوباره تصادفی ذخیره نکند
            st.session_state.pop("dc_live_fetched", None)

    with st.expander("گزارش آخرین Syncها (Sync Log)"):
        log_df = database.list_sync_log(limit=10)
        if log_df.empty:
            st.caption("هنوز هیچ Syncی ثبت نشده.")
        else:
            st.dataframe(
                log_df[["provider", "started_at", "status", "records_received",
                        "records_valid", "records_rejected"]],
                use_container_width=True, hide_index=True,
            )


# ===========================================================================
# دریافت از FIMA — Current Chain + Historical (بخش ۵، ۶ سند)
# ===========================================================================
def _fima_flow():
    c.section(
        "دریافت از FIMA",
        "زنجیره جاری (Current) یک دارایی پایه یا تاریخچه قیمتی یک قرارداد "
        "مشخص، از همان core.data.providers.fima که در سطح Provider تست شده.",
    )
    c.helper(
        "این هم از همان Registry مرکزی Provider (core.data.providers) می‌آید که TSETMC — "
        "هیچ نقطه دیگری در پروژه مستقیماً fima را import نمی‌کند."
    )

    # توجه: Streamlit اجازه تودرتو کردن st.tabs داخل st.tabs را نمی‌دهد
    # (StreamlitAPIException)؛ چون خود این تابع از داخل یک تب دیگر
    # (tab_fima) صدا زده می‌شود، اینجا از st.radio افقی استفاده می‌شود،
    # نه یک ست دوم Tabs.
    sub_choice = st.radio(
        "نوع دریافت از FIMA", ["زنجیره جاری (Current)", "تاریخچه یک قرارداد (Historical)"],
        key="dc_fima_sub", horizontal=True,
    )
    c.spacer(8)
    if sub_choice == "زنجیره جاری (Current)":
        _fima_current_flow()
    else:
        _fima_historical_flow()


def _fima_current_flow():
    underlying = st.text_input(
        "دارایی پایه (نام دقیق فارسی، مثل «اهرم»)", key="dc_fima_cur_ua",
        help="fima برای زنجیره جاری فقط یک دارایی پایه مشخص را می‌پذیرد؛ کل بازار پشتیبانی نمی‌شود.",
    )
    dataset_name = st.text_input(
        "نام مجموعه (Dataset)", key="dc_fima_cur_name",
        placeholder=f"مثلاً: FIMA زنده {JD(str(dt.date.today()))}",
    )

    if st.button("دریافت و ذخیره از FIMA", type="primary", key="dc_fima_cur_btn"):
        if not underlying.strip():
            c.error_state("دارایی پایه لازم است", "نام دقیق دارایی پایه را وارد کنید.")
        elif not dataset_name.strip():
            c.error_state("نام مجموعه لازم است", "یک نام برای مجموعه (Dataset) وارد کنید.")
        else:
            try:
                with st.spinner("در حال دریافت زنجیره جاری از FIMA..."):
                    provider = get_provider("fima")
                    result = run_manual_sync(provider, dataset_name.strip(), underlying=underlying.strip())
            except ProviderError as exc:
                c.error_state("دریافت داده از FIMA ممکن نشد", str(exc))
            else:
                common.clear_caches()
                if result["status"] == "FAILED":
                    c.error_state("دریافت از FIMA ناموفق بود", result.get("error", ""))
                else:
                    snap = result.get("snapshot_report", {})
                    fetch = result.get("fetch_report", {})
                    st.success(
                        f"{snap.get('records_valid', 0):,} ردیف معتبر ذخیره شد "
                        f"({snap.get('records_rejected', 0)} ردیف نامعتبر رد شد) — "
                        f"provider={fetch.get('provider')}, source={fetch.get('source')}. "
                        f"مجموعه: «{dataset_name.strip()}»"
                    )
                    if snap.get("underlying_rows_saved"):
                        st.caption(f"+ {snap['underlying_rows_saved']:,} ردیف قیمت دارایی پایه.")
                    if snap.get("warnings"):
                        with st.expander("جزئیات اعتبارسنجی"):
                            for w in snap["warnings"]:
                                st.write("• " + w)

    with st.expander("گزارش آخرین Syncها از FIMA"):
        log_df = database.list_sync_log(limit=20)
        if log_df.empty:
            st.caption("هنوز هیچ Syncی ثبت نشده.")
        else:
            fima_log = log_df[log_df["provider"] == "FIMA"]
            if fima_log.empty:
                st.caption("هنوز هیچ Syncی از FIMA ثبت نشده.")
            else:
                st.dataframe(
                    fima_log[["provider", "started_at", "status", "records_received",
                              "records_valid", "records_rejected"]],
                    use_container_width=True, hide_index=True,
                )


def _fima_historical_flow():
    c.helper(
        "fima.download_historical_data به یک **نماد قرارداد مشخص** نیاز دارد "
        "(مثل «ضهرم6040»)، نه نام دارایی پایه — این تاریخچه یک قرارداد را می‌دهد، "
        "نه کل زنجیره تاریخی. برای پوشش کامل، این تابع را برای هر قرارداد مدنظر جداگانه اجرا کنید."
    )
    col1, col2, col3 = st.columns([1.6, 1.2, 1.2])
    with col1:
        symbol = st.text_input("نماد قرارداد (مثل «ضهرم6040»)", key="dc_fima_hist_symbol")
    with col2:
        start_date_str = st.text_input(
            "از تاریخ (شمسی)", key="dc_fima_hist_start", placeholder="۱۴۰۵/۰۵/۰۱",
            help="مثل بقیه بخش‌های ATLAS، تاریخ شمسی وارد کنید؛ خالی = بدون محدودیت شروع.",
        )
    with col3:
        end_date_str = st.text_input(
            "تا تاریخ (شمسی)", key="dc_fima_hist_end", placeholder="۱۴۰۵/۰۵/۳۱",
            help="خالی = تا امروز.",
        )

    dataset_name = st.text_input(
        "نام مجموعه (Dataset)", key="dc_fima_hist_name",
        placeholder="مثلاً: FIMA تاریخی شهریور ۱۴۰۵",
    )

    if st.button("دریافت و ذخیره تاریخچه از FIMA", type="primary", key="dc_fima_hist_btn"):
        if not symbol.strip():
            c.error_state("نماد قرارداد لازم است", "نماد دقیق قرارداد اختیار معامله را وارد کنید.")
        elif not dataset_name.strip():
            c.error_state("نام مجموعه لازم است", "یک نام برای مجموعه (Dataset) وارد کنید.")
        else:
            start_date = importer.parse_date_value(start_date_str) if (start_date_str or "").strip() else None
            end_date = importer.parse_date_value(end_date_str) if (end_date_str or "").strip() else None
            if (start_date_str or "").strip() and start_date is None:
                c.error_state("تاریخ شروع نامعتبر است", "فرمت «۱۴۰۵/۰۵/۰۱» را وارد کنید.")
                return
            if (end_date_str or "").strip() and end_date is None:
                c.error_state("تاریخ پایان نامعتبر است", "فرمت «۱۴۰۵/۰۵/۳۱» را وارد کنید.")
                return
            try:
                provider = get_provider("fima")
                with st.spinner("در حال دریافت تاریخچه از FIMA..."):
                    option_df, underlying_df, fetch_report = provider.get_historical(
                        symbol.strip(), start_date, end_date,
                    )
            except ProviderError as exc:
                c.error_state("دریافت تاریخچه از FIMA ممکن نشد", str(exc))
            else:
                if option_df.empty:
                    c.error_state(
                        "هیچ رکورد تاریخی معتبری یافت نشد",
                        "بازه تاریخ را بررسی کنید (رکوردهای قبل از ۱۴۰۵/۰۱/۰۱ به‌طور عمدی فیلتر می‌شوند).",
                    )
                else:
                    st.session_state["dc_fima_hist_fetched"] = {
                        "option_df": option_df, "underlying_df": underlying_df,
                        "report": fetch_report,
                    }

    fetched = st.session_state.get("dc_fima_hist_fetched")
    if not fetched:
        return

    option_df, underlying_df = fetched["option_df"], fetched["underlying_df"]
    report = fetched["report"]

    c.spacer(16)
    c.kpi_strip([
        {"label": "ردیف قیمت قرارداد", "value": c.fmt_int(len(option_df)), "na": False},
        {"label": "ردیف قیمت دارایی پایه", "value": c.fmt_int(len(underlying_df)), "na": False},
        {"label": "provider", "value": report.get("provider", "—"), "na": False},
        {"label": "source", "value": report.get("source", "—"), "na": False},
    ])
    if report.get("note"):
        c.helper(report["note"])

    with st.expander(f"پیش‌نمایش {min(len(option_df), 20)} ردیف اول"):
        st.dataframe(_jalali_date_cols(option_df.head(20), ["quote_date", "expiry"]),
                     use_container_width=True, hide_index=True)

    c.spacer(16)
    if dataset_name.strip() and st.button("تأیید و ذخیره به‌عنوان مجموعه", type="primary", key="dc_fima_hist_save"):
        result = save_previewed_snapshot(
            get_provider("fima").name, option_df, underlying_df, dataset_name.strip(),
        )
        common.clear_caches()
        snap = result.get("snapshot_report", {})
        if result["status"] == "FAILED":
            c.error_state("ذخیره ناموفق بود", result.get("error", ""))
        else:
            msg = (f"{snap.get('records_valid', 0):,} ردیف معتبر ذخیره شد "
                   f"({snap.get('records_rejected', 0)} ردیف نامعتبر رد شد). "
                   f"مجموعه: «{dataset_name.strip()}»")
            if snap.get("underlying_rows_saved"):
                msg += f" + {snap['underlying_rows_saved']:,} ردیف قیمت دارایی پایه."
            st.success(msg)
            st.session_state.pop("dc_fima_hist_fetched", None)


# ===========================================================================
# ۱–۴: جریان ورود داده (مسیر دستی/اضطراری — دیگر مسیر پیش‌فرض نیست)
# ===========================================================================
def _import_flow():
    st.warning(
        "این مسیر **دیگر منبع اصلی داده ATLAS نیست**. منبع پیش‌فرض حالا تب "
        "«دریافت بازار (TSETMC)» است. این تب فقط برای مواردی نگه داشته شده "
        "که TSETMC/fima در دسترس نیستند یا داده‌ای خارج از پوشش آن‌ها دارید.",
        icon="⚠️",
    )
    c.section("۱. بارگذاری", "فایل اکسل بازار را انتخاب کنید")

    g1, g2 = st.columns([1.6, 1.4])
    with g1:
        kind = st.radio(
            "نوع فایل",
            [KIND_OPTIONS, KIND_SCREENER, KIND_UNDERLYING],
            key="dc_kind",
            captions=[
                "فایل اختیار معامله شما — اگر ستون «آخرین پایه» داشته باشد، قیمت دارایی پایه هم خودکار خوانده می‌شود.",
                "خروجی خام سایت‌های آپشن‌گر (نماد با پیشوند ض/ط).",
                "فقط جدول قیمت سهم — وقتی قیمت پایه در فایل اختیار نیست.",
            ],
        )
    with g2:
        dataset_name = st.text_input("نام مجموعه (Dataset)", key="dc_name",
                                     placeholder="مثلاً: شهریور ۱۴۰۵")
        quote_date_str = None
        if kind == KIND_SCREENER:
            quote_date_str = st.text_input(
                "تاریخ این Snapshot", key="dc_qdate", placeholder="۱۴۰۵/۰۶/۰۵",
                help="این فرمت تاریخ را داخل خودش ندارد چون خروجی لحظه‌ای است.",
            )

    uploaded = st.file_uploader("فایل اکسل", type=["xlsx", "xls"], key="dc_file")

    if uploaded is None:
        c.spacer(16)
        c.empty_state("منتظر فایل",
                      "یک فایل اکسل انتخاب کنید تا ستون‌هایش تشخیص داده شود و پیش از ثبت، آن را بررسی کنید.")
        return
    if not dataset_name.strip():
        c.spacer(16)
        c.empty_state("نام مجموعه لازم است",
                      "برای افزودن Snapshot جدید به داده‌های قبلی، همان نام مجموعه قبلی را وارد کنید.")
        return
    if kind == KIND_SCREENER and not (quote_date_str or "").strip():
        c.spacer(16)
        c.empty_state("تاریخ Snapshot لازم است",
                      "این فرمت تاریخ ندارد؛ تاریخ روزی که خروجی گرفته شده را وارد کنید.")
        return

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(uploaded.getvalue())
        tmp_path = tmp.name

    try:
        _detect_review_import(tmp_path, kind, dataset_name.strip(), quote_date_str)
    except Exception as exc:  # خطای خواندن فایل نباید صفحه را بشکند (بخش ۷۰)
        c.spacer(16)
        c.error_state(
            "خواندن فایل ممکن نشد",
            f"{type(exc).__name__}: {exc}. مطمئن شوید فایل یک اکسل سالم است و "
            "سطر اول آن عنوان ستون‌هاست (نه سطر توضیحی).",
        )
    finally:
        os.unlink(tmp_path)


def _detect_review_import(path: str, kind: str, dataset_name: str, quote_date_str):
    # ---------------- ۲. تشخیص ----------------
    c.spacer(20)
    c.section("۲. تشخیص", "ستون‌های فایل شما به فیلدهای Atlas نگاشت می‌شوند")

    underlying_df = None
    if kind == KIND_SCREENER:
        clean_df, underlying_df, report = importer.import_tse_screener_excel(path, quote_date_str)
    elif kind == KIND_OPTIONS:
        clean_df, report, underlying_df = importer.import_excel(path)
    else:
        clean_df, report = importer.import_underlying_excel(path)

    mapping = report.get("detected_mapping") or {}
    if mapping:
        headers = ["فیلد Atlas", "ستون فایل شما"]
        labels = {
            "quote_date": "تاریخ", "symbol": "نماد قرارداد", "underlying": "نماد پایه",
            "option_type": "نوع (Call/Put)", "strike": "قیمت اعمال", "expiry": "سررسید",
            "close": "قیمت پایانی", "bid": "بهترین تقاضا", "ask": "بهترین عرضه",
            "volume": "حجم", "open_interest": "موقعیت باز", "iv": "نوسان ضمنی",
            "underlying_close": "قیمت دارایی پایه",
        }
        rows = [[c.esc(labels.get(k, k)), c.num(v)] for k, v in mapping.items()]
        c.table(headers, rows)
    elif kind == KIND_SCREENER:
        c.helper("این فرمت نگاشت ثابت دارد و ستون‌هایش مستقیماً شناخته می‌شوند.")

    missing = report.get("missing_required_fields") or []
    if missing:
        c.spacer(16)
        c.error_state("ستون‌های ضروری پیدا نشد", "این فیلدها در فایل نبودند: " + "، ".join(missing))
        return
    if clean_df is None or clean_df.empty:
        c.spacer(16)
        c.error_state("هیچ ردیف معتبری در فایل نبود",
                      "همه ردیف‌ها در اعتبارسنجی حذف شدند. هشدارهای زیر را ببینید.")
        for w in report.get("warnings", []):
            c.helper("• " + w)
        return

    # ---------------- ۳. بررسی ----------------
    c.spacer(24)
    c.section("۳. بررسی", "پیش از ثبت، نتیجه اعتبارسنجی را ببینید")

    n_spot = report.get("underlying_prices_found")
    c.kpi_strip([
        {"label": "ردیف‌های فایل", "value": c.fmt_int(report["total_rows"]), "na": False},
        {"label": "ردیف معتبر", "value": c.fmt_int(report.get("kept_rows", 0)), "na": False},
        {"label": "ردیف حذف‌شده", "value": c.fmt_int(report.get("dropped_rows", 0)), "na": False},
        {"label": "Call", "value": c.fmt_int(report.get("call_count")) if "call_count" in report else "—",
         "na": "call_count" not in report},
        {"label": "Put", "value": c.fmt_int(report.get("put_count")) if "put_count" in report else "—",
         "na": "put_count" not in report},
        {"label": "قیمت دارایی پایه",
         "value": f"{n_spot} نماد" if n_spot else ("جداگانه" if kind == KIND_UNDERLYING else "یافت نشد"),
         "na": not n_spot},
    ])

    warnings = report.get("warnings", [])
    if warnings:
        st.markdown(
            '<div class="chips">' + "".join(
                f'<span class="chip warn">{c.esc(w)}</span>' for w in warnings
            ) + "</div>",
            unsafe_allow_html=True,
        )
        c.spacer(12)

    if underlying_df is not None and not underlying_df.empty:
        c.helper("قیمت دارایی پایه از همین فایل استخراج شد — نیازی به فایل جداگانه نیست.")
        rows = [[c.esc(r["underlying"]), c.num(JD(r["quote_date"])), c.num(c.fmt_int(r["close"]))]
                for _, r in underlying_df.head(10).iterrows()]
        c.table(["نماد پایه", "تاریخ", "قیمت پایانی"], rows, numeric_cols={1, 2})
        if len(underlying_df) > 10:
            c.helper(f"{len(underlying_df) - 10} ردیف دیگر نمایش داده نشده.")
        c.spacer(16)

    with st.expander(f"پیش‌نمایش {min(len(clean_df), 20)} ردیف اول"):
        st.dataframe(_jalali_date_cols(clean_df.head(20), ["quote_date", "expiry"]),
                     use_container_width=True, hide_index=True)

    # هشدار داده تکراری — پیش از ثبت، نه بعدش
    dup_dates = _existing_dates(dataset_name, clean_df)
    if dup_dates:
        c.spacer(12)
        st.markdown(
            f'<div class="chips"><span class="chip warn">'
            f'برای {"، ".join(JD(d) for d in dup_dates[:3])}'
            f'{" و چند تاریخ دیگر" if len(dup_dates) > 3 else ""} '
            f'از قبل در این مجموعه داده وجود دارد — ثبت دوباره ردیف تکراری می‌سازد.'
            f"</span></div>",
            unsafe_allow_html=True,
        )

    # ---------------- ۴. ثبت ----------------
    c.spacer(24)
    c.section("۴. ثبت")
    if not st.button("تأیید و ذخیره", type="primary", key="dc_save"):
        return

    if kind == KIND_UNDERLYING:
        n = database.save_underlying_dataframe(clean_df, dataset_name, replace_existing=False)
        msg = f"{n:,} ردیف قیمت دارایی پایه ذخیره شد."
    else:
        n1 = database.save_dataframe(clean_df, dataset_name, replace_existing=False)
        msg = f"{n1:,} ردیف اختیار معامله ذخیره شد."
        if underlying_df is not None and not underlying_df.empty:
            n2 = database.save_underlying_dataframe(underlying_df, dataset_name, replace_existing=False)
            msg += f" همراه با {n2:,} ردیف قیمت دارایی پایه."

    common.clear_caches()  # وگرنه صفحات دیگر داده قدیمی Cache‌شده را نشان می‌دهند
    st.success(msg + f" مجموعه: «{dataset_name}»")


def _existing_dates(dataset_name: str, clean_df: pd.DataFrame) -> list:
    """تاریخ‌هایی از این فایل که از قبل در همین مجموعه ثبت شده‌اند."""
    if "quote_date" not in clean_df.columns:
        return []
    existing = database.load_data(dataset_name=dataset_name)
    if existing.empty:
        return []
    have = set(existing["quote_date"].dropna().unique())
    return sorted(set(clean_df["quote_date"].dropna().unique()) & have)


# ===========================================================================
def _datasets(datasets: pd.DataFrame):
    if datasets.empty:
        c.empty_state("هنوز مجموعه‌ای وارد نشده", "از تب «ورود داده» اولین فایل را اضافه کنید.")
        return

    c.section("مجموعه‌ها", f"{len(datasets)} مجموعه ثبت‌شده")
    headers = ["مجموعه", "ردیف‌ها", "نمادهای پایه", "از تاریخ", "تا تاریخ"]
    rows = [[
        c.esc(r["dataset"]),
        c.num(c.fmt_int(r["rows"])),
        c.num(c.fmt_int(r["underlyings"])),
        c.num(JD(r["from_date"])),
        c.num(JD(r["to_date"])),
    ] for _, r in datasets.iterrows()]
    c.table(headers, rows, numeric_cols={1, 2, 3, 4})

    c.spacer(24)
    c.section("حذف مجموعه", "این کار برگشت‌پذیر نیست")
    d1, d2 = st.columns([2, 1])
    target = d1.selectbox("مجموعه", ["—"] + datasets["dataset"].tolist(), key="dc_del")
    if target != "—":
        confirm = d1.checkbox(f"می‌دانم که همه داده‌های «{target}» پاک می‌شود", key="dc_del_ok")
        if d2.button("حذف", type="secondary", use_container_width=True,
                     disabled=not confirm, key="dc_del_btn"):
            database.delete_dataset(target)
            common.clear_caches()
            st.success(f"مجموعه «{target}» حذف شد.")
            st.rerun()


def _quality(datasets: pd.DataFrame):
    if datasets.empty:
        c.empty_state("داده‌ای برای بررسی نیست", "ابتدا یک فایل وارد کنید.")
        return

    dataset_name = st.selectbox("مجموعه", datasets["dataset"].tolist(), key="dc_q_dataset")
    options_df = database.load_data(dataset_name=dataset_name)
    if options_df.empty:
        c.empty_state("این مجموعه رکوردی ندارد", "مجموعه دیگری انتخاب کنید.")
        return

    rep = analytics.data_quality_report(options_df)
    c.kpi_strip([
        {"label": "ردیف‌ها", "value": c.fmt_int(rep["rows"]), "na": False},
        {"label": "نمادهای پایه", "value": c.fmt_int(rep["underlyings"]), "na": False},
        {"label": "قراردادها", "value": c.fmt_int(rep["contracts"]), "na": rep["contracts"] is None},
        {"label": "Snapshotها", "value": c.fmt_int(rep["snapshots"]), "na": False},
        {"label": "Call", "value": c.fmt_int(rep["calls"]), "na": False},
        {"label": "Put", "value": c.fmt_int(rep["puts"]), "na": False},
    ])

    # هشدار مهم: بک‌تست بدون Snapshot کافی بی‌معناست
    if rep["snapshots"] < 5:
        st.markdown(
            f'<div class="chips"><span class="chip warn">فقط {rep["snapshots"]} Snapshot موجود است — '
            f'برای HV، سیگنال‌های تغییر و بک‌تست معنادار، داده روزهای بیشتری لازم است.</span></div>',
            unsafe_allow_html=True)
        c.spacer(12)

    # قیمت دارایی پایه: بدون آن نیمی از محصول کار نمی‌کند
    und = database.load_underlying_data(dataset_name=dataset_name)
    covered = set(zip(und["underlying"], und["quote_date"])) if not und.empty else set()
    needed = set(zip(options_df["underlying"], options_df["quote_date"]))
    missing = len(needed - covered)
    tone = "warn" if missing else ""
    st.markdown(
        f'<div class="chips"><span class="chip {tone}">قیمت دارایی پایه: '
        f'{len(needed) - missing} از {len(needed)} جفت (نماد، تاریخ) پوشش داده شده'
        + (f" — {missing} جفت بدون قیمت پایه، Greeks و ITM/ATM/OTM آن‌ها محاسبه نمی‌شود."
           if missing else "") + "</span></div>",
        unsafe_allow_html=True)

    c.spacer(20)
    c.section("تکمیل بودن فیلدها", "چند درصد ردیف‌ها این فیلد را واقعاً دارند")
    labels = {"iv": "نوسان ضمنی", "open_interest": "موقعیت باز", "volume": "حجم",
              "bid": "بهترین تقاضا", "ask": "بهترین عرضه", "close": "قیمت پایانی"}
    rows = []
    for field, pct in rep["completeness_pct"].items():
        tone = "pos" if pct >= 90 else ("neg" if pct < 50 else "")
        bar = (f'<div style="background:var(--bg-elevated);border-radius:3px;height:6px;width:120px">'
               f'<div style="width:{max(pct, 0):.0f}%;height:6px;border-radius:3px;'
               f'background:var({"--pos" if pct >= 90 else "--neg" if pct < 50 else "--warn"})"></div></div>')
        rows.append([
            c.esc(labels.get(field, field)),
            f'<span class="num {tone}">{pct:.1f}%</span>',
            c.num(c.fmt_int(rep["missing"][field])),
            bar,
        ])
    c.table(["فیلد", "تکمیل‌شده", "مقادیر خالی", ""], rows, numeric_cols={1, 2})
