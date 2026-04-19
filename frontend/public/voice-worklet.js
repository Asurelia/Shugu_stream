// PCM16 voice worklet — 16kHz mono, 20ms frames (640 bytes = 320 samples int16).
//
// The main thread creates an AudioContext at 16kHz so we receive samples at
// the native target rate — no resampling here. We buffer incoming 128-sample
// blocks (the Web Audio render quantum) until we have 320 samples, pack them
// as int16 little-endian, and post the ArrayBuffer to the main thread.

class PCM16Worklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = new Float32Array(320);
    this._filled = 0;
  }

  process(inputs /*, outputs, parameters */) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const channel = input[0];
    if (!channel) return true;

    let read = 0;
    while (read < channel.length) {
      const remaining = 320 - this._filled;
      const toCopy = Math.min(remaining, channel.length - read);
      this._buffer.set(channel.subarray(read, read + toCopy), this._filled);
      this._filled += toCopy;
      read += toCopy;
      if (this._filled === 320) {
        const int16 = new Int16Array(320);
        for (let i = 0; i < 320; i++) {
          let s = this._buffer[i];
          if (s > 1) s = 1;
          else if (s < -1) s = -1;
          int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        this.port.postMessage(int16.buffer, [int16.buffer]);
        this._filled = 0;
      }
    }
    return true;
  }
}

registerProcessor("pcm16-worklet", PCM16Worklet);
