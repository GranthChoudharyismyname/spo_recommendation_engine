"""
Size and standing for organisations the recruiter knowledge graph does not carry.

The KG covers firms that recruit at IIT Kanpur. Plenty of legitimate employers sit
outside it — a research lab, an overseas firm, a startup, a company that simply has not
run a campus process here. Previously any such name was reported as "did not resolve to
any curated entry", worded so that it read as a data error and put the candidate's own
employer under suspicion.

This module answers the question that was actually being asked: how large and how
established is this organisation? The model is asked to place it in a size band and to
say plainly when it does not recognise the name, which is a fact about coverage rather
than a fault in the resume. Nothing here changes a score; it changes what the candidate
is told.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import llm

log = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parent.parent / "config" / "company-profiles.json"

# Ordered largest to smallest. `unrecognised` is not a size; it records that the model
# had nothing to say, which must never be dressed up as a judgement about the firm.
SIZE_BANDS = {
    "global_major": "Large multinational",
    "large": "Large established firm",
    "mid": "Mid-size firm",
    "small": "Small firm",
    "startup": "Startup or early-stage",
    "research": "Research lab or institute",
    "unrecognised": "Not widely documented",
}

_SYSTEM = (
    "You size up employers for a university placement office. For each organisation, "
    "state how large and established it is from your own knowledge. You are describing "
    "the organisation, never judging the person who worked there. If a name is not one "
    "you recognise, say so with band 'unrecognised' — do not guess, and do not suggest "
    "the name is misspelled or invalid. Return only JSON."
)

_PROMPT = """Classify each organisation into one size band.

Bands:
- global_major: a household-name multinational (Google, Samsung, Goldman Sachs)
- large: a large established firm, thousands of staff, well known in its own market
- mid: a mid-size company, hundreds of staff
- small: a small company
- startup: an early-stage or recently founded venture
- research: a research laboratory, institute, or university group
- unrecognised: you do not recognise this name

Organisations:
{names}

Return JSON: {{"companies": [{{"name": "<exactly as given>", "band": "<band>", \
"note": "<one short factual clause about what it is, or empty if unrecognised>"}}]}}"""


def _load_cache() -> Dict[str, Any]:
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")
    except Exception as exc:  # a cache miss is cheap; a crash here is not
        log.warning("could not write company profile cache: %s", exc)


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _fallback(name: str) -> Dict[str, Any]:
    """Used when the model is unavailable. States the coverage gap, blames nothing."""
    return {
        "name": name,
        "band": "unrecognised",
        "label": SIZE_BANDS["unrecognised"],
        "note": "",
        "source": "unavailable",
    }


def classify(names: List[str], api_key: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """
    Size band per organisation, keyed by the name as it was passed in.

    Never raises and never blocks: a model failure yields the neutral fallback, because
    an unavailable classifier is not a finding about the candidate's resume.
    """
    wanted = [n for n in dict.fromkeys(n.strip() for n in names) if n]
    if not wanted:
        return {}

    cache = _load_cache()
    out: Dict[str, Dict[str, Any]] = {}
    missing: List[str] = []
    for name in wanted:
        hit = cache.get(_key(name))
        if isinstance(hit, dict) and hit.get("band") in SIZE_BANDS:
            out[name] = {**hit, "name": name, "label": SIZE_BANDS[hit["band"]]}
        else:
            missing.append(name)

    if missing and llm.available():
        try:
            raw = llm.generate_json(
                prompt=_PROMPT.format(names="\n".join(f"- {n}" for n in missing)),
                system_instruction=_SYSTEM,
                api_key=api_key,
                stage="company_profile",
                temperature=0.0,
            )
            by_key = {
                _key(str(e.get("name", ""))): e
                for e in (raw.get("companies") or [])
                if isinstance(e, dict)
            }
            for name in missing:
                entry = by_key.get(_key(name))
                band = str((entry or {}).get("band", "")).strip()
                if band not in SIZE_BANDS:
                    out[name] = _fallback(name)
                    continue
                note = str((entry or {}).get("note", "") or "").strip()[:140]
                record = {"band": band, "note": note, "source": "model"}
                cache[_key(name)] = record
                out[name] = {**record, "name": name, "label": SIZE_BANDS[band]}
            _save_cache(cache)
        except Exception as exc:
            log.warning("company classification unavailable: %s", exc)
            for name in missing:
                out.setdefault(name, _fallback(name))
    else:
        for name in missing:
            out.setdefault(name, _fallback(name))

    return out


def describe(profile: Dict[str, Any]) -> str:
    """One neutral sentence for a candidate-facing panel."""
    label = profile.get("label") or SIZE_BANDS["unrecognised"]
    note = (profile.get("note") or "").strip()
    if profile.get("band") == "unrecognised":
        return (
            "Not among the firms with a campus record here, and not one this system "
            "recognises independently. That says nothing about the role itself."
        )
    if not note:
        return f"{label}, outside the campus recruiter graph."
    # The model returns a clause ("a major food delivery service"), not a sentence, so it
    # is joined into one rather than punctuated as a second.
    return f"{label} — {note.rstrip('.')} — with no campus recruiting record here."
