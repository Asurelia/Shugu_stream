"""Tests unitaires pour ``AudioBridge`` (D-2).

L'AudioBridge est le pont entre ``PiperTTS`` (synthèse vocale streaming) et
``LiveKitPublisher`` (transport WebRTC). Pour chaque phrase produite par le
LLM, on synthétise du PCM s16le 22050 Hz mono via Piper, puis on pousse les
bytes sur la track LiveKit en frames AudioFrame de 10 ms.

Contraintes testées :

- Best-effort : aucune méthode publique ne propage d'exception (catch + log).
- Idempotence du ``cancel`` et du ``aclose``.
- ``publish_stream`` annulable en plein milieu via ``cancel()``.
- Le flag ``_cancelled`` est reset à chaque entrée de ``publish_stream`` pour
  permettre la reprise après barge-in (test spécifique).
- ``chunk_started_at_ms`` est un pass-through pur vers le publisher (utilisé
  par event_bus D-5 pour calculer ``audio_at_ms``).

Spec : ``docs/specs/2026-05-08-voice-body-pipeline-design.md`` §3.1, §5.1, §6.1.
"""
from __future__ import annotations

from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from shugu.voice.audio_bridge import AudioBridge
from shugu.voice.livekit_publisher import LiveKitPublisher
from shugu.voice.tts_local import PiperTTS

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_tts() -> MagicMock:
    """Mock ``PiperTTS`` qui retourne 1 s de PCM par défaut.

    44100 bytes = 22050 samples × 2 bytes (s16le) × 1 channel = 1 s @ 22050 Hz.
    """
    tts = MagicMock(spec=PiperTTS)
    tts.synthesize = AsyncMock(return_value=b"\x00\x01" * 22_050)
    tts.aclose = AsyncMock(return_value=None)
    return tts


@pytest.fixture
def mock_publisher() -> MagicMock:
    """Mock ``LiveKitPublisher`` avec API complète.

    ``chunk_started_at_ms`` est un attribut MagicMock standard ici (pas une
    vraie ``property``) ; le bridge exposera la valeur via pass-through.
    """
    pub = MagicMock(spec=LiveKitPublisher)
    pub.publish_pcm = AsyncMock(return_value=None)
    pub.unpublish = AsyncMock(return_value=None)
    pub.aclose = AsyncMock(return_value=None)
    pub.chunk_started_at_ms = 1_234_567_890
    return pub


