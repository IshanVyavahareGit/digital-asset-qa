"""Gemini client wrapper.

Why Gemini 2.5: it natively emits bounding boxes as `box_2d = [ymin, xmin, ymax,
xmax]` normalized to 0..1000 (per-axis, aspect-independent) and enforces JSON via
`response_schema`. This module:
  - runs a structured, schema-validated generation (async)
  - converts box_2d -> 0..1 fractions of the canvas
  - retries once on transport/parse failure, then fails loudly (no hallucinated data)
  - accounts token usage -> USD so the README can report demo cost

If no API key is configured the call raises GeminiUnavailable, which each check
turns into an honest `failed` CheckRun rather than a fabricated finding.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel

from app.core.config import settings
from app.schemas import BBox

T = TypeVar("T", bound=BaseModel)

# List price (USD per 1M tokens) per model, for the cost estimate. Keyed by the
# model id in settings.gemini_model so switching models keeps the estimate honest.
_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-3-flash": (0.50, 3.00),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.5-flash-preview": (1.50, 9.00),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.1-pro": (2.00, 12.00),
}
_DEFAULT_PRICE = (0.50, 3.00)


def price_for_model(model: str | None = None) -> tuple[float, float]:
    return _PRICING.get(model or settings.gemini_model, _DEFAULT_PRICE)


def usd_for(input_tokens: int, output_tokens: int, model: str | None = None) -> float:
    """USD for a token count at the given (or current) model's list price."""
    price_in, price_out = price_for_model(model)
    return round(input_tokens / 1e6 * price_in + output_tokens / 1e6 * price_out, 6)


class GeminiUnavailable(RuntimeError):
    """Raised when Gemini can't be used (no key) or fails after a retry."""


@dataclass
class Usage:
    """Accumulates token usage across calls in a single evaluation."""
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.calls += other.calls

    @property
    def usd(self) -> float:
        return usd_for(self.input_tokens, self.output_tokens)


@dataclass
class GeminiResult:
    parsed: BaseModel
    usage: Usage = field(default_factory=Usage)


def box2d_to_bbox(box_2d: list[int | float], clamp: bool = True) -> BBox:
    """Convert Gemini's [ymin, xmin, ymax, xmax] (0..1000) to a 0..1 BBox.

    Per-axis normalization means this is correct for any aspect ratio; we scale
    back by the real width/height only in the frontend (here everything is 0..1).
    """
    # Gemini occasionally emits a malformed box (wrong length / non-numeric).
    # Degrade to a zero box rather than crashing the whole check.
    try:
        if len(box_2d) != 4:
            return BBox(x=0.0, y=0.0, w=0.0, h=0.0)
        ymin, xmin, ymax, xmax = (float(v) / 1000.0 for v in box_2d)
    except (TypeError, ValueError):
        return BBox(x=0.0, y=0.0, w=0.0, h=0.0)
    x, y = min(xmin, xmax), min(ymin, ymax)
    w, h = abs(xmax - xmin), abs(ymax - ymin)
    if clamp:
        x, y = max(0.0, x), max(0.0, y)
        w, h = min(w, 1.0 - x), min(h, 1.0 - y)
    return BBox(x=round(x, 5), y=round(y, 5), w=round(w, 5), h=round(h, 5))


class GeminiClient:
    def __init__(self) -> None:
        self._client = None  # lazily created so importing this module needs no key

    @property
    def available(self) -> bool:
        return bool(settings.gemini_api_key)

    def _ensure_client(self):
        if self._client is None:
            if not self.available:
                raise GeminiUnavailable("GEMINI_API_KEY is not set")
            from google import genai  # local import: heavy SDK, optional at runtime

            self._client = genai.Client(api_key=settings.gemini_api_key)
        return self._client

    async def generate(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        mime_type: str,
        schema: type[T],
        extra_images: list[tuple[bytes, str]] | None = None,
    ) -> GeminiResult:
        """Structured generation with one retry. Returns a validated `schema`.

        `extra_images` (bytes, mime) are prepended as additional visual context —
        used by the theme check to pass approved reference graphics (Tier 3).
        """
        from google import genai  # noqa: F401  (ensures SDK import errors surface here)
        from google.genai import types

        client = self._ensure_client()
        contents = [
            types.Part.from_bytes(data=b, mime_type=m) for b, m in (extra_images or [])
        ]
        contents += [
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            prompt,
        ]
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.0,  # deterministic QA
        )

        last_err: Exception | None = None
        for _ in range(2):  # initial attempt + one retry
            try:
                resp = await client.aio.models.generate_content(
                    model=settings.gemini_model, contents=contents, config=config
                )
                parsed = resp.parsed
                if parsed is None:  # schema failed to bind -> treat as failure
                    raise ValueError("Gemini returned no schema-valid output")
                return GeminiResult(parsed=parsed, usage=_usage_from(resp))
            except Exception as exc:  # noqa: BLE001 - normalize to GeminiUnavailable
                last_err = exc
        raise GeminiUnavailable(f"Gemini failed after retry: {last_err}")


def _usage_from(resp) -> Usage:
    meta = getattr(resp, "usage_metadata", None)
    if meta is None:
        return Usage(calls=1)
    return Usage(
        input_tokens=getattr(meta, "prompt_token_count", 0) or 0,
        output_tokens=getattr(meta, "candidates_token_count", 0) or 0,
        calls=1,
    )


# Module-level singleton (stateless aside from the lazy client).
gemini = GeminiClient()
