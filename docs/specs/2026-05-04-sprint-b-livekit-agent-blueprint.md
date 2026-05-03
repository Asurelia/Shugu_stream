---
date: 2026-05-04
status: blueprint-final-v1
sprint: B
authors: architect-agent
environment-verified: livekit-agents==1.5.5, livekit==1.1.5, livekit-plugins-silero==1.5.5
---

# Blueprint Sprint B — LiveKit Agent Worker Python (pipe fonctionnel naif)

## Corrections preliminaires au spec 2026-05-03

Deux divergences entre `docs/specs/2026-05-03-realtime-voice-shugu.md` et l'etat reel du repo :

1. `backend/shugu/adapters/vip_agent.py` n'existe pas. Les options (a)/(b)/(c) du §15.5 sont caduques. Sprint B batit le worker depuis les stubs existants dans `voice/`, sans extension ni depreciation.

2. `livekit-agents` et `livekit-plugins-silero` ne sont pas dans `backend/pyproject.toml`. Seul `livekit-api>=1.0,<2.0` y figure. Les deux sont ajouts obligatoires (§7). `faster-whisper` n'est jamais importe dans le code source — il est deplace en extra optionnel (§7).

---

## 1. Tree fichiers definitif

Layout plat sous `backend/shugu/voice/`. Aucun sous-dossier `agent/` n'est cree.

```
backend/shugu/voice/
├── __init__.py                        # existant — vide, OK
├── llm_local.py                       # existant — ajouter asyncio.Lock (§3)
├── stt_local.py                       # existant — implémenter WhisperSTT.transcribe()
├── tts_local.py                       # existant — implémenter PiperTTS.synthesize()
├── livekit_agent.py                   # existant — implémenter entrypoint complet
├── audio_bridge.py                    # existant — Sprint E, ne pas toucher
├── recording.py                       # existant — Sprint G, ne pas toucher
└── regie/
    ├── __init__.py                    # existant
    ├── intent_classifier.py           # existant, complet
    └── tool_call_parser.py            # existant, complet

backend/tests/unit/voice/              # CREER
├── __init__.py
├── test_stt_local.py
├── test_tts_local.py
└── test_livekit_agent.py

backend/tests/integration/voice/       # CREER
├── __init__.py
└── test_agent_room.py
```

Fichiers hors `voice/` modifies dans Sprint B :

| Fichier | Changement |
|---|---|
| `backend/pyproject.toml` | Ajout deps Sprint B, deplacement `faster-whisper` en extra |
| `backend/shugu/config.py` | Ajout 4 champs settings avec defaults DUR-5, ajout `voice_agent_enabled` |
| `backend/shugu/app.py` | Wire `build_worker_options` dans le lifespan (DUR-1 in-process) |

---

## 2. Signatures Python typees des classes principales

### 2.1 `stt_local.py` — `WhisperSTT`

Renommage : le stub s'appelle `LocalSTT`. Le coder renomme en `WhisperSTT` (coherence avec `PiperTTS`).
Garder `LocalSTT = WhisperSTT` en alias si des fichiers existants importent deja `LocalSTT`.

```python
class WhisperSTT:
    _SUBPROCESS_TIMEOUT_S: float = 30.0
    _WAV_SAMPLE_RATE: int = 16_000
    _WAV_NUM_CHANNELS: int = 1
    _WAV_BITS_PER_SAMPLE: int = 16

    def __init__(self, settings: Settings) -> None:
        """Raises FileNotFoundError si whisper_bin ou whisper_model absent du FS."""

    @staticmethod
    def _build_wav_header(pcm_bytes: bytes) -> bytes:
        """WAV header 44 bytes pour PCM s16le 16 kHz mono.
        struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", ...).
        """

    async def transcribe(
        self,
        pcm_16k_mono: bytes,   # PCM s16le 16 kHz mono, duree <= 30s
        language: str = "fr",
    ) -> str:
        """One-shot via subprocess. Retourne "" sur silence/erreur/timeout.
        CLI  : whisper-cli.exe --model <path> --language <lang> --no-timestamps -f -
        stdin: WAV header 44 bytes + pcm_16k_mono
        """

    async def transcribe_stream(
        self,
        audio_chunks: AsyncIterator[bytes],
        language: str = "fr",
    ) -> AsyncIterator[str]:
        """Sprint C."""
        raise NotImplementedError("Sprint C")
        yield  # type: ignore[misc]
```

### 2.2 `tts_local.py` — `PiperTTS`

Renommage : le stub s'appelle `LocalTTS`. Le coder renomme en `PiperTTS`.

