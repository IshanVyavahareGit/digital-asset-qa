"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  Check,
  Pencil,
  RotateCcw,
  Trash2,
  Wand2,
  X,
  User,
  Bot,
} from "lucide-react";
import { useState } from "react";

import type { Finding, Severity } from "@/lib/types";
import { CHECK_LABEL, SEVERITY_META, cn } from "@/lib/utils";
import { Button } from "./ui/Button";

interface Props {
  findings: Finding[];
  hoveredId: string | null;
  selectedId: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string | null) => void;
  canOverride: boolean;
  onUpdate: (id: string, body: any) => void;
  onDelete: (id: string) => void;
  busyId: string | null;
}

export function FindingsPanel({
  findings,
  hoveredId,
  selectedId,
  onHover,
  onSelect,
  canOverride,
  onUpdate,
  onDelete,
  busyId,
}: Props) {
  if (!findings.length) {
    return (
      <div className="rounded-xl border border-success/30 bg-success/5 p-6 text-center">
        <Check className="mx-auto mb-2 h-6 w-6 text-success" />
        <p className="text-sm text-success">Passed All Checks</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <AnimatePresence initial={false}>
        {findings.map((f) => (
          <FindingRow
            key={f.id}
            f={f}
            active={hoveredId === f.id || selectedId === f.id}
            onHover={onHover}
            onSelect={onSelect}
            canOverride={canOverride}
            onUpdate={onUpdate}
            onDelete={onDelete}
            busy={busyId === f.id}
          />
        ))}
      </AnimatePresence>
    </div>
  );
}

function FindingRow({
  f,
  active,
  onHover,
  onSelect,
  canOverride,
  onUpdate,
  onDelete,
  busy,
}: {
  f: Finding;
  active: boolean;
  onHover: (id: string | null) => void;
  onSelect: (id: string | null) => void;
  canOverride: boolean;
  onUpdate: (id: string, body: any) => void;
  onDelete: (id: string) => void;
  busy: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [msg, setMsg] = useState(f.message);
  const [sev, setSev] = useState<Severity>(f.severity);
  const meta = SEVERITY_META[f.severity];
  const dismissed = f.status === "dismissed";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 8 }}
      animate={{ opacity: dismissed ? 0.5 : 1, x: 0 }}
      exit={{ opacity: 0, x: 8 }}
      onMouseEnter={() => onHover(f.id)}
      onMouseLeave={() => onHover(null)}
      onClick={() => onSelect(f.id)}
      className={cn(
        "cursor-pointer rounded-xl border bg-surface/60 p-3 transition-all",
        active ? "border-primary/60 shadow-glow" : "border-border",
      )}
      style={{ borderLeft: `3px solid ${meta.color}` }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className="rounded px-1.5 py-0.5 text-[10px] font-bold uppercase"
            style={{ background: `${meta.color}22`, color: meta.color }}
          >
            {f.severity}
          </span>
          <span className="text-[11px] text-muted">
            {CHECK_LABEL[f.check_type]}
          </span>
          {f.source === "manager" ? (
            <User className="h-3 w-3 text-accent" />
          ) : (
            <Bot className="h-3 w-3 text-muted" />
          )}
          {dismissed && (
            <span className="text-[10px] uppercase text-muted">dismissed</span>
          )}
          {f.status === "edited" && (
            <span className="text-[10px] uppercase text-primary">edited</span>
          )}
        </div>
        {f.confidence != null && (
          <span className="font-mono text-[10px] text-muted">
            {Math.round(f.confidence * 100)}%
          </span>
        )}
      </div>

      {editing ? (
        <div className="mt-2 space-y-2" onClick={(e) => e.stopPropagation()}>
          <textarea
            value={msg}
            onChange={(e) => setMsg(e.target.value)}
            rows={2}
            className="w-full rounded-lg border border-border bg-surface-2 px-2 py-1.5 text-sm outline-none focus:border-primary/60"
          />
          <div className="flex items-center gap-2">
            <select
              value={sev}
              onChange={(e) => setSev(e.target.value as Severity)}
              className="rounded-lg border border-border bg-surface-2 px-2 py-1 text-xs"
            >
              <option value="critical">Critical</option>
              <option value="warning">Warning</option>
              <option value="info">Info</option>
            </select>
            <Button
              variant="primary"
              className="px-2 py-1 text-xs"
              loading={busy}
              onClick={() => {
                onUpdate(f.id, { message: msg, severity: sev });
                setEditing(false);
              }}
            >
              Save
            </Button>
            <Button
              variant="ghost"
              className="px-2 py-1 text-xs"
              onClick={() => {
                setEditing(false);
                setMsg(f.message);
                setSev(f.severity);
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <>
          <p className={cn("mt-1.5 text-sm", dismissed && "line-through")}>
            {f.message}
          </p>
          {f.suggested_fix && (
            <p className="mt-1 flex items-start gap-1 text-xs text-muted">
              <Wand2 className="mt-0.5 h-3 w-3 shrink-0 text-primary" />
              {f.suggested_fix}
            </p>
          )}
        </>
      )}

      {canOverride && !editing && (
        <div
          className="mt-2 flex items-center gap-1 border-t border-border/60 pt-2"
          onClick={(e) => e.stopPropagation()}
        >
          {dismissed ? (
            <IconBtn
              label="Restore"
              onClick={() => onUpdate(f.id, { status: "open" })}
              busy={busy}
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </IconBtn>
          ) : (
            <IconBtn
              label="Dismiss"
              onClick={() => onUpdate(f.id, { status: "dismissed" })}
              busy={busy}
            >
              <X className="h-3.5 w-3.5" />
            </IconBtn>
          )}
          <IconBtn label="Edit" onClick={() => setEditing(true)}>
            <Pencil className="h-3.5 w-3.5" />
          </IconBtn>
          {f.source === "manager" && (
            <IconBtn
              label="Delete"
              danger
              onClick={() => onDelete(f.id)}
              busy={busy}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </IconBtn>
          )}
        </div>
      )}
    </motion.div>
  );
}

function IconBtn({
  children,
  label,
  onClick,
  danger,
  busy,
}: {
  children: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
  busy?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      title={label}
      className={cn(
        "flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted transition-colors hover:bg-surface-2 disabled:opacity-50",
        danger ? "hover:text-critical" : "hover:text-primary",
      )}
    >
      {children}
      {label}
    </button>
  );
}
