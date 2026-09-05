"use client";

import { motion } from "framer-motion";

import type { Verdict } from "@/lib/types";
import { VERDICT_META, cn } from "@/lib/utils";

export function VerdictBadge({
  verdict,
  size = "md",
}: {
  verdict: Verdict;
  size?: "sm" | "md" | "lg";
}) {
  const m = VERDICT_META[verdict];
  const sizing =
    size === "lg"
      ? "text-base px-4 py-1.5"
      : size === "sm"
        ? "text-[11px] px-2 py-0.5"
        : "text-sm px-3 py-1";
  return (
    <motion.span
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ type: "spring", stiffness: 400, damping: 20 }}
      className={cn(
        "inline-flex items-center gap-2 rounded-full border font-semibold uppercase tracking-wide",
        m.className,
        sizing,
      )}
    >
      <span className={cn("h-2 w-2 rounded-full", m.dot)} />
      {m.label}
    </motion.span>
  );
}
