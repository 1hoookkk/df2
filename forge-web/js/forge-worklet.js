/* df2 forge audio worklet — runs the WASM trench-core engine (filter cascade +
   AGC + Mackie saturation + QSound) on a looping excitation, live. The body and
   live params (morph/q/drive) arrive via postMessage; output is linearly
   resampled from the engine rate (39062.5) to the AudioContext rate, exactly as
   the Rust bench does. This is the real drive chain — the ear authors against it. */
class ForgeProcessor extends AudioWorkletProcessor {
  constructor(opts) {
    super();
    this.ready = false;
    this.playing = false;
    this.src = 0;
    this.morph = 0; this.q = 0; this.agc = 3.5; this.slam = 0.0; this.wide = 0.4;
    this.inputGain = 1.0; this.makeup = 0.6;
    // engine-domain source state
    this.phase = 0; this.kickT = 1e9; this.rng = 0x9e3779b9 >>> 0;
    // resample queue (engine-domain processed output)
    this.ql = []; this.qr = []; this.frac = 0;
    this.port.onmessage = (e) => this.onmsg(e.data);
    const po = opts.processorOptions || {};
    WebAssembly.instantiate(po.wasm, {}).then((m) => {
      const ex = m.instance.exports;
      this.ex = ex; this.mem = ex.memory;
      ex.forge_engine_init();
      this.maxN = Number(ex.forge_max_block());
      this.engSR = ex.forge_engine_sr();
      this.inV = new Float32Array(this.mem.buffer, ex.forge_in_ptr(), this.maxN);
      this.olV = new Float32Array(this.mem.buffer, ex.forge_outl_ptr(), this.maxN);
      this.orV = new Float32Array(this.mem.buffer, ex.forge_outr_ptr(), this.maxN);
      if (po.body) this.loadBody(new Uint8Array(po.body));
      this.ready = true;
      this.port.postMessage({ ready: true });
    }).catch((err) => this.port.postMessage({ error: String(err) }));
  }
  loadBody(bytes) {
    const ptr = this.ex.forge_body_ptr(), len = Number(this.ex.forge_body_len());
    new Uint8Array(this.mem.buffer, ptr, len).set(bytes.subarray(0, len));
    this.ex.forge_engine_load();
  }
  onmsg(d) {
    if (d.body) this.loadBody(new Uint8Array(d.body));
    if (d.params) {
      const p = d.params;
      this.morph = p.morph; this.q = p.q; this.agc = p.agc; this.slam = p.slam; this.wide = p.wide;
      if (p.inputGain != null) this.inputGain = Math.max(0.05, Math.min(16, p.inputGain));
      if (p.makeup != null) this.makeup = Math.max(0.05, Math.min(16, p.makeup));
    }
    if ("playing" in d) this.playing = d.playing;
    if ("src" in d) this.src = d.src;
  }
  gen() {
    const sr = this.engSR;
    if (this.src === 1) {                          // white noise
      let r = this.rng; r ^= r << 13; r ^= r >>> 17; r ^= r << 5; this.rng = r >>> 0;
      return (this.rng / 4294967295 * 2 - 1) * 0.4;
    }
    if (this.src === 2) {                          // 808 (pitch-drop sine, retrigger)
      if (this.kickT >= 0.6) this.kickT = 0;
      const t = this.kickT, f = 46 + 44 * Math.exp(-t * 16);
      this.phase += f / sr; if (this.phase >= 1) this.phase -= 1;
      const env = Math.exp(-t * 4.5); this.kickT += 1 / sr;
      return Math.sin(this.phase * 2 * Math.PI) * env * 0.7;
    }
    if (this.src === 3) {                          // voice buzz
      this.phase += 110 / sr; if (this.phase >= 1) this.phase -= 1;
      return (2 * this.phase - 1) * 0.4;
    }
    this.phase += 55 / sr; if (this.phase >= 1) this.phase -= 1;   // saw bass
    return (2 * this.phase - 1) * 0.5;
  }
  process(inputs, outputs) {
    const out = outputs[0], L = out[0], R = out[1] || out[0], frames = L.length;
    if (!this.ready || !this.playing) { L.fill(0); if (R !== L) R.fill(0); return true; }
    this.ex.forge_set_params(this.morph, this.q, this.agc, this.slam, this.wide);
    const step = this.engSR / sampleRate;
    const need = Math.ceil(this.frac + frames * step) + 2;
    while (this.ql.length < need) {
      const block = Math.min(this.maxN, 256);
      for (let i = 0; i < block; i++) this.inV[i] = this.gen() * this.inputGain;
      this.ex.forge_engine_process(block);
      for (let i = 0; i < block; i++) { this.ql.push(this.olV[i]); this.qr.push(this.orV[i]); }
    }
    const master = this.makeup;
    for (let f = 0; f < frames; f++) {
      const idx = Math.floor(this.frac), t = this.frac - idx;
      L[f] = (this.ql[idx] + (this.ql[idx + 1] - this.ql[idx]) * t) * master;
      if (R !== L) R[f] = (this.qr[idx] + (this.qr[idx + 1] - this.qr[idx]) * t) * master;
      this.frac += step;
    }
    const consumed = Math.floor(this.frac);
    if (consumed > 0) { this.ql.splice(0, consumed); this.qr.splice(0, consumed); this.frac -= consumed; }
    // post-drive level meter (the eye's truth signal): peak + smoothed RMS of what actually hits the speaker
    let pk = 0, ss = 0;
    for (let f = 0; f < frames; f++) { const a = Math.abs(L[f]); if (a > pk) pk = a; ss += L[f] * L[f]; }
    this._rms = (this._rms || 0) * 0.9 + Math.sqrt(ss / frames) * 0.1;
    this._mt = (this._mt || 0) + frames;
    if (this._mt >= 1500) { this._mt = 0; this.port.postMessage({ level: this._rms, peak: pk }); }
    return true;
  }
}
registerProcessor("forge-processor", ForgeProcessor);
