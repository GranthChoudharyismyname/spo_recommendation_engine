"""
Module A: Resume Parsing Agent
==============================
Extracts structured JSON conforming strictly to RESUME_SCHEMA from resume text.
Content is read with high-fidelity PyMuPDF block reconstruction, which preserves word
spacing and the multi-column labels of the SPO template.
"""

import os
import re
import html
import json
from typing import Dict, Any, Optional

import fitz  # PyMuPDF

try:
    from google import genai
    from google.genai import types
    HAS_NEW_GENAI = True
except ImportError:
    import google.generativeai as legacy_genai
    HAS_NEW_GENAI = False


# ============================================================
# RESUME JSON SCHEMA
# ============================================================

RESUME_SCHEMA = {
    "type": "object",
    "properties": {
        "Name": {"type": "string"},
        "Department": {"type": "string"},
        "Contact Information": {
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "linkedin": {"type": "string"},
                "github": {"type": "string"},
                "portfolio": {"type": "string"}
            },
            "required": ["email", "phone"]
        },
        "Academic Qualifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "degree": {"type": "string"},
                    "institution": {"type": "string"},
                    "year": {"type": "string"},
                    "grade": {"type": "string"}
                },
                "required": [
                    "degree",
                    "institution",
                    "year",
                    "grade"
                ]
            }
        },
        "Scholastic Qualifications": {
            "type": "array",
            "items": {"type": "string"}
        },
        "Work Experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "organization": {"type": "string"},
                    "role": {"type": "string"},
                    "duration": {"type": "string"},
                    "description": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "description_roles": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": [
                    "organization",
                    "role",
                    "duration",
                    "description",
                    "description_roles"
                ]
            }
        },
        "Projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "organization": {"type": "string"},
                    "duration": {"type": "string"},
                    "description": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "description_roles": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": [
                    "title",
                    "organization",
                    "duration",
                    "description",
                    "description_roles"
                ]
            }
        },
        "Research Experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "organization_or_professor": {"type": "string"},
                    "duration": {"type": "string"},
                    "description": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "description_roles": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": [
                    "title",
                    "organization_or_professor",
                    "duration",
                    "description",
                    "description_roles"
                ]
            }
        },
        "Major Competitions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "competition": {"type": "string"},
                    "organization": {"type": "string"},
                    "achievement": {"type": "string"},
                    "year": {"type": "string"},
                    "description": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "description_roles": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": [
                    "competition",
                    "organization",
                    "achievement",
                    "year",
                    "description",
                    "description_roles"
                ]
            }
        },
        "Position of Responsibility": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "position": {"type": "string"},
                    "organization": {"type": "string"},
                    "duration": {"type": "string"},
                    "description": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": [
                    "position",
                    "organization",
                    "duration",
                    "description"
                ]
            }
        },
        "Social Impact": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "organization": {"type": "string"},
                    "role": {"type": "string"},
                    "duration": {"type": "string"},
                    "description": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": [
                    "organization",
                    "role",
                    "duration",
                    "description"
                ]
            }
        },
        "Extra Curricular Activities": {
            "type": "array",
            "items": {"type": "string"}
        },
        "Technical Skills": {
            "type": "array",
            "items": {"type": "string"}
        },
        "Relevant Courses": {
            "type": "array",
            "items": {"type": "string"}
        }
    },
    "required": [
        "Name",
        "Department",
        "Contact Information",
        "Academic Qualifications",
        "Scholastic Qualifications",
        "Work Experience",
        "Research Experience",
        "Major Competitions",
        "Position of Responsibility",
        "Social Impact",
        "Projects",
        "Extra Curricular Activities",
        "Technical Skills",
        "Relevant Courses"
    ]
}


# ============================================================
# EXTRACT HIGH-FIDELITY MARKDOWN FROM PDF
# ============================================================

def extract_pdf_markdown(pdf_path: str) -> str:
    """
    Extracts high-fidelity text and structure from the PDF.

    Blocks are read and sorted rather than taking a flat text dump, which preserves word
    spacing and keeps the multi-column labels of the SPO template attached to their rows.
    """
    # Block extraction: preserves word spacing and block structure
    doc = fitz.open(pdf_path)
    all_text = []
    for page in doc:
        blocks = page.get_text("blocks")
        valid_blocks = [b for b in blocks if b[4].strip()]
        # Sort blocks vertically, then horizontally
        valid_blocks.sort(key=lambda b: (round(b[1], 1), round(b[0], 1)))
        page_text = "\n\n".join(b[4].strip() for b in valid_blocks)
        all_text.append(page_text)

    combined = "\n\n".join(all_text)
    return clean_resume_text(combined)


