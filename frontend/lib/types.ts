// Mirrors the backend Pydantic schemas (app/schemas.py). The frontend consumes
// this typed JSON directly — no regex parsing of free text.

export type Role = "designer" | "manager";
export type Severity = "info" | "warning" | "critical";
export type Verdict = "pass" | "needs_changes" | "fail";
export type CheckType =
  | "typo_roster"
  | "matchup"
  | "sponsor_audit"
  | "safe_zone"
  | "design_theme";
export type FindingSource = "ai" | "manager";
export type FindingStatus = "open" | "dismissed" | "edited";
export type CheckStatus = "ok" | "low_confidence" | "failed";
export type GraphicType = "match_announcement" | "bracket" | "roster_update";
export type Platform = "instagram_story" | "youtube_thumbnail" | "x_post" | "instagram_post";

export interface User {
  id: string;
  email: string;
  role: Role;
}

export interface BBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Finding {
  id: string;
  check_type: CheckType;
  severity: Severity;
  message: string;
  suggested_fix: string;
  bbox: BBox | null;
  is_pin: boolean;
  confidence: number | null;
  source: FindingSource;
  status: FindingStatus;
}

export interface CheckRun {
  check_type: CheckType;
  status: CheckStatus;
  detail: string;
  confidence: number | null;
  duration_ms: number;
}

export interface Graphic {
  id: string;
  filename: string;
  graphic_type: GraphicType;
  platform: Platform;
  canvas_w: number;
  canvas_h: number;
  version: number;
  version_group_id: string;
  image_url: string;
}

export interface Review {
  id: string;
  verdict: Verdict;
  reasoning: string;
  pipeline_status: string;
  graphic: Graphic;
  findings: Finding[];
  check_runs: CheckRun[];
  created_at: string;
}

export interface ReviewSummary {
  id: string;
  graphic_id: string;
  filename: string;
  graphic_type: GraphicType;
  platform: Platform;
  verdict: Verdict;
  image_url: string;
  critical_count: number;
  warning_count: number;
  version: number;
  versions: number;
  version_group_id: string;
}

export interface VersionItem {
  review_id: string;
  version: number;
  verdict: Verdict;
  is_latest: boolean;
  critical_count: number;
  warning_count: number;
  created_at: string;
}

export interface BatchStatus {
  id: string;
  status: "queued" | "processing" | "done";
  total: number;
  completed: number;
  failed: number;
  reviews: ReviewSummary[];
}

export interface RecheckResult {
  review: Review;
  previous_review_id: string;
  resolved: Finding[];
  persisting: Finding[];
  new_findings: Finding[];
}

export interface ManagerFindingCreate {
  message: string;
  severity: Severity;
  suggested_fix?: string;
  bbox: BBox | null;
  is_pin: boolean;
  check_type?: CheckType;
}

export interface FindingUpdate {
  message?: string;
  severity?: Severity;
  suggested_fix?: string;
  status?: FindingStatus;
  bbox?: BBox;
}
