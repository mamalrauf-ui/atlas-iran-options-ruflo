"""
موتور استراتژی - محاسبه Payoff، سود/زیان حداکثر، نقاط سربه‌سر و
احتمال سودآوری (POP) برای یک استراتژی چندپایه (Multi-leg).

Contract Size (بخش ۲، ۷، ۸، ۹ سند): در بازار اختیار معامله ایران هر قرارداد
شامل ۱۰۰۰ واحد اختیار است. تمام محاسبات اقتصادی (Premium، Payoff، Max
Profit/Loss، Expected Value) باید:

    Economic P&L = Payoff per Option Unit × Contract Size × Quantity

باشند، نه اینکه «۱ Contract» را «۱ Option Unit» فرض کنند. Contract Size از
داده Provider می‌آید (اگر معتبر بود) و فقط در نبود آن، Fallback=۱۰۰۰
(core/opportunity_config.DEFAULT_CONTRACT_SIZE) استفاده می‌شود — هرگز برعکس.
"""
from dataclasses import dataclass
import numpy as np

from core.opportunity_config import DEFAULT_CONTRACT_SIZE


@dataclass
class Leg:
    """
    یک پایه از استراتژی.

    option_type:
        'call' / 'put' — قرارداد اختیار.
        'stock'        — خودِ دارایی پایه. برای Covered Call و Collar لازم است،
                         چون بدون آن «فروش Call» یک موقعیت برهنه با زیان
                         نامحدود به نظر می‌رسد، در حالی که با مالکیت سهم،
                         زیان کراندار است.
    برای پایه سهام:
        premium = قیمت خرید/فروش هر سهم
        strike  = بی‌معناست و نادیده گرفته می‌شود (برای سازگاری، همان premium)
        contract_size = همیشه ۱ (یک سهم یک واحد است؛ ضریب ۱۰۰۰ فقط برای
                        قراردادهای اختیار معنا دارد).

    contract_size: تعداد واحد اختیار در هر قرارداد (Provider اگر معتبر بود،
        وگرنه Fallback=۱۰۰۰). این تنها منبع حقیقت Contract Size در کل مسیر
        محاسباتی است — از چند منبع مستقل برایش استفاده نکنید (بخش ۷ سند).
    """
    option_type: str   # 'call' | 'put' | 'stock'
    side: str           # 'buy' یا 'sell'
    strike: float
    premium: float       # قیمت هر واحد اختیار (یا هر سهم برای پایه سهام)
    qty: int = 1          # تعداد قرارداد (نه تعداد واحد اختیار خام)
    contract_size: float = DEFAULT_CONTRACT_SIZE

    def __post_init__(self):
        if self.option_type == "stock":
            self.contract_size = 1.0  # هر سهم = ۱ واحد؛ ضریب قرارداد اختیار اینجا بی‌معناست

    @property
    def is_stock(self) -> bool:
        return self.option_type == "stock"

    @property
    def multiplier(self) -> float:
        """qty (تعداد قرارداد) × contract_size (واحد در هر قرارداد) = کل واحدهای اقتصادی."""
        return self.qty * self.contract_size

    def payoff_at_expiry(self, S):
        """Economic P&L این پایه (Payoff per Unit × Contract Size × Quantity)."""
        if self.is_stock:
            pnl_per_unit = S - self.premium
        else:
            intrinsic = (max(0.0, S - self.strike) if self.option_type == "call"
                         else max(0.0, self.strike - S))
            pnl_per_unit = intrinsic - self.premium
        sign = 1 if self.side == "buy" else -1
        return sign * pnl_per_unit * self.multiplier


def net_premium(legs):
    """
    خالص دریافتی/پرداختی هنگام ورود (Credit مثبت، Debit منفی) — به‌صورت
    اقتصادی کامل (Contract Size × Quantity لحاظ شده، نه فقط قیمت هر واحد).
    """
    total = 0.0
    for leg in legs:
        sign = -1 if leg.side == "buy" else 1  # buy = پرداخت، sell = دریافت
        total += sign * leg.premium * leg.multiplier
    return total


def payoff_curve(legs, price_range):
    """
    Payoff اقتصادی کل استراتژی (نه فقط per-unit) روی یک بازه از قیمت‌های
    دارایی پایه در سررسید — Contract Size و Quantity هر پایه لحاظ شده‌اند.

    نسخه برداری‌شده (Vectorized): ریاضیات دقیقاً همان Leg.payoff_at_expiry است،
    فقط به‌جای حلقه پایتون روی هزاران قیمت، یک‌بار روی هر پایه با numpy محاسبه
    می‌شود. این برای اسکن استراتژی روی کل بازار حیاتی است (۲۰۰۰ قیمت × چند پایه
    × ده‌ها قالب × ده‌ها نماد).
    """
    S = np.asarray(price_range, dtype=float)
    total = np.zeros_like(S)
    for leg in legs:
        if getattr(leg, "option_type", None) == "stock":
            pnl = S - leg.premium
        elif leg.option_type == "call":
            pnl = np.maximum(0.0, S - leg.strike) - leg.premium
        else:
            pnl = np.maximum(0.0, leg.strike - S) - leg.premium
        sign = 1 if leg.side == "buy" else -1
        total += sign * pnl * leg.multiplier
    return total


