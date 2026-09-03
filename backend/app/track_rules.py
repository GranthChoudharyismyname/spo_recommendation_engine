"""
Track-specific dilution rules, transcribed from the role knowledge bases
(knowledge-base/role-frameworks/*.txt).

Each entry is a pattern the corresponding knowledge base explicitly names as a red
flag, together with the advice that knowledge base gives. Nothing here is inferred:
`kb_section` records where in the source document the rule comes from, and it is
carried through to the API response so a reviewer can check it.

These drive recommendations only. They never touch a score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Pattern


@dataclass(frozen=True)
class DilutionRule:
    rule_id: str
    pattern: Pattern[str]
    title: str
    rationale: str
    action: str
    kb_section: str
    # Which resume areas the pattern is tested against.
    scan: str  # "bullets" | "skills" | "extra_curricular"
    pillar_hint: str = "PROJECT"


def _p(expr: str) -> Pattern[str]:
    return re.compile(expr, re.IGNORECASE)


# ---------------------------------------------------------------- SCOPE framework
# S-C-O-P-E, defined identically across the role knowledge bases (consult.txt §3).

SCOPE_DIMENSIONS = {
    "SCALE": "How big were the stakes — users, revenue, dataset size, traffic, team size",
    "CONTEXT": "Why it mattered — the real data, segment or operating constraint involved",
    "OWN": "What you specifically did — the lever, design decision or algorithm you chose",
    "PROOF": "Evidence it landed — shipped, adopted, merged, deployed, published, approved",
    "EDGE": "The measured outcome — a number attached to the result",
}

# What a bullet is *for*, which decides whether asking it for a number is fair.
#
# The IITK project tables label rows Objective / Approach / Result, but extraction
# flattens them into one list, so the distinction has to be recovered from the text.
# It matters because only two of the five SCOPE dimensions ask for a figure — SCALE
# ("how big were the stakes") and EDGE ("a number attached to the result") — and those
# belong to how the work was done and what it produced. An objective states intent, and
# a recognition is a matter of record: neither is improved by a metric, and demanding
# one produces advice the candidate cannot act on.
NUMERIC_SCOPE_DIMENSIONS = ("SCALE", "EDGE")

# A record of something conferred. Not a work claim, so no dimension is owed.
_RECOGNITION = _p(
    r"\b(?:pre[-\s]?placement\s+offer|ppo|award\w*|prize|medal|gold|silver|bronze"
    r"|scholarship|fellowship|shortlist\w*|selected\s+(?:for|as|among)|finalist|runner[-\s]?up"
    r"|patent\w*|accepted\s+at|published\s+(?:in|at)|commendation"
    r"|recogni[sz]\w*|conferred|honou?red)\b"
)

# Names a method, so it describes how the work was done.
_APPROACH = _p(
    r"\b(?:using|via|with|through|leveraging|based\s+on|by\s+\w+ing"
    r"|implement\w*|appli\w*|design\w*|train\w*|fine[-\s]?tun\w*|architect\w*|engineer\w*"
    r"|integrat\w*|migrat\w*|refactor\w*|optimi[sz]\w*)\b"
)

# States an outcome.
_RESULT = _p(
    r"\b(?:achiev\w*|improv\w*|reduc\w*|increas\w*|cut|boost\w*|sav\w*|grew|gain\w*"
    r"|deliver\w*|shipp\w*|deploy\w*|resulted\s+in|led\s+to|yield\w*|outperform\w*"
    r"|accuracy|precision|recall|f1|latency|throughput|speed[-\s]?up)\b"
)


# The row label as the resume printed it, mapped onto the kinds used here.
_PRINTED_LABEL = {
    "objective": "OBJECTIVE",
    "approach": "APPROACH",
    "result": "RESULT",
    "results": "RESULT",
    "outcome": "RESULT",
    "outcomes": "RESULT",
    "impact": "RESULT",
}


def kind_from_label(label: Optional[str]) -> Optional[str]:
    """
    The kind stated by the resume itself, when the extraction preserved it.

    Extraction now carries `description_roles` alongside each bullet, recording the row
    label the document printed. That is evidence rather than inference, so it wins over
    `line_kind` — a bullet the candidate filed under Approach is an approach line even
    if it happens to read like an outcome.
    """
    if not label:
        return None
    return _PRINTED_LABEL.get(str(label).strip().strip(":").lower())


def line_kind(text: str) -> str:
    """
    `RECOGNITION`, `RESULT`, `APPROACH` or `OBJECTIVE` for one bullet.

    Recognition is tested first because such a line rarely names a method or an outcome
    verb and would otherwise fall through to OBJECTIVE — harmless here, but the two are
    treated differently and the distinction is worth keeping honest.
    """
    t = text or ""
    if _RECOGNITION.search(t):
        return "RECOGNITION"
    if _RESULT.search(t):
        return "RESULT"
    if _APPROACH.search(t):
        return "APPROACH"
    return "OBJECTIVE"


def numeric_expected(kind: str) -> bool:
    """Only the doing and the outcome are asked to carry a figure."""
    return kind in ("APPROACH", "RESULT")


SCOPE_PATTERNS: Dict[str, Pattern[str]] = {
    "SCALE": _p(
        r"\b\d[\d,.]*\s*(?:\+|k\b|m\b|mn\b|bn\b|cr\b|lakh|crore|million|billion|thousand)"
        r"|\b(?:\d[\d,.]*)\s*(?:users?|customers?|students?|records?|rows?|samples?|images?|"
        r"documents?|transactions?|requests?|queries|events?|nodes?|servers?|stores?|clients?|"
        r"members?|volunteers?|participants?|teams?|sku|gb|tb|qps|rps|fps)"
        r"|[₹$€]\s*\d"
    ),
    "CONTEXT": _p(
        r"\b(?:across \w+|among \w+|spanning|within a|using (?:a |the )?dataset|on (?:a |the )?dataset|"
        r"based on \w+|under (?:a |the )?\w*constraint|in production|live traffic|real[- ]world|"
        r"cohort|benchmark(?:ing|ed)|survey(?:ed|ing)|A/B|ablation|"
        r"where \w+|amid|driven by|in collaboration with)\b"
    ),
    # A bullet shows ownership when it opens with a past-tense action verb. A closed
    # verb list under-matches badly on real resumes ("Simulated", "Integrated"), so the
    # rule is morphological, with the irregular verbs listed explicitly. Weak openers are
    # excluded separately by WEAK_OWNERSHIP_VERBS.
    "OWN": _p(
        r"^\s*(?:[A-Z][a-z]{2,}(?:ed|ted|led|ped|ged|red|sed|ved|zed|ised|ized)\b"
        r"|(?:Built|Led|Drove|Wrote|Ran|Made|Won|Grew|Oversaw|Undertook|Rebuilt|Set up|Took)\b)"
        r"|\b(?:architected|designed|engineered|implemented|derived|formulated|optimi[sz]ed|"
        r"refactored|automated|spearheaded|orchestrated|negotiated|recommended|devised|"
        r"parallel(?:i[sz]ed)?|vectori[sz]ed|instrumented|fine[- ]tuned)\b"
    ),
    "PROOF": _p(
        r"\b(?:deployed|shipped|adopted|merged|released|in production|productioni[sz]ed|"
        r"rolled out|approved|accepted|published|patent|awarded|selected|presented at|"
        r"open[- ]sourced|handed over|went live|integrated into)\b"
    ),
    "EDGE": _p(
        r"\d+(?:\.\d+)?\s*(?:%|percent|x\b|×|bps|ms\b|µs|us\b|ns\b|sec(?:onds?)?\b|min(?:utes?)?\b|"
        r"hours?|days?|gb/s|mb/s|qps|rps|fps)"
        r"|\b(?:reduc|increas|improv|cut|rais|boost|acceler|lower|sav)\w*\s+(?:\w+\s+){0,4}?\d"
        r"|\b(?:accuracy|precision|recall|f1|auc|rmse|mae|mape|r2|sharpe|cagr|drawdown|latency|"
        r"throughput|speedup|uplift|conversion|retention|churn)\b[^.]{0,30}?\d"
        r"|\d+(?:\.\d+)?\s*(?:→|->|to)\s*\d+(?:\.\d+)?"
    ),
}

# consult.txt §4: "Red-flag verbs that show zero ownership".
WEAK_OWNERSHIP_VERBS = _p(
    r"^\s*(?:worked on|was responsible for|responsible for|helped (?:with|in)|assisted (?:in|with)|"
    r"was part of|part of|involved in|participated in|contributed to the team)\b"
)


# ---------------------------------------------------------------- per-track dilution rules

_COMMON: List[DilutionRule] = []

TRACK_DILUTION_RULES: Dict[str, List[DilutionRule]] = {
    "ANALYST_AIML": [
        DilutionRule(
            rule_id="KB_ANALYST_TUTORIAL_DATASET",
            pattern=_p(r"\b(titanic|iris dataset|iris flower|boston housing|mnist|fashion[- ]mnist|cifar[- ]?10)\b"),
            title="Project rests on a classroom dataset",
            rationale=(
                "The analytics knowledge base treats Titanic, Iris, Boston Housing and plain MNIST as "
                "presence-only signals: they register that a project exists but cannot reach the higher tiers."
            ),
            action=(
                "Rerun the same method on a dataset you sourced or a real problem statement, and describe "
                "the messiness you had to handle."
            ),
            kb_section="knowledge-base/role-frameworks/analyst_aiml.txt §3.2 — Clichéd Tutorial Datasets",
            scan="bullets",
        ),
        DilutionRule(
            rule_id="KB_ANALYST_ALGORITHM_LIST",
            pattern=_p(
                r"(?:\b(?:svm|knn|k-nn|random forest|naive bayes|decision trees?|logistic regression|"
                r"linear regression|xgboost|gradient boosting)\b[,;/ ]+){3,}"
            ),
            title="Skills line reads as an algorithm shopping list",
            rationale=(
                "Listing many algorithms side by side is read as fluff rather than capability; the "
                "knowledge base asks for frameworks and libraries instead."
            ),
            action=(
                "Replace the algorithm list with the stack you actually work in — PyTorch, scikit-learn, "
                "Hugging Face, pandas — and let the projects show which methods you used."
            ),
            kb_section="knowledge-base/role-frameworks/analyst_aiml.txt §3.3 — Uncontextualized Algorithm Shopping Lists",
            scan="skills",
        ),
        DilutionRule(
            rule_id="KB_ANALYST_METRIC_WITHOUT_BASELINE",
            pattern=_p(
                r"\b(?:achieved|reached|obtained|got)\s+(?:an?\s+)?\d{2}(?:\.\d+)?\s*%\s*"
                r"(?:accuracy|precision|recall|f1|auc)?"
            ),
            title="Model metric is stated without a baseline",
            rationale=(
                "A headline accuracy with no dataset size, baseline, class balance or companion metric "
                "cannot be interpreted by a reviewer."
            ),
            action=(
                "State the metric alongside the baseline you beat and the dataset size, and add the "
                "companion metric you already computed (precision/recall or F1)."
            ),
            kb_section="knowledge-base/role-frameworks/analyst_aiml.txt §3.4 — Vague Metrics without Baselines",
            scan="bullets",
        ),
    ],
    "SDE": [
        DilutionRule(
            rule_id="KB_SDE_UI_CLONE",
            pattern=_p(
                r"\b(?:clone|replica)\b[^.]{0,40}\b(?:netflix|spotify|amazon|instagram|twitter|youtube|airbnb)\b"
                r"|\b(?:netflix|spotify|instagram|twitter|youtube|airbnb)\b[^.]{0,20}\b(?:clone|replica|landing page)\b"
                r"|\bstatic\s+(?:website|landing page|portfolio)\b"
            ),
            title="Tutorial-style clone project",
            rationale=(
                "The SDE knowledge base flags superficial frontend clones without real functionality as "
                "diluting: they occupy project space without demonstrating engineering."
            ),
            action=(
                "Replace it with a project that carries backend, database, auth or API logic — or extend "
                "this one until it does, and describe that layer instead."
            ),
            kb_section="knowledge-base/role-frameworks/sde.txt §3.1 — Static UI / Tutorial Clones",
            scan="bullets",
        ),
        DilutionRule(
            rule_id="KB_SDE_GENERIC_CERTIFICATE",
            pattern=_p(r"\b(?:coursera|udemy|great learning|simplilearn)\b|\bcertificate of completion\b"),
            title="Generic completion certificate is taking resume space",
            rationale=(
                "Basic MOOC completion certificates are listed as dilution in the SDE knowledge base; "
                "they compete for space with verifiable engineering work."
            ),
            action="Drop the certificate and use the line for a project, contribution or rated profile.",
            kb_section="knowledge-base/role-frameworks/sde.txt §3.3 — Unrelated Non-Technical Certificates",
            scan="extra_curricular",
        ),
    ],
    "QUANT": [
        DilutionRule(
            rule_id="KB_QUANT_WEB_CRUD",
            pattern=_p(
                r"\b(?:mern|mean stack|crud (?:app|application)|react (?:app|website)|"
                r"django (?:website|blog)|full[- ]stack (?:web|website)|e-?commerce (?:site|website))\b"
            ),
            title="Web/CRUD project signals a software profile, not a quant one",
            rationale=(
                "The quant knowledge base reads full-stack CRUD work as an SDE signal that displaces the "
                "mathematical and low-latency work quant desks screen for."
            ),
            action=(
                "Give the space to a C++/systems or mathematical project — a backtester, a pricing engine, "
                "a stochastic model, or a latency-sensitive data structure."
            ),
            kb_section="knowledge-base/role-frameworks/quant.txt §4.2 — Web Development & CRUD Apps",
            scan="bullets",
        ),
        DilutionRule(
            rule_id="KB_QUANT_SOFT_SKILL_FLUFF",
            pattern=_p(
                r"\b(?:quick learner|fast learner|hard[- ]?working|hardworking|team player|"
                r"go[- ]getter|self[- ]motivated|passionate about|detail[- ]oriented)\b"
            ),
            title="Unprovable soft-skill claim",
            rationale=(
                "Quant screening is described in the knowledge base as strictly proof-and-numbers; "
                "self-descriptive adjectives carry no signal and invite scepticism."
            ),
            action="Delete the phrase. The measured results already carry the claim.",
            kb_section="knowledge-base/role-frameworks/quant.txt §4.3 — Soft Skills & Fluff",
            scan="bullets",
        ),
    ],
    "CONSULT_PM": [
        DilutionRule(
            rule_id="KB_CONSULT_RAW_TOOL_JARGON",
            pattern=_p(
                r"\bused\b[^.]{0,30}\b(?:xgboost|bert|react hooks?|tensorflow|pytorch|scikit|"
                r"pandas|numpy|kubernetes|docker)\b"
            ),
            title="Technical tooling is stated without the business outcome",
            rationale=(
                "The consulting and PM knowledge base asks for every technical method to be translated "
                "into business or product impact; the tool name on its own is not evaluated."
            ),
            action=(
                "Rewrite the line around the decision the work enabled and the outcome it moved, keeping "
                "the method as a clause rather than the subject."
            ),
            kb_section="knowledge-base/role-frameworks/consult_pm.txt §4 — Speak Business & User Impact",
            scan="bullets",
        ),
    ],
    "CORE_TECHNOM": [
        DilutionRule(
            rule_id="KB_CORE_COURSEWORK_MISSING",
            pattern=_p(r"$never^"),  # handled structurally, not by pattern; see recommendations.py
            title="",
            rationale="",
            action="",
            kb_section="core.txt Pillar 4 — Relevant Coursework (Mandatory to Highlight)",
            scan="bullets",
        ),
    ],
}


def dilution_rules_for(track: str) -> List[DilutionRule]:
    rules = [r for r in TRACK_DILUTION_RULES.get(track, []) if r.title]
    return _COMMON + rules
