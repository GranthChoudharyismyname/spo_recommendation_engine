/**
 * PDF evidence viewer.
 *
 * Highlights are positioned from normalised (0..1) bounding boxes supplied by the
 * backend, so the overlay tracks the canvas at any zoom without recomputing anything.
 * The overlay never covers the text it marks: the fill is translucent and the page
 * stays readable underneath.
 *
 * When no ref could be resolved for a recommendation, the toolbar says so rather than
 * highlighting a nearby region that was never matched.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Download,
  FileWarning,
  Maximize2,
  Minus,
  Plus,
} from "lucide-react";
import type { EvidenceRef, Recommendation, Severity } from "../lib/types";
import { severityToken, truncate } from "../lib/format";
import { IconButton, Panel, Skeleton } from "./primitives";

import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

// Bundled worker — nothing is fetched from a CDN at runtime. pdfjs refuses to run when
// the worker and API versions differ, so package.json pins pdfjs-dist to exactly the
// version react-pdf depends on. Keep the two in step when upgrading either.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

const MIN_SCALE = 0.5;
const MAX_SCALE = 2.5;

export interface ViewerProps {
  fileUrl: string | null;
  fileName: string | null;
  focused: Recommendation | null;
  pinnedId: string | null;
  scale: number;
  fitWidth: boolean;
  page: number;
  onPageChange: (page: number) => void;
  onScaleChange: (scale: number) => void;
  onFitWidth: (on: boolean) => void;
}

export function ResumeEvidenceViewer(props: ViewerProps) {
  const { fileUrl, fileName, focused, pinnedId, scale, fitWidth, page } = props;
  const containerRef = useRef<HTMLDivElement>(null);
  const pageWrapRef = useRef<HTMLDivElement>(null);
  const [pageCount, setPageCount] = useState(0);
  const [containerWidth, setContainerWidth] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);

  useLayoutEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setContainerWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [fileUrl]);

  const refs = focused?.evidence_refs ?? [];

  /*
   * Moving the document is reserved for a deliberate choice.
   *
   * Hovering the list used to turn the page and scroll the PDF, so simply reading down
   * the recommendations dragged the page around under the cursor and the passage being
   * read slid away. Hover still highlights — the marks are drawn for whatever is on the
   * page already — but only pinning a recommendation navigates to it.
   */
  const leads = !!focused && focused.id === pinnedId;
  const targetPage = leads ? refs[0]?.page : undefined;

  const { onPageChange } = props;
  useEffect(() => {
    if (targetPage && targetPage !== page) onPageChange(targetPage);
  }, [targetPage, page, onPageChange]);

  const scrollToHighlight = useCallback(() => {
    const node = pageWrapRef.current?.querySelector<HTMLElement>("[data-evidence-primary]");
    node?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, []);

  useEffect(() => {
    if (leads && refs.length > 0) {
      const id = window.setTimeout(scrollToHighlight, 90);
      return () => window.clearTimeout(id);
    }
    return undefined;
  }, [leads, focused?.id, refs.length, scrollToHighlight]);

  const renderWidth = fitWidth
    ? Math.max(240, containerWidth - 32)
    : undefined;

  return (
    <Panel className="flex h-full flex-col overflow-hidden">
      <PdfToolbar
        fileName={fileName}
        page={page}
        pageCount={pageCount}
        scale={scale}
        fitWidth={fitWidth}
        fileUrl={fileUrl}
        onPageChange={props.onPageChange}
        onScaleChange={props.onScaleChange}
        onFitWidth={props.onFitWidth}
      />

      <EvidenceStatus focused={focused} pinned={focused?.id === pinnedId} />

      <div ref={containerRef} className="scroll-area flex-1 p-4">
        {!fileUrl ? (
          <ViewerEmpty />
        ) : loadError ? (
          <ViewerError message={loadError} />
        ) : (
          <Document
            file={fileUrl}
            onLoadSuccess={({ numPages }) => {
              setPageCount(numPages);
              setLoadError(null);
            }}
            onLoadError={(error) =>
              setLoadError(
                `The PDF could not be rendered: ${error.message}. The evaluation above is unaffected.`,
              )
            }
            loading={<ViewerSkeleton />}
            error={<ViewerError message="The PDF could not be rendered." />}
          >
            <div
              ref={pageWrapRef}
              className="relative mx-auto w-fit"
              style={{
                borderRadius: "var(--radius-md)",
                overflow: "hidden",
                boxShadow: "var(--shadow-raised)",
                background: "#fff",
              }}
            >
              <Page
                pageNumber={page}
                width={renderWidth}
                scale={fitWidth ? undefined : scale}
                renderAnnotationLayer={false}
                renderTextLayer
                loading={<ViewerSkeleton />}
              />
              <EvidenceOverlay
                refs={refs}
                page={page}
                severity={focused?.severity ?? "POLISH"}
                title={focused?.title ?? ""}
                pinned={focused?.id === pinnedId}
              />
            </div>
          </Document>
        )}
      </div>
    </Panel>
  );
}

