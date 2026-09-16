"""Nightly wrapper around fetch.py, built to be run by a scheduler.

Design notes (these are the things that make scheduled jobs fail silently):
  * The venv interpreter is resolved by ABSOLUTE path from this file's location.
    Never "python" - a scheduler does not inherit your PATH.
  * The working directory is set explicitly, for the same reason.
  * fetch.py writes to a STAGING file. data.csv is only replaced after the run
    is judged good, so a partial run can never overwrite good data.
  * A run is "good" only if fetch.py exits 0 AND >= MIN_SUCCESS tickers landed.

Usage:
    python run_fetch.py            # nightly mode: clears cache, fetches fresh
    python run_fetch.py --resume   # keep cache, finish an interrupted run
    python run_fetch.py --limit 20 # smoke test (still honours MIN_SUCCESS)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

BASE = Path(__file__).resolve().parent

# Absolute path to the venv interpreter - the #1 cause of silent scheduler failure.
_VENV_PY = (
    BASE / "venv" / "Scripts" / "python.exe"
    if os.name == "nt"
    else BASE / "venv" / "bin" / "python"
)
# CI installs dependencies into the job's own Python rather than a ./venv, so
# fall back to the interpreter running this script - which by definition works.
VENV_PY = _VENV_PY if _VENV_PY.exists() else Path(sys.executable)

FETCH = BASE / "fetch.py"
DATA = BASE / "data.csv"
FIELDS = BASE / "fields.md"
CACHE_DIR = BASE / "cache"
LOG_DIR = BASE / "logs"
HISTORY_DIR = BASE / "history"

STAGE_CSV = BASE / "data.staging.csv"
STAGE_FIELDS = BASE / "fields.staging.md"
STAGE_SUMMARY = BASE / "fetch_summary.json"

MIN_SUCCESS = 400          # below this the run is considered gutted
KEEP_LOGS = 14             # log files
KEEP_HISTORY_DAYS = 90     # history snapshots
RUN_TIMEOUT_SECONDS = 2 * 60 * 60

EXIT_OK = 0
EXIT_TOO_FEW = 1
EXIT_FETCH_FAILED = 2
EXIT_WRAPPER_ERROR = 3


def log_path(now: datetime) -> Path:
    return LOG_DIR / f"fetch_{now:%Y%m%d}.log"


def rotate_logs() -> list[str]:
    """Keep only the newest KEEP_LOGS log files."""
    logs = sorted(LOG_DIR.glob("fetch_*.log"), key=lambda p: p.name)
    removed = []
    for old in logs[:-KEEP_LOGS] if len(logs) > KEEP_LOGS else []:
        try:
            old.unlink()
            removed.append(old.name)
        except OSError:
            pass
    return removed


def rotate_history(today: datetime) -> list[str]:
    """Drop history snapshots older than KEEP_HISTORY_DAYS."""
    cutoff = (today - timedelta(days=KEEP_HISTORY_DAYS)).date()
    removed = []
    for snap in HISTORY_DIR.glob("data_*.csv"):
        stamp = snap.stem.removeprefix("data_")
        try:
            snap_date = datetime.strptime(stamp, "%Y%m%d").date()
        except ValueError:
            continue  # unrecognised name, leave it alone
        if snap_date < cutoff:
            try:
                snap.unlink()
                removed.append(snap.name)
            except OSError:
                pass
    return removed


MARKET_TZ = ZoneInfo("America/New_York")


def data_vintage(path: Path) -> datetime:
    """The date the data in `path` actually describes.

    Read from the fetched_at column and expressed in market time, NOT from the
    file's mtime: a CI checkout stamps every file with the checkout time, which
    would label yesterday's numbers as today's and corrupt score-drift history.
    Falls back to mtime only if fetched_at cannot be read.
    """
    try:
        stamps = pd.read_csv(path, usecols=["fetched_at"])["fetched_at"]
        latest = pd.to_datetime(stamps, format="ISO8601", utc=True).max()
        if pd.notna(latest):
            return latest.tz_convert(MARKET_TZ)
    except Exception:  # noqa: BLE001 - any parse problem falls back to mtime
        pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def archive_current_data() -> Path | None:
    """Copy the existing data.csv into history/, named for the data's own vintage."""
    if not DATA.exists():
        return None
    vintage = data_vintage(DATA)
    dest = HISTORY_DIR / f"data_{vintage:%Y%m%d}.csv"
    shutil.copy2(DATA, dest)
    return dest


