"""
موتور Opportunity - قلب هوشمند ATLAS.

نسخه ۲ (بازطراحی Contract Engine طبق Master Prompt جدید):
- risk_reward / probability / momentum از سطح Contract کاملاً حذف شدند
  (مفاهیم سطح-استراتژی یا نیازمند داده‌ای که Contract به‌تنهایی ندارد).
- Contract Score حالا روی ۶ بُعد واقعی بنا شده: Liquidity & Execution،
  IV/Volatility Value، Relative IV Value، OI/Participation Quality،
  Premium Efficiency، Breakeven/Moneyness Quality (core/opportunity_config.py).
- Eligibility Gate: قراردادهای با داده غیرقابل‌استفاده (نه فقط ناقص) اصلاً
  امتیازدهی نمی‌شوند تا امتیاز گمراه‌کننده تولید نشود.
- Coverage/Confidence به‌صورت صریح برمی‌گردد؛ هیچ داده غایبی صفر نمی‌شود.
- Strategy Opportunities (سطح ۲) فعلاً با منطق قبلی دست‌نخورده مانده؛
  بازطراحی آن مطابق بخش ۱۵-۲۰ Master Prompt، فاز بعدی است.
"""
import numpy as np
import pandas as pd

from core import strategy as strat_engine
from core import analytics
from core.opportunity_config import (
    CONTRACT_WEIGHTS, LIQUIDITY_SUBWEIGHTS, IV_VALUE_SUBWEIGHTS,
    OI_PARTICIPATION_SUBWEIGHTS, MIN_PEERS_FOR_RELATIVE_IV,
    MAX_REASONABLE_SPREAD_PCT, MIN_DTE_FOR_ELIGIBILITY,
    MAX_DTE_ANNUALIZE_FLOOR_DAYS, SPREAD_ABSOLUTE_BANDS,
    STRATEGY_WEIGHTS, STRATEGY_LIQUIDITY_SUBWEIGHTS, STRATEGY_LEG_ACTIVITY_SCALE, RISK_REWARD_BANDS,
    BREAKEVEN_RATIO_BANDS, BREAKEVEN_ALREADY_MET_RATIO, IV_HV_DEVIATION_SCALE, DIRECTIONAL_SCORE_MIDPOINT,
    RELATIVE_IV_CHEAP_THRESHOLD, RELATIVE_IV_EXPENSIVE_THRESHOLD, RELATIVE_IV_SCORE_SCALE,
    OI_CHANGE_SCORE_SCALE, CATEGORY_HIGH_LIQUIDITY, CATEGORY_HIGH_IV_RANK,
    CATEGORY_LOW_IV_RANK, CATEGORY_HIGH_OI, CATEGORY_OI_BUILDUP_PCT, CATEGORY_OI_UNWIND_PCT,
    LOW_LIQUIDITY_RISK_THRESHOLD, WIDE_SPREAD_RISK_PCT, THETA_DECAY_WARNING_RATIO,
    GOOD_BREAKEVEN_RATIO_FOR_WHY, STRATEGY_IV_CONTEXT_BANDS_LOW_GOOD,
    STRATEGY_IV_CONTEXT_BANDS_HIGH_GOOD, IV_CONTEXT_CHEAP_THRESHOLD, IV_CONTEXT_EXPENSIVE_THRESHOLD,
    STRAT_RR_GOOD_THRESHOLD, STRAT_POP_GOOD_THRESHOLD, STRAT_POP_BAD_THRESHOLD,
    STRAT_LIQUIDITY_GOOD_THRESHOLD, STRAT_WORST_LEG_BAD_THRESHOLD, STRAT_IV_CONTEXT_GOOD_THRESHOLD,
    EXPECTED_VALUE_SCORE_MIDPOINT, EXPECTED_VALUE_SCORE_SCALE, STRAT_LOW_CAPACITY_UNITS_THRESHOLD,
    confidence_from_coverage, grade_from_score, band_score,
)

def _pct_rank(series: pd.Series, value) -> float:
    """رتبه صدکی value درون series (۰ تا ۱۰۰). NaNها نادیده گرفته می‌شوند."""
    s = series.dropna()
    if s.empty or pd.isna(value):
        return None
    return float((s <= value).mean() * 100)


def _renormalize(components: dict) -> tuple:
    """
    جمع وزن‌دار مؤلفه‌های موجود (None حذف و وزن‌ها Re-normalize می‌شوند).
    Returns: (score یا None, coverage_pct)
    coverage_pct = چند درصد از وزن کل واقعاً در دسترس بود (بخش ۱۴ سند).
    """
    total_possible = sum(v["weight"] for v in components.values())
    available = {k: v for k, v in components.items() if v.get("score") is not None}
    if not available or total_possible <= 0:
        return None, 0.0
    total_w = sum(v["weight"] for v in available.values())
    if total_w <= 0:
        return None, 0.0
    score = sum(v["score"] * v["weight"] for v in available.values()) / total_w
    coverage_pct = round(total_w / total_possible * 100, 1)
    return score, coverage_pct


# ---------------------------------------------------------------------------
# سطح ۱: Contract Opportunities (بازطراحی‌شده)
# ---------------------------------------------------------------------------

CONTRACT_CATEGORIES = [
    "High Liquidity", "High IV", "Low IV",
    "Relatively Cheap IV", "Relatively Expensive IV",
    "High OI", "OI Build-up", "OI Unwinding", "Unusual Volume",
]


def _spread_pct(bid, ask, close):
    if pd.isna(bid) or pd.isna(ask) or pd.isna(close) or close in (0, None) or bid is None or ask is None:
        return None
    if bid <= 0 or ask < bid:
        return None  # Quote تک‌طرفه یا نامعتبر - نه صفر
    return (ask - bid) / close * 100