/* ---------------------------------------------------------------- Overlay */

export function EvidenceOverlay({
  refs,
  page,
  severity,
  title,
  pinned,
}: {
  refs: EvidenceRef[];
  page: number;
  severity: Severity;
  title: string;
  pinned: boolean;
}) {
  const onPage = refs.filter((ref) => ref.page === page);
  if (onPage.length === 0) return null;
  const tone = severityToken(severity);

  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden>
      {onPage.map((ref, index) => (
        <div
          key={`${ref.page}-${ref.y}-${index}`}
          data-evidence-primary={index === 0 ? "" : undefined}
          className="absolute rounded-[3px]"
          style={{
            left: `${ref.x * 100}%`,
            top: `${ref.y * 100}%`,
            width: `${ref.width * 100}%`,
            height: `${ref.height * 100}%`,
            // Padding keeps the mark clear of the glyphs it sits behind.
            padding: "0 2px",
            margin: "-1px -2px",
            background: `color-mix(in srgb, ${tone} 22%, transparent)`,
            color: tone,
            boxShadow: `0 0 0 1.5px ${tone}`,
            animation: pinned
              ? "evidence-pulse 1.8s var(--ease-out) infinite"
              : `rise var(--motion-fast) var(--ease-out) both`,
            // Secondary matches dim so the primary one reads as the anchor.
            opacity: index === 0 ? 1 : 0.45,
          }}
        >
          {index === 0 && title ? (
            <span
              className="absolute left-0 -translate-y-full whitespace-nowrap rounded-[var(--radius-sm)] px-2 py-1"
              style={{
                bottom: "calc(100% + 5px)",
                font: "var(--type-label)",
                color: "#fff",
                background: tone,
                boxShadow: "var(--shadow-panel)",
              }}
            >
              {truncate(title, 46)}
            </span>
          ) : null}
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- Toolbar */

export function PdfToolbar({
  fileName,
  page,
  pageCount,
  scale,
  fitWidth,
  fileUrl,
  onPageChange,
  onScaleChange,
  onFitWidth,
}: {
  fileName: string | null;
  page: number;
  pageCount: number;
  scale: number;
  fitWidth: boolean;
  fileUrl: string | null;
  onPageChange: (page: number) => void;
  onScaleChange: (scale: number) => void;
  onFitWidth: (on: boolean) => void;
}) {
  return (
    <div
      className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5"
      style={{ borderColor: "var(--colour-hairline)" }}
    >
      <div className="min-w-0 flex-1">
        {fileName ? (
          <p className="truncate" style={{ font: "var(--type-title-sm)" }} title={fileName}>
            {fileName}
          </p>
        ) : (
          <p className="eyebrow">Resume evidence</p>
        )}
      </div>

      <div className="flex items-center gap-0.5">
        <IconButton
          label="Previous page"
          disabled={page <= 1}
          onClick={() => onPageChange(Math.max(1, page - 1))}
        >
          <ChevronLeft size={15} />
        </IconButton>
        <span
          className="data px-1"
          style={{ fontSize: 11, color: "var(--colour-ink-muted)", minWidth: "3.5rem", textAlign: "center" }}
        >
          {pageCount ? `${page} / ${pageCount}` : "—"}
        </span>
        <IconButton
          label="Next page"
          disabled={!pageCount || page >= pageCount}
          onClick={() => onPageChange(Math.min(pageCount, page + 1))}
        >
          <ChevronRight size={15} />
        </IconButton>
      </div>

      <span className="h-4 w-px" style={{ background: "var(--colour-hairline)" }} />

      <div className="flex items-center gap-0.5">
        <IconButton
          label="Zoom out"
          disabled={!fileUrl || scale <= MIN_SCALE}
          onClick={() => onScaleChange(Math.max(MIN_SCALE, +(scale - 0.25).toFixed(2)))}
        >
          <Minus size={15} />
        </IconButton>
        <IconButton
          label="Zoom in"
          disabled={!fileUrl || scale >= MAX_SCALE}
          onClick={() => onScaleChange(Math.min(MAX_SCALE, +(scale + 0.25).toFixed(2)))}
        >
          <Plus size={15} />
        </IconButton>
        <IconButton
          label="Fit width"
          active={fitWidth}
          disabled={!fileUrl}
          onClick={() => onFitWidth(!fitWidth)}
        >
          <Maximize2 size={14} />
        </IconButton>
        {fileUrl ? (
          <a
            href={fileUrl}
            download={fileName ?? "resume.pdf"}
            aria-label="Download the resume"
            title="Download the resume"
            className="grid h-8 w-8 place-items-center rounded-[var(--radius-sm)]"
            style={{ color: "var(--colour-ink-muted)" }}
          >
            <Download size={15} />
          </a>
        ) : null}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- States */

function EvidenceStatus({
  focused,
  pinned,
}: {
  focused: Recommendation | null;
  pinned: boolean;
}) {
  if (!focused) return null;
  const located = focused.evidence_refs.length > 0;
  const tone = located ? severityToken(focused.severity) : "var(--colour-ink-muted)";
  return (
    <div
      className="flex items-center gap-2 border-b px-4 py-2"
      style={{
        borderColor: "var(--colour-hairline)",
        background: located ? severityToken(focused.severity, true) : "var(--colour-glass-sunken)",
      }}
    >
      {located ? (
        <span
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ background: tone }}
          aria-hidden
        />
      ) : (
        <FileWarning size={13} className="shrink-0" style={{ color: tone }} />
      )}
      <p className="min-w-0 flex-1 truncate" style={{ font: "var(--type-label)", color: tone }}>
        {located
          ? `${pinned ? "Pinned" : "Showing"}: ${focused.title}`
          : "Evidence location unavailable for this finding"}
      </p>
    </div>
  );
}

function ViewerEmpty() {
  return (
    <div className="grid h-full min-h-[18rem] place-content-center px-6 text-center">
      <p style={{ font: "var(--type-title-sm)" }}>No resume loaded</p>
      <p
        className="mt-1 max-w-xs"
        style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}
      >
        Add a PDF and it will render here, with each recommendation's evidence marked on
        the page.
      </p>
    </div>
  );
}

function ViewerError({ message }: { message: string }) {
  return (
    <div className="grid h-full min-h-[18rem] place-content-center px-6 text-center">
      <AlertCircle size={20} className="mx-auto mb-2" style={{ color: "var(--colour-critical)" }} />
      <p style={{ font: "var(--type-title-sm)" }}>Preview unavailable</p>
      <p
        className="mt-1 max-w-xs"
        style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}
      >
        {message}
      </p>
    </div>
  );
}

function ViewerSkeleton() {
  return (
    <div className="mx-auto w-full max-w-md space-y-2.5 p-6">
      <Skeleton h={22} w="55%" />
      <Skeleton h={10} w="80%" />
      <div className="h-3" />
      {Array.from({ length: 12 }).map((_, i) => (
        <Skeleton key={i} h={9} w={`${72 + ((i * 13) % 26)}%`} />
      ))}
    </div>
  );
}
