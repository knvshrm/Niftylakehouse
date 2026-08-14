"""
Options Analytics
==================
The actual "edge" layer. Every function here takes a snapshot's worth of
silver rows (one symbol, one snapshot_ts, all strikes/sides) and returns a
derived metric a trader can't just eyeball off the raw NSE option chain.
"""

import pandas as pd


def put_call_ratio(snapshot: pd.DataFrame) -> float:
    """OI-based PCR. >1 suggests more put writing (bullish bias from writers),
    <1 suggests more call writing (bearish bias from writers)."""
    ce_oi = snapshot.loc[snapshot.option_type == "CE", "open_interest"].sum()
    pe_oi = snapshot.loc[snapshot.option_type == "PE", "open_interest"].sum()
    return round(pe_oi / ce_oi, 3) if ce_oi else float("nan")


def max_pain(snapshot: pd.DataFrame) -> float:
    """
    Strike at which option writers (sellers) collectively lose the least —
    classic theory being price gravitates here into expiry. Computed by
    summing, for each candidate strike, the total intrinsic-value payout
    writers would owe across all CE+PE open interest.
    """
    strikes = sorted(snapshot.strike_price.unique())
    ce = snapshot[snapshot.option_type == "CE"].set_index("strike_price")["open_interest"]
    pe = snapshot[snapshot.option_type == "PE"].set_index("strike_price")["open_interest"]

    best_strike, best_payout = None, None
    for candidate in strikes:
        ce_payout = ((candidate - ce.index) * ce).clip(lower=0).sum()
        pe_payout = ((pe.index - candidate) * pe).clip(lower=0).sum()
        total = ce_payout + pe_payout
        if best_payout is None or total < best_payout:
            best_payout, best_strike = total, candidate
    return float(best_strike)


def oi_buildup_classification(snapshot: pd.DataFrame, prev_snapshot: pd.DataFrame) -> pd.DataFrame:
    """
    Classic 4-quadrant OI/price interpretation, per strike+side, comparing
    this snapshot to the previous one:
      Long Buildup    : price up   & OI up    -> fresh longs entering
      Short Buildup    : price down & OI up    -> fresh shorts entering
      Long Unwinding   : price down & OI down  -> longs exiting
      Short Covering   : price up   & OI down  -> shorts exiting
    This is the signal that's genuinely hard to eyeball across 20+ strikes
    at once but is exactly what a pipeline should surface automatically.
    """
    cur = snapshot.set_index(["strike_price", "option_type"])
    prev = prev_snapshot.set_index(["strike_price", "option_type"])
    joined = cur[["last_price", "open_interest"]].join(
        prev[["last_price", "open_interest"]], lsuffix="_cur", rsuffix="_prev", how="inner"
    )
    joined["price_up"] = joined.last_price_cur > joined.last_price_prev
    joined["oi_up"] = joined.open_interest_cur > joined.open_interest_prev

    def label(row):
        if row.price_up and row.oi_up:
            return "Long Buildup"
        if not row.price_up and row.oi_up:
            return "Short Buildup"
        if not row.price_up and not row.oi_up:
            return "Long Unwinding"
        return "Short Covering"

    joined["classification"] = joined.apply(label, axis=1)
    return joined.reset_index()[
        ["strike_price", "option_type", "open_interest_cur", "classification"]
    ].rename(columns={"open_interest_cur": "open_interest"})


def iv_skew(snapshot: pd.DataFrame, spot: float,
            otm_band: tuple = (0.02, 0.08)) -> dict:
    """
    Compares IV of OTM puts (strikes otm_band% below spot) vs OTM calls
    (strikes otm_band% above spot) — this is where real skew shows up, not
    at-the-money where put/call IV converge by put-call parity. Positive
    skew (puts richer) = market paying up for downside protection = fear
    premium. Negative = complacent/greedy for upside.
    """
    lo_pct, hi_pct = otm_band
    put_lo, put_hi = spot * (1 - hi_pct), spot * (1 - lo_pct)
    call_lo, call_hi = spot * (1 + lo_pct), spot * (1 + hi_pct)

    otm_puts = snapshot[(snapshot.option_type == "PE")
                         & (snapshot.strike_price.between(put_lo, put_hi))]
    otm_calls = snapshot[(snapshot.option_type == "CE")
                          & (snapshot.strike_price.between(call_lo, call_hi))]
    put_iv = otm_puts["implied_volatility"].mean()
    call_iv = otm_calls["implied_volatility"].mean()
    return {
        "put_iv_otm": round(put_iv, 2) if pd.notna(put_iv) else None,
        "call_iv_otm": round(call_iv, 2) if pd.notna(call_iv) else None,
        "skew_pts": round(put_iv - call_iv, 2) if pd.notna(put_iv) and pd.notna(call_iv) else None,
    }


def snapshot_summary(snapshot: pd.DataFrame) -> dict:
    spot = float(snapshot.underlying_value.iloc[0])
    return {
        "snapshot_ts": snapshot.snapshot_ts.iloc[0],
        "underlying_value": spot,
        "pcr": put_call_ratio(snapshot),
        "max_pain": max_pain(snapshot),
        "distance_to_max_pain_pct": None,  # filled by caller once max_pain known
        **iv_skew(snapshot, spot),
    }
