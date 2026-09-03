"""
SPO guideline configuration.

The guidelines are revised each placement cycle — word counts, font rules and which
items are forbidden on a submitted resume all move — so they live in
`config/spo-guidelines.json` rather than in code. Nothing here is hardcoded except the
fallbacks used when the file is missing, which match the 2026 cycle.

To run a different cycle: copy the JSON, edit it, and point `SPO_GUIDELINES_PATH` at it.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("resume_intelligence.spo")

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "spo-guidelines.json"

# Used only when the config file is absent or unreadable. Kept identical to the values
# `resume_structure.GUIDELINES` shipped with, so behaviour is unchanged without the file.
FALLBACK_LAYOUT: Dict[str, Any] = {
    "min_margin_in": 0.5,
    "min_margin_pt": 36.0,
    "min_content_font_size_pt": 9.0,
    "min_reference_font_size_pt": 6.0,
    "min_words": 500,
    "max_words": 750,
    "name_min_ratio": 2.0,
    "max_font_families": 1,
    "max_pages_technical": 2,
    "max_pages_non_technical": 1,
}


@lru_cache(maxsize=4)
def load(path: Optional[str] = None) -> Dict[str, Any]:
    """Loaded once per process. Falls back to the shipped defaults, never raises."""
    import os

    target = Path(path or os.environ.get("SPO_GUIDELINES_PATH") or DEFAULT_PATH)
    try:
        with target.open() as fp:
            data = json.load(fp)
        data.setdefault("layout", {})
        for key, value in FALLBACK_LAYOUT.items():
            data["layout"].setdefault(key, value)
        data["_source_path"] = str(target)
        return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("SPO guidelines not loaded from %s (%s); using built-in defaults",
                       target, exc)
        return {
            "cycle": "built-in",
            "layout": dict(FALLBACK_LAYOUT),
            "compliance_rules": {},
            "approved_headings": [],
            "preferred_fonts": [],
            "_source_path": None,
        }


def layout(path: Optional[str] = None) -> Dict[str, Any]:
    return load(path)["layout"]


def cycle(path: Optional[str] = None) -> str:
    return str(load(path).get("cycle", "unknown"))


def rule(rule_id: str, path: Optional[str] = None) -> Dict[str, Any]:
    """One compliance rule. An unknown id is treated as enabled with no overrides."""
    rules = load(path).get("compliance_rules") or {}
    entry = rules.get(rule_id)
    return entry if isinstance(entry, dict) else {"enabled": True}


def is_enabled(rule_id: str, path: Optional[str] = None) -> bool:
    return rule(rule_id, path).get("enabled", True) is not False


def severity(rule_id: str, default: str, path: Optional[str] = None) -> str:
    return str(rule(rule_id, path).get("severity") or default)


def guideline_text(rule_id: str, default: str, path: Optional[str] = None) -> str:
    return str(rule(rule_id, path).get("guideline") or default)


def message(rule_id: str, default: str, path: Optional[str] = None) -> str:
    return str(rule(rule_id, path).get("message") or default)


def approved_headings(path: Optional[str] = None) -> List[str]:
    return list(load(path).get("approved_headings") or [])


def preferred_fonts(path: Optional[str] = None) -> List[str]:
    return list(load(path).get("preferred_fonts") or [])
