"""Sector-relative factor screener over data.csv.

Library use:
    from screen import screen
    top = screen(
        gates=["marketCap > 20e9", "freeCashflow > 0"],
        weights={"revenueGrowth": (0.4, "high"), "forwardPE": (0.6, "low")},
        n=25,
    )

CLI use:
    python screen.py --gates "marketCap>20e9" "forwardPE<25" \
        --weights "revenueGrowth:0.4:high" "returnOnEquity:0.3:high" "forwardPE:0.3:low" \
        --n 25
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from tabulate import tabulate

DATA_CSV = Path(__file__).resolve().parent / "data.csv"

# A sector needs at least this many gate survivors before we trust its internal
# ranking; below it, those rows are ranked against the whole surviving universe.
MIN_SECTOR_MEMBERS = 8

NEUTRAL_PERCENTILE = 0.5  # what a NaN factor value scores


def load_data(path: str | Path = DATA_CSV) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - run fetch.py first")
    df = pd.read_csv(path, low_memory=False)
    if "symbol" not in df.columns:
        raise ValueError(f"{path} has no 'symbol' column")
    if "sector" not in df.columns:
        raise ValueError(f"{path} has no 'sector' column")
    df["sector"] = df["sector"].fillna("Unknown")
    return df


# --------------------------------------------------------------------------
# Gates
# --------------------------------------------------------------------------
def apply_gates(df: pd.DataFrame, gates: list[str] | None, verbose: bool = False) -> pd.DataFrame:
    """Apply each boolean expression in turn. NaN never passes a comparison."""
    if not gates:
        return df

    out = df
    for expr in gates:
        try:
            mask = out.eval(expr, engine="python")
        except Exception as exc:  # noqa: BLE001 - surface the user's bad expression clearly
            raise ValueError(f"could not evaluate gate {expr!r}: {exc}") from exc

        if not isinstance(mask, pd.Series) or mask.dtype != bool:
            mask = pd.Series(mask, index=out.index).astype("boolean").fillna(False).astype(bool)
        else:
            mask = mask.fillna(False)

        before = len(out)
        out = out[mask]
        if verbose:
            print(f"  gate {expr!r}: {before} -> {len(out)}")
    return out.copy()


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------
def factor_percentile(
    df: pd.DataFrame,
    col: str,
    direction: str,
    min_sector_members: int = MIN_SECTOR_MEMBERS,
) -> pd.Series:
    """Percentile rank of `col` within sector, 0-1, higher is always better.

    - NaN scores NEUTRAL_PERCENTILE (0.5) rather than being dropped.
    - Sectors with fewer than `min_sector_members` rows fall back to a
      whole-universe rank, because a 3-name sector percentile is noise.
    - direction "low" inverts the rank so small values score high.
    """
    direction = direction.lower()
    if direction not in ("high", "low"):
        raise ValueError(f"direction for {col!r} must be 'high' or 'low', got {direction!r}")
    if col not in df.columns:
        raise ValueError(f"column {col!r} is not in the data")

    values = pd.to_numeric(df[col], errors="coerce")
    sectors = df["sector"]

    sector_pct = values.groupby(sectors).rank(pct=True)
    universe_pct = values.rank(pct=True)

    sector_sizes = sectors.map(sectors.value_counts())
    pct = sector_pct.where(sector_sizes >= min_sector_members, universe_pct)

    pct = pct.fillna(NEUTRAL_PERCENTILE)
    if direction == "low":
        pct = 1.0 - pct
    return pct


def screen(
    gates: list[str] | None = None,
    weights: dict[str, tuple[float, str]] | None = None,
    n: int = 25,
    data: pd.DataFrame | str | Path | None = None,
    min_sector_members: int = MIN_SECTOR_MEMBERS,
    verbose: bool = False,
) -> pd.DataFrame:
    """Gate the universe, score survivors on weighted sector-relative factors.

    gates:   boolean expression strings, e.g. ["marketCap > 20e9"]
    weights: {column: (weight, "high"|"low")}
    n:       how many rows to return
    Returns the top n with one `<factor>_pct` column per factor and a 0-100 `score`.
    """
    if isinstance(data, pd.DataFrame):
        df = data.copy()
    else:
        df = load_data(data if data is not None else DATA_CSV)

    if not weights:
        raise ValueError("weights is required: {column: (weight, 'high'|'low')}")

    total_weight = sum(float(w) for w, _ in weights.values())
    if total_weight <= 0:
        raise ValueError("weights must sum to a positive number")

    if verbose:
        print(f"universe: {len(df)} rows")
    survivors = apply_gates(df, gates, verbose=verbose)
    if survivors.empty:
        return survivors.assign(score=pd.Series(dtype=float))

    if verbose:
        small = [
            f"{s} ({c})"
            for s, c in survivors["sector"].value_counts().items()
            if c < min_sector_members
        ]
        if small:
            print(f"  whole-universe rank fallback for: {', '.join(small)}")

    out = survivors.copy()
    score = pd.Series(0.0, index=out.index)
    pct_cols: list[str] = []

    for col, spec in weights.items():
        weight, direction = float(spec[0]), spec[1]
        pct = factor_percentile(out, col, direction, min_sector_members)
        pct_col = f"{col}_pct"
        out[pct_col] = pct
        pct_cols.append(pct_col)
        score = score + weight * pct

    out["score"] = (score / total_weight) * 100.0

    # symbol, name, sector, then each factor's raw value beside its percentile.
    lead = [c for c in ("symbol", "shortName", "sector", "industry") if c in out.columns]
    factor_cols: list[str] = []
    for col in weights:
        factor_cols.extend([col, f"{col}_pct"])
    ordered = lead + factor_cols + ["score"]
    ordered = list(dict.fromkeys(ordered))

    return out.sort_values("score", ascending=False).head(n)[ordered].reset_index(drop=True)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def parse_weight_spec(specs: list[str]) -> dict[str, tuple[float, str]]:
    """Parse ["revenueGrowth:0.4:high", ...] into {col: (weight, direction)}."""
    weights: dict[str, tuple[float, str]] = {}
    for spec in specs:
        parts = spec.split(":")
        if len(parts) != 3:
            raise ValueError(f"bad --weights entry {spec!r}, expected column:weight:high|low")
        col, raw_weight, direction = (p.strip() for p in parts)
        try:
            weight = float(raw_weight)
        except ValueError as exc:
            raise ValueError(f"bad weight in {spec!r}: {raw_weight!r} is not a number") from exc
        if direction.lower() not in ("high", "low"):
            raise ValueError(f"bad direction in {spec!r}: expected 'high' or 'low'")
        weights[col] = (weight, direction.lower())
    return weights


def human(x: object) -> str:
    """Compact display formatting; percentiles and scores keep 2 decimals."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "-"
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        v = float(x)
        a = abs(v)
        if a >= 1e12:
            return f"{v / 1e12:.2f}T"
        if a >= 1e9:
            return f"{v / 1e9:.2f}B"
        if a >= 1e6:
            return f"{v / 1e6:.2f}M"
        if a >= 1000:
            return f"{v:,.0f}"
        return f"{v:.2f}"
    return str(x)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Screen data.csv with hard gates plus weighted sector-relative factor ranks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "example:\n"
            '  python screen.py --gates "marketCap>20e9" "forwardPE<25" \\\n'
            '      --weights "revenueGrowth:0.4:high" "returnOnEquity:0.3:high" "forwardPE:0.3:low" \\\n'
            "      --n 25"
        ),
    )
    parser.add_argument("--gates", nargs="*", default=[], help='boolean expressions, e.g. "marketCap>20e9"')
    parser.add_argument("--weights", nargs="+", required=True, help="column:weight:high|low")
    parser.add_argument("--n", type=int, default=25, help="rows to show (default: 25)")
    parser.add_argument("--data", default=str(DATA_CSV), help="input CSV (default: ./data.csv)")
    parser.add_argument("--min-sector", type=int, default=MIN_SECTOR_MEMBERS,
                        help=f"sector size below which ranks fall back to the whole universe (default: {MIN_SECTOR_MEMBERS})")
    parser.add_argument("--csv", default=None, help="also write the result to this CSV path")
    parser.add_argument("--quiet", action="store_true", help="table only, no gate/fallback commentary")
    args = parser.parse_args(argv)

    try:
        weights = parse_weight_spec(args.weights)
        result = screen(
            gates=args.gates,
            weights=weights,
            n=args.n,
            data=args.data,
            min_sector_members=args.min_sector,
            verbose=not args.quiet,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if result.empty:
        print("\nNo stocks passed the gates.")
        return 0

    display = result.copy()
    for col in display.columns:
        display[col] = display[col].map(human)
    display.insert(0, "#", range(1, len(display) + 1))

    if not args.quiet:
        print(f"\nTop {len(result)} of the gated universe:")
    print(tabulate(display, headers="keys", tablefmt="simple_outline", showindex=False))

    if args.csv:
        result.to_csv(args.csv, index=False)
        print(f"\nwrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
