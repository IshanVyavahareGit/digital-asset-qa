"use client";

import { useRouter } from "next/navigation";
import { History } from "lucide-react";

import { useVersions } from "@/lib/hooks";
import { VERDICT_META, cn } from "@/lib/utils";

/**
 * Shows the full revision lineage (parent + revisions) inline on the review page,
 * so a graphic and its revisions live together instead of as separate dashboard
 * entries. Older versions are marked REVISED (superseded).
 */
export function VersionTimeline({ reviewId }: { reviewId: string }) {
  const router = useRouter();
  const { data: versions } = useVersions(reviewId);

  if (!versions || versions.length < 2) return null; // no revisions -> nothing to show

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-surface/60 px-3 py-2">
      <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
        <History className="h-3.5 w-3.5" /> Version history
      </span>
      <div className="flex flex-wrap items-center gap-1.5">
        {versions.map((v, i) => {
          const isCurrent = v.review_id === reviewId;
          const meta = VERDICT_META[v.verdict];
          return (
            <div key={v.review_id} className="flex items-center gap-1.5">
              {i > 0 && <span className="text-muted">→</span>}
              <button
                onClick={() => !isCurrent && router.push(`/reviews/${v.review_id}`)}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs transition-colors",
                  isCurrent
                    ? "border-primary/60 bg-primary/10 text-primary"
                    : "border-border bg-surface-2 text-[#C6D0E8] hover:border-primary/40",
                )}
              >
                <span className="font-semibold">v{v.version}</span>
                <span className={cn("h-1.5 w-1.5 rounded-full", meta.dot)} />
                <span className="uppercase tracking-wide text-[10px] opacity-80">
                  {v.is_latest ? "current" : "revised"}
                </span>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
