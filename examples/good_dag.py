"""Example clean DAG — no anti-patterns."""

from airflow.sdk import DAG, Variable
from airflow.providers.standard.operators.python import PythonOperator
from datetime import datetime, timedelta

default_args = {
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
}


def extract(**context):
    from airflow.providers.postgres.hooks.postgres import PostgresHook

    hook = PostgresHook(postgres_conn_id="warehouse_conn")
    df = hook.get_pandas_df("SELECT * FROM orders WHERE date = '{{ ds }}'")
    context["ti"].xcom_push(key="order_count", value=len(df))
    staging = Variable.get("staging_path")
    df.to_parquet(f"{staging}/orders.parquet")


def transform(**context):
    import pandas as pd

    staging = Variable.get("staging_path")
    df = pd.read_parquet(f"{staging}/orders.parquet")
    df["total"] = df["amount"] * 1.2
    df.to_parquet(f"{staging}/orders_clean.parquet")


def load(**context):
    from airflow.providers.postgres.hooks.postgres import PostgresHook

    hook = PostgresHook(postgres_conn_id="warehouse_conn")
    hook.run("INSERT INTO results SELECT * FROM staging")


with DAG(
    "orders_pipeline_clean",
    start_date=datetime(2024, 1, 1),
    schedule="@daily",
    catchup=False,
    default_args=default_args,
) as dag:
    t_extract = PythonOperator(task_id="extract", python_callable=extract)
    t_transform = PythonOperator(task_id="transform", python_callable=transform)
    t_load = PythonOperator(task_id="load", python_callable=load)

    t_extract >> t_transform >> t_load
