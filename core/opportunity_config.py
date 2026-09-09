"""
core/opportunity_config.py

تمام وزن‌ها، آستانه‌ها و بندهای Grading در یک جا — طبق بخش ۲۷ سند
(«No magic numbers scattered through scoring functions»).
هر عددی که در گذشته داخل core/opportunity.py Hardcode بود، باید از
اینجا خوانده شود.
"""
from __future__ import annotations

# ============================================================
# بخش ۵: وزن‌های سطح Contract (شش بُعد واقعی)
# ============================================================
CONTRACT_WEIGHTS = {
    "liquidity": 0.25,
    "iv_value": 0.20,
    "relative_iv": 0.20,
    "oi_participation": 0.15,
    "premium_efficiency": 0.10,
    "breakeven_quality": 0.10,
}
assert abs(sum(CONTRACT_WEIGHTS.values()) - 1.0) < 1e-9

# بخش ۶: زیرمؤلفه‌های Liquidity & Execution
LIQUIDITY_SUBWEIGHTS = {
    "spread": 0.40,
    "volume": 0.25,
    "oi": 0.20,
    "depth": 0.15,
}
assert abs(sum(LIQUIDITY_SUBWEIGHTS.values()) - 1.0) < 1e-9

# بخش ۷: زیرمؤلفه‌های IV / Volatility Value
IV_VALUE_SUBWEIGHTS = {
    "iv_hv": 0.50,
    "iv_rank": 0.25,
    "iv_percentile": 0.25,
}
assert abs(sum(IV_VALUE_SUBWEIGHTS.values()) - 1.0) < 1e-9

# بخش ۹: زیرمؤلفه‌های OI / Participation Quality
OI_PARTICIPATION_SUBWEIGHTS = {
    "oi_level": 0.40,
    "oi_change_signal": 0.30,
    "volume_oi_ratio": 0.20,
    "volume_quality": 0.10,
}
assert abs(sum(OI_PARTICIPATION_SUBWEIGHTS.values()) - 1.0) < 1e-9

# ============================================================
# بخش ۱۵: وزن‌های سطح Strategy (فاز بعد پیاده‌سازی می‌شود)
# ============================================================
STRATEGY_WEIGHTS = {
    "expected_value": 0.25,
    "probability_of_profit": 0.20,
    "risk_reward": 0.20,
    "liquidity": 0.20,
    "iv_context": 0.10,
    "breakeven_quality": 0.05,
}
assert abs(sum(STRATEGY_WEIGHTS.values()) - 1.0) < 1e-9

STRATEGY_LIQUIDITY_SUBWEIGHTS = {"avg_leg": 0.60, "worst_leg": 0.40}

# مقیاس امتیاز خام «فعالیت» یک پایه (Volume+OI) در نبود اطلاعات اسپرد کافی
STRATEGY_LEG_ACTIVITY_SCALE = 50.0

# ============================================================
# بخش ۹، ۱۳: آستانه‌های Eligibility و کیفیت داده
# ============================================================
MIN_PEERS_FOR_RELATIVE_IV = 3        # بخش ۸: حداقل تعداد هم‌گروه معنادار
MIN_VOLUME_FOR_PARTICIPATION = 1     # کمتر از این یعنی مشارکت غیرقابل اتکا (نه صفر بودن Invalid)
MIN_OI_FOR_PARTICIPATION = 1
MAX_REASONABLE_SPREAD_PCT = 50.0     # بالاتر از این: Quote تک‌طرفه/غیرقابل استفاده تلقی می‌شود
MIN_DTE_FOR_ELIGIBILITY = 1          # DTE=0 یا منفی: قرارداد منقضی/بی‌معنا برای Opportunity
MAX_DTE_ANNUALIZE_FLOOR_DAYS = 3     # برای جلوگیری از Annualized Yield کاذب در DTEهای خیلی کوتاه

# ============================================================
# Contract Size — بخش ۲، ۷، ۲۵ سند
# ============================================================
# قرارداد اختیار معامله بورس ایران به‌صورت استاندارد شامل ۱۰۰۰ واحد است.
# این مقدار فقط Fallback است؛ اگر Provider (TSETMC) مقدار معتبر contract_size
# داشته باشد، همیشه بر این عدد اولویت دارد (core/strategy.py این ترتیب را
# در ساخت هر Leg رعایت می‌کند).
DEFAULT_CONTRACT_SIZE = 1000.0

# بخش ۵ سند: Position Sizing
DEFAULT_ACCOUNT_CAPITAL = 100_000_000.0   # ۱۰۰ میلیون ریال - فقط پیش‌فرض UI، کاربر تغییر می‌دهد
DEFAULT_RISK_BUDGET_PCT = 2.0             # ٪ از سرمایه که کاربر حاضر است در یک استراتژی به خطر بیندازد

# بخش ۱۲: بندهای امتیاز مطلق (Absolute Quality) برای اسپرد (٪) — پایین‌تر بهتر
SPREAD_ABSOLUTE_BANDS = [
    (2.0, 100), (5.0, 85), (10.0, 65), (20.0, 40), (35.0, 20), (float("inf"), 0),
]

# بخش ۱۸: نگاشت Risk/Reward به امتیاز (Diminishing Returns، نه خطی نامحدود)
RISK_REWARD_BANDS = [
    (0.5, 20), (1.0, 50), (1.5, 70), (2.0, 85), (2.5, 100), (float("inf"), 100),
]

