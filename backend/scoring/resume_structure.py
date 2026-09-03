"""
Module Structure: SPO Relaxed Resume Parser & Layout Evaluator
==============================================================
Evaluates physical SPO guidelines: margins, font size, word count, font family count, and name ratio.
"""

import re
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF

# Graceful import of AestheticScorer for local execution without predict.py
try:
    from predict import AestheticScorer
    HAS_AESTHETIC_SCORER = True
except ImportError:
    HAS_AESTHETIC_SCORER = False

try:
    from google import genai
    from google.genai import types
    HAS_NEW_GENAI = True
except ImportError:
    import google.generativeai as legacy_genai
    HAS_NEW_GENAI = False


# ============================================================
# SPO GUIDELINES CONFIGURATION
# ============================================================
GUIDELINES = {
    "min_margin_in": 0.5,
    "min_margin_pt": 36.0,
    "min_content_font_size_pt": 9.0,
    "min_reference_font_size_pt": 6.0,
    "min_words": 500,
    "max_words": 750,
    "name_min_ratio": 2.0,
    "max_font_families": 1,
}

# The SPO revises these every placement cycle, so they are overlaid from
# config/spo-guidelines.json when it is present. The literals above remain the fallback,
# so this module still works standalone with no config file and no behaviour change.
try:
    from spo_config import layout as _spo_layout
    GUIDELINES.update({k: v for k, v in _spo_layout().items() if k in GUIDELINES or True})
except Exception:
    pass

ICON_FONT_PATTERNS = (
    "fontawesome", "material icons", "wingdings", "webdings", "symbol", "zapfdingbats",
)


# ============================================================
# DATA STRUCTURES & UTILITIES
# ============================================================
@dataclass
class TextSpan:
    page: int
    text: str
    font: str
    font_family: str
    size: float
    flags: int
    color: int
    bbox: Tuple[float, float, float, float]


def normalize_font_name(font: str) -> str:
    font = font.strip()
    if "+" in font:
        prefix, remainder = font.split("+", 1)
        if len(prefix) == 6 and prefix.isupper():
            font = remainder
    font = re.sub(
        r"[-_](regular|bold|italic|oblique|medium|semibold|light|book|black|heavy|roman|condensed|demi)$",
        "", font, flags=re.IGNORECASE,
    )
    return font.strip()

def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def is_icon_font(font_family: str) -> bool:
    return any(pattern in font_family.lower() for pattern in ICON_FONT_PATTERNS)

def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", text, flags=re.UNICODE))

def compact_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: {"val": v.get("ACTUAL_VALUE"), "delta": v.get("DELTA")}
        for k, v in metrics.items()
    }


# ============================================================
# PYMUPDF SPO METRIC EVALUATION ENGINE
# ============================================================
# Typographic reference points, not a house style: single spacing sets a line at ~1.2x
# its font size. The band runs from slightly tight to halfway toward one-and-a-half,
# so an ordinarily-set resume is never penalised for it.
_WS_MIN = float(GUIDELINES.get("min_line_spacing", 1.0))
_WS_MAX = float(GUIDELINES.get("max_line_spacing", 1.45))


