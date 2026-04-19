// Streaming audio player for progressive TTS chunks.
//
// The server broadcasts `performance.audio_begin` then N × `performance.audio_chunk`
// events (final=true on the last). This module assembles them into a playable
// audio element while forwarding the output through a Web Audio AnalyserNode
// so the existing `LipSync` keeps driving the VRM mouth naturally.
//
// Primary strategy: Media Source Extensions (MSE) with an `audio/mpeg` source
// buffer. Chrome/Firefox/Edge support this. Safari's MSE MP3 support is
// historically patchy, so we detect feasibility upfront and fall back to the
// legacy blob path (the server can still emit `performance.audio` when needed).
//
// The streamer exposes `appendChunk(bytes, final)` plus `abort()` for the
// barge-in case (phase 5). A single streamer instance plays one performance;
// create a new one per `performance.audio_begin` event.

import { Screenplay } from "./messages";

export type AudioStreamerOptions = {
  mime?: string;                // default "audio/mpeg"
  audioElement?: HTMLAudioElement;
  onEnded?: () => void;
  onError?: (err: unknown) => void;
};

export class StreamingAudioPlayer {
  private mediaSource: MediaSource;
  private sourceBuffer: SourceBuffer | null = null;
  private audio: HTMLAudioElement;
  private objectUrl: string;
  private pending: Uint8Array[] = [];
  private updating = false;
  private sawFinal = false;
  private closed = false;
  // True once we've fed at least one non-empty chunk into MSE. The first
  // non-empty chunk is the right moment to kick playback — we do NOT rely
  // on `seq === 0` because FallbackTTS produces a lone `seq=0, final=true`
  // chunk and any future chunking scheme might start at seq>0.
  private started = false;
  private onEnded?: () => void;
  private onError?: (err: unknown) => void;
  private mime: string;

  constructor(opts: AudioStreamerOptions = {}) {
    this.mime = opts.mime ?? "audio/mpeg";
    this.audio = opts.audioElement ?? new Audio();
    this.audio.autoplay = false;
    this.audio.crossOrigin = "anonymous";
    this.onEnded = opts.onEnded;
    this.onError = opts.onError;

    this.mediaSource = new MediaSource();
    this.objectUrl = URL.createObjectURL(this.mediaSource);
    this.audio.src = this.objectUrl;

    this.mediaSource.addEventListener("sourceopen", this.handleSourceOpen, { once: true });
    this.audio.addEventListener("ended", () => this.onEnded?.());
    this.audio.addEventListener("error", () => {
      this.onError?.(this.audio.error);
    });
  }

  public static canPlayMp3Streaming(): boolean {
    if (typeof MediaSource === "undefined") return false;
    try {
      return MediaSource.isTypeSupported("audio/mpeg");
    } catch {
      return false;
    }
  }

  public get element(): HTMLAudioElement {
    return this.audio;
  }

  /** Append a chunk; call with `final=true` on the last chunk. Safe to call
   *  before the source has opened — chunks are buffered. Starts playback on
   *  the first non-empty chunk. */
  public appendChunk(bytes: Uint8Array, final: boolean): void {
    if (this.closed) return;
    if (bytes.length > 0) {
      this.pending.push(bytes);
      if (!this.started) {
        this.started = true;
        // Fire the autoplay asynchronously so we don't block the handler.
        void this.play();
      }
    }
    if (final) this.sawFinal = true;
    this.drain();
  }

  /** True iff at least one non-empty chunk has been fed. */
  public get hasStarted(): boolean {
    return this.started;
  }

  /** Start playback. Should be called after first chunk has been appended so
   *  the browser has something to decode. Safe to call multiple times. */
  public async play(): Promise<void> {
    try {
      await this.audio.play();
    } catch (err) {
      // Autoplay policy — caller may need to trigger this on a user gesture.
      this.onError?.(err);
    }
  }

  /** Tear down everything. Safe to call multiple times. */
  public abort(reason?: string): void {
    if (this.closed) return;
    this.closed = true;
    try { this.audio.pause(); } catch {}
    try {
      if (this.sourceBuffer && !this.sourceBuffer.updating) {
        this.sourceBuffer.abort();
      }
    } catch {}
    try {
      if (this.mediaSource.readyState === "open") {
        this.mediaSource.endOfStream();
      }
    } catch {}
    URL.revokeObjectURL(this.objectUrl);
    if (reason) console.warn(`[audioStreamer] abort: ${reason}`);
  }

  // ─── Internals ────────────────────────────────────────────────────────────

  private handleSourceOpen = () => {
    if (this.closed) return;
    try {
      this.sourceBuffer = this.mediaSource.addSourceBuffer(this.mime);
      this.sourceBuffer.mode = "sequence";
      this.sourceBuffer.addEventListener("updateend", this.handleUpdateEnd);
      this.sourceBuffer.addEventListener("error", () => this.onError?.(new Error("sourceBuffer error")));
      this.drain();
    } catch (err) {
      this.onError?.(err);
    }
  };

  private handleUpdateEnd = () => {
    this.updating = false;
    this.drain();
  };

  private drain(): void {
    if (this.closed || this.updating || !this.sourceBuffer) return;
    if (this.pending.length > 0) {
      const next = this.pending.shift()!;
      try {
        this.updating = true;
        this.sourceBuffer.appendBuffer(next);
      } catch (err) {
        this.updating = false;
        this.onError?.(err);
      }
      return;
    }
    if (this.sawFinal && this.mediaSource.readyState === "open") {
      try {
        this.mediaSource.endOfStream();
      } catch (err) {
        this.onError?.(err);
      }
    }
  }
}

/** Bind the streamer's audio element to a Web Audio analyser so the existing
 *  VRM LipSync (reads `volume` from analyser) keeps driving mouth blendshapes
 *  as the stream plays. Returns the analyser so the caller can wire it up. */
export function attachLipSync(
  audio: HTMLAudioElement,
  ctx: AudioContext,
): AnalyserNode {
  const source = ctx.createMediaElementSource(audio);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 2048;
  source.connect(analyser);
  analyser.connect(ctx.destination);
  return analyser;
}

/** Decode a base64 chunk into a Uint8Array without creating an ArrayBuffer copy. */
export function base64ChunkToUint8(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** Kept for typing symmetry with other modules; the Screenplay shape isn't
 *  altered by streaming, only the delivery mechanism. */
export type StreamingScreenplay = Screenplay;
