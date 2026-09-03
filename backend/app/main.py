"""
FastAPI adapter over the IITK resume scoring pipeline.

The browser never talks to Python directly and never sees the Gemini key: the key is
read from the server environment in `config.py`, passed into the scoring engine
in-process, and never serialised into a response.

Endpoints
    GET  /api/health    service and capability status
    GET  /api/tracks    the five placement tracks with their weight vectors
    POST /api/evaluate  multipart upload -> normalised evaluation view model
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Dict, List

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
from pipeline import ENGINE_VERSION, EvaluationError, evaluate
from tracks import TRACK_CODES, track_payload

from scorer_engine import ROLE_WEIGHTS

logger = logging.getLogger("resume_intelligence")

PDF_MAGIC = b"%PDF-"

app = FastAPI(title="IITK Resume Intelligence API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _error(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, **extra}})


@app.get("/api/health")
def health() -> Dict[str, Any]:
    from kg_adapter import load_kg
    from role_frameworks import availability as framework_availability
    import spo_config

    kg = load_kg()
    frameworks = framework_availability()
    try:
        from predict import AestheticScorer
        visual = AestheticScorer.availability()
    except ImportError:
        visual = {"siglip_ready": False}
    return {
        "status": "ok",
        "engine_version": ENGINE_VERSION,
        "capabilities": {
            # Reports whether a key is configured. The key itself is never returned.
            "gemini_configured": config.gemini_available(),
            "knowledge_graph": kg is not None,
            "kg_schema_version": kg.schema_version if kg else None,
            "kg_company_count": len(kg.companies) if kg else 0,
            # Which role frameworks reached the evaluator's prompt this run.
            "role_frameworks": frameworks,
            "role_frameworks_loaded": sum(1 for v in frameworks.values() if v),
            "visual_layout_scoring": {
                **visual,
                # SigLIP needs a reference set of accepted resumes per track; without one
                # the VLM backend runs instead, which needs only a model key.
                "active_backend": (
                    "siglip" if visual.get("siglip_ready")
                    else ("vlm" if config.gemini_available() else None)
                ),
            },
        },
        "spo_guidelines": {
            "cycle": spo_config.cycle(),
            "source": spo_config.load().get("source"),
            "rules_disabled": sorted(
                r for r in (spo_config.load().get("compliance_rules") or {})
                if not r.startswith("_") and not spo_config.is_enabled(r)
            ),
        },
        "limits": {
            "max_upload_bytes": config.MAX_UPLOAD_BYTES,
            "accepted_mime_types": ["application/pdf"],
        },
        "model": config.GEMINI_MODEL_NAME,
        # What a call actually falls back to when the primary is shedding load.
        "model_fallbacks": config.GEMINI_FALLBACK_MODELS,
        # How many keys are configured — never the keys themselves. Quota is counted per
        # model per project, so this is the multiplier on the daily allowance.
        "api_keys_configured": len(config.GEMINI_API_KEYS),
    }


@app.get("/api/tracks")
def tracks() -> Dict[str, Any]:
    payload: List[Dict[str, Any]] = []
    for code in TRACK_CODES:
        entry = track_payload(code)
        weights = ROLE_WEIGHTS[code]
        entry["weights"] = [
            {"pillar": pillar, "weight": weight}
            for pillar, weight in sorted(weights.items(), key=lambda kv: -kv[1])
        ]
        payload.append(entry)
    return {"tracks": payload}


@app.post("/api/evaluate")
async def evaluate_resume(
    resume: UploadFile = File(...),
    track: str = Form(...),
) -> Any:
    if track not in TRACK_CODES:
        return _error(
            400, "INVALID_TRACK", f"Unknown track '{track}'.", allowed=TRACK_CODES
        )

    if not config.gemini_available():
        return _error(
            503,
            "SCORING_UNAVAILABLE",
            "The scoring service has no Gemini API key configured, so no evaluation can be "
            "produced. Results are never fabricated when the model is unavailable.",
        )

    payload = await resume.read()
    size = len(payload)

    if size == 0:
        return _error(400, "EMPTY_FILE", "The uploaded file is empty.")
    if size > config.MAX_UPLOAD_BYTES:
        return _error(
            413,
            "FILE_TOO_LARGE",
            f"The PDF is {size / 1048576:.1f} MB. The maximum is "
            f"{config.MAX_UPLOAD_BYTES / 1048576:.0f} MB.",
            max_upload_bytes=config.MAX_UPLOAD_BYTES,
        )
    if not payload.startswith(PDF_MAGIC):
        return _error(
            415,
            "NOT_A_PDF",
            "The uploaded file is not a PDF. Only PDF resumes can be evaluated.",
        )

    handle, tmp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(handle, "wb") as fp:
            fp.write(payload)
        result = evaluate(
            pdf_path=tmp_path,
            track=track,
            original_filename=resume.filename or "resume.pdf",
            file_size=size,
        )
        return result
    except EvaluationError as exc:
        logger.warning("evaluation failed at %s: %s", exc.stage, exc)
        return _error(502, exc.code, str(exc), stage=exc.stage)
    except Exception as exc:  # noqa: BLE001 - surfaced, never replaced with a fake score
        logger.exception("unexpected failure")
        return _error(
            500,
            "UNEXPECTED_ERROR",
            f"The evaluation failed unexpectedly: {exc}",
        )
    finally:
        # The upload exists only for the duration of the request.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
