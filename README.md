# ATLAS — Iran Options Intelligence

موتور تحلیل و تصمیم‌یار بازار اختیار معامله ایران. ATLAS صرفاً یک Viewer برای
داده TSETMC نیست؛ داده خام بازار را می‌گیرد و خودش IV، Greeks، نقدشوندگی،
فرصت‌های معاملاتی و بک‌تست را محاسبه می‌کند.

## اجرا

```bash
pip install -r requirements.txt
streamlit run app.py
```

## شروع سریع

۱. به **مرکز داده** بروید، تب **«دریافت بازار (TSETMC)»** (پیش‌فرض و اصلی).
۲. دامنه دریافت (یک دارایی پایه یا کل بازار) و نام یک مجموعه (Dataset) را انتخاب و
   **«دریافت و پیش‌نمایش»** را بزنید، سپس **«تأیید و ذخیره»**.
۳. به **داشبورد**، **فرصت‌ها** یا **زنجیره اختیار** بروید.

اگر TSETMC در دسترس نبود یا داده‌ای خارج از پوششش دارید، تب **«ورود دستی
(اضطراری)»** همان Excel Importer قبلی را نگه داشته — ولی دیگر مسیر پیش‌فرض
نیست.

## منابع داده (Provider Architecture)

| Provider | نقش | وضعیت |
|---|---|---|
| **TSETMC** (`core/live_data.py`, `core/data/providers/tsetmc.py`) | Primary — بازار لحظه‌ای/EOD | با داده واقعی تست شده |
| **fima** (`core/data/providers/fima.py`) | تاریخچه قیمت/حجم هر قرارداد (نه OI) | پیاده‌سازی شده، تست شبکه واقعی هنوز نیاز است |
| **Excel** (`core/importer.py`) | دستی/اضطراری | حفظ شده، از مسیر اصلی خارج شده |

هیچ صفحه UI مستقیماً به API یک Provider وصل نیست؛ همه از پشت
`core/data/snapshot.py` (اعتبارسنجی) و `core/data/sync.py` (ثبت در
`sync_log`) عبور می‌کنند.

### محدودیت واقعی Historical Data (شواهد، نه فرض)

- قیمت/حجم/تعداد معامله **تاریخی هر قرارداد** از TSETMC/fima قابل‌دریافت است.
- **Open Interest تاریخی در هیچ Endpoint رسمی TSETMC وجود ندارد.** از لحظه‌ی
  فعال‌شدن دریافت زنده به بعد، ATLAS خودش با ذخیره Snapshotهای روزانه این
  تاریخچه را می‌سازد (`previous_open_interest`, `oi_change`) — نه با Backfill.

## Data Integrity

- **Missing ≠ Zero.** هر مقدار غایب `None`/`NaN` می‌ماند، هرگز صفر یا تخمین
  جایگزین آن نمی‌شود (`core/schema.py`, `core/data/validator.py`).
- **Source Tracking.** هر ردیف `source` (`TSETMC_LIVE`/`EXCEL_IMPORT`/...) و
  `data_quality` (`LIVE`/`IMPORTED`/`CALCULATED`/...) دارد.
- **Duplicate/Validation Gate.** قبل از ذخیره، `core/data/validator.py`
  ردیف‌های نامعتبر (Strike کمتر مساوی صفر، نوع نامعتبر، سررسید قبل از Quote Date، تکراری) را
  رد می‌کند و در گزارش Sync مشخص می‌شود — نه Silent.

## Opportunity Engine v2

موتور فرصت قدیمی (`risk_reward`/`probability`/`momentum` همیشه `None` در سطح
Contract) کاملاً بازطراحی شد. **Contract** و **Strategy** حالا دو مدل امتیازدهی
کاملاً مستقل دارند (`core/opportunity_config.py` برای همه وزن‌ها/آستانه‌ها —
بدون عدد جادویی پراکنده در کد).

### Contract Opportunity (۶ بُعد)

| بُعد | وزن | بر چه چیزی |
|---|---|---|
| Liquidity & Execution | ۲۵٪ | اسپرد، حجم، OI، عمق سفارش |
| IV / Volatility Value | ۲۰٪ | IV/HV، IV Rank، IV Percentile (per-contract) |
| Relative IV Value | ۲۰٪ | انحراف IV از میانه هم‌گروه هم‌سطح Moneyness (حداقل ۳ هم‌گروه) |
| OI / Participation Quality | ۱۵٪ | سطح OI، تغییر OI (فقط جاری، نه Historical)، نسبت Volume/OI |
| Premium Efficiency | ۱۰٪ | ارزش زمانی روزانه نسبت به حق بیمه، با کف DTE (بدون پاداش کاذب DTE کوتاه) |
| Breakeven / Moneyness Quality | ۱۰٪ | نسبت حرکت موردانتظار (بر مبنای نوسان) به حرکت موردنیاز تا سربه‌سر |