```python
class PiperTTS:
    NATIVE_SAMPLE_RATE: int = 22_050   # fr_FR-siwis-medium natif confirme
    _SUBPROCESS_TIMEOUT_S: float = 30.0

    def __init__(self, settings: Settings) -> None:
        """Raises FileNotFoundError si piper_bin ou piper_voice absent du FS."""

    async def synthesize(self, text: str) -> bytes:
        """One-shot via subprocess. Retourne b"" sur erreur/timeout.
        CLI  : piper.exe --model <piper_voice> --output_raw
        stdin: text encode UTF-8
        out  : PCM s16le 22050 Hz mono brut (sans WAV header)
        """

    async def synthesize_stream(
        self,
        text_chunks: AsyncIterator[str],
    ) -> AsyncIterator[bytes]:
        """Sprint C."""
        raise NotImplementedError("Sprint C")
        yield  # type: ignore[misc]
```

### 2.3 `llm_local.py` — `LocalLLM` (deux ajouts Sprint B, reste inchange)

Modifications minimales : `asyncio.Lock` et logs de chargement.

```python
class LocalLLM:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = None
        self._lock = asyncio.Lock()   # AJOUT Sprint B — non-reentrancy llama-cpp-python

    def _ensure_loaded(self) -> None:
        if self._llm is not None:
            return
        from llama_cpp import Llama
        log.info("voice.llm.loading", model_path=self._settings.llm_model_path)
        self._llm = Llama(
            model_path=self._settings.llm_model_path,
            n_ctx=self._settings.llm_n_ctx,
            n_gpu_layers=self._settings.llm_n_gpu_layers,
            n_batch=2048,
            n_threads=10,
            flash_attn=self._settings.llm_flash_attn,
            verbose=True,   # temporaire Sprint B — verifie "registered backend Vulkan"
        )
        log.info("voice.llm.loaded")

    async def generate(
        self,
        system: str,
        messages: Sequence[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.85,
        enable_thinking: bool = False,
    ) -> str:
        async with self._lock:          # AJOUT Sprint B
            self._ensure_loaded()
            full_messages = [{"role": "system", "content": system}] + list(messages)
            loop = asyncio.get_event_loop()
            out = await loop.run_in_executor(
                None,
                lambda: self._llm.create_chat_completion(
                    messages=full_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    chat_template_kwargs={"enable_thinking": enable_thinking},
                ),
            )
        text = out["choices"][0]["message"]["content"]
        log.info("voice.llm.response", length=len(text))
        return text

    async def stream(self, *args, **kwargs) -> AsyncIterator[str]:
        raise NotImplementedError("Sprint C")
        yield  # type: ignore[misc]
```

Regle coder : toute methode future appelant `self._llm.create_chat_completion` ou
`self._llm.create_completion` doit etre protegee par `async with self._lock`.

### 2.4 `livekit_agent.py` — `ShuguVoiceAgent` + entrypoint

Signatures contractuelles. Le corps est a implementer par le coder.
API verifiee sur livekit-agents==1.5.5 installe.

```python
from functools import partial
from livekit import agents, rtc
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, AutoSubscribe
from livekit.plugins.silero import VAD

from ..config import Settings
from .stt_local import WhisperSTT
from .tts_local import PiperTTS
from .llm_local import LocalLLM


class ShuguVoiceAgent(Agent):
    """LiveKit Agent pipeline naif Sprint B.
    Injection constructeur — testable avec mocks sans LiveKit reel.
    Sprint D remplace _handle_turn par la FSM 7 etats (spec §4).
    """

    def __init__(
        self,
        stt: WhisperSTT,
        llm: LocalLLM,
        tts: PiperTTS,
        settings: Settings,
        audio_source: rtc.AudioSource,
    ) -> None:
        super().__init__()
        self._stt = stt
        self._llm = llm
        self._tts = tts
        self._settings = settings
        self._audio_source = audio_source
        self._processing: bool = False      # backpressure flag — voir §6.2
        self._active_stt_proc = None        # ref subprocess pour shutdown — voir §6.3
        self._active_tts_proc = None

    async def on_enter(self) -> None:
        """Appele par AgentSession a la connexion. Sprint B : log voice.session.ready."""

    async def _drain_and_transcribe(self, track: rtc.RemoteAudioTrack) -> None:
        """Accumule frames AudioStream jusqu'a VAD EoU ou 30s max.
        Droppe si self._processing == True. Lance _handle_turn(transcript).
        """

    async def _handle_turn(self, transcript: str) -> None:
        """Pipeline complet un tour.
        1. intent_classifier.classify(transcript)
        2. _build_sprint_b_system_prompt(intent_match)
        3. LocalLLM.generate(system, msgs, max_tokens=200, enable_thinking=False)
        4. tool_call_parser.has_tool_calls(resp) -> log+strip si True (Sprint C execute)
        5. PiperTTS.synthesize(response_text) -> pcm_22050: bytes
        6. _resample_and_publish(pcm_22050)
        finally: self._processing = False  (toujours)
        """

    async def _resample_and_publish(self, pcm_22050: bytes) -> None:
        """Resample 22050->48000 Hz via rtc.AudioResampler(HIGH).
        Frames 10ms = 220 samples = 440 bytes.
        Pour chaque frame: await self._audio_source.capture_frame(frame).
        """

    @staticmethod
    def _build_sprint_b_system_prompt(intent_match) -> str:
        """Prompt minimal inline. Sprint C remplace par regie/prompt_builder.py."""


async def entrypoint(ctx: JobContext, llm: LocalLLM) -> None:
    """Enregistree dans WorkerOptions.entrypoint_fnc via partial(entrypoint, llm=llm).

    Sequence d'initialisation :
    1. settings = get_settings()
    2. stt = WhisperSTT(settings)  — FileNotFoundError si bin absent
    3. tts = PiperTTS(settings)    — FileNotFoundError si bin absent
    4. source = rtc.AudioSource(sample_rate=48_000, num_channels=1)
    5. track = rtc.LocalAudioTrack.create_audio_track("shugu-voice", source)
    6. await ctx.room.local_participant.publish_track(track, rtc.TrackPublishOptions())
    7. agent = ShuguVoiceAgent(stt, llm, tts, settings, source)
    8. session = AgentSession(vad=VAD.load())
    9. await session.start(agent=agent, room=ctx.room)
    10. await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    11. @room.on("track_subscribed"): si KIND_AUDIO -> create_task(agent._drain_and_transcribe)
    12. ctx.add_shutdown_callback(_on_shutdown)
    """


def build_worker_options(settings: Settings, llm: LocalLLM) -> WorkerOptions:
    """Factory appelee depuis app.py lifespan.
    Retourne WorkerOptions(
        entrypoint_fnc=partial(entrypoint, llm=llm),
        ws_url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    ).
    """
```

