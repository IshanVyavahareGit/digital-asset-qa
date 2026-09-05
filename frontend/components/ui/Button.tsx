"use client";

import { motion } from "framer-motion";
import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";
import { Spinner } from "./Spinner";

type Variant = "primary" | "ghost" | "danger" | "subtle";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-primary text-bg font-semibold hover:shadow-glow hover:brightness-110",
  danger:
    "bg-critical/90 text-white font-semibold hover:bg-critical hover:shadow-glow-critical",
  ghost:
    "bg-transparent border border-border text-[#C6D0E8] hover:border-primary/60 hover:text-primary",
  subtle: "bg-surface-2 text-[#C6D0E8] hover:bg-border",
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
}

export function Button({
  variant = "primary",
  loading,
  className,
  children,
  disabled,
  ...props
}: Props) {
  return (
    <motion.button
      whileTap={{ scale: 0.97 }}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        className,
      )}
      disabled={disabled || loading}
      {...(props as any)}
    >
      {loading && <Spinner size={14} />}
      {children}
    </motion.button>
  );
}
