#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyruntime import trench_ffi

SR = 39_062.5
BODY = ROOT / "juce-shell" / "assets" / "cartridges" / "P2k_013_talking_hedz.json"


def source(kind: str, seconds: float = 4.0) -> np.ndarray:
    n = int(SR * seconds)
    t = np.arange(n, dtype=np.float64) / SR
    if kind == "pink":
        rng = np.random.default_rng(13)
        white = rng.standard_normal(n)
        spectrum = np.fft.rfft(white)
        freqs = np.fft.rfftfreq(n, 1.0 / SR)
        spectrum /= np.sqrt(np.maximum(freqs, 1.0))
        x = np.fft.irfft(spectrum, n)
        x *= 0.62 / max(1e-9, float(np.max(np.abs(x))))
    elif kind == "tone":
        x = 0.48 * np.sin(2.0 * np.pi * 110.0 * t)
    elif kind == "808":
        phase = 2.0 * np.pi * np.cumsum(47.0 + 72.0 * np.exp(-t / 0.04)) / SR
        x = 0.78 * np.sin(phase) * np.exp(-t / 0.82)
        x += 0.13 * np.sin(2.0 * phase) * np.exp(-t / 0.36)
    else:
        phase = (92.0 * t) % 1.0
        x = 0.48 * (2.0 * phase - 1.0)
    fade = min(n // 2, int(SR * 0.02))
    if fade:
        ramp = np.linspace(0.0, 1.0, fade)
        x[:fade] *= ramp
        x[-fade:] *= ramp[::-1]
    return x.astype("<f4")


def stereo_wav(left: bytes, right: bytes) -> bytes:
    l = np.frombuffer(left, dtype="<f4")
    r = np.frombuffer(right, dtype="<f4")
    n = min(len(l), len(r))
    interleaved = np.empty(n * 2, dtype="<i2")
    interleaved[0::2] = (np.clip(l[:n], -1.0, 1.0) * 32767.0).astype("<i2")
    interleaved[1::2] = (np.clip(r[:n], -1.0, 1.0) * 32767.0).astype("<i2")
    out = BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(round(SR))
        wav.writeframes(interleaved.tobytes())
    return out.getvalue()


def value(query: dict[str, list[str]], key: str, default: float) -> float:
    return float(query.get(key, [str(default)])[0])


def enabled(query: dict[str, list[str]], key: str, default: bool) -> bool:
    return query.get(key, ["1" if default else "0"])[0] == "1"


class Handler(BaseHTTPRequestHandler):
    cartridge = BODY.read_text(encoding="utf-8")

    def log_message(self, _format: str, *_args) -> None:
        return

    def send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/player"}:
            self.send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/health":
            data = {
                "engine": trench_ffi.engine_available(),
                "body": str(BODY),
            }
            self.send(200, json.dumps(data).encode("utf-8"), "application/json")
            return
        if parsed.path != "/audio.wav":
            self.send(404, b"not found", "text/plain")
            return
        try:
            q = parse_qs(parsed.query)
            dry = source(q.get("source", ["saw"])[0])
            left, right = trench_ffi.engine_render_controls_stereo(
                self.cartridge,
                morph=max(0.0, min(1.0, value(q, "morph", 0.5))),
                q=max(0.0, min(1.0, value(q, "q", 0.5))),
                in_f32_bytes=dry.tobytes(),
                slam_drive=max(0.0, min(1.0, value(q, "slam", 0.0))),
                qsound_enabled=enabled(q, "qsound", False),
                space=max(0.0, min(1.0, value(q, "space", 0.75))),
                agc_enabled=enabled(q, "agc", True),
                agc_drive=4.0,
                sr=SR,
            )
            self.send(200, stereo_wav(left, right), "audio/wav")
        except Exception as exc:
            self.send(500, str(exc).encode("utf-8"), "text/plain; charset=utf-8")


PAGE = r"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Talking Hedz calibration player</title>
<style>
  :root{font-family:Inter,system-ui,sans-serif;background:#f2f0eb;color:#252723}
  body{margin:0;min-height:100vh;display:grid;place-items:center}
  main{width:min(820px,calc(100vw - 48px));background:#fffdf8;border:1px solid #cac4b8;border-radius:18px;padding:30px;box-shadow:0 14px 35px #7a746628}
  header{display:flex;justify-content:space-between;align-items:start;gap:20px;border-bottom:1px solid #ddd6ca;padding-bottom:20px}
  h1{font-size:30px;margin:0 0 6px;letter-spacing:-.04em}.sub{color:#716d64;font-size:14px}.badge{font-size:12px;padding:7px 10px;border:1px solid #98a286;border-radius:999px;color:#52623b;background:#f5f9ed}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:18px 28px;margin:26px 0}
  label{display:block;font-size:12px;font-weight:750;letter-spacing:.1em;color:#69645c;text-transform:uppercase}.value{float:right;color:#252723}
  input[type=range]{width:100%;accent-color:#6a873c;margin-top:12px}
  .switches{display:flex;gap:12px;flex-wrap:wrap;border-top:1px solid #ddd6ca;border-bottom:1px solid #ddd6ca;padding:18px 0}
  .switch{display:flex;align-items:center;gap:9px;background:#f8f5ee;border:1px solid #d8d0c4;border-radius:10px;padding:10px 12px;font-size:14px;font-weight:650}
  .source{display:flex;gap:8px;align-items:center;margin-top:18px}.source label{margin-right:5px}select,button{font:inherit;border-radius:10px;border:1px solid #bdb5a8;background:#fffdf8;padding:10px 13px}
  button{cursor:pointer;background:#54722f;color:white;border-color:#54722f;font-weight:750}.stop{background:#fffdf8;color:#514d46;border-color:#bdb5a8}
  audio{width:100%;margin-top:18px}.foot{font-size:12px;color:#807a70;margin-top:14px}
  @media(max-width:650px){.grid{grid-template-columns:1fr}main{padding:20px}}
</style>
<main>
  <header>
    <div><h1>Talking Hedz</h1><div class="sub">Real trench-core calibration player · held control position · stereo output</div></div>
    <div class="badge">P2k_013 · ENGINE PATH</div>
  </header>
  <div class="grid">
    <label>Morph <span class="value" id="morphV">50</span><input id="morph" type="range" min="0" max="100" value="50"></label>
    <label>Q <span class="value" id="qV">50</span><input id="q" type="range" min="0" max="100" value="50"></label>
    <label>Mackie input slam <span class="value" id="slamV">0</span><input id="slam" type="range" min="0" max="100" value="0"></label>
    <label>QSound space <span class="value" id="spaceV">75</span><input id="space" type="range" min="0" max="100" value="75"></label>
  </div>
  <div class="switches">
    <label class="switch"><input id="agc" type="checkbox" checked> AGC on</label>
    <label class="switch"><input id="qsound" type="checkbox"> QSound on</label>
  </div>
  <div class="source">
    <label for="source">Source</label>
    <select id="source"><option value="saw">Saw</option><option value="pink">Pink</option><option value="808">808</option><option value="tone">Tone</option></select>
    <button id="play">Play / refresh</button><button class="stop" id="stop">Stop</button>
  </div>
  <audio id="audio" controls loop></audio>
  <div class="foot">AGC on uses the engine's audible x4 engagement setting. Mackie Slam is pre-filter. QSound is post-filter and requires headphones or stereo speakers.</div>
</main>
<script>
  const ids=["morph","q","slam","space"], audio=document.getElementById("audio");
  for(const id of ids){const el=document.getElementById(id), out=document.getElementById(id+"V");el.oninput=()=>{out.textContent=el.value; schedule()}}
  for(const id of ["agc","qsound","source"])document.getElementById(id).onchange=schedule;
  let timer;
  function url(){const g=id=>document.getElementById(id);return "/audio.wav?morph="+g("morph").value/100+"&q="+g("q").value/100+"&slam="+g("slam").value/100+"&space="+g("space").value/100+"&agc="+(g("agc").checked?1:0)+"&qsound="+(g("qsound").checked?1:0)+"&source="+g("source").value+"&t="+Date.now()}
  function schedule(){if(!audio.paused){clearTimeout(timer);timer=setTimeout(play,180)}}
  function play(){audio.src=url();audio.play()}
  document.getElementById("play").onclick=play;
  document.getElementById("stop").onclick=()=>{audio.pause();audio.currentTime=0};
</script>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8780, type=int)
    args = parser.parse_args()
    if not trench_ffi.engine_available():
        raise SystemExit("trench-core FFI unavailable: cargo build --release -p trench-core")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Talking Hedz player: http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
