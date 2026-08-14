"""
Automated Scheduler (local)
=============================
Run this ONCE and leave it running — it automatically fetches NSE data
every 15 minutes during market hours (9:15 AM - 3:30 PM IST, Mon-Fri),
rebuilds bronze -> silver -> gold, and refreshes the dashboard JSON.
No manual re-running of anything.

Usage:
    python3 scheduler.py

Leave the terminal window open (or use nohup/a service — see README's
"Keeping this running" section — to survive closing the terminal).
Press Ctrl+C to stop.

This is the SIMPLE automation option: it requires your computer to be on
and this script to be running. For automation that works even when your
laptop is off, see .github/workflows/scheduled_ingest.yml instead (runs
in the cloud on a schedule, free, via GitHub Actions).
"""

import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = (9, 15)   # 9:15 AM IST
MARKET_CLOSE = (15, 30)  # 3:30 PM IST
POLL_INTERVAL_SECONDS = 15 * 60  # 15 minutes
IDLE_CHECK_SECONDS = 5 * 60      # how often to check "has the market opened yet"

LOG_FILE = Path(__file__).parent / "scheduler.log"


def log(msg: str):
    line = f"[{datetime.now(IST).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def is_market_hours(now: datetime) -> bool:
    if now.weekday() >= 5:  # Sat=5, Sun=6
        return False
    open_t = now.replace(hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0, microsecond=0)
    close_t = now.replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0, microsecond=0)
    return open_t <= now <= close_t


def run_one_cycle():
    from ingestion.nse_option_chain_client import NSEOptionChainClient
    from pipeline.bronze_to_silver import run as bronze_to_silver
    from pipeline.silver_to_gold import run as silver_to_gold
    from dashboard.export_gold_json import run as export_dashboard

    client = NSEOptionChainClient(min_interval_seconds=0)
    for symbol in ("NIFTY",):  # add "BANKNIFTY" here too if you want both
        snap = client.fetch(symbol)
        path = client.write_bronze(snap, "data/bronze")
        log(f"Fetched {symbol}: spot={snap.payload['records']['underlyingValue']} -> {path}")

    bronze_to_silver()
    silver_to_gold()
    export_dashboard()
    log("Pipeline refreshed: silver + gold + dashboard JSON updated.")


def main():
    log("Scheduler started. Waiting for market hours (9:15-15:30 IST, Mon-Fri)...")
    while True:
        now = datetime.now(IST)
        if is_market_hours(now):
            try:
                run_one_cycle()
            except Exception:
                log("ERROR during cycle:\n" + traceback.format_exc())
            time.sleep(POLL_INTERVAL_SECONDS)
        else:
            time.sleep(IDLE_CHECK_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Scheduler stopped by user.")
