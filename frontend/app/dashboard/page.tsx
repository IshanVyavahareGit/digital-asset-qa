"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Layers } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { BatchUpload } from "@/components/BatchUpload";
import { ReviewCard } from "@/components/ReviewCard";
import { UploadDropzone } from "@/components/UploadDropzone";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAuth } from "@/lib/auth";
import { useReviews } from "@/lib/hooks";

export default function DashboardPage() {
  return (
    <AppShell>
      <Dashboard />
    </AppShell>
  );
}

function Dashboard() {
  const { user } = useAuth();
  const { data: reviews, isLoading } = useReviews();
  const isManager = user?.role === "manager";

  return (
    <div className="space-y-6">
      {isManager && (
        <div className="grid gap-4 lg:grid-cols-2">
          <UploadDropzone />
          <BatchUpload />
        </div>
      )}

      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <Layers className="h-5 w-5 text-primary" />
            Review triage
          </h2>
          {reviews && (
            <span className="text-xs text-muted">
              {reviews.length} graphic{reviews.length === 1 ? "" : "s"}
            </span>
          )}
        </div>

        {isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-56" />
            ))}
          </div>
        ) : !reviews?.length ? (
          <EmptyState isManager={isManager} />
        ) : (
          <motion.div layout className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <AnimatePresence>
              {reviews.map((r) => (
                <ReviewCard key={r.id} review={r} canDelete={isManager} />
              ))}
            </AnimatePresence>
          </motion.div>
        )}
      </div>
    </div>
  );
}

function EmptyState({ isManager }: { isManager: boolean }) {
  return (
    <div className="rounded-xl border border-dashed border-border bg-surface/40 p-10 text-center">
      <p className="text-sm text-muted">
        {isManager
          ? "No graphics reviewed yet. Upload one above to run the first QA pass."
          : "No reviewed graphics yet. Check back once a manager has run a review."}
      </p>
    </div>
  );
}
