"use client";

import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { LogOut, ShieldCheck, Palette, Activity } from "lucide-react";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Spinner } from "./ui/Spinner";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  const { data: cost } = useQuery({
    queryKey: ["cost"],
    queryFn: api.cost,
    enabled: !!user,
    refetchInterval: 20_000,
  });

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Loading…" />
      </div>
    );
  }

  const RoleIcon = user.role === "manager" ? ShieldCheck : Palette;

  return (
    <div className="bg-grid min-h-screen">
      <header className="sticky top-0 z-40 border-b border-border bg-bg/70 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
          <Link href="/dashboard" className="flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary/15 text-primary">
              <Activity className="h-4 w-4" />
            </span>
            <div className="leading-tight">
              <div className="text-sm font-bold">Visual QA</div>
              <div className="text-[10px] uppercase tracking-widest text-muted">
                TEC Productions
              </div>
            </div>
          </Link>

          <div className="flex items-center gap-4">
            {cost && (
              <div className="hidden text-right sm:block">
                <div className="text-[10px] uppercase tracking-wide text-muted">
                  API cost
                </div>
                <div className="font-mono text-xs text-primary">
                  ${cost.total.estimated_usd.toFixed(4)}
                </div>
              </div>
            )}
            <div className="flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1.5">
              <RoleIcon className="h-4 w-4 text-primary" />
              <span className="text-xs font-medium capitalize">
                {user.role}
              </span>
            </div>
            <button
              onClick={logout}
              className="rounded-lg p-2 text-muted transition-colors hover:bg-surface hover:text-critical"
              title="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </header>

      <motion.main
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="mx-auto max-w-7xl px-4 py-6"
      >
        {children}
      </motion.main>
    </div>
  );
}
