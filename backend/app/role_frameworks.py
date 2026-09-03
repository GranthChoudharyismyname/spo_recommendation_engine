"""
Role-wise IITK evaluation frameworks.

`ROLE_RUBRICS` in scorer_engine is a compact rubric — 804 to 2,448 characters. The
frameworks in `knowledge-base/role-frameworks/` are the full articles the signal corpora
were labelled against: 9,349 to 15,392 characters covering tier definitions, the SCOPE
worked example, articulation principles, red flags, and IITK institutional knowledge.

Feeding only the rubric meant the evaluator was working with as little as 5% of the
available guidance for a track, and judging resumes against a different standard from the
one the corpora were built on.

This module loads the framework at runtime and the scorer APPENDS it to the system
prompt. `ROLE_RUBRICS` is left byte-identical and still leads the prompt, so the rubric
remains the primary instruction and the framework is supporting context.

Loading is cached per track and degrades to nothing if a file is missing, so the pipeline
runs unchanged without the knowledge base present.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("resume_intelligence.frameworks")

DEFAULT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "knowledge-base" / "role-frameworks"
)

# Canonical track code -> framework filename.
FRAMEWORK_FILES: Dict[str, str] = {
    "ANALYST_AIML": "analyst_aiml.txt",
    "CONSULT_PM": "consult_pm.txt",
    "CORE_TECHNOM": "core_technom.txt",
    "QUANT": "quant.txt",
    "SDE": "sde.txt",
}

# Guards the prompt against an unexpectedly large file. The largest shipped framework is
# ~15k characters, so this is headroom rather than a real constraint.
MAX_CHARS = 40_000


def framework_dir() -> Path:
    return Path(os.environ.get("ROLE_FRAMEWORKS_DIR") or DEFAULT_DIR)


@lru_cache(maxsize=8)
def load(track: str) -> Optional[str]:
    """The full framework for a track, or None when it is unavailable."""
    filename = FRAMEWORK_FILES.get(track)
    if not filename:
        return None
    path = framework_dir() / filename
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:
        logger.warning("role framework for %s not loaded from %s (%s)", track, path, exc)
        return None
    if not text:
        return None
    if len(text) > MAX_CHARS:
        logger.warning("role framework for %s truncated from %d to %d chars",
                       track, len(text), MAX_CHARS)
        text = text[:MAX_CHARS]
    return text


def prompt_section(track: str) -> str:
    """
    The framework formatted for appending to a system prompt, or "" when unavailable.

    Framed explicitly as supporting context so it cannot be read as overriding the rubric
    that precedes it, and the scoring bands stay the rubric's.
    """
    text = load(track)
    if not text:
        return ""
    return (
        "\n\n"
        "=========================================================\n"
        f"SUPPORTING FRAMEWORK — {track}\n"
        "=========================================================\n"
        "The rubric above defines the scoring bands and takes precedence. What follows is\n"
        "the full IITK evaluation framework for this track: tier definitions, what strong\n"
        "and diluting evidence looks like, the SCOPE framework for judging bullets, and\n"
        "institutional context. Use it to decide WHERE a candidate falls inside a band and\n"
        "to justify that placement. Do not invent bands that are not in the rubric.\n"
        "---------------------------------------------------------\n"
        f"{text}\n"
        "---------------------------------------------------------\n"
    )


def availability() -> Dict[str, bool]:
    """Which tracks have a framework on disk. Reported by /api/health."""
    return {track: load(track) is not None for track in FRAMEWORK_FILES}