def _liquidity_score(row, group) -> tuple:
    """Returns: (score یا None, subscores dict) — بخش ۶ سند."""
    spread_pct = _spread_pct(row.get("bid"), row.get("ask"), row.get("close"))
    spread_score = band_score(spread_pct, SPREAD_ABSOLUTE_BANDS) if spread_pct is not None else None

    volume_score = _pct_rank(group["volume"], row.get("volume")) if "volume" in group.columns else None
    oi_score = _pct_rank(group["open_interest"], row.get("open_interest")) if "open_interest" in group.columns else None

    depth_score = None
    if "bid_size" in group.columns and "ask_size" in group.columns:
        bsz, asz = row.get("bid_size"), row.get("ask_size")
        if pd.notna(bsz) and pd.notna(asz):
            depth_val = float(bsz) + float(asz)
            depth_series = (group["bid_size"].fillna(0) + group["ask_size"].fillna(0))
            depth_score = _pct_rank(depth_series, depth_val)

    parts = {
        "spread": {"score": spread_score, "weight": LIQUIDITY_SUBWEIGHTS["spread"]},
        "volume": {"score": volume_score, "weight": LIQUIDITY_SUBWEIGHTS["volume"]},
        "oi": {"score": oi_score, "weight": LIQUIDITY_SUBWEIGHTS["oi"]},
        "depth": {"score": depth_score, "weight": LIQUIDITY_SUBWEIGHTS["depth"]},
    }
    score, _cov = _renormalize(parts)
    return score, {"spread_pct": spread_pct, **{k: v["score"] for k, v in parts.items()}}


def _iv_value_score(row, underlying_hist, option_hist) -> tuple:
    """
    بخش ۷، ۱۵ سند: IV/HV + IV Rank + IV Percentile.

    IV/HV جهت‌دار است (نه صرفاً اندازه‌ی انحراف): IV ارزان‌تر از نوسان واقعی
    (احتمالاً فرصت خرید بهتر) امتیاز بالاتر می‌گیرد، IV گران‌تر امتیاز
    پایین‌تر — چون |log(iv/hv)| هر دو جهت را یکسان «خوب» نشان می‌داد که
    از نظر اقتصادی نادرست بود.
    """
    iv = row.get("iv")
    iv_hv_score = None
    iv_hv_direction = None
    hv = analytics.underlying_hv(underlying_hist, row["underlying"]) if underlying_hist is not None else None
    if pd.notna(iv) and hv:
        log_dev = np.log(iv / hv)  # منفی = IV ارزان‌تر از HV، مثبت = گران‌تر
        iv_hv_score = float(np.clip(
            DIRECTIONAL_SCORE_MIDPOINT - log_dev * IV_HV_DEVIATION_SCALE, 0, 100
        ))
        iv_hv_direction = ("IV ارزان‌تر از نوسان واقعی اخیر" if log_dev < -0.05
                            else "IV گران‌تر از نوسان واقعی اخیر" if log_dev > 0.05
                            else "IV نزدیک به نوسان واقعی اخیر")

    iv_rank_score = iv_pctl_score = None
    hist_series = analytics.contract_iv_history(
        option_hist, instrument_id=row.get("instrument_id"), symbol=row.get("symbol"),
        exclude_quote_date=row.get("quote_date"),
    ) if option_hist is not None else pd.Series(dtype=float)
    if pd.notna(iv) and len(hist_series):
        res = analytics.iv_percentile(hist_series, iv)
        iv_rank_score = res["rank"]
        iv_pctl_score = res["percentile"]

    parts = {
        "iv_hv": {"score": iv_hv_score, "weight": IV_VALUE_SUBWEIGHTS["iv_hv"]},
        "iv_rank": {"score": iv_rank_score, "weight": IV_VALUE_SUBWEIGHTS["iv_rank"]},
        "iv_percentile": {"score": iv_pctl_score, "weight": IV_VALUE_SUBWEIGHTS["iv_percentile"]},
    }
    score, _cov = _renormalize(parts)
    return score, {"hv": hv, "iv_hv_ratio": (iv / hv) if (pd.notna(iv) and hv) else None,
                    "iv_hv_direction": iv_hv_direction,
                    "iv_rank": iv_rank_score, "iv_percentile": iv_pctl_score}


def _relative_iv_score(row, group) -> tuple:
    """
    بخش ۸، ۱۶ سند: «Relative IV Value»، نه Fair Value واقعی.
    هم‌گروه = همان (underlying, expiry, option_type) + همان دسته Moneyness،
    تا Strikeهای خیلی متفاوت با هم مقایسه نشوند.

    جهت‌دار: IV ارزان‌تر از هم‌گروه امتیاز بالاتر، IV گران‌تر امتیاز
    پایین‌تر می‌گیرد (نه |انحراف| که هر دو جهت را یکسان نشان می‌داد).
    """
    iv = row.get("iv")
    if pd.isna(iv) or "moneyness" not in group.columns:
        return None, {"peers": 0, "direction": None}

    peers = group[group["moneyness"] == row.get("moneyness")]["iv"].dropna()
    peers_excl_self = peers[peers.index != row.name] if row.name in peers.index else peers
    if len(peers_excl_self) < MIN_PEERS_FOR_RELATIVE_IV:
        return None, {"peers": len(peers_excl_self), "direction": None,
                       "note": f"حداقل {MIN_PEERS_FOR_RELATIVE_IV} هم‌گروه هم‌سطح Moneyness لازم است."}

    peer_median = float(peers_excl_self.median())
    if peer_median <= 0:
        return None, {"peers": len(peers_excl_self), "direction": None}

    deviation = (iv - peer_median) / peer_median  # منفی = ارزان‌تر، مثبت = گران‌تر
    score = float(np.clip(
        DIRECTIONAL_SCORE_MIDPOINT - deviation * RELATIVE_IV_SCORE_SCALE, 0, 100
    ))
    if deviation <= RELATIVE_IV_CHEAP_THRESHOLD:
        direction = "نسبتاً ارزان (IV پایین‌تر از هم‌گروه هم‌سطح)"
    elif deviation >= RELATIVE_IV_EXPENSIVE_THRESHOLD:
        direction = "نسبتاً گران (IV بالاتر از هم‌گروه هم‌سطح)"
    else:
        direction = "در محدوده عادی هم‌گروه"
    return score, {"peers": len(peers_excl_self), "peer_median_iv": peer_median, "direction": direction}


