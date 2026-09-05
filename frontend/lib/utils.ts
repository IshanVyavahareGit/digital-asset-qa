import type { CheckType, Severity, Verdict } from "./types";

export function cn(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

export const VERDICT_META: Record<
  Verdict,
  { label: string; className: string; dot: string }
> = {
  pass: {
    label: "Pass",
    className: "text-success border-success/40 bg-black/60 backdrop-blur-sm shadow-md",
    dot: "bg-success",
  },
  needs_changes: {
    label: "Needs Changes",
    className: "text-warning border-warning/40 bg-black/60 backdrop-blur-sm shadow-md",
    dot: "bg-warning",
  },
  fail: {
    label: "Fail",
    className: "text-critical border-critical/40 bg-black/60 backdrop-blur-sm shadow-md",
    dot: "bg-critical",
  },
};

export const SEVERITY_META: Record<
  Severity,
  { label: string; color: string; ring: string; text: string }
> = {
  critical: { label: "Critical", color: "#FF4D5E", ring: "ring-critical", text: "text-critical" },
  warning: { label: "Warning", color: "#FFB020", ring: "ring-warning", text: "text-warning" },
  info: { label: "Info", color: "#38BDF8", ring: "ring-info", text: "text-info" },
};

export const CHECK_LABEL: Record<CheckType, string> = {
  typo_roster: "Typo & Roster",
  matchup: "Matchup",
  sponsor_audit: "Sponsor Audit",
  safe_zone: "Safe Zone",
  design_theme: "Design & Theme",
};

export const GRAPHIC_TYPES = [
  { value: "match_announcement", label: "Match Announcement" },
  { value: "bracket", label: "Bracket" },
  { value: "roster_update", label: "Roster Update" },
] as const;

export const PLATFORMS = [
  { value: "instagram_story", label: "Instagram Story (1080×1920)" },
  { value: "youtube_thumbnail", label: "YouTube Thumbnail (1920×1080)" },
  { value: "x_post", label: "X / Community (1920×1080)" },
  { value: "instagram_post", label: "Instagram Post (1080×1080)" },
] as const;

export function prettyType(t: string) {
  return t
    .split("_")
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}
