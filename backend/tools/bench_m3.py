"""Benchmark M3 — TTFB, coût, tokens-vision par provider (spec M-0).

Usage:
    cd backend && .venv/Scripts/python -m tools.bench_m3 --runs 5

Mesure, pour le provider configuré (mind_m3_base_url) :
- TTFB (time-to-first-byte de la réponse non-stream — proxy du TTFT),
- coût estimé par appel (usage réel),
- tokens facturés pour un appel AVEC une image (pour calibrer le coût vision).

Lit la config via Settings (env). Imprime un résumé JSON. N'effectue AUCUN
appel si la clé est absente (affiche un message clair).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import httpx

from shugu.adapters.brain_m3 import M3Brain, Message
from shugu.config import Settings

# Prix MiniMax M3 (≤512K contexte), USD par token.
_PRICE_IN_PER_TOKEN = 0.30 / 1_000_000
_PRICE_OUT_PER_TOKEN = 1.20 / 1_000_000

# 1x1 PNG transparent en data-URI (calibration coût vision sans vraie frame).
_TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def cost_usd(*, in_tokens: int, out_tokens: int) -> float:
    return in_tokens * _PRICE_IN_PER_TOKEN + out_tokens * _PRICE_OUT_PER_TOKEN


def summarize(samples: list[dict]) -> dict:
    ttfbs = sorted(s["ttfb_s"] for s in samples)
    return {
        "n": len(samples),
        "ttfb_p50_s": statistics.median(ttfbs) if ttfbs else 0.0,
        "ttfb_max_s": max(ttfbs) if ttfbs else 0.0,
        "avg_cost_usd": (
            sum(cost_usd(in_tokens=s["in"], out_tokens=s["out"]) for s in samples)
            / len(samples)
            if samples else 0.0
        ),
    }


async def _one_call(brain: M3Brain, *, with_image: bool) -> dict:
    msgs = [Message(
        role="user",
        content="Réponds en une phrase courte : quel temps fait-il ?",
        image_urls=[_TINY_PNG] if with_image else [],
    )]
    start = time.monotonic()
    result = await brain.generate(system="Tu es Shugu.", messages=msgs,
                                  thinking="disabled", max_tokens=64, timeout_s=60.0)
    return {"ttfb_s": time.monotonic() - start,
            "in": result.usage.input_tokens, "out": result.usage.output_tokens}


async def _main(runs: int) -> None:
    settings = Settings()  # lit l'env
    if not settings.effective_m3_api_key():
        print("Aucune clé M3 (mind_m3_api_key / minimax_api_key). Bench annulé.")
        return
    async with httpx.AsyncClient() as http:
        brain = M3Brain(settings=settings, http=http)
        text_samples = [await _one_call(brain, with_image=False) for _ in range(runs)]
        vision_samples = [await _one_call(brain, with_image=True) for _ in range(max(1, runs // 2))]
    report = {
        "provider_base_url": settings.mind_m3_base_url,
        "model": settings.mind_m3_model,
        "text_only": summarize(text_samples),
        "with_image": summarize(vision_samples),
        "vision_token_delta": (
            summarize(vision_samples)["avg_cost_usd"] - summarize(text_samples)["avg_cost_usd"]
        ),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(_main(args.runs))