def _oi_participation_score(row, group) -> tuple:
    """بخش ۹ سند: فقط OI/Volume فعلی؛ هیچ Historical OI استفاده نمی‌شود."""
    oi = row.get("open_interest")
    prev_oi = row.get("previous_open_interest")
    vol = row.get("volume")

    oi_level_score = _pct_rank(group["open_interest"], oi) if "open_interest" in group.columns else None

    oi_change_score = None
    oi_change_pct = None
    if pd.notna(oi) and pd.notna(prev_oi) and prev_oi not in (0, None):
        oi_change_pct = (oi - prev_oi) / prev_oi * 100
        oi_change_score = float(min(100.0, abs(oi_change_pct) * OI_CHANGE_SCORE_SCALE))

    vol_oi_score = None
    vol_oi_ratio = None
    if pd.notna(vol) and pd.notna(oi) and oi > 0:
        vol_oi_ratio = vol / oi
        vol_oi_series = (group["volume"] / group["open_interest"].replace(0, np.nan))
        vol_oi_score = _pct_rank(vol_oi_series, vol_oi_ratio)

    vol_quality_score = _pct_rank(group["volume"], vol) if "volume" in group.columns else None

    parts = {
        "oi_level": {"score": oi_level_score, "weight": OI_PARTICIPATION_SUBWEIGHTS["oi_level"]},
        "oi_change_signal": {"score": oi_change_score, "weight": OI_PARTICIPATION_SUBWEIGHTS["oi_change_signal"]},
        "volume_oi_ratio": {"score": vol_oi_score, "weight": OI_PARTICIPATION_SUBWEIGHTS["volume_oi_ratio"]},
        "volume_quality": {"score": vol_quality_score, "weight": OI_PARTICIPATION_SUBWEIGHTS["volume_quality"]},
    }
    score, _cov = _renormalize(parts)
    return score, {"oi_change_pct": oi_change_pct, "volume_oi_ratio": vol_oi_ratio}


def _premium_efficiency_score(row, group) -> tuple:
    """
    بخش ۱۰ سند: Time Value per Day نسبت به حق بیمه پرداختی، Rank‌شده درون
    هم‌گروه. مخرج DTE با یک کف (MAX_DTE_ANNUALIZE_FLOOR_DAYS) محدود می‌شود
    تا قراردادهای با DTE بسیار کوتاه به‌صرف تقسیم بر عدد کوچک، امتیاز کاذب
    بالا نگیرند.
    """
    tv, close, dte = row.get("time_value"), row.get("close"), row.get("dte")
    if pd.isna(tv) or pd.isna(close) or close in (0, None) or pd.isna(dte):
        return None, {"time_value_per_day": None}

    safe_dte = max(float(dte), MAX_DTE_ANNUALIZE_FLOOR_DAYS)
    efficiency_raw = (tv / safe_dte) / close

    ref_col = None
    if {"time_value", "close", "dte"}.issubset(group.columns):
        ref = (group["time_value"] / group["dte"].clip(lower=MAX_DTE_ANNUALIZE_FLOOR_DAYS)) / group["close"].replace(0, np.nan)
        ref_col = ref

    score = _pct_rank(ref_col, efficiency_raw) if ref_col is not None else None
    return score, {"time_value_per_day": tv / safe_dte if safe_dte else None}


def _breakeven_quality_score(row, underlying_hist) -> tuple:
    """
    بخش ۱۱ سند: نسبت «حرکت موردنیاز تا سربه‌سر» به «حرکت موردانتظار
    بر مبنای نوسان». نزدیک نه به‌معنای همیشه بهتر است نه بدتر - این
    امتیاز فقط می‌گوید رسیدن به سربه‌سر با نوسان فعلی چقدر محتمل‌الوقوع است.
    """
    close, strike, S, dte = row.get("close"), row.get("strike"), row.get("underlying_close"), row.get("dte")
    opt_type = row.get("option_type")
    if any(pd.isna(x) for x in [close, strike, S, dte]) or S in (0, None) or dte is None:
        return None, {"breakeven": None}

    breakeven = strike + close if opt_type == "call" else strike - close
    required_move_pct = abs(breakeven - S) / S

    vol_for_move = row.get("iv")
    if pd.isna(vol_for_move) or not vol_for_move:
        vol_for_move = analytics.underlying_hv(underlying_hist, row["underlying"]) if underlying_hist is not None else None
    if not vol_for_move or vol_for_move <= 0:
        return None, {"breakeven": breakeven, "required_move_pct": required_move_pct * 100}

    expected_move_pct = float(vol_for_move) * np.sqrt(max(dte, 0) / 365.0)
    if required_move_pct <= 0:
        ratio = BREAKEVEN_ALREADY_MET_RATIO
    else:
        ratio = expected_move_pct / required_move_pct

    # نکته: چون thresholdها و scoreهای BREAKEVEN_RATIO_BANDS هر دو صعودی‌اند،
    # مسیر پیش‌فرض (lower_is_better) band_score دقیقاً «هرچه ratio بزرگ‌تر
    # امتیاز بزرگ‌تر» را می‌دهد؛ عمداً higher_is_better=False فراخوانی می‌شود.
    score = band_score(ratio, BREAKEVEN_RATIO_BANDS, higher_is_better=False)
    return score, {"breakeven": breakeven, "required_move_pct": required_move_pct * 100,
                    "expected_move_pct": expected_move_pct * 100, "ratio": ratio}


