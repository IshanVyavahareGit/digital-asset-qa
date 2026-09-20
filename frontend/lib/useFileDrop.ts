"use client";

import { useCallback, useRef, useState } from "react";

interface Options {
  /** Keep every dropped file, or just the first. Default: false. */
  multiple?: boolean;
  /** Ignore anything that isn't an image. Default: true. */
  imagesOnly?: boolean;
}

/**
 * Accept files dragged straight from Finder / File Explorer onto an element.
 *
 * Spread the returned handlers onto the drop target and use `dragOver` to style
 * it. Two details this handles that a naive implementation gets wrong:
 *
 *   - dragenter/dragleave fire again for every CHILD element the cursor crosses,
 *     which makes a plain boolean flicker off mid-drag. We count depth instead.
 *   - dragover MUST call preventDefault on every event, or the drop never fires
 *     and the browser navigates away to the dropped file instead.
 */
export function useFileDrop(
  onFiles: (files: File[]) => void,
  { multiple = false, imagesOnly = true }: Options = {},
) {
  const [dragOver, setDragOver] = useState(false);
  const depth = useRef(0);

  const onDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    depth.current += 1;
    setDragOver(true);
  }, []);

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault(); // required on EVERY dragover, not just the first
    e.dataTransfer.dropEffect = "copy"; // shows the "+" cursor
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    depth.current -= 1;
    if (depth.current <= 0) {
      depth.current = 0;
      setDragOver(false);
    }
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      depth.current = 0;
      setDragOver(false);

      let dropped = Array.from(e.dataTransfer.files ?? []);
      if (imagesOnly) dropped = dropped.filter((f) => f.type.startsWith("image/"));
      if (!dropped.length) return; // dropped a folder or a non-image — ignore
      onFiles(multiple ? dropped : dropped.slice(0, 1));
    },
    [onFiles, multiple, imagesOnly],
  );

  return {
    dragOver,
    dropHandlers: { onDragEnter, onDragOver, onDragLeave, onDrop },
  };
}

/** Merge new files into an existing list, skipping ones already picked. */
export function mergeFiles(existing: File[], incoming: File[]): File[] {
  const key = (f: File) => `${f.name}:${f.size}:${f.lastModified}`;
  const seen = new Set(existing.map(key));
  return [...existing, ...incoming.filter((f) => !seen.has(key(f)))];
}
