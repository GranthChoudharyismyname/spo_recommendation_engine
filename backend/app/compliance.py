"""
SPO submission-compliance checks.

Source: "Students' Placement Office, IIT Kanpur — Resume Making Guidelines"
(knowledge-base/spo-resume-guidelines.pdf, 6 pages).

`resume_structure.py` already measures and scores five physical guidelines (margins,
content font size, font-family count, word count, name ratio). This module covers the
submission rules it does not: the ones that are pass/fail policy rather than a
gradient, and that therefore must not be folded into a 0-100 score.

Nothing here modifies the composite score. Findings are returned alongside it.

One deliberate note: the guidelines forbid a JEE/GATE rank on the submitted resume,
while `scorer_engine.extract_deterministic_signals` awards up to +3 academic points
for a JEE Advanced AIR. When both fire, the report says so explicitly rather than
silently preferring one.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF

import spo_config

SEVERITY_BLOCKING = "BLOCKING"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"

# Page 5 of the guidelines: the accepted section headings, normalised. Overlaid from
# config/spo-guidelines.json when present; the literals are the fallback.
APPROVED_HEADINGS = {
    "education", "educational details", "academic qualification", "academic qualifications",
    "academic details", "academic performance",
    "academic achievements", "curricular achievements", "scholastic achievements",
    "scholastic qualifications", "academic excellence",
    "co-curricular activities", "co-curricular achievements",
    "awards", "honors", "honours", "achievements", "rewards",
    "research paper", "paper publication", "term papers", "publications", "patents",
    "b tech project", "btech project", "m tech thesis",
    "projects", "key projects", "relevant projects", "live project experience",
    "key academic projects", "technical projects",
    "summer internship", "internships", "professional experience", "industry internships",
    "work experience", "industry experience", "entrepreneurship experience",
    "social entrepreneurship",
    "initiatives taken", "on-campus initiatives", "social initiatives", "sports initiatives",
    "organizational initiatives", "cultural initiatives", "creative initiatives",
    "strategic initiatives",
    "positions of responsibility", "position of responsibility", "leadership",
    "team building activities",
    "extra-curricular activities", "extra-curricular achievements",
    "extra curricular activities", "extra curricular achievements",
    "relevant courses", "important courses", "finance courses", "management courses",
    "operational courses", "professional courses", "programming courses",
    "technical skills", "relevant tools", "relevant skills",
    "interests and hobbies", "interests", "hobbies",
}

_configured_headings = set(spo_config.approved_headings())
if _configured_headings:
    APPROVED_HEADINGS = _configured_headings


def _rule_enabled(rule_id: str) -> bool:
    return spo_config.is_enabled(rule_id)


def _sev(rule_id: str, default: str) -> str:
    return spo_config.severity(rule_id, default)


def _guide(rule_id: str, default: str) -> str:
    return spo_config.guideline_text(rule_id, default)


def _msg(rule_id: str, default: str) -> str:
    return spo_config.message(rule_id, default)


_PHONE = re.compile(
    r"(?:\+91[\s-]?)?\b[6-9]\d{9}\b"
    r"|\+\d{1,3}[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{4}\b"
)
_JEE_GATE_RANK = re.compile(
    r"\b(?:JEE|GATE)\b[^.\n]{0,40}?\b(?:AIR|All\s*India\s*Rank|rank)\b[^.\n]{0,12}?\d"
    r"|\b(?:AIR|All\s*India\s*Rank)\b[^.\n]{0,12}?\d[^.\n]{0,40}?\b(?:JEE|GATE)\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b|\b\d{2}\s*[-–]\s*\d{2}\b|'\d{2}\b")
_CPI = re.compile(r"\b(?:CPI|CGPA)\b", re.IGNORECASE)
_SELF_PROJECT = re.compile(r"\bself[\s-]?project", re.IGNORECASE)
_ONGOING = re.compile(r"\bongoing\b|\bpresent\b|\bcurrent(?:ly)?\b", re.IGNORECASE)


def _finding(
    check: str,
    severity: str,
    message: str,
    guideline: str,
    *,
    evidence: Optional[str] = None,
    section: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "check": check,
        "severity": severity,
        "message": message,
        "guideline": guideline,
        "evidence": evidence,
        "section": section,
    }


def _colour_threshold() -> int:
    """0-255 per channel. Anti-aliased near-black passes below this."""
    return int(spo_config.rule("SPO_FONT_COLOUR").get("max_channel_value", 90))


def _non_black_text(pdf_path: str) -> List[str]:
    """Guidelines p.4: 'Font Color: Strictly Black'. Returns sample offending strings."""
    samples: List[str] = []
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return samples
    try:
        for page in doc:
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        colour = span.get("color", 0)
                        text = (span.get("text") or "").strip()
                        if not text:
                            continue
                        r, g, b = (colour >> 16) & 255, (colour >> 8) & 255, colour & 255
                        # Anti-aliased near-black and pure black both pass.
                        if max(r, g, b) > _colour_threshold() and text not in samples:
                            samples.append(text[:80])
                        if len(samples) >= 5:
                            return samples
    except Exception:
        pass
    finally:
        doc.close()
    return samples



# Which schooling stage a row of the education table refers to.
#
# Two ideas, in order of trust.
#
# First, read the level generically. Almost every way a resume writes these rows carries
# the number itself — "Class 12", "XII", "12th", "Twelfth", "+2" — so a numeral, roman
# and word-form matcher covers the long tail without anyone maintaining a list.
#
# Second, fall back to the school-leaving exams that name a level without stating one.
# That list is short and stable because these are the standard Indian board exams; it
# does not try to be exhaustive, and it does not need to be, because of the rule below.
#
# The balance that matters is in `_level_of` returning None. An unfamiliar row is
# reported as unknown rather than guessed at, and the caller then declines to claim
# anything is missing. Recognition is generous; accusation requires certainty.
_DEGREE_TERMS = re.compile(
    r"\b(?:b\.?\s?tech|m\.?\s?tech|b\.?\s?e|m\.?\s?e|b\.?\s?sc|m\.?\s?sc|b\.?\s?a|m\.?\s?a"
    r"|b\.?\s?com|m\.?\s?com|bba|mba|bachelor|master|ph\.?\s?d|doctorate|diploma"
    r"|dual\s+degree|integrated)\b",
    re.IGNORECASE,
)

_LEVEL_12 = re.compile(
    r"(?<!\d)12(?!\d)|\bxii(?:th)?\b|\btwelfth\b|\btwelve\b|\+\s?2\b|\bplus\s?two\b",
    re.IGNORECASE,
)
_LEVEL_10 = re.compile(
    r"(?<!\d)10(?!\d)|\bx(?:th)?\b|\btenth\b|\bten\b",
    re.IGNORECASE,
)

# Exams that imply a level without naming a number.
_EXAM_12 = re.compile(
    r"\b(?:isc|hsc|hssc|aissce|intermediate|puc|pre[-\s]?university"
    r"|(?:senior|higher)\s+secondary)\b",
    re.IGNORECASE,
)
_EXAM_10 = re.compile(
    r"\b(?:icse|ssc|aisse|sslc|hslc|matric\w*|secondary)\b",
    re.IGNORECASE,
)

# A score is any number: 96, 96%, 8.2/10, 9.1 CGPA.
_MARK = re.compile(r"\d")


def _level_of(qual: Dict[str, Any]) -> Optional[str]:
    """
    `"XII"`, `"X"`, `"DEGREE"`, or None when the row is not recognisable.

    None is a real answer, not a failure — see the rule that consumes it.
    """
    text = f"{qual.get('degree') or ''} {qual.get('institution') or ''}"
    # Degree first: an integrated or 10-semester programme should not read as Class X.
    if _DEGREE_TERMS.search(text):
        return "DEGREE"
    # Twelve before ten, because several spellings of it contain a Class X word.
    if _LEVEL_12.search(text) or _EXAM_12.search(text):
        return "XII"
    if _LEVEL_10.search(text) or _EXAM_10.search(text):
        return "X"
    return None


def evaluate_compliance(
    pdf_path: str,
    raw_text: str,
    resume_json: Dict[str, Any],
    layout_metrics: Dict[str, Any],
    signals: Dict[str, Any],
    total_pages: int,
) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []

    # --- p.1: no mobile numbers on the submitted resume -------------------
    contact = resume_json.get("Contact Information") or {}
    phone_in_json = (contact.get("phone") or "").strip()
    phone_hit = _PHONE.search(raw_text or "")
    if _rule_enabled("SPO_NO_MOBILE_NUMBER") and (phone_in_json or phone_hit):
        findings.append(
            _finding(
                "SPO_NO_MOBILE_NUMBER",
                _sev("SPO_NO_MOBILE_NUMBER", SEVERITY_BLOCKING),
                "A mobile number appears on the resume. SPO does not permit phone numbers on "
                "master or single-page resumes submitted through the portal.",
                "Guidelines p.1 — 'No JEE/GATE rank or mobile numbers are allowed in the "
                "submitted Master and Single page resumes.'",
                evidence=phone_in_json or (phone_hit.group(0) if phone_hit else None),
                section="Contact Information",
            )
        )

    # --- p.1: no JEE/GATE rank -------------------------------------------
    rank_hit = _JEE_GATE_RANK.search(raw_text or "")
    if _rule_enabled("SPO_NO_JEE_GATE_RANK") and (rank_hit or signals.get("jee_adv_air")):
        credited = signals.get("jee_adv_air")
        message = (
            "A JEE/GATE rank appears on the resume. SPO does not permit it on submitted resumes."
        )
        if credited:
            message += (
                f" Note that the scoring engine separately credited AIR {credited} toward the "
                "academics pillar, so removing it for submission will lower the modelled academic "
                "score even though it is required for compliance."
            )
        findings.append(
            _finding(
                "SPO_NO_JEE_GATE_RANK",
                _sev("SPO_NO_JEE_GATE_RANK", SEVERITY_BLOCKING),
                message,
                "Guidelines p.1 — 'No JEE/GATE rank or mobile numbers are allowed in the "
                "submitted Master and Single page resumes.'",
                evidence=rank_hit.group(0) if rank_hit else f"AIR {credited}",
                section="Scholastic Qualifications",
            )
        )

    # --- p.4: page count --------------------------------------------------
    max_pages = spo_config.layout().get("max_pages_technical", 2)
    if _rule_enabled("SPO_PAGE_COUNT") and total_pages > max_pages:
        findings.append(
            _finding(
                "SPO_PAGE_COUNT",
                _sev("SPO_PAGE_COUNT", SEVERITY_BLOCKING),
                f"The document is {total_pages} pages. A technical CV must be at most {max_pages}; "
                "a non-technical CV must be one page.",
                "Guidelines p.4 — 'The Technical CV should either be 1 Page or 2 Pages. The "
                "Non-Technical CV should be 1 Page Only.'",
                section="Document layout",
            )
        )

    # --- p.4: font colour strictly black ----------------------------------
    coloured = _non_black_text(pdf_path)
    if _rule_enabled("SPO_FONT_COLOUR") and (coloured):
        findings.append(
            _finding(
                "SPO_FONT_COLOUR",
                _sev("SPO_FONT_COLOUR", SEVERITY_WARNING),
                "Non-black text was detected. SPO requires the entire CV to be black.",
                "Guidelines p.4 — 'Font Color: Strictly Black'.",
                evidence="; ".join(coloured[:3]),
                section="Document layout",
            )
        )

    # --- p.1 / p.2 / p.6: education section content -----------------------
    quals = resume_json.get("Academic Qualifications") or []
    grades = " ".join((q.get("grade") or "") for q in quals)

    if _rule_enabled("SPO_CPI_MANDATORY") and signals.get("cpi_status") == "UNVERIFIED_MISSING" \
            and not _CPI.search(grades):
        findings.append(
            _finding(
                "SPO_CPI_MANDATORY",
                _sev("SPO_CPI_MANDATORY", SEVERITY_BLOCKING),
                "No Pingala CPI was found in the academic qualifications section. Stating it there "
                "is compulsory.",
                "Guidelines p.2 — 'It is compulsory to mention your Pingala CPI in the Academic "
                "Qualification section.'",
                section="Academic Qualifications",
            )
        )

    levels = [_level_of(q) for q in quals]
    xii_rows = [q for q, lv in zip(quals, levels) if lv == "XII"]
    x_rows = [q for q, lv in zip(quals, levels) if lv == "X"]
    has_xii, has_x = bool(xii_rows), bool(x_rows)

    # A row nobody could classify means the table cannot be judged complete or
    # incomplete. Telling a student their Class X is missing when it is printed in front
    # of them is a worse error than staying quiet about a genuinely missing row, so an
    # unreadable row buys silence rather than a guess.
    unreadable = sum(1 for lv in levels if lv is None)

    if _rule_enabled("SPO_EDUCATION_TABLE_ROWS") and quals and not unreadable \
            and not (has_xii and has_x):
        missing = ", ".join(
            label for label, present in (("Class XII", has_xii), ("Class X", has_x)) if not present
        )
        findings.append(
            _finding(
                "SPO_EDUCATION_TABLE_ROWS",
                _sev("SPO_EDUCATION_TABLE_ROWS", SEVERITY_WARNING),
                f"The education section does not appear to list {missing}. It must carry CPI, "
                "Class XII and Class X.",
                "Guidelines p.1 — 'This section should have your CPI, 12th, and 10th scores.'",
                section="Academic Qualifications",
            )
        )

    # The guideline asks for the *scores*, not merely the rows. A row that names the
    # exam but carries no mark satisfied the check above while still being incomplete.
    if _rule_enabled("SPO_EDUCATION_TABLE_ROWS"):
        unscored = [
            label
            for label, rows in (("Class XII", xii_rows), ("Class X", x_rows))
            if rows and not any(_MARK.search(r.get("grade") or "") for r in rows)
        ]
        if unscored:
            findings.append(
                _finding(
                    "SPO_EDUCATION_SCORES",
                    _sev("SPO_EDUCATION_SCORES", SEVERITY_WARNING),
                    f"{' and '.join(unscored)} appears in the education table without a score. "
                    "The percentage or CGPA has to be stated alongside the row.",
                    "Guidelines p.1 — 'This section should have your CPI, 12th, and 10th scores.'",
                    section="Academic Qualifications",
                )
            )

    if _rule_enabled("SPO_EDUCATION_CHRONOLOGY") and len(quals) >= 2:
        years = [_first_year(q.get("year") or "") for q in quals]
        known = [y for y in years if y]
        if len(known) >= 2 and known != sorted(known, reverse=True):
            findings.append(
                _finding(
                "SPO_EDUCATION_CHRONOLOGY",
                _sev("SPO_EDUCATION_CHRONOLOGY", SEVERITY_WARNING),
                    "The education table is not in reverse chronological order.",
                    "Guidelines p.6 — 'The content in the table should be in reverse "
                    "chronological order.'",
                    section="Academic Qualifications",
                )
            )

    # --- p.6: achievements must carry a year ------------------------------
    undated = [
        item
        for item in (resume_json.get("Scholastic Qualifications") or [])
        if isinstance(item, str) and len(item.split()) >= 4 and not _YEAR.search(item)
    ]
    if _rule_enabled("SPO_ACHIEVEMENT_YEAR") and (undated):
        findings.append(
            _finding(
                "SPO_ACHIEVEMENT_YEAR",
                _sev("SPO_ACHIEVEMENT_YEAR", SEVERITY_WARNING),
                f"{len(undated)} achievement line(s) do not state a year.",
                "Guidelines p.6 — \"Any 'Achievements' or 'Activities': Definitely mention the "
                "year of Activity or Achievement.\"",
                evidence=undated[0][:160],
                section="Scholastic Qualifications",
            )
        )

    # --- p.3: self projects must be labelled ------------------------------
    unlabelled_self = [
        p
        for p in (resume_json.get("Projects") or [])
        if not (p.get("organization") or "").strip()
        and not _SELF_PROJECT.search(" ".join([p.get("title") or "", p.get("organization") or ""]))
    ]
    if _rule_enabled("SPO_SELF_PROJECT_LABEL") and (unlabelled_self):
        findings.append(
            _finding(
                "SPO_SELF_PROJECT_LABEL",
                _sev("SPO_SELF_PROJECT_LABEL", SEVERITY_WARNING),
                f"{len(unlabelled_self)} project(s) list no guide, course or organisation. A project "
                "done individually must be stated as a 'Self Project'.",
                "Guidelines p.3 — 'Projects done at an individual level will have to be clearly "
                "stated as \"Self Projects\" in the resume if mentioned.'",
                evidence=(unlabelled_self[0].get("title") or None),
                section="Projects",
            )
        )

    # --- p.3: ongoing work must say so ------------------------------------
    ongoing_unmarked = [
        w
        for w in (resume_json.get("Work Experience") or [])
        if re.search(r"present|current", (w.get("duration") or ""), re.IGNORECASE)
        and not _ONGOING.search(" ".join(w.get("description") or []))
    ]
    if _rule_enabled("SPO_ONGOING_LABEL") and (ongoing_unmarked):
        findings.append(
            _finding(
                "SPO_ONGOING_LABEL",
                _sev("SPO_ONGOING_LABEL", SEVERITY_INFO),
                "An in-progress engagement is listed. SPO asks that ongoing work be explicitly "
                "marked 'ongoing'.",
                "Guidelines p.3 — 'In case of an ongoing project/internship, you can mention that "
                "on your resume - explicitly mentioning that it is \"ongoing\".'",
                evidence=(ongoing_unmarked[0].get("organization") or None),
                section="Work Experience",
            )
        )

    severities = {f["severity"] for f in findings}
    if SEVERITY_BLOCKING in severities:
        status = "NON_COMPLIANT"
    elif SEVERITY_WARNING in severities:
        status = "REVIEW_REQUIRED"
    else:
        status = "COMPLIANT"

    return {
        "status": status,
        "findings": findings,
        "counts": {
            "blocking": sum(1 for f in findings if f["severity"] == SEVERITY_BLOCKING),
            "warning": sum(1 for f in findings if f["severity"] == SEVERITY_WARNING),
            "info": sum(1 for f in findings if f["severity"] == SEVERITY_INFO),
        },
        "source": "SPO IIT Kanpur — Resume Making Guidelines",
        # Which revision of the guidelines these findings were produced against.
        "cycle": spo_config.cycle(),
        "rules_disabled": sorted(
            r for r in (spo_config.load().get("compliance_rules") or {})
            if not r.startswith("_") and not spo_config.is_enabled(r)
        ),
    }


def _first_year(text: str) -> Optional[int]:
    match = re.search(r"(?:19|20)\d{2}", text or "")
    return int(match.group(0)) if match else None
