"""Extract Emulator X ROM filter banks from the installed EmulatorX.dll.

Outputs:
  - ref/presets/P2k_000_*.bin .. P2k_049_*.bin
    Verbatim 240-byte packed corner banks in runtime order:
    A/B/C/D = M0_Q0 / M100_Q0 / M0_Q100 / M100_Q100.

  - ref/p2k_variants/P2k_###/*.bin
    The four DAT variants per skin. Variant 0 is the bank that matches the
    known Talking Hedz CE dump for P2k_013.

  - P2K artifacts only.

For the correctly classified X3 computed menu classes, including Bat Phaser,
Flanger Lite, both vocals, the Morph family, and Morph Designer, run:

  python tools/extract_x3_menu_filters.py

This is extraction-only: it does not touch runtime code or cartridge formats.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DLL = Path(r"C:\Program Files\Common Files\VST3\EmulatorX.dll")

IMAGE_BASE = 0x180000000

P2K_DAT = 0x1806D762E
P2K_BANK_BYTES = 0xF0
P2K_DAT_TO_STAGE0_A_DELTA = -0x1E
DEFAULT_P2K_SKIN_COUNT = 50

P2K_NAMES = [
    "Ace of Bass",
    "MegaSweepz",
    "Early Rizer",
    "Millennium",
    "Meaty Gizmo",
    "Klub Klassik",
    "BassBox 303",
    "Fuzzi Face",
    "Dead Ringer",
    "TB or Not TB",
    "Ooh to Eee",
    "Boland Bass",
    "Multi Q Vox",
    "Talking Hedz",
    "Zoom Peaks",
    "DJ Alkaline",
    "Bass Tracer",
    "Rogue Hertz",
    "Razor Blades",
    "Radio Craze",
    "Eeh to Aah",
    "Ubu Orator",
    "Deep Bouche",
    "Freak Shifta",
    "Cruz Pusher",
    "Angelz Hairz",
    "Dream Weava",
    "Acid Ravage",
    "Bass-O-Matic",
    "Lucifer's Q",
    "Tooth Comb",
    "Ear Bender",
    "Klang Kling",
    "Classic 4 LPF",
    "Smooth 2 LPF",
    "Steeper 6 LPF",
    "Shallow 2 HPF",
    "Deeper 4 HPF",
    "Band-pass1 2 BPF",
    "Band-pass2 4 BPF",
    "ContraBand 6 BPF",
    "Swept1oct 6 EQ+",
    "Swept2 to 1oct 6 EQ+",
    "Swept3 to 1oct 6 EQ+",
    "PhazeShift1 6 PHA",
    "PhazeShift2 6 PHA",
    "BlissBatz 6 PHA",
    "FlangerLite 6 FLG",
    "Aah-Ay-Eeh 6 VOW",
    "Ooh-To-Aah 6 VOW",
]

def slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PeImage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = path.read_bytes()
        peoff = struct.unpack_from("<I", self.data, 0x3C)[0]
        if self.data[peoff : peoff + 4] != b"PE\0\0":
            raise ValueError(f"{path} is not a PE file")
        section_count = struct.unpack_from("<H", self.data, peoff + 6)[0]
        optional_size = struct.unpack_from("<H", self.data, peoff + 20)[0]
        optional = peoff + 24
        self.image_base = struct.unpack_from("<Q", self.data, optional + 24)[0]
        section_table = optional + optional_size
        self.sections = []
        for i in range(section_count):
            off = section_table + i * 40
            name = self.data[off : off + 8].split(b"\0")[0].decode("ascii", "ignore")
            virtual_size, virtual_address, raw_size, raw_ptr = struct.unpack_from(
                "<IIII", self.data, off + 8
            )
            self.sections.append(
                {
                    "name": name,
                    "va": virtual_address,
                    "virtual_size": virtual_size,
                    "raw_size": raw_size,
                    "raw_ptr": raw_ptr,
                }
            )

    def offset(self, va: int) -> int:
        rva = va - self.image_base
        for section in self.sections:
            start = section["va"]
            size = max(section["virtual_size"], section["raw_size"])
            if start <= rva < start + size:
                return section["raw_ptr"] + (rva - start)
        raise ValueError(f"VA {va:#x} is not in any PE section")

    def bytes_at(self, va: int, size: int) -> bytes:
        off = self.offset(va)
        return self.data[off : off + size]


def transpose_p2k_bank(image: PeImage, dat_index: int) -> bytes:
    """Recreate FUN_1802d3ce0's source-stage -> destination-corner copy."""

    dat_off = image.offset(P2K_DAT)
    src0 = dat_off + dat_index * P2K_BANK_BYTES + P2K_DAT_TO_STAGE0_A_DELTA
    corners = [bytearray() for _ in range(4)]
    for stage in range(6):
        stage_off = src0 + stage * 40
        for corner in range(4):
            start = stage_off + corner * 10
            corners[corner].extend(image.data[start : start + 10])
    return b"".join(corners)


