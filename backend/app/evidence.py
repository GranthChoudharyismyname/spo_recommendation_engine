"""
Evidence locator: resolves a snippet of resume text to bounding boxes on the PDF page.

The frontend overlays highlights on a PDF.js canvas, so coordinates are returned
normalised to the 0..1 range of each page's rendered box. That keeps the overlay
correct at any zoom level and independent of the device pixel ratio.

Strategy, in order:
  1. Exact search for the full snippet (PyMuPDF `search_for`, which already handles
     line wrapping within a block).
  2. Search for the longest distinctive prefix, shortened word by word.
  3. Give up and return no refs. Callers must surface "evidence location
     unavailable" rather than highlighting an unrelated region.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF

MIN_SNIPPET_WORDS = 4
MAX_REFS_PER_SNIPPET = 4


@dataclass
class EvidenceRef:
    page: int          # 1-indexed, matching the PDF viewer's page numbering
    x: float           # normalised left edge, 0..1 of page width
    y: float           # normalised top edge, 0..1 of page height
    width: float       # normalised
    height: float      # normalised
    text: str
    match: str         # "exact" | "prefix" — how the location was resolved

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _normalise_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


class PdfEvidenceLocator:
    """Opens the PDF once and resolves many snippets against it."""

    def __init__(self, pdf_path: str):
        self._doc = fitz.open(pdf_path)
        self._page_boxes = [(p.rect.width, p.rect.height) for p in self._doc]
        self._headings: Optional[List[Dict[str, Any]]] = None

    @property
    def page_count(self) -> int:
        return len(self._page_boxes)

    def close(self) -> None:
        try:
            self._doc.close()
        except Exception:
            pass

    def __enter__(self) -> "PdfEvidenceLocator":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def headings(self) -> List[Dict[str, Any]]:
        """
        The section headings this document actually prints.

        Found by typography rather than from a list of expected names: a heading is
        short text set noticeably larger than the body. That way the locator follows
        whatever template the candidate used instead of assuming one.
        """
        if self._headings is not None:
            return self._headings

        spans: List[Dict[str, Any]] = []
        for index, page in enumerate(self._doc):
            try:
                data = page.get_text("dict")
            except Exception:
                continue
            for block in data.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    text = _normalise_whitespace(
                        "".join(sp.get("text", "") for sp in line.get("spans", []))
                    )
                    sizes = [sp.get("size", 0) for sp in line.get("spans", [])]
                    if not text or not sizes:
                        continue
                    spans.append({
                        "page": index + 1, "text": text,
                        "size": max(sizes), "bbox": line.get("bbox"),
                    })

        if not spans:
            self._headings = []
            return self._headings

        # Body size is whatever is most common; a heading stands clear of it.
        body = sorted(sp["size"] for sp in spans)[len(spans) // 2]
        self._headings = [
            sp for sp in spans
            if sp["size"] >= body * 1.12 and 0 < len(sp["text"].split()) <= 6
        ]
        return self._headings

    def locate_section(self, name: str) -> List[EvidenceRef]:
        """The heading for a named section, when this document has one."""
        wanted = _normalise_whitespace(name).lower()
        if not wanted:
            return []
        candidates = [wanted, *(_SECTION_ALIASES.get(wanted) or ())]

        best = None
        best_score = 0.0
        for heading in self.headings():
            actual = heading["text"].lower()
            for candidate in candidates:
                want = set(candidate.split())
                got = set(actual.split())
                if not want or not got:
                    continue
                # Overlap relative to the shorter side, so "Projects" matches
                # "Key Projects" without "Key" counting against it.
                score = len(want & got) / min(len(want), len(got))
                if score > best_score:
                    best, best_score = heading, score

        # Half the words in common is a match; less is a coincidence.
        if not best or best_score < 0.5:
            return []

        page_w, page_h = self._page_boxes[best["page"] - 1]
        x0, y0, x1, y1 = best["bbox"]
        return [EvidenceRef(
            page=best["page"],
            x=round(x0 / page_w, 5), y=round(y0 / page_h, 5),
            width=round((x1 - x0) / page_w, 5), height=round((y1 - y0) / page_h, 5),
            text=best["text"], match="section",
        )]

    def locate(self, snippet: str) -> List[EvidenceRef]:
        snippet = _normalise_whitespace(snippet)
        if len(snippet.split()) < MIN_SNIPPET_WORDS:
            return []

        refs = self._search(snippet, "exact")
        if refs:
            return refs

        # Progressively shorten from the right. LLM-extracted bullets are frequently
        # re-punctuated relative to the PDF, so the head of the string is the reliable part.
        words = snippet.split()
        for cut in range(len(words) - 1, MIN_SNIPPET_WORDS - 1, -2):
            refs = self._search(" ".join(words[:cut]), "prefix")
            if refs:
                return refs
        return []

    def _search(self, needle: str, match_kind: str) -> List[EvidenceRef]:
        found: List[EvidenceRef] = []
        for index, page in enumerate(self._doc):
            try:
                rects = page.search_for(needle, quads=False)
            except Exception:
                continue
            if not rects:
                continue
            page_w, page_h = self._page_boxes[index]
            if page_w <= 0 or page_h <= 0:
                continue
            for rect in rects[:MAX_REFS_PER_SNIPPET]:
                found.append(
                    EvidenceRef(
                        page=index + 1,
                        x=round(rect.x0 / page_w, 5),
                        y=round(rect.y0 / page_h, 5),
                        width=round((rect.x1 - rect.x0) / page_w, 5),
                        height=round((rect.y1 - rect.y0) / page_h, 5),
                        text=needle,
                        match=match_kind,
                    )
                )
            if found:
                # A resume bullet lives on exactly one page; stop at the first page that hits.
                break
        return found[:MAX_REFS_PER_SNIPPET]


# A finding names a section ("Academic Qualifications"); the resume prints a heading
# ("Academic Qualifications", or "Key Projects"). These bridge the gap where the two
# vocabularies differ. Matching is by token overlap, so only the differing words are
# listed and an exact name needs no entry.
_SECTION_ALIASES = {
    "projects": ("key projects", "projects", "academic projects", "selected projects"),
    "position of responsibility": (
        "positions of responsibility", "position of responsibility", "responsibility",
    ),
    "scholastic qualifications": ("scholastic achievements", "scholastic qualifications"),
    "work experience": ("work experience", "internships", "professional experience"),
    "academic qualifications": ("academic qualifications", "education"),
}


def locate_many(pdf_path: str, snippets: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Convenience wrapper: snippet -> list of serialised refs (empty list when unresolved)."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    with PdfEvidenceLocator(pdf_path) as locator:
        for snippet in snippets:
            key = _normalise_whitespace(snippet)
            if not key or key in out:
                continue
            out[key] = [r.to_dict() for r in locator.locate(key)]
    return out
