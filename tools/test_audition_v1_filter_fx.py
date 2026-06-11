import hashlib
import json
import wave
from html.parser import HTMLParser
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
AUDITION = ROOT / "dev" / "tmp" / "forge_v1_lineup" / "audition" / "manifest.json"


def _wav_peak(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
    samples = np.frombuffer(frames, dtype="<i2")
    return float(np.max(np.abs(samples)) / 32767.0) if samples.size else 0.0


class _AuditionHtml(HTMLParser):
    def __init__(self):
        super().__init__()
        self.audio_sources = []
        self.headings = []
        self._in_h2 = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "audio":
            self.audio_sources.append(attrs.get("src"))
        if tag == "h2":
            self._in_h2 = True

    def handle_endtag(self, tag):
        if tag == "h2":
            self._in_h2 = False

    def handle_data(self, data):
        if self._in_h2 and data.strip():
            self.headings.append(data.strip())


def test_v1_audition_pack_matches_canonical_bodies():
    manifest = json.loads(AUDITION.read_text(encoding="utf-8"))
    assert manifest["engine"] == "trench_ffi shipped engine path (AGC+saturate)"
    assert len(manifest["entries"]) == 6

    for entry in manifest["entries"]:
        body = (ROOT / entry["body240"]).read_bytes()
        assert len(body) == 240
        assert hashlib.sha256(body).hexdigest() == entry["body240_sha256"]

        for key in ("snapshots_wav", "sweep_wav"):
            wav = ROOT / entry[key]
            assert wav.exists(), key
            assert wav.stat().st_size > 1024
            assert _wav_peak(wav) > 0.05


def test_v1_audition_html_links_all_audio():
    html_path = AUDITION.parent / "audition.html"
    parser = _AuditionHtml()
    parser.feed(html_path.read_text(encoding="utf-8"))

    assert parser.headings == ["808 Tear", "Talking Mouth", "Epoch Bank", "Abyss Cut", "Warehouse Acid", "Needle Comb"]
    assert len(parser.audio_sources) == 12
    for source in parser.audio_sources:
        assert source
        assert (html_path.parent / source).exists()
