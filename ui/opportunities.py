"""
Opportunities — رتبه‌بندی Atlas (بخش ۳۲ تا ۳۷ و ۸۰ Master Prompt).

پرسش اصلی صفحه: «Atlas چه موقعیت‌هایی را ارزشمند می‌داند؟»

تفاوت با Scanner: اینجا Atlas تحلیل و رتبه‌بندی می‌کند؛ آنجا کاربر شرط می‌گذارد.

دو حالت (بخش ۳۳):
    A) فرصت‌های قرارداد   — کدام قرارداد به‌خودی‌خود جالب است؟
    B) فرصت‌های استراتژی  — امروز این استراتژی کجای بازار جذاب است؟

امتیاز Contract و امتیاز Strategy عمداً دو مفهوم جدا هستند (بخش ۳۶) و هر دو
از منطق واقعی core/opportunity.py می‌آیند — هیچ وزن یا فرمولی در UI ساخته نمی‌شود.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import database, opportunity, strategy as strat_engine
from ui import common, contract_detail
from ui import components as c
from ui.common import JD

TOP_LIMIT = 50


@st.cache_data(show_spinner=False, ttl=900)
def _contract_opps(chain: pd.DataFrame, underlying_hist: pd.DataFrame,
                    option_hist: pd.DataFrame, weights: dict) -> pd.DataFrame:
    return opportunity.detect_contract_opportunities(chain, underlying_hist, option_hist, weights)


@st.cache_data(show_spinner="در حال اسکن استراتژی روی بازار…", ttl=900)
def _strategy_opps(chain: pd.DataFrame, underlying_hist: pd.DataFrame,
                    r: float, weights: dict, strategies: tuple) -> pd.DataFrame:
    return opportunity.scan_strategy_universe(chain, r, weights,
                                              strategies=list(strategies) or None,
                                              underlying_hist_df=underlying_hist)


def render():
    datasets = database.list_datasets()
    if datasets.empty:
        c.page_header("فرصت‌ها", "رتبه‌بندی Atlas از موقعیت‌های قابل‌بررسی",
                      status="err", status_text="داده‌ای موجود نیست")
        c.empty_state("هنوز داده‌ای وارد نشده", "از «مرکز داده» یک فایل اختیار معامله وارد کنید.")
        return

    intent = common.take_intent("dataset") or {}
    if intent.get("dataset"):
        st.session_state["opp_dataset"] = intent["dataset"]
    if intent.get("strategy"):
        st.session_state["opp_strategy_filter"] = [intent["strategy"]]

    f1, f2, _ = st.columns([1.4, 1.4, 3])
    with f1:
        dataset_name = st.selectbox("Dataset", datasets["dataset"].tolist(), key="opp_dataset")
    options_all, underlying_all = common.load_dataset(dataset_name)
    if options_all.empty:
        c.page_header("فرصت‌ها", "رتبه‌بندی Atlas از موقعیت‌های قابل‌بررسی")
        c.empty_state("این Dataset رکوردی ندارد", "Dataset دیگری انتخاب کنید.")
        return
    with f2:
        quote_date, _p, quote_dates = common.snapshot_picker(options_all, key="opp_qdate")
    if quote_date is None:
        c.empty_state("Snapshot معتبری یافت نشد", "تاریخ رکوردهای این Dataset نامعتبر است.")
        return

    is_latest = quote_date == max(quote_dates)
    c.page_header(
        "فرصت‌ها",
        "آنچه Atlas پس از تحلیل داده امروز ارزش بررسی می‌داند",
        snapshot_label=JD(quote_date),
        status="ok" if is_latest else "warn",
        status_text="داده به‌روز است" if is_latest else "Snapshot تاریخی",
    )

    chain = common.enrich_snapshot(options_all, underlying_all, quote_date,
                                   st.session_state.risk_free_rate,
                                   st.session_state.atm_band_pct)
    if chain.empty:
        c.empty_state("این Snapshot قراردادی ندارد", "تاریخ دیگری انتخاب کنید.")
        return

    tab_contract, tab_strategy = st.tabs(["فرصت‌های قرارداد", "فرصت‌های استراتژی"])
    with tab_contract:
        _contract_mode(chain, dataset_name, quote_date)
    with tab_strategy:
        _strategy_mode(chain, dataset_name, quote_date)

    # وزن‌ها — ثانویه، انتهای صفحه تا کنترل تحلیلی صفحه را اشغال نکند
    c.spacer(24)
    with st.expander("تنظیم وزن‌های امتیازدهی (Contract / Strategy جدا)"):
        c.helper("این وزن‌ها فقط روی مؤلفه‌هایی اعمال می‌شوند که برای هر فرصت واقعاً "
                 "قابل‌محاسبه‌اند؛ مؤلفه‌های بدون داده از فرمول حذف و وزن‌های باقی‌مانده بازتوزیع می‌شوند.")
        st.markdown("**Contract**")
        wc = st.session_state.opportunity_weights_contract
        cols_c = st.columns(3)
        for i, k in enumerate(wc.keys()):
            wc[k] = cols_c[i % 3].slider(k, 0.0, 1.0, wc[k], 0.05, key=f"opp_wc_{k}")
        st.markdown("**Strategy**")
        ws = st.session_state.opportunity_weights_strategy
        cols_s = st.columns(3)
        for i, k in enumerate(ws.keys()):
            ws[k] = cols_s[i % 3].slider(k, 0.0, 1.0, ws[k], 0.05, key=f"opp_ws_{k}")


# ===========================================================================
# A) فرصت‌های قرارداد (بخش ۳۴)
# ===========================================================================
def _contract_mode(chain: pd.DataFrame, dataset_name: str, quote_date: str):
    options_all, underlying_all = common.load_dataset(dataset_name)
    opps = _contract_opps(chain, underlying_all, options_all, st.session_state.opportunity_weights_contract)
    if opps.empty:
        c.empty_state(
            "فرصتی شناسایی نشد",
            "موتور فرصت‌ها برای مقایسه نسبی به حداقل ۳ قرارداد هم‌گروه (همان نماد، سررسید و نوع) نیاز دارد. "
            "با داده فعلی هیچ گروهی این شرط را برآورده نکرد.",
        )
        return

    all_cats = sorted({cat for cats in opps["categories"] for cat in cats})
    g1, g2, _ = st.columns([2, 1.2, 2])
    with g1:
        chosen = st.multiselect("فیلتر سیگنال", all_cats, key="opp_cat_filter")
    with g2:
        moneyness = st.selectbox("وضعیت", ["همه", "ITM", "ATM", "OTM"], key="opp_moneyness")

    view = opps
    if chosen:
        view = view[view["categories"].apply(lambda cats: any(x in chosen for x in cats))]
    if moneyness != "همه":
        allowed = set(chain.loc[chain["moneyness_bucket"] == moneyness, "symbol"].dropna())
        view = view[view["symbol"].isin(allowed)]

    c.spacer(10)
    c.section("رتبه‌بندی", f"{len(view):,} فرصت — مرتب بر اساس امتیاز قرارداد")
    if view.empty:
        c.empty_state("با این فیلترها فرصتی نماند", "فیلتر سیگنال یا وضعیت را بردارید.")
        return

    top = view.head(TOP_LIMIT)
    headers = ["#", "قرارداد", "نماد پایه", "نوع", "وضعیت", "سیگنال",
               "IV", "حجم", "موقعیت باز", "امتیاز", "Grade", "Coverage"]
    m_map = dict(zip(chain["symbol"], chain["moneyness_bucket"])) if "symbol" in chain.columns else {}
    rows = []
    for i, o in top.iterrows():
        rows.append([
            f'<span class="rank">{i + 1}</span>',
            c.num(o.get("symbol") or c.NA),
            c.esc(o.get("underlying")),
            c.type_label(o.get("option_type")),
            c.moneyness_badge(m_map.get(o.get("symbol"))),
            " ".join(c.signal_badge(x) for x in (o["categories"] or [])[:3]) or c.NA,
            c.num(c.fmt_pct(o.get("iv"))),
            c.num(c.fmt_compact(o.get("volume"))),
            c.num(c.fmt_compact(o.get("open_interest"))),
            _score_cell(o.get("score")),
            c.esc(o.get("grade") or c.NA),
            _coverage_cell(o.get("coverage"), o.get("confidence")),
        ])
    c.table(headers, rows, numeric_cols={0, 6, 7, 8, 9})
    if opps.attrs.get("ineligible_count"):
        c.helper(f"{opps.attrs['ineligible_count']:,} قرارداد به‌دلیل داده غیرقابل‌استفاده "
                 "(بدون Volume/OI، Quote نامعتبر یا اسپرد بیش‌ازحد) از این لیست کنار گذاشته شد.")
    if len(view) > TOP_LIMIT:
        c.helper(f"{TOP_LIMIT} فرصت برتر نمایش داده شده از مجموع {len(view):,} مورد.")

    # --- توضیح‌پذیری + جزئیات (بخش ۳۷) ---
    c.spacer(28)
    c.section("چرا این فرصت؟", "امتیاز جعبه سیاه نیست — دلایل از داده واقعی همین Snapshot می‌آیند")

    symbols = top["symbol"].dropna().tolist()
    if not symbols:
        return
    if st.session_state.get("opp_detail_symbol") not in symbols:
        st.session_state["opp_detail_symbol"] = symbols[0]
    sel = st.selectbox("فرصت", symbols, key="opp_detail_symbol")
    o = top[top["symbol"] == sel].iloc[0]

    _why_panel(o.get("score"), o.get("why"), o.get("risks"),
               coverage=o.get("coverage"), confidence=o.get("confidence"),
               grade=o.get("grade"), subscores=o.get("subscores"))

    match = chain[chain["symbol"] == sel]
    if not match.empty:
        c.spacer(16)
        contract_detail.render(
            match.iloc[0],
            context={"dataset": dataset_name, "underlying": o["underlying"],
                     "quote_date": quote_date, "expiry": o["expiry"]},
            on_add_to_strategy=_add_contract_to_strategy,
            on_view_chain=_view_chain,
            key_prefix="opp",
        )


# ===========================================================================
# B) فرصت‌های استراتژی (بخش ۳۵)
# ===========================================================================
def _strategy_mode(chain: pd.DataFrame, dataset_name: str, quote_date: str):
    coverage = opportunity.universe_coverage(chain)
    if coverage["scanned_pairs"] == 0:
        c.empty_state(
            "اسکن استراتژی ممکن نیست",
            "برای ساخت و ارزیابی استراتژی، قیمت دارایی پایه لازم است و برای هیچ‌کدام از "
            f"{coverage['total_pairs']} جفت (نماد، سررسید) این Snapshot وارد نشده. "
            "فایل «قیمت دارایی پایه» را در مرکز داده اضافه کنید.",
        )
        return

    available = list(strat_engine.STRATEGY_TEMPLATES.keys())
    g1, _ = st.columns([3, 2])
    with g1:
        chosen = st.multiselect(
            "استراتژی", available, key="opp_strategy_filter",
            help="فقط قالب‌هایی فهرست شده‌اند که موتور استراتژی واقعاً پشتیبانی می‌کند.",
        )

    c.helper(
        f"اسکن روی {coverage['scanned_pairs']} جفت (نماد، سررسید) از {coverage['total_pairs']} جفت این Snapshot انجام می‌شود."
        + (f" {coverage['skipped_no_spot']} جفت به‌دلیل نبود قیمت دارایی پایه کنار گذاشته شد."
           if coverage["skipped_no_spot"] else "")
    )
    c.spacer(14)

    options_all, underlying_all = common.load_dataset(dataset_name)
    res = _strategy_opps(chain, underlying_all, st.session_state.risk_free_rate,
                         st.session_state.opportunity_weights_strategy, tuple(chosen))
    if res.empty:
        c.empty_state(
            "هیچ موقعیت استراتژی قابل‌ساختی پیدا نشد",
            "برای هر قالب، وجود همزمان Call/Put کافی در همان سررسید لازم است. "
            "اگر فایل شما فقط Call یا فقط Put دارد، سمت دیگر را هم وارد کنید.",
        )
        return

    c.section("رتبه‌بندی استراتژی", f"{len(res):,} موقعیت — مرتب بر اساس امتیاز استراتژی")
    top = res.head(TOP_LIMIT)
    headers = ["#", "استراتژی", "نماد پایه", "سررسید", "دریافتی/پرداختی",
               "حداکثر سود", "حداکثر زیان", "POP", "ارزش موردانتظار", "امتیاز", "Coverage"]
    rows = []
    for i, o in top.iterrows():
        rows.append([
            f'<span class="rank">{i + 1}</span>',
            c.esc(_short_strategy(o["strategy"])),
            c.esc(o["underlying"]),
            c.num(JD(o["expiry"])),
            _signed_cell(o.get("credit_debit")),
            _bound_cell(o.get("max_profit")),
            _bound_cell(o.get("max_loss")),
            c.num(f"{o['pop']:.0f}%" if o.get("pop") is not None and pd.notna(o.get("pop")) else c.NA),
            _signed_cell(o.get("expected_value")),
            _score_cell(o.get("score")),
            _coverage_cell(o.get("coverage"), o.get("confidence")),
        ])
    c.table(headers, rows, numeric_cols={0, 3, 4, 5, 6, 7, 8, 9, 10})

    c.spacer(28)
    c.section("چرا این موقعیت؟", "ترکیب پایه‌ها و دلایل امتیاز")
    labels = [f"{i + 1}. {_short_strategy(o['strategy'])} — {o['underlying']}"
              for i, o in top.iterrows()]
    pick = st.selectbox("موقعیت", range(len(top)), format_func=lambda i: labels[i],
                        key="opp_strat_pick")
    o = top.iloc[pick]

    _legs_table(o["legs"])
    _why_panel(o.get("score"), o.get("why"), o.get("risks"),
               coverage=o.get("coverage"), confidence=o.get("confidence"),
               grade=o.get("grade"), subscores=o.get("subscores"))

    if st.button("باز کردن در استراتژی لب", type="primary", key="opp_open_strategy"):
        st.session_state.pending_strategy_legs = {
            "dataset": dataset_name, "underlying": o["underlying"],
            "quote_date": quote_date, "expiry": o["expiry"],
            "template": o["strategy"],
            "legs": [
                {"option_type": leg.option_type, "side": leg.side, "strike": leg.strike,
                 "close": leg.premium, "qty": leg.qty, "contract_size": leg.contract_size}
                for leg in o["legs"]
            ],
        }
        st.session_state.strategy_lab_hint = (
            f"«{o['strategy']}» با هر {len(o['legs'])} پایه دقیقاً همان قراردادها منتقل شد."
        )
        common.go_to("Strategy Lab")


# ===========================================================================
# کمکی‌ها
# ===========================================================================
def _short_strategy(name: str) -> str:
    """نام قالب‌ها پرانتز توضیحی طولانی دارد؛ برای جدول کوتاهش می‌کنیم."""
    return name.split(" (")[0].strip()


def _score_cell(score) -> str:
    if score is None or pd.isna(score):
        return f'<span class="muted">{c.NA}</span>'
    return (f'<span class="num" style="color:var(--accent);font-weight:600">'
            f'{float(score):.0f}</span>')


def _coverage_cell(coverage, confidence) -> str:
    if coverage is None or pd.isna(coverage):
        return f'<span class="muted">{c.NA}</span>'
    color_cls = {"High": "pos", "Moderate": "num", "Low": "warn", "Very Low": "neg"}.get(confidence, "muted")
    return f'<span class="num {color_cls}">{coverage:.0f}% ({c.esc(confidence or "")})</span>'


def _signed_cell(v) -> str:
    if v is None or pd.isna(v):
        return f'<span class="muted">{c.NA}</span>'
    v = float(v)
    cls = "pos" if v > 0 else ("neg" if v < 0 else "muted")
    return f'<span class="num {cls}">{v:+,.0f}</span>'


def _bound_cell(v) -> str:
    """max_profit/max_loss ممکن است رشته «نامحدود» باشد."""
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return f'<span class="muted">{c.NA}</span>'
    if isinstance(v, str):
        return f'<span class="warn" style="color:var(--warn)">{c.esc(v)}</span>'
    return _signed_cell(v)


def _why_panel(score, why, risks, coverage=None, confidence=None, grade=None, subscores=None):
    score_html = (f'<div style="font-size:1.5rem;font-weight:600;color:var(--accent);'
                  f'font-family:var(--font-num)">{float(score):.0f}'
                  f'<span style="font-size:.8rem;color:var(--text-3)"> / 100</span></div>'
                  if score is not None and not pd.isna(score)
                  else '<div class="muted">امتیاز قابل‌محاسبه نبود</div>')

    meta_bits = []
    if grade:
        meta_bits.append(f'Grade: <b>{c.esc(grade)}</b>')
    if coverage is not None and pd.notna(coverage):
        meta_bits.append(f'Coverage: <b>{coverage:.0f}%</b>')
    if confidence:
        meta_bits.append(f'Confidence: <b>{c.esc(confidence)}</b>')
    meta_html = (f'<div style="font-size:.78rem;color:var(--text-3);margin-top:4px">'
                 f'{" · ".join(meta_bits)}</div>' if meta_bits else "")

    sub_html = ""
    if subscores:
        chips = "".join(
            f'<span style="display:inline-block;margin:2px 6px 2px 0;padding:2px 8px;'
            f'border-radius:6px;background:var(--panel-2);font-size:.75rem">'
            f'{c.esc(k)}: {("—" if v is None else f"{v:.0f}")}</span>'
            for k, v in subscores.items()
        )
        sub_html = f'<div style="margin-top:8px">{chips}</div>'

    def lines(items, fallback):
        if not items:
            return f'<div class="helper">{fallback}</div>'
        return "".join(f'<div style="font-size:.82rem;line-height:2;color:var(--text-1)">'
                       f"{c.esc(x)}</div>" for x in items)

    st.markdown(
        f'<div class="brief">'
        f'<div style="display:flex;gap:28px;align-items:flex-start">'
        f'<div style="min-width:110px"><div class="kpi-label">امتیاز</div>{score_html}{meta_html}</div>'
        f'<div style="flex:1"><div class="kpi-label">دلایل</div>{lines(why, "دلیل ثبت‌شده‌ای وجود ندارد.")}</div>'
        f'<div style="flex:1"><div class="kpi-label">ریسک‌ها</div>{lines(risks, "ریسک قابل‌تشخیصی ثبت نشد.")}</div>'
        f"</div>{sub_html}</div>",
        unsafe_allow_html=True,
    )


def _legs_table(legs):
    if not legs:
        return
    headers = ["پایه", "نوع", "موقعیت", "قیمت اعمال", "قیمت", "تعداد"]
    rows = []
    for i, leg in enumerate(legs):
        side = "خرید" if leg.side == "buy" else "فروش"
        cls = "pos" if leg.side == "buy" else "neg"
        rows.append([
            f'<span class="rank">{i + 1}</span>',
            c.type_label(leg.option_type),
            f'<span class="{cls}">{side}</span>',
            c.num(c.fmt_int(leg.strike)),
            c.num(c.fmt_int(leg.premium)),
            c.num(str(leg.qty)),
        ])
    c.table(headers, rows, numeric_cols={0, 3, 4, 5})
    c.spacer(14)


def _add_contract_to_strategy(row, ctx):
    st.session_state.pending_strategy_legs = {
        "dataset": ctx.get("dataset"), "underlying": ctx.get("underlying"),
        "quote_date": ctx.get("quote_date"), "expiry": ctx.get("expiry"),
        "leg": {"option_type": row["option_type"], "strike": float(row["strike"]),
                "close": float(row["close"]) if pd.notna(row.get("close")) else 0.0,
                "symbol": row.get("symbol")},
    }
    common.go_to("Strategy Lab")


def _view_chain(row, ctx):
    common.go_to("Option Chain", dataset=ctx.get("dataset"), underlying=row["underlying"],
                 quote_date=ctx.get("quote_date"), expiry=row.get("expiry"),
                 symbol=row.get("symbol"))
