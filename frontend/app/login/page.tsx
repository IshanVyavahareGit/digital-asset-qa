"use client";

import { motion } from "framer-motion";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ShieldCheck, Palette } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";

const DEMO = [
  { role: "Manager", email: "manager@tec.dev", password: "manager123", icon: ShieldCheck, hint: "Upload, evaluate & override" },
  { role: "Designer", email: "designer@tec.dev", password: "designer123", icon: Palette, hint: "Read-only reviewed feedback" },
];

export default function LoginPage() {
  const { login, user, loading } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("manager@tec.dev");
  const [password, setPassword] = useState("manager123");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [user, loading, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-grid flex min-h-screen items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="w-full max-w-md rounded-2xl border border-border bg-surface/80 p-8 backdrop-blur"
      >
        <div className="mb-6">
          <div className="mb-1 text-xs font-semibold uppercase tracking-[0.2em] text-primary">
            TEC Productions
          </div>
          <h1 className="text-2xl font-bold">Esports Visual QA</h1>
          <p className="mt-1 text-sm text-muted">
            Automated review for tournament graphics.
          </p>
        </div>

        <form onSubmit={submit} className="space-y-3">
          <input
            className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm outline-none focus:border-primary/60"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
          />
          <input
            className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm outline-none focus:border-primary/60"
            placeholder="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
          {error && (
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="text-sm text-critical"
            >
              {error}
            </motion.p>
          )}
          <Button type="submit" loading={busy} className="w-full">
            Sign in
          </Button>
        </form>

        <div className="mt-6">
          <p className="mb-2 text-xs uppercase tracking-wide text-muted">
            Demo accounts
          </p>
          <div className="grid grid-cols-2 gap-2">
            {DEMO.map((d) => (
              <button
                key={d.email}
                onClick={() => {
                  setEmail(d.email);
                  setPassword(d.password);
                }}
                className="group rounded-lg border border-border bg-surface-2 p-3 text-left transition-colors hover:border-primary/50"
              >
                <d.icon className="mb-1 h-4 w-4 text-primary" />
                <div className="text-sm font-semibold">{d.role}</div>
                <div className="text-[11px] text-muted">{d.hint}</div>
              </button>
            ))}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
