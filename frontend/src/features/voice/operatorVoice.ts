// Operator voice client — getUserMedia → AudioWorklet (16kHz PCM16) → WebSocket.
//
// One OperatorVoice instance per session. `start()` requests mic access and
// opens the /ws/operator/voice WS; `stop()` tears everything down. Incoming
// server events are surfaced via the onEvent callback: state changes, final
// transcripts, barge-in notifications.
//
// The AudioContext is explicitly configured at 16kHz so the worklet doesn't
// need to resample — it just packs the samples into 20ms int16 frames.

export type VoiceState =
  | "idle"
  | "operator_speaking"
  | "silence_debounce"
  | "processing"
  | "hermes_responding";

export type OperatorVoiceEvent =
  | { type: "voice.ready"; sample_rate: number; frame_bytes: number }
  | { type: "voice.state.change"; from: VoiceState; to: VoiceState }
  | { type: "voice.transcript.final"; text: string }
  | { type: "voice.barge_in"; performance_id: string | null }
  | { type: "voice.closed" }
  | { type: "pong"; t?: number };

export type OperatorVoiceStatus = "closed" | "connecting" | "open" | "error";

export type OperatorVoiceOptions = {
  onEvent?: (ev: OperatorVoiceEvent) => void;
  onStatus?: (status: OperatorVoiceStatus) => void;
  onMicError?: (err: unknown) => void;
};

export class OperatorVoice {
  private ws: WebSocket | null = null;
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private readonly onEvent?: (ev: OperatorVoiceEvent) => void;
  private readonly onStatus?: (status: OperatorVoiceStatus) => void;
  private readonly onMicError?: (err: unknown) => void;
  private readonly url: string;

  constructor(opts: OperatorVoiceOptions = {}) {
    this.onEvent = opts.onEvent;
    this.onStatus = opts.onStatus;
    this.onMicError = opts.onMicError;
    const wsProto = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = typeof window !== "undefined" ? window.location.host : "";
    this.url = `${wsProto}//${host}/ws/operator/voice`;
  }

  public async start(): Promise<void> {
    this.onStatus?.("connecting");

    // 1. Get mic. Request 16kHz explicitly; browsers will honor where possible.
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (err) {
      this.onMicError?.(err);
      this.onStatus?.("error");
      return;
    }

    // 2. AudioContext at 16kHz (so the worklet sees target-rate samples).
    try {
      this.ctx = new AudioContext({ sampleRate: 16000, latencyHint: "interactive" });
    } catch {
      // Some browsers reject non-default sample rates — fallback to default,
      // worklet will still run but the backend gets the wrong rate and STT
      // will degrade. Best-effort.
      this.ctx = new AudioContext({ latencyHint: "interactive" });
    }

    await this.ctx.audioWorklet.addModule("/voice-worklet.js");
    this.workletNode = new AudioWorkletNode(this.ctx, "pcm16-worklet");
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.source.connect(this.workletNode);
    // We do NOT connect the worklet to destination — no feedback echo.

    // 3. Open WS.
    try {
      this.ws = new WebSocket(this.url);
      this.ws.binaryType = "arraybuffer";
    } catch (err) {
      this.onStatus?.("error");
      this.teardownAudio();
      throw err;
    }

    this.ws.onopen = () => {
      this.onStatus?.("open");
      // Wire the worklet → WS once both sides are live.
      if (this.workletNode && this.ws) {
        const ws = this.ws;
        this.workletNode.port.onmessage = (ev) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(ev.data as ArrayBuffer);
          }
        };
      }
    };
    this.ws.onmessage = (msg) => {
      if (typeof msg.data !== "string") return;
      try {
        const ev = JSON.parse(msg.data) as OperatorVoiceEvent;
        this.onEvent?.(ev);
      } catch {
        /* ignore */
      }
    };
    this.ws.onerror = () => this.onStatus?.("error");
    this.ws.onclose = () => this.onStatus?.("closed");
  }

  public stop(): void {
    try {
      this.ws?.send(JSON.stringify({ type: "mic.close" }));
    } catch {}
    this.ws?.close();
    this.ws = null;
    this.teardownAudio();
    this.onStatus?.("closed");
  }

  private teardownAudio(): void {
    try { this.workletNode?.port.close(); } catch {}
    try { this.workletNode?.disconnect(); } catch {}
    try { this.source?.disconnect(); } catch {}
    try { this.stream?.getTracks().forEach((t) => t.stop()); } catch {}
    try { this.ctx?.close(); } catch {}
    this.workletNode = null;
    this.source = null;
    this.stream = null;
    this.ctx = null;
  }
}
