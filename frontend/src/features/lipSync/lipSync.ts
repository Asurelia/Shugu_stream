import { LipSyncAnalyzeResult } from "./lipSyncAnalyzeResult";

const TIME_DOMAIN_DATA_LENGTH = 2048;

export class LipSync {
  public readonly audio: AudioContext;
  public readonly analyser: AnalyserNode;
  public readonly timeDomainData: Float32Array;

  public constructor(audio: AudioContext) {
    this.audio = audio;

    this.analyser = audio.createAnalyser();
    this.timeDomainData = new Float32Array(TIME_DOMAIN_DATA_LENGTH);
  }

  public update(): LipSyncAnalyzeResult {
    this.analyser.getFloatTimeDomainData(this.timeDomainData);

    let volume = 0.0;
    for (let i = 0; i < TIME_DOMAIN_DATA_LENGTH; i++) {
      volume = Math.max(volume, Math.abs(this.timeDomainData[i]));
    }

    // cook
    volume = 1 / (1 + Math.exp(-45 * volume + 5));
    if (volume < 0.1) volume = 0;

    return {
      volume,
    };
  }

  public async playFromArrayBuffer(buffer: ArrayBuffer, onEnded?: () => void) {
    const audioBuffer = await this.audio.decodeAudioData(buffer);

    const bufferSource = this.audio.createBufferSource();
    bufferSource.buffer = audioBuffer;

    bufferSource.connect(this.audio.destination);
    bufferSource.connect(this.analyser);
    bufferSource.start();
    if (onEnded) {
      bufferSource.addEventListener("ended", onEnded);
    }
  }

  public async playFromURL(url: string, onEnded?: () => void) {
    const res = await fetch(url);
    const buffer = await res.arrayBuffer();
    this.playFromArrayBuffer(buffer, onEnded);
  }

  /** Bind an HTMLAudioElement (fed by MSE streaming) to this lip-sync's
   *  analyser so `update()` keeps returning live volume as the stream plays.
   *  An element may only be connected once — we cache the source node on the
   *  element itself to make repeated calls idempotent. */
  public attachMediaElement(audio: HTMLAudioElement): void {
    const anyAudio = audio as HTMLAudioElement & {
      __lipsyncSource?: MediaElementAudioSourceNode;
    };
    if (anyAudio.__lipsyncSource) {
      // Re-plug into our analyser just in case the previous graph was torn down.
      try { anyAudio.__lipsyncSource.connect(this.analyser); } catch {}
      return;
    }
    const source = this.audio.createMediaElementSource(audio);
    source.connect(this.analyser);
    source.connect(this.audio.destination);
    anyAudio.__lipsyncSource = source;
  }
}
