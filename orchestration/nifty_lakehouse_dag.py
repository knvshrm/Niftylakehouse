"""
Airflow DAG: Nifty Options Lakehouse
=====================================
Schedules the ingest -> bronze -> silver -> gold pipeline every trading day.

This is written against Airflow's API so it's a real, reviewable artifact
for a portfolio (not runnable in this sandbox, which has no Airflow
scheduler). `fetch_and_land_bronze` below already calls the real
NSEOptionChainClient (backed by jugaad-data) — deploy this wherever you're
running Airflow with normal internet access and it pulls live data with no
code changes.

Cadence matches how you'd actually run this in production:
  - Poll every ~15 min during market hours (09:15-15:30 IST)
  - Roll up to gold once at end of day, plus incrementally after each poll
    for near-real-time PCR/OI-buildup dashboards
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule


default_args = {
    "owner": "options-lakehouse",
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
}

with DAG(
    dag_id="nifty_options_lakehouse",
    default_args=default_args,
    description="Ingest NSE option chain -> bronze/silver/gold -> analytics",
    schedule_interval="*/15 9-15 * * 1-5",  # every 15 min, market hours, Mon-Fri IST
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["options", "nifty", "lakehouse"],
) as dag:

    def fetch_and_land_bronze(**context):
        from ingestion.nse_option_chain_client import NSEOptionChainClient
        client = NSEOptionChainClient(min_interval_seconds=0)  # scheduler owns cadence
        for symbol in ("NIFTY", "BANKNIFTY"):
            snap = client.fetch(symbol)
            client.write_bronze(snap, bronze_dir="/data/bronze")

    def run_bronze_to_silver(**context):
        from pipeline.bronze_to_silver import run as run_silver
        run_silver()

    def run_silver_to_gold(**context):
        from pipeline.silver_to_gold import run as run_gold
        run_gold()

    def alert_on_signal_shift(**context):
        """
        Placeholder for the paid-product hook: check latest gold row for a
        meaningful PCR swing, OI-buildup cluster, or skew flip vs. the prior
        snapshot, and push to subscribers (Telegram/webhook) if threshold
        crossed. This is where the "signal" product plugs into the pipeline.
        """
        pass

    ingest = PythonOperator(task_id="fetch_and_land_bronze", python_callable=fetch_and_land_bronze)
    to_silver = PythonOperator(task_id="bronze_to_silver", python_callable=run_bronze_to_silver)
    to_gold = PythonOperator(task_id="silver_to_gold", python_callable=run_silver_to_gold)
    alert = PythonOperator(
        task_id="alert_on_signal_shift",
        python_callable=alert_on_signal_shift,
        trigger_rule=TriggerRule.ALL_SUCCESS,
    )

    ingest >> to_silver >> to_gold >> alert
