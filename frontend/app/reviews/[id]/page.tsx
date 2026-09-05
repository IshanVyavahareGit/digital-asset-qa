"use client";

import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ArrowLeft, GitCompare, MapPin, Plus, Square, X } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { CheckHealth } from "@/components/CheckHealth";
import { FindingsPanel } from "@/components/FindingsPanel";
import { ImageOverlay } from "@/components/ImageOverlay";
import { VerdictBadge } from "@/components/VerdictBadge";
import { VersionTimeline } from "@/components/VersionTimeline";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { imageUrl } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  keys,
  useAddFinding,
  useDeleteFinding,
  useReview,
  useUpdateFinding,
} from "@/lib/hooks";
import { prettyType } from "@/lib/utils";
import type { BBox, Review, Severity } from "@/lib/types";

export default function ReviewPage() {
  return (
    <AppShell>
      <Workspace />
    </AppShell>
  );
}

function Workspace() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const { data: review, isLoading, isError } = useReview(id);

  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [addMode, setAddMode] = useState(false);
  const [draft, setDraft] = useState<{
    x: number;
    y: number;
    w: number;
    h: number;
    isPin: boolean;
  } | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const qc = useQueryClient();
  const update = useUpdateFinding(id);
  const del = useDeleteFinding();
  const add = useAddFinding(id);

  const canOverride = user?.role === "manager";

  if (isLoading) return <WorkspaceSkeleton />;
  if (isError || !review)
    return (
      <div className="rounded-xl border border-critical/30 bg-critical/5 p-8 text-center">
        <p className="text-sm text-critical">Review not found.</p>
        <Link href="/dashboard" className="mt-2 inline-block text-sm text-primary">
          ← Back to dashboard
        </Link>
      </div>
    );

  const overlayFindings = review.findings.filter(
    (f) => f.status !== "dismissed",
  );

  const handleUpdate = (fid: string, body: any) => {
    setBusyId(fid);
    update.mutate({ id: fid, body }, { onSettled: () => setBusyId(null) });
  };
  const handleDelete = (fid: string) => {
    setBusyId(fid);
    del.mutate(fid, { onSettled: () => setBusyId(null) });
  };
  // Move or resize (manager drag): optimistically keep the marker at its new
  // geometry so it doesn't flash back, then persist. The server confirms the coords.
  const handleGeometryChange = (fid: string, bbox: BBox) => {
    qc.setQueryData<Review>(keys.review(id), (old) =>
      old
        ? { ...old, findings: old.findings.map((f) => (f.id === fid ? { ...f, bbox } : f)) }
        : old,
    );
    update.mutate({ id: fid, body: { bbox } });
  };

  return (
    <div className="space-y-4">
      {/* header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link
            href="/dashboard"
            className="rounded-lg border border-border p-2 text-muted hover:text-primary"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <h1 className="text-lg font-semibold">{review.graphic.filename}</h1>
            <p className="text-xs text-muted">
              {prettyType(review.graphic.graphic_type)} ·{" "}
              {prettyType(review.graphic.platform)} · {review.graphic.canvas_w}×
              {review.graphic.canvas_h}
              {review.graphic.version > 1 && ` · v${review.graphic.version}`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href={`/reviews/${id}/recheck`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-[#C6D0E8] transition-colors hover:border-primary/60 hover:text-primary"
          >
            <GitCompare className="h-4 w-4" /> Submit revision
          </Link>
          <VerdictBadge verdict={review.verdict} size="lg" />
        </div>
      </div>

      <VersionTimeline reviewId={id} />

      {/* minmax(0,1fr): pins the side panel to its share so long unwrappable
          strings can't widen it and shrink the image column. */}
      <div className="grid gap-4 lg:grid-cols-[1.5fr_minmax(0,1fr)]">
        {/* image + overlay */}
        <div className="lg:sticky lg:top-20 lg:self-start">
          <ImageOverlay
            imageUrl={imageUrl(review.graphic.image_url)}
            findings={
              draft
                ? [
                    ...overlayFindings,
                    {
                      id: "__draft__",
                      bbox: { x: draft.x, y: draft.y, w: draft.w, h: draft.h },
                      is_pin: draft.isPin,
                      severity: "warning",
                      source: "manager",
                    } as any,
                  ]
                : overlayFindings
            }
            hoveredId={hoveredId}
            selectedId={draft ? "__draft__" : selectedId}
            onHover={setHoveredId}
            onSelect={setSelectedId}
            addMode={addMode}
            onPlaceRegion={(bbox, isPin) => {
              setDraft({ ...bbox, isPin });
              setAddMode(false);
            }}
            canEdit={!!canOverride}
            onGeometryChange={handleGeometryChange}
          />
          {/* <p className="mt-2 text-center text-xs text-muted">
            Boxes & pins are positioned as % of the canvas — they stay aligned at
            any size.
          </p> */}
        </div>

        {/* side panel */}
        <div className="space-y-4">
          <div className="rounded-xl border border-border bg-surface/60 p-4">
            <div className="mb-1 text-xs uppercase tracking-wide text-muted">
              Verdict reasoning
            </div>
            <p className="text-sm">{review.reasoning}</p>
          </div>

          <CheckHealth runs={review.check_runs} />

          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
              Findings ({review.findings.length})
            </h2>
            {canOverride && (
              <Button
                variant={addMode ? "danger" : "subtle"}
                className="px-2.5 py-1 text-xs"
                onClick={() => {
                  setAddMode((m) => !m);
                  setDraft(null);
                }}
              >
                {addMode ? (
                  <>
                    <X className="h-3.5 w-3.5" /> Cancel
                  </>
                ) : (
                  <>
                    <Plus className="h-3.5 w-3.5" /> Add Markers
                  </>
                )}
              </Button>
            )}
          </div>

          {addMode && (
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-xs text-primary"
            >
              <MapPin className="h-3.5 w-3.5" /> Click to drop a pin, or drag to
              draw a box.
            </motion.p>
          )}

          <AnimatePresence>
            {draft && (
              <DraftForm
                busy={add.isPending}
                onCancel={() => setDraft(null)}
                isPin={draft.isPin}
                onSave={(message, severity) =>
                  add.mutate(
                    {
                      message,
                      severity,
                      bbox: {
                        x: draft.x,
                        y: draft.y,
                        w: draft.w,
                        h: draft.h,
                      },
                      is_pin: draft.isPin,
                    },
                    { onSuccess: () => setDraft(null) },
                  )
                }
              />
            )}
          </AnimatePresence>

          <FindingsPanel
            findings={review.findings}
            hoveredId={hoveredId}
            selectedId={selectedId}
            onHover={setHoveredId}
            onSelect={setSelectedId}
            canOverride={!!canOverride}
            onUpdate={handleUpdate}
            onDelete={handleDelete}
            busyId={busyId}
          />
        </div>
      </div>
    </div>
  );
}