def p2k_name(index: int) -> str:
    if index < len(P2K_NAMES):
        return P2K_NAMES[index]
    return f"Anonymous Skin {index:03d}"


def write_p2k(image: PeImage, out_dir: Path, variants_dir: Path, skin_count: int) -> list[dict[str, object]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    variants_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for p2k_index in range(skin_count):
        name = p2k_name(p2k_index)
        variant_entries = []
        for variant in range(4):
            dat_index = p2k_index * 4 + variant
            bank = transpose_p2k_bank(image, dat_index)
            variant_subdir = variants_dir / f"P2k_{p2k_index:03d}_{slug(name)}"
            variant_subdir.mkdir(parents=True, exist_ok=True)
            variant_path = variant_subdir / f"variant_{variant}_dat_{dat_index:03d}.bin"
            variant_path.write_bytes(bank)
            variant_entries.append(
                {
                    "variant": variant,
                    "dat_index": dat_index,
                    "file": str(variant_path.relative_to(ROOT)).replace("\\", "/"),
                    "bytes": len(bank),
                    "sha256": sha256(bank),
                }
            )

        bank = transpose_p2k_bank(image, p2k_index * 4)
        filename = f"P2k_{p2k_index:03d}_{slug(name)}.bin"
        path = out_dir / filename
        path.write_bytes(bank)
        manifest.append(
            {
                "id": f"P2k_{p2k_index:03d}",
                "name": name,
                "name_status": "from Proteus Family SysEx filter table"
                if p2k_index < len(P2K_NAMES)
                else "anonymous",
                "main_variant": 0,
                "main_dat_index": p2k_index * 4,
                "source": f"DAT_1806d762e + (skin_index * 4 + variant) * 0xf0, transposed by FUN_1802d3ce0 layout",
                "file": filename,
                "bytes": len(bank),
                "sha256": sha256(bank),
                "variants": variant_entries,
            }
        )
    (out_dir / "P2K_MANIFEST.json").write_text(
        json.dumps(
            {
                "source_dll": str(image.path),
                "image_base": hex(image.image_base),
                "p2k_dat": hex(P2K_DAT),
                "skin_count": skin_count,
                "main_variant": 0,
                "variant_rule": "dat_index = skin_index * 4 + variant",
                "layout": "4 corners x 6 stages x 5 u16, runtime corner-major order",
                "entries": manifest,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def write_batman(_image: PeImage, _out_dir: Path) -> dict[str, object]:
    raise RuntimeError(
        "Deprecated misclassified extractor. Run tools/extract_x3_menu_filters.py instead."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dll", type=Path, default=DEFAULT_DLL)
    parser.add_argument("--p2k-out", type=Path, default=ROOT / "ref" / "presets")
    parser.add_argument("--p2k-variants-out", type=Path, default=ROOT / "ref" / "p2k_variants")
    parser.add_argument("--p2k-skin-count", type=int, default=DEFAULT_P2K_SKIN_COUNT)
    args = parser.parse_args()

    image = PeImage(args.dll)
    if image.image_base != IMAGE_BASE:
        raise ValueError(f"Unexpected image base {image.image_base:#x}; expected {IMAGE_BASE:#x}")

    p2k_manifest = write_p2k(image, args.p2k_out, args.p2k_variants_out, args.p2k_skin_count)
    hedz_new = args.p2k_out / "P2k_013_talking_hedz.bin"
    hedz_old = ROOT / "ref" / "presets" / "talking_hedz.bin"
    hedz_status = "not checked"
    if hedz_old.exists():
        hedz_status = "match" if hedz_new.read_bytes() == hedz_old.read_bytes() else "DIFF"

    print(f"wrote {len(p2k_manifest)} P2K banks -> {args.p2k_out}")
    print(f"P2k_013_talking_hedz.bin vs talking_hedz.bin: {hedz_status}")
    print(f"DJ Alkaline: {args.p2k_out / 'P2k_015_dj_alkaline.bin'}")
    print(f"P2K variants: {args.p2k_variants_out}")
    print("X3 computed menu classes: run python tools/extract_x3_menu_filters.py")


if __name__ == "__main__":
    main()
