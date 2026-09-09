"""
موتور Analytics - هر ماژول فقط وقتی مقدار می‌دهد که داده کافی برای محاسبه
واقعی آن Metric موجود باشد؛ در غیر این صورت وضعیت "Insufficient Historical
Data" یا "Unavailable" برمی‌گرداند (هرگز مقدار ساختگی/صفر گمراه‌کننده).

حداقل تعداد Snapshot متفاوت برای اینکه IV Rank/Percentile یا HV معنادار
باشد را MIN_SNAPSHOTS_FOR_HISTORY تعریف می‌کند.
"""
import numpy as np
import pandas as pd

MIN_SNAPSHOTS_FOR_HISTORY = 5


def iv_analytics(chain_df: pd.DataFrame, underlying_hist_df: pd.DataFrame) -> dict:
    """
    chain_df: زنجیره یک (underlying, expiry, quote_date) خاص با ستون iv.
    underlying_hist_df: کل تاریخچه قیمت دارایی پایه برای این underlying
                        (برای HV و به‌عنوان معیار کفایت تاریخچه).
    """
    out = {"status": "calculated", "iv_mean": None, "hv": None, "iv_hv_ratio": None,
           "iv_rank": None, "iv_percentile": None, "note": None}

    if not (chain_df["iv"].notna().any()):
        out["status"] = "unavailable"
        out["note"] = "نوسان ضمنی (IV) برای این زنجیره در داده موجود نیست."
        return out

    out["iv_mean"] = float(chain_df["iv"].dropna().mean())

    n_snap = underlying_hist_df["quote_date"].nunique() if underlying_hist_df is not None and not underlying_hist_df.empty else 0
    if n_snap < MIN_SNAPSHOTS_FOR_HISTORY:
        out["note"] = "Insufficient Historical Data — برای HV/IV Rank/IV Percentile حداقل ۵ Snapshot تاریخی لازم است."
        return out

    # HV باید per-symbol محاسبه شود. اگر underlying_hist_df بیش از یک نماد
    # داشته باشد، sort سراسری باعث می‌شود log-return بین قیمت دو نماد متفاوت
    # گرفته شود و عدد بی‌معنا تولید کند. market_hv این کار را درست انجام می‌دهد.
    from core.market_brief import market_hv
    hv, n_symbols = market_hv(underlying_hist_df, min_points=MIN_SNAPSHOTS_FOR_HISTORY)
    if hv is not None:
        out["hv_symbols_used"] = n_symbols
        out["hv"] = float(hv)
        if out["hv"] > 0:
            out["iv_hv_ratio"] = round(out["iv_mean"] / out["hv"], 2)

    return out


def oi_analytics(chain_df: pd.DataFrame, prior_chain_df: pd.DataFrame = None) -> dict:
    """
    chain_df: زنجیره یک Snapshot/Expiry خاص.
    prior_chain_df: همان زنجیره در Snapshot قبلی (برای OI Change) - اختیاری.
    """
    out = {"status": "calculated", "call_oi": None, "put_oi": None, "top_strikes": None,
           "oi_concentration_pct": None, "oi_change": None, "note": None}

    if not chain_df["open_interest"].notna().any():
        out["status"] = "unavailable"
        out["note"] = "موقعیت باز (Open Interest) در داده موجود نیست."
        return out

    calls = chain_df[chain_df["option_type"] == "call"]
    puts = chain_df[chain_df["option_type"] == "put"]
    out["call_oi"] = float(calls["open_interest"].sum())
    out["put_oi"] = float(puts["open_interest"].sum())

    total_oi = chain_df["open_interest"].sum()
    if total_oi and total_oi > 0:
        top = chain_df.nlargest(5, "open_interest")[["strike", "option_type", "open_interest"]]
        out["top_strikes"] = top.to_dict("records")
        out["oi_concentration_pct"] = round(float(top["open_interest"].sum()) / float(total_oi) * 100, 1)

    if prior_chain_df is not None and not prior_chain_df.empty and prior_chain_df["open_interest"].notna().any():
        prior_total = prior_chain_df["open_interest"].sum()
        if prior_total:
            out["oi_change"] = float(total_oi - prior_total)
    else:
        out["note"] = "OI Change نیازمند Snapshot قبلی برای همین زنجیره است."

    return out


def volume_analytics(chain_df: pd.DataFrame) -> dict:
    out = {"status": "calculated", "total_volume": None, "call_volume": None, "put_volume": None, "note": None}
    if not chain_df["volume"].notna().any():
        out["status"] = "unavailable"
        out["note"] = "حجم معاملات در داده موجود نیست."
        return out
    calls = chain_df[chain_df["option_type"] == "call"]
    puts = chain_df[chain_df["option_type"] == "put"]
    out["total_volume"] = float(chain_df["volume"].sum())
    out["call_volume"] = float(calls["volume"].sum())
    out["put_volume"] = float(puts["volume"].sum())
    return out


