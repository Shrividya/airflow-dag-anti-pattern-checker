"""All anti-pattern rule definitions."""

from dataclasses import dataclass, field
from typing import Optional
import re


@dataclass
class Rule:
    code: str
    category: str
    category_label: str
    title: str
    severity: str  # "high" | "medium" | "low"
    pattern: re.Pattern
    why: str
    fix: str
    neg_pattern: Optional[re.Pattern] = None
    multiline: bool = False


RULES: list[Rule] = [
    # ── Top-level code ──────────────────────────────────────────────────────
    Rule(
        code="TLC001",
        category="TLC",
        category_label="Top-level code",
        title="Database call at module level",
        severity="high",
        # Only match lines with NO leading whitespace (module-level, not inside a function)
        pattern=re.compile(
            r"^(Variable\.get|session\.query|engine\.execute"
            r"|psycopg2\.connect|pymysql\.connect"
            r"|\w+ = psycopg2|\w+ = pymysql)",
            re.MULTILINE,
        ),
        why=(
            "Airflow parses every DAG file repeatedly to build the scheduler's task "
            "graph. Any database call at module level runs on EVERY parse cycle — "
            "potentially hundreds of times per minute. This stalls the scheduler and "
            "can crash it under load."
        ),
        fix=(
            "# Bad — runs on every DAG parse\n"
            "conn = psycopg2.connect(os.environ['DB_URL'])\n\n"
            "# Good — move DB logic inside the task callable\n"
            "def my_task(**context):\n"
            "    conn = psycopg2.connect(os.environ['DB_URL'])"
        ),
    ),
    Rule(
        code="TLC002",
        category="TLC",
        category_label="Top-level code",
        title="Heavy library imported at module level",
        severity="medium",
        pattern=re.compile(
            r"^import (pandas|numpy|tensorflow|torch|sklearn|scipy|pyspark)",
            re.MULTILINE,
        ),
        why=(
            "Large libraries (pandas, numpy, tensorflow) take 1-3 seconds to import. "
            "Since the scheduler parses your DAG file repeatedly, this cost multiplies "
            "and slows down DAG discovery for every DAG in your deployment."
        ),
        fix=(
            "# Bad — imported at the top of the DAG file\n"
            "import pandas as pd\n\n"
            "# Good — import inside the task function only\n"
            "def process_data(**context):\n"
            "    import pandas as pd  # only loaded when task runs\n"
            "    df = pd.read_parquet(...)"
        ),
    ),
    Rule(
        code="TLC003",
        category="TLC",
        category_label="Top-level code",
        title="HTTP/API call at module level",
        severity="high",
        pattern=re.compile(r"requests\.(get|post|put|delete|request)\s*\("),
        why=(
            "HTTP calls at module scope run every time the scheduler parses the DAG. "
            "Network latency and failures cascade into scheduler instability. A single "
            "slow endpoint can block ALL DAG parsing."
        ),
        fix=(
            "# Bad\n"
            'resp = requests.get("https://api.example.com/config")\n\n'
            "# Good — inside the task only\n"
            "def fetch_config(**context):\n"
            '    resp = requests.get("https://api.example.com/config")'
        ),
    ),

    # ── Retries ─────────────────────────────────────────────────────────────
    Rule(
        code="RET001",
        category="RET",
        category_label="Retries",
        title="No retries configured on operator",
        severity="high",
        pattern=re.compile(
            r"(PythonOperator|BashOperator|SparkSubmitOperator"
            r"|BigQueryOperator|S3FileTransformOperator|EmailOperator)"
        ),
        # retries= anywhere in file OR default_args dict contains retries key
        neg_pattern=re.compile(r"retries\s*=|['\"]retries['\"]\s*:"),
        why=(
            "Transient failures (network blips, API rate limits, cluster hiccups) are "
            "normal in distributed systems. A task with no retries will fail permanently "
            "on the first hiccup. Retries are the safety net of reliable pipelines."
        ),
        fix=(
            "# Bad\n"
            "t = PythonOperator(\n"
            "    task_id='load_data',\n"
            "    python_callable=load_data\n"
            ")\n\n"
            "# Good\n"
            "t = PythonOperator(\n"
            "    task_id='load_data',\n"
            "    python_callable=load_data,\n"
            "    retries=3,\n"
            "    retry_delay=timedelta(minutes=5)\n"
            ")"
        ),
    ),
    Rule(
        code="RET002",
        category="RET",
        category_label="Retries",
        title="Retries set but no retry_delay",
        severity="medium",
        pattern=re.compile(r"retries\s*=\s*[1-9]"),
        neg_pattern=re.compile(r"retry_delay"),
        why=(
            "Without retry_delay, Airflow retries immediately — hammering a failing "
            "service with rapid-fire attempts. This can worsen an outage and makes "
            "logs hard to read. Always pair retries with a sensible delay."
        ),
        fix=(
            "# Bad — retries immediately with no delay\n"
            "retries=3\n\n"
            "# Good — wait and back off exponentially\n"
            "retries=3,\n"
            "retry_delay=timedelta(minutes=5),\n"
            "retry_exponential_backoff=True  # doubles wait each retry"
        ),
    ),

    # ── Hardcoding ──────────────────────────────────────────────────────────
    Rule(
        code="HDC001",
        category="HDC",
        category_label="Hardcoding",
        title="Hardcoded credential or secret",
        severity="high",
        pattern=re.compile(
            r"(password|passwd|secret|token|api_key)\s*=\s*['\"][^'\"]{4,}",
            re.IGNORECASE,
        ),
        why=(
            "Hardcoded credentials end up in version control, scheduler logs, and "
            "audit trails. A single leaked repo exposes your entire infrastructure. "
            "Airflow has a dedicated Connections/Variables system built for this."
        ),
        fix=(
            '# Bad — credential in plain text\n'
            'hook = PostgresHook(password="sup3rs3cr3t")\n\n'
            "# Good — use Airflow Connections\n"
            'hook = PostgresHook(postgres_conn_id="my_postgres_conn")\n'
            "# Set the password once via: Admin > Connections in the UI"
        ),
    ),
    Rule(
        code="HDC002",
        category="HDC",
        category_label="Hardcoding",
        title="datetime.now() used as start_date",
        severity="high",
        pattern=re.compile(r"start_date\s*=\s*datetime\.now\(\)"),
        why=(
            "Using datetime.now() as start_date causes Airflow to create a brand new "
            "DAG run every time the scheduler re-parses the file. You can end up with "
            "thousands of queued runs within hours of deploying the DAG."
        ),
        fix=(
            "# Bad — creates infinite new runs on every parse\n"
            "start_date=datetime.now()\n\n"
            "# Good — fixed date + disable backfill\n"
            "start_date=datetime(2024, 1, 1),\n"
            "catchup=False"
        ),
    ),
    Rule(
        code="HDC003",
        category="HDC",
        category_label="Hardcoding",
        title="Hardcoded absolute file path",
        severity="low",
        pattern=re.compile(
            r"['\"](\/(home|tmp|var|mnt|data|opt)\/|C:\\\\)[^'\"]+['\"]"
        ),
        why=(
            "Absolute paths break when the DAG runs on a different worker, container, "
            "or environment. Use Airflow Variables or environment variables so the DAG "
            "works identically across dev, staging, and production."
        ),
        fix=(
            '# Bad\n'
            'file_path = "/home/airflow/data/input.csv"\n\n'
            "# Good\n"
            "from airflow.models import Variable\n"
            'file_path = Variable.get("input_file_path")'
        ),
    ),

    # ── Dependencies ────────────────────────────────────────────────────────
    Rule(
        code="DEP001",
        category="DEP",
        category_label="Dependencies",
        title="No task dependencies defined",
        severity="medium",
        pattern=re.compile(r"with DAG"),
        neg_pattern=re.compile(r">>|<<|set_downstream|set_upstream|chain\("),
        why=(
            "Without >> or << operators, all tasks run in parallel with no guaranteed "
            "order. This is occasionally intentional, but usually a bug — like sending "
            "a report before the data is ready."
        ),
        fix=(
            "# Bad — tasks run in any order\n"
            "extract = PythonOperator(...)\n"
            "transform = PythonOperator(...)\n"
            "load = PythonOperator(...)\n\n"
            "# Good — explicit chain\n"
            "extract >> transform >> load\n\n"
            "# Fan-out is also fine\n"
            "extract >> [transform_a, transform_b] >> load"
        ),
    ),
    Rule(
        code="DEP002",
        category="DEP",
        category_label="Dependencies",
        title="catchup not explicitly set",
        severity="medium",
        pattern=re.compile(r"with DAG\s*\("),
        neg_pattern=re.compile(r"catchup\s*="),
        why=(
            "When catchup is not set, Airflow defaults to True and will backfill ALL "
            "DAG runs from start_date to now. If start_date is months ago and schedule "
            "is hourly, you instantly get thousands of queued runs, overloading workers."
        ),
        fix=(
            "# Risky — defaults to catchup=True\n"
            "with DAG('my_dag', start_date=datetime(2024,1,1)) as dag:\n\n"
            "# Safe — be explicit\n"
            "with DAG(\n"
            "    'my_dag',\n"
            "    start_date=datetime(2024,1,1),\n"
            "    catchup=False  # don't backfill historical runs\n"
            ") as dag:"
        ),
    ),

    # ── Atomicity ───────────────────────────────────────────────────────────
    Rule(
        code="ATO001",
        category="ATO",
        category_label="Atomicity",
        title="Large monolithic task callable (30+ lines)",
        severity="medium",
        # Matches any python_callable= task function definition — checked per-function in checker
        pattern=re.compile(r"def \w+\s*\([^)]*\*\*context[^)]*\)\s*:"),
        why=(
            "A task that does extract + transform + load in one function cannot be "
            "partially retried. If the load step fails, you re-run everything from "
            "scratch. Split tasks so each step is independently retryable and auditable."
        ),
        fix=(
            "# Bad — one task does everything\n"
            "def etl_pipeline(**context):\n"
            "    data = extract_from_api()\n"
            "    clean = transform(data)\n"
            "    load_to_warehouse(clean)\n\n"
            "# Good — three separate atomic tasks\n"
            "extract = PythonOperator(task_id='extract', ...)\n"
            "transform = PythonOperator(task_id='transform', ...)\n"
            "load = PythonOperator(task_id='load', ...)\n"
            "extract >> transform >> load"
        ),
        multiline=False,
    ),
    Rule(
        code="ATO002",
        category="ATO",
        category_label="Atomicity",
        title="Dynamic task loop without TaskGroup",
        severity="low",
        pattern=re.compile(
            r"for \w+ in .+:\s*\n\s+\w+\s*=\s*(PythonOperator|BashOperator)"
        ),
        neg_pattern=re.compile(r"TaskGroup"),
        why=(
            "Generating tasks in a loop works, but without a TaskGroup the UI shows "
            "dozens of flat tasks that are hard to navigate and monitor. For 5+ "
            "dynamically generated tasks, use TaskGroup for cleaner visualisation."
        ),
        fix=(
            "# OK but hard to monitor at scale\n"
            "for item in items:\n"
            "    task = PythonOperator(task_id=f'process_{item}', ...)\n\n"
            "# Better — wrap in TaskGroup\n"
            "from airflow.utils.task_group import TaskGroup\n"
            "with TaskGroup('process_items') as tg:\n"
            "    for item in items:\n"
            "        PythonOperator(task_id=f'process_{item}', ...)"
        ),
    ),
]