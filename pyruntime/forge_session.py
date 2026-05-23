"""Live forge session — called from terminal, pushes to browser scope.

Usage from Claude Code terminal:
    python pyruntime/forge_session.py render TalkingHedz 0.5 0.5
    python pyruntime/forge_session.py splice TalkingHedz Sub_Cathedral 0.5
    python pyruntime/forge_session.py collide
    python pyruntime/forge_session.py freeze MyNewBody
"""
import sys
import json
import base64
import random
import os

from pyruntime.body import Body, load_vault_body, list_vault_bodies
from pyruntime.splice import SpliceError, SpliceMode, splice_corners
from pyruntime.render import render_from_body
from pyruntime.freq_response import freq_points, cascade_response_db
from pyruntime.constants import SR

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
VAULT_DIR = os.path.join(os.path.dirname(__file__), "..", "vault")
PREVIEW_WAV = os.path.join(os.path.dirname(__file__), "..", "tests", "forge_preview.wav")

# Session state
_current_body = None
_current_label = ""


def push_to_scope(body: Body, morph: float, q: float, label: str):
    """Update the live scope display."""
    enc = body.corners.interpolate(morph, q)
    freqs = freq_points()
    db = cascade_response_db(enc, freqs, SR)
    path = os.path.join(STATIC_DIR, "live_response.json")
    with open(path, "w") as f:
        json.dump({"freqs": freqs.tolist(), "db": db.tolist(), "label": label}, f)


def render_and_save(body: Body, morph: float, q: float, drive: float = 0.5):
    """Render audio and save WAV."""
    result = render_from_body(body, morph, q, mackie_amount=drive, duration=2.0)
    wav = base64.b64decode(result["audio_b64"])
    os.makedirs(os.path.dirname(PREVIEW_WAV), exist_ok=True)
    with open(PREVIEW_WAV, "wb") as f:
        f.write(wav)
    return result


def cmd_render(name: str, morph: float = 0.5, q: float = 0.5, drive: float = 0.5):
    body = load_vault_body(name)
    label = f"{name} @ M{int(morph*100)} Q{int(q*100)}"
    push_to_scope(body, morph, q, label)
    r = render_and_save(body, morph, q, drive)
    print(f"{label} | peak {r['peak_db']:.1f} dB | {PREVIEW_WAV}")
    return body


def cmd_splice(name_a: str, name_b: str, morph: float = 0.5, drive: float = 0.5):
    a = load_vault_body(name_a)
    b = load_vault_body(name_b)
    try:
        spliced = splice_corners(
            a.corners,
            b.corners,
            SpliceMode.REST_TO_MORPHED,
            filter_type_a=a.filter_type,
            filter_type_b=b.filter_type,
        )
    except SpliceError as e:
        raise RuntimeError(f"splice failed: {e}") from e
    body = Body(name=f"{name_a}_x_{name_b}", corners=spliced, boost=a.boost)
    label = f"{name_a} x {name_b} @ M{int(morph*100)}"
    push_to_scope(body, morph, 0.5, label)
    r = render_and_save(body, morph, 0.5, drive)
    print(f"{label} | peak {r['peak_db']:.1f} dB | {PREVIEW_WAV}")
    return body


def cmd_collide(drive: float = 0.5):
    names = list_vault_bodies()
    a_name, b_name = random.sample(names, 2)
    return cmd_splice(a_name, b_name, random.uniform(0.2, 0.8), drive)


def cmd_freeze(body: Body, name: str):
    os.makedirs(VAULT_DIR, exist_ok=True)
    path = os.path.join(VAULT_DIR, f"{name}.json")
    with open(path, "w") as f:
        f.write(body.to_compiled_json())
    print(f"Frozen: {path}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Usage: render <name> [morph] [q] | splice <a> <b> [morph] | collide | freeze <name>")
        sys.exit(1)

    cmd = args[0]
    if cmd == "render":
        cmd_render(args[1], float(args[2]) if len(args) > 2 else 0.5,
                   float(args[3]) if len(args) > 3 else 0.5)
    elif cmd == "splice":
        cmd_splice(args[1], args[2], float(args[3]) if len(args) > 3 else 0.5)
    elif cmd == "collide":
        cmd_collide()
    elif cmd == "freeze":
        print("Freeze requires a body in session. Use from Claude Code.")
    else:
        print(f"Unknown command: {cmd}")
