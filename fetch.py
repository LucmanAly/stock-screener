"""Fetch S&P 500 fundamentals from yfinance into data.csv.

Usage:
    python fetch.py [--limit N] [--refresh] [--cache-dir ./cache] [--out data.csv]

Every field yfinance returns in .info is saved, plus a fetched_at UTC stamp.
Results are cached per-ticker in ./cache/ so a crash or Ctrl-C resumes instead
of restarting the run.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

THROTTLE_SECONDS = 0.4
MAX_ATTEMPTS = 5
BACKOFF_SCHEDULE = [1, 2, 4, 8, 16]  # seconds, used on 429 / rate-limit errors

# Columns the screener depends on. Guaranteed to exist in data.csv even when
# yfinance omits them, and written first so the CSV is readable by eye.
REQUIRED_COLUMNS = [
    "symbol",
    "sector",
    "industry",
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

log = logging.getLogger("fetch")

# Counts every 429 / rate-limit backoff across the run, reported in the summary
# so the nightly wrapper can log it without scraping log text.
RATE_LIMIT_HITS = 0


# --------------------------------------------------------------------------
# Tickers
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
    industries = col("GICS Sub-Industry", "GICS Sub Industry").astype(str).str.strip()

    rows = []
    for sym, name, sec, ind in zip(symbols, names, sectors, industries):
        rows.append(
            {
                "symbol": sym.replace(".", "-"),
                "wiki_name": name,
                "wiki_sector": sec,
                "wiki_industry": ind,
            }
        )
    log.info("Got %d tickers", len(rows))
    return rows


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
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("%s: unreadable cache file (%s), refetching", ticker, exc)
        return None


def write_cache(cache_dir: Path, ticker: str, record: dict) -> None:
    p = cache_path(cache_dir, ticker)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(record, fh, default=str)
    tmp.replace(p)  # atomic, so a Ctrl-C never leaves a half-written cache entry


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------
def is_rate_limited(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return "429" in text or "rate limit" in text or "too many requests" in text


def fetch_info(ticker: str) -> dict:
    """Fetch .info for one ticker, with exponential backoff on 429."""
    global RATE_LIMIT_HITS
    last_exc: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            info = yf.Ticker(ticker).info
            if not isinstance(info, dict) or not info:
                raise RuntimeError("empty .info payload")
            return info
        except Exception as exc:  # noqa: BLE001 - yfinance raises a wide variety
            last_exc = exc
            if attempt == MAX_ATTEMPTS - 1:
                break
            if is_rate_limited(exc):
                RATE_LIMIT_HITS += 1
                wait = BACKOFF_SCHEDULE[attempt]
                log.warning(
                    "%s: rate limited (attempt %d/%d), backing off %ds",
                    ticker, attempt + 1, MAX_ATTEMPTS, wait,
                )
                time.sleep(wait)
            else:
                log.warning(
                    "%s: %s (attempt %d/%d), retrying in 1s",
                    ticker, exc, attempt + 1, MAX_ATTEMPTS,
                )
                time.sleep(1)
    raise RuntimeError(f"{ticker}: failed after {MAX_ATTEMPTS} attempts: {last_exc}")


def build_record(meta: dict, info: dict) -> dict:
    """Flatten .info into one row. Every field present is kept."""
    record: dict = {}
    for key, value in info.items():
        if isinstance(value, (dict, list, tuple)):
            # e.g. companyOfficers - keep it, but as JSON text so it survives CSV.
            record[key] = json.dumps(value, default=str)
        else:
            record[key] = value

    record["symbol"] = meta["symbol"]
    record["wiki_name"] = meta.get("wiki_name")
    record["wiki_sector"] = meta.get("wiki_sector")
    record["wiki_industry"] = meta.get("wiki_industry")

    sector = record.get("sector")
    if sector is None or (isinstance(sector, str) and not sector.strip()):
        log.warning("%s: sector missing from yfinance, setting 'Unknown'", meta["symbol"])
        record["sector"] = "Unknown"

    record["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return record


# --------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------
def order_columns(df: pd.DataFrame) -> list[str]:
    required = [c for c in REQUIRED_COLUMNS if c in df.columns]
    trailing = [c for c in ("wiki_name", "wiki_sector", "wiki_industry", "fetched_at") if c in df.columns]
    rest = sorted(c for c in df.columns if c not in required and c not in trailing)
    return required + rest + trailing


def write_fields_md(df: pd.DataFrame, path: Path) -> None:
    total = len(df)
    lines = [
        "# Available fields",
        "",
        f"Rows: **{total}**  ",
        f"Columns: **{len(df.columns)}**  ",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "| # | column | non-null | coverage | dtype | example |",
        "| --: | --- | --: | --: | --- | --- |",
    ]
    for i, col in enumerate(df.columns, start=1):
        s = df[col]
        non_null = int(s.notna().sum())
        pct = (non_null / total * 100) if total else 0.0
        sample = s.dropna()
        example = "" if sample.empty else str(sample.iloc[0])
        if len(example) > 40:
            example = example[:37] + "..."
        example = example.replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {i} | `{col}` | {non_null} | {pct:.1f}% | {s.dtype} | {example} |"
        )
    lines.append("")
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
        log.error("%s is locked by another process (Excel?) - writing %s instead", path.name, alt.name)
        writer(alt)
        return alt


def write_outputs(records: list[dict], out_csv: Path, fields_md: Path) -> tuple[pd.DataFrame, list[Path]]:
    df = pd.DataFrame(records)
    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            log.warning("required column %r absent from every record, adding as empty", col)
            df[col] = pd.NA
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
    parser = argparse.ArgumentParser(description="Fetch S&P 500 fundamentals into data.csv")
    parser.add_argument("--limit", type=int, default=None, help="only fetch the first N tickers")
    parser.add_argument("--refresh", action="store_true", help="ignore the cache and refetch everything")
    parser.add_argument("--cache-dir", default="cache", help="resume cache directory (default: ./cache)")
    parser.add_argument("--out", default="data.csv", help="output CSV path (default: data.csv)")
    parser.add_argument("--fields", default="fields.md", help="field inventory path (default: fields.md)")
    parser.add_argument("--summary-json", default=None,
                        help="write a machine-readable run summary to this path")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    base = Path(__file__).resolve().parent
    cache_dir = Path(args.cache_dir)
    if not cache_dir.is_absolute():
        cache_dir = base / cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)

    out_csv = Path(args.out) if Path(args.out).is_absolute() else base / args.out
    fields_md = Path(args.fields) if Path(args.fields).is_absolute() else base / args.fields

    tickers = get_sp500_tickers()
    if args.limit is not None:
        tickers = tickers[: args.limit]
        log.info("--limit %d: fetching %d tickers", args.limit, len(tickers))

    records: list[dict] = []
    failures: list[tuple[str, str]] = []
    missing_sector: list[str] = []
    cached_hits = 0
    interrupted = False

    try:
        for i, meta in enumerate(tickers, start=1):
            symbol = meta["symbol"]

            if not args.refresh:
                cached = read_cache(cache_dir, symbol)
                if cached is not None:
                    records.append(cached)
                    cached_hits += 1
                    if cached.get("sector") == "Unknown":
                        missing_sector.append(symbol)
                    log.info("[%d/%d] %s (cached)", i, len(tickers), symbol)
                    continue

            try:
                info = fetch_info(symbol)
            except Exception as exc:  # noqa: BLE001
                log.error("[%d/%d] %s FAILED: %s", i, len(tickers), symbol, exc)
                failures.append((symbol, str(exc)))
                time.sleep(THROTTLE_SECONDS)
                continue

            record = build_record(meta, info)
            if record.get("sector") == "Unknown":
                missing_sector.append(symbol)
            write_cache(cache_dir, symbol, record)
            records.append(record)
            log.info(
                "[%d/%d] %s  %s  %d fields",
                i, len(tickers), symbol, record.get("sector"), len(record),
            )
            time.sleep(THROTTLE_SECONDS)
    except KeyboardInterrupt:
        interrupted = True
        log.warning("Interrupted - writing what has been fetched so far (cache is intact)")

    def emit_summary(rc: int, written_paths: list[Path]) -> None:
        if not args.summary_json:
            return
        summary = {
            "attempted": len(tickers),
            "succeeded": len(records),
            "failed": len(failures),
            "fetched_fresh": len(records) - cached_hits,
            "from_cache": cached_hits,
            "rate_limit_hits": RATE_LIMIT_HITS,
            "missing_sector": missing_sector,
            "failures": [{"symbol": s, "error": e} for s, e in failures],
            "interrupted": interrupted,
            "outputs": [str(p) for p in written_paths],
            "exit_code": rc,
        }
        Path(args.summary_json).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if not records:
        log.error("No records fetched, nothing to write")
        emit_summary(1, [])
        return 1

    df, written = write_outputs(records, out_csv, fields_md)

    print()
    log.info("Wrote %s  (%d rows x %d columns)", written[0], len(df), len(df.columns))
    log.info("Wrote %s", written[1])
    log.info("Fetched fresh: %d | from cache: %d | failed: %d",
             len(records) - cached_hits, cached_hits, len(failures))
    if missing_sector:
        log.warning("Sector missing -> 'Unknown' for %d ticker(s): %s",
                    len(missing_sector), ", ".join(missing_sector))
    if failures:
        log.warning("Failed tickers (rerun to retry, cache keeps the rest):")
        for sym, err in failures:
            log.warning("  %s: %s", sym, err)

    rc = 130 if interrupted else 0
    emit_summary(rc, written)
    return rc


if __name__ == "__main__":
    sys.exit(main())