# بخش ۱۱، ۱۸: نسبت «حرکت موردانتظار / حرکت موردنیاز تا سربه‌سر» به امتیاز
# (هم برای Contract و هم برای Strategy استفاده می‌شود - همان مفهوم است)
BREAKEVEN_RATIO_BANDS = [
    (0.3, 15), (0.6, 35), (1.0, 55), (1.5, 75), (2.5, 90), (float("inf"), 100),
]
BREAKEVEN_ALREADY_MET_RATIO = 5.0  # وقتی سربه‌سر از قبل محقق شده (فاصله صفر/منفی)

# بخش ۷: مقیاس امتیازدهی به اندازه انحراف IV از HV
IV_HV_DEVIATION_SCALE = 80.0

# بخش ۱۵، ۱۶ سند: امتیازدهی جهت‌دار IV (نه صرفاً اندازه‌ی انحراف) — IV
# ارزان‌تر باید امتیاز بالاتر و IV گران‌تر امتیاز پایین‌تر بگیرد، نه اینکه
# |انحراف| هر دو جهت را یکسان «خوب» نشان دهد.
DIRECTIONAL_SCORE_MIDPOINT = 50.0

# بخش ۸: آستانه‌های تشخیص «نسبتاً ارزان/گران» بودن IV نسبت به هم‌گروه
RELATIVE_IV_CHEAP_THRESHOLD = -0.10
RELATIVE_IV_EXPENSIVE_THRESHOLD = 0.10
RELATIVE_IV_SCORE_SCALE = 200.0

# بخش ۹: مقیاس امتیازدهی به اندازه تغییر OI
OI_CHANGE_SCORE_SCALE = 2.0

# بخش ۱۲: آستانه‌های تگ‌گذاری دسته‌ها (Categories) در Contract Opportunities
CATEGORY_HIGH_LIQUIDITY = 75
CATEGORY_HIGH_IV_RANK = 80
CATEGORY_LOW_IV_RANK = 20
CATEGORY_HIGH_OI = 80
CATEGORY_OI_BUILDUP_PCT = 25
CATEGORY_OI_UNWIND_PCT = -25

# آستانه‌های تولید متن Why/Risks سطح Contract
LOW_LIQUIDITY_RISK_THRESHOLD = 20
WIDE_SPREAD_RISK_PCT = 15
THETA_DECAY_WARNING_RATIO = 0.02       # |theta|/close بیشتر از این یعنی فرسایش زمانی قابل‌توجه
GOOD_BREAKEVEN_RATIO_FOR_WHY = 1.5

# بخش ۲۰: بندهای IV Context جهت‌دار سطح Strategy (نسبت IV/HV)
STRATEGY_IV_CONTEXT_BANDS_LOW_GOOD = [
    (0.7, 100), (0.9, 80), (1.1, 55), (1.3, 30), (float("inf"), 10),
]
STRATEGY_IV_CONTEXT_BANDS_HIGH_GOOD = [
    (0.7, 10), (0.9, 30), (1.1, 55), (1.3, 80), (float("inf"), 100),
]
IV_CONTEXT_CHEAP_THRESHOLD = 0.9
IV_CONTEXT_EXPENSIVE_THRESHOLD = 1.1

# آستانه‌های تولید متن Why/Risks سطح Strategy
STRAT_RR_GOOD_THRESHOLD = 70
STRAT_POP_GOOD_THRESHOLD = 0.6
STRAT_POP_BAD_THRESHOLD = 0.4
STRAT_LIQUIDITY_GOOD_THRESHOLD = 60
STRAT_WORST_LEG_BAD_THRESHOLD = 25
STRAT_IV_CONTEXT_GOOD_THRESHOLD = 60
EXPECTED_VALUE_SCORE_MIDPOINT = 50.0
EXPECTED_VALUE_SCORE_SCALE = 50.0
STRAT_LOW_CAPACITY_UNITS_THRESHOLD = 5

# بخش ۲۳: بندهای Grade (روی Score نهایی، مستقل از Coverage)
GRADE_BANDS = [
    (85, "A"), (70, "B"), (55, "C"), (40, "D"), (0, "F"),
]

# بخش ۱۴، ۲۳: سطح Confidence بر اساس Coverage (نه بخشی از خود Score)
def confidence_from_coverage(coverage_pct: float) -> str:
    if coverage_pct is None:
        return "Unknown"
    if coverage_pct >= 85:
        return "High"
    if coverage_pct >= 60:
        return "Moderate"
    if coverage_pct >= 35:
        return "Low"
    return "Very Low"


def grade_from_score(score: float) -> str:
    if score is None:
        return "N/A"
    for threshold, label in GRADE_BANDS:
        if score >= threshold:
            return label
    return "F"


def band_score(value: float, bands: list, higher_is_better: bool = False) -> float:
    """
    نگاشت یک مقدار خام به امتیاز ۰-۱۰۰ بر اساس بندهای پله‌ای (بخش ۱۸، ۱۲).
    bands: لیستی صعودی از (آستانه, امتیاز).
    - higher_is_better=False (پیش‌فرض؛ مثل Spread%): اولین آستانه‌ای که value
      ازش کمتر/مساوی است، امتیازش را می‌دهد (بند پایین = بهترین).
    - higher_is_better=True (مثل Risk/Reward): بالاترین آستانه‌ای که value
      بهش رسیده/بیشتره را پیدا می‌کند (بند بالا = بهترین) — باید از انتها
      پیمایش شود، وگرنه اولین (کوچک‌ترین) آستانه به‌اشتباه برنده می‌شود.
    """
    if value is None:
        return None
    if higher_is_better:
        for threshold, score in reversed(bands):
            if value >= threshold:
                return float(score)
        return float(bands[0][1])
    for threshold, score in bands:
        if value <= threshold:
            return float(score)
    return float(bands[-1][1])
