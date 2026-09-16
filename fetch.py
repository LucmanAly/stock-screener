"""Fetch S&P 500 fundamentals, estimates and price factors into data.csv.

Usage:
    python fetch.py [--limit N] [--stage all|fundamentals|prices]
                    [--throttle 1.5] [--max-retries 7] [--refresh]

Five pillars of data are collected per ticker:
  1. Classification  - GICS sector / sub-industry (Wikipedia) + Yahoo industry,
                       resolved into a peer_group by a membership waterfall.
  2. Snapshot        - every field yfinance .info returns.
  3. Statements      - ROIC, 3Y CAGRs, FCF conversion, leverage, margin stability
                       derived from .income_stmt / .balance_sheet / .cashflow.
  4. Estimates       - FY1/FY2 EPS estimate trend, next-year revenue consensus,
                       and the last four earnings surprises.
  5. Price           - 12-1 momentum, 6m return, relative strength vs SPY and
                       sector, drawdown from the 52w high, price vs 200dma.
                       Fetched in ONE batched download, not per ticker.

Anything unavailable is NaN. Nothing is ever imputed or zero-filled.

Results are cached per-ticker in ./cache/ so a crash or Ctrl-C resumes instead
of restarting what is a ~70 minute run.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

DEFAULT_THROTTLE_SECONDS = 0.4
# Retries AFTER the first attempt, so the default gives waits of 1,2,4,8,16s.
DEFAULT_MAX_RETRIES = 5
BACKOFF_CAP_SECONDS = 300

# Bump when the shape of a cached record changes, so stale entries are refetched
# rather than silently producing a CSV with missing columns.
CACHE_VERSION = 3

# A peer group must have at least this many members to be used for ranking.
MIN_PEER_MEMBERS = 10

BENCHMARK = "SPY"
PRICE_PERIOD = "14mo"

# Overridden from the CLI in main().
THROTTLE_SECONDS = DEFAULT_THROTTLE_SECONDS
MAX_RETRIES = DEFAULT_MAX_RETRIES

STAGES = ("all", "fundamentals", "prices")

STATEMENT_METRICS = [
    "roic",
    "revenue_cagr_3y",
    "eps_cagr_3y",
    "fcf_cagr_3y",
    "fcf_conversion",
    "interest_coverage",
    "net_debt_to_ebitda",
    "gross_margin_stdev_5y",
    # Balance-sheet strength substitute used for Financials / Real Estate,
    # where ROIC and net debt / EBITDA are not meaningful.
    "equity_ratio",
]

ESTIMATE_METRICS = (
    [f"eps_fy{n}_{tag}" for n in (1, 2) for tag in ("current", "7d", "30d", "60d", "90d")]
    + [f"eps_fy{n}_{tag}" for n in (1, 2) for tag in ("avg", "analysts", "growth")]
    + ["revenue_est_next_year"]
)

SURPRISE_METRICS = [f"surprise_pct_{i}" for i in range(1, 5)]

PRICE_METRICS = [
    "momentum_12_1",
    "return_6m",
    "rs_6m_vs_spy",
    "rs_6m_vs_sector",
    "pct_below_52w_high",
    "price_vs_200dma",
]

CLASSIFICATION_COLUMNS = [
    "symbol",
    "gics_sector",
    "gics_sub_industry",
    "sector",
    "industry",
    "peer_group",
    "peer_level",
]

# Columns the screener depends on. Guaranteed to exist in data.csv even when
# yfinance omits them, and written first so the CSV is readable by eye.
REQUIRED_COLUMNS = (
    CLASSIFICATION_COLUMNS
    + [
        "marketCap",
        "trailingPE",
        "forwardPE",
        "priceToBook",
        "enterpriseToEbitda",
        "freeCashflow",
        "operatingMargins",
        "profitMargins",
        "returnOnEquity",
        "revenueGrowth",
        "earningsGrowth",
        "debtToEquity",
        "beta",
        "fiftyTwoWeekHigh",
        "currentPrice",
        "targetMeanPrice",
        "numberOfAnalystOpinions",
    ]
    + STATEMENT_METRICS
    + ESTIMATE_METRICS
    + SURPRISE_METRICS
    + PRICE_METRICS
)

log = logging.getLogger("fetch")

# Counts every 429 / rate-limit backoff across the run, reported in the summary
# so the nightly wrapper can log it without scraping log text.
RATE_LIMIT_HITS = 0


def backoff_seconds(retry_index: int) -> int:
    """Exponential backoff: 1, 2, 4, 8, 16, 32, 64 ... capped."""
    return min(2 ** retry_index, BACKOFF_CAP_SECONDS)


# --------------------------------------------------------------------------
# Small numeric helpers. Every one returns NaN rather than guessing.
# --------------------------------------------------------------------------
def nan() -> float:
    return float("nan")


def finite(x) -> bool:
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def div(numerator, denominator, *, require_positive_denominator: bool = False) -> float:
    """Division that yields NaN instead of raising, inf, or a misleading sign."""
    if not finite(numerator) or not finite(denominator):
        return nan()
    d = float(denominator)
    if d == 0:
        return nan()
    if require_positive_denominator and d <= 0:
        return nan()
    return float(numerator) / d


def cagr(newest, oldest, years: int) -> float:
    """Compound growth. NaN unless both endpoints are positive - a CAGR across
    a sign change is not a meaningful number, so it is not invented."""
    if not finite(newest) or not finite(oldest):
        return nan()
    if float(newest) <= 0 or float(oldest) <= 0:
        return nan()
    return (float(newest) / float(oldest)) ** (1.0 / years) - 1.0


def jsonable(value):
    """Convert numpy/pandas scalars so the cache round-trips exactly."""
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        f = float(value)
        return None if math.isnan(f) else f
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=str)
    return value


# --------------------------------------------------------------------------
# Tickers and classification
# --------------------------------------------------------------------------
def get_sp500_tickers() -> list[dict]:
    """Scrape the Wikipedia constituents table. Dots -> dashes (BRK.B -> BRK-B)."""
    log.info("Fetching S&P 500 constituents from Wikipedia")
    resp = requests.get(WIKI_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()

    tables = pd.read_html(StringIO(resp.text), attrs={"id": "constituents"}, flavor="lxml")
    if not tables:
        raise RuntimeError("Could not find the 'constituents' table on the Wikipedia page")
    df = tables[0]

    def col(*names):
        for n in names:
            if n in df.columns:
                return df[n]
        return pd.Series([None] * len(df))

    symbols = col("Symbol", "Ticker symbol").astype(str).str.strip()
    names = col("Security", "Company").astype(str).str.strip()
    sectors = col("GICS Sector").astype(str).str.strip()
    subs = col("GICS Sub-Industry", "GICS Sub Industry").astype(str).str.strip()

    rows = []
    for sym, name, sec, sub in zip(symbols, names, sectors, subs):
        rows.append(
            {
                "symbol": sym.replace(".", "-"),
                "wiki_name": name,
                "gics_sector": sec or None,
                "gics_sub_industry": sub or None,
            }
        )
    log.info("Got %d tickers", len(rows))
    return rows


def assign_peer_groups(df: pd.DataFrame, min_members: int = MIN_PEER_MEMBERS) -> pd.DataFrame:
    """Waterfall: GICS sub-industry -> Yahoo industry -> GICS sector.

    A group is only usable if it has at least `min_members` in the universe;
    ranking against four peers is noise dressed up as a percentile.
    """
    out = df.copy()
    sub = out.get("gics_sub_industry", pd.Series(index=out.index, dtype=object))
    ind = out.get("industry", pd.Series(index=out.index, dtype=object))
    sec = out.get("gics_sector", pd.Series(index=out.index, dtype=object))

    # Last usable fallback: GICS sector, then Yahoo sector, then Unknown.
    base = sec.where(sec.notna() & (sec != ""), out.get("sector"))
    base = base.where(base.notna() & (base != ""), "Unknown")

    peer = base.astype(object)
    level = pd.Series("gics_sector", index=out.index, dtype=object)

    # Applied coarse -> fine so the finest qualifying rung wins.
    for column, label in ((ind, "yahoo_industry"), (sub, "gics_sub_industry")):
        if column is None:
            continue
        counts = column.map(column.value_counts())
        usable = column.notna() & (column != "") & (counts >= min_members)
        peer = peer.mask(usable, column)
        level = level.mask(usable, label)

    out["peer_group"] = peer
    out["peer_level"] = level
    return out


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------
def cache_path(cache_dir: Path, ticker: str) -> Path:
    # Ticker symbols are alphanumeric plus '-', so they are safe filenames.
    return cache_dir / f"{ticker}.json"


def read_cache(cache_dir: Path, ticker: str) -> dict | None:
    p = cache_path(cache_dir, ticker)
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as fh:
            record = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("%s: unreadable cache file (%s), refetching", ticker, exc)
        return None
    if record.get("_cache_version") != CACHE_VERSION:
        return None  # written by an older schema, refetch
    return record


def write_cache(cache_dir: Path, ticker: str, record: dict) -> None:
    p = cache_path(cache_dir, ticker)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(record, fh, default=str)
    tmp.replace(p)  # atomic, so a Ctrl-C never leaves a half-written cache entry


def price_cache_path(cache_dir: Path) -> Path:
    return cache_dir / "_prices.csv"


# --------------------------------------------------------------------------
# Statement metrics
# --------------------------------------------------------------------------
def stmt_row(df, *names) -> pd.Series | None:
    """First matching line item as a newest-first numeric Series, else None."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    for name in names:
        if name in df.index:
            row = df.loc[name]
            if isinstance(row, pd.DataFrame):  # duplicated line item
                row = row.iloc[0]
            series = pd.to_numeric(row, errors="coerce")
            return series.sort_index(ascending=False)
    return None


