"""
What a position of responsibility actually involved, read from its own bullets.

The Gymkhana hierarchy covers the titles the institute itself confers. Plenty of real
leadership sits outside it — a festival vertical, a hostel body, a student startup, a
chapter of a national society, anything at another institution. The scorer marks those
`por_tier = 8`, and the recommendation used to report that as a title-matching failure
and ask the candidate to rename their role, which is both useless and slightly insulting
when the role was real and simply is not a Gymkhana post.

So when the title says nothing, read the work instead. Recruiters assessing a PoR look
past the designation for three things, and each leaves a trace in the bullets:

  * span      — how many people, across how many teams
  * resources — how much money, how many vendors
  * scale     — how many attendees, and whether it ran safely

None of this changes a score. It changes what the candidate is told: which of the three
their bullets already evidence, and which are missing and worth adding.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_NUMBER = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*"
    r"([kmb]\b|lakh[s]?\b|crore[s]?\b|cr\b|l\b)?",
    re.IGNORECASE,
)

_MAGNITUDE = {
    "k": 1_000, "m": 1_000_000, "b": 1_000_000_000,
    "lakh": 100_000, "lakhs": 100_000, "l": 100_000,
    "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000,
}

# A year is not a headcount or a budget.
_YEAR = re.compile(r"^(?:19|20)\d{2}$")

DIMENSIONS = ("span", "resources", "scale")

DIMENSION_LABEL = {
    "span": "Team size managed",
    "resources": "Budget and vendors",
    "scale": "Turnout and logistics",
}

# What each dimension asks for, in the candidate's own terms.
DIMENSION_PROMPT = {
    "span": "how many people you led, and across how many teams or verticals",
    "resources": "the budget you controlled, and how many external vendors or sponsors you dealt with",
    "scale": "the turnout you handled, and how it ran — an incident-free record counts",
}

# Words that must sit near a number for it to count as that dimension. Proximity matters:
# "40 members" is a span, "40 designs" is not.
_CUES: Dict[str, tuple] = {
    "span": (
        "member", "members", "volunteer", "volunteers", "team", "teams", "vertical",
        "verticals", "people", "student", "students", "coordinator", "coordinators",
        "executive", "executives", "strong", "headcount", "reportee", "reportees",
        "wing", "wings", "subteam", "subteams",
    ),
    "resources": (
        "budget", "fund", "funds", "funding", "sponsor", "sponsors", "sponsorship",
        "vendor", "vendors", "revenue", "grant", "expenditure", "procurement",
        "contract", "contracts", "cost",
    ),
    "scale": (
        "footfall", "attendee", "attendees", "participant", "participants", "audience",
        "visitor", "visitors", "turnout", "registration", "registrations", "crowd",
        "guest", "guests", "delegate", "delegates", "entries",
    ),
}

# Currency implies a budget even with no cue word beside the figure.
_CURRENCY = re.compile(r"(?:₹|rs\.?|inr|usd|\$)\s*", re.IGNORECASE)

# Safety and crisis handling are qualitative; they carry no number at all.
_SAFETY = re.compile(
    r"\b(zero[- ]incident|no[- ]incident|incident[- ]free|zero[- ]accident|"
    r"safety record|without incident|casualt(?:y|ies)[- ]free|crisis|contingency|"
    r"evacuat\w*|emergenc\w*)\b",
    re.IGNORECASE,
)

_WINDOW = 34  # characters either side of a number in which a cue still counts


def _value(raw: str, suffix: Optional[str]) -> Optional[float]:
    try:
        n = float(raw.replace(",", ""))
    except ValueError:
        return None
    if suffix:
        n *= _MAGNITUDE.get(suffix.lower(), 1)
    return n


def _cue_near(text: str, start: int, end: int, cues: tuple) -> Optional[str]:
    window = text[max(0, start - _WINDOW):end + _WINDOW].lower()
    for cue in cues:
        if re.search(rf"\b{re.escape(cue)}\b", window):
            return cue
    return None


def extract(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Evidence for each dimension across every listed position.

    Returns the dimensions found, the dimensions missing, and the exact bullet each
    piece of evidence came from — so a recommendation can quote the candidate's own
    line rather than assert something about it.
    """
    found: Dict[str, List[Dict[str, Any]]] = {d: [] for d in DIMENSIONS}

    for entry in entries or []:
        bullets = entry.get("description")
        if isinstance(bullets, str):
            bullets = [bullets]
        for bullet in bullets or []:
            if not isinstance(bullet, str) or not bullet.strip():
                continue
            text = bullet.strip()

            for match in _NUMBER.finditer(text):
                raw, suffix = match.group(1), match.group(2)
                if _YEAR.match(raw.replace(",", "")) and not suffix:
                    continue
                value = _value(raw, suffix)
                if value is None:
                    continue

                money = bool(_CURRENCY.search(text[max(0, match.start() - 6):match.start()]))
                for dimension, cues in _CUES.items():
                    cue = _cue_near(text, match.start(), match.end(), cues)
                    if not cue and not (dimension == "resources" and money):
                        continue
                    found[dimension].append({
                        "value": value,
                        "text": match.group(0).strip(),
                        "cue": cue or "currency",
                        "evidence": text,
                    })
                    break

            if _SAFETY.search(text):
                found["scale"].append({
                    "value": None,
                    "text": "incident-free operation",
                    "cue": "safety",
                    "evidence": text,
                })

    present = [d for d in DIMENSIONS if found[d]]
    return {
        "dimensions": found,
        "present": present,
        "missing": [d for d in DIMENSIONS if not found[d]],
        "evidenced": len(present),
    }


def summarise(dimension: str, hits: List[Dict[str, Any]]) -> str:
    """One short clause naming the strongest hit for a dimension."""
    if not hits:
        return ""
    numeric = [h for h in hits if h.get("value") is not None]
    if not numeric:
        return hits[0]["text"]
    best = max(numeric, key=lambda h: h["value"])
    if dimension == "resources" and best["cue"] in ("vendor", "vendors", "sponsor", "sponsors"):
        return f"{best['text']} {best['cue']}"
    return f"{best['text']} {best['cue']}" if best["cue"] != "currency" else best["text"]
