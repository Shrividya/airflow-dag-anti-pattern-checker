"""Example DAG with intentional anti-patterns — for testing the linter."""
import pandas as pd                          # TLC002: heavy import at top
import psycopg2                              # TLC001: DB usage at top
import requests                              # TLC003: HTTP at top

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime

# Top-level DB call — runs on every scheduler parse
conn = psycopg2.connect("postgresql://admin:sup3rs3cr3t@prod-db:5432/db")  # HDC001
rows = conn.execute("SELECT count(*) FROM orders").fetchall()

# Top-level HTTP call
config = requests.get("https://api.internal.com/settings").json()  # TLC003


def huge_etl_pipeline(**context):
    """Monolithic task that does extract + transform + load in one go."""
    import numpy as np

    # ── Extract ──────────────────────────────────────────────────────────────
    data = [r for r in rows]
    df = pd.DataFrame(data, columns=["id", "amount", "date"])

    # ── Transform ────────────────────────────────────────────────────────────
    df["total"] = df["amount"] * 1.2
    df = df[df["total"] > 0]
    df["rank"] = np.argsort(df["total"].values)

    # ── Load ─────────────────────────────────────────────────────────────────
    df.to_parquet("/home/airflow/data/output.parquet")               # HDC003
    conn2 = psycopg2.connect("postgresql://admin:pass123@prod-db:5432/db")  # HDC001
    cur = conn2.cursor()
    cur.execute("INSERT INTO results SELECT * FROM staging")
    conn2.commit()
    requests.post("https://hooks.slack.com/xxx", json={"text": "done"})


with DAG(
    "orders_pipeline",
    start_date=datetime.now(),                  # HDC002: datetime.now()
    # catchup not set                           # DEP002
) as dag:
    process = PythonOperator(                   # RET001: no retries
        task_id="process_orders",
        python_callable=huge_etl_pipeline,
    )
    notify = PythonOperator(
        task_id="send_notification",
        python_callable=lambda: print("done"),
        retries=3,                              # RET002: no retry_delay
    )
    # No >> between tasks                       # DEP001
