#!/usr/bin/env python3
"""spellcast.py — crude generative terminal for casting physical bodies on camera.

Low-bitrate ASCII by design; the "expensive" is in the timing and the way every
glyph RESOLVES from noise in real time. What scrambles in is the real physics —
actual formant frequencies and a real crude spectrum — and casting actually
writes ~/Documents/TRENCH/authoring_slot.json, so a running TRENCH hot-reloads
the body you just summoned. The crude readout is the engine thinking out loud.

Run:
  python tools/spellcast.py                 # REPL — type a body, watch it resolve
  python tools/spellcast.py cavern          # single-shot cast (clean recording take)
  python tools/spellcast.py --green         # phosphor green instead of amber
  python tools/spellcast.py --mono          # 1-bit white
"""
from __future__ import annotations
import argparse, importlib.util, math, os, random, sys, time
from pathlib import Path

# ── load the real physics engine (the skill script) ────────────────────────────
ROOT    = Path(__file__).resolve().parents[1]
PC_PATH = ROOT / ".claude" / "skills" / "physical-corners" / "physical_corners.py"
_spec   = importlib.util.spec_from_file_location("physical_corners", PC_PATH)
pc      = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)                      # type: ignore

# ── terminal plumbing ───────────────────────────────────────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8")      # blocks need utf-8
except Exception:
    pass

def _enable_vt():
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            pass
_enable_vt()

THEMES = {"amber": "\033[38;5;208m", "green": "\033[38;5;77m", "mono": "\033[38;5;253m"}
DIM, RST = "\033[2m", "\033[0m"
CLR, HOME = "\033[2J\033[H", "\033[H"
HIDE, SHOW = "\033[?25l", "\033[?25h"
ACCENT = THEMES["amber"]

BARS  = " ▁▂▃▄▅▆▇█"          # crude column heights (low-bitrate spectrum)
NOISE = "01:.#%*=+-/\\|<>[]"  # generative scramble charset
DITH  = "░▒▓"                # dither while resolving

SR = pc.SR

def out(s: str): sys.stdout.write(s); sys.stdout.flush()

# ── the three primitives: stream, scramble-resolve, noise-dissolve-to-bars ──────
def stream(text: str, cps: float = 90, jitter: float = 0.5):
    delay = 1.0 / cps
    for ch in text:
        out(ch)
        time.sleep(delay * (1 + random.random() * jitter))
    out("\n")

def scramble_in(target: str, frames: int = 7, fps: int = 55, indent: str = ""):
    """Resolve a line from random noise to `target`, locking glyphs left→right."""
    n = len(target)
    locked = [c == " " for c in target]
    for f in range(frames + 1):
        for i in range(n):
            if not locked[i] and (i < n * f / frames or random.random() < 0.12):
                locked[i] = True
        line = "".join(target[i] if locked[i] else random.choice(NOISE) for i in range(n))
        out("\r" + indent + ACCENT + line + RST)
        time.sleep(1.0 / fps)
    out("\r" + indent + ACCENT + target + RST + "\n")

def dissolve_to_bars(bars: str, frames: int = 6, fps: int = 45, indent: str = ""):
    """Spectrum arrives as dither static, then settles into the real shape."""
    n = len(bars)
    for f in range(frames):
        p = f / frames
        line = "".join(bars[j] if random.random() < p else random.choice(DITH) for j in range(n))
        out("\r" + indent + ACCENT + line + RST)
        time.sleep(1.0 / fps)
    out("\r" + indent + ACCENT + bars + RST + "\n")

# ── pull REAL data out of a built corner ────────────────────────────────────────
def corner_spectrum(corner, nbins: int = 28):
    mags = []
    for i in range(nbins):
        f = 40.0 * (16000.0 / 40.0) ** (i / (nbins - 1))
        w = 2 * math.pi * f / SR
        m = 1.0
        for s in corner:
            m *= pc._section_mag(s, w)
        mags.append(m)
    mx = max(mags) or 1.0
    return [m / mx for m in mags]

def render_bars(norm):
    top = len(BARS) - 1
    return "".join(BARS[min(top, int(v * top + 0.5))] for v in norm)

def corner_formants(corner):
    fr = []
    for s in corner:
        if s == pc.PASS:
            continue
        a1, a2 = s[2] - 2, 1 - s[3]
        r = math.sqrt(max(a2, 0.0))
        if r > 1e-6:
            fr.append(int(round(math.acos(max(-1, min(1, -a1 / (2 * r)))) * SR / (2 * math.pi))))
    return sorted(fr)

# ── the cast ─────────────────────────────────────────────────────────────────────
def _spec_name(s):
    if s[0] == "tract":
        return s[1].upper()
    if s[0] == "tube":
        return f"TUBE {s[1]:g}cm"
    return f"{str(s[1]).upper()} {s[2]:g}"

def summon(word: str):
    word = word.lower().strip()
    if word not in pc.PRESETS:
        out("\n")
        stream(f"  ?? no body named '{word}'", cps=110)
        stream("  " + DIM + "known bodies:  " + "   ".join(sorted(pc.PRESETS)) + RST, cps=240)
        return
    specs   = pc.PRESETS[word]
    labels  = pc.LABELS
    out("\n")
    scramble_in(f"  ░▒▓  SUMMONING  {word.upper()}  ▓▒░", indent="")
    time.sleep(0.18)
    corners = []
    for i, spec in enumerate(specs):
        c = pc.corner_from_spec(spec)
        corners.append(c)
        stream(f"  {i + 1}/4  {_spec_name(spec):<14}{DIM}{labels[i]}{RST}", cps=130)
        dissolve_to_bars(render_bars(corner_spectrum(c)), indent="       ")
        fr = corner_formants(c)
        stream("       " + DIM + "  ".join(str(x) for x in fr) + " Hz" + RST, cps=260)
        time.sleep(0.1)
    slot = pc.write_cartridge(corners, f"phys_{word}")
    out("\n")
    scramble_in("  4 BODIES LOCKED  →  TRENCH")
    stream("  " + DIM + "now sweep Q / Morph — listen to the middle" + RST, cps=140)

# ── REPL ──────────────────────────────────────────────────────────────────────────
def repl():
    out(HIDE + CLR)
    try:
        scramble_in("  ░▒▓   S P E L L C A S T   ▓▒░", frames=10)
        stream("  " + DIM + "name a body. physics resolves. TRENCH hot-reloads." + RST, cps=130)
        stream("  " + DIM + "bodies:  " + "   ".join(sorted(pc.PRESETS)) + RST, cps=260)
        while True:
            out("\n" + ACCENT + "  ▸ " + RST)
            try:
                line = input()
            except EOFError:
                break
            line = line.strip().lower()
            if line in ("q", "quit", "exit"):
                break
            if line:
                summon(line)
    finally:
        out(SHOW + RST + "\n")

def main():
    global ACCENT
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("body", nargs="?", help="cast this body once and exit (clean take)")
    ap.add_argument("--green", action="store_true")
    ap.add_argument("--mono", action="store_true")
    a = ap.parse_args()
    ACCENT = THEMES["green"] if a.green else THEMES["mono"] if a.mono else THEMES["amber"]
    if a.body:
        out(HIDE)
        try:
            summon(a.body)
        finally:
            out(SHOW + RST + "\n")
    else:
        repl()

if __name__ == "__main__":
    main()
