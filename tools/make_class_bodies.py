#!/usr/bin/env python3
"""make_class_bodies - author whole df2 bodies by FILTER TYPE, not by corner.

A body is a named FILTER TYPE (a "card"). Tyson picks a class + campaign and,
optionally, a reference body inside that class. Claude turns the card into the
hidden 4-corner response machine, generates many originals, culls the broken,
and renders an audition page where the ONLY producer action is KEEP / MAYBE /
REJECT. No poles, zeros, Q numbers, bandwidths, stages, coefficients, or
response editing on the producer surface.

  HOME       = M0_Q0          AWAY       = M100_Q0
  TIGHT HOME = M0_Q100        TIGHT AWAY = M100_Q100

This is a FRONT DOOR over the two engines that already exist
(tools/target_browser generation + tools/reference_brief). It invents no DSP.

Usage:
    python -m tools.make_class_bodies --list
    python -m tools.make_class_bodies --list-classes
    python -m tools.make_class_bodies --class EQ_CUT --campaign razor_shell --count 64 --seed 1001
    python -m tools.make_class_bodies --campaign small_talk --reference ooh_to_eee --count 48
    python -m tools.make_class_bodies --keep <run_dir> cand_07 --notes "why it wins"

Internal class taxonomy (E-mu-style, inspiration only, never product-facing):
    LPF HPF BPF EQ_BOOST EQ_CUT VOWEL PHASER FLANGER RESONANCE WAH DISTORTION
    SPECIAL_FX HYBRID
Clean-room: do not copy or ship legacy coefficients, packed words, ROM data,
exact curves, or preset names. Commercial release needs legal review.
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_HERE = str(Path(__file__).resolve().parent)
sys.path[:] = [p for p in sys.path if p not in ("", _HERE, str(ROOT))]
sys.path.insert(0, str(ROOT))

from tools import target_browser as tb
from tools import reference_brief as rb
from pyruntime import trench_ffi

CARDS = ROOT / "tools" / "filter_type_cards.json"
TEMPLATES = ROOT / "tools" / "target_templates.json"
KEEP_DIR = ROOT / "dev" / "tmp" / "keepers"


def load_cards():
    lib = json.loads(CARDS.read_text(encoding="utf-8"))
    classes = lib["classes"]
    cards = {c["campaign"]: c for c in lib["cards"]}
    return classes, cards


def load_templates():
    lib = json.loads(TEMPLATES.read_text(encoding="utf-8"))
    return {t["name"]: t for t in lib["templates"]}


def resolve_card(cards, campaign, klass):
    if campaign:
        if campaign not in cards:
            raise SystemExit(f"no campaign '{campaign}'. See --list.")
        card = cards[campaign]
        if klass and klass.upper() not in [c.upper() for c in card["classes"]]:
            print(f"note: campaign '{campaign}' is class {card['classes']}, not {klass}", file=sys.stderr)
        return card
    if klass:
        hits = [c for c in cards.values() if klass.upper() in [k.upper() for k in c["classes"]]]
        if not hits:
            raise SystemExit(f"no card in class {klass}. See --list-classes / --list.")
        if len(hits) > 1:
            names = ", ".join(c["campaign"] for c in hits)
            raise SystemExit(f"class {klass} has several cards ({names}). Add --campaign <name>.")
        return hits[0]
    raise SystemExit("pick a --campaign or --class. See --list.")


def enriched_spec(card, templates, seed):
    """Pull generation params from the named archetype, wear the card's musical framing."""
    tname = card["template"]
    if tname not in templates:
        raise SystemExit(f"card '{card['campaign']}' points at missing template '{tname}'")
    spec = dict(templates[tname])
    spec["name"] = card["campaign"]
    spec["label"] = card["name"]
    spec["listening_goal"] = card["job"]
    spec["failure_modes"] = card.get("avoid", spec.get("failure_modes", []))
    return spec


# ── card-framed audition page (purely musical — no DSP on the surface) ────────

