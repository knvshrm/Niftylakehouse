"""
Silver -> Gold
==============
Runs the analytics/metrics.py functions across every snapshot in silver and
writes two gold tables:

  gold.snapshot_metrics   - one row per snapshot: PCR, Max Pain, IV skew
  gold.oi_buildup         - one row per (snapshot, strike, side): OI buildup
                             classification vs. the prior snapshot

These are the tables a dashboard or paid API would actually read from —
small, pre-aggregated, no raw option-chain scanning needed at query time.
"""

import sys
from pathlib import Path

import pandas as pd
from deltalake import DeltaTable, write_deltalake

sys.path.append(str(Path(__file__).parent.parent))
from analytics.metrics import snapshot_summary, oi_buildup_classification, max_pain

SILVER_TABLE = str(Path(__file__).parent.parent / "data" / "silver" / "option_chain_ticks")
GOLD_METRICS_TABLE = str(Path(__file__).parent.parent / "data" / "gold" / "snapshot_metrics")
GOLD_BUILDUP_TABLE = str(Path(__file__).parent.parent / "data" / "gold" / "oi_buildup")


def load_silver() -> pd.DataFrame:
    return DeltaTable(SILVER_TABLE).to_pandas()


def run():
    df = load_silver()
    groups = list(df.groupby(["symbol", "snapshot_ts"], sort=True))

    metrics_rows = []
    buildup_rows = []
    prev_key = None
    prev_snap = None

    for (symbol, ts), snap in groups:
        summary = snapshot_summary(snap)
        summary["symbol"] = symbol
        mp = summary["max_pain"]
        summary["distance_to_max_pain_pct"] = round(
            (summary["underlying_value"] - mp) / mp * 100, 3
        )
        metrics_rows.append(summary)

        if prev_snap is not None and prev_key[0] == symbol:
            buildup = oi_buildup_classification(snap, prev_snap)
            buildup["symbol"] = symbol
            buildup["snapshot_ts"] = ts
            buildup_rows.append(buildup)

        prev_key, prev_snap = (symbol, ts), snap

    metrics_df = pd.DataFrame(metrics_rows)
    metrics_df["trading_date"] = pd.to_datetime(metrics_df["snapshot_ts"]).dt.date.astype(str)
    write_deltalake(GOLD_METRICS_TABLE, metrics_df, mode="overwrite",
                     partition_by=["symbol", "trading_date"])

    buildup_df = pd.concat(buildup_rows, ignore_index=True) if buildup_rows else pd.DataFrame()
    if not buildup_df.empty:
        buildup_df["trading_date"] = pd.to_datetime(buildup_df["snapshot_ts"]).dt.date.astype(str)
        write_deltalake(GOLD_BUILDUP_TABLE, buildup_df, mode="overwrite",
                         partition_by=["symbol", "trading_date"])

    print(f"gold.snapshot_metrics: {len(metrics_df)} rows")
    print(metrics_df.tail(5).to_string())
    print(f"\ngold.oi_buildup: {len(buildup_df)} rows")
    if not buildup_df.empty:
        print(buildup_df.classification.value_counts().to_string())

    return metrics_df, buildup_df


if __name__ == "__main__":
    run()