class RelaxedResumeParser:

    def __init__(self, pdf_path: str):
        self.pdf_path = str(pdf_path)
        self.doc = fitz.open(self.pdf_path)
        self.spans: List[TextSpan] = []
        self._metric_cache: Optional[Dict[str, Any]] = None
        self.pages: List[Dict[str, Any]] = []
        self._extract()

    def _extract(self):
        for page_index, page in enumerate(self.doc):
            rect = page.rect
            page_info = {"page": page_index + 1, "width": rect.width, "height": rect.height, "spans": []}
            blocks = page.get_text("dict")["blocks"]

            for block in blocks:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = normalize_text(span.get("text", ""))
                        if not text:
                            continue
                        ts = TextSpan(
                            page=page_index + 1,
                            text=text,
                            font=span.get("font", ""),
                            font_family=normalize_font_name(span.get("font", "")),
                            size=float(span.get("size", 0)),
                            flags=int(span.get("flags", 0)),
                            color=int(span.get("color", 0)),
                            bbox=tuple(span.get("bbox")),
                        )
                        self.spans.append(ts)
                        page_info["spans"].append(ts)
            self.pages.append(page_info)

    def full_text(self) -> str:
        chunks = []
        for page in self.pages:
            page_spans = sorted(page["spans"], key=lambda s: (s.bbox[1], s.bbox[0]))
            chunks.extend(s.text for s in page_spans)
        return "\n".join(chunks)

    def content_spans(self) -> List[TextSpan]:
        return [s for s in self.spans if not is_icon_font(s.font_family) and normalize_text(s.text)]

    def eval_word_count(self) -> Dict[str, Any]:
        count = word_count(self.full_text())
        target_max = GUIDELINES["max_words"]
        target_min = GUIDELINES["min_words"]

        if count > target_max:
            delta = count - target_max
            note = f"{delta} words above max SPO guideline"
        elif count < target_min:
            delta = count - target_min
            note = f"{abs(delta)} words below min SPO guideline"
        else:
            delta = 0
            note = "Within recommended SPO word count"

        return {
            "ACTUAL_VALUE": count,
            "GUIDELINE_VALUE": f"{target_min}-{target_max}",
            "DELTA": delta,
            "note": note
        }

    def eval_whitespace(self) -> Dict[str, Any]:
        """
        How much vertical whitespace the text carries, as effective line spacing.

        Measured as the median distance between consecutive baselines divided by the
        median font size — both read off this document, nothing fitted to a sample. The
        reference points are typographic constants rather than a house style: single
        spacing sets a line at about 1.2x its font size, one-and-a-half at 1.5x, double
        at 2.0x. A resume opened out past that is padding thin content to fill the page;
        one squeezed below single spacing is running lines into each other.

        The SPO guidelines set no spacing rule, so this is scored against typography
        rather than quoted from them, and the band is deliberately wide.
        """
        pitches: List[float] = []
        sizes: List[float] = []
        for page in self.pages:
            spans = [
                s for s in page["spans"]
                if not is_icon_font(s.font_family) and normalize_text(s.text)
            ]
            if not spans:
                continue
            # Spans sharing a top edge are one line; the gap to the next line is the pitch.
            tops = sorted({round(s.bbox[1], 1) for s in spans})
            # A gap wider than 3x the text size is a section break, not line spacing.
            limit = 3.0 * (statistics.median([s.size for s in spans]) or 10.0)
            pitches.extend(b - a for a, b in zip(tops, tops[1:]) if 0 < b - a <= limit)
            sizes.extend(s.size for s in spans)

        if len(pitches) < 5 or not sizes:
            return {
                "ACTUAL_VALUE": "Not Found",
                "GUIDELINE_VALUE": f"{_WS_MIN}-{_WS_MAX}x",
                "DELTA": 0,
                "note": "Too few lines to measure line spacing",
            }

        font = statistics.median(sizes)
        spacing = statistics.median(pitches) / font if font else 0.0
        if spacing > _WS_MAX:
            delta = round(spacing - _WS_MAX, 3)
            note = (f"Lines are set {spacing:.2f}x their font size; the extra vertical "
                    "space pads the page rather than filling it with content")
        elif spacing < _WS_MIN:
            delta = round(spacing - _WS_MIN, 3)
            note = (f"Lines are set {spacing:.2f}x their font size, tighter than single "
                    "spacing, so the text runs together")
        else:
            delta = 0
            note = f"Lines are set {spacing:.2f}x their font size, normal single spacing"
        return {
            "ACTUAL_VALUE": f"{spacing:.2f}x",
            "GUIDELINE_VALUE": f"{_WS_MIN}-{_WS_MAX}x",
            "DELTA": delta,
            "note": note,
        }

    def eval_margins(self) -> Dict[str, Any]:
        min_margins = []
        for page in self.pages:
            spans = [s for s in page["spans"] if not is_icon_font(s.font_family)]
            if not spans:
                continue
            left = min(s.bbox[0] for s in spans)
            right = page["width"] - max(s.bbox[2] for s in spans)
            top = min(s.bbox[1] for s in spans)
            bottom = page["height"] - max(s.bbox[3] for s in spans)
            min_margins.append(min(left, right, top, bottom) / 72.0)

        actual_min_in = min(min_margins) if min_margins else 0.0
        guideline_in = GUIDELINES["min_margin_in"]
        delta = round(actual_min_in - guideline_in, 3)

        return {
            "ACTUAL_VALUE": f"{round(actual_min_in, 3)} in",
            "GUIDELINE_VALUE": f"{guideline_in} in",
            "DELTA": delta,
            "note": "Negative delta indicates margins tighter than SPO guidelines" if delta < 0 else "Margins fulfill SPO guidelines"
        }

    def eval_font_families(self) -> Dict[str, Any]:
        fonts = Counter(s.font_family for s in self.content_spans())
        unique_count = len(fonts)
        guideline = GUIDELINES["max_font_families"]
        delta = unique_count - guideline

        return {
            "ACTUAL_VALUE": unique_count,
            "GUIDELINE_VALUE": guideline,
            "DELTA": delta,
            "detected_fonts": list(fonts.keys()),
            "note": "Multiple font families detected" if delta > 0 else "Font family usage complies with SPO guidelines"
        }

    def eval_font_size(self) -> Dict[str, Any]:
        sizes = [s.size for s in self.content_spans()]
        min_size = min(sizes) if sizes else 0.0
        guideline = GUIDELINES["min_content_font_size_pt"]
        delta = round(min_size - guideline, 2)

        return {
            "ACTUAL_VALUE": f"{round(min_size, 2)} pt",
            "GUIDELINE_VALUE": f"{guideline} pt",
            "DELTA": delta,
            "note": "Font size is smaller than SPO threshold" if delta < 0 else "Font size matches SPO baseline"
        }

    def eval_name_ratio(self) -> Dict[str, Any]:
        candidates = [s for s in self.spans if s.page == 1 and not is_icon_font(s.font_family) and s.bbox[1] < 120]
        if not candidates:
            return {
                "ACTUAL_VALUE": "Not Found",
                "GUIDELINE_VALUE": GUIDELINES["name_min_ratio"],
                "DELTA": -2.0,
                "note": "Candidate name header not detected on page 1"
            }

        name_span = max(candidates, key=lambda s: s.size)
        body_sizes = [s.size for s in self.content_spans() if s.size < name_span.size]
        body_size = statistics.median(body_sizes) if body_sizes else 10.0
        ratio = round(name_span.size / body_size, 2)
        guideline = GUIDELINES["name_min_ratio"]
        delta = round(ratio - guideline, 2)

        return {
            "ACTUAL_VALUE": ratio,
            "GUIDELINE_VALUE": guideline,
            "DELTA": delta,
            "name_text": name_span.text,
            "note": "Name header meets or exceeds 2.0x body ratio" if ratio >= guideline else "Name header is smaller than 2.0x body ratio"
        }

    # The weights the score has always used, plus whitespace. Kept as raw shares and
    # normalised below rather than hand-balanced to 100, so the six original components
    # keep their standing relative to each other now that a seventh has joined them.
    _RAW_WEIGHTS = {
        "page_count": 0.30,
        "word_count": 0.20,
        "margins": 0.15,
        "font_families": 0.15,
        "font_size": 0.10,
        "name_ratio": 0.10,
        "whitespace": 0.10,
    }

    # Named here so the breakdown reports the same numbers the score is computed from,
    # rather than a second copy that can drift. (Built with an explicit loop: a class-body
    # comprehension cannot see other class-level names.)
    COMPONENT_WEIGHTS = {}
    for _k, _v in _RAW_WEIGHTS.items():
        COMPONENT_WEIGHTS[_k] = _v / sum(_RAW_WEIGHTS.values())
    del _k, _v

    COMPONENT_LABELS = {
        "page_count": "Page count",
        "word_count": "Word count",
        "margins": "Margins",
        "font_families": "Font families",
        "font_size": "Body font size",
        "name_ratio": "Name header size",
        "whitespace": "Whitespace density",
    }

    def structural_components(self) -> Dict[str, Any]:
        """
        The parts the structural score is made of.

        The score was a single number with nothing behind it, so a resume could lose 23
        of 30 points to margins and fonts with no way to see where. This returns each
        component's 0-100 sub-score, its weight, and the points it cost — computed here,
        beside the formula, so nothing downstream re-derives it.
        """
        components = self._component_scores()
        if components is None:
            return {"total": 0, "components": [], "blank_document": True}

        rows = []
        for key, sub in components.items():
            weight = self.COMPONENT_WEIGHTS[key]
            earned = sub * weight
            rows.append({
                "key": key,
                "label": self.COMPONENT_LABELS[key],
                "sub_score": int(round(sub)),
                "weight": weight,
                "points_earned": round(earned, 1),
                "points_available": round(100 * weight, 1),
                "points_lost": round(100 * weight - earned, 1),
                "metric": (self._metric_cache or {}).get(key),
            })
        rows.sort(key=lambda r: -r["points_lost"])
        return {
            "total": round(sum(r["points_earned"] for r in rows)),
            "components": rows,
            "blank_document": False,
        }

    def _component_scores(self) -> Optional[Dict[str, float]]:
        """Each component on its own 0-100 scale, or None for a blank document."""
        words = word_count(self.full_text())
        if words < 50 or not self.content_spans():
            return None

        total_pages = len(self.pages)
        page_score = 100 if total_pages == 1 else max(0, 100 - (total_pages - 1) * 60)

        wc = self.eval_word_count()
        wc_score = 100 if wc["DELTA"] == 0 else max(0, 100 - abs(wc["DELTA"]) // 5)

        mg = self.eval_margins()
        mg_score = 100 if mg["DELTA"] >= 0 else max(0, int(100 + mg["DELTA"] * 200))

        ff = self.eval_font_families()
        ff_score = 100 if ff["DELTA"] <= 0 else max(20, 100 - ff["DELTA"] * 10)

        fs = self.eval_font_size()
        fs_score = 100 if fs["DELTA"] >= 0 else max(0, int(100 + fs["DELTA"] * 20))

        # Both directions cost: a wasted page and a crammed one are each worse than one
        # that uses its space. The band is wide, so a normally-set resume is untouched.
        ws = self.eval_whitespace()
        ws_delta = ws["DELTA"]
        if not isinstance(ws_delta, (int, float)) or ws_delta == 0:
            ws_score = 100.0 if ws["ACTUAL_VALUE"] != "Not Found" else 60.0
        else:
            # Calibrated on the spacing steps themselves: one-and-a-half spacing lands
            # near 93, double near 29. Padding costs real points without wiping out a
            # component that is only worth 9% of the score.
            ws_score = max(0.0, 100 - abs(ws_delta) * 130)

        name = self.eval_name_ratio()
        actual_ratio = name.get("ACTUAL_VALUE")
        if actual_ratio == "Not Found" or not isinstance(actual_ratio, (int, float)):
            name_score = 40  # Penalty for missing/undetected name header
        elif actual_ratio >= 2.0:
            name_score = 100 # Full credit for prominent header >= 2.0x
        else:
            name_score = max(40, int(100 - (2.0 - actual_ratio) * 60))

        self._metric_cache = {
            "page_count": {"ACTUAL_VALUE": total_pages, "GUIDELINE_VALUE": 1,
                           "DELTA": total_pages - 1,
                           "note": "Single page" if total_pages == 1
                                   else f"{total_pages} pages"},
            "word_count": wc, "margins": mg, "font_families": ff,
            "font_size": fs, "name_ratio": name, "whitespace": ws,
        }
        return {
            "page_count": page_score, "word_count": wc_score, "margins": mg_score,
            "font_families": ff_score, "font_size": fs_score, "name_ratio": name_score,
            "whitespace": ws_score,
        }

    def calculate_structural_score(self) -> int:
        """Calculates a composite 0-100 score based on SPO metric deltas."""
        # Fail-closed check for blank, empty or malformed resumes
        components = self._component_scores()
        if components is None:
            return 0
        return round(sum(components[k] * w for k, w in self.COMPONENT_WEIGHTS.items()))

    def eval_visual(self, track: str = "SDE") -> Optional[Dict[str, Any]]:
        """
        Visual layout reading from the aesthetic scorer.

        Renders page one via `pdf_to_pngs` and scores it — against a reference set of
        accepted resumes for the track when SigLIP and that set are available, otherwise
        as a VLM judgement. Returns None when neither backend can run, which is the
        original behaviour.

        Geometry and appearance answer different questions: a resume can hold every SPO
        margin and still be crowded and hard to scan.
        """
        if not HAS_AESTHETIC_SCORER:
            return None
        tmp_dir = None
        try:
            import tempfile
            tmp_dir = tempfile.mkdtemp(prefix="resume-render-")
            pages = pdf_to_pngs(self.pdf_path, output_dir=tmp_dir, dpi=150)
            if not pages:
                return None
            result = AestheticScorer().score(pages, track)
            return result.to_dict() if result else None
        except Exception:
            # Visual scoring is supplementary; a failure must not take down the
            # geometric evaluation.
            return None
        finally:
            if tmp_dir:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def evidence_regions(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Where each layout finding is actually visible on the page.

        A layout problem has no sentence to search for, so it cannot be located the way
        a bullet is. It does have a place: the line sitting closest to the page edge,
        the spans set in the smallest size, the runs in a second font. Those are
        reported here, measured from the same spans the score was computed from, so a
        finding points at the thing that produced it rather than at a guessed position.

        Coordinates are normalised to each page's box, matching `evidence.EvidenceRef`.
        """
        regions: Dict[str, List[Dict[str, Any]]] = {}

        def add(key: str, page_no: int, bbox, label: str) -> None:
            page = self.pages[page_no - 1]
            w, h = page["width"], page["height"]
            if w <= 0 or h <= 0:
                return
            x0, y0, x1, y1 = bbox
            regions.setdefault(key, []).append({
                "page": page_no,
                "x": round(max(0.0, x0) / w, 5),
                "y": round(max(0.0, y0) / h, 5),
                "width": round(max(0.0, x1 - x0) / w, 5),
                "height": round(max(0.0, y1 - y0) / h, 5),
                "text": label,
                "match": "region",
            })

        content = self.content_spans()

        # --- margins: the line that comes closest to a page edge -------------
        tightest = None
        for index, page in enumerate(self.pages, start=1):
            spans = [s for s in page["spans"] if not is_icon_font(s.font_family)]
            if not spans:
                continue
            edges = [
                (min(s.bbox[0] for s in spans), "left"),
                (page["width"] - max(s.bbox[2] for s in spans), "right"),
                (min(s.bbox[1] for s in spans), "top"),
                (page["height"] - max(s.bbox[3] for s in spans), "bottom"),
            ]
            gap, edge = min(edges, key=lambda e: e[0])
            if tightest is None or gap < tightest[0]:
                tightest = (gap, index, edge, spans)
        if tightest:
            gap, page_no, edge, spans = tightest
            page = self.pages[page_no - 1]
            # The span that reaches furthest into the margin on that edge.
            pick = {
                "left": lambda: min(spans, key=lambda s: s.bbox[0]),
                "right": lambda: max(spans, key=lambda s: s.bbox[2]),
                "top": lambda: min(spans, key=lambda s: s.bbox[1]),
                "bottom": lambda: max(spans, key=lambda s: s.bbox[3]),
            }[edge]()
            add("margins", page_no, pick.bbox, f"{round(gap / 72.0, 3)} in from the {edge} edge")

        # --- font size: every span set at the smallest size ------------------
        if content:
            smallest = min(s.size for s in content)
            for span in [s for s in content if abs(s.size - smallest) < 0.01][:6]:
                add("font_size", span.page, span.bbox, f"{round(span.size, 2)} pt")

        # --- font families: the runs that are not in the dominant family -----
        if content:
            counts = Counter(s.font_family for s in content)
            dominant = counts.most_common(1)[0][0]
            for span in [s for s in content if s.font_family != dominant][:6]:
                add("font_families", span.page, span.bbox, span.font_family)

        # --- name header ------------------------------------------------------
        if content:
            biggest = max(content, key=lambda s: s.size)
            add("name_ratio", biggest.page, biggest.bbox, normalize_text(biggest.text)[:60])

        # --- word count and line spacing are properties of the whole block ----
        for index, page in enumerate(self.pages, start=1):
            spans = [s for s in page["spans"]
                     if not is_icon_font(s.font_family) and normalize_text(s.text)]
            if not spans:
                continue
            block = (min(s.bbox[0] for s in spans), min(s.bbox[1] for s in spans),
                     max(s.bbox[2] for s in spans), max(s.bbox[3] for s in spans))
            if index == 1:
                add("word_count", index, block, "the text block")
                add("whitespace", index, block, "the text block")
            if index > 1:
                # Page count is about the pages past the first, so that is what it marks.
                add("page_count", index, block, f"page {index}")

        return regions

    def eval_all(self, track: str = "SDE", include_visual: bool = True) -> Dict[str, Any]:
        metrics = {
            "word_count": self.eval_word_count(),
            "margins": self.eval_margins(),
            "font_families": self.eval_font_families(),
            "font_size": self.eval_font_size(),
            "name_ratio": self.eval_name_ratio(),
            "whitespace": self.eval_whitespace(),
        }
        geometric = self.calculate_structural_score()

        # `score` stays the geometric value it has always been, so every existing
        # consumer is unaffected. The visual reading is reported beside it and blended
        # into `composite_score` only when a backend actually ran.
        visual = self.eval_visual(track) if include_visual else None
        weight = float(GUIDELINES.get("visual_weight", 0.0) or 0.0)
        if visual and weight > 0:
            composite = round((1 - weight) * geometric + weight * visual["score"])
        else:
            composite = geometric

        return {
            "total_pages": len(self.pages),
            "score": geometric,
            "composite_score": composite,
            "visual": visual,
            "visual_weight": weight if visual else 0.0,
            "metrics": metrics,
            # Where the geometric score came from, component by component.
            "breakdown": self.structural_components(),
            # Where each finding is visible on the page, for the evidence overlay.
            "regions": self.evidence_regions(),
        }


# ============================================================
# RENDERING
# ============================================================
def pdf_to_pngs(pdf_path: str, output_dir: str = "rendered", dpi: int = 150) -> List[str]:
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    paths = []
    base_name = Path(pdf_path).stem
    for i, page in enumerate(doc):
        path = output_dir_path / f"{base_name}_page_{i+1}.png"
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        pix.save(path)
        paths.append(str(path))
    doc.close()
    return paths
