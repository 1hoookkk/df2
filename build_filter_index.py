"""Build filter index: inventory, dedup, decode, classify, report."""
from __future__ import annotations
import hashlib, json, math, struct, sys, re, csv
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pyruntime.packed_interp import words_to_coeffs, kernel_to_biquad, decode

CORNERS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
PAD_WORDS = (0xdfff, 0xffff, 0xdfff, 0xffff, 0xe000)
N_PTS = 256
F_MIN, F_MAX = 30.0, 19000.0
SR = 39062.5
BLOCKS = Path(r"C:\Users\hooki\df2\ref\x3_menu\runtime_blocks")

REPOS = [
    Path(r"C:\Users\hooki\df2-workstation"),
    Path(r"C:\Users\hooki\df2"),
    Path(r"C:\Users\hooki\surface-forge"),
    Path(r"C:\Users\hooki\trench-filters"),
]
OUT = Path(r"C:\Users\hooki\filter_index")

# ── archetype definitions ──────────────────────────────────────────────────────
ARCHETYPES = [
    ("2_pole_lowpass", "LPF", 1),
    ("4_pole_lowpass", "LPF", 2),
    ("6_pole_lowpass", "LPF", 3),
    ("2_pole_highpass", "HPF", 1),
    ("4_pole_highpass", "HPF", 2),
    ("2_pole_bandpass", "BPF", 1),
    ("4_pole_bandpass", "BPF", 2),
    ("contrary_bandpass", "BPF", 1),
    ("swept_eq_1_octave", "EQ", 1),
    ("swept_eq_2_1_octave", "EQ", 1),
    ("swept_eq_3_1_octave", "EQ", 1),
    ("phaser_1", "PHA", 2),
    ("phaser_2", "PHA", 2),
    ("bat_phaser", "PHA", 2),
    ("flanger_lite", "FLG", 3),
    ("vocal_ah_ay_ee", "VOW", 3),
    ("vocal_oo_ah", "VOW", 3),
]
ARCH_FAMILIES = {
    "2_pole_lowpass": "LPF", "4_pole_lowpass": "LPF", "6_pole_lowpass": "LPF",
    "2_pole_highpass": "HPF", "4_pole_highpass": "HPF",
    "2_pole_bandpass": "BPF", "4_pole_bandpass": "BPF", "contrary_bandpass": "BPF",
    "swept_eq_1_octave": "EQ", "swept_eq_2_1_octave": "EQ", "swept_eq_3_1_octave": "EQ",
    "phaser_1": "PHA", "phaser_2": "PHA", "bat_phaser": "PHA",
    "flanger_lite": "FLG",
    "vocal_ah_ay_ee": "VOW", "vocal_oo_ah": "VOW",
}

# ── frequency vector ───────────────────────────────────────────────────────────
FREQS = [F_MIN * (F_MAX / F_MIN) ** (i / (N_PTS - 1)) for i in range(N_PTS)]


def is_pad(words5: tuple[int, ...]) -> bool:
    return tuple(words5) == PAD_WORDS


def read_corner_words(data: bytes) -> list[list[tuple[int, ...]]]:
    w = struct.unpack("<120H", data)
    corners = []
    for c in range(4):
        stages = []
        for s in range(6):
            words = tuple(w[(c * 6 + s) * 5: (c * 6 + s) * 5 + 5])
            stages.append(words)
        corners.append(stages)
    return corners


