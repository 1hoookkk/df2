# See Your Plugin — Phase 4 (AI layout *suggestions*) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Claude *propose* TRENCH UI layout changes (element rects, optional text style, and `rules` additions) as a separate **proposal file**, with a human in the loop who must explicitly **accept** before anything touches `ui_layout.json`. A proposal is applicable only if the resulting layout passes the phase-3 validator and touches **only** layout/readout-style fields of **known** element ids — never the curated panel artwork, never an unknown id. Accepting writes `ui_layout.json` atomically (which the plugin hot-reloads); rejecting deletes the proposal. The user drives; Claude assists.

**Architecture:** A pure Python core (`tools/ui_layout_proposal.py`) with three independent pure functions — `parse_proposal` (validate + normalize a proposal JSON), `apply_proposal` (current layout + accepted proposal → new layout, reusing the same merge/override and `rules` semantics as `trench::UiLayout` / the phase-3 resolver), and `gate_proposal` (run the new layout through the phase-3 validator and return PASS/FAIL with reasons). A thin CLI wrapper (`tools/ui_apply_proposal.py`) provides `--accept` (parse → apply → gate → atomic write of `ui_layout.json`) and `--reject` (delete the proposal). The plugin is **unchanged**: it already hot-reloads `ui_layout.json`, so "apply" is just an atomic file write. The proposal lives at `~/Documents/TRENCH/ui_layout.proposal.json` and `ui_layout.json` is never touched until accept.

**Tech Stack:** Python 3 (standard library only: `json`, `argparse`, `pathlib`, `tempfile`, `os`, `hashlib`, `copy`), pytest. Matches existing `tools/` patterns (`tools/packed_interp_report.py`: `from __future__ import annotations`, `pathlib.Path`, `ROOT = Path(__file__).resolve().parent.parent`, module docstring + `Usage:` block). No JUCE / no C++ change.

**depends-on:**
- **Phase 1** — `juce-shell/source/UiLayout.h` (the `ui_layout.json` schema: `version`, `sourceSpace`, `elements[id].rect`, optional `fontSize`/`textColor`, optional `groups`/`rules`; `uiLayoutFile()` → `~/Documents/TRENCH/ui_layout.json`; the plugin hot-reloads this file on its 24 Hz timer). The known element id set is fixed by `UiLayout::defaults()`: `morphWheel`, `qWheel`, `typeSelector`, `morphReadout`, `qReadout`.
- **Phase 3** — the render/scene/validator engine. This plan **consumes** its artifacts and does not reimplement them. Phase-3 DoD (see `docs/superpowers/specs/2026-06-19-trench-ui-layout-loop-design.md` "Definition of done (phase 3)") produces, under `~/Documents/TRENCH/`:
  - `scene.json` — structured per-element truth (`id`, `sourceRect`, `editorRect`, `visible`, `zIndex`, `acceptsMouse`, `text`, `fontSize`, `textColour`), sourced from the editor's `getUiDebugTree()`.
  - `validation.json` — validator output (overlap, off-canvas, missing/malformed rect, text clip, **curated-art-hash change**, rule violations) as a blunt PASS/FAIL + reasons.
  - The **validator** and **resolver** logic (the phase-3 plan, when written, will name its validator entry point — this plan references it as the "phase-3 validator" and pins the contract below so it can be wired to whatever phase 3 ships).
  - **Pinned validator contract (this plan depends on, phase 3 must satisfy):** a callable that takes a layout dict (the `ui_layout.json` shape) and an optional `scene.json` dict and returns `{"status": "PASS"|"FAIL", "reasons": [str, ...]}`. If phase 3 ships only a CLI, this plan's gate shells out to it and parses `validation.json`; if it ships an importable function, the gate imports it. **Both wirings are implemented behind one adapter (`run_validator`) so the choice is a one-function change.** Until phase 3 lands, `run_validator` uses a **built-in fallback validator** (overlap + off-canvas + known-id + rect-shape) that is a strict subset of the phase-3 checks, so this phase is testable and safe standalone and tightens automatically when phase 3 is wired.

