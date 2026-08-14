#!/usr/bin/env bash
# One command to run the whole demo: generate sample data -> build the
# lakehouse -> export the dashboard. Uses fake-but-realistic data.
set -e
cd "$(dirname "$0")"

echo "Installing dependencies..."
pip install -r requirements.txt --break-system-packages -q

echo ""
echo "1/4  Generating sample option-chain data (8 trading days)..."
cd ingestion && python3 synthetic_data_generator.py 8 && cd ..

echo ""
echo "2/4  Building bronze -> silver -> gold..."
python3 run_pipeline.py

echo ""
echo "3/4  Exporting dashboard data..."
cd dashboard && python3 export_gold_json.py && cd ..

echo ""
echo "4/4  Done. Open dashboard/dashboard.html in your browser to see it."
