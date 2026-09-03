"""Runtime configuration. Every secret is read here, server-side, and never serialised into a response."""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
SCORING_DIR = Path(os.environ.get("SCORING_DIR", BACKEND_ROOT / "scoring"))

# scorer_engine.py / resume_parser.py / resume_structure.py / semantic_signal_matcher.py
# import each other flat, so their directory has to be importable as-is.
if str(SCORING_DIR) not in sys.path:
    sys.path.insert(0, str(SCORING_DIR))

# One model name for the whole process. scorer_engine and resume_parser each carry
# their own default; this is the value the API actually passes in, so the two cannot drift.
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL_NAME", "gemini-3.6-flash")

# Models to try when the primary one is refusing work.
#
# Gemini sheds load per-model: a 503 "experiencing high demand" or a 504 means that
# model is busy, not that the request is bad, and a sibling model usually answers
# straight away. Free-tier quota is also counted per model, so a 429 has the same
# remedy. Ordered nearest-first so a fallback answer stays as close to the primary as
# possible. Set GEMINI_FALLBACK_MODELS (comma-separated, or empty to disable).
# How long one model gets before the call moves to the next one.
#
# Load-shedding does not always arrive as a 503: an overloaded model may instead simply
# take minutes to answer, which a fallback chain cannot detect. A deadline converts that
# hang into an error the chain can act on. Generous enough for the long scoring prompts,
# short enough that a stalled model does not hold up an evaluation.
GEMINI_TIMEOUT_SECONDS = float(os.environ.get("GEMINI_TIMEOUT_SECONDS", "45"))

# Ordered by what actually answers, not by version number. Measured 2026-09-02 while
# the primary was quota-exhausted:
#   gemini-3.5-flash        OK    4.9s
#   gemini-3.1-flash-lite   OK    2.6s
#   gemini-3.7-flash        504  99.7s  <- excluded: a stall this long, six calls per
#                                          evaluation, is what exhausts the client timeout
#   gemini-3.8-flash        503   3.0s  <- excluded: no better than the primary
# A model that fails fast is cheap to try; one that fails slowly is not, so the chain is
# only worth as much as its slowest member.
GEMINI_FALLBACK_MODELS = [
    m.strip()
    for m in os.environ.get(
        "GEMINI_FALLBACK_MODELS", "gemini-3.5-flash,gemini-3.1-flash-lite"
    ).split(",")
    if m.strip()
]

# Never returned to the client. Absence is reported as a capability flag, not as the key itself.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

# Additional keys, tried when one runs out of quota.
#
# Gemini's free tier counts requests per day, per model, per *project* — so a second key
# from the same project shares the same exhausted allowance and buys nothing, while a key
# from a different project is a fresh one. Set GEMINI_API_KEYS to a comma-separated list
# to rotate across projects; GEMINI_API_KEY alone still works and remains the first tried.
GEMINI_API_KEYS = [
    k.strip()
    for k in ([GEMINI_API_KEY or ""] + os.environ.get("GEMINI_API_KEYS", "").split(","))
    if k.strip()
]
# Preserve order while dropping duplicates, so the same key is never tried twice.
GEMINI_API_KEYS = list(dict.fromkeys(GEMINI_API_KEYS))

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 8 * 1024 * 1024))
EVALUATION_TIMEOUT_SECONDS = int(os.environ.get("EVALUATION_TIMEOUT_SECONDS", 180))

# Recruiter knowledge graph.
#
# The BUILT export is preferred: it carries observed IITK recruiting per cycle, per-company
# branch affinity and evidence strength, none of which exist in the seed. Produce it with
# `python3 iitk_kg.py build` from recruiter-kg/. The seed is the fallback so the pipeline
# runs before anyone has built it — with tiers only, and no observed signal.
KG_EXPORT_PATH = Path(
    os.environ.get("KG_EXPORT_PATH", REPO_ROOT / "recruiter-kg" / "kg_export.json")
)
KG_SEED_PATH = Path(
    os.environ.get("KG_COMPANIES_PATH", REPO_ROOT / "recruiter-kg" / "companies.seed.json")
)
# Retained for anything still reading the old name.
KG_COMPANIES_PATH = KG_SEED_PATH

CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if o.strip()
]


def gemini_available() -> bool:
    return bool(GEMINI_API_KEY)
