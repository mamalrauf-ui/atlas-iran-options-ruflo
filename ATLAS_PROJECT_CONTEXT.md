# ATLAS Project Context

## Project
ATLAS - Iran Options Intelligence

ATLAS is a Streamlit-based analytics and decision-support dashboard for the Iranian options market.

The project is intended to automatically collect market data, normalize and validate it, calculate missing analytics, evaluate option contracts and strategies, and identify potentially attractive opportunities.

---

## Technology Stack

- Python 3.13.14
- Streamlit
- Pandas
- NumPy
- SQLite
- Git / GitHub
- Ruflo V3 for agentic project orchestration and development workflow

The application is developed and tested locally in VS Code on Windows.

---

## Core Objective

ATLAS should not be merely a market-data display.

It should:

1. Collect available Iranian options market data automatically.
2. Use a provider hierarchy with fallback sources.
3. Normalize inconsistent source data.
4. Validate data before using it.
5. Calculate missing metrics when sufficient inputs are available.
6. Analyze option contracts.
7. Rank opportunities.
8. Analyze option strategies.
9. Provide actionable decision-support information.

---

## Data Policy

Manual Excel import must NOT be part of the final system.

Users must NOT be required to:

- upload Excel files
- manually enter market data
- manually maintain option-chain data
- manually enter prices that can be obtained automatically

Market data should be obtained automatically from available providers.

The architecture should support multiple providers with a fallback hierarchy.

Primary and secondary providers may include:

- TSETMC
- FIMA
- other reliable Iranian market-data sources when technically and legally appropriate

The system must clearly distinguish:

### Source Data
Values directly obtained from external market-data providers.

### Derived Data
Values calculated by ATLAS from source data.

### Estimated / Inferred Data
Values that cannot be directly obtained but can reasonably be inferred from available market information.

Derived or estimated values must never be presented as if they were directly received from the market.

---

## Market Update Model

ATLAS is NOT intended to be a continuously refreshing real-time trading terminal.

The preferred model is:

- end-of-market / closing-price data
- daily updates
- user-triggered refresh/fetch
- historical storage
- reproducible calculations

Historical data should start from Iranian date:

1405/01/01

Older history is not required unless explicitly requested later.

---

## Iranian Options Market Specifics

ATLAS must be designed for the Iranian options market rather than blindly copying international options assumptions.

Important considerations include:

- Iranian contract specifications
- Iranian contract size
- Iranian trading conventions
- relatively lower market depth and liquidity
- potentially sparse volume and open interest
- Iranian option symbols and naming conventions
- American-style exercise conventions currently applicable to the target market model
- early-exercise assumptions must not be introduced incorrectly

All calculations must respect the actual contract specifications used in the Iranian market.

---

## Important Data Fields

The system should attempt to obtain or calculate, where applicable:

- underlying symbol
- option symbol
- option type
- strike price
- expiration date
- days to expiration
- underlying price
- option price
- last price
- closing price
- bid
- ask
- volume
- open interest
- contract size
- intrinsic value
- time value
- moneyness
- ITM / ATM / OTM classification
- implied volatility
- Greeks
- liquidity metrics
- spread
- theoretical value
- relative valuation metrics

A value of zero must NOT automatically mean that the real market value is zero.

The system must distinguish between:

- actual zero
- missing
- unavailable
- not applicable
- calculation failure

---

## Current Known Data Problem

One of the main technical problems being investigated is that TSETMC price data can be obtained, but some fields such as:

- implied volatility
- open interest
- volume
- open positions

may sometimes be returned as zero or may not be detected correctly.

This can break downstream calculations and opportunity ranking.

Therefore the data layer needs robust:

1. provider fallback
2. normalization
3. validation
4. missing-value handling
5. calculation fallback
6. logging

The data layer should be treated as a major engineering priority.

---

## Application Navigation

The preferred main navigation order is:

1. Dashboard
2. Scanner
3. Opportunities
4. Option Chain
5. Strategy Lab
6. Backtests
7. Analytics
8. Data Center
9. Settings

There should NOT be a separate administration/management area because all normal users are considered equivalent.

---

## UI / UX Principles

The interface should be:

- minimalist
- modern
- professional
- uncluttered
- easy to scan
- information-dense without being overwhelming

Important information must not get lost inside excessive cards, panels or decorative components.

Use green/red visual indicators where appropriate for:

- positive / negative
- profit / loss
- bullish / bearish
- favorable / unfavorable

ITM / ATM / OTM should be clearly visible and filterable.

---

## Opportunities

The Opportunities section should not simply list contracts.

It should support strategy-oriented discovery.

Examples:

- best covered calls
- best cash-secured puts
- attractive option purchases
- attractive spreads
- opportunities ranked by score
- liquidity-aware opportunities
- risk-adjusted opportunities

