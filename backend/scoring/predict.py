"""
AestheticScorer — the visual half of the structure pipeline.

`resume_structure.py` has always imported this module:

    from predict import AestheticScorer
    HAS_AESTHETIC_SCORER = True

but the module did not exist, so `HAS_AESTHETIC_SCORER` was always False and the
geometric metrics — margins, font size, word count, family count, name ratio — were the
whole of the structural score. `pdf_to_pngs()` was written for this and never called.

This fills that hook. Nothing about the geometric scoring changes; the visual score is a
separate reading that `eval_all()` reports alongside it.

Two backends, selected automatically:

  SIGLIP   Embeds the rendered page and compares it against a reference set of accepted
           resumes for the target track, scoring by cosine similarity to that track's
           centroid. This is the intended design and needs two things the repository
           does not ship: `transformers` + `torch`, and a directory of reference resume
           images per track. Point REFERENCE_RESUMES_DIR at one to enable it.

  VLM      Sends the rendered page to Gemini and asks for a layout judgement against the
           SPO conventions. Available whenever a key is configured, needs no reference
           corpus, and is what runs today.

Both return the same shape, so the caller does not care which ran. When neither is
available `score()` returns None and the structural score stays purely geometric — the
behaviour before this module existed.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("resume_intelligence.aesthetic")

BACKEND_SIGLIP = "siglip"
BACKEND_VLM = "vlm"

DEFAULT_SIGLIP_MODEL = os.environ.get("SIGLIP_MODEL", "google/siglip-base-patch16-224")
REFERENCE_DIR_ENV = "REFERENCE_RESUMES_DIR"


@dataclass
class AestheticResult:
    score: int                  # 0-100, comparable with the geometric score
    backend: str
    reasoning: str
    detail: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------- SigLIP backend

def _siglip_available() -> bool:
    try:
        import torch  # noqa: F401
        from transformers import AutoModel, AutoProcessor  # noqa: F401
        return True
    except ImportError:
        return False


def reference_dir() -> Optional[Path]:
    raw = os.environ.get(REFERENCE_DIR_ENV)
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_dir() else None


def reference_images(track: str) -> List[Path]:
    """
    Accepted resumes for one track, as images.

    Expected layout:  $REFERENCE_RESUMES_DIR/<TRACK>/*.png
    The track subdirectory is required — comparing an SDE resume against the consulting
    reference set would score the wrong convention.
    """
    root = reference_dir()
    if root is None:
        return []
    track_dir = root / track
    if not track_dir.is_dir():
        return []
    return sorted(
        p for p in track_dir.iterdir()
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )


class _SigLIPScorer:
    """Cosine similarity between a rendered page and a track's reference centroid."""

    def __init__(self, model_name: str = DEFAULT_SIGLIP_MODEL):
        from transformers import AutoModel, AutoProcessor

        self._processor = AutoProcessor.from_pretrained(model_name)
        self._model = AutoModel.from_pretrained(model_name)
        self._model.eval()
        self._centroids: Dict[str, Any] = {}

    def _embed(self, paths: List[Path]):
        import torch
        from PIL import Image

        images = [Image.open(p).convert("RGB") for p in paths]
        inputs = self._processor(images=images, return_tensors="pt")
        with torch.no_grad():
            features = self._model.get_image_features(**inputs)
        return features / features.norm(dim=-1, keepdim=True)

    def _centroid(self, track: str):
        if track in self._centroids:
            return self._centroids[track]
        refs = reference_images(track)
        if not refs:
            self._centroids[track] = None
            return None
        embeddings = self._embed(refs)
        centroid = embeddings.mean(dim=0, keepdim=True)
        centroid = centroid / centroid.norm(dim=-1, keepdim=True)
        self._centroids[track] = (centroid, len(refs))
        return self._centroids[track]

    def score(self, image_paths: List[str], track: str) -> Optional[AestheticResult]:
        entry = self._centroid(track)
        if entry is None:
            return None
        centroid, n_refs = entry
        page = self._embed([Path(image_paths[0])])
        similarity = float((page @ centroid.T).squeeze())

        # SigLIP cosine similarity for same-domain document images clusters roughly in
        # 0.55-0.95. Mapping that band onto 0-100 keeps the reading comparable with the
        # geometric score rather than compressing everything into the top decile.
        lo, hi = 0.55, 0.95
        normalised = (similarity - lo) / (hi - lo)
        score = int(round(max(0.0, min(1.0, normalised)) * 100))

        return AestheticResult(
            score=score,
            backend=BACKEND_SIGLIP,
            reasoning=(
                f"Cosine similarity {similarity:.3f} to the centroid of {n_refs} accepted "
                f"{track} resumes."
            ),
            detail={"similarity": round(similarity, 4), "reference_count": n_refs,
                    "model": DEFAULT_SIGLIP_MODEL},
        )


# ---------------------------------------------------------------- VLM backend

_VLM_SYSTEM = (
    "You are assessing the VISUAL LAYOUT of an IIT Kanpur placement resume. You are "
    "looking at a rendered page image, not its text.\n\n"
    "Judge only what is visible as layout: use of whitespace, column and section "
    "alignment, consistency of spacing between sections, visual hierarchy between the "
    "name, section headings and body, density and crowding, table alignment, and whether "
    "the page reads cleanly at a glance.\n\n"
    "Do NOT judge the candidate, their achievements, their wording, or the substance of "
    "the content. A weak candidate can have an excellent layout and vice versa.\n\n"
    "Score 0-100 where 85+ is a clean, well-balanced single-column SPO-style resume, "
    "60-84 is serviceable with visible spacing or alignment problems, and below 60 is "
    "crowded, misaligned or hard to scan."
)


class _VLMScorer:
    """Gemini as a vision model. Uses the project's single LLM configuration."""

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self._api_key = api_key
        self._model_name = model_name

    def _resolve(self):
        try:
            import config as app_config
            return (self._api_key or app_config.GEMINI_API_KEY,
                    self._model_name or app_config.GEMINI_MODEL_NAME)
        except ImportError:
            return (self._api_key or os.environ.get("GEMINI_API_KEY"),
                    self._model_name or os.environ.get("GEMINI_MODEL_NAME", "gemini-3.6-flash"))

    def score(self, image_paths: List[str], track: str) -> Optional[AestheticResult]:
        key, model = self._resolve()
        if not key or not image_paths:
            return None

        from google import genai
        from google.genai import types

        data = Path(image_paths[0]).read_bytes()
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=data, mime_type="image/png"),
                f"Target track: {track}. Assess this page's visual layout and return JSON:\n"
                '{"score": <int 0-100>, "reasoning": "<one sentence naming what you saw>", '
                '"issues": ["<short visual issue>", ...]}',
            ],
            config={
                "system_instruction": _VLM_SYSTEM,
                "response_mime_type": "application/json",
                "temperature": 0.0,
            },
        )
        parsed = json.loads(response.text)
        raw = parsed.get("score")
        score = int(round(float(raw))) if isinstance(raw, (int, float, str)) and str(raw).strip() else 0
        return AestheticResult(
            score=max(0, min(100, score)),
            backend=BACKEND_VLM,
            reasoning=str(parsed.get("reasoning") or "").strip(),
            detail={"issues": parsed.get("issues") or [], "model": model,
                    "pages_assessed": 1},
        )


# ---------------------------------------------------------------- public interface

class AestheticScorer:
    """
    The interface `resume_structure` has always imported.

    `backend="auto"` prefers SigLIP when both the libraries and a track reference set are
    present, because comparing against accepted resumes for the same track is a stronger
    signal than a general judgement; otherwise it falls back to the VLM.
    """

    def __init__(
        self,
        backend: str = "auto",
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self.backend = backend
        self._api_key = api_key
        self._model_name = model_name
        self._siglip: Optional[_SigLIPScorer] = None

    def _try_siglip(self, image_paths: List[str], track: str) -> Optional[AestheticResult]:
        if not _siglip_available() or not reference_images(track):
            return None
        try:
            if self._siglip is None:
                self._siglip = _SigLIPScorer()
            return self._siglip.score(image_paths, track)
        except Exception as exc:
            logger.warning("SigLIP scoring failed (%s); falling back", exc)
            return None

    def _try_vlm(self, image_paths: List[str], track: str) -> Optional[AestheticResult]:
        try:
            return _VLMScorer(self._api_key, self._model_name).score(image_paths, track)
        except Exception as exc:
            logger.warning("VLM layout scoring unavailable (%s)", exc)
            return None

    def score(self, image_paths: List[str], track: str = "SDE") -> Optional[AestheticResult]:
        """A visual layout reading, or None when no backend can run."""
        if not image_paths:
            return None
        if self.backend in ("auto", BACKEND_SIGLIP):
            result = self._try_siglip(image_paths, track)
            if result is not None:
                return result
            if self.backend == BACKEND_SIGLIP:
                return None
        if self.backend in ("auto", BACKEND_VLM):
            return self._try_vlm(image_paths, track)
        return None

    @staticmethod
    def availability() -> Dict[str, Any]:
        """Reported by /api/health so it is visible which backend, if any, can run."""
        root = reference_dir()
        tracks_with_refs = {}
        if root is not None:
            for track_dir in sorted(p for p in root.iterdir() if p.is_dir()):
                tracks_with_refs[track_dir.name] = len(reference_images(track_dir.name))
        return {
            "siglip_libraries": _siglip_available(),
            "reference_dir": str(root) if root else None,
            "reference_counts": tracks_with_refs,
            "siglip_ready": bool(_siglip_available() and tracks_with_refs),
        }
