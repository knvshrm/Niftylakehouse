"""
Bronze -> Silver
================
Reads raw option-chain JSON snapshots (bronze), flattens each strike/side
into a typed row, and writes a Delta Lake table (silver.option_chain_ticks).

This is the "make it queryable" layer: one row per (snapshot, strike, side),
correctly typed, deduplicated, with the underlying spot price attached to
every row so downstream analytics don't need to re-join anything.
"""

import json
from pathlib import Path

import pandas as pd
from deltalake import write_deltalake, DeltaTable


BRONZE_DIR = Path(__file__).parent.parent / "data" / "bronze"
SILVER_TABLE = str(Path(__file__).parent.parent / "data" / "silver" / "option_chain_ticks")


def _flatten_snapshot(raw: dict) -> list[dict]:
    symbol = raw["symbol"]
    fetched_at = raw["fetched_at_utc"]
    source = raw["source"]
    records = raw["payload"]["records"]
    spot = records["underlyingValue"]
    snapshot_ts = records["timestamp"]

    rows = []
    for entry in records["data"]:
        strike = entry["strikePrice"]
        expiry = entry["expiryDate"]
        for side in ("CE", "PE"):
            if side not in entry:
                continue
            leg = entry[side]
            rows.append({
                "symbol": symbol,
                "snapshot_ts": snapshot_ts,
                "fetched_at_utc": fetched_at,
                "source": source,
                "expiry_date": expiry,
                "strike_price": float(strike),
                "option_type": side,  # CE / PE
                "underlying_value": float(spot),
                "open_interest": int(leg.get("openInterest", 0)),
                "change_in_oi": int(leg.get("changeinOpenInterest", 0)),
                "traded_volume": int(leg.get("totalTradedVolume", 0)),
                "implied_volatility": float(leg.get("impliedVolatility", 0.0)),
                "last_price": float(leg.get("lastPrice", 0.0)),
            })
    return rows


def load_bronze() -> pd.DataFrame:
    all_rows = []
    for symbol_dir in BRONZE_DIR.iterdir():
        if not symbol_dir.is_dir():
            continue
        for f in symbol_dir.glob("*.json"):
            raw = json.loads(f.read_text())
            all_rows.extend(_flatten_snapshot(raw))
    if not all_rows:
        raise RuntimeError(f"No bronze files found under {BRONZE_DIR}")
    df = pd.DataFrame(all_rows)

    # Types + dedup: a rerun of the same snapshot shouldn't duplicate rows
    df["snapshot_ts"] = pd.to_datetime(df["snapshot_ts"])
    df["fetched_at_utc"] = pd.to_datetime(df["fetched_at_utc"])
    df["trading_date"] = df["snapshot_ts"].dt.date.astype(str)
    df = df.drop_duplicates(
        subset=["symbol", "snapshot_ts", "strike_price", "option_type"]
    ).sort_values(["snapshot_ts", "strike_price", "option_type"])
    return df.reset_index(drop=True)


def write_silver(df: pd.DataFrame, mode: str = "overwrite"):
    write_deltalake(SILVER_TABLE, df, mode=mode, partition_by=["symbol", "trading_date"])


def run():
    df = load_bronze()
    write_silver(df)
    dt = DeltaTable(SILVER_TABLE)
    print(f"Silver table written: {len(df)} rows, {dt.version()=}")
    print(df.head(3).to_string())
    return df


if __name__ == "__main__":
    run()
