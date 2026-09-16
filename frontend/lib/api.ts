// Thin typed API client. One place owns the base URL, auth header and error
// normalization so components/hooks stay declarative.
import type {
  BatchStatus,
  FindingUpdate,
  ManagerFindingCreate,
  RecheckResult,
  Review,
  ReviewSummary,
  User,
  VersionItem,
} from "./types";

// Default matches the port the backend actually runs on, so a fresh clone works
// with no config. Override via frontend/.env.local if you move either service.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8001";

const TOKEN_KEY = "vqa_token";

export const tokenStore = {
  get: () =>
    typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

/** Turn a backend "/static/xyz.png" path into an absolute URL. */
export const imageUrl = (path: string) =>
  path.startsWith("http") ? path : `${API_BASE}${path}`;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(
  path: string,
  opts: RequestInit = {},
): Promise<T> {
  const token = tokenStore.get();
  const headers = new Headers(opts.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  // Only set JSON content-type when body is not FormData.
  if (opts.body && !(opts.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  // --- auth ---
  login: (email: string, password: string) =>
    request<{ access_token: string; user: User }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<User>("/auth/me"),

  // --- reviews ---
  listReviews: () => request<ReviewSummary[]>("/reviews"),
  getReview: (id: string) => request<Review>(`/reviews/${id}`),
  getVersions: (id: string) =>
    request<VersionItem[]>(`/reviews/${id}/versions`),
  deleteReview: (id: string) =>
    request<{ deleted: string }>(`/reviews/${id}`, { method: "DELETE" }),

  // --- upload + evaluate ---
  uploadGraphic: (form: FormData) =>
    request<Review>("/graphics", { method: "POST", body: form }),

  // --- HITL overrides ---
  updateFinding: (id: string, body: FindingUpdate) =>
    request<Review>(`/findings/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  addFinding: (reviewId: string, body: ManagerFindingCreate) =>
    request<Review>(`/reviews/${reviewId}/findings`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteFinding: (id: string) =>
    request<Review>(`/findings/${id}`, { method: "DELETE" }),

  // --- batch (Tier 3) ---
  createBatch: (form: FormData) =>
    request<BatchStatus>("/batch", { method: "POST", body: form }),
  getBatch: (id: string) => request<BatchStatus>(`/batch/${id}`),

  // --- re-check (Tier 3) ---
  recheck: (reviewId: string, form: FormData) =>
    request<RecheckResult>(`/reviews/${reviewId}/recheck`, {
      method: "POST",
      body: form,
    }),

  // --- meta ---
  cost: () =>
    request<{ total: { estimated_usd: number; gemini_calls: number } }>(
      "/meta/cost",
    ),
};
