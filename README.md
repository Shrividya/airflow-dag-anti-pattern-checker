# airflow-antipattern-checker

**A static analysis linter for Apache Airflow DAGs — catch performance,
reliability, and maintainability issues before they reach production.**

No Airflow installation required. Runs in CI/CD pipelines with zero overhead.

---

## Quick start

```bash

# Check a single file
airflow-antipattern check dags/my_dag.py

# Check an entire DAGs folder
airflow-antipattern check dags/

# Show fix suggestions inline
airflow-antipattern check dags/ --fix

# Only report HIGH severity issues (useful in CI)
airflow-antipattern check dags/ --severity=high

# JSON output for integration with other tools
airflow-antipattern check dags/ --output=json
```

## Using Streamlit:
```
streamlit run ./streamlit_app.py
```

Exit code `0` — no HIGH findings. Exit code `1` — one or more HIGH violations.

---

## What it catches

| Code | Category | Severity | Rule |
|------|----------|----------|------|
| TLC001 | Top-level code | 🔴 HIGH | Database call at module level |
| TLC002 | Top-level code | 🟡 MEDIUM | Heavy library imported at module level |
| TLC003 | Top-level code | 🔴 HIGH | HTTP/API call at module level |
| RET001 | Retries | 🔴 HIGH | No retries configured on operator |
| RET002 | Retries | 🟡 MEDIUM | Retries set but no retry_delay |
| HDC001 | Hardcoding | 🔴 HIGH | Hardcoded credential or secret |
| HDC002 | Hardcoding | 🔴 HIGH | datetime.now() used as start_date |
| HDC003 | Hardcoding | 🟢 LOW | Hardcoded absolute file path |
| DEP001 | Dependencies | 🟡 MEDIUM | No task dependencies defined |
| DEP002 | Dependencies | 🟡 MEDIUM | catchup not explicitly set |
| ATO001 | Atomicity | 🟡 MEDIUM | Large monolithic task callable |
| ATO002 | Atomicity | 🟢 LOW | Dynamic task loop without TaskGroup |

---

## CLI reference

### `check`

```
airflow-antipattern check PATH [OPTIONS]

Arguments:
  PATH          File or directory to scan

Options:
  -s, --severity [high|medium|low]   Minimum severity to report (default: low)
  --select TEXT                      Comma-separated rule codes to run
  --ignore TEXT                      Comma-separated rule codes to skip
  --exclude-dirs TEXT                Comma-separated dirs to exclude
  --fix                              Show fix suggestions
  --why                              Show why each rule matters
  -o, --output [text|json]           Output format (default: text)
  --version                          Show version and exit
```

### `rules`

```
airflow-antipattern rules [OPTIONS]

Options:
  -c, --category TEXT                Filter by category (TLC, RET, HDC, DEP, ATO)
  -s, --severity [high|medium|low]   Filter by severity
```

---

## Configuration

Add a `[tool.airflow-antipattern]` section to your `pyproject.toml`:

```toml
[tool.airflow-antipattern]
severity = "medium"           # ignore LOW findings
ignore = ["HDC003", "ATO002"] # suppress specific rules
exclude_dirs = ["__pycache__", ".venv", "tests"]
```

---

## CI/CD integration

### GitHub Actions

```yaml
- name: Check DAGs for anti-patterns
  run: |
    pip install airflow-antipattern
    airflow-antipattern check dags/ --severity=high
```

Exit code 1 on HIGH findings automatically fails the workflow.

### Pre-commit hook

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: airflow-antipattern
        name: Airflow DAG anti-pattern check
        entry: airflow-antipattern check
        language: python
        files: \.py$
        args: ["--severity=medium"]
```

---

## Suppressing a rule on a specific line

Add a `# noqa: <CODE>` comment to suppress a rule for that line:

```python
conn = psycopg2.connect(os.environ["DB"])  # noqa: TLC001
```

---

## Severity levels

| Severity | Meaning | CI behaviour |
|----------|---------|-------------|
| 🔴 HIGH | Scheduler crashes, data loss risk, credential exposure | Fails CI (exit 1) |
| 🟡 MEDIUM | Performance degradation, backfill explosions | Warning only |
| 🟢 LOW | Style, minor inefficiencies | Warning only |

---

## Adding custom rules

Rules live in `airflow_antipattern/rules.py`. Each rule is a `Rule` dataclass:

```python
Rule(
    code="HDC004",
    category="HDC",
    category_label="Hardcoding",
    title="Hardcoded environment name",
    severity="low",
    pattern=re.compile(r"['\"]production['\"]", re.IGNORECASE),
    why="Hardcoded environment names break when promoting across envs.",
    fix="Use Variable.get('env') or os.environ['ENV'] instead.",
)
```