function DraftForm({
  onSave,
  onCancel,
  busy,
  isPin,
}: {
  onSave: (message: string, severity: Severity) => void;
  onCancel: () => void;
  busy: boolean;
  isPin: boolean;
}) {
  const [message, setMessage] = useState("");
  const [severity, setSeverity] = useState<Severity>("warning");
  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="rounded-xl border border-accent/40 bg-accent/5 p-3"
    >
      <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-accent">
        {isPin ? <MapPin className="h-3.5 w-3.5" /> : <Square className="h-3.5 w-3.5" />}
        New manager {isPin ? "pin" : "box"}
      </div>
      <textarea
        autoFocus
        rows={2}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        placeholder="Describe the issue…"
        className="w-full rounded-lg border border-border bg-surface-2 px-2 py-1.5 text-sm outline-none focus:border-accent/60"
      />
      <div className="mt-2 flex items-center gap-2">
        <select
          value={severity}
          onChange={(e) => setSeverity(e.target.value as Severity)}
          className="rounded-lg border border-border bg-surface-2 px-2 py-1 text-xs"
        >
          <option value="critical">Critical</option>
          <option value="warning">Warning</option>
          <option value="info">Info</option>
        </select>
        <Button
          className="px-2.5 py-1 text-xs"
          loading={busy}
          disabled={!message.trim()}
          onClick={() => onSave(message.trim(), severity)}
        >
          Add {isPin ? "pin" : "box"}
        </Button>
        <Button variant="ghost" className="px-2.5 py-1 text-xs" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </motion.div>
  );
}

function WorkspaceSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-64" />
      <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
        <Skeleton className="aspect-video w-full" />
        <div className="space-y-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-24" />
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      </div>
    </div>
  );
}
