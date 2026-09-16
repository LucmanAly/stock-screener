"""Five-pillar percentile screen over data.csv.

    python score.py --n 50 --min-per-sector 1 --max-per-sector 15

Every metric is ranked inside its peer_group as rank(pct=True) * 100. Missing
data is EXCLUDED from that metric rather than filled - no 0.5-fill, no
best/worst-fill - and a pillar is the weighted mean of whatever metrics the
company actually has. A company holding fewer than MIN_PILLAR_COVERAGE of a
pillar's metrics has that pillar marked unreliable.

Ranks are outlier-robust by construction, so nothing is winsorized.

All weights live in the CONFIG block below - edit them there.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from tabulate import tabulate

BASE = Path(__file__).resolve().parent
DATA_CSV = BASE / "data.csv"

# ==========================================================================
# CONFIG - edit weights here
# ==========================================================================

PILLAR_WEIGHTS = {
    "Valuation": 0.30,
    "Growth": 0.25,
    "Quality": 0.25,
    "Revisions": 0.10,
    "Momentum": 0.10,
}

# A pillar needs this share of its metrics present to be trusted.
MIN_PILLAR_COVERAGE = 0.60

# Sectors where ROIC and net debt / EBITDA are not meaningful, so balance-sheet
# quality is measured with ROE and the equity ratio instead.
FINANCIAL_SECTORS = {"Financials", "Real Estate"}

# "Fundamentals ahead of price": strong and cheap, decent quality, unloved.
AHEAD_OF_PRICE = {
    "overall_min_pct": 70,
    "vg_min_pct": 70,
    "quality_min_pct": 50,
    "momentum_max_pct": 40,
}


@dataclass(frozen=True)
class Metric:
    column: str          # column in data.csv, or a derived column built below
    direction: str       # "high" = more is better, "low" = less is better
    weight: float = 1.0  # relative weight inside its pillar
    label: str = ""

    def name(self) -> str:
        return self.label or self.column


# Forward-looking metrics carry 2x the weight of trailing ones.
PILLARS: dict[str, list[Metric]] = {
    "Valuation": [
        Metric("forwardPE", "low", 2.0, "Forward P/E"),
        Metric("enterpriseToEbitda", "low", 1.0, "EV/EBITDA"),
        Metric("fcf_yield", "high", 1.0, "FCF yield"),
        Metric("ev_to_sales", "low", 1.0, "EV/Sales"),
        Metric("peg_ratio", "low", 1.0, "PEG"),
    ],
    "Growth": [
        Metric("fwd_eps_growth", "high", 2.0, "Fwd EPS growth"),
        Metric("fwd_revenue_growth", "high", 2.0, "Fwd revenue growth"),
        Metric("revenue_cagr_3y", "high", 1.0, "3Y revenue CAGR"),
        Metric("eps_cagr_3y", "high", 1.0, "3Y EPS CAGR"),
        Metric("fcf_cagr_3y", "high", 1.0, "3Y FCF CAGR"),
    ],
    "Quality": [
        Metric("roic", "high", 1.0, "ROIC"),
        Metric("fcf_margin", "high", 1.0, "FCF margin"),
        Metric("operatingMargins", "high", 1.0, "Operating margin"),
        Metric("fcf_conversion", "high", 1.0, "FCF conversion"),
        Metric("interest_coverage", "high", 1.0, "Interest coverage"),
        Metric("net_debt_to_ebitda", "low", 1.0, "Net debt/EBITDA"),
        Metric("gross_margin_stdev_5y", "low", 1.0, "Gross margin stdev"),
    ],
    "Revisions": [
        Metric("eps_fy1_chg_30d", "high", 1.0, "FY1 EPS 30d chg"),
        Metric("eps_fy1_chg_90d", "high", 1.0, "FY1 EPS 90d chg"),
        Metric("eps_fy2_chg_30d", "high", 1.0, "FY2 EPS 30d chg"),
        Metric("mean_surprise_4q", "high", 1.0, "Mean surprise 4q"),
    ],
    "Momentum": [
        Metric("momentum_12_1", "high", 1.0, "12-1 momentum"),
        Metric("rs_6m_vs_spy", "high", 1.0, "6m RS vs SPY"),
        Metric("rs_6m_vs_sector", "high", 1.0, "6m RS vs sector"),
        Metric("pct_below_52w_high", "low", 1.0, "% below 52w high"),
    ],
}

# Swapped into Quality for FINANCIAL_SECTORS.
QUALITY_SUBSTITUTIONS = {
    "roic": Metric("returnOnEquity", "high", 1.0, "ROE"),
    "net_debt_to_ebitda": Metric("equity_ratio", "high", 1.0, "Equity ratio"),
}

# ==========================================================================
# End of CONFIG
# ==========================================================================


def load_data(path: str | Path = DATA_CSV) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - run fetch.py first")
    df = pd.read_csv(path, low_memory=False)
    for required in ("symbol", "gics_sector", "peer_group"):
        if required not in df.columns:
            raise ValueError(
                f"{path.name} has no '{required}' column - it predates the "
                f"five-pillar fetch.py. Re-run: python fetch.py"
            )
    df["gics_sector"] = df["gics_sector"].fillna("Unknown")
    df["peer_group"] = df["peer_group"].fillna("Unknown")
    return df


def num(df: pd.DataFrame, column: str) -> pd.Series:
    """Numeric view of a column, or an all-NaN series if it is absent."""
    if column not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[column], errors="coerce")


def ratio_change(current: pd.Series, past: pd.Series) -> pd.Series:
    """Percent change, NaN wherever the base is non-positive.

    EPS estimate revisions are only interpretable when the starting estimate is
    positive; a swing through zero is not a percentage move.
    """
    base = past.where(past > 0)
    return current / base - 1.0


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Build the metrics that are ratios of stored columns."""
    out = df.copy()

    market_cap = num(out, "marketCap")
    revenue = num(out, "totalRevenue")
    fcf = num(out, "freeCashflow")
    enterprise = num(out, "enterpriseValue")

    out["fcf_yield"] = fcf / market_cap.where(market_cap > 0)
    out["fcf_margin"] = fcf / revenue.where(revenue > 0)
    out["ev_to_sales"] = enterprise.where(enterprise > 0) / revenue.where(revenue > 0)

    peg = num(out, "trailingPegRatio")
    # A negative PEG means negative growth, not "cheap" - drop it rather than
    # let it rank as the most attractive name in the peer group.
    out["peg_ratio"] = peg.where(peg > 0)

    # Growth: next fiscal year consensus versus the current one.
    out["fwd_eps_growth"] = num(out, "eps_fy2_growth")
    fallback = ratio_change(num(out, "eps_fy2_current"), num(out, "eps_fy1_current"))
    out["fwd_eps_growth"] = out["fwd_eps_growth"].fillna(fallback)
    out["fwd_revenue_growth"] = ratio_change(num(out, "revenue_est_next_year"), revenue)

    # Revisions: where the consensus has moved.
    out["eps_fy1_chg_30d"] = ratio_change(num(out, "eps_fy1_current"), num(out, "eps_fy1_30d"))
    out["eps_fy1_chg_90d"] = ratio_change(num(out, "eps_fy1_current"), num(out, "eps_fy1_90d"))
    out["eps_fy2_chg_30d"] = ratio_change(num(out, "eps_fy2_current"), num(out, "eps_fy2_30d"))

    surprises = pd.concat([num(out, f"surprise_pct_{i}") for i in range(1, 5)], axis=1)
    out["mean_surprise_4q"] = surprises.mean(axis=1, skipna=True)

    # Diagnostic only - never scored.
    trailing_pe = num(out, "trailingPE")
    forward_pe = num(out, "forwardPE")
    out["pe_compression"] = 1.0 - (forward_pe / trailing_pe.where(trailing_pe > 0))

    return out