# ============================================================
# CLEAN PDF-EXTRACTED TEXT
# ============================================================

def clean_resume_text(text: str) -> str:
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\(cid:\d+\)', '', text)
    text = re.sub(r'[§]', '', text)
    text = re.sub(r'^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\|\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*\|\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*-{3,}\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'^\s*•\s*', '• ', text, flags=re.MULTILINE)
    text = re.sub(r'\[([^\]]+)\]\s*', r'\1 ', text)
    text = re.sub(r'^\s*[iI]\s*$', '', text, flags=re.MULTILINE)
    return text.strip()


# ============================================================
# MODULE A: MARKDOWN → STRUCTURED RESUME JSON
# ============================================================

def markdown_to_resume_json(markdown_text: str, api_key: Optional[str] = None, model_name: str = "gemini-3.6-flash") -> Dict[str, Any]:
    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY is required.")

    prompt = f"""
You are a resume structure extraction agent.

Your ONLY task is to convert the supplied Markdown resume into
the provided JSON schema.

You are NOT evaluating the candidate.
You are NOT scoring the candidate.
You are NOT improving the resume.
You are NOT inferring missing information.

========================
STRICT EXTRACTION RULES
========================

1. Extract ONLY information explicitly present in the source Markdown.

2. NEVER hallucinate or invent:
   - organizations
   - companies
   - positions
   - dates
   - grades
   - achievements
   - metrics
   - projects
   - qualifications
   - responsibilities

3. Preserve factual information as closely as possible.
4. Do not change numerical values.
5. Do not change dates.
6. Remove Markdown formatting artifacts.
7. If two pieces of text clearly represent the SAME resume entry, keep only ONE copy.
8. Do not merge DISTINCT experiences.
9. Preserve separate projects, competitions, research experiences, work experiences, etc.
10. If a schema category is absent, return [].
11. If a field is unavailable, return an empty string.
12. Do not infer information from context.
13. Do not use outside knowledge.
14. Do not summarize multiple bullets into one bullet.
15. Preserve the meaning and factual content of each bullet.
16. Use section headings to determine the appropriate schema category.
17. If PDF extraction is malformed, recover structure ONLY when the intended structure is unambiguous.
18. Do not create information merely because the schema contains a corresponding field.

19. `description_roles` records the row label the resume itself printed beside each
    bullet, in the same order and the same length as `description`. Many IITK entries
    lay projects and competitions out as a table with rows labelled Objective, Approach
    and Result. When such a label is present, copy it as exactly one of "Objective",
    "Approach" or "Result". When a bullet carries no label, use "". Never infer a label
    from the wording of the bullet — this field records what was printed, nothing more.
    If one label covers several consecutive bullets, repeat it for each of them.

========================
OUTPUT
========================

Return exactly ONE JSON object conforming to the schema.
No Markdown. No explanation. No commentary. No code fences.

========================
SCHEMA
========================

{json.dumps(RESUME_SCHEMA, indent=2)}

========================
SOURCE MARKDOWN
========================

<resume>
{markdown_text}
</resume>
"""

    # Routed through the shared transport so a "high demand" 503 steps to the next
    # model. The prompt and RESUME_SCHEMA below are unchanged — the extraction contract
    # the signal corpora depend on is exactly as it was.
    try:
        from llm import generate_text as _shared
    except ImportError:
        _shared = None

    if _shared is not None:
        return json.loads(_shared(
            prompt=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": RESUME_SCHEMA
            },
            api_key=key,
            stage="extraction",
        ))
    elif HAS_NEW_GENAI:
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": RESUME_SCHEMA
            }
        )
        return json.loads(response.text)
    else:
        legacy_genai.configure(api_key=key)
        model = legacy_genai.GenerativeModel(
            model_name=model_name,
            generation_config={
                "response_mime_type": "application/json"
            }
        )
        response = model.generate_content(prompt)
        return json.loads(response.text)
