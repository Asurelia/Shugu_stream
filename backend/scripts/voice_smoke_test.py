"""Sprint A smoke test -- STT -> LLM -> TTS chain en CLI.

Usage:
    cd backend
    python scripts/voice_smoke_test.py --input sample.wav --output response.wav

Verifie :
- whisper.cpp Vulkan transcrit l'audio en francais
- Ollama Gemma 4 repond via HTTP API
- Piper synthetise la reponse
- Latence par leg mesuree

Pre-requis :
- Ollama serve running
- whisper.cpp whisper-cli.exe (ou main.exe pour les builds < v1.7) + small.bin
- piper.exe + fr_FR-siwis-medium.onnx
- Settings env vars set (cf. docs/setup/voice-realtime-windows-amd.md)

NOTE CI : ce script depend de binaires locaux (whisper.cpp, piper, ollama).
Il n'est PAS inclus dans la suite pytest -- executer manuellement apres setup.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import httpx


async def whisper_transcribe(wav_path: Path, whisper_bin: str, model_path: str) -> str:
    """Run whisper.cpp on a wav file, return transcript.

    whisper.cpp --output-txt writes <input_path>.txt (appends .txt to the full
    filename including the .wav extension), so we read from that exact path.

    Uses asyncio.create_subprocess_exec (not shell=True) -- no injection risk.
    """
    t0 = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        whisper_bin,
        "-m", model_path,
        "-f", str(wav_path),
        "--language", "fr",
        "--no-prints",
        "--output-txt",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()
    elapsed = (time.monotonic() - t0) * 1000

    # whisper.cpp writes <wav_path>.txt, e.g. sample.wav -> sample.wav.txt
    txt_path = Path(str(wav_path) + ".txt")
    if not txt_path.exists():
        raise RuntimeError(
            f"whisper.cpp did not produce {txt_path}\n"
            f"stderr: {stderr.decode(errors='replace')}"
        )
    transcript = txt_path.read_text(encoding="utf-8").strip()
    print(f"[STT] {elapsed:.0f}ms -- '{transcript}'")
    return transcript


async def ollama_chat(prompt: str, model: str, base_url: str) -> str:
    """Single-shot Ollama chat (non-streaming for smoke test)."""
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Tu es Shugu, une streameuse virtuelle francaise. "
                            "Reponds en 1-2 phrases courtes."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
            },
        )
        r.raise_for_status()
        data = r.json()
    elapsed = (time.monotonic() - t0) * 1000
    response = data["message"]["content"].strip()
    print(f"[LLM] {elapsed:.0f}ms -- '{response}'")
    return response


async def piper_synthesize(
    text: str, output_path: Path, piper_bin: str, voice_path: str
) -> None:
    """Synthesize text to wav via piper subprocess.

    Uses asyncio.create_subprocess_exec (not shell=True) -- no injection risk.
    """
    t0 = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        piper_bin,
        "--model", voice_path,
        "--output_file", str(output_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate(input=text.encode("utf-8"))
    if proc.returncode != 0:
        raise RuntimeError(
            f"piper failed (rc={proc.returncode}): {stderr.decode(errors='replace')}"
        )
    elapsed = (time.monotonic() - t0) * 1000
    print(f"[TTS] {elapsed:.0f}ms -- wrote {output_path}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Voice smoke test -- STT -> LLM -> TTS")
    parser.add_argument("--input", type=Path, required=True, help="Input wav (16kHz, mono)")
    parser.add_argument("--output", type=Path, required=True, help="Output wav path")
    # whisper-cli.exe is the binary name for whisper.cpp >= v1.7;
    # older builds use main.exe -- override via --whisper-bin if needed.
    parser.add_argument(
        "--whisper-bin",
        default="F:/tools/whisper.cpp/build/bin/Release/whisper-cli.exe",
        help="Path to whisper-cli.exe (or main.exe for builds < v1.7)",
    )
    parser.add_argument(
        "--whisper-model",
        default="F:/tools/whisper.cpp/models/ggml-small.bin",
    )
    parser.add_argument("--piper-bin", default="F:/tools/piper/piper.exe")
    parser.add_argument(
        "--piper-voice",
        default="F:/tools/piper/voices/fr_FR-siwis-medium.onnx",
    )
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--ollama-model", default="gemma4:26b-a4b-q5_K_M")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    print("=== Voice smoke test ===")
    print(f"Input:  {args.input}")
    print(f"Output: {args.output}")
    print()

    t_start = time.monotonic()

    transcript = await whisper_transcribe(args.input, args.whisper_bin, args.whisper_model)
    if not transcript:
        print("ERROR: empty transcript", file=sys.stderr)
        sys.exit(1)

    response = await ollama_chat(transcript, args.ollama_model, args.ollama_url)
    if not response:
        print("ERROR: empty LLM response", file=sys.stderr)
        sys.exit(1)

    await piper_synthesize(response, args.output, args.piper_bin, args.piper_voice)

    total = (time.monotonic() - t_start) * 1000
    print()
    print(f"=== TOTAL: {total:.0f}ms ===")


if __name__ == "__main__":
    asyncio.run(main())