def at(series: pd.Series | None, position: int) -> float:
    if series is None or len(series) <= position:
        return nan()
    value = series.iloc[position]
    return float(value) if finite(value) else nan()


def compute_statement_metrics(income, balance, cashflow) -> dict:
    m: dict[str, float] = {k: nan() for k in STATEMENT_METRICS}

    revenue = stmt_row(income, "Total Revenue", "Operating Revenue")
    gross_profit = stmt_row(income, "Gross Profit")
    ebit = stmt_row(income, "EBIT", "Operating Income")
    ebitda = stmt_row(income, "EBITDA", "Normalized EBITDA")
    net_income = stmt_row(income, "Net Income", "Net Income Common Stockholders")
    interest = stmt_row(income, "Interest Expense", "Interest Expense Non Operating")
    pretax = stmt_row(income, "Pretax Income")
    tax = stmt_row(income, "Tax Provision")
    tax_rate_row = stmt_row(income, "Tax Rate For Calcs")
    eps = stmt_row(income, "Diluted EPS", "Basic EPS")

    total_debt = stmt_row(balance, "Total Debt")
    equity = stmt_row(balance, "Stockholders Equity", "Common Stock Equity")
    cash = stmt_row(
        balance,
        "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments",
    )
    total_assets = stmt_row(balance, "Total Assets")

    fcf = stmt_row(cashflow, "Free Cash Flow")

    # --- ROIC = NOPAT / (total debt + equity - cash) -----------------------
    tax_rate = at(tax_rate_row, 0)
    if not finite(tax_rate):
        tax_rate = div(at(tax, 0), at(pretax, 0), require_positive_denominator=True)
    ebit_0 = at(ebit, 0)
    if finite(ebit_0) and finite(tax_rate) and 0.0 <= tax_rate <= 1.0:
        nopat = ebit_0 * (1.0 - tax_rate)
        invested = at(total_debt, 0) + at(equity, 0) - at(cash, 0)
        m["roic"] = div(nopat, invested, require_positive_denominator=True)

    # --- 3 year CAGRs (needs 4 annual points: newest and three years back) --
    m["revenue_cagr_3y"] = cagr(at(revenue, 0), at(revenue, 3), 3)
    m["eps_cagr_3y"] = cagr(at(eps, 0), at(eps, 3), 3)
    m["fcf_cagr_3y"] = cagr(at(fcf, 0), at(fcf, 3), 3)

    # --- Quality and leverage ---------------------------------------------
    # Negative net income makes the conversion ratio meaningless, not "bad".
    m["fcf_conversion"] = div(at(fcf, 0), at(net_income, 0), require_positive_denominator=True)
    m["interest_coverage"] = div(at(ebit, 0), at(interest, 0), require_positive_denominator=True)

    net_debt = at(total_debt, 0) - at(cash, 0)
    m["net_debt_to_ebitda"] = div(net_debt, at(ebitda, 0), require_positive_denominator=True)

    m["equity_ratio"] = div(at(equity, 0), at(total_assets, 0), require_positive_denominator=True)

    # --- 5 year gross margin stability -------------------------------------
    if revenue is not None and gross_profit is not None:
        margins = []
        for i in range(min(5, len(revenue), len(gross_profit))):
            gm = div(at(gross_profit, i), at(revenue, i), require_positive_denominator=True)
            if finite(gm):
                margins.append(gm)
        if len(margins) >= 2:
            m["gross_margin_stdev_5y"] = float(np.std(margins, ddof=1))

    return m


