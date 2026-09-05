"use client";

import { AlertOctagon, CheckCircle2, HelpCircle } from "lucide-react";

import type { CheckRun } from "@/lib/types";
import { CHECK_LABEL, cn } from "@/lib/utils";

const STATUS = {
  ok: { icon: CheckCircle2, color: "text-success", label: "validated" },
  low_confidence: { icon: HelpCircle, color: "text-warning", label: "low confidence" },
  failed: { icon: AlertOctagon, color: "text-critical", label: "could not evaluate" },
} as const;

export function CheckHealth({ runs }: { runs: CheckRun[] }) {
  if (!runs.length) return null;
  const anyFailed = runs.some((r) => r.status === "failed");

  return (
    <div className="rounded-xl border border-border bg-surface/60 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted">
          Check health
        </span>
      </div>
      <div className="space-y-1.5">
        {runs.map((r) => {
          const s = STATUS[r.status];
          const Icon = s.icon;
          return (
            <div key={r.check_type} className="flex items-center gap-2 text-xs">
              <Icon className={cn("h-3.5 w-3.5 shrink-0", s.color)} />
              <span className="w-28 shrink-0 font-medium">
                {CHECK_LABEL[r.check_type]}
              </span>
              <span className={cn("shrink-0", s.color)}>{s.label}</span>
              {/* min-w-0 lets truncate actually clip: without it this nowrap span
                  sets the column's min-content width and squeezes the image. */}
              <span className="min-w-0 truncate text-muted" title={r.detail}>
                {r.detail}
              </span>
              {r.duration_ms > 0 && (
                <span className="ml-auto shrink-0 font-mono text-[10px] text-muted">
                  {(r.duration_ms / 1000).toFixed(1)}s
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
