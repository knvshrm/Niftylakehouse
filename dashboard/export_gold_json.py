"""Exports gold.snapshot_metrics and gold.oi_buildup (latest snapshot) to
JSON files the static dashboard/dashboard.html reads client-side."""

import json
from pathlib import Path

from deltalake import DeltaTable

ROOT = Path(__file__).parent.parent
GOLD_METRICS = str(ROOT / "data" / "gold" / "snapshot_metrics")
GOLD_BUILDUP = str(ROOT / "data" / "gold" / "oi_buildup")
OUT_DIR = Path(__file__).parent


def run():
    metrics = DeltaTable(GOLD_METRICS).to_pandas().sort_values("snapshot_ts")
    metrics["snapshot_ts"] = metrics["snapshot_ts"].astype(str)
    metrics.to_json(OUT_DIR / "snapshot_metrics.json", orient="records")

    buildup = DeltaTable(GOLD_BUILDUP).to_pandas()
    latest_ts = buildup["snapshot_ts"].max()
    latest = buildup[buildup["snapshot_ts"] == latest_ts].copy()
    latest["snapshot_ts"] = latest["snapshot_ts"].astype(str)
    latest.sort_values("strike_price").to_json(OUT_DIR / "oi_buildup_latest.json", orient="records")

    print(f"Exported {len(metrics)} metric rows, {len(latest)} latest-snapshot buildup rows")


if __name__ == "__main__":
    run()