---
## 3. Flow audio frame -> STT -> reegie -> LLM -> TTS -> publish track

```
[LiveKit room Docker localhost:7880]
  Participant (operator mic) publie Opus 48 kHz mono 20 ms/frame (DUR-4 verrouillee)

  entrypoint — initialisation
  ───────────────────────────────────────────────────────────────────────────────
  AudioSource(48_000, 1) cree une fois ; LocalAudioTrack publie dans la room.
  AgentSession(vad=VAD.load()).start(agent, room=ctx.room)
  ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

  ETAPE 1 — Accumulation frames jusqu'a VAD end-of-utterance
  ───────────────────────────────────────────────────────────────────────────────
  room.on("track_subscribed") -> create_task(agent._drain_and_transcribe(track))

  audio_stream = rtc.AudioStream(track, sample_rate=48_000, num_channels=1)
  buffer: list[rtc.AudioFrame] = []

  async for event in audio_stream:
      if agent._processing:
          log("voice.audio.dropped")   # backpressure
          continue
      buffer.append(event.frame)
      if vad_end_of_utterance(event):
          break
      if buffer_duration > 30s:
          break                        # borne max whisper

  combined: rtc.AudioFrame = rtc.combine_audio_frames(buffer)
  # combined : PCM s16le int16, 48 kHz, 1 ch

  ETAPE 2 — Resampling 48 kHz -> 16 kHz  (ratio 3:1 entier, sans artefact)
  ───────────────────────────────────────────────────────────────────────────────
  resampler_down = rtc.AudioResampler(
      input_rate=48_000, output_rate=16_000,
      num_channels=1, quality=AudioResamplerQuality.HIGH,
  )
  frames_16k = resampler_down.push(combined)          # list[AudioFrame]
  pcm_16k    = rtc.combine_audio_frames(frames_16k)
  pcm_bytes  = bytes(pcm_16k.data)                    # PCM s16le 16 kHz mono

  ETAPE 3 — WhisperSTT.transcribe(pcm_bytes, language="fr")
  ───────────────────────────────────────────────────────────────────────────────
  stdin  : WAV header 44 bytes + pcm_bytes
  stdout : texte transcrit
  Latence cible : 80-150 ms (whisper base Vulkan AMD)

  if transcript == "":
      agent._processing = False
      return   # silence ou erreur STT

  ETAPE 4 — Reegie pre-LLM
  ───────────────────────────────────────────────────────────────────────────────
  intent_match = regie.intent_classifier.classify(transcript)
  # Sprint B : CHAT traite, WEB_SEARCH / EMOTION / EMOTE -> loggues, pas executes
  # Sprint C : WEB_SEARCH -> pre-fetch Tavily ; autres intents -> avatar events

  system_prompt = ShuguVoiceAgent._build_sprint_b_system_prompt(intent_match)
  # prompt inline minimal : persona Shugu + "reponds en 1-2 phrases concises"
  # Sprint C : remplace par regie.prompt_builder.build(...)

  messages = [{"role": "user", "content": transcript}]

  ETAPE 5 — LocalLLM.generate(system, messages, max_tokens=200, enable_thinking=False)
  ───────────────────────────────────────────────────────────────────────────────
  async with self._lock:
      run_in_executor(None, create_chat_completion(...))
  Latence cible : ~187 ms TTFB (Gemma 4 26B-A4B IQ4_XS Vulkan chaud)

  if regie.tool_call_parser.has_tool_calls(response_text):
      response_text = _strip_tool_calls(response_text)  # log warning + strip Sprint B
      # Sprint C : executer les tool_calls avant TTS

  ETAPE 6 — PiperTTS.synthesize(response_text)
  ───────────────────────────────────────────────────────────────────────────────
  stdin  : response_text encode UTF-8
  stdout : PCM s16le 22050 Hz mono brut (--output_raw, sans WAV header)
  Latence cible : ~80 ms (Piper ONNX CPU i5 12600k)

  if pcm_22050 == b"":
      agent._processing = False
      return

  ETAPE 7 — Resampling 22050 Hz -> 48 kHz  (ratio non-entier ~2.177)
  ───────────────────────────────────────────────────────────────────────────────
  resampler_up = rtc.AudioResampler(
      input_rate=22_050, output_rate=48_000,
      num_channels=1, quality=AudioResamplerQuality.HIGH,
  )
  # Decouper pcm_22050 en frames 10 ms = 220 samples = 440 bytes
  CHUNK_BYTES = 220 * 2
  frames_48k: list[rtc.AudioFrame] = []
  for i in range(0, len(pcm_22050), CHUNK_BYTES):
      chunk = pcm_22050[i:i+CHUNK_BYTES].ljust(CHUNK_BYTES, b"\x00")
      frame_in = rtc.AudioFrame(
          data=chunk, sample_rate=22_050,
          num_channels=1, samples_per_channel=220,
      )
      frames_48k.extend(resampler_up.push(frame_in))

  ETAPE 8 — Publish audio track LiveKit
  ───────────────────────────────────────────────────────────────────────────────
  # AudioSource reste le meme objet pour toute la session
  for frame in frames_48k:
      await self._audio_source.capture_frame(frame)

  log.info("voice.tts.published", frames=len(frames_48k))
  agent._processing = False   # libere pour le tour suivant

[Participants entendent Shugu dans la room LiveKit Docker localhost]
```

