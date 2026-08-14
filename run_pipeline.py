"""
End-to-end runner: bronze -> silver -> gold.
(Ingestion is run separately/on schedule via orchestration/nifty_lakehouse_dag.py
or ad-hoc via ingestion/synthetic_data_generator.py for this demo.)
"""

from pipeline.bronze_to_silver import run as bronze_to_silver
from pipeline.silver_to_gold import run as silver_to_gold


if __name__ == "__main__":
    print("=== Bronze -> Silver ===")
    bronze_to_silver()
    print("\n=== Silver -> Gold ===")
    silver_to_gold()