def corner_db_response(stages: list[tuple[int, ...]]) -> tuple[list[float], float, list, list, float, int]:
    total = [0.0] * N_PTS
    max_pole_r = 0.0
    n_notches = 0
    n_resonances = 0
    notch_freqs = []
    peak_freqs = []
    n_active = 0
    for words5 in stages:
        if is_pad(words5):
            continue
        n_active += 1
        coeffs = words_to_coeffs(words5)
        b0, b1, b2, a1, a2 = kernel_to_biquad(coeffs)
        disc = a1 * a1 - 4.0 * a2
        if disc < 0:
            pr = math.sqrt(max(a2, 0.0))
        else:
            sq = math.sqrt(disc)
            pr = max(abs((-a1 + sq) / 2.0), abs((-a1 - sq) / 2.0))
        max_pole_r = max(max_pole_r, pr)
        if pr > 0.90 and a2 > 0:
            n_resonances += 1
            ratio = -a1 / (2.0 * math.sqrt(a2))
            ratio = max(-1.0, min(1.0, ratio))
            angle = math.acos(ratio)
            pf = abs(angle) / (2.0 * math.pi) * SR
            if 20 < pf < 20000:
                peak_freqs.append(round(pf, 1))
        if abs(b0) > 1e-12:
            z_disc = b1 * b1 - 4.0 * b0 * b2
            if z_disc >= 0:
                sqrt_d = math.sqrt(z_disc)
                z1 = (-b1 + sqrt_d) / (2.0 * b0)
                z2 = (-b1 - sqrt_d) / (2.0 * b0)
                for zr in (abs(z1), abs(z2)):
                    if zr > 0.90:
                        n_notches += 1
                        ratio = -b1 / (2.0 * math.sqrt(b0 * b2)) if b0 * b2 > 0 else 0.0
                        ratio = max(-1.0, min(1.0, ratio))
                        angle = math.acos(abs(ratio)) if abs(ratio) < 1.0 else 0.0
                        nf = angle / (2.0 * math.pi) * SR if angle > 1e-6 else 0.0
                        if 20 < nf < 20000:
                            notch_freqs.append(round(nf, 1))
        for i, f in enumerate(FREQS):
            w = 2.0 * math.pi * f / SR
            z_re = math.cos(w)
            z_im = -math.sin(w)
            num_re = b0 + b1 * z_re + b2 * (z_re * z_re - z_im * z_im)
            num_im = b1 * z_im + b2 * (2 * z_re * z_im)
            den_re = 1.0 + a1 * z_re + a2 * (z_re * z_re - z_im * z_im)
            den_im = a1 * z_im + a2 * (2 * z_re * z_im)
            mag2 = (num_re * num_re + num_im * num_im) / (den_re * den_re + den_im * den_im + 1e-24)
            total[i] += 10.0 * math.log10(mag2 + 1e-24)
    return total, max_pole_r, notch_freqs, peak_freqs, float(n_notches), n_active


def extract_body_features(data: bytes) -> dict:
    corners = read_corner_words(data)
    all_responses = []
    max_pole_r = 0.0
    all_notch_freqs = []
    all_peak_freqs = []
    total_notches = 0
    total_resonances = 0
    n_active_stages = 0
    for st in corners:
        resp, mr, nf, pf, nn, na = corner_db_response(st)
        all_responses.append(resp)
        max_pole_r = max(max_pole_r, mr)
        all_notch_freqs.extend(nf)
        all_peak_freqs.extend(pf)
        total_notches += nn
        total_resonances += na
    if len(all_responses) == 4:
        ends_db = [all_responses[0][0], all_responses[0][-1],
                   all_responses[1][0], all_responses[1][-1],
                   all_responses[2][0], all_responses[2][-1],
                   all_responses[3][0], all_responses[3][-1]]
        avg_start = sum(ends_db[0::2]) / 4
        avg_end = sum(ends_db[1::2]) / 4
    else:
        avg_start = avg_end = 0.0
    diff = avg_end - avg_start
    if diff > 10:
        slope = "HP"
    elif diff < -10:
        slope = "LP"
    else:
        slope = "FLAT"
    return {
        "responses": all_responses,
        "max_pole_r": round(max_pole_r, 4),
        "notch_freqs": sorted(set(round(f, 1) for f in all_notch_freqs)),
        "peak_freqs": sorted(set(round(f, 1) for f in all_peak_freqs)),
        "n_notches": int(total_notches),
        "n_resonances": int(total_resonances),
        "slope": slope,
        "n_active_stages": n_active_stages,
    }


def correlation(a: list[float], b: list[float]) -> float:
    n = len(a)
    ma = sum(a) / n
    mb = sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((a[i] - ma) ** 2 for i in range(n)))
    db = math.sqrt(sum((b[i] - mb) ** 2 for i in range(n)))
    if da < 1e-12 or db < 1e-12:
        return 0.0
    return num / (da * db)


X3_BODIES = Path(r"C:\Users\hooki\df2\dev\tmp\x3_fixed_cleanroom")

def archetype_response(stem: str, n_stages: int) -> list[list[float]] | None:
    body_path = X3_BODIES / f"x3_shape_{stem}" / f"x3_shape_{stem}.body240"
    if not body_path.exists():
        print(f"  WARNING: no x3 body for {stem} at {body_path}")
        return None
    data = body_path.read_bytes()
    corners = read_corner_words(data)
    responses = []
    for st in corners:
        resp, _, _, _, _, _ = corner_db_response(st)
        responses.append(resp)
    return responses