قبل از امتیازدهی، **Eligibility Gate** قراردادهای بی‌کیفیت (بدون Volume/OI،
Quote نامعتبر، اسپرد غیرمنطقی، DTE نامعتبر) را کاملاً کنار می‌گذارد — امتیاز
پایین نمی‌گیرند، اصلاً امتیازدهی نمی‌شوند.

### Strategy Opportunity (۶ بُعد، مستقل از Contract)

| بُعد | وزن |
|---|---|
| Expected Value (از همان شبیه‌سازی Monte Carlo، نه جدا) | ۲۵٪ |
| Probability of Profit | ۲۰٪ |
| Risk/Reward (بندی پله‌ای، نه خطی نامحدود) | ۲۰٪ |
| Liquidity (میانگین پایه‌ها + بدترین پایه، ۶۰/۴۰) | ۲۰٪ |
| IV Context (جهت‌دار: Long Premium vs Short Premium) | ۱۰٪ |
| Breakeven Quality | ۵٪ |

`core/strategy.py: simulate_outcome()` یک شبیه‌سازی GBM با `seed=42` ثابت اجرا
می‌کند و POP و Expected Value را از همان مسیرها برمی‌گرداند — کاملاً Deterministic.

### Coverage / Confidence / Grade

هر Opportunity (Contract یا Strategy) این‌ها را دارد:

```
Score: 76.1
Coverage: 75%      چند درصد وزن کل واقعاً محاسبه‌پذیر بود
Confidence: Moderate
Grade: B
```

وزن مؤلفه‌های غایب حذف و بین مؤلفه‌های موجود Re-normalize می‌شود
(`opportunity._renormalize`) — هرگز صفر نمی‌شوند.

## ساختار

```
app.py                       Router

core/
  schema.py                  Canonical Data Model + وضعیت‌های کیفیت داده
  live_data.py                Client مستقیم API رسمی TSETMC
  providers.py                Registry سبک Provider (سازگاری قدیم)
  data/
    providers/{base,tsetmc,fima}.py   Provider Interface + پیاده‌سازی‌ها
    historical.py              سقف تاریخی ۱۴۰۵/۰۱/۰۱ + Sync تدریجی
    normalizer.py               یکدست‌سازی/Dedup ستون‌ها
    validator.py                اعتبارسنجی Context-Aware قبل از ذخیره
    quality.py                  Data Quality Score
    snapshot.py / sync.py       ذخیره + ثبت Sync Log
  opportunity_config.py        همه وزن‌ها/آستانه‌ها/بندهای Grading (متمرکز)
  opportunity.py                Contract + Strategy Opportunity Engine (v2)
  pricing.py                   Black-Scholes، Greeks، IV (Brent Solver)
  strategy.py                  Payoff، سربه‌سر، POP + Expected Value (Monte Carlo)
  backtest.py                  شبیه‌سازی تاریخی
  analytics.py                 IV/HV تاریخی، IV Rank/Percentile per-contract
  scanner.py                   فیلترها و Presetها
  importer.py                  Excel — مسیر دستی/اضطراری
  database.py                  SQLite + Migration تدریجی + sync_log

ui/                           نمایش — هیچ محاسبه مالی
tests/                        ۱۲ فایل تست + ۲ اسکریپت راستی‌آزمایی
```

## Contract Size، Position Sizing و رفع باگ‌های مالی حساس

این فاز روی صحت اقتصادی محاسبات استراتژی تمرکز داشت:

- **Contract Size واقعاً در همه‌جا اعمال می‌شود.** قبلاً `core/strategy.py`
  کاملاً «Per Unit» محاسبه می‌کرد (انگار هر قرارداد فقط ۱ واحد اختیار
  است)، در حالی که هر قرارداد بورس ایران معمولاً ۱۰۰۰ واحد است. حالا
  `Leg.contract_size` این ضریب را در Premium، Payoff، حداکثر سود/زیان و
  Expected Value اعمال می‌کند — با اولویت مقدار واقعی Provider و
  Fallback=۱۰۰۰ فقط در نبودش (`core/opportunity_config.DEFAULT_CONTRACT_SIZE`).
- **Position Sizing واقعی.** صفحه Strategy Lab حالا «تعداد واحد پیشنهادی»
  را از روی بودجه ریسک کاربر و حداکثر زیان واقعی هر واحد محاسبه می‌کند —
  نه یک عدد ثابت. برای ریسک نامحدود/نامشخص، عمداً چیزی نشان داده نمی‌شود.
- **Liquidity Capacity.** برای هر استراتژی مشخص می‌شود چند واحد از آن
  واقعاً با نقدشوندگی فعلی بازار (کم‌نقدترین پایه) قابل‌اجراست.
- **باز کردن در Strategy Lab اصلاح شد.** قبلاً فقط پایه اول یک استراتژی
  چندپایه منتقل می‌شد و بقیه باید دستی بازسازی می‌شدند. الان همه پایه‌ها
  با Strike/جهت/تعداد دقیق منتقل و همان قالب (نه «ترکیب دستی») خودکار
  انتخاب می‌شود.
- **باگ Expected Value.** کد قبلی `if ... and credit:` بود که Credit=۰
  (اسپرد کاملاً متوازن) را به‌اشتباه «داده غایب» تلقی می‌کرد. اصلاح شد
  به بررسی صریح `is not None`.