def _is_eligible(row) -> tuple:
    """
    بخش ۱۳ سند: Gate قبل از امتیازدهی. اگر ineligible، دلیل مشخص برمی‌گردد
    (نه فقط True/False) تا در UI/Coverage قابل توضیح باشد.
    """
    if pd.isna(row.get("close")) or row.get("close") in (None, 0):
        return False, "قیمت قرارداد نامعتبر/غایب"
    if pd.isna(row.get("underlying_close")) or row.get("underlying_close") in (None, 0):
        return False, "قیمت دارایی پایه نامعتبر/غایب"
    dte = row.get("dte")
    if pd.isna(dte) or dte < MIN_DTE_FOR_ELIGIBILITY:
        return False, "DTE نامعتبر یا قرارداد در آستانه/بعد از سررسید"
    bid, ask = row.get("bid"), row.get("ask")
    if pd.notna(bid) and pd.notna(ask) and bid > 0 and ask > 0 and ask < bid:
        return False, "Quote نامعتبر (Ask کمتر از Bid)"
    vol, oi = row.get("volume"), row.get("open_interest")
    has_participation = (pd.notna(vol) and vol > 0) or (pd.notna(oi) and oi > 0)
    if not has_participation:
        return False, "نه حجم و نه موقعیت باز قابل‌اتکایی وجود دارد"
    spread_pct = _spread_pct(bid, ask, row.get("close"))
    if spread_pct is not None and spread_pct > MAX_REASONABLE_SPREAD_PCT:
        return False, f"اسپرد Bid/Ask غیرمنطقی گسترده ({spread_pct:.0f}%)"
    return True, None


def detect_contract_opportunities(chain_df: pd.DataFrame, underlying_hist_df: pd.DataFrame = None,
                                   option_hist_df: pd.DataFrame = None, weights: dict = None) -> pd.DataFrame:
    """
    بازطراحی کامل طبق بخش ۵-۱۴ سند. chain_df باید خروجی enrich_full_dataset
    باشد (iv, delta, moneyness, intrinsic_value, time_value, underlying_close).

    underlying_hist_df/option_hist_df اختیاری‌اند (تاریخچه کامل انباشته‌شده
    Dataset، برای HV و IV Rank/Percentile per-contract) — نبودشان فقط باعث
    می‌شود آن مؤلفه‌های خاص «Insufficient History» شوند، نه خطا.

    weights: اگر داده نشود یا با Schema جدید (core/opportunity_config) سازگار
    نباشد (مثلاً دیکشنری قدیمی UI که هنوز جایگزین نشده)، مقادیر پیش‌فرض
    استفاده می‌شود - نه Crash.
    """
    if not weights or set(weights.keys()) != set(CONTRACT_WEIGHTS.keys()):
        weights = CONTRACT_WEIGHTS

    if chain_df is None or chain_df.empty:
        return pd.DataFrame()

    df = chain_df.copy()
    group_keys = ["underlying", "expiry", "option_type"]
    rows = []
    ineligible_count = 0

    for _, group in df.groupby(group_keys):
        if len(group) < 3:
            continue  # مقایسه نسبی معنادار حداقل ۳ هم‌گروه لازم دارد

        for _, row in group.iterrows():
            eligible, reason = _is_eligible(row)
            if not eligible:
                ineligible_count += 1
                continue

            liq_score, liq_detail = _liquidity_score(row, group)
            iv_val_score, iv_val_detail = _iv_value_score(row, underlying_hist_df, option_hist_df)
            rel_iv_score, rel_iv_detail = _relative_iv_score(row, group)
            oi_score, oi_detail = _oi_participation_score(row, group)
            prem_score, prem_detail = _premium_efficiency_score(row, group)
            be_score, be_detail = _breakeven_quality_score(row, underlying_hist_df)

            components = {
                "liquidity": {"score": liq_score, "weight": weights["liquidity"]},
                "iv_value": {"score": iv_val_score, "weight": weights["iv_value"]},
                "relative_iv": {"score": rel_iv_score, "weight": weights["relative_iv"]},
                "oi_participation": {"score": oi_score, "weight": weights["oi_participation"]},
                "premium_efficiency": {"score": prem_score, "weight": weights["premium_efficiency"]},
                "breakeven_quality": {"score": be_score, "weight": weights["breakeven_quality"]},
            }
            score, coverage_pct = _renormalize(components)
            if score is None:
                continue  # هیچ بُعدی قابل‌محاسبه نبود - در لیست فرصت‌ها بی‌معناست

            categories = []
            if liq_score is not None and liq_score >= CATEGORY_HIGH_LIQUIDITY:
                categories.append("High Liquidity")
            if iv_val_detail.get("iv_rank") is not None and iv_val_detail["iv_rank"] >= CATEGORY_HIGH_IV_RANK:
                categories.append("High IV")
            elif iv_val_detail.get("iv_rank") is not None and iv_val_detail["iv_rank"] <= CATEGORY_LOW_IV_RANK:
                categories.append("Low IV")
            if (rel_iv_detail.get("direction") or "").startswith("نسبتاً ارزان"):
                categories.append("Relatively Cheap IV")
            elif (rel_iv_detail.get("direction") or "").startswith("نسبتاً گران"):
                categories.append("Relatively Expensive IV")
            if oi_score is not None and oi_score >= CATEGORY_HIGH_OI:
                categories.append("High OI")
            oi_chg = oi_detail.get("oi_change_pct")
            if oi_chg is not None and oi_chg >= CATEGORY_OI_BUILDUP_PCT:
                categories.append("OI Build-up")
            elif oi_chg is not None and oi_chg <= CATEGORY_OI_UNWIND_PCT:
                categories.append("OI Unwinding")

            why, risks = [], []
            if liq_score is not None and liq_score >= CATEGORY_HIGH_LIQUIDITY:
                why.append("✓ نقدشوندگی و اجرا مناسب نسبت به هم‌گروه")
            if liq_score is not None and liq_score <= LOW_LIQUIDITY_RISK_THRESHOLD:
                risks.append("⚠ کیفیت نقدشوندگی/اجرا پایین")
            if rel_iv_detail.get("direction") and "ارزان" in rel_iv_detail["direction"]:
                why.append(f"✓ {rel_iv_detail['direction']}")
            elif rel_iv_detail.get("direction") and "گران" in rel_iv_detail["direction"]:
                risks.append(f"⚠ {rel_iv_detail['direction']}")
            if oi_score is not None and oi_score >= CATEGORY_HIGH_OI:
                why.append("✓ مشارکت/موقعیت باز قوی نسبت به هم‌گروه")
            if be_detail.get("ratio") is not None and be_detail["ratio"] >= GOOD_BREAKEVEN_RATIO_FOR_WHY:
                why.append("✓ حرکت موردنیاز تا سربه‌سر نسبت به نوسان موردانتظار منطقی است")
            if liq_detail.get("spread_pct") is not None and liq_detail["spread_pct"] > WIDE_SPREAD_RISK_PCT:
                risks.append("⚠ اسپرد Bid/Ask گسترده")
            if pd.notna(row.get("theta")) and row.get("close"):
                if abs(row["theta"]) / max(abs(row["close"]), 1) > THETA_DECAY_WARNING_RATIO:
                    risks.append("⚠ فرسایش زمانی (Theta) بالا")

            rows.append({
                "symbol": row.get("symbol"), "instrument_id": row.get("instrument_id"),
                "underlying": row["underlying"], "option_type": row["option_type"],
                "strike": row["strike"], "expiry": row["expiry"], "dte": row.get("dte"),
                "close": row.get("close"), "iv": row.get("iv"),
                "volume": row.get("volume"), "open_interest": row.get("open_interest"),
                "categories": categories,
                "score": round(score, 1),
                "coverage": coverage_pct,
                "confidence": confidence_from_coverage(coverage_pct),
                "grade": grade_from_score(score),
                "eligible": True,
                "subscores": {
                    "liquidity": round(liq_score, 1) if liq_score is not None else None,
                    "iv_value": round(iv_val_score, 1) if iv_val_score is not None else None,
                    "relative_iv": round(rel_iv_score, 1) if rel_iv_score is not None else None,
                    "oi_participation": round(oi_score, 1) if oi_score is not None else None,
                    "premium_efficiency": round(prem_score, 1) if prem_score is not None else None,
                    "breakeven_quality": round(be_score, 1) if be_score is not None else None,
                },
                "why": why, "risks": risks,
            })

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values("score", ascending=False, na_position="last").reset_index(drop=True)
    result.attrs["ineligible_count"] = ineligible_count
    return result