**Budget latence end-to-end Sprint B (pipeline naif, non-streaming) :**

| Etape | Cible P50 |
|---|---|
| VAD end-of-utterance detect | 50-100 ms |
| Resampling 48->16 kHz (rtc) | ~1 ms |
| STT whisper.cpp Vulkan base | 80-150 ms |
| LLM Gemma 4 26B-A4B IQ4_XS | ~187 ms (chaud) |
| TTS Piper ONNX CPU | ~80 ms |
| Resampling 22050->48 kHz (rtc) | ~1 ms |
| AudioSource capture_frame loop | ~5 ms |
| **Total P50** | **~404-524 ms** |

Cible apres Sprint C (streaming TTS + chunker) : ~330-450 ms.

---
## 4. Decoupage en PRs

### Justification : 2 PRs

1.5 journees de scope. Un PR unique depasserait 500 lignes (regle projet) et
melangerait wiring infrastructure (connexion room, lifecycle) et logique metier
(pipeline audio complet). Deux PRs permite une review focalisee et un merge
incremental safe.

---

### PR1 — Worker shell + infrastructure room (demi-journee)

**Objectif :** l'agent rejoint la room, se deconnecte proprement. Tests unitaires
passent sans infra reelle.

**Fichiers touches :**

| Fichier | Action |
|---|---|
| `backend/shugu/voice/livekit_agent.py` | `ShuguVoiceAgent.__init__` + `on_enter` log, `entrypoint` connect/subscribe/lifecycle/shutdown, `build_worker_options`. `_handle_turn` = stub `pass` (cable PR2). |
| `backend/shugu/config.py` | Remplacer les 4 champs `whisper_bin/model/piper_bin/voice` (vides) par les `Field(default=..., AliasChoices)` de §8. Ajouter `voice_agent_enabled`. |
| `backend/pyproject.toml` | Ajouter `livekit-agents>=1.5,<2.0`, `livekit-plugins-silero>=1.5,<2.0`, `llama-cpp-python>=0.3.22,<0.4.0`. Deplacer `faster-whisper` en extra `cloud-stt`. |
| `backend/tests/unit/voice/__init__.py` | Creer vide. |
| `backend/tests/unit/voice/test_livekit_agent.py` | Tests U-AGT-1 et U-AGT-2 (§5.1). |

**Gate de merge :** `pytest -m "not integration"` vert, ruff vert, pas de regression.

---

### PR2 — STT + TTS + pipe end-to-end naif (1 journee)

**Objectif :** pipeline complet fonctionnel. Smoke test manuel reussi.

**Fichiers touches :**

