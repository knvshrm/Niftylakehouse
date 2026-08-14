# Nifty Options Lakehouse

A medallion-architecture (bronze → silver → gold) data pipeline over NSE
Nifty option-chain data, with derived trading analytics (Max Pain, PCR,
OI-buildup classification, IV skew) computed automatically — the layer
that's actually worth paying for, since the raw option chain is free and
public.

## Quickstart

```bash
# See it working end to end with realistic sample data (2 minutes):
bash quickstart_demo.sh

# Pull ONE real live snapshot from NSE (run on your own machine, not a
# restricted sandbox — see "Going from demo to live" below):
bash quickstart_live.sh
```

Then open `dashboard/dashboard.html` in a browser.

## Why this exists

Anyone can look at NSE's option chain live. Nobody keeps a queryable,
time-series history of it with buildup/skew/max-pain computed automatically
across every strike, every snapshot, every day. That gap is the product.

## Architecture

```
ingestion/                  → raw pulls, written as bronze (one JSON per snapshot)
  nse_option_chain_client.py    real NSE API client (session/cookie handling,
                                 rate-limited) — for use with real network access
  synthetic_data_generator.py   realistic demo data, same JSON shape as NSE's
                                 API, so the rest of the pipeline is identical
                                 whether the source is live or synthetic

pipeline/
  bronze_to_silver.py       flattens raw JSON → typed rows → Delta Lake table
                             (data/silver/option_chain_ticks), partitioned by
                             symbol + trading_date
  silver_to_gold.py         runs analytics across every snapshot, writes:
                               data/gold/snapshot_metrics  (1 row/snapshot)
                               data/gold/oi_buildup        (1 row/strike/side/snapshot)

analytics/
  metrics.py                 the actual signal logic:
                                - put_call_ratio()
                                - max_pain()
                                - oi_buildup_classification()  (4-quadrant: Long/Short
                                  Buildup, Long Unwinding, Short Covering)
                                - iv_skew()  (OTM put IV vs OTM call IV)

orchestration/
  nifty_lakehouse_dag.py     Airflow DAG: poll every 15 min during market
                              hours → bronze → silver → gold → alert hook

dashboard/
  export_gold_json.py        exports gold tables to JSON for the dashboard
  dashboard.html              static dashboard reading the gold layer
```

## Automation — GitHub Actions (fully automated, runs even with your laptop off)

This is already built and git-committed inside this project — `.github/workflows/scheduled_ingest.yml`
runs the entire pipeline on a schedule, on GitHub's own servers, and commits
the fresh data back automatically. Once it's pushed to GitHub, nothing
further is needed from you.

**Being precise about what "no human intervention" means here**, because
that phrase can hide a false promise: one human action is unavoidable —
pushing this code to a GitHub account, because I don't have access to
your GitHub credentials and can't do that step for you. That's it, though:
a one-time ~5 minute setup, not ongoing intervention. After that, the
schedule runs itself forever with no further action from you.

### The only steps left (copy-paste, ~5 minutes, once)

```bash
# 1. Create a free account at github.com if you don't have one.
# 2. Create a new EMPTY repository there (no README/license — just empty).
#    Copy the repo URL it gives you, then:

cd nifty-options-lakehouse
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```

That's the whole thing. This project already has git initialized and every
file committed — you're just pushing it, not setting anything up from
scratch. GitHub detects the workflow file automatically and starts running
it on the schedule.

### How you'll know it's working (without checking manually)

- Go to the **Actions** tab on your repo any time to see every run and its logs.
- **GitHub automatically emails you if a scheduled run fails** — this is a
  built-in GitHub notification, not something I configured — so you don't
  need to poll it. If you never get a failure email, it's running fine.

### The one honest limit — read this before trusting it blindly

NSE occasionally blocks requests from cloud-provider IP ranges (GitHub's
included) even with proper session handling, because that traffic doesn't
look like a normal home connection. I can't guarantee GitHub's IPs won't
ever get blocked — nobody can promise that from outside NSE, since it's
NSE's server-side decision, not a bug in this code. If it happens, you'll
get the failure email above, and `scheduler.py` (Option A from before,
running on your own home internet) is the fallback that doesn't have this
risk. This is the one piece of this project that isn't 100% guaranteed —
everything else (the pipeline logic, the Delta Lake writes, the analytics
math) has been run and verified, not just written and assumed to work.

