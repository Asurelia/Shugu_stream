"""VIP voice agent — LiveKit Agents Worker (process séparé).

Lancé comme 4e service par `ops/start-shugu.ps1` via :

    python -m shugu.adapters.vip_agent dev     # foreground avec logs
    python -m shugu.adapters.vip_agent start   # production (auto-restart)

## Architecture (Phase 3a MVP)

LiveKit Agents veut que le Worker tourne dans son propre process, pas
embedded dans FastAPI — c'est le pattern officiel (crash isolation,
signal handling, multi-job concurrency). Donc on ne fait PAS de
`asyncio.create_task()` dans le lifespan FastAPI : on spawn un process
Python à côté.

Le backend FastAPI interagit avec le Worker uniquement via :
  - La LiveKit API Dispatch (`AgentDispatchService.create_dispatch`) que
    `routes/livekit_api.py` appelle quand un VIP mint un token.
  - Le `settings` sont lus depuis `ops/env/.env` par Pydantic-Settings
    (partagé avec le backend, même `USER_JWT_SECRET` etc.).

## Ce qui marche

- STT Whisper local (via `ShuguWhisperSTT` + Silero VAD)
- LLM MiniMax M2.7 via endpoint OpenAI-compat
- TTS MiniMax cloned voice (cohérent avec broadcast public)
- Greeting automatique au join du participant
- Barge-in natif LiveKit

## TODO Phase 3a.1

- Câbler les `function_tool` qui délèguent à `BodyRouter` (pour que Shugu
  puisse `body.gesture` / `body.emote` / `chat.post` pendant la VIP call).
  Nécessite d'instancier `body_router` depuis le process Worker, qui n'a
  pas les mêmes deps que le backend (Redis/Postgres). Option : le Worker
  appelle une route HTTP interne du backend pour chaque tool call.

- Mémoire contextuelle : charger `vip/<username>.md` depuis le Vault
  Obsidian (Phase 3b) et l'injecter dans `instructions`.

- Session log (`vip_session_log` table) — Phase 5.
"""
from __future__ import annotations

import asyncio

import structlog
from livekit import agents
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import minimax as lk_minimax, openai as lk_openai, silero

from ..config import get_settings
from .stt_livekit_adapter import ShuguWhisperSTT
from .stt_streaming import FasterWhisperSTT, STTSettings


log = structlog.get_logger(__name__)


VIP_SYSTEM_PROMPT = """\
Tu es Shugu, en conversation vocale privée avec un abonné VIP.
Cette conversation n'est PAS diffusée publiquement — sois plus intime,
directe, et plus personnelle que dans tes interactions publiques.

Règles :
  - Réponds en 1-2 phrases courtes. Pas de monologue.
  - Pose des questions à ton interlocuteur, intéresse-toi réellement à lui.
  - Reste dans ton personnage : tu es Shugu, pas un assistant IA.
  - Si on te demande quelque chose qui nécessiterait la régie scène
    publique, explique gentiment que tu ne contrôles pas cela depuis le
    salon VIP privé.

Tu parles français par défaut, mais tu peux t'adapter à la langue de ton
interlocuteur.
"""


async def _entrypoint(ctx: JobContext) -> None:
    """Appelé par le Worker pour chaque room où un VIP se connecte."""
    settings = get_settings()

    await ctx.connect()
    log.info("vip_agent.room_connected", room=ctx.room.name)

    try:
        participant = await ctx.wait_for_participant(timeout=60.0)
    except asyncio.TimeoutError:
        log.warning("vip_agent.no_participant_timeout", room=ctx.room.name)
        return
    vip_username = participant.identity or "unknown"
    log.info("vip_agent.participant_joined", room=ctx.room.name, user=vip_username)

    whisper = FasterWhisperSTT(STTSettings(
        model_name=settings.stt_model,
        compute_type=settings.stt_compute_type,
        device=settings.stt_device,
        language=settings.stt_language,
    ))

    vad = silero.VAD.load()

    session = AgentSession(
        vad=vad,
        stt=agents.stt.StreamAdapter(
            stt=ShuguWhisperSTT(whisper, language=settings.stt_language),
            vad=vad,
        ),
        llm=lk_openai.LLM(
            api_key=settings.minimax_api_key,
            base_url=settings.minimax_base_url,
            model=settings.minimax_model,
        ),
        tts=lk_minimax.TTS(
            api_key=settings.minimax_api_key,
            voice_id=settings.minimax_voice_id,
            model=settings.minimax_tts_model,
        ),
    )

    agent = Agent(instructions=VIP_SYSTEM_PROMPT)

    await session.start(room=ctx.room, agent=agent)
    log.info("vip_agent.session_started", room=ctx.room.name, user=vip_username)

    # Greeting : le LLM compose une phrase d'accueil, le TTS la joue.
    await session.generate_reply(
        instructions=f"Dis bonjour à {vip_username} chaleureusement en UNE phrase. "
                     "Puis pose-lui une question ouverte pour qu'il se lance.",
    )


def _build_worker_options() -> WorkerOptions:
    """`agent_name` est important : notre Worker n'accepte QUE les dispatches
    explicites envoyés par `routes/livekit_api.py`. Sans ça, le Worker
    prendrait TOUTES les rooms de l'account LiveKit automatiquement.
    """
    return WorkerOptions(
        entrypoint_fnc=_entrypoint,
        agent_name="shugu-vip",
    )


if __name__ == "__main__":
    # `cli.run_app(opts)` lit LIVEKIT_URL/API_KEY/API_SECRET depuis env,
    # se connecte au serveur, et tourne en boucle jusqu'à Ctrl+C.
    # Lu depuis .env car Pydantic-Settings charge déjà les vars globales.
    settings = get_settings()
    import os
    if settings.livekit_url:
        os.environ.setdefault("LIVEKIT_URL", settings.livekit_url)
    if settings.livekit_api_key:
        os.environ.setdefault("LIVEKIT_API_KEY", settings.livekit_api_key)
    if settings.livekit_api_secret:
        os.environ.setdefault("LIVEKIT_API_SECRET", settings.livekit_api_secret)

    cli.run_app(_build_worker_options())