def classify_body(body_features: dict, archetype_responses: dict) -> dict:
    br = body_features["responses"]
    best_stem = None
    best_corr = -1.0
    for stem, ar in archetype_responses.items():
        corrs = []
        for c in range(4):
            corrs.append(correlation(br[c], ar[c]))
        mean_corr = sum(corrs) / len(corrs)
        if mean_corr > best_corr:
            best_corr = mean_corr
            best_stem = stem
    confidence = max(0.0, min(1.0, (best_corr + 1.0) / 2.0))
    if best_corr < 0.5:
        return {"archetype": "CUSTOM", "family": "CUSTOM", "confidence": round(confidence, 4), "corr": best_corr}
    return {"archetype": best_stem, "family": ARCH_FAMILIES.get(best_stem, "UNK"),
            "confidence": round(confidence, 4), "corr": best_corr}


def extract_name_tag(path: str) -> str:
    stem = Path(path).stem.lower()
    stem = re.sub(r'^[\d_]+', '', stem)
    for kw in ["phaser", "bat_phaser", "flanger", "vowel", "vocal", "vow",
               "lowpass", "highpass", "bandpass", "contrary",
               "swept_eq", "bell", "notch", "chord", "cavl", "comb",
               "lp", "hp", "bpf", "eq", "pha", "flg", "rez", "fuzz",
               "metal", "tube", "cavity", "skin", "throat", "acid",
               "ship", "riser", "scream", "talker", "mouth"]:
        if kw in stem:
            return kw
    if re.search(r'chord|arpeggio|harmon', stem):
        return "chord"
    if re.search(r'aa|ae|ah|ao|eh|er|ih|iy|uh|uu|uw|oo|ee|a_to|o_to|u_to|i_to', stem):
        return "vowel"
    return ""


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    # ── Step 1: inventory + dedup ────────────────────────────────────────────
    print("Scanning for *.body240 files...")
    all_files = []
    for repo in REPOS:
        if not repo.exists():
            continue
        for f in repo.rglob("*.body240"):
            parts = f.parts
            if ".git" in parts:
                continue
            all_files.append(f)
    print(f"  Found {len(all_files)} body files across all repos")

    by_hash: dict[str, dict] = {}
    decode_failures = []
    for fp in all_files:
        try:
            data = fp.read_bytes()
        except Exception as e:
            decode_failures.append((str(fp), str(e)))
            continue
        if len(data) != 240:
            decode_failures.append((str(fp), f"bad size {len(data)}"))
            continue
        h = hashlib.sha256(data).hexdigest()
        if h in by_hash:
            by_hash[h]["paths"].append(str(fp))
        else:
            name = fp.stem
            by_hash[h] = {"data": data, "canonical_name": name, "paths": [str(fp)]}
    print(f"  Unique bodies: {len(by_hash)}")

    # ── Step 2: decode archetypes ────────────────────────────────────────────
    print("Decoding 17 archetypes...")
    archetype_responses = {}
    for stem, fam, ns in ARCHETYPES:
        resp = archetype_response(stem, ns)
        if resp is None:
            print(f"  WARNING: no raw for {stem}")
            continue
        archetype_responses[stem] = resp
    print(f"  Decoded {len(archetype_responses)} archetypes")

    # ── Step 3 + 4: decode & classify each body ──────────────────────────────
    print("Decoding and classifying unique bodies...")
    rows = []
    body_decode_failures = []
    for h, entry in by_hash.items():
        data = entry["data"]
        name = entry["canonical_name"]
        paths = entry["paths"]
        try:
            feat = extract_body_features(data)
        except Exception as e:
            body_decode_failures.append((name, str(e), paths[0]))
            continue
        result = classify_body(feat, archetype_responses)
        tag = extract_name_tag(paths[0])
        tag_agrees = "YES"
        if tag and result["archetype"] != "CUSTOM":
            tag_short = tag.replace("_", "").lower()
            arch_lower = result["archetype"].replace("_", "").lower()
            if tag_short not in arch_lower and arch_lower not in tag_short:
                tag_agrees = "NO"
        elif tag and result["archetype"] == "CUSTOM":
            tag_agrees = "N/A-CUSTOM"
        rows.append({
            "hash": h,
            "canonical_name": name,
            "matched_archetype": result["archetype"],
            "matched_family": result["family"],
            "match_confidence": result["confidence"],
            "correlation": round(result["corr"], 4),
            "name_tag": tag,
            "tag_agrees": tag_agrees,
            "n_notches": feat["n_notches"],
            "n_resonances": feat["n_resonances"],
            "notch_freqs": ",".join(str(f) for f in feat["notch_freqs"][:10]),
            "peak_freqs": ",".join(str(f) for f in feat["peak_freqs"][:10]),
            "max_pole_r": feat["max_pole_r"],
            "slope": feat["slope"],
            "n_source_copies": len(paths),
            "source_paths": "|".join(paths),
        })

    rows.sort(key=lambda r: r["matched_archetype"])

    # ── Step 5: output ───────────────────────────────────────────────────────
    csv_path = OUT / "index.csv"
    with open(csv_path, "w", newline="") as f:
        fieldnames = ["hash", "canonical_name", "matched_archetype", "matched_family",
                      "match_confidence", "correlation", "name_tag", "tag_agrees",
                      "n_notches", "n_resonances", "notch_freqs", "peak_freqs",
                      "max_pole_r", "slope", "n_source_copies", "source_paths"]
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  Wrote {csv_path} ({len(rows)} rows)")

    json_path = OUT / "index.json"
    with open(json_path, "w") as f:
        json.dump({
            "meta": {
                "codec": "minifloat-packed u16 (FUN_1802c3600)",
                "sr": SR,
                "n_bodies_total": len(all_files),
                "n_unique": len(by_hash),
                "n_decoded_ok": len(rows),
                "n_decode_fail": len(body_decode_failures),
                "archetypes_source": "df2/dev/tmp/x3_fixed_cleanroom x3_shape_*.body240 (cleanroom body240 of ROM fundamentals)",
            },
            "rows": rows,
        }, f, indent=2)
    print(f"  Wrote {json_path}")

    # ── summary.md ────────────────────────────────────────────────────────────
    family_counts: dict[str, int] = defaultdict(int)
    archetype_counts: dict[str, int] = defaultdict(int)
    n_custom = 0
    tag_disagreements = []
    for r in rows:
        family_counts[r["matched_family"]] += 1
        archetype_counts[r["matched_archetype"]] += 1
        if r["matched_archetype"] == "CUSTOM":
            n_custom += 1
        if r["tag_agrees"] == "NO":
            tag_disagreements.append((r["canonical_name"], r["name_tag"], r["matched_archetype"]))

    n_dup_groups = sum(1 for r in rows if r["n_source_copies"] > 1)
    total_copies = sum(r["n_source_copies"] for r in rows)

    summary_lines = [
        "# TRENCH Filter Body Index — Summary",
        "",
        f"**Total body240 files found:** {len(all_files)}",
        f"**Unique bodies (by SHA256):** {len(rows)}",
        f"**Dup groups (bodies with >1 copy):** {n_dup_groups}",
        f"**Total file copies across repos:** {total_copies}",
        f"**Decode failures:** {len(body_decode_failures)}",
        f"**Classified as CUSTOM (confidence < 0.5):** {n_custom}",
        "",
        "## Family Histogram",
        "",
    ]
    for fam in sorted(family_counts):
        summary_lines.append(f"- **{fam}**: {family_counts[fam]}")
    summary_lines.extend(["", "## Archetype Histogram", ""])
    for arch in sorted(archetype_counts):
        if arch != "CUSTOM":
            summary_lines.append(f"- **{arch}**: {archetype_counts[arch]}")
    summary_lines.extend(["", "## Name-vs-DSP Disagreements", ""])
    if tag_disagreements:
        for name, tag, arch in sorted(tag_disagreements):
            summary_lines.append(f"- `{name}` tagged `{tag}` but matched `{arch}`")
    else:
        summary_lines.append("(none)")
    summary_lines.extend(["", "## Decode Failures", ""])
    if body_decode_failures:
        for name, err, path in body_decode_failures:
            summary_lines.append(f"- `{name}` at `{path}`: {err}")
    else:
        summary_lines.append("(none)")
    summary_lines.extend(["", "## Index files", f"- `index.csv` — {len(rows)} rows", f"- `index.json` — structured"])

    summary_path = OUT / "summary.md"
    with open(summary_path, "w") as f:
        f.write("\n".join(summary_lines) + "\n")
    print(f"  Wrote {summary_path}")
    print()
    print("═" * 60)
    print(f"DONE — {len(rows)} unique bodies indexed")
    print(f"Family histogram: {dict(family_counts)}")
    print(f"CUSTOM count: {n_custom}")
    print(f"Dup groups: {n_dup_groups}")
    print(f"Decode failures: {len(body_decode_failures)}")


if __name__ == "__main__":
    main()