- **جهت‌دار شدن IV/Volatility Value و Relative IV.** قبلاً `|انحراف|`
  استفاده می‌شد که IV ارزان و گران را یکسان «خوب» نشان می‌داد. حالا IV
  ارزان‌تر امتیاز بالاتر و گران‌تر امتیاز پایین‌تر می‌گیرد.
- **IV Rank اکنون به بازه ۰-۱۰۰ Clamp می‌شود** (قبلاً می‌توانست منفی یا
  بیش از ۱۰۰ شود).
- **Preview و Save همیشه دقیقاً یک داده‌اند.** قبلاً دکمه «ذخیره» یک
  دریافت تازه از TSETMC انجام می‌داد که می‌توانست با چیزی که در Preview
  دیده بودید فرق کند. الان همان DataFrame پیش‌نمایش مستقیماً ذخیره می‌شود.
- **Duplicate Protection واقعی در Database.** هم در سطح برنامه (ذخیره
  مجدد همان روز جایگزین می‌کند، تکرار نمی‌کند) و هم یک Unique Index در
  خود SQLite (با پاک‌سازی امن تکراری‌های احتمالی قدیمی قبل از ساخت Index).

## اصول

- **محاسبه در core، نمایش در ui.** هیچ فرمول مالی در فایل‌های صفحه نیست.
- **عدد ساختگی ممنوع.** داده غایب خالی/None می‌ماند؛ هرگز صفر یا تقریب نمی‌شود.
- **Contract جدا از Strategy.** دو مدل امتیازدهی کاملاً مجزا، بدون به‌اشتراک‌گذاری
  مفهوم نامعتبر (مثل POP در سطح یک قرارداد تنها).
- **IV/Greeks همیشه توسط خود ATLAS محاسبه می‌شوند** (Black-Scholes + Brent)،
  نه از هیچ Providerی وارداتی — مگر برای Excel که IV وارد شده را با برچسب
  IMPORTED نگه می‌دارد.
- **Manual Refresh فقط.** هیچ Auto-Polling/Live-Streaming دائمی وجود ندارد.

## تست

```bash
# راستی‌آزمایی عمومی
python3 tests/verify_dashboard.py
python3 tests/verify_deep.py

# Data Pipeline (Provider -> Validate -> Snapshot -> Database -> Sync Log)
python3 tests/test_live_data.py
python3 tests/test_fima_provider.py
python3 tests/test_data_pipeline.py

# Opportunity Engine v2 (End-to-End + پوشش کامل هر مؤلفه به‌تفکیک)
python3 tests/test_opportunity_v2.py
python3 tests/test_strategy_opportunity_v2.py
python3 tests/test_opportunity_full_coverage.py

# Contract Size + Position Sizing + Liquidity Capacity
python3 tests/test_contract_size_and_sizing.py

# UI Smoke (رندر واقعی صفحات، نه فقط منطق Core)
python3 tests/test_ui_smoke.py

# سایر
python3 tests/test_backtest.py
python3 tests/test_chain.py
python3 tests/test_import.py
python3 tests/test_payoff.py
python3 tests/test_pop.py
python3 tests/test_stock_leg.py
```

## محدودیت‌های شناخته‌شده (پنهان نشده)

- **fima روی شبکه واقعی تست نشده** (محیط توسعه به cdn.tsetmc.com دسترسی
  ندارد). منطق نگاشت از خواندن مستقیم کد fima نوشته شده، نه حدس، ولی قبل از
  اعتماد کامل باید یک‌بار با داده واقعی امتحان شود.
- **Fallback خودکار TSETMC و fima ساخته نشده.** هرکدام مستقل صدا زده می‌شوند.
- **IV Rank/Percentile per-contract تقریباً همیشه «تاریخچه ناکافی»
  است** چون تاریخچه فقط از روزی که Live Sync فعال شد جمع می‌شود — منتظره،
  نه باگ.
- **Historical OI به‌صورت ذاتی فقط از امروز به بعد قابل ساخت است** (نه
  Backfill به گذشته) — چون هیچ منبع رسمی OI تاریخی ندارد.
- بک‌تست: مالیات، لغزش قیمت و اثر نقدشوندگی مدل نشده‌اند.
- **Execution Price همیشه Close است.** انتخاب هوشمند بین Mid/Bid/Ask/Last/Close
  بر مبنای کیفیت Quote هنوز پیاده نشده — کاندید بهبود بعدی.
- **Position Sizing محلیِ همین صفحه Strategy Lab است**، نه یک تنظیم متمرکز
  در Settings با یادآوری بین صفحات.
- **ظرفیت نقدشوندگی برای پایه سهام (Covered Call/Collar) همیشه Unavailable
  است** چون Volume/OI دارایی پایه در داده پایه ذخیره نمی‌شود — محدودیت داده،
  نه باگ منطقی.
- پوسته روشن (Light Mode) تعریف نشده (توکن‌هایش آماده است).
