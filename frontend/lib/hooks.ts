"use client";

// Central data layer. Queries cache reviews; mutations write the server's returned
// Review straight back into the cache (instant UI) and invalidate the list so
// verdict/counts stay in sync everywhere.
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api } from "./api";
import type {
  FindingUpdate,
  ManagerFindingCreate,
  Review,
  ReviewSummary,
} from "./types";

export const keys = {
  reviews: ["reviews"] as const,
  review: (id: string) => ["review", id] as const,
};

export function useReviews() {
  return useQuery<ReviewSummary[]>({
    queryKey: keys.reviews,
    queryFn: api.listReviews,
  });
}

export function useReview(id: string) {
  return useQuery<Review>({
    queryKey: keys.review(id),
    queryFn: () => api.getReview(id),
  });
}

export function useVersions(id: string) {
  return useQuery({
    queryKey: ["versions", id],
    queryFn: () => api.getVersions(id),
  });
}

/** Shared success handler: refresh the cached review + the dashboard list. */
function useReviewSync() {
  const qc = useQueryClient();
  return (review: Review) => {
    qc.setQueryData(keys.review(review.id), review);
    qc.invalidateQueries({ queryKey: keys.reviews });
    qc.invalidateQueries({ queryKey: ["versions"] }); // verdicts in the timeline
  };
}

export function useUploadGraphic() {
  const sync = useReviewSync();
  return useMutation({
    mutationFn: (form: FormData) => api.uploadGraphic(form),
    onSuccess: sync,
  });
}

export function useUpdateFinding(reviewId: string) {
  const sync = useReviewSync();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: FindingUpdate }) =>
      api.updateFinding(id, body),
    onSuccess: sync,
  });
}

export function useAddFinding(reviewId: string) {
  const sync = useReviewSync();
  return useMutation({
    mutationFn: (body: ManagerFindingCreate) =>
      api.addFinding(reviewId, body),
    onSuccess: sync,
  });
}

export function useDeleteFinding() {
  const sync = useReviewSync();
  return useMutation({
    mutationFn: (id: string) => api.deleteFinding(id),
    onSuccess: sync,
  });
}

export function useDeleteReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteReview(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.reviews }),
  });
}

// --- batch (Tier 3) ---

export function useCreateBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (form: FormData) => api.createBatch(form),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.reviews }),
  });
}

export function useBatch(id: string) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: ["batch", id],
    queryFn: () => api.getBatch(id),
    // Poll while work is in flight; stop once done. Refresh the dashboard too.
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      if (s && s !== "done") return 1500;
      qc.invalidateQueries({ queryKey: keys.reviews });
      return false;
    },
  });
}

// --- re-check (Tier 3) ---

export function useRecheck(reviewId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (form: FormData) => api.recheck(reviewId, form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.reviews });
      qc.invalidateQueries({ queryKey: ["versions"] });
    },
  });
}
