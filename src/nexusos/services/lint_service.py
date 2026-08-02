"""Static-analysis service for the NexusOS kernel source (`nexusos lint`).

Developer tooling: this command runs the project's existing lint/type-check
tooling (ruff, mypy) over the kernel source and reports findings. It returns
a non-zero exit code when any tool fails or cannot be run.

This is deliberately NOT the workspace vault linter (broken wiki links,
invalid frontmatter, orphan pages, ...). That is a future product feature
tracked on the roadmap; ``nexusos lint`` today is a developer command that
operates on the NexusOS source tree itself.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from nexusos import __version__
from nexusos.core.models import LintCheck, LintReport, LintStatus

#: Tool name → argv prefix. Each tool is run from the repo root so it picks
#: up the project's own configuration in pyproject.toml.
LINT_TOOLS: dict[str, tuple[str, ...]] = {
    "ruff": ("ruff", "check"),
    "format": ("ruff", "format", "--check"),
    "mypy": ("mypy",),
}

#: Default source target passed to the tools (mirrors CI and the dev guide).
_MYPY_TARGET = "src"


def find_repo_root(start: Path | None = None) -> Path | None:
    """Locate the NexusOS repository root (the dir containing pyproject.toml).

    Walks up from the installed package location so the command works from
    any working directory, not just the checkout root.
    """
    probe = start or Path(__file__).resolve()
    if not probe.is_dir():
        probe = probe.parent
    for parent in (probe, *probe.parents):
        if (parent / "pyproject.toml").is_file():
            return parent
    return None


def _find_tool(name: str, repo_root: Path) -> str | None:
    """Resolve a tool executable, preferring the repo's own virtualenv."""
    on_path = shutil.which(name)
    if on_path is not None:
        return on_path
    for candidate in (
        repo_root / ".venv" / "bin" / name,
        repo_root / ".venv" / "Scripts" / f"{name}.exe",
        repo_root / ".venv" / "Scripts" / name,
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _run_tool(tool: str, repo_root: Path) -> LintCheck:
    """Run one static-analysis tool and return its check result."""
    argv = LINT_TOOLS[tool]
    exe = _find_tool(argv[0], repo_root)
    if exe is None:
        return LintCheck(
            tool=tool,
            status=LintStatus.ERROR,
            message=f"tool '{argv[0]}' not found on PATH or in {repo_root / '.venv'}",
        )

    target = _MYPY_TARGET if tool == "mypy" else "."
    command = [exe, *argv[1:], target]

    try:
        proc = subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return LintCheck(
            tool=tool,
            status=LintStatus.ERROR,
            message="timed out after 180s",
        )
    except OSError as exc:
        return LintCheck(
            tool=tool,
            status=LintStatus.ERROR,
            message=f"could not run tool: {exc}",
        )

    output = (proc.stdout or "").strip()
    if proc.returncode == 0:
        return LintCheck(
            tool=tool,
            status=LintStatus.PASS,
            message="no findings",
            output=output,
        )
    detail = output or "non-zero exit"
    return LintCheck(
        tool=tool,
        status=LintStatus.FAIL,
        message="findings reported",
        output=detail,
    )


def run_lint(*, repo_root: Path | None = None, tool: str | None = None) -> LintReport:
    """Run the kernel static-analysis tooling and return a typed report.

    Args:
        repo_root: Repository root (defaults to discovery from the package).
        tool: Restrict to one tool: ``ruff``, ``format``, or ``mypy``.
    """
    root = repo_root or find_repo_root()
    if root is None:
        return LintReport(
            repo_root="(unknown)",
            checks=[
                LintCheck(
                    tool="all",
                    status=LintStatus.ERROR,
                    message="could not locate the NexusOS source tree (pyproject.toml)",
                )
            ],
            errors=1,
        )

    selected = [tool] if tool is not None else list(LINT_TOOLS)
    checks = [_run_tool(name, root) for name in selected]
    report = LintReport(
        repo_root=str(root),
        checks=checks,
        passed=sum(1 for c in checks if c.status == LintStatus.PASS),
        failed=sum(1 for c in checks if c.status == LintStatus.FAIL),
        errors=sum(1 for c in checks if c.status == LintStatus.ERROR),
    )
    return report


def print_lint_report(report: LintReport, *, use_json: bool = False) -> None:
    """Print a lint report to stdout (human or JSON form)."""
    import json as _json

    if use_json:
        payload = report.model_dump(mode="json")
        payload["has_findings"] = report.has_findings
        _json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    sys.stdout.write(f"NexusOS lint — static checks over kernel source (nexusos {__version__})\n")
    sys.stdout.write(f"Repo root: {report.repo_root}\n")
    for check in report.checks:
        icon = {
            LintStatus.PASS: "[PASS]",
            LintStatus.FAIL: "[FAIL]",
            LintStatus.ERROR: "[ERR ]",
        }[check.status]
        sys.stdout.write(f"  {icon} {check.tool:<8} {check.message}\n")
        if check.output and check.status != LintStatus.PASS:
            for line in check.output.splitlines()[:40]:
                sys.stdout.write(f"         {line}\n")
    sys.stdout.write(
        f"\nPassed: {report.passed}  Failed: {report.failed}  Errors: {report.errors}\n"
    )
    if report.has_findings:
        sys.stdout.write("Findings detected — run the tools locally for details.\n")
    else:
        sys.stdout.write("All checks passed.\n")
