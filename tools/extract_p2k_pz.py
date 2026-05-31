from pathlib import Path
import struct
import math
import csv

ROOT = Path(__file__).resolve().parents[1]
P2K_DIR = ROOT / "ref" / "p2k_variants"
OUT_CSV = P2K_DIR / "p2k_poles_zeros_M50_Q50.csv"

NUM_STAGES = 6
NUM_COEFFS = 5

def read_body_bytes(path: Path) -> bytes:
    return path.read_bytes()

def body_bytes_to_corner_words(body: bytes) -> dict:
    if len(body) != 4 * NUM_STAGES * NUM_COEFFS * 2:
        raise ValueError(f"unexpected body length: {len(body)}")
    offs = 0
    corners = {k: [] for k in ("A","B","C","D")}
    for corner in ("A","B","C","D"):
        for si in range(NUM_STAGES):
            row = []
            for ci in range(NUM_COEFFS):
                w = int.from_bytes(body[offs:offs+2], 'little')
                offs += 2
                row.append(w)
            corners[corner].append(tuple(row))
    return corners

def quad_roots(a, b, c):
    # solve a*x^2 + b*x + c = 0, return two complex roots
    if abs(a) < 1e-18:
        if abs(b) < 1e-18:
            return (complex(float('nan'),0), complex(float('nan'),0))
        return (complex(-c/b,0), complex(float('nan'),0))
    disc = b*b - 4*a*c
    if disc >= 0:
        sq = math.sqrt(disc)
        return (complex((-b + sq)/(2*a),0), complex((-b - sq)/(2*a),0))
    else:
        sq = math.sqrt(-disc)
        return (complex(-b/(2*a), sq/(2*a)), complex(-b/(2*a), -sq/(2*a)))

def process_one(binpath: Path, morph=0.5, q=0.5):
    from pyruntime import packed_interp

    body = read_body_bytes(binpath)
    cw = body_bytes_to_corner_words(body)
    # use pure-Python reference interpolation (bit-identical at f32 precision)
    rows = packed_interp._packed_bilinear_reference(cw, morph, q)
    stages = []
    for si, row in enumerate(rows):
        b0,b1,b2,a1,a2 = packed_interp.kernel_to_biquad(row)
        # denominator: z^2 + a1 z + a2
        pole1, pole2 = quad_roots(1.0, a1, a2)
        # numerator: b0 z^2 + b1 z + b2
        zero1, zero2 = quad_roots(b0, b1, b2)
        stages.append((pole1, pole2, zero1, zero2, (b0,b1,b2,a1,a2)))
    return stages

def main():
    rows = []
    for preset_dir in sorted(P2K_DIR.iterdir()):
        if not preset_dir.is_dir():
            continue
        preset = preset_dir.name
        for vb in sorted(preset_dir.glob("variant_*.bin")):
            variant = vb.name
            try:
                stages = process_one(vb, morph=0.5, q=0.5)
            except Exception as e:
                print(f"failed {vb}: {e}")
                continue
            for si, st in enumerate(stages):
                pole1,pole2,zero1,zero2,coeffs = st
                rows.append({
                    "preset": preset,
                    "variant": variant,
                    "stage": si,
                    "p1_r": pole1.real, "p1_i": pole1.imag,
                    "p2_r": pole2.real, "p2_i": pole2.imag,
                    "z1_r": zero1.real, "z1_i": zero1.imag,
                    "z2_r": zero2.real, "z2_i": zero2.imag,
                })

    with OUT_CSV.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            "preset","variant","stage",
            "p1_r","p1_i","p2_r","p2_i",
            "z1_r","z1_i","z2_r","z2_i",
        ])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"Wrote {OUT_CSV}")

if __name__ == '__main__':
    main()
