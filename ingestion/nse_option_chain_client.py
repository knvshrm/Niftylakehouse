"""
NSE Option Chain Client (real data)
=====================================
Wraps `jugaad-data` (https://github.com/jugaad-py/jugaad-data), an actively
maintained open-source library that handles NSE's session/cookie/header
requirements — instead of hand-rolling that logic, which breaks every time
NSE tweaks its anti-bot measures. `index_option_chain()` returns the same
raw JSON shape (`records.data[]` with CE/PE blocks per strike) that
synthetic_data_generator.py emits, so nothing downstream (bronze/silver/gold)
needs to change.

WHY THIS DOESN'T RUN IN THIS SANDBOX:
Verified directly — this sandbox's network egress only allows package
registries (pypi, npm, github, etc), not nseindia.com, so a raw request
never leaves the box. Separately, NSE also blocks non-browser-session
requests outright (confirmed via a direct fetch attempt), so even a tool
with unrestricted network access needs jugaad-data's real header/cookie
handling to get through — a plain `requests.get()` will still be refused.
Run this file on your own machine (or a scheduled job with normal internet
access) and it will pull live data with no other changes to the pipeline.

Usage:
    pip install jugaad-data
    python3 nse_option_chain_client.py NIFTY
"""

import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from jugaad_data.nse import NSELive


@dataclass
class RawSnapshot:
    symbol: str
    fetched_at_utc: str
    source: str
    payload: dict


class NSEOptionChainClient:
    def __init__(self, min_interval_seconds: int = 90):
        self.nse = NSELive()  # handles session warmup + NSE's browser-like headers
        self.min_interval = min_interval_seconds
        self._last_call = 0.0

    def _throttle(self):
        elapsed = time.time() - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def fetch(self, symbol: str = "NIFTY", retries: int = 3) -> RawSnapshot:
        self._throttle()
        last_exc = None
        for attempt in range(retries):
            try:
                payload = self.nse.index_option_chain(symbol)
                self._last_call = time.time()
                return RawSnapshot(
                    symbol=symbol,
                    fetched_at_utc=datetime.now(timezone.utc).isoformat(),
                    source="nse_live",
                    payload=payload,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"Failed to fetch {symbol} option chain") from last_exc

    def write_bronze(self, snapshot: RawSnapshot, bronze_dir: str):
        out_dir = Path(bronze_dir) / snapshot.symbol
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = snapshot.fetched_at_utc.replace(":", "-")
        out_path = out_dir / f"{ts}.json"
        out_path.write_text(json.dumps(asdict(snapshot)))
        return str(out_path)


if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "NIFTY"
    client = NSEOptionChainClient(min_interval_seconds=0)
    snap = client.fetch(symbol)
    path = client.write_bronze(snap, "../data/bronze")
    spot = snap.payload["records"]["underlyingValue"]
    n_strikes = len(snap.payload["records"]["data"])
    print(f"Wrote {path}")
    print(f"  {symbol} spot: {spot}  |  strikes: {n_strikes}")