| Fichier | Action |
|---|---|
| `backend/shugu/voice/stt_local.py` | Renommer `LocalSTT` -> `WhisperSTT`. Implémenter `transcribe()`. Garder stub `transcribe_stream()`. |
| `backend/shugu/voice/tts_local.py` | Renommer `LocalTTS` -> `PiperTTS`. Implementer `synthesize()`. Garder stub `synthesize_stream()`. |
| `backend/shugu/voice/llm_local.py` | Ajouter `asyncio.Lock`, logs chargement Vulkan. |
| `backend/shugu/voice/livekit_agent.py` | Implementer `_drain_and_transcribe`, `_handle_turn`, `_resample_and_publish`, `_build_sprint_b_system_prompt`, `_strip_tool_calls`. |
| `backend/shugu/app.py` | Wiring lifespan DUR-1 : si `voice_agent_enabled`, creer `LocalLLM` + `build_worker_options` + `create_task`. Voir §9. |
| `backend/tests/unit/voice/test_stt_local.py` | Tests U-STT-1 a U-STT-6. |
| `backend/tests/unit/voice/test_tts_local.py` | Tests U-TTS-1 a U-TTS-5. |
| `backend/tests/unit/voice/test_livekit_agent.py` | Ajouter U-AGT-3 a U-AGT-5. |
| `backend/tests/integration/voice/__init__.py` | Creer vide. |
| `backend/tests/integration/voice/test_agent_room.py` | Test I-AGT-1 marque `integration`. |
| `docs/setup/voice-realtime-windows-amd.md` | Section env vars DUR-5 + smoke test §5.3. |

**Gate de merge :** `pytest -m "not integration"` vert, ruff vert, smoke test §5.3 reussi.

---

## 5. Plan de tests

### 5.1 Tests unitaires (`pytest -m "not integration"`)

Tous utilisent `asyncio_mode = "auto"` (configure dans pyproject.toml).
Mock subprocess : `unittest.mock.patch("asyncio.create_subprocess_exec")` + `AsyncMock`
sur `communicate`.

#### `test_stt_local.py`

| # | Nom du test | Assertion cle |
|---|---|---|
| U-STT-1 | `test_build_wav_header_format` | 44 bytes, magic `RIFF`/`WAVE`/`fmt `/`data`, sample_rate=16000, data_size=len(pcm) |
| U-STT-2 | `test_transcribe_subprocess_args` | Args CLI contiennent `--language fr`, `--no-timestamps`, `-f`, `-` |
| U-STT-3 | `test_transcribe_returns_empty_on_nonzero_exit` | Subprocess returncode=1 -> `""`, pas de raise |
| U-STT-4 | `test_transcribe_returns_empty_on_timeout` | `communicate` bloque -> `asyncio.TimeoutError` interne -> `""` |
| U-STT-5 | `test_init_raises_if_bin_missing` | `Settings(whisper_bin="nonexistent.exe")` -> `FileNotFoundError` au `__init__` |
| U-STT-6 | `test_transcribe_empty_pcm_skips_subprocess` | `pcm_16k_mono=b""` -> `""` sans appel subprocess |

#### `test_tts_local.py`

| # | Nom du test | Assertion cle |
|---|---|---|
| U-TTS-1 | `test_synthesize_subprocess_args` | Args contiennent `--output_raw`, `--model <piper_voice>` |
| U-TTS-2 | `test_synthesize_text_to_stdin` | `communicate(b"Bonjour")` appele avec le texte encode UTF-8 |
| U-TTS-3 | `test_synthesize_returns_empty_on_nonzero_exit` | returncode=1 -> `b""` |
| U-TTS-4 | `test_synthesize_empty_text_skips_subprocess` | `text=""` -> `b""` sans subprocess |
| U-TTS-5 | `test_init_raises_if_voice_missing` | `Settings(piper_voice="nonexistent.onnx")` -> `FileNotFoundError` |

#### `test_livekit_agent.py`

| # | Nom du test | Assertion cle |
|---|---|---|
| U-AGT-1 | `test_build_worker_options_type` | `build_worker_options(settings, mock_llm)` retourne instance `WorkerOptions` |
| U-AGT-2 | `test_on_enter_no_raise` | `agent.on_enter()` s'execute sans exception avec STT/LLM/TTS mocks |
| U-AGT-3 | `test_handle_turn_empty_transcript_skips_llm` | STT mock retourne `""` -> `LocalLLM.generate` non appele |
| U-AGT-4 | `test_handle_turn_calls_pipeline_in_order` | STT->"bonjour", LLM->"Salut", TTS->1024 bytes. Assert ordre STT < LLM < TTS < `capture_frame` |
| U-AGT-5 | `test_llm_lock_serializes_concurrent_calls` | Deux `generate()` via `asyncio.gather()`. LLM mock dure 0.05s. Assert calls serielises (timestamps non-overlappants). |

### 5.2 Tests integration (LiveKit Docker + modeles locaux)

Marques `@pytest.mark.integration`. Exclus du CI par `pytest -m "not integration"`.

**`test_agent_room.py` — I-AGT-1 : end-to-end one-shot**