def _card_header_html(card, classes):
    cls = " / ".join(card["classes"])
    rows = [
        ("Job", card["job"]),
        ("Move Morph", card["morph"]),
        ("Move Q", card["q"]),
        ("Good on", ", ".join(card.get("good_on", []))),
        ("Avoid", " · ".join(card.get("avoid", []))),
    ]
    body = "\n".join(f'<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>' for k, v in rows)
    return cls, body


def write_class_audition_page(run, card, classes, seed, count, survivors, published):
    cls, header = _card_header_html(card, classes)
    rel = run.as_posix()
    rows = []
    for idx, c in enumerate(survivors, 1):
        adv = [tb.GATE_WORDS[k] for k in c["gate"]["advisory_failed"]]
        warn = " · ".join(adv) if adv else "clean enough for ears"
        command = f"python -m tools.make_class_bodies --keep {rel} {c['name']} --notes \"\""
        rows.append(f"""
<section class="candidate" data-name="{html.escape(c['name'])}">
  <header>
    <div>
      <h2>Candidate {idx:02d}</h2>
      <p class="warn">{html.escape(warn)}</p>
    </div>
    <div class="vote">
      <button data-vote="KEEP">KEEP</button>
      <button data-vote="MAYBE">MAYBE</button>
      <button data-vote="REJECT">REJECT</button>
    </div>
  </header>
  <div class="clips">
    {tb.clip_players(c['name'])}
  </div>
  <textarea placeholder="producer notes"></textarea>
  <code>{html.escape(command)}</code>
</section>""")
    pub = ", ".join(published) if published else "none"
    doc = f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(card['name'])} — audition</title>