def liquidity_analytics(chain_df: pd.DataFrame) -> dict:
    out = {"status": "calculated", "avg_spread_pct": None, "avg_volume": None,
           "avg_oi": None, "note": None}
    has_bid_ask = chain_df["bid"].notna().any() and chain_df["ask"].notna().any() if (
        "bid" in chain_df.columns and "ask" in chain_df.columns
    ) else False

    if has_bid_ask:
        valid = chain_df[(chain_df["bid"].notna()) & (chain_df["ask"].notna()) & (chain_df["close"] > 0)]
        if not valid.empty:
            spread_pct = (valid["ask"] - valid["bid"]) / valid["close"]
            out["avg_spread_pct"] = round(float(spread_pct.mean()) * 100, 2)
    else:
        out["note"] = "Bid/Ask در داده موجود نیست؛ Spread محاسبه نشد."

    if chain_df["volume"].notna().any():
        out["avg_volume"] = float(chain_df["volume"].mean())
    if chain_df["open_interest"].notna().any():
        out["avg_oi"] = float(chain_df["open_interest"].mean())

    if out["avg_volume"] is None and out["avg_oi"] is None and out["avg_spread_pct"] is None:
        out["status"] = "unavailable"

    return out


def data_quality_report(options_df: pd.DataFrame) -> dict:
    """گزارش کیفیت داده واقعی برای یک Dataset (بدون هیچ Score ساختگی)."""
    if options_df.empty:
        return {"rows": 0}

    fields_to_check = ["iv", "open_interest", "volume", "bid", "ask", "close"]
    missing = {}
    for f in fields_to_check:
        if f in options_df.columns:
            missing[f] = int(options_df[f].isna().sum())
        else:
            missing[f] = len(options_df)

    completeness = {
        f: round(100 * (1 - missing[f] / len(options_df)), 1) for f in fields_to_check
    }
    # Data Quality Score واقعی = میانگین درصد تکمیل‌بودن فیلدهای کلیدی
    quality_score = round(float(np.mean(list(completeness.values()))), 1)

    return {
        "rows": len(options_df),
        "underlyings": options_df["underlying"].nunique(),
        "contracts": options_df["symbol"].nunique() if "symbol" in options_df.columns else None,
        "snapshots": options_df["quote_date"].nunique(),
        "calls": int((options_df["option_type"] == "call").sum()),
        "puts": int((options_df["option_type"] == "put").sum()),
        "missing": missing,
        "completeness_pct": completeness,
        "quality_score": quality_score,
    }


