// Ring-buffer PCM player: receives interleaved stereo Int16 frames, outputs Float32.
const BUFFER_FRAMES = 48000; // 1s ring
const PREBUFFER = 9600; // ~200ms before playback starts

class PcmPlayer extends AudioWorkletProcessor {
  constructor() {
    super();
    this.l = new Float32Array(BUFFER_FRAMES);
    this.r = new Float32Array(BUFFER_FRAMES);
    this.read = 0;
    this.write = 0;
    this.filled = 0;
    this.playing = false;
    this.port.onmessage = (e) => {
      const d = e.data;
      for (let i = 0; i + 1 < d.length; i += 2) {
        if (this.filled >= BUFFER_FRAMES) { // overflow: drop oldest
          this.read = (this.read + 1) % BUFFER_FRAMES;
          this.filled--;
        }
        this.l[this.write] = d[i] / 32768;
        this.r[this.write] = d[i + 1] / 32768;
        this.write = (this.write + 1) % BUFFER_FRAMES;
        this.filled++;
      }
    };
  }

  process(_in, outputs) {
    const out = outputs[0];
    const n = out[0].length;
    if (!this.playing && this.filled >= PREBUFFER) this.playing = true;
    if (this.playing && this.filled < n) this.playing = false; // underrun: rebuffer
    if (!this.playing) return true;
    for (let i = 0; i < n; i++) {
      out[0][i] = this.l[this.read];
      if (out[1]) out[1][i] = this.r[this.read];
      this.read = (this.read + 1) % BUFFER_FRAMES;
    }
    this.filled -= n;
    return true;
  }
}
registerProcessor('pcm-player', PcmPlayer);
