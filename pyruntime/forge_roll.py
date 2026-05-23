"""Forge roll — generative body discovery with preference learning.

Generates random collisions, learns from yes/no feedback.
Sources that produce "yes" get higher weight. Over time,
the roller biases toward what you like.

Usage:
    from pyruntime.forge_roll import Roller
    r = Roller()
    r.roll()        # generates, renders, pushes to scope
    r.yes()         # liked it — boost those sources, save body
    r.no()          # skip — penalize those sources
    r.roll()        # next one, biased by preferences
    r.history()     # show what you've liked
"""
import json
import math
import os
import random
import base64

from pyruntime.body import Body, load_vault_body, list_vault_bodies
from pyruntime.splice import SpliceError, SpliceMode, splice_corners
from pyruntime.target import (
    load_sonic_tables, get_vowel_keys, get_nasal_keys, get_landmark_names,
    build_vowel_target, build_nasal_target, build_landmark_target,
)
from pyruntime.macro_compile import compile_body
from pyruntime.render import render_from_body
from pyruntime.freq_response import freq_points, cascade_response_db
from pyruntime.constants import SR

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
VAULT_DIR = os.path.join(os.path.dirname(__file__), "..", "vault")
PREVIEW_WAV = os.path.join(os.path.dirname(__file__), "..", "tests", "forge_preview.wav")
PREFS_PATH = os.path.join(os.path.dirname(__file__), "..", "forge_preferences.json")

SPLICE_MODES = [SpliceMode.REST_TO_MORPHED, SpliceMode.MORPHED_TO_MORPHED, SpliceMode.CROSS]


def _all_sources():
    """All available source names: vault bodies + sonic table entries."""
    sources = []
    for name in list_vault_bodies():
        sources.append(("vault", name))
    for key in get_vowel_keys():
        sources.append(("vowel", key))
    for key in get_nasal_keys():
        sources.append(("nasal", key))
    return sources


def _load_source(kind: str, key: str) -> Body:
    if kind == "vault":
        return load_vault_body(key)
    elif kind == "vowel":
        spec = build_vowel_target(key, key)
        corners = compile_body(spec)
        return Body(name=key, corners=corners, boost=spec.boost)
    elif kind == "nasal":
        spec = build_nasal_target(key, key)
        corners = compile_body(spec)
        return Body(name=key, corners=corners, boost=spec.boost)
    else:
        raise ValueError(f"Unknown source kind: {kind}")