# ---------------------------------------------------------------------------
# publish_sentence — chaîne nominale + edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_sentence_calls_tts_then_publisher(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """``publish_sentence`` synthétise via Piper puis pousse le PCM au publisher.

    Le caller (audio_bridge) doit synthétiser la phrase complète puis la
    publier en un seul appel ``publish_pcm`` (le découpage en frames 10 ms
    est interne au publisher D-1).
    """
    bridge = AudioBridge(mock_tts, mock_publisher)
    await bridge.publish_sentence("Salut tout le monde !")

    mock_tts.synthesize.assert_awaited_once_with("Salut tout le monde !")
    mock_publisher.publish_pcm.assert_awaited_once()
    args, kwargs = mock_publisher.publish_pcm.call_args
    # PCM passé tel quel (pas de modif côté bridge — c'est le publisher qui découpe).
    assert args[0] == b"\x00\x01" * 22_050
    # Sample rate = NATIVE_SAMPLE_RATE Piper (par défaut OK).
    assert kwargs.get("sample_rate", LiveKitPublisher.NATIVE_SAMPLE_RATE) in (
        LiveKitPublisher.NATIVE_SAMPLE_RATE,
        None,
    )


@pytest.mark.asyncio
async def test_publish_sentence_passes_native_sample_rate(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """Le bridge transmet explicitement ``NATIVE_SAMPLE_RATE`` au publisher.

    Évite de dépendre du défaut côté publisher : si ``LiveKitPublisher
    .NATIVE_SAMPLE_RATE`` change, le bridge doit utiliser la même constante
    pour rester cohérent (Piper natif).
    """
    bridge = AudioBridge(mock_tts, mock_publisher)
    await bridge.publish_sentence("Coucou")

    _, kwargs = mock_publisher.publish_pcm.call_args
    # Soit kwargs explicite, soit positional — tolérant aux deux mais stride exact.
    expected = LiveKitPublisher.NATIVE_SAMPLE_RATE
    if "sample_rate" in kwargs:
        assert kwargs["sample_rate"] == expected
    else:
        # positional : 2e arg
        args = mock_publisher.publish_pcm.call_args.args
        assert len(args) >= 2
        assert args[1] == expected


@pytest.mark.asyncio
async def test_publish_sentence_empty_string_is_noop(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """Phrase vide : ne déclenche ni Piper ni publisher.

    Évite de gaspiller un subprocess Piper sur du vide. Comportement aligné
    avec ``PiperTTS.synthesize_stream`` qui skip déjà whitespace-only.
    """
    bridge = AudioBridge(mock_tts, mock_publisher)
    await bridge.publish_sentence("")

    mock_tts.synthesize.assert_not_called()
    mock_publisher.publish_pcm.assert_not_called()


@pytest.mark.asyncio
async def test_publish_sentence_whitespace_only_is_noop(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """Whitespace-only (espaces/tabs/newlines) : noop comme la chaîne vide."""
    bridge = AudioBridge(mock_tts, mock_publisher)
    await bridge.publish_sentence("   \t\n  ")

    mock_tts.synthesize.assert_not_called()
    mock_publisher.publish_pcm.assert_not_called()


@pytest.mark.asyncio
async def test_publish_sentence_tts_returns_empty_bytes_skips_publish(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """Si Piper retourne ``b""`` (timeout/crash via ``synthesize``), on skip publish.

    ``PiperTTS.synthesize`` retourne ``b""`` proprement sur erreur (timeout,
    nonzero exit, exception interne) — pas une exception. Le bridge doit
    juste ne pas pousser un PCM vide au publisher (qui ferait un noop de
    toute façon, mais autant éviter le call inutile).
    """
    mock_tts.synthesize.return_value = b""
    bridge = AudioBridge(mock_tts, mock_publisher)
    await bridge.publish_sentence("ok")

    mock_tts.synthesize.assert_awaited_once_with("ok")
    mock_publisher.publish_pcm.assert_not_called()


@pytest.mark.asyncio
async def test_publish_sentence_tts_raises_does_not_propagate(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """Best-effort : si ``tts.synthesize`` raise, on log + return sans propager.

    Spec §6.1 : aucune méthode publique du bridge ne doit propager d'exception
    au caller. Le pipeline voice continue malgré une phrase perdue.
    """
    mock_tts.synthesize.side_effect = RuntimeError("piper crashed")
    bridge = AudioBridge(mock_tts, mock_publisher)

    # Ne doit PAS raise.
    await bridge.publish_sentence("ok")

    mock_publisher.publish_pcm.assert_not_called()


@pytest.mark.asyncio
async def test_publish_sentence_publisher_raises_does_not_propagate(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """Best-effort : si ``publish_pcm`` raise, on log + return sans propager.

    LiveKitPublisher.publish_pcm est déjà best-effort (catch interne), mais
    une exception inattendue (ex. assertion violée, mock buggé) ne doit pas
    couler le bridge.
    """
    mock_publisher.publish_pcm.side_effect = RuntimeError("livekit dead")
    bridge = AudioBridge(mock_tts, mock_publisher)

    # Ne doit PAS raise.
    await bridge.publish_sentence("ok")


@pytest.mark.asyncio
async def test_publish_sentence_strips_whitespace_before_tts(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """La phrase est strip-ée avant de la passer à Piper.

    Aligne sur le comportement ``PiperTTS.synthesize_stream`` qui strip déjà,
    cohérent pour le pipeline streaming.
    """
    bridge = AudioBridge(mock_tts, mock_publisher)
    await bridge.publish_sentence("   Salut !   ")

    mock_tts.synthesize.assert_awaited_once_with("Salut !")


# ---------------------------------------------------------------------------
# publish_stream — itération + cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_stream_iterates_all_sentences(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """``publish_stream`` itère un AsyncIterator et publie chaque sentence.

    Le bridge doit consommer un async iterator de phrases (sortie d'un
    SentenceChunker) et appeler ``publish_sentence`` pour chacune. Pas de
    fusion / batching — on garde la granularité phrase-par-phrase pour que
    event_bus puisse tagger ``audio_at_ms`` finement.
    """

    async def gen() -> AsyncIterator[str]:
        for s in ["Salut.", "Comment ça va ?", "À plus !"]:
            yield s

    bridge = AudioBridge(mock_tts, mock_publisher)
    await bridge.publish_stream(gen())

    assert mock_tts.synthesize.await_count == 3
    assert mock_publisher.publish_pcm.await_count == 3


@pytest.mark.asyncio
async def test_publish_stream_skips_empty_sentences(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """Phrases vides/whitespace-only sont skipées (pas d'appel Piper)."""

    async def gen() -> AsyncIterator[str]:
        for s in ["", "Salut.", "   ", "Bye."]:
            yield s

    bridge = AudioBridge(mock_tts, mock_publisher)
    await bridge.publish_stream(gen())

    # Seulement 2 phrases non-vides → 2 appels.
    assert mock_tts.synthesize.await_count == 2
    assert mock_publisher.publish_pcm.await_count == 2


@pytest.mark.asyncio
async def test_publish_stream_cancelled_stops_iteration(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """Si ``cancel()`` appelé pendant ``publish_stream``, l'itération s'arrête.

    Use case : barge-in détecté pendant que le bridge pipe des phrases vers
    LiveKit. Le ``cancel()`` doit déclencher ``unpublish()`` côté publisher
    ET poser un flag qui interrompt la boucle ``publish_stream`` au prochain
    point de check.
    """

    async def gen() -> AsyncIterator[str]:
        for i in range(10):
            yield f"sentence {i}"

    bridge = AudioBridge(mock_tts, mock_publisher)

    # Mock synthesize pour cancel après la 2ème phrase.
    call_count = {"n": 0}

    async def fake_synth(s: str) -> bytes:
        call_count["n"] += 1
        if call_count["n"] == 2:
            await bridge.cancel()
        return b"\x00\x01" * 22_050

    mock_tts.synthesize.side_effect = fake_synth

    await bridge.publish_stream(gen())

    # On a publié au moins 2 (la 2e étant celle qui déclenche le cancel),
    # mais pas tous les 10. ``<= 3`` couvre le cas où le check est fait
    # APRÈS publish_sentence (donc on a peut-être publié la 3ème avant
    # de break) — implémentation acceptée tant qu'on s'arrête tôt.
    assert call_count["n"] <= 3, (
        f"Cancel a échoué à interrompre l'itération : {call_count['n']} synth calls"
    )
    assert call_count["n"] >= 2, "Au moins les 2 premières phrases doivent passer"


@pytest.mark.asyncio
async def test_publish_stream_after_cancel_resumes_fresh(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """Après un ``cancel()`` puis un nouveau ``publish_stream``, on recommence.

    Use case : barge-in interrompt le 1er stream → reset → le LLM produit un
    nouveau tour → publish_stream recommence. Le flag ``_cancelled`` doit
    être reset à l'entrée de chaque ``publish_stream`` pour ne pas bloquer
    en boucle après barge-in.
    """

    bridge = AudioBridge(mock_tts, mock_publisher)

    # 1er stream — annulé immédiatement avant d'itérer.
    await bridge.cancel()

    # 2e stream — doit fonctionner normalement.
    async def gen() -> AsyncIterator[str]:
        for s in ["Reprise.", "On continue."]:
            yield s

    await bridge.publish_stream(gen())

    assert mock_tts.synthesize.await_count == 2
    assert mock_publisher.publish_pcm.await_count == 2


@pytest.mark.asyncio
async def test_publish_stream_iterator_exception_does_not_propagate(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """Si l'AsyncIterator de phrases raise, on log + return sans propager.

    Best-effort sur tout le bridge — un crash du chunker amont ne doit pas
    fait crasher l'agent voice.
    """

    async def gen() -> AsyncIterator[str]:
        yield "Première."
        raise RuntimeError("chunker exploded")

    bridge = AudioBridge(mock_tts, mock_publisher)

    # Ne doit PAS raise.
    await bridge.publish_stream(gen())

    # La 1ère phrase a quand même été publiée avant le crash.
    assert mock_tts.synthesize.await_count == 1


@pytest.mark.asyncio
async def test_publish_stream_empty_iterator_is_noop(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """Iterator vide → noop, pas de raise."""

    async def gen() -> AsyncIterator[str]:
        if False:  # type: ignore[unreachable]
            yield ""  # pragma: no cover — make it an async generator

    bridge = AudioBridge(mock_tts, mock_publisher)
    await bridge.publish_stream(gen())

    mock_tts.synthesize.assert_not_called()
    mock_publisher.publish_pcm.assert_not_called()


# ---------------------------------------------------------------------------
# cancel — barge-in
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_calls_publisher_unpublish(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """``cancel()`` délègue au publisher pour stopper le track LiveKit."""
    bridge = AudioBridge(mock_tts, mock_publisher)
    await bridge.cancel()

    mock_publisher.unpublish.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_idempotent(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """``cancel()`` peut être appelé plusieurs fois sans erreur.

    ``LiveKitPublisher.unpublish()`` est lui-même idempotent (test D-1
    ``test_unpublish_idempotent_no_track``), donc 2 appels ne causent pas
    d'erreur. On vérifie que le bridge ne pose pas de garde inutile qui
    bloquerait le 2ᵉ appel.
    """
    bridge = AudioBridge(mock_tts, mock_publisher)
    await bridge.cancel()
    await bridge.cancel()

    # Publisher.unpublish appelé 2x (idempotent côté D-1).
    assert mock_publisher.unpublish.await_count == 2


@pytest.mark.asyncio
async def test_cancel_does_not_propagate_publisher_exception(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """Best-effort : si ``publisher.unpublish`` raise, on log + return sans propager."""
    mock_publisher.unpublish.side_effect = RuntimeError("livekit dead")
    bridge = AudioBridge(mock_tts, mock_publisher)

    # Ne doit PAS raise.
    await bridge.cancel()


# ---------------------------------------------------------------------------
# aclose — cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aclose_calls_publisher_aclose_and_tts_aclose(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """``aclose`` ferme proprement le publisher ET le tts.

    Garantit qu'aucune ressource native (subprocess Piper, AudioSource FFI
    LiveKit) ne fuit après arrêt du worker.
    """
    bridge = AudioBridge(mock_tts, mock_publisher)
    await bridge.aclose()

    mock_publisher.aclose.assert_awaited_once()
    mock_tts.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_aclose_idempotent(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """``aclose`` peut être appelé plusieurs fois sans raise."""
    bridge = AudioBridge(mock_tts, mock_publisher)
    await bridge.aclose()
    await bridge.aclose()
    # Pas d'assertion stricte sur le count — l'important est qu'aucun raise.


@pytest.mark.asyncio
async def test_aclose_continues_if_publisher_aclose_raises(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """Si ``publisher.aclose`` raise, on tente quand même ``tts.aclose``.

    Best-effort par étape : un crash sur le cleanup d'une ressource ne doit
    pas empêcher le cleanup des autres (sinon un Piper subprocess orphelin
    survit à un crash LiveKit).
    """
    mock_publisher.aclose.side_effect = RuntimeError("publisher boom")
    bridge = AudioBridge(mock_tts, mock_publisher)

    # Ne doit PAS raise.
    await bridge.aclose()

    # tts.aclose appelé malgré l'échec publisher.
    mock_tts.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_aclose_continues_if_tts_aclose_raises(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """Si ``tts.aclose`` raise, ``aclose`` ne propage pas."""
    mock_tts.aclose.side_effect = RuntimeError("piper boom")
    bridge = AudioBridge(mock_tts, mock_publisher)

    # Ne doit PAS raise.
    await bridge.aclose()

    mock_publisher.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# chunk_started_at_ms — pass-through pour event_bus D-5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chunk_started_at_ms_pass_through(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """``bridge.chunk_started_at_ms`` retourne directement la valeur du publisher.

    Consommé par event_bus (D-5) pour calculer ``audio_at_ms`` :
        audio_at_ms = monotonic_ms() - bridge.chunk_started_at_ms
    """
    mock_publisher.chunk_started_at_ms = 999_999
    bridge = AudioBridge(mock_tts, mock_publisher)

    assert bridge.chunk_started_at_ms == 999_999


@pytest.mark.asyncio
async def test_chunk_started_at_ms_pass_through_none(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """Quand le publisher n'a rien publié, ``chunk_started_at_ms`` vaut None."""
    mock_publisher.chunk_started_at_ms = None
    bridge = AudioBridge(mock_tts, mock_publisher)

    assert bridge.chunk_started_at_ms is None


@pytest.mark.asyncio
async def test_chunk_started_at_ms_updates_after_publish(
    mock_tts: MagicMock, mock_publisher: MagicMock
) -> None:
    """Le pass-through reflète l'état courant — on ne cache pas la valeur côté bridge.

    Le publisher est la source de vérité ; le bridge n'a pas son propre
    cache (sinon drift entre les 2 horloges au moindre changement publisher).
    """
    bridge = AudioBridge(mock_tts, mock_publisher)

    # Avant publication.
    mock_publisher.chunk_started_at_ms = None
    assert bridge.chunk_started_at_ms is None

    # Le publisher publie → mise à jour côté publisher.
    mock_publisher.chunk_started_at_ms = 42
    assert bridge.chunk_started_at_ms == 42

    # Le publisher reset (unpublish).
    mock_publisher.chunk_started_at_ms = None
    assert bridge.chunk_started_at_ms is None
