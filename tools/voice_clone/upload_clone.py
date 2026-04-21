#!/usr/bin/env python
"""Upload a voice sample + clone it on MiniMax.

Usage
-----

    python tools/voice_clone/upload_clone.py \
        --sample assets/voice/shugu_sample.wav \
        --name shugu_fr_v1

Reads MINIMAX_API_KEY from the environment (or --api-key flag). Optionally
reads MINIMAX_BASE_URL to target a specific deployment (defaults to
`https://api.minimax.io/v1`).

The script:
  1. POST /v1/files/upload?purpose=voice_clone → gets a file_id.
  2. POST /v1/voice_clone with file_id + desired voice_id.
  3. Prints the final voice_id, ready to paste in ops/env/.env.

Exit code is non-zero if any step fails; the MiniMax error is surfaced
verbatim (status_code + status_msg) so you can diagnose rejection reasons.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx


DEFAULT_BASE_URL = "https://api.minimax.io/v1"
DEFAULT_TTS_MODEL = "speech-02-hd"

# MiniMax constraint: voice_id must start with a letter, 8-256 chars,
# alphanumeric + underscore only.
VOICE_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{7,255}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Upload a voice sample and clone it on MiniMax. "
            "Prints the final voice_id to paste in ops/env/.env."
        ),
    )
    parser.add_argument(
        "--sample",
        required=True,
        type=Path,
        help="Path to the WAV/MP3/M4A sample (30-60s, mono, 16kHz+).",
    )
    parser.add_argument(
        "--name",
        required=True,
        help=(
            "Custom voice_id (8-256 chars, starts with letter, [A-Za-z0-9_]). "
            "This is what you will paste in MINIMAX_VOICE_ID."
        ),
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("MINIMAX_API_KEY", ""),
        help="MiniMax API key (defaults to $MINIMAX_API_KEY).",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("MINIMAX_BASE_URL", DEFAULT_BASE_URL),
        help="MiniMax API base URL.",
    )
    parser.add_argument(
        "--tts-model",
        default=DEFAULT_TTS_MODEL,
        help=f"TTS model used for the cloning validation (default: {DEFAULT_TTS_MODEL}).",
    )
    parser.add_argument(
        "--preview-text",
        default="Bonjour, je suis Shugu. Ravie de te rencontrer.",
        help="Short text MiniMax uses to validate the clone.",
    )
    parser.add_argument(
        "--noise-reduction",
        action="store_true",
        default=True,
        help="Ask MiniMax to apply noise reduction on the sample (default: on).",
    )
    parser.add_argument(
        "--no-noise-reduction",
        dest="noise_reduction",
        action="store_false",
        help="Disable server-side noise reduction (use if your sample is already clean).",
    )
    return parser.parse_args()


def die(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(code)


def validate(args: argparse.Namespace) -> None:
    if not args.api_key:
        die("MINIMAX_API_KEY is missing. Pass --api-key or export the env var.")
    if not args.sample.exists():
        die(f"Sample file not found: {args.sample}")
    if not args.sample.is_file():
        die(f"Not a regular file: {args.sample}")
    if args.sample.suffix.lower() not in {".wav", ".mp3", ".m4a"}:
        die(
            f"Unsupported extension '{args.sample.suffix}'. "
            "Use .wav, .mp3 or .m4a."
        )
    if not VOICE_ID_PATTERN.match(args.name):
        die(
            f"Invalid voice_id '{args.name}'. Must start with a letter, "
            "8-256 chars, only [A-Za-z0-9_]."
        )
    size = args.sample.stat().st_size
    if size < 10_000:
        die(
            f"Sample too small ({size} bytes). "
            "At 16kHz mono WAV, 30 seconds is ~960KB. Re-record a longer take."
        )
    if size > 20_000_000:
        die(
            f"Sample too large ({size} bytes). "
            "MiniMax caps voice_clone uploads at ~20MB — trim or re-encode."
        )


def _check_base_resp(payload: dict[str, Any], step: str) -> None:
    """Raise via die() if MiniMax returned a non-zero status in base_resp."""
    base = payload.get("base_resp") or {}
    status_code = base.get("status_code")
    if status_code not in (0, None):
        die(
            f"[{step}] MiniMax rejected the request: "
            f"status_code={status_code} "
            f"status_msg={base.get('status_msg') or '<no message>'} "
            f"full_payload={payload}"
        )


def upload_file(
    client: httpx.Client,
    api_key: str,
    base_url: str,
    sample: Path,
) -> str:
    url = f"{base_url}/files/upload"
    with sample.open("rb") as fh:
        files = {"file": (sample.name, fh, "application/octet-stream")}
        try:
            resp = client.post(
                url,
                params={"purpose": "voice_clone"},
                headers={"Authorization": f"Bearer {api_key}"},
                data={"purpose": "voice_clone"},
                files=files,
                timeout=120.0,
            )
        except httpx.HTTPError as exc:
            die(f"[upload] Network error: {exc!r}")
    if resp.status_code >= 400:
        die(f"[upload] HTTP {resp.status_code}: {resp.text[:500]}")
    try:
        payload = resp.json()
    except ValueError:
        die(f"[upload] Response is not JSON: {resp.text[:500]}")
    _check_base_resp(payload, "upload")
    file_block = payload.get("file") or {}
    file_id = file_block.get("file_id")
    if file_id in (None, "", 0):
        die(f"[upload] Response missing file_id: {payload}")
    return str(file_id)


def clone_voice(
    client: httpx.Client,
    api_key: str,
    base_url: str,
    file_id: str,
    voice_id: str,
    preview_text: str,
    tts_model: str,
    noise_reduction: bool,
) -> str:
    url = f"{base_url}/voice_clone"
    body = {
        "file_id": file_id,
        "voice_id": voice_id,
        "text": preview_text,
        "model": tts_model,
        "need_noise_reduction": noise_reduction,
    }
    try:
        resp = client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=180.0,
        )
    except httpx.HTTPError as exc:
        die(f"[clone] Network error: {exc!r}")
    if resp.status_code >= 400:
        die(f"[clone] HTTP {resp.status_code}: {resp.text[:500]}")
    try:
        payload = resp.json()
    except ValueError:
        die(f"[clone] Response is not JSON: {resp.text[:500]}")
    _check_base_resp(payload, "clone")
    # MiniMax returns the same voice_id we sent. The preview audio (demo_audio)
    # can be played client-side if present, but we don't need it here.
    return voice_id


def main() -> None:
    args = parse_args()
    validate(args)
    size_kb = args.sample.stat().st_size // 1024
    print(f"[1/2] Uploading {args.sample.name} ({size_kb} KB) to MiniMax...")
    with httpx.Client() as client:
        file_id = upload_file(client, args.api_key, args.base_url, args.sample)
        print(f"      → file_id = {file_id}")
        print(f"[2/2] Cloning as voice_id '{args.name}'...")
        voice_id = clone_voice(
            client,
            args.api_key,
            args.base_url,
            file_id,
            args.name,
            args.preview_text,
            args.tts_model,
            args.noise_reduction,
        )
    print()
    print(f"  Voice cloned successfully: {voice_id}")
    print()
    print("Next steps:")
    print("  1. Update ops/env/.env:")
    print(f"        MINIMAX_VOICE_ID={voice_id}")
    print("  2. Restart the backend (dev or prod):")
    print("        pm2 restart shugu-backend     # if using PM2")
    print("        # or kill + relaunch uvicorn in dev")
    print("  3. Test via /ws/operator and listen for the new voice.")


if __name__ == "__main__":
    main()