# --------------------------------------------------------------------------
# Estimates and surprises
# --------------------------------------------------------------------------
def cell(df, row_label: str, column: str) -> float:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return nan()
    if row_label not in df.index or column not in df.columns:
        return nan()
    value = df.loc[row_label, column]
    if isinstance(value, pd.Series):
        value = value.iloc[0]
    return float(value) if finite(value) else nan()


def compute_estimate_metrics(eps_trend, earnings_estimate, revenue_estimate) -> dict:
    m: dict[str, float] = {k: nan() for k in ESTIMATE_METRICS}

    # yfinance labels the current fiscal year "0y" and the next one "+1y".
    for n, period in ((1, "0y"), (2, "+1y")):
        for tag, column in (
            ("current", "current"),
            ("7d", "7daysAgo"),
            ("30d", "30daysAgo"),
            ("60d", "60daysAgo"),
            ("90d", "90daysAgo"),
        ):
            m[f"eps_fy{n}_{tag}"] = cell(eps_trend, period, column)
        m[f"eps_fy{n}_avg"] = cell(earnings_estimate, period, "avg")
        m[f"eps_fy{n}_analysts"] = cell(earnings_estimate, period, "numberOfAnalysts")
        m[f"eps_fy{n}_growth"] = cell(earnings_estimate, period, "growth")

    m["revenue_est_next_year"] = cell(revenue_estimate, "+1y", "avg")
    return m