# ---------------------------------------------------------------------------
# سطح ۲: Strategy Opportunities (بازطراحی طبق بخش ۱۵-۲۰ Master Prompt)
# ---------------------------------------------------------------------------

def _default_index(strikes, rank, opt_type, s_ref):
    arr = np.array(strikes)
    if len(arr) == 0:
        return None
    atm_idx = int(np.argmin(np.abs(arr - s_ref)))
    if rank == "atm":
        return atm_idx
    step = 1 if rank == "otm" else 3
    idx = atm_idx + step if opt_type == "call" else atm_idx - step
    return max(0, min(len(arr) - 1, idx))


def _leg_liquidity_score(row) -> float:
    """
    امتیاز نقدشوندگی یک پایه منفرد: ترکیب کیفیت اسپرد (در صورت وجود
    Bid/Ask) با حجم/OI خام آن پایه. برای Worst-Leg Penalty (بخش ۱۹ سند)
    استفاده می‌شود.
    """
    spread_pct = _spread_pct(row.get("bid"), row.get("ask"), row.get("close"))
    spread_score = band_score(spread_pct, SPREAD_ABSOLUTE_BANDS) if spread_pct is not None else None

    vol, oi = row.get("volume"), row.get("open_interest")
    activity_score = None
    if pd.notna(vol) or pd.notna(oi):
        activity_score = min(100.0, ((vol or 0) + (oi or 0)) / STRATEGY_LEG_ACTIVITY_SCALE)

    parts = {k: v for k, v in
             {"spread": spread_score, "activity": activity_score}.items() if v is not None}
    if not parts:
        return None
    return float(np.mean(list(parts.values())))


def _strategy_liquidity_score(leg_rows: list) -> tuple:
    """میانگین + بدترین پایه (بخش ۱۹ سند) - یک پایه بسیار بی‌نقد کل استراتژی را غیرقابل‌اجرا می‌کند."""
    leg_scores = [s for s in (_leg_liquidity_score(r) for r in leg_rows) if s is not None]
    if not leg_scores:
        return None, {"avg_leg": None, "worst_leg": None}
    avg_leg = float(np.mean(leg_scores))
    worst_leg = float(min(leg_scores))
    combined = (avg_leg * STRATEGY_LIQUIDITY_SUBWEIGHTS["avg_leg"]
                + worst_leg * STRATEGY_LIQUIDITY_SUBWEIGHTS["worst_leg"])
    return combined, {"avg_leg": round(avg_leg, 1), "worst_leg": round(worst_leg, 1)}