**Scope note (in):** the proposal format; pure parse/apply/gate; the accept/reject CLI; the hard constraint that suggestions may only change layout (rects/`rules`) + readout text style of **known** ids and may **never** change curated art (enforced by a structural allow-list *and* the validator's curated-art-hash check); atomic, corruption-proof writes with last-good fallback; evidence-referencing rationale.
**Scope note (out):** the edit mode (phase 2); the render/scene/validator **internals** (phase 3 — consumed, not built); the Inspect schematic; generating any DSP / bodies / coefficients. This plan writes **no** poles, zeros, or `.body240` bytes.

---

## Why CLI + Python (decision, justified)

- **Pure data over JSON.** Parse/apply/gate are pure transforms over the `ui_layout.json` shape and `scene.json`. No audio, no JUCE types, no packed math. Python + pytest is the lightest place to TDD them and matches `tools/` (`packed_interp_report.py` style).
- **Lowest-friction accept/reject.** An in-plugin "proposal preview overlay with accept/reject keys" would require C++ work in `PluginEditor`, a rebuild to test, and duplicating the validator into C++. A CLI needs none of that: the plugin **already hot-reloads `ui_layout.json`**, so accept = atomic write of that file and the running plugin shows the result within one 24 Hz tick. Reject = delete one file. This is the minimal complete loop.
- **Reuse, not re-derive (engineering doctrine).** The merge/override semantics already exist in `UiLayout::fromJson` (rect required, style optional, unknown id ignored) and the `rules` semantics in the phase-3 resolver. `apply_proposal` mirrors them; the gate **calls** the phase-3 validator rather than reimplementing it.

**Accept/reject mechanism chosen:** a CLI — `tools/ui_apply_proposal.py --accept` (parse → apply → gate → atomic write `ui_layout.json`, plugin hot-reloads) and `--reject` (delete the proposal). Language: **Python** (`tools/`, pytest).

---

## The proposal format (`ui_layout.proposal.json`)

Location: `~/Documents/TRENCH/ui_layout.proposal.json` (same dir as `ui_layout.json`). Claude writes it; the CLI reads it; `ui_layout.json` is untouched until `--accept`.

```json
{
  "version": 1,
  "kind": "ui-layout-proposal",
  "baseLayoutSha256": "<sha256 of the ui_layout.json this was authored against>",
  "summary": "Align the two readouts to the same width and vertically center each on its wheel.",
  "changes": [
    {
      "element": "qReadout",
      "set": { "rect": [603, 889, 168, 79] },
      "rationale": "validation.json: 'qReadout is 1 source px wider than morphReadout (rule sameWidth)'. scene.json morphReadout.sourceRect width = 168; matching it."
    },
    {
      "element": "morphReadout",
      "set": { "fontSize": 14 },
      "rationale": "scene.json morphReadout.text='100.0' at fontSize 13 measured 2 px from clip per validation.json text-clip note; bumping size needs the extra width above, kept within rect."
    }
  ],
  "addRules": [
    { "type": "sameWidth", "elements": ["morphReadout", "qReadout"],
      "rationale": "validation.json flagged sameWidth violation; declaring the rule so the resolver/validator hold it going forward." }
  ]
}
```

Rules of the format (enforced by `parse_proposal`):

- `version` must be `1`; `kind` must be `"ui-layout-proposal"`. Anything else → reject (this is not a `ui_layout.json`).
- `baseLayoutSha256` (optional but recommended): sha256 of the `ui_layout.json` the proposal targets. On accept, if present and it does **not** match the current `ui_layout.json`, **reject** (the layout moved under the proposal — stale, must re-author). Prevents clobbering a hand-edit.
- `summary`: required, non-empty string (the human reads this to decide).
- `changes`: list. Each item:
  - `element`: must be one of the **known ids** (`morphWheel`, `qWheel`, `typeSelector`, `morphReadout`, `qReadout`). Unknown id → reject.
  - `set`: object whose keys are a subset of the **allow-list** `{"rect", "fontSize", "textColor"}` **only**. Any other key (e.g. `image`, `panel`, `art`, `texture`, `color` on a non-readout, anything) → reject. `rect` must be 4 finite numbers with w,h > 0; `fontSize` finite > 0; `textColor` a 1–8 char hex string. (Mirrors `UiLayout` validation exactly.)
  - `rationale`: required, non-empty string. Convention: cite `scene.json` / `validation.json` facts (numbers), not vibes. (Enforced as non-empty; evidence quality is a human-review gate, but the format demands the field.)
- `addRules`: optional list. Each: `type` ∈ `{sameX, sameY, sameWidth, sameHeight, centerY, centerX}` (the phase-3 supported set), plus the rule's element refs (`elements` for the symmetric rules, `a`/`b` for `centerX`/`centerY`), each ref a **known id**, plus a non-empty `rationale`. Unknown rule type or unknown id ref → reject.
- There is **no** field that can express "change the panel artwork" — the format has no such key, and any unrecognized key is rejected. Curated art is structurally unreachable.

---

## File Structure

- **Create** `tools/ui_layout_proposal.py` — pure core: `KNOWN_IDS`, `ALLOWED_SET_KEYS`, `ALLOWED_RULE_TYPES`, `ProposalError`, `parse_proposal(obj) -> dict`, `apply_proposal(layout, proposal) -> dict`, `run_validator(layout, scene) -> dict` (phase-3 adapter + built-in fallback), `gate_proposal(layout, proposal, scene) -> dict`, `sha256_of_layout(layout) -> str`. No I/O, no `argparse`.
- **Create** `tools/ui_apply_proposal.py` — thin CLI over the core: `--accept` / `--reject`, file paths, atomic write, exit codes. The only module that touches the filesystem.
- **Create** `tools/tests/test_ui_layout_proposal.py` — pytest for the three pure functions + the hard-constraint rejections.
- **Create** `tools/tests/test_ui_apply_proposal_cli.py` — pytest driving the CLI as a subprocess against a temp `~/Documents/TRENCH` (atomic write, last-good fallback, reject deletes, stale-base rejection).

Conventions for every command below: run from repo root `C:\Users\hooki\df2`. Tests use a temp dir, never the real `~/Documents/TRENCH`.

---

## Task 1: `parse_proposal` — strict format validation (the security gate)

**Files:**
- Create: `tools/ui_layout_proposal.py`
- Test: `tools/tests/test_ui_layout_proposal.py`

- [ ] **Step 1: Write the failing test**

Create `tools/tests/test_ui_layout_proposal.py`:

```python
"""Tests for the pure UI-layout proposal core (parse / apply / gate)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.ui_layout_proposal import (  # noqa: E402
    ProposalError,
    parse_proposal,
)


def _good_proposal() -> dict:
    return {
        "version": 1,
        "kind": "ui-layout-proposal",
        "summary": "Match readout widths.",
        "changes": [
            {
                "element": "qReadout",
                "set": {"rect": [603, 889, 168, 79]},
                "rationale": "validation.json: qReadout 1px wider than morphReadout.",
            }
        ],
    }


def test_parse_accepts_a_well_formed_proposal():
    parsed = parse_proposal(_good_proposal())
    assert parsed["changes"][0]["element"] == "qReadout"
    assert parsed["changes"][0]["set"]["rect"] == [603.0, 889.0, 168.0, 79.0]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update({"version": 2}),
        lambda p: p.update({"kind": "ui_layout"}),
        lambda p: p.update({"summary": ""}),
        lambda p: p.pop("summary"),
        lambda p: p.update({"changes": "not-a-list"}),
    ],
)
def test_parse_rejects_bad_envelope(mutate):
    p = _good_proposal()
    mutate(p)
    with pytest.raises(ProposalError):
        parse_proposal(p)


def test_parse_rejects_unknown_element_id():
    p = _good_proposal()
    p["changes"][0]["element"] = "panelArtwork"
    with pytest.raises(ProposalError) as e:
        parse_proposal(p)
    assert "unknown element" in str(e.value).lower()


@pytest.mark.parametrize("bad_key", ["image", "panel", "art", "texture", "background", "src"])
def test_parse_rejects_non_allowlisted_set_key_curated_art_unreachable(bad_key):
    p = _good_proposal()
    p["changes"][0]["set"] = {bad_key: "anything.png"}
    with pytest.raises(ProposalError) as e:
        parse_proposal(p)
    assert "not allowed" in str(e.value).lower()


def test_parse_rejects_missing_or_empty_rationale():
    p = _good_proposal()
    p["changes"][0]["rationale"] = ""
    with pytest.raises(ProposalError):
        parse_proposal(p)
    p["changes"][0].pop("rationale")
    with pytest.raises(ProposalError):
        parse_proposal(p)


@pytest.mark.parametrize(
    "rect",
    [[1, 2, 3], [1, 2, 3, 4, 5], [1, 2, 0, 4], [1, 2, 4, -1], ["a", 2, 3, 4],
     [1, 2, float("inf"), 4]],
)
def test_parse_rejects_bad_rect(rect):
    p = _good_proposal()
    p["changes"][0]["set"] = {"rect": rect}
    with pytest.raises(ProposalError):
        parse_proposal(p)


def test_parse_rejects_bad_fontsize_and_textcolor():
    p = _good_proposal()
    p["changes"][0]["set"] = {"fontSize": 0}
    with pytest.raises(ProposalError):
        parse_proposal(p)
    p["changes"][0]["set"] = {"textColor": "xyz"}
    with pytest.raises(ProposalError):
        parse_proposal(p)
    p["changes"][0]["set"] = {"textColor": "deadbeef00"}  # too long
    with pytest.raises(ProposalError):
        parse_proposal(p)


def test_parse_rejects_addrule_unknown_type_or_id():
    p = _good_proposal()
    p["addRules"] = [{"type": "magic", "elements": ["morphReadout", "qReadout"],
                      "rationale": "x"}]
    with pytest.raises(ProposalError):
        parse_proposal(p)
    p["addRules"] = [{"type": "sameWidth", "elements": ["morphReadout", "ghost"],
                      "rationale": "x"}]
    with pytest.raises(ProposalError):
        parse_proposal(p)


def test_parse_rejects_non_object():
    with pytest.raises(ProposalError):
        parse_proposal([1, 2, 3])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tools/tests/test_ui_layout_proposal.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.ui_layout_proposal'` (core does not exist yet).

- [ ] **Step 3: Implement `parse_proposal`**

Create `tools/ui_layout_proposal.py`:

```python
#!/usr/bin/env python3
"""Pure core for TRENCH AI layout *suggestions* (phase 4).

Three pure functions, no I/O:
  parse_proposal(obj)            -> normalized proposal dict   (strict validation)
  apply_proposal(layout, prop)   -> new ui_layout.json dict    (merge/override)
  gate_proposal(layout, prop, scene) -> {"status", "reasons", "layout"}

A proposal may only change layout (rect / rules) and readout text style
(fontSize / textColor) of KNOWN element ids. There is no field that can change
the curated panel artwork; any non-allow-listed key is rejected. See CLAUDE.md
and the spec non-goal "AI auto-restyle of the look".
"""
from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any

# Fixed by juce-shell/source/UiLayout.h :: UiLayout::defaults().
KNOWN_IDS = ("morphWheel", "qWheel", "typeSelector", "morphReadout", "qReadout")

# The ONLY per-element fields a proposal may set. Curated art is unreachable.
ALLOWED_SET_KEYS = ("rect", "fontSize", "textColor")

# Phase-3 supported rule types.
ALLOWED_RULE_TYPES = ("sameX", "sameY", "sameWidth", "sameHeight", "centerY", "centerX")
_PAIR_RULES = ("centerY", "centerX")  # use a/b instead of elements


class ProposalError(ValueError):
    """A proposal is malformed or attempts a forbidden change. Never applied."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ProposalError(msg)


def _finite_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _validate_rect(rect: Any) -> list[float]:
    _require(isinstance(rect, list) and len(rect) == 4, "rect must be a list of 4 numbers")
    _require(all(_finite_number(v) for v in rect), "rect values must be finite numbers")
    vals = [float(v) for v in rect]
    _require(vals[2] > 0.0 and vals[3] > 0.0, "rect width and height must be > 0")
    return vals


def _validate_textcolor(value: Any) -> str:
    _require(isinstance(value, str), "textColor must be a hex string")
    s = value.strip()
    _require(1 <= len(s) <= 8, "textColor must be 1-8 hex chars")
    _require(all(c in "0123456789abcdefABCDEF" for c in s), "textColor must be hex")
    return s


def _validate_set(set_obj: Any) -> dict:
    _require(isinstance(set_obj, dict) and len(set_obj) > 0, "'set' must be a non-empty object")
    out: dict[str, Any] = {}
    for key, value in set_obj.items():
        _require(
            key in ALLOWED_SET_KEYS,
            f"set key '{key}' is not allowed (only {ALLOWED_SET_KEYS}); "
            "curated artwork can never be changed",
        )
        if key == "rect":
            out["rect"] = _validate_rect(value)
        elif key == "fontSize":
            _require(_finite_number(value) and float(value) > 0.0, "fontSize must be finite > 0")
            out["fontSize"] = float(value)
        else:  # textColor
            out["textColor"] = _validate_textcolor(value)
    return out


def _validate_change(change: Any) -> dict:
    _require(isinstance(change, dict), "each change must be an object")
    element = change.get("element")
    _require(element in KNOWN_IDS, f"unknown element id '{element}'")
    rationale = change.get("rationale")
    _require(isinstance(rationale, str) and rationale.strip() != "",
             f"change for '{element}' needs a non-empty rationale")
    return {"element": element, "set": _validate_set(change.get("set")),
            "rationale": rationale}


def _validate_rule(rule: Any) -> dict:
    _require(isinstance(rule, dict), "each rule must be an object")
    rtype = rule.get("type")
    _require(rtype in ALLOWED_RULE_TYPES, f"unknown rule type '{rtype}'")
    rationale = rule.get("rationale")
    _require(isinstance(rationale, str) and rationale.strip() != "",
             "each addRule needs a non-empty rationale")
    out: dict[str, Any] = {"type": rtype, "rationale": rationale}
    if rtype in _PAIR_RULES:
        a, b = rule.get("a"), rule.get("b")
        _require(a in KNOWN_IDS and b in KNOWN_IDS, f"{rtype} a/b must be known ids")
        out["a"], out["b"] = a, b
    else:
        elements = rule.get("elements")
        _require(isinstance(elements, list) and len(elements) >= 2,
                 f"{rtype} needs an 'elements' list of >= 2 ids")
        _require(all(e in KNOWN_IDS for e in elements),
                 f"{rtype} elements must all be known ids")
        out["elements"] = list(elements)
    return out


def parse_proposal(obj: Any) -> dict:
    """Validate + normalize a proposal. Raise ProposalError on anything wrong."""
    _require(isinstance(obj, dict), "proposal must be a JSON object")
    _require(obj.get("version") == 1, "proposal version must be 1")
    _require(obj.get("kind") == "ui-layout-proposal",
             "proposal kind must be 'ui-layout-proposal'")
    summary = obj.get("summary")
    _require(isinstance(summary, str) and summary.strip() != "",
             "proposal needs a non-empty summary")

    changes_in = obj.get("changes")
    _require(isinstance(changes_in, list), "'changes' must be a list")
    changes = [_validate_change(c) for c in changes_in]

    rules_in = obj.get("addRules", [])
    _require(isinstance(rules_in, list), "'addRules' must be a list")
    add_rules = [_validate_rule(r) for r in rules_in]

    _require(len(changes) > 0 or len(add_rules) > 0,
             "proposal must contain at least one change or rule")

    out: dict[str, Any] = {
        "version": 1,
        "kind": "ui-layout-proposal",
        "summary": summary,
        "changes": changes,
        "addRules": add_rules,
    }
    base = obj.get("baseLayoutSha256")
    if base is not None:
        _require(isinstance(base, str) and base.strip() != "",
                 "baseLayoutSha256 must be a non-empty string when present")
        out["baseLayoutSha256"] = base.strip()
    return out
```

- [ ] **Step 4: Re-run, expect PASS**

Run: `python -m pytest tools/tests/test_ui_layout_proposal.py -q`
Expected: all `parse_proposal` tests PASS (apply/gate tests are added in Tasks 2–3).

---

## Task 2: `apply_proposal` + `sha256_of_layout` — pure merge

**Files:**
- Modify: `tools/ui_layout_proposal.py`
- Modify: `tools/tests/test_ui_layout_proposal.py`

- [ ] **Step 1: Add failing tests**

Append to `tools/tests/test_ui_layout_proposal.py`:

```python
from tools.ui_layout_proposal import apply_proposal, sha256_of_layout  # noqa: E402


def _seed_layout() -> dict:
    # Equals juce-shell/source/UiLayout.h defaults.
    return {
        "version": 1,
        "sourceSpace": [1024, 1591],
        "elements": {
            "morphWheel": {"rect": [127, 694, 423, 101]},
            "qWheel": {"rect": [127, 871, 423, 101]},
            "typeSelector": {"rect": [230, 142, 672, 73]},
            "morphReadout": {"rect": [603, 712, 168, 77]},
            "qReadout": {"rect": [602, 889, 169, 79]},
        },
    }


def test_apply_overrides_only_named_fields_and_is_pure():
    layout = _seed_layout()
    before = json.dumps(layout, sort_keys=True)
    prop = parse_proposal({
        "version": 1, "kind": "ui-layout-proposal", "summary": "x",
        "changes": [
            {"element": "qReadout", "set": {"rect": [603, 889, 168, 79]},
             "rationale": "match width"},
            {"element": "morphReadout", "set": {"fontSize": 14, "textColor": "ff112233"},
             "rationale": "bigger"},
        ],
    })
    new = apply_proposal(layout, prop)
    # input untouched (pure)
    assert json.dumps(layout, sort_keys=True) == before
    assert new["elements"]["qReadout"]["rect"] == [603.0, 889.0, 168.0, 79.0]
    assert new["elements"]["morphReadout"]["fontSize"] == 14.0
    assert new["elements"]["morphReadout"]["textColor"] == "ff112233"
    # morphReadout rect untouched, other elements untouched
    assert new["elements"]["morphReadout"]["rect"] == [603, 712, 168, 77]
    assert new["elements"]["morphWheel"]["rect"] == [127, 694, 423, 101]
    # never adds keys outside the allow-list
    assert set(new["elements"]["morphReadout"]) <= {"rect", "fontSize", "textColor"}


def test_apply_adds_rules_without_duplicating():
    layout = _seed_layout()
    prop = parse_proposal({
        "version": 1, "kind": "ui-layout-proposal", "summary": "x",
        "changes": [],
        "addRules": [
            {"type": "sameWidth", "elements": ["morphReadout", "qReadout"],
             "rationale": "validation.json sameWidth"},
        ],
    })
    new = apply_proposal(layout, prop)
    rules = new["rules"]
    assert {"type": "sameWidth", "elements": ["morphReadout", "qReadout"]} in rules
    # idempotent: applying same rule again does not duplicate
    again = apply_proposal(new, prop)
    assert again["rules"].count(
        {"type": "sameWidth", "elements": ["morphReadout", "qReadout"]}) == 1


def test_sha256_is_stable_under_key_order():
    a = sha256_of_layout(_seed_layout())
    reordered = {"elements": _seed_layout()["elements"],
                 "sourceSpace": [1024, 1591], "version": 1}
    assert sha256_of_layout(reordered) == a
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tools/tests/test_ui_layout_proposal.py -q`
Expected: FAIL — `ImportError: cannot import name 'apply_proposal'`.

- [ ] **Step 3: Implement**

Append to `tools/ui_layout_proposal.py`:

```python
def sha256_of_layout(layout: dict) -> str:
    """Canonical sha256 of a layout dict (key-order independent)."""
    canonical = json.dumps(layout, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _rule_key(rule: dict) -> tuple:
    if rule["type"] in _PAIR_RULES:
        return (rule["type"], rule["a"], rule["b"])
    return (rule["type"], tuple(rule["elements"]))


def apply_proposal(layout: dict, proposal: dict) -> dict:
    """current layout + a parsed proposal -> new layout dict. Pure (deep-copies).

    Mirrors UiLayout::fromJson override semantics: rect/style overrides only;
    known ids only (parse_proposal already guaranteed that). Appends addRules,
    skipping any already present. Never adds a key outside the allow-list.
    """
    result = deepcopy(layout)
    elements = result.setdefault("elements", {})

    for change in proposal["changes"]:
        el = elements.setdefault(change["element"], {})
        for key, value in change["set"].items():  # key in ALLOWED_SET_KEYS
            el[key] = deepcopy(value)

    if proposal["addRules"]:
        existing = result.setdefault("rules", [])
        seen = {_rule_key(_normalize_existing_rule(r)) for r in existing
                if _is_recognized_rule(r)}
        for rule in proposal["addRules"]:
            emitted = {"type": rule["type"]}
            if rule["type"] in _PAIR_RULES:
                emitted["a"], emitted["b"] = rule["a"], rule["b"]
            else:
                emitted["elements"] = list(rule["elements"])
            if _rule_key(emitted) not in seen:
                existing.append(emitted)
                seen.add(_rule_key(emitted))

    return result


def _is_recognized_rule(rule: Any) -> bool:
    return isinstance(rule, dict) and rule.get("type") in ALLOWED_RULE_TYPES


def _normalize_existing_rule(rule: dict) -> dict:
    out = {"type": rule["type"]}
    if rule["type"] in _PAIR_RULES:
        out["a"], out["b"] = rule.get("a"), rule.get("b")
    else:
        out["elements"] = list(rule.get("elements", []))
    return out
```

- [ ] **Step 4: Re-run, expect PASS**

Run: `python -m pytest tools/tests/test_ui_layout_proposal.py -q`
Expected: all tests PASS.

---

## Task 3: `run_validator` adapter + `gate_proposal` — the validation gate

**Files:**
- Modify: `tools/ui_layout_proposal.py`
- Modify: `tools/tests/test_ui_layout_proposal.py`

- [ ] **Step 1: Add failing tests**

Append to `tools/tests/test_ui_layout_proposal.py`:

```python
from tools.ui_layout_proposal import gate_proposal  # noqa: E402


def test_gate_passes_a_valid_proposal():
    layout = _seed_layout()
    prop = parse_proposal({
        "version": 1, "kind": "ui-layout-proposal", "summary": "nudge",
        "changes": [{"element": "qReadout", "set": {"rect": [603, 889, 168, 79]},
                     "rationale": "match width"}],
    })
    result = gate_proposal(layout, prop, scene=None)
    assert result["status"] == "PASS", result["reasons"]
    assert result["layout"]["elements"]["qReadout"]["rect"] == [603.0, 889.0, 168.0, 79.0]


def test_gate_rejects_proposal_that_causes_overlap():
    layout = _seed_layout()
    # Move qReadout to sit on top of morphReadout -> overlap -> FAIL.
    prop = parse_proposal({
        "version": 1, "kind": "ui-layout-proposal", "summary": "bad",
        "changes": [{"element": "qReadout", "set": {"rect": [603, 712, 168, 77]},
                     "rationale": "intentionally overlapping for the test"}],
    })
    result = gate_proposal(layout, prop, scene=None)
    assert result["status"] == "FAIL"
    assert any("overlap" in r.lower() for r in result["reasons"])


def test_gate_rejects_off_canvas_rect():
    layout = _seed_layout()
    prop = parse_proposal({
        "version": 1, "kind": "ui-layout-proposal", "summary": "bad",
        "changes": [{"element": "morphWheel", "set": {"rect": [2000, 694, 423, 101]},
                     "rationale": "off canvas"}],
    })
    result = gate_proposal(layout, prop, scene=None)
    assert result["status"] == "FAIL"
    assert any("canvas" in r.lower() or "off" in r.lower() for r in result["reasons"])
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tools/tests/test_ui_layout_proposal.py -q`
Expected: FAIL — `ImportError: cannot import name 'gate_proposal'`.

- [ ] **Step 3: Implement the validator adapter + gate**

Append to `tools/ui_layout_proposal.py`:

```python
# --- Phase-3 validator adapter -------------------------------------------------
# Pinned contract: run_validator(layout, scene) -> {"status": "PASS"|"FAIL",
# "reasons": [...]}. When phase 3 ships an importable validator, wire it here;
# until then the built-in fallback (a strict SUBSET of phase-3 checks) runs so
# this phase is safe and testable standalone. The gate NEVER passes a layout the
# validator would reject.

SOURCE_SPACE = (1024, 1591)


def _try_phase3_validator(layout: dict, scene: Any) -> dict | None:
    """Import and call the phase-3 validator if present; else None."""
    try:
        from tools.ui_layout_validator import validate_layout  # type: ignore
    except Exception:
        return None
    try:
        result = validate_layout(layout, scene)
        if isinstance(result, dict) and "status" in result:
            result.setdefault("reasons", [])
            return result
    except Exception as exc:  # validator errored -> treat as FAIL, never pass
        return {"status": "FAIL", "reasons": [f"phase-3 validator raised: {exc}"]}
    return None


def _fallback_validator(layout: dict, scene: Any) -> dict:
    """Subset of phase-3 checks: known-id, rect shape, off-canvas, overlap."""
    reasons: list[str] = []
    elements = layout.get("elements", {})
    rects: dict[str, tuple[float, float, float, float]] = {}

    for el_id, el in elements.items():
        if el_id not in KNOWN_IDS:
            reasons.append(f"unknown element id '{el_id}' in layout")
            continue
        rect = el.get("rect")
        if not (isinstance(rect, list) and len(rect) == 4
                and all(_finite_number(v) for v in rect)
                and rect[2] > 0 and rect[3] > 0):
            reasons.append(f"{el_id} has a missing/malformed rect")
            continue
        x, y, w, h = (float(v) for v in rect)
        rects[el_id] = (x, y, w, h)
        if x < 0 or y < 0 or x + w > SOURCE_SPACE[0] or y + h > SOURCE_SPACE[1]:
            reasons.append(f"{el_id} rect is off the {SOURCE_SPACE} source canvas")

    ids = sorted(rects)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            ax, ay, aw, ah = rects[ids[i]]
            bx, by, bw, bh = rects[ids[j]]
            if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                reasons.append(f"{ids[i]} and {ids[j]} overlap")

    return {"status": "FAIL" if reasons else "PASS", "reasons": reasons}


def run_validator(layout: dict, scene: Any = None) -> dict:
    """Validate a layout. Prefer phase-3 validator; fall back to the subset."""
    phase3 = _try_phase3_validator(layout, scene)
    if phase3 is not None:
        return phase3
    return _fallback_validator(layout, scene)


def gate_proposal(layout: dict, proposal: dict, scene: Any = None) -> dict:
    """Apply the proposal, validate the result. Return status+reasons+layout.

    The returned 'layout' is applicable ONLY when status == PASS. Callers must
    not write it otherwise.
    """
    candidate = apply_proposal(layout, proposal)
    verdict = run_validator(candidate, scene)
    return {"status": verdict["status"], "reasons": verdict.get("reasons", []),
            "layout": candidate}
```

- [ ] **Step 4: Re-run, expect PASS**

Run: `python -m pytest tools/tests/test_ui_layout_proposal.py -q`
Expected: all tests PASS.

---

## Task 4: The accept/reject CLI — `tools/ui_apply_proposal.py`

**Files:**
- Create: `tools/ui_apply_proposal.py`
- Test: `tools/tests/test_ui_apply_proposal_cli.py`

- [ ] **Step 1: Write the failing CLI test**

Create `tools/tests/test_ui_apply_proposal_cli.py`:

```python
"""End-to-end tests for the accept/reject CLI (runs as a subprocess)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CLI = ROOT / "tools" / "ui_apply_proposal.py"


def _seed_layout() -> dict:
    return {
        "version": 1,
        "sourceSpace": [1024, 1591],
        "elements": {
            "morphWheel": {"rect": [127, 694, 423, 101]},
            "qWheel": {"rect": [127, 871, 423, 101]},
            "typeSelector": {"rect": [230, 142, 672, 73]},
            "morphReadout": {"rect": [603, 712, 168, 77]},
            "qReadout": {"rect": [602, 889, 169, 79]},
        },
    }


def _write(p: Path, obj: dict) -> None:
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _run(args, trench_dir):
    return subprocess.run(
        [sys.executable, str(CLI), "--trench-dir", str(trench_dir), *args],
        capture_output=True, text=True,
    )


def _good_proposal() -> dict:
    return {
        "version": 1, "kind": "ui-layout-proposal", "summary": "match width",
        "changes": [{"element": "qReadout", "set": {"rect": [603, 889, 168, 79]},
                     "rationale": "validation.json sameWidth"}],
    }


def test_accept_writes_layout_and_clears_proposal(tmp_path):
    d = tmp_path / "TRENCH"
    d.mkdir()
    _write(d / "ui_layout.json", _seed_layout())
    _write(d / "ui_layout.proposal.json", _good_proposal())

    r = _run(["--accept"], d)
    assert r.returncode == 0, r.stderr
    layout = json.loads((d / "ui_layout.json").read_text())
    assert layout["elements"]["qReadout"]["rect"] == [603.0, 889.0, 168.0, 79.0]
    # proposal consumed
    assert not (d / "ui_layout.proposal.json").exists()


def test_accept_rejects_overlap_and_leaves_layout_untouched(tmp_path):
    d = tmp_path / "TRENCH"
    d.mkdir()
    _write(d / "ui_layout.json", _seed_layout())
    before = (d / "ui_layout.json").read_text()
    bad = _good_proposal()
    bad["changes"][0]["set"]["rect"] = [603, 712, 168, 77]  # overlap morphReadout
    _write(d / "ui_layout.proposal.json", bad)

    r = _run(["--accept"], d)
    assert r.returncode != 0
    assert "FAIL" in (r.stdout + r.stderr)
    # layout NOT changed, proposal NOT deleted (so user can fix it)
    assert (d / "ui_layout.json").read_text() == before
    assert (d / "ui_layout.proposal.json").exists()


def test_accept_rejects_curated_art_touch(tmp_path):
    d = tmp_path / "TRENCH"
    d.mkdir()
    _write(d / "ui_layout.json", _seed_layout())
    before = (d / "ui_layout.json").read_text()
    bad = _good_proposal()
    bad["changes"][0]["set"] = {"image": "evil_panel.png"}
    _write(d / "ui_layout.proposal.json", bad)

    r = _run(["--accept"], d)
    assert r.returncode != 0
    assert "not allowed" in (r.stdout + r.stderr).lower()
    assert (d / "ui_layout.json").read_text() == before


def test_accept_rejects_stale_base_sha(tmp_path):
    d = tmp_path / "TRENCH"
    d.mkdir()
    _write(d / "ui_layout.json", _seed_layout())
    before = (d / "ui_layout.json").read_text()
    p = _good_proposal()
    p["baseLayoutSha256"] = "0" * 64  # does not match current layout
    _write(d / "ui_layout.proposal.json", p)

    r = _run(["--accept"], d)
    assert r.returncode != 0
    assert "stale" in (r.stdout + r.stderr).lower() or "base" in (r.stdout + r.stderr).lower()
    assert (d / "ui_layout.json").read_text() == before


def test_accept_with_malformed_proposal_does_not_corrupt_layout(tmp_path):
    d = tmp_path / "TRENCH"
    d.mkdir()
    _write(d / "ui_layout.json", _seed_layout())
    before = (d / "ui_layout.json").read_text()
    (d / "ui_layout.proposal.json").write_text("{ this is not json", encoding="utf-8")

    r = _run(["--accept"], d)
    assert r.returncode != 0
    assert (d / "ui_layout.json").read_text() == before


def test_accept_with_missing_proposal_errors_cleanly(tmp_path):
    d = tmp_path / "TRENCH"
    d.mkdir()
    _write(d / "ui_layout.json", _seed_layout())
    r = _run(["--accept"], d)
    assert r.returncode != 0
    assert "no proposal" in (r.stdout + r.stderr).lower()


def test_reject_deletes_proposal_and_leaves_layout(tmp_path):
    d = tmp_path / "TRENCH"
    d.mkdir()
    _write(d / "ui_layout.json", _seed_layout())
    before = (d / "ui_layout.json").read_text()
    _write(d / "ui_layout.proposal.json", _good_proposal())

    r = _run(["--reject"], d)
    assert r.returncode == 0
    assert not (d / "ui_layout.proposal.json").exists()
    assert (d / "ui_layout.json").read_text() == before
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tools/tests/test_ui_apply_proposal_cli.py -q`
Expected: FAIL — every subprocess returns non-zero / file-not-found because `tools/ui_apply_proposal.py` does not exist.

- [ ] **Step 3: Implement the CLI**

Create `tools/ui_apply_proposal.py`:

```python
#!/usr/bin/env python3
"""Accept or reject an AI UI-layout proposal (phase 4).

A proposal at <trench-dir>/ui_layout.proposal.json is NEVER applied until the
user runs --accept. Accept = parse (strict) -> apply -> validate gate -> atomic
write of ui_layout.json (the running plugin hot-reloads it) -> delete proposal.
Reject = delete the proposal, layout untouched.

ui_layout.json is never partially written and never corrupted: the write is
atomic (temp file + os.replace) and only happens after the gate PASSES.

Usage:
    python tools/ui_apply_proposal.py --accept
    python tools/ui_apply_proposal.py --reject
    python tools/ui_apply_proposal.py --accept --trench-dir /path/to/TRENCH
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.ui_layout_proposal import (  # noqa: E402
    ProposalError,
    gate_proposal,
    parse_proposal,
    sha256_of_layout,
)


def default_trench_dir() -> Path:
    # Mirrors juce::File::userDocumentsDirectory / "TRENCH" (uiLayoutFile()).
    return Path.home() / "Documents" / "TRENCH"


def _atomic_write_json(path: Path, obj: dict) -> None:
    """Write JSON atomically: temp file in the same dir + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)  # atomic on the same filesystem
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_accept(trench_dir: Path) -> int:
    layout_path = trench_dir / "ui_layout.json"
    proposal_path = trench_dir / "ui_layout.proposal.json"

    if not proposal_path.exists():
        print(f"ERROR: no proposal at {proposal_path}", file=sys.stderr)
        return 2
    if not layout_path.exists():
        print(f"ERROR: no ui_layout.json at {layout_path}", file=sys.stderr)
        return 2

    try:
        layout = _load_json(layout_path)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: cannot read current layout: {exc}", file=sys.stderr)
        return 2

    try:
        raw = _load_json(proposal_path)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: proposal is not valid JSON: {exc}", file=sys.stderr)
        return 3

    try:
        proposal = parse_proposal(raw)
    except ProposalError as exc:
        print(f"REJECTED (malformed/forbidden proposal): {exc}", file=sys.stderr)
        return 3

    base = proposal.get("baseLayoutSha256")
    if base is not None and base != sha256_of_layout(layout):
        print("REJECTED: stale baseLayoutSha256 — the layout changed since this "
              "proposal was authored. Re-author against the current layout.",
              file=sys.stderr)
        return 4

    # optional scene.json from phase 3 (used by the validator when present)
    scene = None
    scene_path = trench_dir / "scene.json"
    if scene_path.exists():
        try:
            scene = _load_json(scene_path)
        except (json.JSONDecodeError, OSError):
            scene = None  # missing/broken scene -> validator uses geometry only

    result = gate_proposal(layout, proposal, scene)
    if result["status"] != "PASS":
        print("REJECTED by validator (FAIL):", file=sys.stderr)
        for reason in result["reasons"]:
            print(f"  - {reason}", file=sys.stderr)
        return 5

    # Only now do we touch ui_layout.json, atomically.
    try:
        _atomic_write_json(layout_path, result["layout"])
    except OSError as exc:
        print(f"ERROR: failed to write layout (original left intact): {exc}",
              file=sys.stderr)
        return 6

    try:
        proposal_path.unlink()
    except OSError:
        pass  # layout is already applied; a lingering proposal is harmless

    print(f"ACCEPTED: {proposal['summary']}")
    print(f"Wrote {layout_path} ({len(proposal['changes'])} change(s), "
          f"{len(proposal['addRules'])} rule(s)). Plugin will hot-reload.")
    return 0


def cmd_reject(trench_dir: Path) -> int:
    proposal_path = trench_dir / "ui_layout.proposal.json"
    if not proposal_path.exists():
        print(f"Nothing to reject: no proposal at {proposal_path}")
        return 0
    try:
        proposal_path.unlink()
    except OSError as exc:
        print(f"ERROR: could not delete proposal: {exc}", file=sys.stderr)
        return 2
    print(f"REJECTED: deleted {proposal_path}. Layout untouched.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Accept or reject a UI-layout proposal.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--accept", action="store_true",
                       help="validate the proposal and, if it passes, write ui_layout.json")
    group.add_argument("--reject", action="store_true",
                       help="delete the proposal; leave ui_layout.json untouched")
    parser.add_argument("--trench-dir", type=Path, default=default_trench_dir(),
                        help="dir holding ui_layout.json + the proposal "
                             "(default: ~/Documents/TRENCH)")
    args = parser.parse_args(argv)

    if args.accept:
        return cmd_accept(args.trench_dir)
    return cmd_reject(args.trench_dir)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Re-run, expect PASS**

Run: `python -m pytest tools/tests/test_ui_apply_proposal_cli.py -q`
Expected: all CLI tests PASS.

---

## Task 5: Full suite + manual verification of the live loop

- [ ] **Step 1: Run the whole phase-4 suite**

Run: `python -m pytest tools/tests/test_ui_layout_proposal.py tools/tests/test_ui_apply_proposal_cli.py -q`
Expected output (counts may grow): `... passed in N.NNs`, zero failures.

- [ ] **Step 2: MANUAL — accept a real proposal into the running plugin**

Preconditions: phase 1 shipped (plugin hot-reloads `ui_layout.json`); `~/Documents/TRENCH/ui_layout.json` exists; the plugin is open in the DAW.

1. Author a proposal file. Run from repo root:
   ```bash
   python - <<'PY'
   import json, hashlib, pathlib
   d = pathlib.Path.home() / "Documents" / "TRENCH"
   layout = json.loads((d / "ui_layout.json").read_text())
   sha = hashlib.sha256(json.dumps(layout, sort_keys=True, separators=(",",":")).encode()).hexdigest()
   prop = {
     "version": 1, "kind": "ui-layout-proposal",
     "baseLayoutSha256": sha,
     "summary": "Nudge qReadout to match morphReadout width.",
     "changes": [{"element": "qReadout",
       "set": {"rect": [layout["elements"]["morphReadout"]["rect"][0],
                        layout["elements"]["qReadout"]["rect"][1],
                        layout["elements"]["morphReadout"]["rect"][2],
                        layout["elements"]["qReadout"]["rect"][3]]},
       "rationale": "morphReadout width from ui_layout.json; matching qReadout to it."}],
   }
   (d / "ui_layout.proposal.json").write_text(json.dumps(prop, indent=2))
   print("wrote proposal")
   PY
   ```
   Expected: `wrote proposal`. **Confirm** `ui_layout.json` is unchanged at this point (proposal authoring never touches it).

2. Accept it:
   ```bash
   python tools/ui_apply_proposal.py --accept
   ```
   Expected stdout: `ACCEPTED: Nudge qReadout ...` and `Wrote .../ui_layout.json ... Plugin will hot-reload.`; exit 0; the proposal file is gone.

3. **Observe in the plugin:** within ~1 second (one 24 Hz timer tick) the qReadout snaps to the new width. **Confirm** the curated panel artwork is visually identical (only the readout box moved). The wheels keep spinning and audio keeps running.

4. Reject path: write any proposal again, then `python tools/ui_apply_proposal.py --reject` → expected `REJECTED: deleted ...`; `ui_layout.json` unchanged; plugin unchanged.

- [ ] **Step 3: MANUAL — confirm a forbidden proposal is refused**

Write a proposal whose change `set` is `{"image": "anything.png"}`, run `--accept`. Expected: non-zero exit, stderr contains `not allowed`, `ui_layout.json` byte-identical, plugin unchanged. This is the curated-art guard firing.

---

## Self-Review

**Spec coverage:**
- Spec phasing item 4 "AI layout *suggestions* — propose rects/rule-fixes, gated by user accept — never auto-restyle curated art": delivered as a proposal file + accept/reject CLI; nothing reaches `ui_layout.json` without `--accept` (Task 4).
- Spec non-goal "AI auto-restyle of the look": the proposal format has **no** art/image/panel field; any non-allow-listed `set` key is rejected by `parse_proposal` (Task 1) and the change never reaches disk. Covered by `test_parse_rejects_non_allowlisted_set_key_curated_art_unreachable` and `test_accept_rejects_curated_art_touch`.
- Spec error-handling ("Malformed JSON → keep last good; never corrupt") and "atomic write": Task 4 parses before touching the layout, writes via temp-file + `os.replace`, and on any failure leaves `ui_layout.json` byte-identical (three CLI tests assert this).
- Reuse doctrine: `apply_proposal` mirrors `UiLayout::fromJson` override semantics; the gate **calls** the phase-3 validator (adapter `run_validator`) rather than reimplementing it, with a documented subset fallback so the phase is safe before phase 3 lands.
- Consumes phase-3 artifacts: `scene.json` (read on accept, fed to the validator) and the phase-3 validator (pinned contract); writes the phase-1 `ui_layout.json` the plugin hot-reloads.

**Placeholder scan:** every code block is complete and runnable — no `...`, no TODO, no stubbed function body. The phase-3 validator is reached through a real adapter with a real fallback (not a placeholder); when phase 3 ships `tools/ui_layout_validator.validate_layout`, `run_validator` picks it up with zero edits here.

**Consistency:** element id set (`morphWheel`, `qWheel`, `typeSelector`, `morphReadout`, `qReadout`), the style allow-list (`rect`, `fontSize`, `textColor`), the rule type set, source space `1024×1591`, and `~/Documents/TRENCH/` all match `juce-shell/source/UiLayout.h` and the spec schema. Tool style (`from __future__ import annotations`, `ROOT = Path(__file__).resolve().parent.parent`, module docstring + `Usage:`) matches `tools/packed_interp_report.py`.

**Validation / safety:** malformed proposals, unknown ids, bad rects/colors/sizes, unknown rule types, stale base sha, missing files, and non-JSON proposals are each rejected with a clear message and a distinct exit code, with `ui_layout.json` never partially written (atomic) and never written at all unless the validator returns PASS.

**Curated art can never be auto-restyled — explicit confirmation:** there are two independent guards, either of which alone blocks it. (1) Structural: the proposal schema exposes only `{rect, fontSize, textColor}` on known control ids; there is no field that names artwork, and any unrecognized key is a hard reject in `parse_proposal` before anything is applied. (2) Validator: on accept, the gate runs the phase-3 validator whose checks include the **curated-art hash unchanged** rule, so even a layout that somehow shifted panel pixels would FAIL and never be written. The accept path also writes only the layout JSON the plugin reads for rects/style — it never touches any PNG/asset. A human must still run `--accept`; Claude can only ever leave a proposal file for review.