The ranking system should be explainable.

Users should be able to understand why an opportunity receives a particular score.

---

## Scanner

Scanner functionality should allow users to identify contracts based on criteria such as:

- moneyness
- expiration
- liquidity
- volume
- open interest
- implied volatility
- Greeks
- premium
- theoretical value
- spread
- opportunity score

---

## Option Chain

Option Chain should provide a clean view of calls and puts around strikes and expiration dates.

Important information should include:

- strike
- call/put
- price
- volume
- open interest
- IV
- Greeks
- ITM/ATM/OTM
- liquidity
- theoretical value

---

## Strategy Lab

Strategy Lab should allow analysis of option strategies.

The system should eventually support strategies such as:

- long call
- long put
- covered call
- cash-secured put
- protective put
- bull call spread
- bear put spread
- other practical combinations

Strategy calculations must use Iranian market specifications.

---

## Backtests

Backtesting should use stored historical data.

Backtests must clearly distinguish:

- actual historical observations
- calculated metrics
- assumptions
- simulated execution

Backtests must not create false precision when historical market data is incomplete.

---

## Analytics

Analytics should provide meaningful market intelligence rather than decorative charts.

Potential analytics include:

- volatility
- liquidity
- volume
- open interest
- moneyness distribution
- expiration analysis
- opportunity distribution
- strategy performance
- market-wide option statistics

---

## Data Center

Data Center should expose the data pipeline transparently.

Users should be able to understand:

- last successful data update
- provider used
- fallback provider used
- records collected
- validation status
- missing fields
- calculation status
- errors/warnings

It should NOT contain manual Excel upload as a normal workflow.

---

## Architecture

The project currently contains major components under:

### core/

- analytics.py
- backtest.py
- database.py
- design.py
- importer.py
- live_data.py
- market_brief.py
- opportunity.py
- opportunity_config.py
- pricing.py
- providers.py
- scanner.py
- schema.py
- strategy.py

### core/data/

- historical.py
- normalizer.py
- snapshot.py
- sync.py
- validator.py

### core/data/providers/

- base.py
- fima.py
- tsetmc.py

### ui/

- dashboard.py
- scanner.py
- opportunities.py
- option_chain.py
- strategy_lab.py
- backtest.py
- analytics.py
- data_center.py
- settings.py
- common.py
- components.py
- contract_detail.py

---

## Engineering Principles

When modifying ATLAS:

1. Do not break existing working functionality unnecessarily.
2. Prefer modular changes.
3. Keep data acquisition separate from calculations.
4. Keep calculations separate from UI.
5. Keep provider-specific logic isolated.
6. Avoid hard-coded market assumptions where configuration is more appropriate.
7. Validate external data before calculations.
8. Handle missing data explicitly.
9. Never silently convert unavailable data into zero.
10. Avoid manual data-entry dependencies.
11. Preserve historical reproducibility.
12. Add tests for important calculations and data transformations.
13. Prefer explainable scoring over opaque ranking.
14. Keep the UI simple and professional.

---

## Ruflo Development Role

Ruflo is being introduced as an orchestration and development layer around the ATLAS project.

Ruflo should understand that ATLAS is an existing software project, not a greenfield project.

Before making major changes, agents should:

1. inspect the existing repository
2. understand the current architecture
3. identify existing functionality
4. identify current tests
5. identify dependencies
6. identify data-flow problems
7. avoid unnecessary rewrites

Changes should be incremental and testable.

---

## Current Priority

The highest-priority technical area is the data architecture.

The target architecture should be:

External Providers
        ↓
Provider Adapter
        ↓
Raw Data
        ↓
Normalization
        ↓
Validation
        ↓
Missing Data Resolution / Fallback
        ↓
ATLAS Calculations
        ↓
Database / Historical Storage
        ↓
Analytics / Scanner / Opportunities / Strategies
        ↓
UI

The data layer must become reliable before advanced opportunity scoring and strategy analysis are considered complete.

---

## Current Development Constraint

The Ruflo memory/embedding subsystem currently has a Windows-related problem involving:

Xenova/all-MiniLM-L6-v2

and a large memory allocation failure.

This must NOT block ATLAS development.

Project understanding should therefore rely primarily on:

- repository files
- ATLAS_PROJECT_CONTEXT.md
- CLAUDE.md
- Git history
- source code
- tests
- explicit project documentation

Do not make the ATLAS project dependent on successful Ruflo embedding initialization.

---

## Development Philosophy

ATLAS should evolve toward a reliable, explainable and maintainable Iranian options intelligence platform.

The goal is not to add the maximum number of features.

The goal is to make the existing features:

- accurate
- automated
- understandable
- robust
- useful for real decision-making