<style>
body{{margin:0;background:#080a0a;color:#eee9dc;font:14px/1.45 system-ui,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:24px 18px 56px}}
h1{{font-size:28px;margin:0 0 2px}}
.cls{{color:#f1c46a;font:12px ui-monospace,Consolas,monospace;letter-spacing:.06em;margin:0 0 12px}}
h2{{font-size:18px;margin:0 0 4px;color:#9fe7c6}}
.meta,.warn{{color:#a4aaa2;margin:0 0 5px}}
.card{{border:1px solid #2a3d34;background:#0d1110;border-radius:8px;padding:14px 16px;margin:8px 0 18px}}
.card table{{border-collapse:collapse;width:100%}}
.card th{{text-align:left;color:#f1d76a;font-weight:600;width:130px;vertical-align:top;padding:3px 8px 3px 0}}
.card td{{padding:3px 0;color:#dfe7e0}}
.candidate{{border:1px solid #20342d;background:#0d1110;border-radius:8px;padding:14px;margin:14px 0}}
header{{display:flex;gap:16px;align-items:flex-start;justify-content:space-between}}
.vote{{display:flex;gap:8px;flex-wrap:wrap}}
button{{background:#151a18;color:#eee9dc;border:1px solid #405247;border-radius:5px;padding:7px 10px;cursor:pointer}}
button.active[data-vote=KEEP]{{background:#17422c;border-color:#6ee7a8}}
button.active[data-vote=MAYBE]{{background:#433716;border-color:#e5c75f}}
button.active[data-vote=REJECT]{{background:#421d1d;border-color:#ff6d6d}}
.clips{{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px;margin-top:12px}}
label{{display:block;color:#f1d76a;font:12px ui-monospace,Consolas,monospace}}
label span{{color:#79827b;margin-left:8px}}
audio{{display:block;width:100%;margin-top:4px}}
textarea{{box-sizing:border-box;width:100%;min-height:54px;margin:12px 0 8px;background:#070908;color:#eee9dc;border:1px solid #28332d;border-radius:5px;padding:8px}}
code{{display:block;white-space:pre-wrap;color:#81d4ff;background:#070908;border:1px solid #18221d;border-radius:5px;padding:8px}}
@media(max-width:860px){{header{{display:block}}.vote{{margin-top:10px}}.clips{{grid-template-columns:1fr}}}}
</style>
<main>
  <h1>{html.escape(card['name'])}</h1>
  <p class="cls">{html.escape(cls)}</p>
  <div class="card"><table>{header}</table></div>
  <p class="meta">{len(survivors)} bodies to audition · seed={seed} · generated={count}. Listen to HOME / AWAY / TIGHT, then the Morph, Q and diagonal sweeps. Mark KEEP / MAYBE / REJECT. Buttons + notes save in this browser.</p>
  <p class="meta">Also playable in the Filter Factory PRESET list: {html.escape(pub)}</p>
  {''.join(rows) if rows else '<p class="meta">No survivors — every body broke a hard gate. Try another seed.</p>'}
</main>
<script>
const runKey = "make-class:{html.escape(card['campaign'])}:s{seed}";
for (const card of document.querySelectorAll(".candidate")) {{
  const name = card.dataset.name;
  const stateKey = runKey + ":" + name;
  const saved = JSON.parse(localStorage.getItem(stateKey) || "{{}}");
  const notes = card.querySelector("textarea");
  if (saved.notes) notes.value = saved.notes;
  function save(vote) {{
    localStorage.setItem(stateKey, JSON.stringify({{ vote, notes: notes.value }}));
    for (const b of card.querySelectorAll("button")) b.classList.toggle("active", b.dataset.vote === vote);
  }}
  if (saved.vote) save(saved.vote);
  for (const b of card.querySelectorAll("button")) b.onclick = () => save(b.dataset.vote);
  notes.oninput = () => {{
    const active = card.querySelector("button.active");
    save(active ? active.dataset.vote : "");
  }};
}}
</script>
"""
    (run / "audition.html").write_text(doc, encoding="utf-8")


# ── generate ─────────────────────────────────────────────────────────────────

def run_class_path(card, classes, templates, seed, count):
    spec = enriched_spec(card, templates, seed)
    print(f"FILTER TYPE  {card['name']}  [{' / '.join(card['classes'])}]  (archetype: {card['template']})")
    print(f"  job   : {card['job']}")
    print(f"  morph : {card['morph']}")
    print(f"  Q     : {card['q']}")
    print(f"\nGENERATE {count} bodies  seed={seed}")
    run, cands = tb.generate(spec, seed, count)
    survivors = [c for c in cands if c["gate"]["pass"]]
    broken = [c for c in cands if not c["gate"]["pass"]]
    published = tb.publish(spec, seed, survivors)
    _write_campaign(run, card, seed, count, reference=None)
    write_class_audition_page(run, card, classes, seed, count, survivors, published)
    for c in survivors:
        adv = " · ".join(tb.GATE_WORDS[k] for k in c["gate"]["advisory_failed"])
        print(f"  {c['name']}" + (f"   [heads-up: {adv}]" if adv else ""))
    print(f"\n{len(survivors)}/{count} survived ({len(broken)} broken culled).")
    print(f"audition -> {run / 'audition.html'}")
    print(f"Factory presets -> bodies/generated/gen_{card['campaign']}_s{seed}_NN.bin")
    print("NEXT: open the audition page, mark KEEP / MAYBE / REJECT, then:")
    print(f"  python -m tools.make_class_bodies --keep {run.as_posix()} <NN> --notes \"why\"")
    return run


def run_reference_path(card, seed, count):
    framing = {"campaign": card["campaign"], "label": card["name"],
               "job": card["job"], "avoid": card.get("avoid"), "classes": card["classes"]}
    print(f"FILTER TYPE  {card['name']}  [{' / '.join(card['classes'])}]  via reference brief")
    run = rb.run_brief(card.get("_reference"), seed, count, framing=framing)
    _write_campaign(run, card, seed, count, reference=card.get("_reference"))
    return run


def _write_campaign(run, card, seed, count, reference):
    (run / "campaign.json").write_text(json.dumps({
        "campaign": card["campaign"], "name": card["name"], "classes": card["classes"],
        "template": card["template"], "reference": reference, "seed": seed, "count": count,
    }, indent=2), encoding="utf-8")


# ── keep ──────────────────────────────────────────────────────────────────────

def do_keep(run_dir: Path, names, notes):
    if not run_dir.exists():
        print(f"run dir not found: {run_dir}", file=sys.stderr)
        return 1
    camp = {}
    cpath = run_dir / "campaign.json"
    if cpath.exists():
        camp = json.loads(cpath.read_text(encoding="utf-8"))
    # reference-path runs carry a brief — let reference_brief own those keepers
    if camp.get("reference") or (run_dir / "brief.json").exists():
        return rb.do_keep(run_dir, names, notes)

    KEEP_DIR.mkdir(parents=True, exist_ok=True)
    campaign = camp.get("campaign", "class")
    for name in names:
        name = name if name.startswith("cand_") else f"cand_{int(name):02d}"
        cdir = run_dir / name
        report = json.loads((cdir / "report.json").read_text(encoding="utf-8"))
        stem = f"{campaign}_s{report['seed']}_{name}"
        shutil.copy(cdir / f"{name}.body240", KEEP_DIR / f"{stem}.body240")
        shutil.copy(cdir / f"{name}.cart.json", KEEP_DIR / f"{stem}.cart.json")
        (KEEP_DIR / f"{stem}.keep.json").write_text(json.dumps({
            "kept_utc": datetime.now(timezone.utc).isoformat(),
            "filter_type": camp.get("name", campaign), "classes": camp.get("classes", []),
            "campaign": campaign, "seed": report["seed"], "index": report["index"],
            "provenance": report.get("provenance", ""),
            "reproduce": f"python -m tools.make_class_bodies --campaign {campaign} "
                         f"--seed {report['seed']} --count {report['index'] + 1}",
            "gate": report["gate"], "notes": notes}, indent=2), encoding="utf-8")
        print(f"  kept {stem}")
    print(f"\nkept -> {KEEP_DIR}")
    return 0


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--class", dest="klass", help="internal class (see --list-classes)")
    ap.add_argument("--campaign", help="filter type card (see --list)")
    ap.add_argument("--reference", nargs="?", const="", default=None,
                    help="optional reference inside the class. Bare flag uses the card's default inspiration; "
                         "or pass a slug (see reference_brief --list-refs).")
    ap.add_argument("--seed", type=int, default=1001)
    ap.add_argument("--count", type=int, default=48, help="bodies to generate (8-64)")
    ap.add_argument("--list", action="store_true", help="list the filter type cards")
    ap.add_argument("--list-classes", action="store_true", help="list the internal class taxonomy")
    ap.add_argument("--keep", nargs="+", metavar=("RUN_DIR", "CAND"))
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    classes, cards = load_cards()

    if args.list_classes:
        print("\nInternal class taxonomy (inspiration only — never product-facing):\n")
        for k, v in classes.items():
            print(f"  {k:<12} {v}")
        return 0

    if args.list:
        print("\nFilter type cards (v1):\n")
        for c in cards.values():
            print(f"  {c['campaign']:<18} {c['name']:<18} [{' / '.join(c['classes'])}]  — {c['job']}")
        return 0

    if args.keep:
        return do_keep(Path(args.keep[0]), args.keep[1:], args.notes)

    if not trench_ffi.available() or not trench_ffi.engine_available():
        print("trench-core not built. Run: cargo build --release -p trench-core", file=sys.stderr)
        return 1

    card = resolve_card(cards, args.campaign, args.klass)
    count = max(8, min(64, args.count))
    templates = load_templates()

    if args.reference is not None:
        ref = args.reference or card.get("reference_inspiration")
        if not ref:
            raise SystemExit(f"--reference given with no value and card '{card['campaign']}' has no default inspiration")
        card = dict(card, _reference=ref)
        run_reference_path(card, args.seed, count)
    else:
        run_class_path(card, classes, templates, args.seed, count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
