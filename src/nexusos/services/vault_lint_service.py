"""Read-only workspace vault linter for NexusOS.

``nexusos lint --workspace PATH`` runs a battery of read-only checks over a
workspace's source files and its index. The linter never writes to the
workspace: it does a fresh discovery + parse pass (so it works even before
indexing) and reports findings typed by check.

Checks implemented (v0.1.0):
  - broken-links       wiki links that resolve to no document
  - ambiguous-links    wiki links matching more than one document stem
  - invalid-frontmatter  frontmatter parse warnings (bad YAML, missing `---`, duplicate keys)
  - orphans            documents no other document links to
  - duplicate-slugs    two or more documents sharing a filename stem
  - stale-index        index missing, stale, or with source drift
  - oversized-files    source files above the configured lint size cap
  - empty-documents    source files with no body content
  - symlink-escapes    symlinks resolving outside the workspace
  - outside-collections  files not under any configured collection directory
  - unreadable-files   source files that cannot be read or decoded as UTF-8

All checks reuse the discovery scanner and the parsing modules; link
resolution mirrors ``nexusos.indexing.graph`` so findings agree with what
the indexer would produce.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nexusos.core.config import load_config_effective
from nexusos.core.link_suffixes import LINK_SUFFIXES
from nexusos.core.models import (
    VaultLintCheck,
    VaultLintFinding,
    VaultLintReport,
)
from nexusos.discovery.scanner import scan_workspace
from nexusos.parsing.markdown import parse_markdown
from nexusos.parsing.models import ParsedDocument
from nexusos.parsing.plaintext import parse_plaintext
from nexusos.services.status_service import get_status
from nexusos.workspace.init import load_workspace_identity

#: Check names, in report order.
CHECK_BROKEN_LINKS = "broken-links"
CHECK_AMBIGUOUS_LINKS = "ambiguous-links"
CHECK_INVALID_FRONTMATTER = "invalid-frontmatter"
CHECK_ORPHANS = "orphans"
CHECK_DUPLICATE_SLUGS = "duplicate-slugs"
CHECK_STALE_INDEX = "stale-index"
CHECK_OVERSIZED_FILES = "oversized-files"
CHECK_EMPTY_DOCUMENTS = "empty-documents"
CHECK_SYMLINK_ESCAPES = "symlink-escapes"
CHECK_OUTSIDE_COLLECTIONS = "outside-collections"
CHECK_UNREADABLE_FILES = "unreadable-files"

#: Suffixes stripped when resolving wiki-link targets (canonical order from
#: ``nexusos.core.link_suffixes``; mirrors graph.py and kernel.py).
_RESOLVABLE_SUFFIXES = LINK_SUFFIXES


def _path_stem(normalized_path: str) -> str:
    """Return the filename stem of a normalized relative path."""
    return Path(normalized_path.replace("\\", "/")).stem


def _read_source_text(path: Path) -> tuple[str | None, str | None]:
    """Read a source file as UTF-8; return ``(text, None)`` on success.

    Returns ``(None, error_message)`` when the file cannot be read or is
    not valid UTF-8. Per-file read/decoding problems never raise, so one
    malformed source file cannot abort the whole lint run (audit MED-3).
    """
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError as exc:
        return None, f"cannot read file: {exc}"
    except UnicodeDecodeError as exc:
        return None, f"file is not valid UTF-8: {exc}"


def _parse_document(workspace_root: Path, discovered: Any) -> ParsedDocument | None:
    """Read + parse one discovered file read-only; None on read failure."""
    path = workspace_root / discovered.relative_path
    source_text, error = _read_source_text(path)
    if source_text is None or error is not None:
        return None
    if discovered.file_type == "plaintext":
        return parse_plaintext(discovered, source_text)
    return parse_markdown(discovered, source_text)


def run_vault_lint(workspace_root: Path) -> VaultLintReport:
    """Lint a NexusOS workspace vault (read-only).

    Args:
        workspace_root: Resolved workspace root.

    Returns:
        A :class:`VaultLintReport` with one check per lint category.
    """
    root = Path(workspace_root).resolve(strict=False)
    config = load_config_effective(root)

    checks: list[VaultLintCheck] = []
    identity = load_workspace_identity(root)

    # -- discovery (read-only) -------------------------------------------------
    discovery = scan_workspace(root, config)

    # Path → stem maps for link resolution.
    path_stems: dict[str, str] = {
        f.normalized_path: _path_stem(f.normalized_path) for f in discovery.files
    }
    stem_to_paths: dict[str, list[str]] = {}
    for normalized_path, stem in path_stems.items():
        stem_to_paths.setdefault(stem, []).append(normalized_path)

    def _resolve_target(slug: str) -> tuple[str | None, bool]:
        """Resolve a normalized slug → (path, ambiguous).

        Mirrors graph.py tiers: exact path, path+suffix, unique stem.
        """
        if slug in path_stems:
            return slug, False
        for suffix in _RESOLVABLE_SUFFIXES:
            if slug + suffix in path_stems:
                return slug + suffix, False
        candidates = stem_to_paths.get(slug, [])
        if len(candidates) == 1:
            return candidates[0], False
        if len(candidates) > 1:
            return None, True
        return None, False

    # -- broken / ambiguous links ----------------------------------------------
    broken: list[VaultLintFinding] = []
    ambiguous: list[VaultLintFinding] = []
    for f in discovery.files:
        parsed = _parse_document(root, f)
        if parsed is None:
            continue
        for link in parsed.wikilinks:
            slug = link.target_slug
            resolved_path, is_ambiguous = _resolve_target(slug)
            if is_ambiguous:
                ambiguous.append(
                    VaultLintFinding(
                        check=CHECK_AMBIGUOUS_LINKS,
                        path=f.relative_path,
                        line=link.source_line,
                        message=f"ambiguous link {link.raw_target!r} matches multiple documents",
                    )
                )
            elif resolved_path is None:
                broken.append(
                    VaultLintFinding(
                        check=CHECK_BROKEN_LINKS,
                        path=f.relative_path,
                        line=link.source_line,
                        message=f"unresolved link {link.raw_target!r}",
                    )
                )

    checks.append(
        VaultLintCheck(
            name=CHECK_BROKEN_LINKS,
            status="fail" if broken else "pass",
            message=f"{len(broken)} broken wiki link(s)" if broken else "no broken wiki links",
            findings=broken,
        )
    )
    checks.append(
        VaultLintCheck(
            name=CHECK_AMBIGUOUS_LINKS,
            status="fail" if ambiguous else "pass",
            message=f"{len(ambiguous)} ambiguous wiki link(s)"
            if ambiguous
            else "no ambiguous wiki links",
            findings=ambiguous,
        )
    )

    # -- unreadable files ------------------------------------------------------
    # Files that cannot be read (OSError) or decoded as UTF-8
    # (UnicodeDecodeError) are reported here and skipped by the other
    # per-file checks; one malformed file never aborts the run (MED-3).
    unreadable: list[VaultLintFinding] = []
    for f in discovery.files:
        _, error = _read_source_text(root / f.relative_path)
        if error is not None:
            unreadable.append(
                VaultLintFinding(
                    check=CHECK_UNREADABLE_FILES,
                    path=f.relative_path,
                    message=error,
                )
            )
    checks.append(
        VaultLintCheck(
            name=CHECK_UNREADABLE_FILES,
            status="fail" if unreadable else "pass",
            message=f"{len(unreadable)} unreadable file(s)" if unreadable else "all files readable",
            findings=unreadable,
        )
    )

    # -- frontmatter warnings ---------------------------------------------------
    fm_findings: list[VaultLintFinding] = []
    for f in discovery.files:
        if f.file_type == "plaintext":
            continue
        parsed = _parse_document(root, f)
        if parsed is None:
            continue
        for warning in parsed.parse_warnings:
            fm_findings.append(
                VaultLintFinding(
                    check=CHECK_INVALID_FRONTMATTER,
                    path=f.relative_path,
                    message=warning,
                )
            )
    checks.append(
        VaultLintCheck(
            name=CHECK_INVALID_FRONTMATTER,
            status="fail" if fm_findings else "pass",
            message=(
                f"{len(fm_findings)} frontmatter warning(s)" if fm_findings else "frontmatter valid"
            ),
            findings=fm_findings,
        )
    )

    # -- orphans ----------------------------------------------------------------
    incoming: dict[str, int] = {}
    for f in discovery.files:
        parsed = _parse_document(root, f)
        if parsed is None:
            continue
        for link in parsed.wikilinks:
            resolved_path, is_ambiguous = _resolve_target(link.target_slug)
            if not is_ambiguous and resolved_path is not None:
                incoming[resolved_path] = incoming.get(resolved_path, 0) + 1
    orphan_findings = [
        VaultLintFinding(
            check=CHECK_ORPHANS,
            path=f.relative_path,
            message="no other document links to this document",
        )
        for f in discovery.files
        if incoming.get(f.normalized_path, 0) == 0
    ]
    checks.append(
        VaultLintCheck(
            name=CHECK_ORPHANS,
            status="warn" if orphan_findings else "pass",
            message=f"{len(orphan_findings)} orphan document(s)"
            if orphan_findings
            else "no orphans",
            findings=orphan_findings,
        )
    )

    # -- duplicate slugs --------------------------------------------------------
    dup_findings: list[VaultLintFinding] = []
    for stem, paths in sorted(stem_to_paths.items()):
        if len(paths) > 1:
            for p in sorted(paths):
                dup_findings.append(
                    VaultLintFinding(
                        check=CHECK_DUPLICATE_SLUGS,
                        path=p,
                        message=f"duplicate slug {stem!r} also used by {', '.join(sorted(paths))}",
                    )
                )
    checks.append(
        VaultLintCheck(
            name=CHECK_DUPLICATE_SLUGS,
            status="fail" if dup_findings else "pass",
            message=f"{len(dup_findings)} duplicate slug(s)"
            if dup_findings
            else "no duplicate slugs",
            findings=dup_findings,
        )
    )

    # -- stale index -------------------------------------------------------------
    stale_reasons: list[str] = []
    if identity is None:
        stale_reasons.append("no workspace identity")
    else:
        status = get_status(root)
        stale_reasons = list(status.get("stale_reasons", []))
        if status.get("status") == "error":
            stale_reasons.append("index error")
        if not stale_reasons and status.get("status") == "uninitialized":
            stale_reasons.append("no index")
    checks.append(
        VaultLintCheck(
            name=CHECK_STALE_INDEX,
            status="fail" if stale_reasons else "pass",
            message="; ".join(stale_reasons) if stale_reasons else "index is fresh",
            findings=[
                VaultLintFinding(
                    check=CHECK_STALE_INDEX,
                    path="",
                    message=reason,
                )
                for reason in stale_reasons
            ],
        )
    )

    # -- oversized / empty / symlink / outside collections -----------------------
    oversized: list[VaultLintFinding] = []
    empty: list[VaultLintFinding] = []
    outside: list[VaultLintFinding] = []
    for f in discovery.files:
        if f.size_bytes > config.lint_max_file_size_bytes:
            oversized.append(
                VaultLintFinding(
                    check=CHECK_OVERSIZED_FILES,
                    path=f.relative_path,
                    message=(
                        f"{f.size_bytes} bytes exceeds lint cap {config.lint_max_file_size_bytes}"
                    ),
                )
            )
        if config.lint_warn_empty_docs:
            parsed = _parse_document(root, f)
            if parsed is not None and parsed.body_text.strip() == "":
                empty.append(
                    VaultLintFinding(
                        check=CHECK_EMPTY_DOCUMENTS,
                        path=f.relative_path,
                        message="document has no body content",
                    )
                )
        if config.collection_mappings and f.collection == config.default_collection:
            outside.append(
                VaultLintFinding(
                    check=CHECK_OUTSIDE_COLLECTIONS,
                    path=f.relative_path,
                    message=(
                        f"file is outside every configured collection "
                        f"(fell back to default collection {config.default_collection!r})"
                    ),
                )
            )

    checks.append(
        VaultLintCheck(
            name=CHECK_OVERSIZED_FILES,
            status="fail" if oversized else "pass",
            message=f"{len(oversized)} oversized file(s)" if oversized else "no oversized files",
            findings=oversized,
        )
    )
    checks.append(
        VaultLintCheck(
            name=CHECK_EMPTY_DOCUMENTS,
            status="warn" if empty else "pass",
            message=f"{len(empty)} empty document(s)" if empty else "no empty documents",
            findings=empty,
        )
    )

    symlink_findings = [
        VaultLintFinding(
            check=CHECK_SYMLINK_ESCAPES,
            path=str(w.get("path", "")),
            message=str(w.get("message", w.get("type", "symlink issue"))),
        )
        for w in discovery.warnings
        if w.get("type") in ("symlink_escape", "symlink_denied", "unreadable_symlink")
    ]
    checks.append(
        VaultLintCheck(
            name=CHECK_SYMLINK_ESCAPES,
            status="fail" if symlink_findings else "pass",
            message=(
                f"{len(symlink_findings)} symlink issue(s)"
                if symlink_findings
                else "no symlink issues"
            ),
            findings=symlink_findings,
        )
    )
    checks.append(
        VaultLintCheck(
            name=CHECK_OUTSIDE_COLLECTIONS,
            status="warn" if outside else "pass",
            message=(
                f"{len(outside)} file(s) outside collections"
                if outside
                else "all files in collections"
            ),
            findings=outside,
        )
    )

    passed = sum(1 for c in checks if c.status == "pass")
    warned = sum(1 for c in checks if c.status == "warn")
    failed = sum(1 for c in checks if c.status == "fail")
    return VaultLintReport(
        workspace=str(root),
        checks=checks,
        passed=passed,
        warned=warned,
        failed=failed,
    )


def print_vault_lint_report(report: VaultLintReport, *, use_json: bool = False) -> None:
    """Print a vault lint report to stdout (human or JSON form)."""
    import json as _json
    import sys

    if use_json:
        payload = report.model_dump(mode="json")
        payload["has_findings"] = report.has_findings
        _json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    sys.stdout.write(f"NexusOS vault lint — {report.workspace}\n")
    for check in report.checks:
        icon = {
            "pass": "[PASS]",
            "warn": "[WARN]",
            "fail": "[FAIL]",
        }[check.status]
        sys.stdout.write(f"  {icon} {check.name:<24} {check.message}\n")
        for finding in check.findings[:20]:
            where = f"{finding.path}" + (f":{finding.line}" if finding.line else "")
            sys.stdout.write(f"         {where}  {finding.message}\n")
    sys.stdout.write(
        f"\nPassed: {report.passed}  Warned: {report.warned}  Failed: {report.failed}\n"
    )
    if report.has_findings:
        sys.stdout.write("Findings detected — fix the reported issues and re-lint.\n")
    else:
        sys.stdout.write("Vault lint clean.\n")