def _strategy_iv_context_score(leg_rows: list, credit: float, underlying_hist, underlying_name) -> tuple:
    """
    بخش ۲۰ سند: تفسیر IV باید جهت‌دار باشد، نه «IV بالا=خوب» ساده.
    - استراتژی Long Premium (Debit خالص پرداخت می‌شود): IV نسبتاً ارزان (نسبت
      IV/HV پایین‌تر) به نفع خریدار است.
    - استراتژی Short Premium (Credit خالص دریافت می‌شود): IV نسبتاً گران
      (نسبت IV/HV بالاتر) به نفع فروشنده است.
    اگر HV قابل‌محاسبه نباشد، Unavailable (نه فرض پیش‌فرض جهت‌دار).
    """
    ivs = [r.get("iv") for r in leg_rows if pd.notna(r.get("iv"))]
    if not ivs:
        return None, {"avg_iv": None, "iv_hv_ratio": None, "direction": None}
    avg_iv = float(np.mean(ivs))

    hv = analytics.underlying_hv(underlying_hist, underlying_name) if underlying_hist is not None else None
    if not hv or hv <= 0:
        return None, {"avg_iv": avg_iv, "iv_hv_ratio": None,
                       "note": "HV کافی برای زمینه‌سازی IV موجود نیست."}

    ratio = avg_iv / hv
    is_long_premium = credit < 0  # net_premium منفی یعنی خالص پرداخت (Debit)

    # بندها به‌گونه‌اند که نزدیک ۱٫۰ = خنثی؛ برای Long Premium ratio پایین بهتر،
    # برای Short Premium ratio بالا بهتر.
    score = band_score(ratio, STRATEGY_IV_CONTEXT_BANDS_LOW_GOOD if is_long_premium
                        else STRATEGY_IV_CONTEXT_BANDS_HIGH_GOOD)

    direction = ("IV نسبتاً ارزان - به نفع خرید Premium" if ratio < IV_CONTEXT_CHEAP_THRESHOLD
                 else "IV نسبتاً گران - به نفع فروش Premium" if ratio > IV_CONTEXT_EXPENSIVE_THRESHOLD
                 else "IV در محدوده معمول نسبت به نوسان واقعی")
    return score, {"avg_iv": avg_iv, "iv_hv_ratio": ratio, "direction": direction,
                    "strategy_side": "Long Premium" if is_long_premium else "Short Premium"}


def _strategy_breakeven_score(legs, s_ref, dte, avg_iv, underlying_hist, underlying_name) -> tuple:
    """همان مفهوم «حرکت موردنیاز / حرکت موردانتظار» ولی روی نزدیک‌ترین نقطه سربه‌سر استراتژی."""
    try:
        bes = strat_engine.breakevens(legs, s_ref)
    except Exception:
        bes = []
    if not bes or not s_ref:
        return None, {"breakevens": bes}

    nearest = min(bes, key=lambda b: abs(b - s_ref))
    required_move_pct = abs(nearest - s_ref) / s_ref

    vol = avg_iv or (analytics.underlying_hv(underlying_hist, underlying_name) if underlying_hist is not None else None)
    if not vol or not dte:
        return None, {"breakevens": bes, "nearest": nearest}

    expected_move_pct = float(vol) * np.sqrt(max(dte, 0) / 365.0)
    ratio = BREAKEVEN_ALREADY_MET_RATIO if required_move_pct <= 0 else expected_move_pct / required_move_pct
    score = band_score(ratio, BREAKEVEN_RATIO_BANDS, higher_is_better=False)
    return score, {"breakevens": bes, "nearest": nearest, "required_move_pct": required_move_pct * 100,
                    "expected_move_pct": expected_move_pct * 100}


def _strategy_liquidity_capacity(leg_rows: list):
    """
    بخش ۶ سند: چند «واحد» از این استراتژی واقعاً قابل‌اجراست، محدود به
    کم‌نقدترین پایه (Bottleneck). اگر Volume یک پایه در دسترس نبود، OI همان
    پایه Fallback است؛ اگر هیچ‌کدام نبود، این پایه ظرفیت را نامشخص می‌کند
    (نه صفر) و کل ظرفیت Unavailable می‌شود.
    """
    caps = []
    for r in leg_rows:
        vol, oi = r.get("volume"), r.get("open_interest")
        cap = vol if pd.notna(vol) and vol > 0 else (oi if pd.notna(oi) and oi > 0 else None)
        if cap is None:
            return None
        caps.append(cap)
    return int(min(caps)) if caps else None