def clear_cache() -> int:
    """Remove per-ticker cache so the nightly run fetches genuinely fresh data."""
    if not CACHE_DIR.exists():
        return 0
    n = 0
    for f in CACHE_DIR.glob("*.json"):
        try:
            f.unlink()
            n += 1
        except OSError:
            pass
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nightly data.csv refresh")
    parser.add_argument("--resume", action="store_true",
                        help="keep the cache (finish an interrupted run) instead of refetching")
    parser.add_argument("--limit", type=int, default=None, help="pass --limit through to fetch.py")
    parser.add_argument("--min-success", type=int, default=MIN_SUCCESS,
                        help=f"fail the run below this many tickers (default: {MIN_SUCCESS})")
    parser.add_argument("--throttle", type=float, default=None,
                        help="pass --throttle through to fetch.py (CI uses a larger value)")
    parser.add_argument("--max-retries", type=int, default=None,
                        help="pass --max-retries through to fetch.py")
    args = parser.parse_args(argv)

    for d in (LOG_DIR, HISTORY_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)

    started = datetime.now()
    logfile = log_path(started)

    # Append, so two runs on the same day both leave a record.
    with logfile.open("a", encoding="utf-8") as lf:
        def say(msg: str = "") -> None:
            lf.write(msg + "\n")
            lf.flush()

        rc = EXIT_WRAPPER_ERROR
        try:
            say("=" * 72)
            say(f"RUN START      {started:%Y-%m-%d %H:%M:%S} (local)")
            say(f"host / user    {os.environ.get('COMPUTERNAME', '?')} / {os.environ.get('USERNAME', '?')}")
            say(f"interpreter    {VENV_PY}")
            say(f"working dir    {BASE}")
            say(f"mode           {'resume (cache kept)' if args.resume else 'fresh (cache cleared)'}")
            say("=" * 72)

            if not VENV_PY.exists():
                say(f"FATAL: venv interpreter not found at {VENV_PY}")
                say(f"EXIT CODE      {EXIT_WRAPPER_ERROR}")
                return EXIT_WRAPPER_ERROR
            if not FETCH.exists():
                say(f"FATAL: fetch.py not found at {FETCH}")
                say(f"EXIT CODE      {EXIT_WRAPPER_ERROR}")
                return EXIT_WRAPPER_ERROR

            if not args.resume:
                say(f"cleared {clear_cache()} cached ticker files")

            for stale in (STAGE_CSV, STAGE_FIELDS, STAGE_SUMMARY):
                stale.unlink(missing_ok=True)

            cmd = [
                str(VENV_PY), str(FETCH),
                "--out", str(STAGE_CSV),
                "--fields", str(STAGE_FIELDS),
                "--summary-json", str(STAGE_SUMMARY),
            ]
            if args.limit is not None:
                cmd += ["--limit", str(args.limit)]
            if args.throttle is not None:
                cmd += ["--throttle", str(args.throttle)]
            if args.max_retries is not None:
                cmd += ["--max-retries", str(args.max_retries)]
            say(f"command        {' '.join(cmd)}")
            say("-" * 72)

            # cwd is set explicitly; the scheduler will not provide one.
            # CREATE_NO_WINDOW is load-bearing, not cosmetic: under pythonw.exe
            # the parent has no console, so a console child gets a freshly
            # allocated one and dies instantly with STATUS_CONTROL_C_EXIT
            # (0xC000013A). Giving it no console at all avoids that entirely,
            # and also guarantees no window ever flashes up.
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(
                cmd, cwd=str(BASE),
                stdout=lf, stderr=subprocess.STDOUT,
                text=True,
                creationflags=creation_flags,
            )
            try:
                fetch_rc = proc.wait(timeout=RUN_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                fetch_rc = -1
                say(f"FATAL: fetch.py exceeded {RUN_TIMEOUT_SECONDS}s and was killed")

            say("-" * 72)

            summary: dict = {}
            if STAGE_SUMMARY.exists():
                try:
                    summary = json.loads(STAGE_SUMMARY.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    say("WARNING: summary json was unreadable")

            attempted = summary.get("attempted", 0)
            succeeded = summary.get("succeeded", 0)
            failed = summary.get("failed", 0)
            rate_limits = summary.get("rate_limit_hits", 0)
            runtime = (datetime.now() - started).total_seconds()

            say(f"tickers attempted   {attempted}")
            say(f"tickers succeeded   {succeeded}")
            say(f"tickers failed      {failed}")
            say(f"429 / rate limits   {rate_limits}")
            say(f"fetch.py exit code  {fetch_rc}")
            say(f"total runtime       {runtime:.1f}s ({runtime / 60:.1f} min)")

            for f in summary.get("failures", []):
                say(f"  FAILED {f.get('symbol')}: {f.get('error')}")
            missing = summary.get("missing_sector", [])
            if missing:
                say(f"sector -> Unknown   {len(missing)}: {', '.join(missing)}")

            good = fetch_rc == 0 and succeeded >= args.min_success and STAGE_CSV.exists()

            if not good:
                if fetch_rc != 0:
                    reason = f"fetch.py exited {fetch_rc}"
                    rc = EXIT_FETCH_FAILED
                elif not STAGE_CSV.exists():
                    reason = "staging CSV was never written"
                    rc = EXIT_FETCH_FAILED
                else:
                    reason = f"only {succeeded} tickers succeeded, need >= {args.min_success}"
                    rc = EXIT_TOO_FEW
                say("")
                say(f"RESULT         FAILED - {reason}")
                say(f"data.csv       LEFT UNCHANGED (previous good data preserved)")
                for stale in (STAGE_CSV, STAGE_FIELDS):
                    stale.unlink(missing_ok=True)
            else:
                archived = archive_current_data()
                say("")
                say(f"archived       {archived if archived else 'nothing (no previous data.csv)'}")
                # Same volume, so this is an atomic swap.
                os.replace(STAGE_CSV, DATA)
                os.replace(STAGE_FIELDS, FIELDS)
                say(f"data.csv       REPLACED ({succeeded} rows)")
                rc = EXIT_OK
                say(f"RESULT         OK")

            dropped_logs = rotate_logs()
            dropped_hist = rotate_history(started)
            say(f"log rotation   keeping {KEEP_LOGS}"
                + (f", removed {', '.join(dropped_logs)}" if dropped_logs else ", nothing to remove"))
            say(f"history        keeping {KEEP_HISTORY_DAYS}d"
                + (f", removed {', '.join(dropped_hist)}" if dropped_hist else ", nothing to remove"))

        except Exception:
            # pythonw.exe has no console, so an unhandled error would vanish.
            say("")
            say("FATAL: unhandled wrapper exception")
            say(traceback.format_exc())
            rc = EXIT_WRAPPER_ERROR

        say(f"EXIT CODE      {rc}")
        say(f"RUN END        {datetime.now():%Y-%m-%d %H:%M:%S}")
        say("")
        return rc


if __name__ == "__main__":
    sys.exit(main())
