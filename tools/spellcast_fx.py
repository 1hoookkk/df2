#!/usr/bin/env python3
"""spellcast_fx.py — the "crazy" cut. Modern terminal-demoscene tricks over the
real physics engine, built to be screen-recorded for short-form.

Tricks in here:
  • 24-bit TRUECOLOR phosphor gradients (not 256-color)
  • sub-pixel BRAILLE rendering — 2x4 dots per cell, so the spectrum is a smooth
    high-res silhouette, not chunky ASCII blocks
  • a FLOW-FIELD of noise that crystallizes into the real shape (not random static)
  • RGB-SPLIT / chromatic-aberration GLITCH burst on the cast
  • CRT SCANLINES (every other row dimmed)
  • a live MORPH-SWEEP money shot — the body melts continuously through all 4
    corners (the "magic in the middle", drawn from the real interpolated spectra)

Still real: imports the physical-corners engine, the silhouettes are the actual
filter magnitude responses, and casting writes the hot-reload slot.

  python tools/spellcast_fx.py            # REPL
  python tools/spellcast_fx.py cavern     # single take
  python tools/spellcast_fx.py --green
"""
from __future__ import annotations
import argparse, importlib.util, math, os, random, sys, time
from pathlib import Path

# ── real physics engine ─────────────────────────────────────────────────────────
ROOT    = Path(__file__).resolve().parents[1]
PC_PATH = ROOT / ".claude" / "skills" / "physical-corners" / "physical_corners.py"
_spec   = importlib.util.spec_from_file_location("physical_corners", PC_PATH)
pc      = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)                      # type: ignore
SR = pc.SR

# ── terminal ──────────────────────────────────────────────────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
if os.name == "nt":
    try:
        import ctypes
        _k = ctypes.windll.kernel32
        _k.SetConsoleMode(_k.GetStdHandle(-11), 7)
    except Exception:
        pass

CLR, HOME, HIDE, SHOW, RST = "\033[2J\033[H", "\033[H", "\033[?25l", "\033[?25h", "\033[0m"
def out(s): sys.stdout.write(s); sys.stdout.flush()
def _c(x): return min(255, max(0, int(x)))
def rgb(r, g, b): return f"\033[38;2;{_c(r)};{_c(g)};{_c(b)}m"
def lerp(a, b, t): return a + (b - a) * t

# canvas size (cells). pixel grid is 2*W wide, 4*H tall (braille sub-cells)
W, H = 56, 16
PX, PY = W * 2, H * 4
DOTS = [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]]   # [row][col] braille bits

# phosphor gradients: (cool low) -> (hot tip)
THEMES = {
    "amber": ((120, 38, 4), (255, 244, 198)),
    "green": ((10, 90, 28), (190, 255, 205)),
    "mono":  ((70, 70, 78), (250, 250, 255)),
}
PAL = THEMES["amber"]

# ── pull real magnitude response of a corner, hi-res + log-spaced ────────────────
def corner_curve(corner, nbins=PX):
    mags = []
    for i in range(nbins):
        f = 40.0 * (16000.0 / 40.0) ** (i / (nbins - 1))
        w = 2 * math.pi * f / SR
        m = 1.0
        for s in corner:
            m *= pc._section_mag(s, w)
        mags.append(m)
    mx = max(mags) or 1.0
    # soft compress so peaks don't pin and the floor has life
    return [(v / mx) ** 0.6 for v in mags]

# ── braille canvas render (one truecolor code per row = cheap + smooth) ──────────
def render(heights, glow=1.0, split=0):
    """heights: list[PX] of pixel column heights (0..PY). split: chromatic glitch px."""
    lo, hi = PAL
    buf = [HOME]
    for cy in range(H):
        t = 1.0 - cy / (H - 1)                         # hotter toward the top
        dim = 1.0 if cy % 2 == 0 else 0.62             # CRT scanline
        col = rgb(*(lerp(lo[k], hi[k], t) * dim * glow for k in range(3)))
        row = []
        for cx in range(W):
            mask = 0
            for r in range(4):
                py = 4 * cy + r
                for c in range(2):
                    x = 2 * cx + c + split
                    if 0 <= x < PX and py >= PY - heights[x]:
                        mask |= DOTS[r][c]
            row.append(chr(0x2800 + mask) if mask else " ")
        buf.append(col + "".join(row))
    buf.append(RST)
    return "".join(buf)

def heights_from(curve, scale=1.0):
    return [max(0, min(PY, int(v * PY * scale))) for v in curve]

# ── flow-field noise that crystallizes into the real silhouette ──────────────────
def crystallize(curve, frames=26, fps=42):
    target = heights_from(curve)
    for f in range(frames + 1):
        p = (f / frames) ** 1.6                        # ease-in lock
        t = f * 0.22
        hs = []
        for x in range(PX):
            if random.random() < p:
                hs.append(target[x])
            else:
                # flowing value-noise field, not random static
                v = (math.sin(x * 0.18 + t) + math.sin(x * 0.07 - t * 1.7)
                     + random.random() * 1.2)
                hs.append(int((v + 2.4) / 4.8 * PY * 0.55))
        out(render(hs, glow=0.8 + 0.2 * p))
        time.sleep(1.0 / fps)

