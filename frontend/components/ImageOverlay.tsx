"use client";

import { AnimatePresence, motion } from "framer-motion";
import { MapPin, Move } from "lucide-react";
import { useRef, useState } from "react";

import type { BBox, Finding } from "@/lib/types";
import { SEVERITY_META, cn } from "@/lib/utils";

interface Region {
  x: number;
  y: number;
  w: number;
  h: number;
}

type Handle = "nw" | "n" | "ne" | "w" | "e" | "sw" | "s" | "se";
type DragMode = "move" | Handle;

interface Props {
  imageUrl: string;
  findings: Finding[];
  hoveredId: string | null;
  selectedId: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string | null) => void;
  addMode: boolean;
  onPlaceRegion: (bbox: Region, isPin: boolean) => void;
  // Managers can move and resize markers; commit fires once on release.
  canEdit?: boolean;
  onGeometryChange?: (id: string, bbox: BBox) => void;
}

const isPin = (f: Finding) =>
  f.is_pin || !f.bbox || (f.bbox.w < 0.005 && f.bbox.h < 0.005);

const PIN_THRESHOLD = 0.01; // drag smaller than this collapses to a pin
const MOVE_EPS = 0.003; // movement under this counts as a click, not a drag
const MIN_SIZE = 0.012; // smallest box a resize may produce
const BAND = 12; // px width of the draggable border band
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const isReal = (f: Finding) => !f.id.startsWith("__"); // the live draft isn't persisted

// Resize grips: [handle, x fraction, y fraction, cursor]
const HANDLES: [Handle, number, number, string][] = [
  ["nw", 0, 0, "nwse-resize"],
  ["n", 0.5, 0, "ns-resize"],
  ["ne", 1, 0, "nesw-resize"],
  ["w", 0, 0.5, "ew-resize"],
  ["e", 1, 0.5, "ew-resize"],
  ["sw", 0, 1, "nesw-resize"],
  ["s", 0.5, 1, "ns-resize"],
  ["se", 1, 1, "nwse-resize"],
];

// Only the border band is interactive, so a marker's interior never intercepts
// events meant for whatever sits inside it.
const EDGES: [string, React.CSSProperties][] = [
  ["t", { left: 0, right: 0, top: -BAND / 2, height: BAND }],
  ["b", { left: 0, right: 0, bottom: -BAND / 2, height: BAND }],
  ["l", { top: 0, bottom: 0, left: -BAND / 2, width: BAND }],
  ["r", { top: 0, bottom: 0, right: -BAND / 2, width: BAND }],
];

// Bigger boxes stack lower, so a canvas-wide finding can never bury a small one.
const boxZ = (f: Finding) => {
  const area = clamp((f.bbox?.w ?? 0) * (f.bbox?.h ?? 0), 0, 1);
  return Math.round(10 + (1 - area) * 10); // 10 (full canvas) .. 20 (tiny)
};

/** Apply a resize to `start` for the given handle, clamped to the canvas. */
function resized(start: BBox, mode: Handle, p: { x: number; y: number }): BBox {
  const right = start.x + start.w;
  const bottom = start.y + start.h;
  let { x, y, w, h } = start;
  if (mode.includes("w")) {
    x = clamp(p.x, 0, right - MIN_SIZE);
    w = right - x;
  }
  if (mode.includes("e")) w = clamp(p.x - start.x, MIN_SIZE, 1 - start.x);
  if (mode.includes("n")) {
    y = clamp(p.y, 0, bottom - MIN_SIZE);
    h = bottom - y;
  }
  if (mode.includes("s")) h = clamp(p.y - start.y, MIN_SIZE, 1 - start.y);
  return { x, y, w, h };
}

