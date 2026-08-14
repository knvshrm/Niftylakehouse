#!/usr/bin/env bash
# Same as quickstart_demo.sh, but pulls ONE real snapshot from NSE instead
# of generating fake data. Run this on your own laptop/PC — it will NOT
# work inside an environment with restricted internet access (like the
# sandbox this project was originally built in), because NSE requires a
# normal internet connection and blocks non-browser requests without one.
#
# Run it once every few minutes during market hours (9:15 AM - 3:30 PM IST)
# to build up a real time-series, same as the demo's 6-snapshots-per-day.
set -e
cd "$(dirname "$0")"

echo "Installing dependencies..."
pip install -r requirements.txt --break-system-packages -q

echo ""
echo "1/4  Fetching ONE real live snapshot from NSE (NIFTY)..."
cd ingestion && python3 nse_option_chain_client.py NIFTY && cd ..

echo ""
echo "2/4  Building bronze -> silver -> gold from what's in data/bronze..."
python3 run_pipeline.py

echo ""
echo "3/4  Exporting dashboard data..."
cd dashboard && python3 export_gold_json.py && cd ..

echo ""
echo "4/4  Done. Open dashboard/dashboard.html to see it."
echo "     Re-run this script every ~15 min during market hours to add more"
echo "     snapshots — buildup/PCR-trend charts get more meaningful with more data."