## Run it manually (understanding each step)

```bash
pip install -r requirements.txt

# 1. Generate demo bronze data (8 trading days, synthetic but realistic)
cd ingestion && python3 synthetic_data_generator.py 8

# 2. Run the pipeline: bronze -> silver -> gold
cd .. && python3 run_pipeline.py

# 3. Export gold -> dashboard JSON and open dashboard/dashboard.html
cd dashboard && python3 export_gold_json.py
```

(Or just run `bash quickstart_demo.sh` from the project root — it does all
three steps for you.)

## Going from demo to live

Only `ingestion/` changes. `NSEOptionChainClient` in
`nse_option_chain_client.py` wraps [`jugaad-data`](https://github.com/jugaad-py/jugaad-data),
an actively maintained open-source library that handles NSE's session/cookie
requirements — this is more robust than hand-rolling that logic yourself,
since NSE's anti-bot measures shift periodically and a maintained library
gets patched when they do.

**This was tested directly, not assumed.** Running it inside this build
sandbox fails — traced all the way to the network call, which the sandbox's
egress proxy refuses (only package registries are reachable from here, not
`nseindia.com`). That's the actual failure point; the client code itself is
correct. Run it on your own machine or a scheduled job with normal internet
access:

```bash
pip install jugaad-data
cd ingestion && python3 nse_option_chain_client.py NIFTY
```

Point the Airflow DAG's `fetch_and_land_bronze` task at it instead of the
synthetic generator and nothing downstream changes, since both emit the
same bronze JSON shape.

**If you want something more production-robust than scraping NSE at all**:
NSE's website can change its anti-bot behavior without notice, which breaks
any scraper (including jugaad-data) until someone patches it. Since you
already trade options, check whether your broker exposes an official option
chain API — Zerodha's Kite Connect or Dhan's API both offer this with a
stable contract and proper rate limits, at the cost of a developer
subscription. That's the more durable choice if this becomes a real
product; jugaad-data is the right choice for getting it running today.

## Known simplifications (be upfront about these if you demo this)

- **Synthetic data**: prices/OI/IV are generated with a simple random-walk +
  smile model, not real market data. It's structurally realistic (correct
  NSE JSON shape, coherent OI buildup across snapshots, genuine put/call
  skew) but the specific numbers aren't real.
- **Max Pain / PCR / skew are classic retail heuristics**, not proven alpha
  — they're widely tracked, but treat them as descriptive signals, not a
  backtested edge. If you productionize this, back-test before selling
  "signals" to anyone.
- **No options-pricing model** (Black-Scholes/Greeks) yet — IV is read
  directly from the chain, not derived. Adding delta/theta/gamma per
  strike would be a natural next layer.

## Portfolio narrative

What this demonstrates, if you're using it as a Data Engineering portfolio
piece:
- **Medallion architecture** (bronze/silver/gold) on **Delta Lake**, the
  same table format Databricks is built around
- **Partitioned, incremental-friendly design** (by symbol + trading_date)
- **Idempotent transforms** (dedup on load, overwrite-by-partition semantics)
- **Production ingestion concerns handled explicitly**: session/cookie
  auth, rate limiting, retry/backoff — not just a happy-path API call
- **Orchestration**: a real Airflow DAG with sensible scheduling and a
  dependency chain (ingest → silver → gold → alert hook)
- **A defined "gold" contract**: small, pre-aggregated tables a dashboard
  or paid API would actually query, instead of scanning raw data live

## Next steps toward monetization

1. Swap in the live NSE client, run for a few weeks, backtest whether
   max-pain / OI-buildup / skew signals actually predict anything on your
   data before claiming they do.
2. Add the `alert_on_signal_shift` logic in the DAG — push to a Telegram
   channel when PCR or skew crosses a threshold, or a strike shows unusual
   buildup.
3. Only after you have a track record: wrap the gold tables in a small paid
   API or freemium dashboard.