export function ImageOverlay({
  imageUrl,
  findings,
  hoveredId,
  selectedId,
  onHover,
  onSelect,
  addMode,
  onPlaceRegion,
  canEdit = false,
  onGeometryChange,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);

  // --- drawing a NEW region (addMode) ---
  const [start, setStart] = useState<{ x: number; y: number } | null>(null);
  const [draft, setDraft] = useState<Region | null>(null);

  // --- moving / resizing an EXISTING marker ---
  const [drag, setDrag] = useState<{
    id: string;
    mode: DragMode;
    start: BBox;
    gx: number; // pointer offset from the box origin, for "move"
    gy: number;
  } | null>(null);
  const [live, setLive] = useState<BBox | null>(null);
  const moved = useRef(false);

  const toNorm = (e: { clientX: number; clientY: number }) => {
    const rect = wrapRef.current!.getBoundingClientRect();
    return {
      x: clamp((e.clientX - rect.left) / rect.width, 0, 1),
      y: clamp((e.clientY - rect.top) / rect.height, 0, 1),
    };
  };

  const onMouseDown = (e: React.MouseEvent) => {
    if (!addMode) return;
    const p = toNorm(e);
    setStart(p);
    setDraft({ x: p.x, y: p.y, w: 0, h: 0 });
  };
  const onMouseMove = (e: React.MouseEvent) => {
    if (!addMode || !start) return;
    const p = toNorm(e);
    setDraft({
      x: Math.min(start.x, p.x),
      y: Math.min(start.y, p.y),
      w: Math.abs(p.x - start.x),
      h: Math.abs(p.y - start.y),
    });
  };
  const onMouseUp = () => {
    if (!addMode || !start || !draft) return;
    const pinLike = draft.w < PIN_THRESHOLD && draft.h < PIN_THRESHOLD;
    onPlaceRegion(pinLike ? { x: start.x, y: start.y, w: 0, h: 0 } : draft, pinLike);
    setStart(null);
    setDraft(null);
  };

  // --- marker drag/resize (manager only) ---
  const canDragF = (f: Finding) => canEdit && !addMode && isReal(f) && !!f.bbox;

  const begin = (f: Finding, mode: DragMode) => (e: React.PointerEvent) => {
    e.stopPropagation();
    if (!canDragF(f) || !f.bbox) return;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    const p = toNorm(e);
    setDrag({
      id: f.id,
      mode,
      start: f.bbox,
      gx: p.x - f.bbox.x,
      gy: p.y - f.bbox.y,
    });
    setLive(f.bbox);
    moved.current = false;
  };

  const onDragMove = (f: Finding) => (e: React.PointerEvent) => {
    if (drag?.id !== f.id) return;
    const p = toNorm(e);
    const s = drag.start;
    const next =
      drag.mode === "move"
        ? {
            ...s,
            x: clamp(p.x - drag.gx, 0, 1 - s.w),
            y: clamp(p.y - drag.gy, 0, 1 - s.h),
          }
        : resized(s, drag.mode, p);

    if (
      Math.abs(next.x - s.x) > MOVE_EPS ||
      Math.abs(next.y - s.y) > MOVE_EPS ||
      Math.abs(next.w - s.w) > MOVE_EPS ||
      Math.abs(next.h - s.h) > MOVE_EPS
    )
      moved.current = true;
    setLive(next);
  };

  const end = (f: Finding) => (e: React.PointerEvent) => {
    e.stopPropagation();
    // No active drag (e.g. designer, or addMode) -> treat as a plain click.
    if (drag?.id !== f.id) {
      onSelect(f.id);
      return;
    }
    if (moved.current && live) onGeometryChange?.(f.id, live);
    else onSelect(f.id); // press without real movement = select
    setDrag(null);
    setLive(null);
  };

  // Geometry to render: the live drag/resize value, else the stored bbox.
  const geom = (f: Finding) => (drag?.id === f.id && live ? live : f.bbox!);

  return (
    <div
      ref={wrapRef}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={() => {
        setStart(null);
        setDraft(null);
      }}
      className={cn(
        "relative inline-block w-full select-none overflow-hidden rounded-xl border border-border bg-bg",
        addMode && "cursor-crosshair",
      )}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={imageUrl} alt="graphic under review" className="block w-full" draggable={false} />

      {addMode && (
        <div className="pointer-events-none absolute inset-0 bg-primary/5 ring-2 ring-inset ring-primary/40" />
      )}

      {draft && (draft.w > 0 || draft.h > 0) && (
        <div
          className="pointer-events-none absolute rounded-md border-2 border-dashed border-accent bg-accent/10"
          style={{
            left: `${draft.x * 100}%`,
            top: `${draft.y * 100}%`,
            width: `${draft.w * 100}%`,
            height: `${draft.h * 100}%`,
          }}
        />
      )}

      <div style={{ pointerEvents: addMode ? "none" : "auto" }}>
        <AnimatePresence>
          {findings.map((f) => {
            if (!f.bbox) return null;
            const active = hoveredId === f.id || selectedId === f.id;
            const dragging = drag?.id === f.id;
            const color =
              f.source === "manager" ? "#A855F7" : SEVERITY_META[f.severity].color;
            const canDrag = canDragF(f);
            const hoverProps = {
              onMouseEnter: () => onHover(f.id),
              onMouseLeave: () => onHover(null),
            };
            const dragProps = {
              onPointerMove: onDragMove(f),
              onPointerUp: end(f),
            };

            if (isPin(f)) {
              const p = geom(f);
              return (
                <Pin
                  key={f.id}
                  x={p.x}
                  y={p.y}
                  color={color}
                  active={active || dragging}
                  canDrag={canDrag}
                  z={dragging ? 60 : active ? 55 : 45}
                  onEnter={() => onHover(f.id)}
                  onLeave={() => onHover(null)}
                  handlers={{ onPointerDown: begin(f, "move"), ...dragProps }}
                />
              );
            }

            const g = geom(f);
            return (
              <motion.div
                key={f.id}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={
                  dragging
                    ? { duration: 0 }
                    : { type: "spring", stiffness: 300, damping: 24 }
                }
                className="absolute"
                style={{
                  left: `${g.x * 100}%`,
                  top: `${g.y * 100}%`,
                  width: `${g.w * 100}%`,
                  height: `${g.h * 100}%`,
                  zIndex: dragging ? 60 : active ? boxZ(f) + 20 : boxZ(f),
                  // Interior is click-through; only the band/chip/grips react.
                  pointerEvents: "none",
                  touchAction: "none",
                }}
              >
                <div
                  className="absolute inset-0 rounded-md"
                  style={{
                    border: `2px solid ${color}`,
                    background: active || dragging ? `${color}18` : "transparent",
                    boxShadow:
                      active || dragging
                        ? `0 0 0 3px ${color}55, 0 0 18px ${color}77`
                        : "none",
                  }}
                />

                {/* label chip doubles as the move handle */}
                <span
                  {...hoverProps}
                  onPointerDown={begin(f, "move")}
                  {...dragProps}
                  className="absolute -top-5 left-0 flex items-center gap-1 whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-semibold"
                  style={{
                    background: color,
                    color: "#0A0E1A",
                    pointerEvents: "auto",
                    cursor: canDrag ? "move" : "pointer",
                  }}
                >
                  {canDrag && <Move className="h-2.5 w-2.5" />}
                  {f.severity}
                </span>

                {/* border bands: hover, select, and drag-to-move */}
                {EDGES.map(([k, style]) => (
                  <div
                    key={k}
                    {...hoverProps}
                    onPointerDown={begin(f, "move")}
                    {...dragProps}
                    style={{
                      position: "absolute",
                      pointerEvents: "auto",
                      cursor: canDrag ? "move" : "pointer",
                      ...style,
                    }}
                  />
                ))}

                {/* corner + edge grips: drag to resize */}
                {canDrag &&
                  HANDLES.map(([k, hx, hy, cursor]) => (
                    <div
                      key={k}
                      onPointerDown={begin(f, k)}
                      {...dragProps}
                      className="absolute rounded-sm"
                      style={{
                        left: `${hx * 100}%`,
                        top: `${hy * 100}%`,
                        width: 9,
                        height: 9,
                        marginLeft: -4.5,
                        marginTop: -4.5,
                        background: "#0A0E1A",
                        border: `2px solid ${color}`,
                        pointerEvents: "auto",
                        cursor,
                        zIndex: 2,
                        opacity: active || dragging ? 1 : 0.55,
                      }}
                    />
                  ))}
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}

function Pin({
  x,
  y,
  color,
  active,
  canDrag,
  z,
  onEnter,
  onLeave,
  handlers,
}: {
  x: number;
  y: number;
  color: string;
  active: boolean;
  canDrag: boolean;
  z: number;
  onEnter: () => void;
  onLeave: () => void;
  handlers: {
    onPointerDown: (e: React.PointerEvent) => void;
    onPointerMove: (e: React.PointerEvent) => void;
    onPointerUp: (e: React.PointerEvent) => void;
  };
}) {
  return (
    <motion.button
      initial={{ opacity: 0, y: -8, scale: 0.6 }}
      animate={{ opacity: 1, y: 0, scale: active ? 1.25 : 1 }}
      exit={{ opacity: 0, scale: 0.6 }}
      transition={{ type: "spring", stiffness: 400, damping: 18 }}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      {...handlers}
      className={cn(
        "absolute -translate-x-1/2 -translate-y-full",
        canDrag ? "cursor-move" : "cursor-pointer",
      )}
      style={{ left: `${x * 100}%`, top: `${y * 100}%`, zIndex: z, touchAction: "none" }}
    >
      <span
        className="grid h-7 w-7 place-items-center rounded-full rounded-bl-none shadow-lg"
        style={{ background: color }}
      >
        <MapPin className="h-4 w-4 text-[#0A0E1A]" />
      </span>
      {active && (
        <span
          className="absolute left-1/2 top-1/2 -z-10 h-7 w-7 -translate-x-1/2 -translate-y-1/2 rounded-full"
          style={{ boxShadow: `0 0 0 6px ${color}44` }}
        />
      )}
    </motion.button>
  );
}
