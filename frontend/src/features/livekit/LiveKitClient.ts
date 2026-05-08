/**
 * LiveKitClient — wrapper bas niveau autour de `livekit-client` Room.
 *
 * Sprint D PR D-6 (voice-body pipeline) : ce wrapper consomme l'audio track
 * publié par le backend `LiveKitPublisher` (PR D-1 backend) et expose un
 * `HTMLAudioElement` détaché du DOM via le callback `onAudioTrack`. Le caller
 * (LiveKitProvider) branche cet élément sur le `lipSync.attachMediaElement`
 * du viewer pour driver les blendshapes mouth de l'avatar VRM.
 *
 * Design notes :
 *  - On NE met PAS l'`<audio>` dans le DOM. La sortie son passe par le graph
 *    AudioContext de lipSync (`createMediaElementSource(audio).connect(...)`).
 *    Le HTMLAudioElement sert d'adapter MediaStream → AudioContext, pas de
 *    sortie visible ou audible directe.
 *  - Reconnect : `livekit-client` gère le reconnect automatique (built-in
 *    backoff exponentiel). On ne ré-implémente pas — on relaie juste les
 *    callbacks Reconnecting/Reconnected pour que l'UI puisse afficher un
 *    indicateur "reconnexion en cours".
 *  - Idempotence : `connect()` appelé deux fois est un no-op (return immédiat
 *    si la Room existe). `disconnect()` avant connect() est aussi no-op.
 *
 * Référence spec : docs/specs/2026-05-08-voice-body-pipeline-design.md §3.2.
 */

import {
  RemoteAudioTrack,
  Room,
  RoomEvent,
  Track,
  type DisconnectReason,
  type RemoteParticipant,
  type RemoteTrackPublication,
  type RemoteTrack,
} from "livekit-client";

/** Options de configuration du LiveKitClient. */
export interface LiveKitClientOptions {
  /** URL WSS du serveur LiveKit, ex `wss://livekit.example.com`. */
  url: string;
  /** JWT viewer-token issu par le backend. */
  token: string;
  /**
   * Callback invoqué lorsqu'une RemoteAudioTrack est subscribed.
   * Le `HTMLAudioElement` est créé par `track.attach()` et n'est PAS inséré
   * dans le DOM — il sert d'input au pipeline AudioContext (lipSync).
   */
  onAudioTrack?: (track: RemoteAudioTrack, audio: HTMLAudioElement) => void;
  /** Callback fire-and-forget sur RoomEvent.Connected. */
  onConnected?: () => void;
  /**
   * Callback fire-and-forget sur RoomEvent.Disconnected.
   * `reason` est l'enum `DisconnectReason` de `@livekit/protocol` côté SDK.
   * Pour un usage UI simple, on peut le stringifier (`String(reason)`).
   */
  onDisconnected?: (reason?: DisconnectReason) => void;
  /** Callback fire-and-forget sur RoomEvent.Reconnecting (UI peut griser). */
  onReconnecting?: () => void;
  /** Callback fire-and-forget sur RoomEvent.Reconnected. */
  onReconnected?: () => void;
}

/**
 * Wrapper autour de `livekit-client` Room.
 *
 * Lifecycle :
 *   1. `new LiveKitClient(opts)` — capture des callbacks, pas de connexion.
 *   2. `await client.connect()` — ouvre la Room, subscribe aux events, appelle
 *      `Room.connect(url, token)`.
 *   3. Quand un audio track distant arrive, `onAudioTrack` est invoqué avec un
 *      `HTMLAudioElement` que le caller peut passer à `lipSync`.
 *   4. `client.disconnect()` — ferme la Room et reset l'état interne.
 */
export class LiveKitClient {
  private readonly _options: LiveKitClientOptions;
  private _room: Room | null = null;

  public constructor(options: LiveKitClientOptions) {
    this._options = options;
  }

  /**
   * Ouvre la Room et s'abonne aux events. Idempotent : appelé 2 fois → no-op.
   *
   * En cas d'échec de `Room.connect`, l'erreur est ré-levée pour que le caller
   * (Provider) puisse afficher un état d'erreur. La Room interne est laissée
   * non-null pour éviter une seconde tentative silencieuse — le caller doit
   * `disconnect()` puis `connect()` pour retry.
   */
  public async connect(): Promise<void> {
    if (this._room) {
      return;
    }
    const room = new Room();
    this._room = room;

    // Wire les events AVANT le connect : un track peut arriver très tôt après
    // la handshake selon la latence du serveur.
    room.on(RoomEvent.TrackSubscribed, this._handleTrackSubscribed);
    room.on(RoomEvent.Connected, this._handleConnected);
    room.on(RoomEvent.Disconnected, this._handleDisconnected);
    room.on(RoomEvent.Reconnecting, this._handleReconnecting);
    room.on(RoomEvent.Reconnected, this._handleReconnected);

    await room.connect(this._options.url, this._options.token);
  }

  /** Ferme la Room et reset l'état. No-op si jamais connect(). */
  public disconnect(): void {
    if (!this._room) return;
    try {
      // `disconnect()` est async côté livekit-client mais on ne block pas le
      // caller : le cleanup React unmount doit rester synchrone.
      void this._room.disconnect();
    } finally {
      this._room = null;
    }
  }

  /** True si la Room est en état "connected". False sinon (incl. reconnecting). */
  public isConnected(): boolean {
    return this._room?.state === "connected";
  }

  /** Pour debug / tests : retourne l'instance Room ou null. */
  public getRoom(): Room | null {
    return this._room;
  }

  // ─── Handlers ───────────────────────────────────────────────────────────

  private _handleTrackSubscribed = (
    track: RemoteTrack,
    _publication: RemoteTrackPublication,
    _participant: RemoteParticipant,
  ): void => {
    if (track.kind !== Track.Kind.Audio) {
      // Video / data ignorés en D-6. Le viewer ne consomme que l'audio TTS.
      return;
    }
    const audioTrack = track as RemoteAudioTrack;
    // `attach()` sans argument crée un HTMLAudioElement détaché, pas inséré
    // dans le DOM. C'est exactement ce qu'on veut : la sortie passe par le
    // graph AudioContext de lipSync, pas par la balise <audio>.
    const audioElement = audioTrack.attach() as HTMLAudioElement;
    this._options.onAudioTrack?.(audioTrack, audioElement);
  };

  private _handleConnected = (): void => {
    this._options.onConnected?.();
  };

  private _handleDisconnected = (reason?: DisconnectReason): void => {
    this._options.onDisconnected?.(reason);
  };

  private _handleReconnecting = (): void => {
    this._options.onReconnecting?.();
  };

  private _handleReconnected = (): void => {
    this._options.onReconnected?.();
  };
}
