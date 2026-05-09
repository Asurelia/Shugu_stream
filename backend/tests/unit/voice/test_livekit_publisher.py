"""Tests unitaires pour LiveKitPublisher (D-1).

Wrapper Python autour de LocalAudioTrack LiveKit qui publie du PCM Piper
en AudioFrames de 10 ms vers une room LiveKit.

API LiveKit ciblée (vérifiée sur livekit-rtc 1.5.5) :
- ``rtc.AudioSource(sample_rate, num_channels)`` créé une fois, pousse
  les frames via ``capture_frame(AudioFrame)``.
- ``rtc.LocalAudioTrack.create_audio_track(name, source)`` créé une fois.
- ``room.local_participant.publish_track(track, options)`` appelé UNE fois
  pour publier la track. Renvoie un ``LocalTrackPublication``.
- ``room.local_participant.unpublish_track(track_sid)`` prend le ``sid``
  (string), pas l'objet track.

Conséquences pour les tests :
- ``publish_pcm`` créé la chaîne (AudioSource + Track + publish) au PREMIER
  appel uniquement → ``publish_track.call_count == 1`` même après plusieurs
  ``publish_pcm``.
- Découpage PCM en frames de 10 ms : ``capture_frame.call_count`` = nombre
  de frames complets contenus dans le PCM.
- Reconnect exponentiel s'applique à ``publish_track`` (échec d'init de
  publication) — pas à ``capture_frame`` (best-effort, on log + drop).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit import rtc

from shugu.config import Settings
from shugu.voice.livekit_publisher import LiveKitPublisher

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Path) -> Settings:
    """Settings minimaliste pour tests (env=test → contournes les validators prod)."""
    return Settings(
        env="test",
        shugu_jwt_secret="x",
        user_jwt_secret="x",
        ip_hash_salt="x",
        livekit_url="ws://localhost:7880",
        livekit_api_key="testkey",
        livekit_api_secret="testsecret",
    )


def _make_mock_room() -> MagicMock:
    """Construit un mock ``rtc.Room`` avec ``local_participant`` complet.

    - ``publish_track`` async, retourne un mock publication.
    - ``unpublish_track`` async, no-op.
    - ``isconnected`` retourne True par défaut (room saine).
    """
    room = MagicMock(spec=rtc.Room)
    room.isconnected = MagicMock(return_value=True)

    publication = MagicMock()
    publication.sid = "TR_publication_sid"

    local_participant = MagicMock(spec=rtc.LocalParticipant)
    local_participant.publish_track = AsyncMock(return_value=publication)
    local_participant.unpublish_track = AsyncMock(return_value=None)
    room.local_participant = local_participant

    return room


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return _make_settings(tmp_path)


@pytest.fixture
def mock_room() -> MagicMock:
    return _make_mock_room()


@pytest.fixture(autouse=True)
def _patch_audio_primitives():
    """Patche AudioSource + LocalAudioTrack.create_audio_track pour isoler les tests.

    Sans ce patch, AudioSource() tente d'allouer des ressources natives FFI
    qui ne sont pas dispo en environnement test (CI Linux sans LiveKit C SDK).
    """
    fake_source = MagicMock(spec=rtc.AudioSource)
    fake_source.capture_frame = AsyncMock(return_value=None)
    fake_source.aclose = AsyncMock(return_value=None)
    fake_source.clear_queue = MagicMock(return_value=None)
    fake_source.sample_rate = 22_050
    fake_source.num_channels = 1

    fake_track = MagicMock(spec=rtc.LocalAudioTrack)
    fake_track.sid = "TR_track_sid_local"

    with patch(
        "shugu.voice.livekit_publisher.rtc.AudioSource",
        return_value=fake_source,
    ) as audio_source_cls, patch(
        "shugu.voice.livekit_publisher.rtc.LocalAudioTrack.create_audio_track",
        return_value=fake_track,
    ) as create_track_fn:
        yield {
            "audio_source_cls": audio_source_cls,
            "create_track_fn": create_track_fn,
            "fake_source": fake_source,
            "fake_track": fake_track,
        }


# ---------------------------------------------------------------------------
# Initialisation + invariants
# ---------------------------------------------------------------------------


def test_init_no_publish_yet(settings: Settings, mock_room: MagicMock) -> None:
    """À l'init, aucune ressource LiveKit n'est créée et aucun track publié.

    Permet d'instancier le publisher avant d'avoir un audio à pousser, ce
    qui simplifie le wiring dans audio_bridge (Sprint D-2).
    """
    publisher = LiveKitPublisher(settings, mock_room)
    assert publisher.chunk_started_at_ms is None
    mock_room.local_participant.publish_track.assert_not_called()


def test_native_sample_rate_constant(settings: Settings, mock_room: MagicMock) -> None:
    """NATIVE_SAMPLE_RATE doit valoir 22050 (Piper fr_FR-siwis-medium)."""
    assert LiveKitPublisher.NATIVE_SAMPLE_RATE == 22_050


# ---------------------------------------------------------------------------
# publish_pcm — chaîne nominale
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_pcm_creates_source_and_track_once(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """Premier publish_pcm crée AudioSource + LocalAudioTrack + publish_track.

    Deuxième appel réutilise les mêmes objets (publish_track.call_count == 1).
    """
    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 22_050  # 1 s @ 22050 Hz s16le mono = 44100 bytes

    await publisher.publish_pcm(pcm)
    assert _patch_audio_primitives["audio_source_cls"].call_count == 1
    assert _patch_audio_primitives["create_track_fn"].call_count == 1
    assert mock_room.local_participant.publish_track.call_count == 1

    await publisher.publish_pcm(pcm)
    # Réutilisation : aucun nouveau publish.
    assert _patch_audio_primitives["audio_source_cls"].call_count == 1
    assert _patch_audio_primitives["create_track_fn"].call_count == 1
    assert mock_room.local_participant.publish_track.call_count == 1


@pytest.mark.asyncio
async def test_publish_pcm_capture_frame_count_matches_10ms_frames(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """1 s de PCM @ 22050 Hz → 100 frames de 10 ms exactement.

    22050 * 0.01 = 220.5 samples → on tronque à 220 samples / frame.
    1 s = 22050 samples = 100 * 220 + 50 reste → 100 frames complets,
    50 samples résiduels droppés (cf. TestFrameSlicing pour la décision).
    """
    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 22_050  # 1 s

    await publisher.publish_pcm(pcm)

    fake_source = _patch_audio_primitives["fake_source"]
    assert fake_source.capture_frame.call_count == 100, (
        f"Expected 100 frames (1s/10ms), got {fake_source.capture_frame.call_count}"
    )


@pytest.mark.asyncio
async def test_publish_pcm_audio_frame_metadata(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """Chaque AudioFrame poussé doit avoir sample_rate=22050, channels=1, samples_per_channel=220."""
    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 4_410  # 200 ms @ 22050 → 20 frames

    await publisher.publish_pcm(pcm)

    fake_source = _patch_audio_primitives["fake_source"]
    assert fake_source.capture_frame.call_count == 20

    # Inspecte le premier frame poussé.
    first_call = fake_source.capture_frame.call_args_list[0]
    frame: rtc.AudioFrame = first_call.args[0]
    assert isinstance(frame, rtc.AudioFrame)
    assert frame.sample_rate == 22_050
    assert frame.num_channels == 1
    assert frame.samples_per_channel == 220  # 22050 * 0.01 = 220.5 → 220
    # data length = samples_per_channel * channels * 2 (s16le)
    assert len(bytes(frame.data)) == 220 * 1 * 2


@pytest.mark.asyncio
async def test_publish_pcm_drops_residual_partial_frame(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """PCM dont la longueur n'est pas un multiple d'un frame → on drop le résidu.

    Décision : éviter de pousser un frame incomplet ou padder avec silence
    (qui introduirait un click). Le résidu (<10 ms) est inaudible et sera
    couvert par le frame suivant en streaming.
    """
    publisher = LiveKitPublisher(settings, mock_room)
    # 220 samples × 3.5 frames = 770 samples = 1540 bytes (3 frames + résidu).
    pcm = b"\x00\x01" * 770

    await publisher.publish_pcm(pcm)

    fake_source = _patch_audio_primitives["fake_source"]
    assert fake_source.capture_frame.call_count == 3  # résidu de 110 samples droppé


@pytest.mark.asyncio
async def test_publish_pcm_empty_pcm_is_noop(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """PCM vide : pas d'erreur, pas de publish, chunk_started_at_ms reste None."""
    publisher = LiveKitPublisher(settings, mock_room)

    await publisher.publish_pcm(b"")

    assert publisher.chunk_started_at_ms is None
    mock_room.local_participant.publish_track.assert_not_called()
    fake_source = _patch_audio_primitives["fake_source"]
    fake_source.capture_frame.assert_not_called()