def compute_surprise_metrics(earnings_history) -> dict:
    m: dict[str, float] = {k: nan() for k in SURPRISE_METRICS}
    if not isinstance(earnings_history, pd.DataFrame) or earnings_history.empty:
        return m
    if "surprisePercent" not in earnings_history.columns:
        return m
    series = pd.to_numeric(earnings_history["surprisePercent"], errors="coerce")
    series = series.sort_index(ascending=False)  # most recent quarter first
    for i in range(min(4, len(series))):
        value = series.iloc[i]
        m[f"surprise_pct_{i + 1}"] = float(value) if finite(value) else nan()
    return m


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------
def is_rate_limited(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return "429" in text or "rate limit" in text or "too many requests" in text


def safe_attr(ticker_obj, name: str):
    """yfinance raises a wide variety for unavailable data; absent means NaN."""
    try:
        return getattr(ticker_obj, name)
    except Exception:  # noqa: BLE001
        return None


def fetch_bundle(ticker: str) -> dict:
    """All per-ticker network data, retried as a unit with exponential backoff."""
    global RATE_LIMIT_HITS
    last_exc: Exception | None = None
    total_attempts = MAX_RETRIES + 1

    for attempt in range(total_attempts):
        try:
            t = yf.Ticker(ticker)
            info = t.info
            if not isinstance(info, dict) or not info:
                raise RuntimeError("empty .info payload")

            bundle: dict = {"info": info}
            bundle["statements"] = compute_statement_metrics(
                safe_attr(t, "income_stmt"),
                safe_attr(t, "balance_sheet"),
                safe_attr(t, "cashflow"),
            )
            bundle["estimates"] = compute_estimate_metrics(
                safe_attr(t, "eps_trend"),
                safe_attr(t, "earnings_estimate"),
                safe_attr(t, "revenue_estimate"),
            )
            bundle["surprises"] = compute_surprise_metrics(safe_attr(t, "earnings_history"))
            return bundle

        except Exception as exc:  # noqa: BLE001 - yfinance raises a wide variety
            last_exc = exc
            if attempt == total_attempts - 1:
                break
            if is_rate_limited(exc):
                RATE_LIMIT_HITS += 1
                wait = backoff_seconds(attempt)
                log.warning(
                    "%s: rate limited (attempt %d/%d), backing off %ds",
                    ticker, attempt + 1, total_attempts, wait,
                )
                time.sleep(wait)
            else:
                log.warning(
                    "%s: %s (attempt %d/%d), retrying in 1s",
                    ticker, exc, attempt + 1, total_attempts,
                )
                time.sleep(1)

    raise RuntimeError(f"{ticker}: failed after {total_attempts} attempts: {last_exc}")


def build_record(meta: dict, bundle: dict) -> dict:
    """Flatten a bundle into one row. Every .info field present is kept."""
    record: dict = {}
    for key, value in bundle["info"].items():
        record[key] = jsonable(value)

    for section in ("statements", "estimates", "surprises"):
        for key, value in bundle[section].items():
            record[key] = jsonable(value)

    record["symbol"] = meta["symbol"]
    record["wiki_name"] = meta.get("wiki_name")
    record["gics_sector"] = meta.get("gics_sector")
    record["gics_sub_industry"] = meta.get("gics_sub_industry")

    sector = record.get("sector")
    if sector is None or (isinstance(sector, str) and not sector.strip()):
        log.warning("%s: sector missing from yfinance, setting 'Unknown'", meta["symbol"])
        record["sector"] = "Unknown"

    record["fetched_at"] = datetime.now(timezone.utc).isoformat()
    record["_cache_version"] = CACHE_VERSION
    return record


# --------------------------------------------------------------------------
# Prices - one batched download for the whole universe
# --------------------------------------------------------------------------
def fetch_price_matrix(symbols: list[str]) -> pd.DataFrame | None:
    """Daily adjusted closes for every ticker plus the benchmark, in one call."""
    universe = sorted(set(symbols) | {BENCHMARK})
    log.info("Downloading %s of daily closes for %d symbols (batched)",
             PRICE_PERIOD, len(universe))
    try:
        raw = yf.download(
            universe,
            period=PRICE_PERIOD,
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("batched price download failed: %s", exc)
        return None

    if raw is None or raw.empty:
        log.error("batched price download returned nothing")
        return None

    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" not in raw.columns.get_level_values(0):
            log.error("no Close level in the downloaded price frame")
            return None
        close = raw["Close"]
    else:  # single symbol
        close = raw[["Close"]].rename(columns={"Close": universe[0]})

    close = close.sort_index()
    log.info("Price matrix: %d rows x %d symbols (%s to %s)",
             len(close), close.shape[1],
             close.index.min().date(), close.index.max().date())
    return close


def _asof(series: pd.Series, when: pd.Timestamp) -> float:
    """Last observation at or before `when`, else NaN. No forward peeking."""
    upto = series[series.index <= when]
    if upto.empty:
        return nan()
    value = upto.iloc[-1]
    return float(value) if finite(value) else nan()


def compute_price_metrics(close: pd.DataFrame, sector_by_symbol: dict[str, str]) -> pd.DataFrame:
    """12-1 momentum, 6m return and relative strength, drawdown, 200dma."""
    if close is None or close.empty:
        return pd.DataFrame(columns=["symbol"] + PRICE_METRICS)

    as_of = close.index.max()
    one_month = as_of - pd.DateOffset(months=1)
    six_months = as_of - pd.DateOffset(months=6)
    twelve_months = as_of - pd.DateOffset(months=12)

    rows = []
    for symbol in close.columns:
        series = close[symbol].dropna()
        row = {"symbol": symbol, **{k: nan() for k in PRICE_METRICS}}
        if series.empty:
            rows.append(row)
            continue

        price = float(series.iloc[-1])
        p_1m = _asof(series, one_month)
        p_6m = _asof(series, six_months)
        p_12m = _asof(series, twelve_months)

        # 12-1: the 12 month return excluding the most recent month, which is
        # the standard construction - recent-month reversal is not momentum.
        row["momentum_12_1"] = div(p_1m, p_12m) - 1 if finite(div(p_1m, p_12m)) else nan()
        row["return_6m"] = div(price, p_6m) - 1 if finite(div(price, p_6m)) else nan()

        trailing_year = series[series.index >= twelve_months]
        if not trailing_year.empty:
            high = float(trailing_year.max())
            row["pct_below_52w_high"] = div(high - price, high, require_positive_denominator=True)

        if len(series) >= 200:
            dma200 = float(series.iloc[-200:].mean())
            row["price_vs_200dma"] = div(price, dma200) - 1 if finite(div(price, dma200)) else nan()

        rows.append(row)

    out = pd.DataFrame(rows)

    # Relative strength is computed on the ratio of growth factors, so a stock
    # up 10% against a benchmark up 10% reads as 0, not as a raw spread.
    bench = out.loc[out["symbol"] == BENCHMARK, "return_6m"]
    bench_return = float(bench.iloc[0]) if len(bench) and finite(bench.iloc[0]) else nan()
    if finite(bench_return):
        out["rs_6m_vs_spy"] = (1 + out["return_6m"]) / (1 + bench_return) - 1

    out["_sector"] = out["symbol"].map(sector_by_symbol)
    sector_mean = out.groupby("_sector")["return_6m"].transform("mean")
    out["rs_6m_vs_sector"] = (1 + out["return_6m"]) / (1 + sector_mean) - 1
    out = out.drop(columns=["_sector"])

    return out[out["symbol"] != BENCHMARK].reset_index(drop=True)


# --------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------
def order_columns(df: pd.DataFrame) -> list[str]:
    required = [c for c in REQUIRED_COLUMNS if c in df.columns]
    trailing = [c for c in ("wiki_name", "fetched_at") if c in df.columns]
    hidden = [c for c in df.columns if c.startswith("_")]
    rest = sorted(
        c for c in df.columns
        if c not in required and c not in trailing and c not in hidden
    )
    return required + rest + trailing


def write_fields_md(df: pd.DataFrame, path: Path) -> None:
    total = len(df)
    groups = {
        "Classification": CLASSIFICATION_COLUMNS,
        "Statement-derived": STATEMENT_METRICS,
        "Estimates": ESTIMATE_METRICS,
        "Earnings surprises": SURPRISE_METRICS,
        "Price factors": PRICE_METRICS,
    }
    labelled = {c: g for g, cols in groups.items() for c in cols}

    lines = [
        "# Available fields",
        "",
        f"Rows: **{total}**  ",
        f"Columns: **{len(df.columns)}**  ",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Computed columns are grouped first; everything after `-- yfinance .info --`",
        "is passed through untouched from the Yahoo snapshot.",
        "",
    ]

    def table(columns: list[str], heading: str) -> None:
        present = [c for c in columns if c in df.columns]
        if not present:
            return
        lines.append(f"## {heading}")
        lines.append("")
        lines.append("| column | non-null | coverage | dtype | example |")
        lines.append("| --- | --: | --: | --- | --- |")
        for col in present:
            s = df[col]
            non_null = int(s.notna().sum())
            pct = (non_null / total * 100) if total else 0.0
            sample = s.dropna()
            example = "" if sample.empty else str(sample.iloc[0])
            if len(example) > 36:
                example = example[:33] + "..."
            example = example.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| `{col}` | {non_null} | {pct:.1f}% | {s.dtype} | {example} |")
        lines.append("")

    for heading, columns in groups.items():
        table(columns, heading)

    passthrough = [c for c in df.columns if c not in labelled]
    table(passthrough, "-- yfinance .info --")

    path.write_text("\n".join(lines), encoding="utf-8")


def safe_write(path: Path, writer) -> Path:
    """Write via `writer(path)`, falling back to a sidecar if the file is locked.

    On Windows an open Excel window holds an exclusive lock on the CSV, which
    would otherwise throw away a completed run at the very last step.
    """
    try:
        writer(path)
        return path
    except PermissionError:
        alt = path.with_name(f"{path.stem}.new{path.suffix}")
        log.error("%s is locked by another process (Excel?) - writing %s instead",
                  path.name, alt.name)
        writer(alt)
        return alt


def write_outputs(df: pd.DataFrame, out_csv: Path, fields_md: Path) -> tuple[pd.DataFrame, list[Path]]:
    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            log.warning("required column %r absent from every record, adding as empty", col)
            df[col] = np.nan
    df = df[order_columns(df)]
    df = df.sort_values("symbol").reset_index(drop=True)
    written = [
        safe_write(out_csv, lambda p: df.to_csv(p, index=False)),
        safe_write(fields_md, lambda p: write_fields_md(df, p)),
    ]
    return df, written


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch S&P 500 data into data.csv")
    parser.add_argument("--limit", type=int, default=None, help="only fetch the first N tickers")
    parser.add_argument("--stage", choices=STAGES, default="all",
                        help="'prices' refreshes price factors only (fast, no fundamentals refetch)")
    parser.add_argument("--refresh", action="store_true", help="ignore the cache and refetch everything")
    parser.add_argument("--cache-dir", default="cache", help="resume cache directory (default: ./cache)")
    parser.add_argument("--out", default="data.csv", help="output CSV path (default: data.csv)")
    parser.add_argument("--fields", default="fields.md", help="field inventory path (default: fields.md)")
    parser.add_argument("--summary-json", default=None,
                        help="write a machine-readable run summary to this path")
    parser.add_argument("--throttle", type=float, default=DEFAULT_THROTTLE_SECONDS,
                        help=f"seconds to sleep between tickers (default: {DEFAULT_THROTTLE_SECONDS})")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES,
                        help=f"retries after the first attempt, backing off 1,2,4,8... "
                             f"(default: {DEFAULT_MAX_RETRIES})")
    args = parser.parse_args(argv)

    global THROTTLE_SECONDS, MAX_RETRIES
    THROTTLE_SECONDS = args.throttle
    MAX_RETRIES = args.max_retries

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    log.info("stage=%s  throttle=%.2fs  max_retries=%d (backoff %s)",
             args.stage, THROTTLE_SECONDS, MAX_RETRIES,
             ",".join(f"{backoff_seconds(i)}s" for i in range(MAX_RETRIES)) or "none")

    base = Path(__file__).resolve().parent

    def resolve(value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else base / p

    cache_dir = resolve(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_csv = resolve(args.out)
    fields_md = resolve(args.fields)

    tickers = get_sp500_tickers()
    if args.limit is not None:
        tickers = tickers[: args.limit]
        log.info("--limit %d: using %d tickers", args.limit, len(tickers))

    records: list[dict] = []
    failures: list[tuple[str, str]] = []
    missing_sector: list[str] = []
    cached_hits = 0
    interrupted = False

    # ---------------- fundamentals ----------------
    if args.stage in ("all", "fundamentals"):
        try:
            for i, meta in enumerate(tickers, start=1):
                symbol = meta["symbol"]

                if not args.refresh:
                    cached = read_cache(cache_dir, symbol)
                    if cached is not None:
                        # Classification comes from Wikipedia, so refresh it
                        # cheaply rather than pinning it to the cache vintage.
                        cached["gics_sector"] = meta.get("gics_sector")
                        cached["gics_sub_industry"] = meta.get("gics_sub_industry")
                        records.append(cached)
                        cached_hits += 1
                        if cached.get("sector") == "Unknown":
                            missing_sector.append(symbol)
                        log.info("[%d/%d] %s (cached)", i, len(tickers), symbol)
                        continue

                try:
                    bundle = fetch_bundle(symbol)
                except Exception as exc:  # noqa: BLE001
                    log.error("[%d/%d] %s FAILED: %s", i, len(tickers), symbol, exc)
                    failures.append((symbol, str(exc)))
                    time.sleep(THROTTLE_SECONDS)
                    continue

                record = build_record(meta, bundle)
                if record.get("sector") == "Unknown":
                    missing_sector.append(symbol)
                write_cache(cache_dir, symbol, record)
                records.append(record)
                # Price factors are computed after the loop from the batched
                # download, so only statement metrics can be shown here.
                log.info("[%d/%d] %s  %s  roic=%s  rev3y=%s",
                         i, len(tickers), symbol, record.get("sector"),
                         _fmt(record.get("roic")), _fmt(record.get("revenue_cagr_3y")))
                time.sleep(THROTTLE_SECONDS)
        except KeyboardInterrupt:
            interrupted = True
            log.warning("Interrupted - writing what has been fetched so far (cache is intact)")
    else:
        # prices-only: reuse cached fundamentals, falling back to the last CSV.
        for meta in tickers:
            cached = read_cache(cache_dir, meta["symbol"])
            if cached is not None:
                cached["gics_sector"] = meta.get("gics_sector")
                cached["gics_sub_industry"] = meta.get("gics_sub_industry")
                records.append(cached)
        if records:
            cached_hits = len(records)  # nothing was fetched fresh in this stage
            log.info("stage=prices: loaded %d cached fundamentals records", len(records))
        elif out_csv.exists():
            log.info("stage=prices: cache empty, reusing fundamentals from %s", out_csv.name)
            existing = pd.read_csv(out_csv, low_memory=False)
            existing = existing.drop(columns=[c for c in PRICE_METRICS if c in existing.columns])
            records = existing.to_dict("records")
            cached_hits = len(records)
        else:
            log.error("stage=prices needs either a populated cache or an existing %s", out_csv.name)
            return 1

    if not records:
        log.error("No records available, nothing to write")
        return 1

    df = pd.DataFrame(records)

    # ---------------- prices ----------------
    price_cache = price_cache_path(cache_dir)
    close: pd.DataFrame | None = None

    if args.stage in ("all", "prices"):
        close = fetch_price_matrix([m["symbol"] for m in tickers])
        if close is not None:
            close.to_csv(price_cache)
    if close is None and price_cache.exists():
        log.info("Using cached price matrix %s", price_cache.name)
        close = pd.read_csv(price_cache, index_col=0, parse_dates=True)

    if close is None:
        log.warning("No price data available - price factors will be NaN")
        for col in PRICE_METRICS:
            df[col] = np.nan
    else:
        sector_by_symbol = dict(zip(df["symbol"], df.get("gics_sector", pd.Series(dtype=object))))
        price_df = compute_price_metrics(close, sector_by_symbol)
        df = df.drop(columns=[c for c in PRICE_METRICS if c in df.columns])
        df = df.merge(price_df, on="symbol", how="left")

    # ---------------- classification waterfall ----------------
    df = assign_peer_groups(df)
    level_counts = df["peer_level"].value_counts().to_dict()
    log.info("peer_group resolution: %s", level_counts)

    df, written = write_outputs(df, out_csv, fields_md)

    if args.summary_json:
        summary = {
            "stage": args.stage,
            "attempted": len(tickers),
            "succeeded": len(df),
            "failed": len(failures),
            "fetched_fresh": max(len(records) - cached_hits, 0),
            "from_cache": cached_hits,
            "rate_limit_hits": RATE_LIMIT_HITS,
            "missing_sector": missing_sector,
            "failures": [{"symbol": s, "error": e} for s, e in failures],
            "peer_levels": level_counts,
            "interrupted": interrupted,
            "outputs": [str(p) for p in written],
            "exit_code": 130 if interrupted else 0,
        }
        Path(args.summary_json).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print()
    log.info("Wrote %s  (%d rows x %d columns)", written[0], len(df), len(df.columns))
    log.info("Wrote %s", written[1])
    log.info("Fetched fresh: %d | from cache: %d | failed: %d",
             max(len(records) - cached_hits, 0), cached_hits, len(failures))
    if missing_sector:
        log.warning("Sector missing -> 'Unknown' for %d ticker(s): %s",
                    len(missing_sector), ", ".join(missing_sector))
    if failures:
        log.warning("Failed tickers (rerun to retry, cache keeps the rest):")
        for sym, err in failures:
            log.warning("  %s: %s", sym, err)

    return 130 if interrupted else 0


def _fmt(value) -> str:
    return "-" if not finite(value) else f"{float(value):.3f}"


if __name__ == "__main__":
    sys.exit(main())
