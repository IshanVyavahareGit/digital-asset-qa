"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, CheckCircle2, Loader2 } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { ReviewCard } from "@/components/ReviewCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { useBatch } from "@/lib/hooks";

export default function BatchPage() {
  return (
    <AppShell>
      <Batch />
    </AppShell>
  );
}

function Batch() {
  const { id } = useParams<{ id: string }>();
  const { data: batch, isLoading } = useBatch(id);

  if (isLoading || !batch) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-3 w-full" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-56" />
          ))}
        </div>
      </div>
    );
  }

  const done = batch.status === "done";
  const pct = batch.total ? (batch.completed / batch.total) * 100 : 0;

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <Link
          href="/dashboard"
          className="rounded-lg border border-border p-2 text-muted hover:text-primary"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            Batch triage
            {done ? (
              <CheckCircle2 className="h-4 w-4 text-success" />
            ) : (
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
            )}
          </h1>
          <p className="text-xs capitalize text-muted">
            {batch.status} · {batch.completed}/{batch.total} processed
            {batch.failed > 0 && (
              <span className="text-critical"> · {batch.failed} failed</span>
            )}
          </p>
        </div>
      </div>

      {/* progress bar */}
      <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2">
        <motion.div
          className="h-full rounded-full bg-primary"
          animate={{ width: `${pct}%` }}
          transition={{ type: "spring", stiffness: 120, damping: 20 }}
        />
      </div>

      {/* verdict-sorted board (worst first, from the API) */}
      {batch.reviews.length ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {batch.reviews.map((r) => (
            <ReviewCard key={r.id} review={r} />
          ))}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-border bg-surface/40 p-10 text-center text-sm text-muted">
          Waiting for the first results…
        </div>
      )}
    </div>
  );
}