# ---------------------------------------------------------------------------
# تحلیل تاریخی (بخش ۵۶ و ۵۷ Master Prompt) — Analytics بر خلاف Dashboard
# «سری زمانی» است، نه Snapshot.
# ---------------------------------------------------------------------------
def history_series(options_df: pd.DataFrame, underlying_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    یک ردیف به‌ازای هر Snapshot، با معیارهای تجمیعی بازار.

    اگر یک معیار در هیچ ردیفی داده نداشته باشد ستونش None می‌ماند تا UI
    بتواند به‌جای رسم نمودار صفر، صادقانه بگوید «قابل‌محاسبه نیست» (بخش ۵۷).
    """
    if options_df is None or options_df.empty:
        return pd.DataFrame()

    rows = []
    for qd, g in options_df.groupby("quote_date"):
        def agg(col, how="sum"):
            if col not in g.columns or g[col].dropna().empty:
                return None
            s = g[col].dropna()
            return float(s.sum() if how == "sum" else s.mean())

        call_v = g[g["option_type"] == "call"]["volume"].dropna() if "volume" in g.columns else pd.Series(dtype=float)
        put_v = g[g["option_type"] == "put"]["volume"].dropna() if "volume" in g.columns else pd.Series(dtype=float)
        cp = (float(call_v.sum()) / float(put_v.sum())
              if len(call_v) and len(put_v) and put_v.sum() > 0 else None)

        # تمرکز: سهم ۳ نماد برتر از حجم کل
        conc = None
        if "volume" in g.columns and g["volume"].notna().any():
            by_u = g.groupby("underlying")["volume"].sum().sort_values(ascending=False)
            tot = by_u.sum()
            if tot > 0 and len(by_u) >= 3:
                conc = float(by_u.head(3).sum() / tot * 100)

        rows.append({
            "quote_date": qd,
            "volume": agg("volume"),
            "open_interest": agg("open_interest"),
            "avg_iv": agg("iv", "mean"),
            "contracts": int(len(g)),
            "underlyings": int(g["underlying"].nunique()),
            "cp_ratio": cp,
            "top3_share": conc,
        })

    out = pd.DataFrame(rows).sort_values("quote_date").reset_index(drop=True)

    # HV بازار در هر تاریخ، با پنجره متحرک از تاریخچه قیمت پایه تا همان روز
    if underlying_df is not None and not underlying_df.empty:
        from core.market_brief import market_hv
        hvs = []
        for qd in out["quote_date"]:
            window = underlying_df[underlying_df["quote_date"] <= qd]
            hv, _ = market_hv(window)
            hvs.append(hv)
        out["hv"] = hvs
        out["iv_hv"] = [
            (iv / hv) if (iv is not None and hv) else None
            for iv, hv in zip(out["avg_iv"], out["hv"])
        ]
    else:
        out["hv"] = None
        out["iv_hv"] = None

    return out


def underlying_hv(underlying_hist: pd.DataFrame, underlying_name: str, min_points: int = MIN_SNAPSHOTS_FOR_HISTORY):
    """
    HV تک‌نماد (نه میانگین کل بازار مثل market_hv) — برای IV/HV سطح Contract.
    خروجی: hv (float) یا None اگر تاریخچه کافی نباشد.
    """
    if underlying_hist is None or underlying_hist.empty:
        return None
    g = underlying_hist[underlying_hist["underlying"] == underlying_name]
    g = g.dropna(subset=["close"]).sort_values("quote_date")
    g = g[g["close"] > 0]
    if len(g) < min_points:
        return None
    ret = np.log(g["close"].astype(float) / g["close"].astype(float).shift(1)).dropna()
    if len(ret) < min_points - 1:
        return None
    sd = ret.std(ddof=1)
    if pd.isna(sd) or sd <= 0:
        return None
    return float(sd) * np.sqrt(252)


def contract_iv_history(option_hist: pd.DataFrame, instrument_id=None, symbol=None,
                         exclude_quote_date=None) -> pd.Series:
    """
    سری تاریخی IV یک قرارداد مشخص در طول Snapshotهای ذخیره‌شده — برای IV
    Rank/Percentile سطح Contract. instrument_id در دسترس‌تر و پایدارتر است؛
    اگر نبود (مثلاً داده اکسل قدیمی)، symbol جایگزین می‌شود.

    exclude_quote_date: تاریخ Snapshot جاری که دارد امتیازدهی می‌شود — باید
    از «تاریخچه» حذف شود، وگرنه مقدار امروز در سری‌ای که خودش را با آن
    مقایسه می‌کند ظاهر می‌شود (نه Look-ahead، ولی خودـمقایسه‌ای بی‌معناست).
    """
    if option_hist is None or option_hist.empty or "iv" not in option_hist.columns:
        return pd.Series(dtype=float)
    if instrument_id and "instrument_id" in option_hist.columns and option_hist["instrument_id"].notna().any():
        sub = option_hist[option_hist["instrument_id"] == instrument_id]
    elif symbol and "symbol" in option_hist.columns:
        sub = option_hist[option_hist["symbol"] == symbol]
    else:
        return pd.Series(dtype=float)
    if exclude_quote_date is not None and "quote_date" in sub.columns:
        sub = sub[sub["quote_date"] != exclude_quote_date]
    return sub.sort_values("quote_date")["iv"].dropna()



def iv_percentile(series, current) -> dict:
    """
    جایگاه مقدار امروز در تاریخچه خودش.
    rank  = (current - min) / (max - min)
    pctl  = درصد روزهایی که مقدارشان کمتر از امروز بوده
    اگر داده کافی نباشد None برمی‌گردد، نه عدد گمراه‌کننده.
    """
    s = pd.Series(series).dropna()
    if current is None or len(s) < MIN_SNAPSHOTS_FOR_HISTORY:
        return {"rank": None, "percentile": None, "n": len(s),
                "note": f"حداقل {MIN_SNAPSHOTS_FOR_HISTORY} Snapshot لازم است."}
    lo, hi = float(s.min()), float(s.max())
    if hi == lo:
        rank = None
    else:
        raw = (float(current) - lo) / (hi - lo) * 100
        rank = float(max(0.0, min(100.0, raw)))  # Clamp صریح: بالاتر از تاریخچه=۱۰۰، پایین‌تر=۰
    pctl = float((s < float(current)).mean() * 100)
    return {"rank": rank, "percentile": pctl, "n": len(s), "note": None}


def oi_by_dimension(chain_df: pd.DataFrame, dimension: str, top_n: int = 8) -> pd.DataFrame:
    """توزیع موقعیت باز روی یک بُعد (underlying / expiry / option_type)."""
    if chain_df is None or chain_df.empty or "open_interest" not in chain_df.columns:
        return pd.DataFrame()
    if chain_df["open_interest"].dropna().empty or dimension not in chain_df.columns:
        return pd.DataFrame()
    out = (chain_df.groupby(dimension)["open_interest"].sum()
           .sort_values(ascending=False).head(top_n).reset_index())
    total = chain_df["open_interest"].dropna().sum()
    out["share_pct"] = out["open_interest"] / total * 100 if total > 0 else None
    return out
