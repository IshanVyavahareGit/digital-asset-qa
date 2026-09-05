"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Layers, X, ChevronDown } from "lucide-react";

import { Button } from "./ui/Button";
import { useCreateBatch } from "@/lib/hooks";
import { GRAPHIC_TYPES, PLATFORMS } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import type { GraphicType, Platform } from "@/lib/types";

export function BatchUpload() {
  const router = useRouter();
  const create = useCreateBatch();
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [graphicType, setGraphicType] = useState<GraphicType>(GRAPHIC_TYPES[0].value);
  const [platform, setPlatform] = useState<Platform>(PLATFORMS[0].value);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!files.length) return;
    setError(null);
    const form = new FormData();
    // Backend expects aligned arrays: one type/platform per file.
    files.forEach((f) => {
      form.append("files", f);
      form.append("graphic_types", graphicType);
      form.append("platforms", platform);
    });
    try {
      const batch = await create.mutateAsync(form);
      router.push(`/batch/${batch.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Batch upload failed");
    }
  };

  return (
    <div className="rounded-2xl border border-border bg-surface/60 p-5">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted">
        <Layers className="h-4 w-4 text-accent" /> Batch mode
      </h2>

      <div className="grid gap-4 md:grid-cols-[1.2fr_1fr]">
        <div
          onClick={() => inputRef.current?.click()}
          className="flex min-h-[120px] cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-border p-4 text-center transition-colors hover:border-accent/50"
        >
          <input
            ref={inputRef}
            type="file"
            accept="image/*"
            multiple
            className="hidden"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
          />
          {files.length ? (
            <p className="text-sm">
              <span className="font-semibold text-accent">{files.length}</span>{" "}
              file{files.length === 1 ? "" : "s"} selected
            </p>
          ) : (
            <p className="text-sm text-muted">
              Select multiple graphics (10+) to process through the queue
            </p>
          )}
        </div>

        <div className="flex flex-col gap-3">
          <div className="relative">
            <select
              value={graphicType}
              onChange={(e) => setGraphicType(e.target.value as GraphicType)}
              className="w-full appearance-none rounded-lg border border-border bg-surface-2 pl-3 pr-10 py-2 text-sm outline-none focus:border-accent/60"
            >
              {GRAPHIC_TYPES.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          </div>
          <div className="relative">
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value as Platform)}
              className="w-full appearance-none rounded-lg border border-border bg-surface-2 pl-3 pr-10 py-2 text-sm outline-none focus:border-accent/60"
            >
              {PLATFORMS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          </div>
          <div className="mt-auto">
            {error && <p className="mb-2 text-xs text-critical">{error}</p>}
            <Button
              onClick={submit}
              disabled={!files.length}
              loading={create.isPending}
              variant="subtle"
              className="w-full"
            >
              Process {files.length || ""} graphic{files.length === 1 ? "" : "s"}
            </Button>
          </div>
        </div>
      </div>

      {/* selected files chips */}
      <AnimatePresence>
        {files.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-3 flex flex-wrap gap-1.5"
          >
            {files.map((f, i) => (
              <span
                key={i}
                className="flex items-center gap-1 rounded-full border border-border bg-surface-2 px-2 py-0.5 text-[11px] text-muted"
              >
                {f.name.slice(0, 22)}
                <button
                  onClick={() => setFiles(files.filter((_, j) => j !== i))}
                  className="hover:text-critical"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