def percentile(df: pd.DataFrame, metric: Metric) -> pd.Series:
    """Rank inside peer_group, 0-100, higher always better. NaN stays NaN."""
    values = num(df, metric.column)
    pct = values.groupby(df["peer_group"]).rank(pct=True) * 100.0
    if metric.direction == "low":
        pct = 100.0 - pct
    elif metric.direction != "high":
        raise ValueError(f"{metric.column}: direction must be 'high' or 'low'")
    # A peer group of one ranks at 100 by construction, which is meaningless.
    singletons = df["peer_group"].map(df["peer_group"].value_counts()) < 2
    return pct.mask(singletons)


def score_pillars(df: pd.DataFrame, verbose: bool = True) -> tuple[pd.DataFrame, dict]:
    """Compute each pillar as the weighted mean of its available metrics."""
    out = df.copy()
    is_financial = out["gics_sector"].isin(FINANCIAL_SECTORS)
    coverage_report: dict[str, dict] = {}

    for pillar, metrics in PILLARS.items():
        # Build the percentile matrix for the standard metric set.
        columns: dict[str, pd.Series] = {}
        weights: dict[str, float] = {}

        for metric in metrics:
            pct = percentile(out, metric)
            if pillar == "Quality" and metric.column in QUALITY_SUBSTITUTIONS:
                substitute = QUALITY_SUBSTITUTIONS[metric.column]
                sub_pct = percentile(out, substitute)
                # Financials get the substitute, everyone else the original.
                pct = pct.mask(is_financial, sub_pct)
                coverage_report.setdefault("_substitutions", []).append(
                    f"{metric.name()} -> {substitute.name()} for "
                    f"{int(is_financial.sum())} {'/'.join(sorted(FINANCIAL_SECTORS))} names"
                )
            columns[metric.column] = pct
            weights[metric.column] = metric.weight

        matrix = pd.DataFrame(columns, index=out.index)
        weight_vector = pd.Series(weights)

        present = matrix.notna()
        # Weighted mean over present metrics only; absent ones contribute
        # nothing to either numerator or denominator.
        weighted_sum = (matrix.fillna(0.0) * weight_vector).sum(axis=1)
        weight_total = (present * weight_vector).sum(axis=1)
        out[pillar] = weighted_sum / weight_total.where(weight_total > 0)

        count = present.sum(axis=1)
        share = count / len(metrics)
        out[f"{pillar}_coverage"] = share
        out[f"{pillar}_unreliable"] = share < MIN_PILLAR_COVERAGE

        coverage_report[pillar] = {
            metric.name(): int(matrix[metric.column].notna().sum()) for metric in metrics
        }

    weights_series = pd.Series(PILLAR_WEIGHTS)
    pillar_matrix = out[list(PILLAR_WEIGHTS)]
    present = pillar_matrix.notna()
    weighted_sum = (pillar_matrix.fillna(0.0) * weights_series).sum(axis=1)
    weight_total = (present * weights_series).sum(axis=1)
    out["Overall"] = weighted_sum / weight_total.where(weight_total > 0)

    out["VG"] = out[["Valuation", "Growth"]].mean(axis=1, skipna=True)

    unreliable_cols = [f"{p}_unreliable" for p in PILLARS]
    out["unreliable_flag"] = out[unreliable_cols].apply(
        lambda row: ",".join(p for p, bad in zip(PILLARS, row) if bad), axis=1
    )

    return out, coverage_report