```
Prerequis :
  - docker compose -f infra/livekit/docker-compose.yml up -d
  - Tous les binaires et modeles DUR-5 presents a leurs chemins
  - LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET dans l'env

Setup :
  1. Mint deux AccessToken (roles : agent, test-client) via livekit-api.
  2. Lancer asyncio.create_task(entrypoint(ctx_mock)) avec ctx bouchonne.
  3. Connecter un second client Python (livekit.rtc.Room + token test-client).
  4. Publier un AudioTrack depuis tests/fixtures/bonjour_shugu.wav
     (WAV 3s, 48 kHz mono, "Bonjour Shugu, comment tu vas ?").
  5. Souscrire au track audio de l'agent.
  6. Accumuler les frames Shugu pendant 15s max (asyncio.wait_for).

Assertions :
  assert len(frames_recus) > 0,  "Shugu n'a pas publie de frame audio"
  ttfb_ms = (t_premier_frame_shugu - t_dernier_frame_input) * 1000
  assert ttfb_ms < 2000, f"TTFB trop eleve : {ttfb_ms:.0f} ms"

Teardown :
  await room_test.disconnect()
  await agent_room.disconnect()

Note : ce test est l'unique oracle end-to-end reel.
Ne pas inclure dans le gate de merge automatique CI.
```

### 5.3 Smoke test manuel (machine Windows user)

```powershell
# -- Etape 1 : LiveKit Docker --
cd F:\Dev\Fork\Shugu_stream\infra\livekit
docker compose up -d
# Verifier : docker logs <container_id> | Select-String "server started"

# -- Etape 2 : llama-server Vulkan --
& F:\Dev\Fork\Shugu_stream\infra\llama\start-llama-server.ps1
# Attendre dans les logs :
#   "registered backend Vulkan"  <- OBLIGATOIRE. Si absent : wheel CPU-only -> rebuild
#   "llama server listening"

# -- Etape 3 : variables d'environnement --
$env:SHUGU_ENV             = "dev"
$env:SHUGU_JWT_SECRET      = "devsecret_local_only"
$env:SHUGU_USER_JWT_SECRET = "devsecret_local_only"
$env:SHUGU_IP_HASH_SALT    = "devsalt_local_only"
$env:LIVEKIT_URL           = "ws://localhost:7880"
$env:LIVEKIT_API_KEY       = "devkey"
$env:LIVEKIT_API_SECRET    = "devsecret"
$env:WHISPER_BIN           = "E:\ai\tools\whisper.cpp\build\bin\whisper-cli.exe"
$env:WHISPER_MODEL         = "E:\ai\models\whisper\ggml-base.bin"
$env:PIPER_BIN             = "E:\ai\tools\piper\piper.exe"
$env:PIPER_VOICE           = "E:\ai\models\piper\fr_FR-siwis-medium.onnx"
$env:VOICE_AGENT_ENABLED   = "true"
$env:LOG_FORMAT            = "pretty"

# -- Etape 4 : lancer le worker standalone (sans FastAPI) --
cd F:\Dev\Fork\Shugu_stream\backend
python -m shugu.voice.livekit_agent
# Log attendu immediat : "voice.session.start"

# -- Etape 5 : parler depuis le browser --
# Ouvrir : https://agents-playground.livekit.io/
# Server URL  = ws://localhost:7880
# API Key     = devkey
# API Secret  = devsecret
# Connect -> autoriser micro -> parler en francais

# -- Criteres de succes --
# Logs worker dans l'ordre, sans ERROR :
#   voice.stt.transcribed    text="..."
#   voice.llm.response       length=<n>
#   voice.tts.synthesized    pcm_bytes=<n>
#   voice.tts.published      frames=<n>
# Audio Shugu audible dans le browser en ~500 ms
# Second tour de parole fonctionne sans restart
# Ctrl+C -> "voice.session.shutdown" + "voice.session.end" (pas d'orphan process)
```

---
## 6. Risques techniques

### 6.1 Thread-safety LocalLLM (asyncio.Lock)

**Risque :** `llama-cpp-python` n'est pas reentrant. Deux coroutines appelant
`create_chat_completion` en parallele sur le meme objet `Llama` produisent une
corruption memoire silencieuse ou un segfault.

**Mitigation Sprint B :** `asyncio.Lock` dans `LocalLLM.__init__` ; `async with self._lock`
dans `generate()` avant `run_in_executor`. Sprint B est single-speaker donc la
concurrence ne se produit jamais, mais le lock est pose maintenant pour eviter une
regression Sprint D.

**Mitigation Sprint D :** Le barge-in demandera d'annuler la tache LLM en cours
(`asyncio.Task.cancel()`) pour liberer le lock, puis relancer `generate()` avec le
nouveau contexte. La FSM Sprint D gere ce cas via l'etat `INTERRUPTED`.

**Regle coder :** Toute methode future appelant `self._llm.create_chat_completion` ou
`self._llm.create_completion` doit etre protegee par `async with self._lock` sans
exception. Ce pattern sera verifie en code review PR2.

---

### 6.2 Backpressure audio frames

**Risque :** Le traitement STT+LLM+TTS prend ~500 ms pendant que les frames
arrivent a 50 fps (1 frame/20 ms). Sans controle, le buffer grossit -> OOM lente.

**Mitigation Sprint B :** Drapeau `self._processing: bool`.

