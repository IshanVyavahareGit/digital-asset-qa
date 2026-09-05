"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { UploadCloud, ImageIcon, X, ChevronDown } from "lucide-react";

import { Button } from "./ui/Button";
import { useUploadGraphic } from "@/lib/hooks";
import { GRAPHIC_TYPES, PLATFORMS, cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";

const PIPELINE_STEPS = [
  "Reading text from the graphic…",
  "Cross-referencing the roster…",
  "Validating matchups…",
  "Detecting sponsor logos…",
  "Reviewing brand & design theme…",
  "Checking platform safe zones…",
  "Computing verdict…",
];

export function UploadDropzone() {
  const router = useRouter();
  const upload = useUploadGraphic();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [graphicType, setGraphicType] = useState(GRAPHIC_TYPES[0].value);
  const [platform, setPlatform] = useState(PLATFORMS[0].value);
  const [dragOver, setDragOver] = useState(false);
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const choose = (f: File | null) => {
    if (!f) return;
    setFile(f);
    setPreview(URL.createObjectURL(f));
    setError(null);
  };

  const submit = async () => {
    if (!file) return;
    setError(null);
    // Cosmetic step ticker while the (real) pipeline runs.
    setStep(0);
    const ticker = setInterval(
      () => setStep((s) => Math.min(s + 1, PIPELINE_STEPS.length - 1)),
      2300,
    );
    const form = new FormData();
    form.append("file", file);
    form.append("graphic_type", graphicType);
    form.append("platform", platform);
    try {
      const review = await upload.mutateAsync(form);
      router.push(`/reviews/${review.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      clearInterval(ticker);
    }
  };

  return (
    <div className="rounded-2xl border border-border bg-surface/60 p-5">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted">
        Upload & evaluate
      </h2>

      <div className="grid gap-4 md:grid-cols-[1.2fr_1fr]">
        {/* dropzone */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            choose(e.dataTransfer.files?.[0] ?? null);
          }}
          onClick={() => inputRef.current?.click()}
          className={cn(
            "relative flex min-h-[200px] cursor-pointer flex-col items-center justify-center overflow-hidden rounded-xl border-2 border-dashed p-4 text-center transition-colors",
            dragOver
              ? "border-primary bg-primary/5"
              : "border-border hover:border-primary/50",
          )}
        >
          <input
            ref={inputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => choose(e.target.files?.[0] ?? null)}
          />
          {preview ? (
            <>
              <img
                src={preview}
                alt="preview"
                className="max-h-[220px] rounded-lg object-contain"
              />
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setFile(null);
                  setPreview(null);
                }}
                className="absolute right-2 top-2 rounded-full bg-bg/80 p-1 text-muted hover:text-critical"
              >
                <X className="h-4 w-4" />
              </button>
            </>
          ) : (
            <>
              <motion.div
                animate={{ y: dragOver ? -4 : 0 }}
                className="mb-2 grid h-12 w-12 place-items-center rounded-full bg-primary/10 text-primary"
              >
                <UploadCloud className="h-6 w-6" />
              </motion.div>
              <p className="text-sm">
                Drop a graphic here or{" "}
                <span className="text-primary">browse</span>
              </p>
              <p className="mt-1 text-xs text-muted">PNG / JPG</p>
            </>
          )}
        </div>

        {/* controls */}
        <div className="flex flex-col gap-3">
          <Field label="Graphic type">
            <Select
              value={graphicType}
              onChange={setGraphicType}
              options={GRAPHIC_TYPES}
            />
          </Field>
          <Field label="Platform">
            <Select value={platform} onChange={setPlatform} options={PLATFORMS} />
          </Field>

          <div className="mt-auto">
            {error && <p className="mb-2 text-xs text-critical">{error}</p>}
            <Button
              onClick={submit}
              disabled={!file}
              loading={upload.isPending}
              className="w-full"
            >
              {upload.isPending ? "Evaluating…" : "Run QA"}
            </Button>
          </div>
        </div>
      </div>

      {/* live pipeline status */}
      <AnimatePresence>
        {upload.isPending && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-4 flex items-center gap-3 rounded-lg border border-primary/20 bg-primary/5 px-4 py-3"
          >
            <ImageIcon className="h-4 w-4 shrink-0 animate-pulse text-primary" />
            <AnimatePresence mode="wait">
              <motion.span
                key={step}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                className="text-sm text-[#C6D0E8]"
              >
                {PIPELINE_STEPS[step]}
              </motion.span>
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs uppercase tracking-wide text-muted">
        {label}
      </span>
      {children}
    </label>
  );
}

function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: any) => void;
  options: readonly { value: string; label: string }[];
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full appearance-none rounded-lg border border-border bg-surface-2 pl-3 pr-10 py-2 text-sm outline-none focus:border-primary/60"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
    </div>
  );
}
