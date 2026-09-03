"""
IIT Kanpur Positive Signal Semantic Similarity Engine (Rolewise Dictionaries)
=============================================================================
Loads rolewise aggregated signal dictionaries:
  - ANALYST_AIML : analyst_signal_dictionary.json (267 signals, 27 resumes)
  - SDE          : sde_signal_dictionary.json (234 signals, 18 resumes)
  - CORE_TECHNOM : core_signal_dictionary.json (113 signals, 22 resumes)
  - CONSULT_PM   : consulting_signal_dictionary.json (72 signals, 10 resumes)

Computes role-specific semantic similarity, positive anchor matching, and dimensional alignment.
"""

import os
import json
import re
from typing import Dict, Any

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ROLE_DICTIONARY_FILES = {
    "ANALYST_AIML": os.path.join(_BASE_DIR, "analyst_signal_dictionary.json"),
    "SDE": os.path.join(_BASE_DIR, "sde_signal_dictionary.json"),
    "CORE_TECHNOM": os.path.join(_BASE_DIR, "core_signal_dictionary.json"),
    "CONSULT_PM": os.path.join(_BASE_DIR, "consulting_signal_dictionary.json"),
    "QUANT": os.path.join(_BASE_DIR, "quant_signal_dictionary.json")
}

_ROLE_DICT_CACHE = {}

def load_role_signal_dictionary(track: str) -> Dict[str, Any]:
    if track in _ROLE_DICT_CACHE:
        return _ROLE_DICT_CACHE[track]
        
    dict_file = ROLE_DICTIONARY_FILES.get(track, ROLE_DICTIONARY_FILES["ANALYST_AIML"])
    if os.path.exists(dict_file):
        with open(dict_file, "r") as fp:
            data = json.load(fp)
            _ROLE_DICT_CACHE[track] = data
            return data
            
    return {"all_signals": [], "total_signals": 0, "positive_spikes_registry": []}

def match_candidate_against_signal_corpus(
    resume_json: Dict[str, Any],
    raw_text: str,
    track: str
) -> Dict[str, Any]:
    role_dict = load_role_signal_dictionary(track)
    corpus = role_dict.get("all_signals", [])
    spikes_registry = role_dict.get("positive_spikes_registry", [])
    
    # 1. Extract Candidate Raw Signal Text
    work_ex_items = resume_json.get("Work Experience", [])
    proj_items = resume_json.get("Projects", [])
    pors = resume_json.get("Position of Responsibility", [])
    
    work_text = " ".join([w.get("organization", "") + " " + w.get("role", "") + " " + " ".join(w.get("description", [])) for w in work_ex_items]).lower()
    proj_text = " ".join([p.get("title", "") + " " + " ".join(p.get("description", [])) for p in proj_items]).lower()
    por_text = " ".join([p.get("position", "") + " " + p.get("organization", "") for p in pors]).lower()
    
    # 2. Match Role-Specific Work Experience Anchors
    matched_work_anchors = []
    for s in corpus:
        sec = s.get("section", "").lower()
        if "work" in sec or "experience" in sec or "intern" in sec:
            label = s.get("raw_signal_label", "")
            ev = s.get("evidence", "")
            entities = s.get("entities", [])
            if any(e.lower() in work_text for e in entities if len(e) > 3):
                matched_work_anchors.append(s)
            elif any(k in work_text for k in ["quant", "options", "volatility", "garch", "p&l", "greek", "backtester", "gradient boosting", "shap", "optimization", "yield", "savings", "backend", "sdk", "api", "microservices", "operations", "plant", "refinery"] if k in ev.lower()):
                matched_work_anchors.append(s)

    # 3. Match Role-Specific Project & Depth Anchors
    matched_proj_anchors = []
    for s in corpus:
        sec = s.get("section", "").lower()
        if "project" in sec:
            ev = s.get("evidence", "")
            label = s.get("raw_signal_label", "")
            keywords = [
                "bayesian", "mpt", "lstm", "smote", "isolation forest", "startup policy",
                "worm-gear", "bridge", "robotics", "transformer", "bert", "diffusion",
                "deep learning", "ansys", "cfd", "cad", "fem", "solidworks", "react", "fastapi"
            ]
            if any(k in proj_text for k in keywords if k in ev.lower() or k in label.lower()):
                matched_proj_anchors.append(s)

    # 4. Match SCOPE & Impact Anchors
    matched_spikes = []
    for s in spikes_registry:
        label = s.get("raw_signal_label", "").lower()
        ev = s.get("evidence", "").lower()
        if any(w in work_text or w in proj_text or w in por_text for w in [label[:20], ev[:20]] if len(w) > 5):
            matched_spikes.append(s.get("raw_signal_label"))

    # Compute Pillar Semantic Scores (0-20)
    if len(matched_work_anchors) >= 2 or any(k in work_text for k in ["multyfi", "quadeye", "graviton", "tower", "alphagrep", "carlsen", "d.e. shaw", "worldquant", "squarepoint", "nk securities", "optiver", "imc", "jane street", "citadel", "sprinklr", "aditya birla", "abg", "mckinsey", "bcg", "bain", "google", "microsoft", "amazon", "slb", "tatasteel", "reliance"]):
        we_score = 17
        we_tier = "Very Good (Top Benchmark Alignment)"
    elif len(work_ex_items) >= 1:
        we_score = 14
        we_tier = "Good (Solid Work Ex)"
    else:
        we_score = 6
        we_tier = "Below Par (No Work Ex)"

    if len(matched_proj_anchors) >= 3:
        proj_score = 19
        proj_tier = "Outstanding (High Anchor Overlap)"
    elif len(matched_proj_anchors) >= 1 or len(proj_items) >= 2:
        proj_score = 16
        proj_tier = "Very Good (Strong Algorithmic Rigor)"
    elif len(proj_items) >= 1:
        proj_score = 13
        proj_tier = "Good (Baseline Project)"
    else:
        proj_score = 6
        proj_tier = "Below Par"

    metric_count = len(re.findall(r"(\d+(?:\.\d+)?%|\₹\d+[L|K|Cr]+|\$\d+|[0-9]+(?:\,[0-9]+)?\+?\s*(?:users|cycles|deliveries|hours|records|mentors|students))", raw_text, re.IGNORECASE))
    if metric_count >= 6:
        scope_score = 19
        scope_tier = "Outstanding (Dense SCOPE Proof)"
    elif metric_count >= 3:
        scope_score = 16
        scope_tier = "Very Good (Quantified Metrics)"
    else:
        scope_score = 10
        scope_tier = "Average"

    return {
        "role": track,
        "role_dictionary": os.path.basename(ROLE_DICTIONARY_FILES.get(track, "")),
        "total_role_signals": len(corpus),
        "total_role_spikes_in_corpus": len(spikes_registry),
        "matched_work_anchors_count": len(matched_work_anchors),
        "matched_proj_anchors_count": len(matched_proj_anchors),
        "matched_scope_metrics_count": metric_count,
        "semantic_scores": {
            "work_experience_score": we_score,
            "work_experience_tier": we_tier,
            "projects_score": proj_score,
            "projects_tier": proj_tier,
            "scope_score": scope_score,
            "scope_tier": scope_tier
        },
        "sample_matched_corpus_anchors": [s.get("raw_signal_label") for s in (matched_work_anchors[:2] + matched_proj_anchors[:2])]
    }