# ── the morph-sweep money shot: melt through all 4 corners ───────────────────────
def morph_sweep(curves, frames=80, fps=40):
    for f in range(frames):
        u = f / (frames - 1)
        pos = u * 3.0                                  # 0..3 across the 4 corners
        i = min(2, int(pos)); frac = pos - i
        cur = [lerp(curves[i][x], curves[i + 1][x], frac) for x in range(PX)]
        strike = 1.0 + 0.18 * math.exp(-((u * 6) % 1.0) * 5)   # subtle pulse per corner
        hs = heights_from(cur, scale=strike)
        out(render(hs, glow=1.0))
        out(_puck_bar(u))
        time.sleep(1.0 / fps)

def _puck_bar(u):
    p = int(u * (W - 1))
    lo, hi = PAL
    chars = ["─"] * W
    left, right = "".join(chars[:p]), "".join(chars[p + 1:])
    return "\n  " + rgb(*lo) + left + rgb(*hi) + "◆" + rgb(*lo) + right + RST

# ── RGB-split chromatic glitch title ─────────────────────────────────────────────
def glitch_title(text, frames=10, fps=30):
    pad = "  "
    for f in range(frames):
        settle = f / frames
        shift = max(0, int((1 - settle) * 3))
        jit = "" if random.random() < settle else " " * random.randint(0, 2)
        ghost_b = "\033[38;2;0;120;255m" + " " * (len(pad) + shift) + text
        ghost_r = "\033[38;2;255;40;60m" + pad + " " * max(0, shift - 1) + text
        white   = rgb(245, 245, 255) + pad + jit + text
        out("\r\033[K" + ghost_b)
        out("\r\033[K" + ghost_r)
        out("\r\033[K" + white + RST)
        time.sleep(1.0 / fps)
    out("\r\033[K" + rgb(245, 245, 255) + pad + text + RST + "\n")

# ── cast ─────────────────────────────────────────────────────────────────────────
def _spec_name(s):
    if s[0] == "tract": return s[1].upper()
    if s[0] == "tube":  return f"TUBE {s[1]:g}cm"
    return f"{str(s[1]).upper()} {s[2]:g}"

def summon(word):
    word = word.lower().strip()
    if word not in pc.PRESETS:
        out("\n" + rgb(*PAL[1]) + f"  ?? no body '{word}'" + RST + "\n")
        out(rgb(*PAL[0]) + "  " + "   ".join(sorted(pc.PRESETS)) + RST + "\n")
        return
    specs   = pc.PRESETS[word]
    corners = [pc.corner_from_spec(s) for s in specs]
    curves  = [corner_curve(c) for c in corners]

    out(CLR)
    glitch_title(f"▓▒░  S U M M O N   {word.upper()}  ░▒▓")
    out("\n" * (H))                              # reserve canvas space
    crystallize(curves[0])                       # noise -> first corner
    morph_sweep(curves)                          # melt through all four
    slot = pc.write_cartridge(corners, f"phys_{word}")
    # strike flash, then settle — purely visual
    for g in (1.7, 1.3, 1.0):
        out(render(heights_from(curves[-1]), glow=g))
        time.sleep(0.045)
    lo, hi = PAL
    out("\n\n" + rgb(*hi) + f"   ● {word.upper()}" + RST + "\n")
    time.sleep(0.7)
    return slot

def repl():
    out(HIDE + CLR)
    try:
        glitch_title("▓▒░   S P E L L C A S T   ·   F X   ▓▒░")
        out(rgb(*PAL[0]) + "  name a body:  " + "   ".join(sorted(pc.PRESETS)) + RST + "\n")
        while True:
            out("\n" + rgb(*PAL[1]) + "  ▸ " + RST)
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

def headless(word):
    """No TTY (piped/captured) — animation can't draw. Still author the body."""
    word = (word or "cavern").lower().strip()
    if word in pc.PRESETS:
        corners = [pc.corner_from_spec(s) for s in pc.PRESETS[word]]
        pc.write_cartridge(corners, f"phys_{word}")
        print(f"[spellcast_fx] authored phys_{word} -> the hot-reload slot.")
    print("[spellcast_fx] this is a LIVE screen animation; it can't draw through a")
    print("  pipe or capture. Open Windows Terminal directly and run:")
    print(f"    python tools/spellcast_fx.py {word}")

def main():
    global PAL
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("body", nargs="?")
    ap.add_argument("--green", action="store_true")
    ap.add_argument("--mono", action="store_true")
    a = ap.parse_args()
    PAL = THEMES["green"] if a.green else THEMES["mono"] if a.mono else THEMES["amber"]
    if not sys.stdout.isatty():
        headless(a.body)
        return
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
