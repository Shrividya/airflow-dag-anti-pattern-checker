"""CLI entry point for airflow-antipattern."""

import sys
from pathlib import Path
from typing import Optional

import click

from . import __version__
from .checker import check_path, Finding, SEVERITY_ORDER


# ── ANSI colours (no external dep needed) ────────────────────────────────────
def _c(text: str, code: str) -> str:
    """Wrap text in an ANSI colour code (auto-stripped when not a tty)."""
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"

RED     = lambda t: _c(t, "31")
YELLOW  = lambda t: _c(t, "33")
GREEN   = lambda t: _c(t, "32")
CYAN    = lambda t: _c(t, "36")
BOLD    = lambda t: _c(t, "1")
DIM     = lambda t: _c(t, "2")

SEV_COLOR = {"high": RED, "medium": YELLOW, "low": GREEN}
SEV_ICON  = {"high": "●", "medium": "◐", "low": "○"}


def _severity_label(sev: str) -> str:
    col = SEV_COLOR.get(sev, str)
    icon = SEV_ICON.get(sev, " ")
    return col(f"{icon} {sev.upper():<6}")


def _print_findings(
    results: dict,
    show_fix: bool,
    show_why: bool,
) -> None:
    for filepath, findings in results.items():
        click.echo(f"\n{BOLD(str(filepath))}")
        for f in findings:
            lines_str = ""
            if f.line_numbers:
                lines_str = DIM(f"  line {', '.join(str(l) for l in f.line_numbers[:3])}")

            click.echo(
                f"  {_severity_label(f.severity)}  "
                f"{CYAN(f.rule.code):<12}  "
                f"{f.rule.title}"
                f"{lines_str}"
            )

            if show_why:
                for line in f.rule.why.splitlines():
                    click.echo(f"             {DIM(line)}")

            if show_fix:
                click.echo(f"             {GREEN('Fix:')}")
                for line in f.rule.fix.splitlines():
                    click.echo(f"               {DIM(line)}")

                click.echo()


def _print_summary(results: dict) -> tuple[int, int, int]:
    all_findings: list[Finding] = [f for findings in results.values() for f in findings]
    high   = sum(1 for f in all_findings if f.severity == "high")
    medium = sum(1 for f in all_findings if f.severity == "medium")
    low    = sum(1 for f in all_findings if f.severity == "low")
    total  = len(all_findings)
    files  = len(results)

    click.echo()
    click.echo("─" * 50)
    click.echo(
        f"Found {BOLD(str(total))} issue(s) in {files} file(s)  "
        f"{RED(f'● {high} high')}  "
        f"{YELLOW(f'◐ {medium} medium')}  "
        f"{GREEN(f'○ {low} low')}"
    )
    return high, medium, low


# ── CLI definition ────────────────────────────────────────────────────────────

@click.group()
@click.version_option(__version__, prog_name="airflow-antipattern")
def cli():
    """Airflow DAG anti-pattern detector.

    Catch performance, reliability, and maintainability issues
    in your DAG files before they reach production.
    """


@cli.command("check")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--severity", "-s",
    type=click.Choice(["high", "medium", "low"], case_sensitive=False),
    default="low",
    show_default=True,
    help="Minimum severity level to report.",
)
@click.option(
    "--select",
    default=None,
    help="Comma-separated rule codes to run, e.g. TLC001,RET001",
)
@click.option(
    "--ignore",
    default=None,
    help="Comma-separated rule codes to skip, e.g. HDC003,ATO002",
)
@click.option(
    "--exclude-dirs",
    default="__pycache__,.venv,venv,node_modules",
    show_default=True,
    help="Comma-separated directory names to exclude.",
)
@click.option("--fix", "show_fix", is_flag=True, default=False, help="Show fix suggestions.")
@click.option("--why", "show_why", is_flag=True, default=False, help="Show why each rule matters.")
@click.option(
    "--output", "-o",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Output format.",
)
def check_cmd(
    path: Path,
    severity: str,
    select: Optional[str],
    ignore: Optional[str],
    exclude_dirs: str,
    show_fix: bool,
    show_why: bool,
    output: str,
):
    """Check PATH (file or directory) for Airflow DAG anti-patterns."""

    select_list = [s.strip().upper() for s in select.split(",")] if select else None
    ignore_list = [s.strip().upper() for s in ignore.split(",")] if ignore else None
    exclude_list = [d.strip() for d in exclude_dirs.split(",") if d.strip()]

    results = check_path(
        path,
        select=select_list,
        ignore=ignore_list,
        min_severity=severity,
        exclude_dirs=exclude_list,
    )

    if not results:
        click.echo(GREEN("\nNo anti-patterns detected. Clean DAGs!"))
        sys.exit(0)

    if output == "json":
        _print_json(results)
    else:
        _print_findings(results, show_fix=show_fix, show_why=show_why)
        high, medium, low = _print_summary(results)

    # Exit 1 if any HIGH findings, 0 otherwise (useful for CI)
    total_high = sum(
        1 for findings in results.values() for f in findings if f.severity == "high"
    )
    sys.exit(1 if total_high > 0 else 0)


@cli.command("rules")
@click.option(
    "--category", "-c",
    default=None,
    help="Filter by category prefix, e.g. TLC, RET, HDC, DEP, ATO",
)
@click.option(
    "--severity", "-s",
    type=click.Choice(["high", "medium", "low"], case_sensitive=False),
    default=None,
    help="Filter by severity.",
)
def rules_cmd(category: Optional[str], severity: Optional[str]):
    """List all available rules."""
    from .rules import RULES

    filtered = RULES
    if category:
        filtered = [r for r in filtered if r.category.upper() == category.upper()]
    if severity:
        filtered = [r for r in filtered if r.severity == severity.lower()]

    if not filtered:
        click.echo("No rules match the given filters.")
        return

    current_cat = None
    for rule in filtered:
        if rule.category != current_cat:
            current_cat = rule.category
            click.echo(f"\n{BOLD(rule.category_label)} ({rule.category})")
            click.echo("─" * 40)

        click.echo(
            f"  {CYAN(rule.code):<12}  "
            f"{_severity_label(rule.severity)}  "
            f"{rule.title}"
        )


def _print_json(results: dict) -> None:
    import json

    output = []
    for filepath, findings in results.items():
        for f in findings:
            output.append({
                "file": str(filepath),
                "rule": f.rule.code,
                "category": f.rule.category,
                "severity": f.rule.severity,
                "title": f.rule.title,
                "lines": f.line_numbers,
                "why": f.rule.why,
                "fix": f.rule.fix,
            })

    click.echo(json.dumps(output, indent=2))


def main():
    cli()


if __name__ == "__main__":
    main()