def max_profit_loss(legs, S_ref, width_factor=3.0, steps=2000):
    """
    برآورد سود/زیان حداکثر با اسکن یک بازه وسیع قیمتی حول قیمت فعلی.
    برای استراتژی‌های با ریسک نامحدود (مثل Naked Call فروخته‌شده)، سود/زیان
    در انتهای بازه به‌عنوان تقریبی از "نامحدود" گزارش می‌شود.
    """
    low = max(0.01, S_ref * (1 - width_factor))
    high = S_ref * (1 + width_factor)
    prices = np.linspace(low, high, steps)
    payoffs = payoff_curve(legs, prices)

    max_p = payoffs.max()
    min_p = payoffs.min()

    # اگر Payoff در انتهای بازه (بالاترین قیمت) همچنان رو به افزایش/کاهش باشد،
    # یعنی سود یا زیان عملاً نامحدود است (مثلاً Call فروخته‌شده بدون پوشش)
    unbounded_profit = payoffs[-1] > payoffs[-2]
    unbounded_loss = payoffs[-1] < payoffs[-2]

    return {
        "max_profit": float(max_p) if not unbounded_profit else None,
        "max_loss": float(min_p) if not unbounded_loss else None,
        "max_profit_is_unbounded": bool(unbounded_profit),
        "max_loss_is_unbounded": bool(unbounded_loss),
    }


def breakevens(legs, S_ref, width_factor=3.0, steps=5000):
    """پیدا کردن نقاط سربه‌سر با جستجوی تغییر علامت روی منحنی Payoff."""
    low = max(0.01, S_ref * (1 - width_factor))
    high = S_ref * (1 + width_factor)
    prices = np.linspace(low, high, steps)
    payoffs = payoff_curve(legs, prices)

    points = []
    for i in range(len(prices) - 1):
        p1, p2 = payoffs[i], payoffs[i + 1]
        if p1 == 0:
            points.append(prices[i])
        elif p1 * p2 < 0:
            # درون‌یابی خطی برای تقریب دقیق‌تر نقطه صفر
            frac = -p1 / (p2 - p1)
            points.append(prices[i] + frac * (prices[i + 1] - prices[i]))
    return sorted(set(round(p, 2) for p in points))


def simulate_outcome(legs, S0, sigma, T_years, r=0.20, n_sims=20000, seed=42):
    """
    یک شبیه‌سازی واحد GBM که هم POP و هم Expected Value را از همان مسیرهای
    شبیه‌سازی‌شده برمی‌گرداند (بخش ۱۶ سند: «Do not rely only on POP» + سازگاری
    کامل بین این دو عدد، چون از یک منبع تصادفی با seed ثابت می‌آیند).

    خروجی: dict با pop, expected_value, std, n_sims, seed - برای مستندسازی
    کامل مفروضات شبیه‌سازی (بخش ۱۷ سند).
    """
    if T_years <= 0 or sigma <= 0:
        return {"pop": None, "expected_value": None, "std": None,
                "n_sims": n_sims, "seed": seed}
    rng = np.random.default_rng(seed)
    Z = rng.standard_normal(n_sims)
    ST = S0 * np.exp((r - 0.5 * sigma ** 2) * T_years + sigma * np.sqrt(T_years) * Z)
    payoffs = payoff_curve(legs, ST)
    return {
        "pop": float((payoffs > 0).mean()),
        "expected_value": float(payoffs.mean()),
        "std": float(payoffs.std(ddof=1)) if n_sims > 1 else None,
        "n_sims": n_sims, "seed": seed,
    }


def probability_of_profit(legs, S0, sigma, T_years, r=0.20, n_sims=20000, seed=42):
    """
    برآورد POP با شبیه‌سازی Monte Carlo تحت حرکت هندسی براونی (GBM) —
    همان رویکردی که در ابزارهایی مثل poptions استفاده می‌شود، اما پیاده‌سازی
    ساده و مستقل با numpy. (نگه‌داشته شده برای سازگاری با کدهای موجود؛
    برای POP+Expected Value با هم از simulate_outcome استفاده کنید.)
    """
    return simulate_outcome(legs, S0, sigma, T_years, r, n_sims, seed)["pop"]


PRESET_STRATEGIES = {
    "Long Call": lambda K, prem: [Leg("call", "buy", K, prem)],
    "Long Put": lambda K, prem: [Leg("put", "buy", K, prem)],
    "Covered Call (فرض تصاحب دارایی پایه جدا)": lambda K, prem: [Leg("call", "sell", K, prem)],
    "Bull Call Spread": lambda K1, p1, K2, p2: [Leg("call", "buy", K1, p1), Leg("call", "sell", K2, p2)],
    "Bear Put Spread": lambda K1, p1, K2, p2: [Leg("put", "buy", K1, p1), Leg("put", "sell", K2, p2)],
    "Straddle": lambda K, pc, pp: [Leg("call", "buy", K, pc), Leg("put", "buy", K, pp)],
    "Strangle": lambda Kc, pc, Kp, pp: [Leg("call", "buy", Kc, pc), Leg("put", "buy", Kp, pp)],
    "Iron Condor": lambda Kp1, pp1, Kp2, pp2, Kc1, pc1, Kc2, pc2: [
        Leg("put", "buy", Kp1, pp1),
        Leg("put", "sell", Kp2, pp2),
        Leg("call", "sell", Kc1, pc1),
        Leg("call", "buy", Kc2, pc2),
    ],
}


