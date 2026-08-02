"""YAML frontmatter extraction from Markdown documents.

Uses the standard library yaml module. Must be parsed safely — no arbitrary
Python objects via YAML tags or constructors.
"""

from __future__ import annotations

from typing import Any

import yaml  # type: ignore[import-untyped]


def extract_frontmatter(text: str) -> tuple[dict[str, Any], str, int, list[str]]:
    """Extract YAML frontmatter from the start of a Markdown document."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text, 1, []

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, text, 1, ["unclosed frontmatter delimiter: no closing '---' found"]

    fm_text = "\n".join(lines[1:end_idx])

    if not fm_text.strip():
        return {}, "\n".join(lines[end_idx + 1 :]), end_idx + 2, []

    # Safe YAML — use SafeLoader directly (it already blocks arbitrary objects)
    try:
        data: Any = yaml.safe_load(fm_text)
    except yaml.YAMLError as exc:
        return (
            {},
            "\n".join(lines[end_idx + 1 :]),
            end_idx + 2,
            [f"invalid YAML frontmatter: {exc}"],
        )

    if not isinstance(data, dict):
        return (
            {},
            "\n".join(lines[end_idx + 1 :]),
            end_idx + 2,
            ["frontmatter must be a YAML mapping, got a scalar or sequence"],
        )

    warnings: list[str] = []

    dupes = _detect_duplicate_keys(fm_text)
    if dupes:
        warnings.append(f"duplicate YAML keys in frontmatter: {', '.join(sorted(dupes))}")

    clean: dict[str, Any] = _jsonify(data)

    body_text = "\n".join(lines[end_idx + 1 :])
    return clean, body_text, end_idx + 2, warnings


def _detect_duplicate_keys(yaml_str: str) -> set[str]:
    """Find duplicate keys in a YAML mapping using line-by-line scanning."""
    import re

    seen: dict[str, int] = {}
    dupes: set[str] = set()
    key_re = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_-]*)\s*:")
    for line in yaml_str.split("\n"):
        m = key_re.match(line)
        if m:
            key = m.group(1)
            if key in seen:
                dupes.add(key)
            else:
                seen[key] = 1
    return dupes


def _jsonify(obj: Any) -> Any:
    """Recursively convert YAML values to JSON-serializable types."""
    if isinstance(obj, dict):
        return {str(k): _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonify(v) for v in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)
