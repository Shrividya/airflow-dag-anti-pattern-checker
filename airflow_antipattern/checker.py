import logging
import re as _re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from .rules import RULES, Rule

_log = logging.getLogger(__name__)

_TASK_FN_RE = _re.compile(r"^def \w+\s*\([^)]*\*\*context[^)]*\)\s*:", _re.MULTILINE)


def _find_large_task_functions(lines: list[str], threshold: int = 30) -> list[int]:
    """
    Return the starting line numbers of task callables (**context functions)
    whose body is at least `threshold` non-blank lines long.

    Think of it like measuring each recipe individually — we don't add up
    all the recipes in a cookbook to decide if one is too long.
    """
    hits: list[int] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _TASK_FN_RE.match(line):
            fn_start = i + 1  # 1-indexed
            # Measure the indented body
            indent = len(line) - len(line.lstrip())
            body_lines = 0
            j = i + 1
            while j < len(lines):
                body = lines[j]
                if body.strip() == "":
                    j += 1
                    continue
                body_indent = len(body) - len(body.lstrip())
                if body_indent <= indent and body.strip():
                    break  # back to same or lower indent — function ended
                body_lines += 1
                j += 1
            if body_lines >= threshold:
                hits.append(fn_start)
        i += 1
    return hits

@dataclass
class Finding:
    rule: Rule
    filepath: Path
    line_numbers: list[int]

    @property
    def severity(self) -> str:
        return self.rule.severity

    @property
    def code(self) -> str:
        return self.rule.code


SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

def check_file(
    filepath: Path,
    select: Optional[list[str]] = None,
    ignore: Optional[list[str]] = None,
    min_severity: Optional[str] = None,
) -> list[Finding]:
    """
    Analyse a single DAG file and return all findings.

    Parameters
    ----------
    filepath    : path to the .py file
    select      : only run these rule codes (e.g. ["TLC001", "RET001"])
    ignore      : skip these rule codes
    min_severity: "high" | "medium" | "low" — skip findings below this level
    """
    source = filepath.read_text(encoding="utf-8", errors="replace")
    lines = source.splitlines()

    findings: list[Finding] = []

    for rule in RULES:
        if select and rule.code not in select:
            continue
        if ignore and rule.code in ignore:
            continue
        if min_severity:
            if SEVERITY_ORDER.get(rule.severity, 99) > SEVERITY_ORDER.get(min_severity, 99):
                continue

        if rule.code == "ATO001":
            matched_lines = _find_large_task_functions(lines, threshold=30)
            if matched_lines:
                findings.append(Finding(rule=rule, filepath=filepath, line_numbers=matched_lines))
            continue

        if rule.neg_pattern and rule.neg_pattern.search(source):
            continue

        matched_lines: list[int] = []
        for i, line in enumerate(lines, start=1):
            if rule.pattern.search(line):
                matched_lines.append(i)

        if not matched_lines:
            continue

        findings.append(Finding(rule=rule, filepath=filepath, line_numbers=matched_lines))

    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 99), f.code))
    return findings


def run_ruff_check(path: str) -> list[str]:
    """Run 'ruff check --select AIR3' on *path* and return output lines."""
    try:
        result = subprocess.run(
            ["ruff", "check", path, "--select", "AIR3"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        _log.warning("ruff not found — install with: pip install ruff")
        return ["ruff not found — install with: pip install ruff"]

    if result.returncode != 0:
        _log.warning("ruff found issues in %s", path)
        return result.stdout.splitlines()
    return ["No issues found!"]

def check_path(
    path: Path,
    select: Optional[list[str]] = None,
    ignore: Optional[list[str]] = None,
    min_severity: Optional[str] = None,
    exclude_dirs: Optional[list[str]] = None,
) -> dict[Path, list[Finding]]:
    """
    Recursively scan a file or directory for DAG anti-patterns.
    Returns a dict of {filepath: [Finding, ...]}
    """
    exclude_dirs = exclude_dirs or []
    results: dict[Path, list[Finding]] = {}

    if path.is_file():
        if path.suffix == ".py":
            findings = check_file(path, select, ignore, min_severity)
            if findings:
                results[path] = findings
        return results

    for py_file in sorted(path.rglob("*.py")):
        # Skip excluded directories
        if any(excl in py_file.parts for excl in exclude_dirs):
            continue
        findings = check_file(py_file, select, ignore, min_severity)
        if findings:
            results[py_file] = findings
    return results