# ---------------------------------------------------------------------------
# قالب‌های استراتژی برای صفحه «ساخت استراتژی» - هر قالب لیستی از "نقش" پایه‌هاست:
# نوع (call/put)، جهت (buy/sell)، تعداد پیش‌فرض، و ترجیح انتخاب پیش‌فرض Strike
# (rank): "atm" نزدیک‌ترین به قیمت فعلی، "otm" اولین Strike خارج از سود بعد از
# ATM، "far_otm" یک پله دورتر از آن (برای پایه‌های پوششی در Iron Condor/Butterfly).
# کاربر همیشه می‌تواند این پیشنهاد پیش‌فرض را از یک لیست کشویی از قراردادهای
# واقعی موجود در داده تغییر دهد.
# ---------------------------------------------------------------------------
STRATEGY_TEMPLATES = {
    "Long Call (خرید اختیار خرید)": [
        {"option_type": "call", "side": "buy", "qty": 1, "rank": "atm"},
    ],
    "Long Put (خرید اختیار فروش)": [
        {"option_type": "put", "side": "buy", "qty": 1, "rank": "atm"},
    ],
    # Covered Call واقعی: مالکیت سهم + فروش Call. بدون پایه سهام، این موقعیت
    # یک Naked Call با زیان نامحدود است که تصویر ریسک را کاملاً غلط نشان می‌دهد.
    "Covered Call (خرید سهم + فروش Call)": [
        {"option_type": "stock", "side": "buy", "qty": 1},
        {"option_type": "call", "side": "sell", "qty": 1, "rank": "otm"},
    ],
    "Naked Call (فروش Call بدون پوشش)": [
        {"option_type": "call", "side": "sell", "qty": 1, "rank": "otm"},
    ],
    "Protective Put (خرید Put برای پوشش - با فرض مالکیت جدا از دارایی پایه)": [
        {"option_type": "put", "side": "buy", "qty": 1, "rank": "otm"},
    ],
    "Bull Call Spread (اسپرد صعودی با Call)": [
        {"option_type": "call", "side": "buy", "qty": 1, "rank": "atm"},
        {"option_type": "call", "side": "sell", "qty": 1, "rank": "otm"},
    ],
    "Bear Call Spread (اسپرد نزولی اعتباری با Call)": [
        {"option_type": "call", "side": "sell", "qty": 1, "rank": "atm"},
        {"option_type": "call", "side": "buy", "qty": 1, "rank": "otm"},
    ],
    "Bull Put Spread (اسپرد صعودی اعتباری با Put)": [
        {"option_type": "put", "side": "sell", "qty": 1, "rank": "atm"},
        {"option_type": "put", "side": "buy", "qty": 1, "rank": "otm"},
    ],
    "Bear Put Spread (اسپرد نزولی با Put)": [
        {"option_type": "put", "side": "buy", "qty": 1, "rank": "atm"},
        {"option_type": "put", "side": "sell", "qty": 1, "rank": "otm"},
    ],
    "Long Straddle (خرید هم‌زمان Call و Put هم‌قیمت)": [
        {"option_type": "call", "side": "buy", "qty": 1, "rank": "atm"},
        {"option_type": "put", "side": "buy", "qty": 1, "rank": "atm"},
    ],
    "Long Strangle (خرید Call و Put با Strike متفاوت)": [
        {"option_type": "call", "side": "buy", "qty": 1, "rank": "otm"},
        {"option_type": "put", "side": "buy", "qty": 1, "rank": "otm"},
    ],
    "Iron Condor": [
        {"option_type": "put", "side": "buy", "qty": 1, "rank": "far_otm"},
        {"option_type": "put", "side": "sell", "qty": 1, "rank": "otm"},
        {"option_type": "call", "side": "sell", "qty": 1, "rank": "otm"},
        {"option_type": "call", "side": "buy", "qty": 1, "rank": "far_otm"},
    ],
    "Iron Butterfly": [
        {"option_type": "put", "side": "buy", "qty": 1, "rank": "far_otm"},
        {"option_type": "put", "side": "sell", "qty": 1, "rank": "atm"},
        {"option_type": "call", "side": "sell", "qty": 1, "rank": "atm"},
        {"option_type": "call", "side": "buy", "qty": 1, "rank": "far_otm"},
    ],
    "Collar (خرید سهم + Put حمایتی + فروش Call)": [
        {"option_type": "stock", "side": "buy", "qty": 1},
        {"option_type": "put", "side": "buy", "qty": 1, "rank": "otm"},
        {"option_type": "call", "side": "sell", "qty": 1, "rank": "otm"},
    ],
    "ترکیب سفارشی (خودم قرارداد اضافه می‌کنم)": None,
}