def flag_ahead_of_price(df: pd.DataFrame) -> pd.Series:
    """Strong fundamentals the price has not caught up to yet."""
    def pct_rank(column: str) -> pd.Series:
        return df[column].rank(pct=True) * 100.0

    return (
        (pct_rank("Overall") >= AHEAD_OF_PRICE["overall_min_pct"])
        & (pct_rank("VG") >= AHEAD_OF_PRICE["vg_min_pct"])
        & (pct_rank("Quality") > AHEAD_OF_PRICE["quality_min_pct"])
        & (pct_rank("Momentum") <= AHEAD_OF_PRICE["momentum_max_pct"])
    )


def select(
    df: pd.DataFrame,
    n: int,
    min_per_sector: int,
    max_per_sector: int,
) -> pd.DataFrame:
    """Constrained selection: sector floor first, then fill by Overall."""
    ranked = df.dropna(subset=["Overall"]).sort_values("Overall", ascending=False)
    sectors = sorted(ranked["gics_sector"].unique())

    chosen: list[int] = []
    per_sector: dict[str, int] = {s: 0 for s in sectors}

    # 1. Sector floor - the best name in each GICS sector.
    for sector in sectors:
        block = ranked[ranked["gics_sector"] == sector].head(min_per_sector)
        for idx in block.index:
            chosen.append(idx)
            per_sector[sector] += 1

    # 2. Fill the remainder by Overall, respecting the per-sector cap.
    for idx, row in ranked.iterrows():
        if len(chosen) >= n:
            break
        if idx in chosen:
            continue
        sector = row["gics_sector"]
        if per_sector.get(sector, 0) >= max_per_sector:
            continue
        chosen.append(idx)
        per_sector[sector] = per_sector.get(sector, 0) + 1

    out = df.loc[chosen].sort_values("Overall", ascending=False).reset_index(drop=True)

    # 3. Assert loudly - a silently wrong basket is worse than no basket.
    problems = []
    if len(out) != n:
        problems.append(f"expected exactly {n} picks, got {len(out)}")
    counts = out["gics_sector"].value_counts()
    missing = [s for s in sectors if counts.get(s, 0) < min_per_sector]
    if missing:
        problems.append(f"sectors below the floor of {min_per_sector}: {', '.join(missing)}")
    over = counts[counts > max_per_sector]
    if not over.empty:
        problems.append(f"sectors over the cap of {max_per_sector}: {over.to_dict()}")
    if problems:
        raise AssertionError("Selection constraints violated: " + "; ".join(problems))

    out.insert(0, "Rank", range(1, len(out) + 1))
    return out


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def fmt_cap(x) -> str:
    if pd.isna(x):
        return "-"
    x = float(x)
    for cutoff, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(x) >= cutoff:
            return f"{x / cutoff:.1f}{suffix}"
    return f"{x:.0f}"