- `False` (etat LISTENING) : frames accumules dans `buffer`.
- `True` (etat PROCESSING) : frames droppees. Log `voice.audio.dropped` + compteur.
- Remis a `False` dans un bloc `finally` de `_handle_turn()`, meme sur erreur.
- Borne max buffer : si duree > 30s, tronquer et transcrire immediatement
  (evite le timeout subprocess whisper).

**Compatibilite Sprint D :** Le drapeau sera remplace par la FSM (etats LISTENING /
THINKING / SPEAKING). Pattern identique, migration sans casse.

---

### 6.3 Clean shutdown SIGINT / SIGTERM sur Windows

**Risque :** Ctrl+C dans PowerShell envoie `SIGINT`. Les subprocesses
`whisper-cli.exe` et `piper.exe` en cours deviennent orphelins si Python ne les
gere pas explicitement.

**Mitigation :** `ctx.add_shutdown_callback(_on_shutdown)` dans `entrypoint()`.

Sequence d'arret pour chaque subprocess actif :

```python
async def _on_shutdown(self) -> None:
    log.info("voice.session.shutdown")
    for proc_ref in (self._active_stt_proc, self._active_tts_proc):
        if proc_ref is None:
            continue
        proc_ref.terminate()              # TerminateProcess Win32 — propre
        try:
            await asyncio.wait_for(proc_ref.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            proc_ref.kill()               # SIGKILL garanti — dernier recours
            await proc_ref.wait()
    await self._audio_source.aclose()
    log.info("voice.session.end")
```

References `_active_stt_proc` / `_active_tts_proc` affectees avant `communicate()`,
remises a `None` apres `proc.wait()`. Shutdown verifie `is not None` avant `terminate()`.

**Regle coder :** Ne jamais appeler `proc.kill()` directement sans essayer
`proc.terminate() + asyncio.wait_for(proc.wait(), 2.0)` en premier.

---

### 6.4 Build Vulkan llama-cpp-python (verification au demarrage)

**Risque :** Le wheel PyPI par defaut est CPU-only. Si installe sans `CMAKE_ARGS`,
la generation tourne a 1 tok/s silencieusement. Aucune erreur n'est levee.

**Mitigation :** `_ensure_loaded()` met `verbose=True` au premier chargement.
Le log doit contenir la ligne `"register_backend: registered backend Vulkan"`.
Si cette ligne est absente, le coder doit logger un WARNING explicite et
conseiller de rebuilder le wheel avec les flags Vulkan.

Build correct :

```powershell
$env:CMAKE_ARGS = "-DGGML_VULKAN=on"
pip install llama-cpp-python==0.3.22 --no-binary llama-cpp-python --force-reinstall
```

---

### 6.5 Point d'attention app.py wiring (Worker.run())

**Risque :** `agents.cli.run_app()` est concu pour `__main__` — il appelle `sys.exit()`
en fin d'execution. Ne pas l'utiliser dans un lifespan FastAPI.

**Alternative correcte :** `agents.Worker(opts).run()` qui est une coroutine asyncio
sans `sys.exit()`. Verifier que cette API est exposee dans livekit-agents 1.5.5
avant d'ecrire le lifespan. Si `Worker` n'est pas accessible directement, le coder
documente dans le PR le workaround utilise.

---

## 7. Dependances pip exactes

### Ajouts dans `[project.dependencies]` (core)

```toml
# Sprint B — LiveKit Agent worker + VAD Silero
# Versions verifiees sur la machine dev 2026-05-04 :
#   livekit-agents == 1.5.5  (confirme python -c "import livekit.agents; print(agents.__version__)")
#   livekit-plugins-silero == 1.5.5
#   livekit (rtc SDK) == 1.1.5  (dependance transitive, ne pas declarer separement)
"livekit-agents>=1.5,<2.0",
"livekit-plugins-silero>=1.5,<2.0",

# Sprint B — LLM local Vulkan AMD
# IMPORTANT : le wheel PyPI par defaut est CPU-only.
# Build Vulkan requis (voir §6.4).
# La contrainte ici documente la version cible et bloque les upgrades accidentels.
"llama-cpp-python>=0.3.22,<0.4.0",
```

### Deplacement `faster-whisper` en extra optionnel

```toml
[project.optional-dependencies]
dev = [
    # ...inchange...
]

# faster-whisper deplace hors du core — jamais importe dans shugu/ (verifie grep).
# Incompatible avec whisper.cpp Vulkan AMD Windows natif (pull CTranslate2 + torch CUDA).
# Garde pour compatibilite eventuelle VPS Linux CUDA (path alternatif futur).
cloud-stt = [
    "faster-whisper>=1.0,<2.0",
]
```

### Ce qui n'est PAS a ajouter

| Package | Raison |
|---|---|
| `livekit-api` | deja core (`>=1.0,<2.0`, v1.1.0 installee) |
| `livekit` / `livekit-rtc` | dependance transitive de `livekit-agents` |
| `numpy` | deja core (`>=1.26,<3.0`) |
| `scipy` | non requis — `rtc.AudioResampler` couvre les deux resamplings |
| `livekit-plugins-turn-detector` | Sprint D uniquement |
| `webrtcvad-wheels` | conserver en core (usage potentiel autres chemins audio) |

