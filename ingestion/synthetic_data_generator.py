"""
Synthetic Option Chain Generator
=================================
Emits raw snapshots in the SAME shape NSE's option-chain API returns
(records.data[] with CE/PE blocks per strike), so the bronze/silver/gold
pipeline downstream is byte-for-byte identical whether the source is this
generator or the real NSEOptionChainClient.

Simulates a trading day: opening spot, intraday drift with realistic vol,
OI building up around ATM strikes, IV skew (puts richer than calls in a
selloff, calls richer in a rally), and multiple snapshots over the day so
gold-layer OI-buildup / PCR-trend logic has real time-series to work with.
"""

import json
import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass
class RawSnapshot:
    symbol: str
    fetched_at_utc: str
    source: str
    payload: dict


def _strike_ladder(spot: float, step: int = 50, width: int = 12):
    base = round(spot / step) * step
    return [base + i * step for i in range(-width, width + 1)]


def _bs_like_iv(base_iv: float, moneyness: float, skew_bias: float):
    """Cheap smile approximation: IV rises away from ATM (moneyness = (K-S)/S),
    and skew_bias tilts it so low strikes (skew_bias>0) or high strikes
    (skew_bias<0) trade richer — i.e. genuine directional skew, not symmetric."""
    smile = 0.04 * (moneyness ** 2)
    skew = -skew_bias * moneyness  # negative moneyness (low strikes) richer when skew_bias>0
    return max(8.0, base_iv + smile * 100 + skew * 100)


def generate_day(
    symbol: str = "NIFTY",
    trading_date: str = None,
    open_spot: float = 24650.0,
    snapshots: int = 6,
    seed: int = 42,
):
    """
    Returns a list[RawSnapshot] simulating `snapshots` option-chain pulls
    across one trading day (e.g. 9:20, 10:15, 11:30, 13:00, 14:15, 15:15).
    """
    rng = random.Random(seed)
    trading_date = trading_date or datetime.now(timezone.utc).date().isoformat()
    times = ["09:20", "10:15", "11:30", "13:00", "14:15", "15:15"][:snapshots]

    spot = open_spot
    # Drift regime for the day: mildly bullish, mildly bearish, or choppy
    regime = rng.choice(["bullish", "bearish", "choppy"])
    drift_map = {"bullish": 0.0009, "bearish": -0.0009, "choppy": 0.0}
    skew_bias = {"bullish": -0.15, "bearish": 0.35, "choppy": 0.05}[regime]

    out = []
    # Track running OI per strike/side so buildup/unwinding is coherent
    strikes0 = _strike_ladder(spot)
    running_oi = {(k, side): rng.randint(400_000, 1_800_000)
                  for k in strikes0 for side in ("CE", "PE")}

    for t in times:
        # random-walk the spot within the day
        spot *= (1 + rng.gauss(drift_map[regime], 0.0022))
        strikes = _strike_ladder(spot)

        data = []
        total_ce_oi = total_pe_oi = 0
        for k in strikes:
            moneyness = (k - spot) / spot
            # IV is a function of strike (the "smile"), not option type — CE and
            # PE at the same strike share ~the same vol via put-call parity.
            # skew_bias>0 means low strikes (OTM puts) trade richer than high
            # strikes (OTM calls) => fear/downside-protection premium.
            strike_iv = _bs_like_iv(13.0, moneyness, skew_bias=skew_bias)

            for side, iv in (("CE", strike_iv), ("PE", strike_iv)):
                key = (k, side)
                prev_oi = running_oi.get(key, rng.randint(300_000, 900_000))
                # OI drifts, with extra buildup near ATM
                atm_boost = max(0, 1 - abs(moneyness) * 40)
                change = int(rng.gauss(0, 60_000) + atm_boost * rng.randint(-40_000, 90_000))
                new_oi = max(10_000, prev_oi + change)
                running_oi[key] = new_oi

                intrinsic = max(0.0, (spot - k) if side == "CE" else (k - spot))
                time_value = max(1.0, iv * math.sqrt(1 / 365) * spot * 0.4 / 100)
                ltp = round(intrinsic + time_value, 2)

                data.append({
                    "strikePrice": k,
                    "expiryDate": _next_weekly_expiry(trading_date),
                    "identifier": f"OPTIDX{symbol}{side}{k}",
                    side: {
                        "openInterest": new_oi,
                        "changeinOpenInterest": new_oi - prev_oi,
                        "totalTradedVolume": rng.randint(5_000, 250_000),
                        "impliedVolatility": round(iv, 2),
                        "lastPrice": ltp,
                        "bidQty": rng.randint(50, 5000),
                        "askQty": rng.randint(50, 5000),
                    },
                })
                if side == "CE":
                    total_ce_oi += new_oi
                else:
                    total_pe_oi += new_oi

        # merge CE/PE rows per strike, like NSE's actual shape
        merged = {}
        for row in data:
            k = row["strikePrice"]
            merged.setdefault(k, {"strikePrice": k, "expiryDate": row["expiryDate"]})
            merged[k].update({s: row[s] for s in ("CE", "PE") if s in row})

        payload = {
            "records": {
                "underlyingValue": round(spot, 2),
                "timestamp": f"{trading_date} {t}:00",
                "data": list(merged.values()),
            },
            "filtered": {
                "CE": {"totOI": total_ce_oi},
                "PE": {"totOI": total_pe_oi},
            },
        }

        out.append(RawSnapshot(
            symbol=symbol,
            fetched_at_utc=f"{trading_date}T{t}:00+00:00",
            source="synthetic_demo",
            payload=payload,
        ))

    return out


def _next_weekly_expiry(trading_date: str) -> str:
    d = datetime.fromisoformat(trading_date)
    days_ahead = (1 - d.weekday()) % 7  # next Tuesday (NSE weekly index expiry)
    days_ahead = days_ahead or 7
    expiry = d + timedelta(days=days_ahead)
    return expiry.strftime("%d-%b-%Y")


def write_bronze(snapshots, bronze_dir: str):
    written = []
    for snap in snapshots:
        out_dir = Path(bronze_dir) / snap.symbol
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = snap.fetched_at_utc.replace(":", "-")
        out_path = out_dir / f"{ts}.json"
        out_path.write_text(json.dumps(asdict(snap)))
        written.append(str(out_path))
    return written


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    spot = 24650.0
    all_written = []
    for d in range(days):
        trading_date = (datetime.now(timezone.utc).date() - timedelta(days=days - d)).isoformat()
        snaps = generate_day("NIFTY", trading_date=trading_date, open_spot=spot, seed=100 + d)
        # carry spot forward day to day
        last_spot = snaps[-1].payload["records"]["underlyingValue"]
        spot = last_spot
        all_written += write_bronze(snaps, "../data/bronze")
    print(f"Wrote {len(all_written)} bronze snapshot files across {days} trading days")