def fmt_num(x, places: int = 1) -> str:
    return "-" if pd.isna(x) else f"{float(x):.{places}f}"


def print_coverage(df: pd.DataFrame, report: dict, total: int) -> None:
    print("\n" + "=" * 78)
    print(f"COVERAGE REPORT - how many of {total} companies had real data per metric")
    print("=" * 78)
    rows = []
    for pillar, metrics in report.items():
        if pillar.startswith("_"):
            continue
        for name, count in metrics.items():
            share = count / total * 100 if total else 0
            bar = "#" * int(share / 5)
            rows.append([pillar, name, count, f"{share:.1f}%", bar])
    print(tabulate(rows, headers=["Pillar", "Metric", "n", "coverage", ""], tablefmt="simple"))

    thin = [(p, m, c) for p, ms in report.items() if not p.startswith("_")
            for m, c in ms.items() if total and c / total < 0.80]
    if thin:
        print("\nThin metrics (<80% coverage) - these carry less weight than they appear to:")
        for pillar, metric, count in sorted(thin, key=lambda r: r[2]):
            print(f"  {pillar:<10} {metric:<22} {count}/{total} ({count / total * 100:.1f}%)")

    for note in report.get("_substitutions", [])[:2]:
        print(f"\nSector substitution applied: {note}")

    print("\nPillar reliability (share of companies with a usable pillar):")
    for pillar in PILLARS:
        ok = int((~df[f"{pillar}_unreliable"]).sum())
        print(f"  {pillar:<10} {ok}/{total} reliable "
              f"({ok / total * 100:.1f}%), "
              f"{int(df[f'{pillar}_unreliable'].sum())} flagged unreliable")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Five-pillar percentile screen")
    parser.add_argument("--n", type=int, default=50, help="how many picks (default: 50)")
    parser.add_argument("--min-per-sector", type=int, default=1,
                        help="minimum picks per GICS sector (default: 1)")
    parser.add_argument("--max-per-sector", type=int, default=15,
                        help="maximum picks per GICS sector (default: 15)")
    parser.add_argument("--data", default=str(DATA_CSV), help="input CSV (default: ./data.csv)")
    parser.add_argument("--csv", default=str(BASE / "screen_results.csv"),
                        help="where to write the result CSV")
    parser.add_argument("--no-coverage", action="store_true", help="skip the coverage report")
    args = parser.parse_args(argv)

    try:
        raw = load_data(args.data)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    total = len(raw)
    stamp = "unknown"
    if "fetched_at" in raw.columns:
        stamps = pd.to_datetime(raw["fetched_at"], format="ISO8601", utc=True, errors="coerce")
        if stamps.notna().any():
            stamp = stamps.max().tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M %Z")

    print("=" * 78)
    print(f"FIVE-PILLAR SCREEN   universe: {total} companies   data as of: {stamp}")
    weights = "  ".join(f"{p} {w:.0%}" for p, w in PILLAR_WEIGHTS.items())
    print(f"weights: {weights}")
    print("=" * 78)

    enriched = add_derived_columns(raw)
    scored, coverage = score_pillars(enriched)
    scored["ahead_of_price"] = flag_ahead_of_price(scored)

    if not args.no_coverage:
        print_coverage(scored, coverage, total)

    try:
        picks = select(scored, args.n, args.min_per_sector, args.max_per_sector)
    except AssertionError as exc:
        print(f"\nFATAL: {exc}", file=sys.stderr)
        return 1

    display_columns = [
        ("Rank", "Rank", 0), ("symbol", "Ticker", None), ("shortName", "Company", None),
        ("gics_sector", "Sector", None), ("gics_sub_industry", "Industry", None),
        ("peer_level", "PeerLvl", None), ("marketCap", "MktCap", None),
        ("Overall", "Overall", 1), ("Valuation", "Val", 1), ("Growth", "Grw", 1),
        ("Quality", "Qual", 1), ("Revisions", "Rev", 1), ("Momentum", "Mom", 1),
        ("VG", "VG", 1), ("trailingPE", "TrailPE", 1), ("forwardPE", "FwdPE", 1),
        ("pe_compression", "PEcomp", 2), ("unreliable_flag", "Unreliable", None),
        ("ahead_of_price", "Ahead", None),
    ]

    table = pd.DataFrame()
    for column, header, places in display_columns:
        if column not in picks.columns:
            table[header] = "-"
        elif column == "marketCap":
            table[header] = picks[column].map(fmt_cap)
        elif column == "ahead_of_price":
            table[header] = picks[column].map(lambda v: "YES" if v else "")
        elif column == "peer_level":
            table[header] = picks[column].str.replace("gics_", "", regex=False) \
                                         .str.replace("yahoo_", "y:", regex=False)
        elif places is None:
            table[header] = picks[column].fillna("-").astype(str).str.slice(0, 26)
        else:
            table[header] = picks[column].map(lambda v: fmt_num(v, places))

    print("\n" + "=" * 78)
    print(f"TOP {len(picks)}")
    print("=" * 78)
    print(tabulate(table, headers="keys", tablefmt="simple", showindex=False))

    print("\nSector counts in the final "
          f"{len(picks)} (floor {args.min_per_sector}, cap {args.max_per_sector}):")
    counts = picks["gics_sector"].value_counts().sort_values(ascending=False)
    for sector, count in counts.items():
        print(f"  {sector:<26} {count:>3}  {'#' * count}")
    print(f"  {'TOTAL':<26} {counts.sum():>3}   across {len(counts)} sectors")

    ahead = picks[picks["ahead_of_price"]]
    print(f"\nFundamentals ahead of price ({len(ahead)} of {len(picks)}): "
          f"Overall >= {AHEAD_OF_PRICE['overall_min_pct']}th pct, "
          f"VG >= {AHEAD_OF_PRICE['vg_min_pct']}th, Quality above median, "
          f"Momentum <= {AHEAD_OF_PRICE['momentum_max_pct']}th")
    if len(ahead):
        for _, row in ahead.iterrows():
            print(f"  {row['symbol']:<6} {str(row.get('shortName', ''))[:32]:<34} "
                  f"Overall {row['Overall']:.1f}  VG {row['VG']:.1f}  "
                  f"Qual {row['Quality']:.1f}  Mom {row['Momentum']:.1f}")
    else:
        print("  none in this basket")

    flagged = picks[picks["unreliable_flag"] != ""]
    if len(flagged):
        print(f"\nRows with an unreliable pillar (<{MIN_PILLAR_COVERAGE:.0%} of its metrics): "
              f"{len(flagged)} of {len(picks)}")
        for _, row in flagged.iterrows():
            print(f"  {row['symbol']:<6} {row['unreliable_flag']}")

    out_columns = [c for c, _, _ in display_columns if c in picks.columns]
    extra = [f"{p}_coverage" for p in PILLARS]
    picks[out_columns + [c for c in extra if c in picks.columns]].to_csv(args.csv, index=False)
    print(f"\nWrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
