"use client";

import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  CircleDot,
  PlusCircle,
  UploadCloud,
} from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { ImageOverlay } from "@/components/ImageOverlay";
import { VerdictBadge } from "@/components/VerdictBadge";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { ApiError, imageUrl } from "@/lib/api";
import { useRecheck, useReview } from "@/lib/hooks";
import { CHECK_LABEL, SEVERITY_META, cn } from "@/lib/utils";
import type { Finding, RecheckResult } from "@/lib/types";

export default function RecheckPage() {
  return (
    <AppShell>
      <Recheck />
    </AppShell>
  );
}

function Recheck() {
  const { id } = useParams<{ id: string }>();
  const { data: original, isLoading } = useReview(id);
  const recheck = useRecheck(id);
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [result, setResult] = useState<RecheckResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (isLoading || !original) return <Skeleton className="h-96 w-full" />;

  const choose = (f: File | null) => {
    if (!f) return;
    setFile(f);
    setPreview(URL.createObjectURL(f));
    setError(null);
  };

  const submit = async () => {
    if (!file) return;
    setError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      setResult(await recheck.mutateAsync(form));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Re-check failed");
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <Link
          href={`/reviews/${id}`}
          className="rounded-lg border border-border p-2 text-muted hover:text-primary"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div>
          <h1 className="text-lg font-semibold">Re-check</h1>
          <p className="text-xs text-muted">
            Comparing a revision against{" "}
            <span className="text-[#C6D0E8]">{original.graphic.filename}</span> (v
            {original.graphic.version})
          </p>
        </div>
      </div>

      <AnimatePresence mode="wait">
        {!result ? (
          <motion.div
            key="upload"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="grid gap-4 md:grid-cols-2"
          >
            <div
              onClick={() => inputRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                choose(e.dataTransfer.files?.[0] ?? null);
              }}
              className="flex min-h-[240px] cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-border p-4 text-center hover:border-primary/50"
            >
              <input
                ref={inputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => choose(e.target.files?.[0] ?? null)}
              />
              {preview ? (
                <img
                  src={preview}
                  alt="revision preview"
                  className="max-h-[240px] rounded-lg object-contain"
                />
              ) : (
                <>
                  <UploadCloud className="mb-2 h-8 w-8 text-primary" />
                  <p className="text-sm">Drop the revised graphic</p>
                  <p className="mt-1 text-xs text-muted">
                    Same type & platform as the original
                  </p>
                </>
              )}
            </div>

            <div className="flex flex-col justify-between rounded-xl border border-border bg-surface/60 p-4">
              <div>
                <div className="mb-1 text-xs uppercase tracking-wide text-muted">
                  Original verdict
                </div>
                <VerdictBadge verdict={original.verdict} />
                <p className="mt-3 text-sm text-muted">
                  We’ll re-run the checks on your revision and diff the findings
                  showing what’s been <span className="text-success">resolved</span>,
                  what’s <span className="text-warning">still present</span>, and
                  if any <span className="text-info">new issues</span> have emerged.
                </p>
              </div>
              <div>
                {error && <p className="mb-2 text-xs text-critical">{error}</p>}
                <Button
                  onClick={submit}
                  disabled={!file}
                  loading={recheck.isPending}
                  className="w-full"
                >
                  {recheck.isPending ? "Re-checking…" : "Run re-check"}
                </Button>
              </div>
            </div>
          </motion.div>
        ) : (
          <DiffResult key="result" result={result} />
        )}
      </AnimatePresence>
    </div>
  );
}

function DiffResult({ result }: { result: RecheckResult }) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const { review, resolved, persisting, new_findings } = result;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted">New version verdict:</span>
          <VerdictBadge verdict={review.verdict} />
          <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs text-primary">
            v{review.graphic.version}
          </span>
        </div>
        <Link href={`/reviews/${review.id}`}>
          <Button variant="subtle" className="text-xs">
            Open full review →
          </Button>
        </Link>
      </div>

      {/* summary chips */}
      <div className="flex flex-wrap gap-2">
        <Chip color="#22D39A" icon={CheckCircle2} label={`${resolved.length} resolved`} />
        <Chip color="#FFB020" icon={CircleDot} label={`${persisting.length} still present`} />
        <Chip color="#38BDF8" icon={PlusCircle} label={`${new_findings.length} new`} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.4fr_minmax(0,1fr)]">
        <div className="lg:sticky lg:top-20 lg:self-start">
          <ImageOverlay
            imageUrl={imageUrl(review.graphic.image_url)}
            findings={review.findings}
            hoveredId={hoveredId}
            selectedId={null}
            onHover={setHoveredId}
            onSelect={() => {}}
            addMode={false}
            onPlaceRegion={() => {}}
          />
          {/* <p className="mt-2 text-center text-xs text-muted">
            Revised graphic: remaining & new findings shown.
          </p> */}
        </div>

        <div className="space-y-4">
          <DiffGroup
            title="Resolved"
            color="#22D39A"
            findings={resolved}
            strike
            empty="Nothing resolved yet."
          />
          <DiffGroup
            title="Still present"
            color="#FFB020"
            findings={persisting}
            onHover={setHoveredId}
            empty="No findings persisted."
          />
          <DiffGroup
            title="New"
            color="#38BDF8"
            findings={new_findings}
            onHover={setHoveredId}
            empty="No new findings introduced."
          />
        </div>
      </div>
    </motion.div>
  );
}

function DiffGroup({
  title,
  color,
  findings,
  strike,
  empty,
  onHover,
}: {
  title: string;
  color: string;
  findings: Finding[];
  strike?: boolean;
  empty: string;
  onHover?: (id: string | null) => void;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-2">
        <span className="h-2 w-2 rounded-full" style={{ background: color }} />
        <span className="text-xs font-semibold uppercase tracking-wide" style={{ color }}>
          {title} ({findings.length})
        </span>
      </div>
      {findings.length === 0 ? (
        <p className="rounded-lg border border-border bg-surface/40 px-3 py-2 text-xs text-muted">
          {empty}
        </p>
      ) : (
        <div className="space-y-1.5">
          {findings.map((f) => (
            <div
              key={f.id}
              onMouseEnter={() => onHover?.(f.id)}
              onMouseLeave={() => onHover?.(null)}
              className="rounded-lg border border-border bg-surface/60 p-2.5"
              style={{ borderLeft: `3px solid ${SEVERITY_META[f.severity].color}` }}
            >
              <div className="mb-0.5 flex items-center gap-2">
                <span
                  className="rounded px-1.5 py-0.5 text-[10px] font-bold uppercase"
                  style={{
                    background: `${SEVERITY_META[f.severity].color}22`,
                    color: SEVERITY_META[f.severity].color,
                  }}
                >
                  {f.severity}
                </span>
                <span className="text-[11px] text-muted">
                  {CHECK_LABEL[f.check_type]}
                </span>
              </div>
              <p className={cn("text-sm", strike && "text-muted line-through")}>
                {f.message}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Chip({
  color,
  icon: Icon,
  label,
}: {
  color: string;
  icon: any;
  label: string;
}) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium"
      style={{ borderColor: `${color}55`, color, background: `${color}12` }}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </span>
  );
}
