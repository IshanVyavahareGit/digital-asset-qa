"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import { AlertTriangle, History, Trash2 } from "lucide-react";

import { VerdictBadge } from "./VerdictBadge";
import { imageUrl } from "@/lib/api";
import { useDeleteReview } from "@/lib/hooks";
import { prettyType } from "@/lib/utils";
import type { ReviewSummary } from "@/lib/types";

export function ReviewCard({
  review,
  canDelete,
}: {
  review: ReviewSummary;
  canDelete?: boolean;
}) {
  const del = useDeleteReview();
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={{ type: "spring", stiffness: 300, damping: 26 }}
      className="group relative overflow-hidden rounded-xl border border-border bg-surface/60"
    >
      <Link href={`/reviews/${review.id}`}>
        <div className="relative aspect-video overflow-hidden bg-bg">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imageUrl(review.image_url)}
            alt={review.filename}
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
          />
          <div className="absolute left-2 top-2">
            <VerdictBadge verdict={review.verdict} size="sm" />
          </div>
          {review.versions > 1 && (
            <span className="absolute right-2 top-2 flex items-center gap-1 rounded-full border border-accent/40 bg-black/60 px-2 py-0.5 text-[10px] font-semibold uppercase text-accent backdrop-blur">
              <History className="h-3 w-3" /> Revised · v{review.version}
            </span>
          )}
        </div>
        <div className="p-3">
          <div className="truncate text-sm font-medium">{review.filename}</div>
          <div className="mt-0.5 text-xs text-muted">
            {prettyType(review.graphic_type)} · {prettyType(review.platform)}
          </div>
          <div className="mt-2 flex items-center gap-3 text-xs">
            {review.critical_count > 0 && (
              <span className="flex items-center gap-1 text-critical">
                <AlertTriangle className="h-3 w-3" />
                {review.critical_count} critical
              </span>
            )}
            {review.warning_count > 0 && (
              <span className="text-warning">{review.warning_count} warning</span>
            )}
            {review.critical_count === 0 && review.warning_count === 0 && (
              <span className="text-success">Clean</span>
            )}
          </div>
        </div>
      </Link>

      {canDelete && (
        <button
          onClick={() => del.mutate(review.id)}
          className="absolute bottom-3 right-3 rounded-lg bg-bg/70 p-1.5 text-muted opacity-0 transition-opacity hover:text-critical group-hover:opacity-100"
          title="Delete review"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      )}
    </motion.div>
  );
}
