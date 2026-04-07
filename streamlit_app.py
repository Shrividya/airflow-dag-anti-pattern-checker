"""Streamlit web app for the Airflow DAG anti-pattern detector."""

import streamlit as st
import tempfile
from pathlib import Path
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from airflow_antipattern.checker import check_file, SEVERITY_ORDER
from airflow_antipattern.rules import RULES

st.set_page_config(
    page_title="Airflow DAG anti-pattern detector",
    page_icon="🔍",
    layout="wide",
)

SEV_COLOR = {"high": "#E24B4A", "medium": "#EF9F27", "low": "#639922"}
SEV_ICON  = {"high": "🔴", "medium": "🟡", "low": "🟢"}
SEV_BG    = {"high": "#FCEBEB", "medium": "#FAEEDA", "low": "#EAF3DE"}
SEV_TEXT  = {"high": "#A32D2D", "medium": "#854F0B", "low": "#3B6D11"}

BAD_EXAMPLE = '''\
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
import pandas as pd
import psycopg2
import requests

# top-level DB call — runs on every scheduler parse
conn = psycopg2.connect("postgresql://admin:sup3rs3cr3t@prod-db:5432/warehouse")
rows = conn.execute("SELECT count(*) FROM orders").fetchall()

# top-level HTTP call
config = requests.get("https://api.internal.com/config").json()


def huge_etl_pipeline(**context):
    data = [r for r in rows]
    df = pd.DataFrame(data)
    df["total"] = df["amount"] * 1.2
    df = df[df["total"] > 0]
    df.to_parquet("/home/airflow/data/output.parquet")
    conn2 = psycopg2.connect("postgresql://admin:pass123@prod-db:5432/warehouse")
    conn2.cursor().execute("INSERT INTO results SELECT * FROM staging")
    conn2.commit()
    requests.post("https://hooks.slack.com/xxx", json={"text": "done"})
    a = df.groupby("id").sum()
    b = df.merge(a, on="id")
    c = b[b["total"] > 100]
    d = c.sort_values("total")
    e = d.head(1000)
    f2 = e.reset_index()
    g = f2.rename(columns={"total": "amount_total"})
    h = g.dropna()
    ii = h.fillna(0)
    jj = ii.astype(str)


with DAG(
    "orders_pipeline",
    start_date=datetime.now(),
) as dag:
    process = PythonOperator(
        task_id="process_orders",
        python_callable=huge_etl_pipeline,
    )
    notify = PythonOperator(
        task_id="send_notification",
        python_callable=lambda: print("done"),
        retries=3,
    )
'''

GOOD_EXAMPLE = '''\
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from datetime import datetime, timedelta

default_args = {
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
}


def extract(**context):
    import pandas as pd
    from airflow.providers.postgres.hooks.postgres import PostgresHook
    hook = PostgresHook(postgres_conn_id="warehouse_conn")
    df = hook.get_pandas_df("SELECT * FROM orders")
    df.to_parquet(Variable.get("staging_path") + "/orders.parquet")


def transform(**context):
    import pandas as pd
    path = Variable.get("staging_path")
    df = pd.read_parquet(path + "/orders.parquet")
    df["total"] = df["amount"] * 1.2
    df.to_parquet(path + "/orders_clean.parquet")


def load(**context):
    from airflow.providers.postgres.hooks.postgres import PostgresHook
    hook = PostgresHook(postgres_conn_id="warehouse_conn")
    hook.run("INSERT INTO results SELECT * FROM staging")


with DAG(
    "orders_pipeline_clean",
    start_date=datetime(2024, 1, 1),
    schedule_interval="@daily",
    catchup=False,
    default_args=default_args,
) as dag:
    t1 = PythonOperator(task_id="extract", python_callable=extract)
    t2 = PythonOperator(task_id="transform", python_callable=transform)
    t3 = PythonOperator(task_id="load", python_callable=load)
    t1 >> t2 >> t3
'''

# ── Page header ──────────────────────────────────────────────────────────────
st.title("🔍 Airflow DAG anti-pattern detector")
st.caption(
    "Paste your DAG code below to catch performance, reliability, and "
    "maintainability issues before they reach production."
)

# ── Sidebar: filters ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")
    min_sev = st.selectbox(
        "Minimum severity",
        options=["low", "medium", "high"],
        index=0,
        help="Only show findings at this severity level and above.",
    )
    all_cats = sorted({r.category for r in RULES})
    selected_cats = st.multiselect(
        "Categories",
        options=all_cats,
        default=all_cats,
        help="Only show findings from these categories.",
    )
    show_fix = st.toggle("Show fix suggestions", value=True)
    show_why = st.toggle("Show explanation", value=True)

    st.divider()
    st.header("Rules reference")
    for cat in all_cats:
        cat_rules = [r for r in RULES if r.category == cat]
        with st.expander(f"{cat} — {cat_rules[0].category_label}"):
            for r in cat_rules:
                st.markdown(
                    f"`{r.code}` {SEV_ICON[r.severity]} **{r.title}**"
                )

# ── Main area ────────────────────────────────────────────────────────────────
col_input, col_results = st.columns([1, 1], gap="medium")

with col_input:
    ex_col1, ex_col2, _ = st.columns([1, 1, 2])
    with ex_col1:
        if st.button("Load bad DAG", use_container_width=True):
            st.session_state["dag_code"] = BAD_EXAMPLE
    with ex_col2:
        if st.button("Load clean DAG", use_container_width=True):
            st.session_state["dag_code"] = GOOD_EXAMPLE

    code = st.text_area(
        "DAG code",
        value=st.session_state.get("dag_code", ""),
        height=480,
        placeholder="# Paste your Airflow DAG here...",
        label_visibility="collapsed",
    )

    analyze = st.button("Analyze DAG", type="primary", use_container_width=True)

with col_results:
    if analyze and code.strip():
        # Write to a temp file so the checker can read it
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(code)
            tmp_path = Path(f.name)

        findings = check_file(
            tmp_path,
            ignore=None,
            select=None,
            min_severity=min_sev,
        )
        tmp_path.unlink()

        # Apply category filter
        findings = [f for f in findings if f.rule.category in selected_cats]

        if not findings:
            st.success("No anti-patterns detected — clean DAG!")
        else:
            high   = sum(1 for f in findings if f.severity == "high")
            medium = sum(1 for f in findings if f.severity == "medium")
            low    = sum(1 for f in findings if f.severity == "low")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total", len(findings))
            m2.metric("🔴 High",   high)
            m3.metric("🟡 Medium", medium)
            m4.metric("🟢 Low",    low)

            st.divider()

            for f in findings:
                icon = SEV_ICON[f.severity]
                lines_str = ""
                if f.line_numbers:
                    lines_str = f" · line {', '.join(str(l) for l in f.line_numbers[:3])}"

                with st.expander(
                    f"{icon} `{f.rule.code}` — {f.rule.title}{lines_str}",
                    expanded=False,
                ):
                    if show_why:
                        st.markdown(f"**Why it matters**")
                        st.info(f.rule.why)

                    if show_fix:
                        st.markdown(f"**Suggested fix**")
                        st.code(f.rule.fix, language="python")

    elif analyze and not code.strip():
        st.warning("Paste some DAG code first.")
    else:
        st.markdown(
            "<div style='padding:4rem 0;text-align:center;color:gray;font-size:14px'>"
            "Results will appear here after you click Analyze DAG"
            "</div>",
            unsafe_allow_html=True,
        )