@pytest.mark.asyncio
async def test_publish_pcm_zero_sample_rate_is_noop(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """sample_rate=0 : guard early return, pas de ZeroDivisionError propagée.

    Sans la guard, ``samples_per_frame = 0`` → ``bytes_per_frame = 0`` →
    ``len(pcm) // 0`` lève ``ZeroDivisionError`` en dehors du try/except.
    Spec §6.1 mandate "pas de propagation d'exception au caller".
    """
    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 22_050

    # Ne doit pas raise.
    await publisher.publish_pcm(pcm, sample_rate=0)

    assert publisher.chunk_started_at_ms is None
    mock_room.local_participant.publish_track.assert_not_called()
    fake_source = _patch_audio_primitives["fake_source"]
    fake_source.capture_frame.assert_not_called()


@pytest.mark.asyncio
async def test_publish_pcm_low_sample_rate_below_100hz_is_noop(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """sample_rate < 100 Hz : ``samples_per_frame = int(99 * 0.01) = 0`` → guard.

    Cas limite : caller passerait 50 Hz (impossible Piper, mais possible bug
    upstream — un mauvais Settings). On ne crash pas, on log + drop.
    """
    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 22_050

    # Ne doit pas raise.
    await publisher.publish_pcm(pcm, sample_rate=50)

    assert publisher.chunk_started_at_ms is None
    mock_room.local_participant.publish_track.assert_not_called()


@pytest.mark.asyncio
async def test_publish_pcm_pcm_shorter_than_one_frame(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """PCM < 10 ms : on ne pousse aucun frame complet, mais on ne crash pas.

    NB : on appelle quand même publish_track pour matérialiser la track —
    sinon le caller voit un état incohérent (chunk_started_at_ms reste None,
    pas de side-effect observable). On ouvre le pipeline pour le prochain
    appel utile.
    """
    publisher = LiveKitPublisher(settings, mock_room)
    # 100 samples = 200 bytes → moins qu'un frame de 220 samples.
    pcm = b"\x00\x01" * 100

    await publisher.publish_pcm(pcm)

    fake_source = _patch_audio_primitives["fake_source"]
    fake_source.capture_frame.assert_not_called()
    # chunk_started_at_ms reste None car aucun frame poussé.
    assert publisher.chunk_started_at_ms is None


# ---------------------------------------------------------------------------
# chunk_started_at_ms — horloge monotonic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chunk_started_at_ms_initially_none(
    settings: Settings, mock_room: MagicMock
) -> None:
    """Avant tout publish, chunk_started_at_ms vaut None."""
    publisher = LiveKitPublisher(settings, mock_room)
    assert publisher.chunk_started_at_ms is None


@pytest.mark.asyncio
async def test_chunk_started_at_ms_set_on_first_frame(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """chunk_started_at_ms est set au monotonic_ms du PREMIER frame d'un appel publish_pcm."""
    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 22_050

    assert publisher.chunk_started_at_ms is None
    await publisher.publish_pcm(pcm)
    assert publisher.chunk_started_at_ms is not None
    assert isinstance(publisher.chunk_started_at_ms, int)
    assert publisher.chunk_started_at_ms > 0


@pytest.mark.asyncio
async def test_chunk_started_at_ms_updates_each_call(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """Chaque publish_pcm met à jour chunk_started_at_ms.

    Permet à event_bus (D-5) de calculer ``audio_at_ms`` relatif au début
    de la chunk audio courante — pas la première chunk de la session.
    """
    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 220  # 1 frame, ~10 ms d'audio

    await publisher.publish_pcm(pcm)
    first_ts = publisher.chunk_started_at_ms
    assert first_ts is not None

    # Pause 10 ms pour garantir un monotonic_ns différent même sur OS à
    # résolution d'horloge dégradée (Windows < 10, certains conteneurs).
    await asyncio.sleep(0.010)
    await publisher.publish_pcm(pcm)
    second_ts = publisher.chunk_started_at_ms
    assert second_ts is not None
    # Strict ``>`` : si le test flake ici, c'est que monotonic_ns a la même
    # valeur sur 2 lectures à 10 ms d'intervalle — pathologique, augmenter
    # le sleep plutôt que retomber sur ``>=`` qui masque un vrai bug.
    assert second_ts > first_ts


# ---------------------------------------------------------------------------
# unpublish — barge-in
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unpublish_calls_unpublish_track_with_sid(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """unpublish doit appeler local_participant.unpublish_track(track.sid)."""
    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 22_050

    await publisher.publish_pcm(pcm)
    await publisher.unpublish()

    mock_room.local_participant.unpublish_track.assert_awaited_once_with(
        _patch_audio_primitives["fake_track"].sid
    )


@pytest.mark.asyncio
async def test_unpublish_resets_chunk_started_at_ms(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """unpublish reset chunk_started_at_ms à None (plus de chunk en cours)."""
    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 22_050

    await publisher.publish_pcm(pcm)
    assert publisher.chunk_started_at_ms is not None

    await publisher.unpublish()
    assert publisher.chunk_started_at_ms is None


@pytest.mark.asyncio
async def test_unpublish_idempotent_no_track(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """unpublish appelé sans publish préalable ne raise pas et n'appelle rien."""
    publisher = LiveKitPublisher(settings, mock_room)

    await publisher.unpublish()
    await publisher.unpublish()

    mock_room.local_participant.unpublish_track.assert_not_called()


@pytest.mark.asyncio
async def test_unpublish_idempotent_after_publish(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """unpublish appelé deux fois après un publish n'appelle unpublish_track qu'une fois."""
    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 22_050

    await publisher.publish_pcm(pcm)
    await publisher.unpublish()
    await publisher.unpublish()

    assert mock_room.local_participant.unpublish_track.await_count == 1


@pytest.mark.asyncio
async def test_publish_pcm_after_unpublish_recreates_track(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """Après unpublish, un nouveau publish_pcm recréé la chaîne complète.

    Use case : barge-in interrompt l'audio, puis Shugu reprend la parole
    sur un nouveau tour.
    """
    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 22_050

    await publisher.publish_pcm(pcm)
    await publisher.unpublish()
    await publisher.publish_pcm(pcm)

    assert _patch_audio_primitives["audio_source_cls"].call_count == 2
    assert _patch_audio_primitives["create_track_fn"].call_count == 2
    assert mock_room.local_participant.publish_track.call_count == 2


# ---------------------------------------------------------------------------
# Reconnect exponentiel sur Room disconnected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_pcm_reconnect_succeeds_on_third_try(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """Si publish_track lève 'Room disconnected' 2 fois puis succeed → 3 essais.

    Backoff exponentiel 200/400/800 ms documenté spec §6.1. On patche
    asyncio.sleep pour ne pas attendre réellement.
    """
    publication = MagicMock()
    publication.sid = "TR_reconnect_ok"
    mock_room.local_participant.publish_track = AsyncMock(
        side_effect=[
            Exception("Room disconnected"),
            Exception("Room disconnected"),
            publication,
        ]
    )

    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 22_050

    with patch("shugu.voice.livekit_publisher.asyncio.sleep", new=AsyncMock()) as fake_sleep:
        await publisher.publish_pcm(pcm)

    assert mock_room.local_participant.publish_track.await_count == 3
    # Backoff vérifié : 200ms et 400ms (3e essai = succès, pas de sleep après).
    fake_sleep.assert_any_await(0.2)
    fake_sleep.assert_any_await(0.4)


@pytest.mark.asyncio
async def test_publish_pcm_drops_audio_after_3_reconnect_fails(
    settings: Settings, mock_room: MagicMock,
    _patch_audio_primitives: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Après 3 essais ratés sur publish_track, drop l'audio sans propager.

    Comportement best-effort : log error, retourne sans raise.
    """
    mock_room.local_participant.publish_track = AsyncMock(
        side_effect=Exception("Room disconnected")
    )

    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 22_050

    with patch("shugu.voice.livekit_publisher.asyncio.sleep", new=AsyncMock()):
        # Ne doit PAS raise.
        await publisher.publish_pcm(pcm)

    assert mock_room.local_participant.publish_track.await_count == 3
    # Aucun frame poussé (publish_track n'a jamais réussi).
    fake_source = _patch_audio_primitives["fake_source"]
    fake_source.capture_frame.assert_not_called()
    # chunk_started_at_ms reste None car aucun frame n'a été poussé.
    assert publisher.chunk_started_at_ms is None


@pytest.mark.asyncio
async def test_publish_pcm_capture_frame_exception_does_not_propagate(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """Si capture_frame raise mid-stream, on log + drop le reste, on ne propage pas.

    Audio est best-effort. On ne casse pas tout le pipeline pour un frame
    perdu mid-publish.
    """
    fake_source = _patch_audio_primitives["fake_source"]
    fake_source.capture_frame = AsyncMock(side_effect=Exception("Source closed"))

    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 22_050

    # Ne doit PAS raise.
    await publisher.publish_pcm(pcm)


# ---------------------------------------------------------------------------
# aclose — cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aclose_unpublishes_and_closes_source(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """aclose unpublish + ferme le AudioSource."""
    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 22_050

    await publisher.publish_pcm(pcm)
    await publisher.aclose()

    mock_room.local_participant.unpublish_track.assert_awaited_once()
    fake_source = _patch_audio_primitives["fake_source"]
    fake_source.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_aclose_idempotent(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """aclose appelé deux fois ne raise pas."""
    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 22_050

    await publisher.publish_pcm(pcm)
    await publisher.aclose()
    await publisher.aclose()  # second call no-op


@pytest.mark.asyncio
async def test_aclose_without_publish(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """aclose sans publish préalable ne raise pas."""
    publisher = LiveKitPublisher(settings, mock_room)
    await publisher.aclose()


# ---------------------------------------------------------------------------
# Concurrence : publish + unpublish en parallèle (barge-in race)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unpublish_during_publish_pcm_is_safe(
    settings: Settings, mock_room: MagicMock, _patch_audio_primitives: dict[str, Any]
) -> None:
    """unpublish concurrent avec publish_pcm ne corrompt pas l'état.

    Use case : VAD détecte parole user → interrupt_handler appelle unpublish
    pendant qu'audio_bridge est encore en train de pousser des frames.
    Le publisher doit terminer proprement sans laisser un track fantôme.
    """
    publisher = LiveKitPublisher(settings, mock_room)
    pcm = b"\x00\x01" * 22_050

    publish_task = asyncio.create_task(publisher.publish_pcm(pcm))
    # Yield pour laisser publish_task créer la track.
    await asyncio.sleep(0)
    await publisher.unpublish()
    # publish_task continue en arrière-plan, sans raise.
    await publish_task

    # Au final : track unpublished, état nettoyé.
    assert publisher.chunk_started_at_ms is None