def recommended_position_size(max_loss_per_unit, account_capital: float, risk_budget_pct: float):
    """
    بخش ۵ سند: تعداد واحد پیشنهادی بر مبنای بودجه ریسک، نه یک عدد ثابت.

    اگر ریسک نامحدود یا نامشخص باشد، هرگز عددی ساختگی برنمی‌گردانیم؛ دلیل
    مشخص گزارش می‌شود تا کاربر بداند چرا محاسبه نشده، نه اینکه سکوت کند.
    """
    if max_loss_per_unit is None:
        return None, "حداکثر زیان هر واحد نامشخص است."
    if max_loss_per_unit == 0:
        return None, "حداکثر زیان هر واحد صفر است؛ محاسبه اندازه موقعیت بی‌معناست."
    if not account_capital or account_capital <= 0:
        return None, "سرمایه حساب نامعتبر است."
    risk_amount = account_capital * (risk_budget_pct / 100.0)
    units = int(risk_amount // abs(max_loss_per_unit))
    if units < 1:
        return 0, "بودجه ریسک برای حتی یک واحد این استراتژی کافی نیست."
    return units, None


def detect_strategy_opportunities(chain_df: pd.DataFrame, underlying: str, expiry,
                                   s_ref: float, r: float, weights: dict = None,
                                   underlying_hist_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    برای یک (underlying, expiry) مشخص، همه قالب‌های STRATEGY_TEMPLATES را با
    Strikeهای پیش‌فرض واقعی (از همان زنجیره) می‌سازد و امتیازدهی می‌کند.

    امتیازدهی طبق بخش ۱۵-۲۰ Master Prompt، کاملاً مستقل از مدل Contract:
    Expected Value (از همان شبیه‌سازی POP)، Risk/Reward پله‌ای (نه خطی
    نامحدود)، نقدشوندگی میانگین+بدترین پایه، IV Context جهت‌دار، کیفیت
    سربه‌سر. Coverage/Confidence/Grade مثل سطح Contract صریح گزارش می‌شود.
    """
    if not weights or set(weights.keys()) != set(STRATEGY_WEIGHTS.keys()):
        weights = STRATEGY_WEIGHTS

    sub = chain_df[(chain_df["underlying"] == underlying) & (chain_df["expiry"] == expiry)]
    if sub.empty:
        return pd.DataFrame()

    calls = sub[sub["option_type"] == "call"].sort_values("strike").reset_index(drop=True)
    puts = sub[sub["option_type"] == "put"].sort_values("strike").reset_index(drop=True)
    # مقدار Fallback فقط اگر هیچ IV در سطح Leg موجود نبود استفاده می‌شود (بخش ۱۲ سند)
    fallback_sigma = float(sub["iv"].dropna().mean()) if sub["iv"].notna().any() else None
    dte_ctx = int(sub["dte"].dropna().iloc[0]) if sub["dte"].notna().any() else None

    rows = []
    for name, template in strat_engine.STRATEGY_TEMPLATES.items():
        if template is None:
            continue
        legs, leg_rows = [], []
        ok = True
        for role in template:
            if role["option_type"] == "stock":
                legs.append(strat_engine.Leg("stock", role["side"], 0.0,
                                             float(s_ref), role.get("qty", 1)))
                continue
            book = calls if role["option_type"] == "call" else puts
            if book.empty:
                ok = False
                break
            idx = _default_index(book["strike"].values, role["rank"], role["option_type"], s_ref)
            if idx is None:
                ok = False
                break
            row = book.iloc[idx]
            cs = float(row["contract_size"]) if pd.notna(row.get("contract_size")) and row.get("contract_size", 0) > 0 else None
            legs.append(strat_engine.Leg(role["option_type"], role["side"], float(row["strike"]),
                                          float(row["close"]), role.get("qty", 1),
                                          **({"contract_size": cs} if cs else {})))
            leg_rows.append(row)
        if not ok or not legs:
            continue

        # IV زمینه‌ای برای Monte Carlo: میانگین وزن‌دار (با qty) فقط پایه‌های
        # اختیارِ همین استراتژی، نه میانگین کل زنجیره (بخش ۱۲ سند). فقط اگر
        # هیچ IV سطح-پایه در دسترس نبود، به میانگین کل سررسید برمی‌گردیم.
        leg_ivs = [(r["iv"], role.get("qty", 1)) for r, role in zip(leg_rows, [t for t in template if t["option_type"] != "stock"])
                   if pd.notna(r.get("iv"))]
        if leg_ivs:
            sigma_ctx = sum(iv * w for iv, w in leg_ivs) / sum(w for _, w in leg_ivs)
        else:
            sigma_ctx = fallback_sigma

        credit = strat_engine.net_premium(legs)
        mpl = strat_engine.max_profit_loss(legs, s_ref)

        # --- Expected Value + POP از یک شبیه‌سازی واحد (بخش ۱۶ سند) ---
        sim = {"pop": None, "expected_value": None}
        if sigma_ctx and dte_ctx:
            sim = strat_engine.simulate_outcome(legs, s_ref, sigma_ctx, dte_ctx / 365, r)
        pop = sim["pop"]

        # --- Risk/Reward پله‌ای (بخش ۱۸ سند) ---
        rr_score = None
        if not mpl["max_profit_is_unbounded"] and not mpl["max_loss_is_unbounded"] and mpl["max_loss"] is not None:
            ratio = abs(mpl["max_profit"] / mpl["max_loss"]) if mpl["max_loss"] != 0 else None
            rr_score = band_score(ratio, RISK_REWARD_BANDS, higher_is_better=True) if ratio is not None else None

        # --- نقدشوندگی: میانگین + بدترین پایه (بخش ۱۹ سند) ---
        liq_score, liq_detail = _strategy_liquidity_score(leg_rows)
        liq_capacity = _strategy_liquidity_capacity(leg_rows)

        # --- IV Context جهت‌دار (بخش ۲۰ سند) ---
        iv_ctx_score, iv_ctx_detail = _strategy_iv_context_score(leg_rows, credit, underlying_hist_df, underlying)

        # --- کیفیت سربه‌سر (بخش ۱۱ اصل، تعمیم‌یافته به سطح Strategy) ---
        be_score, be_detail = _strategy_breakeven_score(
            legs, s_ref, dte_ctx, iv_ctx_detail.get("avg_iv"), underlying_hist_df, underlying
        )

        ev_score = None
        if sim["expected_value"] is not None:
            # بخش ۱۰ سند: قاعده قطعی None=missing، ۰=مقدار واقعی. هرگز از
            # `if credit` استفاده نمی‌شود چون credit=۰ (اسپرد کاملاً متوازن)
            # را به‌اشتباه «غایب» تلقی می‌کند.
            # - استراتژی Debit (credit<0): مرجع = Net Debit
            # - استراتژی Credit با ریسک محدود (credit>=0 و Max Loss مشخص): مرجع = Max Loss
            # - ریسک نامحدود/نامشخص و credit=0: مرجع ساختگی نمی‌سازیم -> None
            if credit is not None and credit < 0:
                capital_ref = abs(credit)
            elif mpl.get("max_loss") is not None:
                capital_ref = abs(mpl["max_loss"])
            elif credit:  # credit>0 ولی Max Loss نامشخص/نامحدود؛ Net Credit به‌عنوان آخرین مرجع منطقی
                capital_ref = abs(credit)
            else:
                capital_ref = None
            if capital_ref:
                ev_score = float(np.clip(
                    EXPECTED_VALUE_SCORE_MIDPOINT + (sim["expected_value"] / capital_ref) * EXPECTED_VALUE_SCORE_SCALE,
                    0, 100))

        components = {
            "expected_value": {"score": ev_score, "weight": weights["expected_value"]},
            "probability_of_profit": {"score": float(pop * 100) if pop is not None else None,
                                       "weight": weights["probability_of_profit"]},
            "risk_reward": {"score": rr_score, "weight": weights["risk_reward"]},
            "liquidity": {"score": liq_score, "weight": weights["liquidity"]},
            "iv_context": {"score": iv_ctx_score, "weight": weights["iv_context"]},
            "breakeven_quality": {"score": be_score, "weight": weights["breakeven_quality"]},
        }
        score, coverage_pct = _renormalize(components)
        if score is None:
            continue

        why, risks = [], []
        if rr_score is not None and rr_score >= STRAT_RR_GOOD_THRESHOLD:
            why.append("✓ نسبت ریسک/بازده مناسب")
        if pop is not None and pop >= STRAT_POP_GOOD_THRESHOLD:
            why.append("✓ احتمال سودآوری (POP) بالا")
        if liq_score is not None and liq_score >= STRAT_LIQUIDITY_GOOD_THRESHOLD:
            why.append("✓ نقدشوندگی پایه‌ها مناسب (میانگین و بدترین پایه)")
        if liq_detail.get("worst_leg") is not None and liq_detail["worst_leg"] < STRAT_WORST_LEG_BAD_THRESHOLD:
            risks.append("⚠ حداقل یک پایه نقدشوندگی بسیار پایینی دارد")
        if liq_capacity is not None and liq_capacity < STRAT_LOW_CAPACITY_UNITS_THRESHOLD:
            risks.append(f"⚠ ظرفیت اجرای هم‌زمان همه پایه‌ها بسیار محدود است (≈{liq_capacity} واحد)")
        if mpl["max_loss_is_unbounded"]:
            risks.append("⚠ ریسک زیان نامحدود")
        if pop is not None and pop < STRAT_POP_BAD_THRESHOLD:
            risks.append("⚠ احتمال سودآوری پایین")
        if iv_ctx_detail.get("direction"):
            (why if (iv_ctx_score or 0) >= STRAT_IV_CONTEXT_GOOD_THRESHOLD else risks).append(
                ("✓ " if (iv_ctx_score or 0) >= STRAT_IV_CONTEXT_GOOD_THRESHOLD else "⚠ ") + iv_ctx_detail["direction"]
            )

        rows.append({
            "strategy": name, "underlying": underlying, "expiry": expiry,
            "credit_debit": round(credit, 1),
            "max_profit": "نامحدود" if mpl["max_profit_is_unbounded"] else round(mpl["max_profit"], 1),
            "max_loss": "نامحدود" if mpl["max_loss_is_unbounded"] else round(mpl["max_loss"], 1),
            "max_loss_raw": None if mpl["max_loss_is_unbounded"] else mpl["max_loss"],
            "liquidity_capacity_units": liq_capacity,
            "pop": round(pop * 100, 1) if pop is not None else None,
            "expected_value": round(sim["expected_value"], 1) if sim["expected_value"] is not None else None,
            "score": round(score, 1),
            "coverage": coverage_pct,
            "confidence": confidence_from_coverage(coverage_pct),
            "grade": grade_from_score(score),
            "subscores": {k: (round(v["score"], 1) if v["score"] is not None else None)
                          for k, v in components.items()},
            "legs": legs, "why": why, "risks": risks,
        })

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values("score", ascending=False, na_position="last").reset_index(drop=True)
    return result


# ---------------------------------------------------------------------------
# سطح ۳: اسکن استراتژی روی کل Universe بازار (بخش ۳۵ Master Prompt)
# ---------------------------------------------------------------------------
def scan_strategy_universe(chain_df: pd.DataFrame, r: float, weights: dict = None,
                           strategies: list = None, min_legs_liquidity: bool = False,
                           underlying_hist_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    پاسخ به پرسش «امروز بهترین <استراتژی>های بازار کدام‌اند؟».

    این تابع فرمول جدیدی اختراع نمی‌کند: صرفاً detect_strategy_opportunities را
    روی همه جفت‌های (underlying, expiry) موجود در Snapshot اجرا و نتایج را در
    یک رتبه‌بندی واحد ادغام می‌کند.

    strategies: اگر داده شود، فقط همین نام‌ها نگه داشته می‌شوند.
    خروجی: DataFrame مرتب‌شده بر اساس score (نزولی).
    """
    if not weights or set(weights.keys()) != set(STRATEGY_WEIGHTS.keys()):
        weights = STRATEGY_WEIGHTS
    if chain_df is None or chain_df.empty:
        return pd.DataFrame()

    frames = []
    for (underlying, expiry), group in chain_df.groupby(["underlying", "expiry"]):
        # مرجع قیمت: قیمت واقعی دارایی پایه. اگر موجود نباشد این جفت را
        # کنار می‌گذاریم — با میانه Strike جایگزین نمی‌کنیم چون آن یک
        # قیمتِ ساختگی است و Moneyness/POP را بی‌معنا می‌کند.
        s_ref = None
        if "underlying_close" in group.columns and group["underlying_close"].notna().any():
            s_ref = float(group["underlying_close"].dropna().iloc[0])
        if not s_ref or s_ref <= 0:
            continue

        res = detect_strategy_opportunities(group, underlying, expiry, s_ref, r, weights, underlying_hist_df)
        if not res.empty:
            res = res.copy()
            res["spot"] = s_ref
            frames.append(res)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    if strategies:
        out = out[out["strategy"].isin(strategies)]
    if out.empty:
        return out
    return out.sort_values("score", ascending=False, na_position="last").reset_index(drop=True)


def universe_coverage(chain_df: pd.DataFrame) -> dict:
    """
    گزارش شفاف پوشش اسکن: چند جفت (نماد، سررسید) قابل‌بررسی بودند و چند تا
    به‌دلیل نبود قیمت دارایی پایه کنار گذاشته شدند. برای اینکه UI بتواند
    صادقانه بگوید اسکن روی چه بخشی از بازار انجام شده.
    """
    if chain_df is None or chain_df.empty:
        return {"total_pairs": 0, "scanned_pairs": 0, "skipped_no_spot": 0}

    total = skipped = 0
    for _, group in chain_df.groupby(["underlying", "expiry"]):
        total += 1
        has_spot = ("underlying_close" in group.columns
                    and group["underlying_close"].notna().any()
                    and float(group["underlying_close"].dropna().iloc[0]) > 0)
        if not has_spot:
            skipped += 1
    return {"total_pairs": total, "scanned_pairs": total - skipped, "skipped_no_spot": skipped}