---

## 8. Champs `Settings` a ajouter dans `backend/shugu/config.py`

Le coder remplace les quatre champs existants `whisper_bin/model/piper_bin/voice`
(actuellement `str = ""`) par les definitions ci-dessous et ajoute `voice_agent_enabled`.

```python
# Voice realtime Sprint B — chemins binaires locaux (decisions DUR-5)
# Defaults = chemins machine dev Windows user (jamais hardcodes en prod, toujours .env).
# AliasChoices accepte les deux noms d'env pour retrocompatibilite.
whisper_bin: str = Field(
    default="E:/ai/tools/whisper.cpp/build/bin/whisper-cli.exe",
    validation_alias=AliasChoices("WHISPER_BIN", "WHISPER_CLI_PATH"),
    description="Chemin vers whisper-cli.exe (build Vulkan AMD). "
                "Env: WHISPER_BIN ou WHISPER_CLI_PATH.",
)
whisper_model: str = Field(
    default="E:/ai/models/whisper/ggml-base.bin",
    validation_alias=AliasChoices("WHISPER_MODEL", "WHISPER_MODEL_PATH"),
    description="Chemin vers le modele ggml whisper (.bin). "
                "Env: WHISPER_MODEL ou WHISPER_MODEL_PATH.",
)
piper_bin: str = Field(
    default="E:/ai/tools/piper/piper.exe",
    validation_alias=AliasChoices("PIPER_BIN", "PIPER_BIN_PATH"),
    description="Chemin vers piper.exe (ONNX CPU). "
                "Env: PIPER_BIN ou PIPER_BIN_PATH.",
)
piper_voice: str = Field(
    default="E:/ai/models/piper/fr_FR-siwis-medium.onnx",
    validation_alias=AliasChoices("PIPER_VOICE", "PIPER_VOICE_PATH"),
    description="Chemin vers le modele ONNX Piper (.onnx). "
                "Env: PIPER_VOICE ou PIPER_VOICE_PATH.",
)
voice_agent_enabled: bool = Field(
    default=False,
    validation_alias=AliasChoices("VOICE_AGENT_ENABLED", "SHUGU_VOICE_AGENT_ENABLED"),
    description="Active le LiveKit Agent worker voice dans le lifespan FastAPI (DUR-1). "
                "OFF par defaut. Opt-in via SHUGU_VOICE_AGENT_ENABLED=true. "
                "Si False : LocalLLM voice non instanciee (zero impact VRAM).",
)
```

---

## 9. Wiring in-process `app.py` (DUR-1)

A ajouter dans le lifespan de `backend/shugu/app.py`, apres l'init Redis,
avant le `yield` :

```python
_voice_worker_task: asyncio.Task | None = None

if settings.voice_agent_enabled:
    from .voice.llm_local import LocalLLM as VoiceLLM
    from .voice.livekit_agent import build_worker_options
    import livekit.agents as _lk_agents

    _voice_llm_instance = VoiceLLM(settings)
    # Lazy : le modele n'est pas charge ici (charge au 1er appel generate())
    _worker_opts = build_worker_options(settings, _voice_llm_instance)

    # Note : agents.cli.run_app() appelle sys.exit() -> INTERDIT dans un lifespan.
    # Utiliser agents.Worker(opts).run() a la place.
    # A verifier dans livekit-agents 1.5.5 avant d'ecrire cette ligne.
    # Si Worker.run() n'est pas expose publiquement, le coder documente le workaround.
    _voice_worker_task = asyncio.create_task(
        _lk_agents.Worker(_worker_opts).run()
    )
    log.info("voice.agent.started")

yield   # lifespan

if _voice_worker_task is not None:
    _voice_worker_task.cancel()
    try:
        await asyncio.wait_for(_voice_worker_task, timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    log.info("voice.agent.stopped")
```

---

## 10. Hors scope Sprint B — ne pas implementer

| Element | Sprint cible |
|---|---|
| Streaming TTS (`synthesize_stream`, chunker prosodique) | C |
| FSM barge-in (7 etats : IDLE/LISTENING/THINKING/SPEAKING/INTERRUPTED/YIELDING/STUBBORN) | D |
| Fillers acoustiques pre-rendus (`models/piper/fillers/`) | D |
| Turn detector plugin (`livekit-plugins-turn-detector`) | D |
| Tool calls LLM reels (web_search, avatar_control) | C / H |
| Regie/prompt_builder.py (prompt augmente web context) | C |
| Audio bridge listener_ws (mode live/private) | E |
| Recording LiveKit Egress + Postgres `voice_sessions` | G |
| Raise-hand UX + admin moderation | F |
| Metriques Prometheus voice (`shugu_voice_e2e_latency_ms`, etc.) | H |
| Lip-sync viseme data_track parallele | Sprint post-E |

---

Blueprint final — pret pour coder