class Roller:
    def __init__(self, drive: float = 0.5):
        self.drive = drive
        self.scores = {}  # source_key → score
        self.sources = _all_sources()
        self.current_body = None
        self.current_a = None
        self.current_b = None
        self.current_morph = 0.5
        self.current_label = ""
        self.kept = []  # list of (label, body_name) that got yes
        self._load_prefs()

    def _load_prefs(self):
        if os.path.exists(PREFS_PATH):
            with open(PREFS_PATH) as f:
                self.scores = json.load(f)

    def _save_prefs(self):
        with open(PREFS_PATH, "w") as f:
            json.dump(self.scores, f, indent=2)

    def _score(self, key: str) -> float:
        return self.scores.get(key, 1.0)

    def _pick_weighted(self) -> tuple:
        weights = [max(0.1, self._score(f"{k}:{n}")) for k, n in self.sources]
        total = sum(weights)
        probs = [w / total for w in weights]
        idx = random.choices(range(len(self.sources)), weights=probs, k=1)[0]
        return self.sources[idx]

    def _push_scope(self, body: Body, morph: float, label: str):
        enc = body.corners.interpolate(morph, 0.5)
        freqs = freq_points()
        db = cascade_response_db(enc, freqs, SR)
        path = os.path.join(STATIC_DIR, "live_response.json")
        with open(path, "w") as f:
            json.dump({"freqs": freqs.tolist(), "db": db.tolist(), "label": label}, f)

    def _render(self, body: Body, morph: float):
        result = render_from_body(body, morph, 0.5, mackie_amount=self.drive, duration=2.0)
        wav = base64.b64decode(result["audio_b64"])
        os.makedirs(os.path.dirname(PREVIEW_WAV), exist_ok=True)
        with open(PREVIEW_WAV, "wb") as f:
            f.write(wav)
        return result

    def roll(self):
        """Generate a new random collision."""
        attempts = 0
        while True:
            attempts += 1
            kind_a, name_a = self._pick_weighted()
            kind_b, name_b = self._pick_weighted()
            while name_b == name_a:
                kind_b, name_b = self._pick_weighted()

            body_a = _load_source(kind_a, name_a)
            body_b = _load_source(kind_b, name_b)
            mode = random.choice(SPLICE_MODES)
            morph = round(random.uniform(0.15, 0.85), 2)
            try:
                spliced = splice_corners(
                    body_a.corners,
                    body_b.corners,
                    mode,
                    filter_type_a=body_a.filter_type,
                    filter_type_b=body_b.filter_type,
                )
                break
            except SpliceError:
                if attempts >= 16:
                    raise
                continue

        body = Body(name=f"{name_a}_x_{name_b}", corners=spliced, boost=body_a.boost)

        self.current_body = body
        self.current_a = f"{kind_a}:{name_a}"
        self.current_b = f"{kind_b}:{name_b}"
        self.current_morph = morph
        self.current_label = f"{name_a} x {name_b} [{mode.value}] @ M{int(morph*100)}"

        self._push_scope(body, morph, self.current_label)
        r = self._render(body, morph)

        print(f"\n  {self.current_label}")
        print(f"  peak {r['peak_db']:.1f} dB | {PREVIEW_WAV}")
        print(f"  scores: {name_a}={self._score(self.current_a):.1f}  {name_b}={self._score(self.current_b):.1f}")
        return self

    def yes(self, name: str = None):
        """Liked it. Boost source scores, save body."""
        if not self.current_body:
            print("Nothing to approve. Roll first.")
            return self

        # Boost both sources
        self.scores[self.current_a] = self._score(self.current_a) + 1.0
        self.scores[self.current_b] = self._score(self.current_b) + 1.0
        self._save_prefs()

        # Save to vault
        body_name = name or self.current_body.name
        os.makedirs(VAULT_DIR, exist_ok=True)
        path = os.path.join(VAULT_DIR, f"{body_name}.json")
        with open(path, "w") as f:
            f.write(self.current_body.to_compiled_json())

        self.kept.append((self.current_label, body_name))
        print(f"  FROZEN → {path}")
        print(f"  {self.current_a} ↑{self._score(self.current_a):.0f}  {self.current_b} ↑{self._score(self.current_b):.0f}")
        return self

    def no(self):
        """Skip. Penalize source scores."""
        if not self.current_body:
            print("Nothing to skip. Roll first.")
            return self

        self.scores[self.current_a] = max(0.1, self._score(self.current_a) - 0.3)
        self.scores[self.current_b] = max(0.1, self._score(self.current_b) - 0.3)
        self._save_prefs()

        print(f"  skip. {self.current_a} ↓{self._score(self.current_a):.1f}  {self.current_b} ↓{self._score(self.current_b):.1f}")
        return self

    def morph(self, value: float):
        """Re-render at a different morph position."""
        if not self.current_body:
            print("Nothing loaded. Roll first.")
            return self
        self.current_morph = value
        self.current_label = self.current_label.rsplit("@", 1)[0] + f"@ M{int(value*100)}"
        self._push_scope(self.current_body, value, self.current_label)
        r = self._render(self.current_body, value)
        print(f"  morph → {int(value*100)} | peak {r['peak_db']:.1f} dB")
        return self

    def history(self):
        """Show kept bodies."""
        if not self.kept:
            print("  No bodies frozen yet.")
        for label, name in self.kept:
            print(f"  {name}: {label}")
        return self

    def top(self, n: int = 10):
        """Show highest-scored sources."""
        ranked = sorted(self.scores.items(), key=lambda x: -x[1])[:n]
        for key, score in ranked:
            print(f"  {score:5.1f}  {key}")
        return self
