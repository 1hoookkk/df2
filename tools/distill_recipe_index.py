#!/usr/bin/env python3
"""Build the clean-room Workstation recipe index from read-only atlas evidence.

This is an evidence distiller, not a body compiler. It never emits reference
names, source/body identifiers, packed words, or absolute pole/zero locations.
The output retains only registered topology classes, relative movement,
relative zero placement, and measured lane-ablation effects.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


FORMAT = "trench-workstation-recipe-index-v1"
POSES = ("M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100")
EDGES = ("MORPH_AT_Q0", "MORPH_AT_Q100", "Q_AT_M0", "Q_AT_M100")
LANES = tuple(range(1, 7))
STAGE_NYQUIST_HZ = 19_531.25
PAIR_TOLERANCE = 1.0e-7
BOUNDARY_TOLERANCE_HZ = 1.0e-6

FixtureKey = tuple[str, str, str, str]
EndpointKey = tuple[FixtureKey, str, int]
EdgeKey = tuple[FixtureKey, str, int]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{path.name} is empty")
    return rows


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fixture_key(row: dict[str, str]) -> FixtureKey:
    return (row["family_id"], row["variant"], row["dat_index"], row["source_path"])


def family_sort_key(family_id: str) -> tuple[str, int]:
    prefix, _, suffix = family_id.rpartition("_")
    return (prefix, int(suffix))


def number(row: dict[str, str], field: str) -> float | None:
    value = row.get(field, "").strip()
    return None if value == "" else float(value)


def rounded(value: float | None) -> float | None:
    if value is None:
        return None
    result = round(value, 6)
    return 0.0 if result == -0.0 else result


def summary(values: Iterable[float | None]) -> dict[str, float | int | None]:
    observed = [value for value in values if value is not None and math.isfinite(value)]
    if not observed:
        return {"median": None, "minimum": None, "maximum": None, "support": 0}
    return {
        "median": rounded(statistics.median(observed)),
        "minimum": rounded(min(observed)),
        "maximum": rounded(max(observed)),
        "support": len(observed),
    }


def topology(row: dict[str, str], side: str, kind: str) -> str:
    count = int(row[f"{side}_{kind}_root_count"])
    if count == 0:
        return "degenerate"
    if count == 1:
        return "single_real_root"
    if count != 2:
        return "unsupported_root_count"

    hz_a = float(row[f"{side}_{kind}_root1_hz"])
    hz_b = float(row[f"{side}_{kind}_root2_hz"])
    radius_a = float(row[f"{side}_{kind}_root1_radius"])
    radius_b = float(row[f"{side}_{kind}_root2_radius"])
    same_pair = (
        abs(hz_a - hz_b) <= PAIR_TOLERANCE
        and abs(radius_a - radius_b) <= PAIR_TOLERANCE
    )
    if not same_pair:
        return "independent_real_pair"
    if (
        hz_a <= BOUNDARY_TOLERANCE_HZ
        or abs(hz_a - STAGE_NYQUIST_HZ) <= BOUNDARY_TOLERANCE_HZ
    ):
        # At DC/Nyquist the CSV projection cannot distinguish a repeated real
        # pair from the limiting case of a conjugate pair. Preserve that fact.
        return "boundary_pair_ambiguous"
    return "conjugate_pair"


def endpoint_geometry(row: dict[str, str], side: str) -> dict[str, Any]:
    return {
        "poleTopology": topology(row, side, "pole"),
        "zeroTopology": topology(row, side, "zero"),
        "poleRepresentativeHz": number(row, f"{side}_pole_representative_hz"),
        "poleRepresentativeRadius": number(row, f"{side}_pole_representative_radius"),
        "zeroRepresentativeHz": number(row, f"{side}_zero_representative_hz"),
        "zeroRepresentativeRadius": number(row, f"{side}_zero_representative_radius"),
        "poleRoots": tuple(
            (
                number(row, f"{side}_pole_root{root}_hz"),
                number(row, f"{side}_pole_root{root}_radius"),
            )
            for root in (1, 2)
        ),
        "zeroRoots": tuple(
            (
                number(row, f"{side}_zero_root{root}_hz"),
                number(row, f"{side}_zero_root{root}_radius"),
            )
            for root in (1, 2)
        ),
    }


def require_equal(existing: dict[str, Any], candidate: dict[str, Any], label: str) -> None:
    if existing != candidate:
        raise ValueError(f"inconsistent duplicated endpoint geometry for {label}")


def octave_interval(numerator_hz: float | None, denominator_hz: float | None) -> float | None:
    if numerator_hz is None or denominator_hz is None:
        return None
    if numerator_hz <= 0.0 or denominator_hz <= 0.0:
        return None
    return math.log2(numerator_hz / denominator_hz)


def nearest_root_interval(endpoint: dict[str, Any]) -> float | None:
    intervals = []
    for pole_hz, _ in endpoint["poleRoots"]:
        for zero_hz, _ in endpoint["zeroRoots"]:
            interval = octave_interval(zero_hz, pole_hz)
            if interval is not None:
                intervals.append(abs(interval))
    return min(intervals) if intervals else None


def topology_summary(values: Iterable[str]) -> dict[str, Any]:
    counts = Counter(values)
    ordered = dict(sorted(counts.items()))
    mode_count = max(ordered.values())
    modes = [name for name, count in ordered.items() if count == mode_count]
    return {
        "mode": modes[0] if len(modes) == 1 else "mixed",
        "observedCounts": ordered,
    }


def build_index(
    delta_rows: list[dict[str, str]],
    ablation_rows: list[dict[str, str]],
    *,
    delta_hash: str,
    ablation_hash: str,
    source_commit: str,
) -> dict[str, Any]:
    if any(row["status"] != "OBSERVED" for row in delta_rows + ablation_rows):
        raise ValueError("recipe inputs must contain OBSERVED rows only")

    endpoints: dict[EndpointKey, dict[str, Any]] = {}
    edges: dict[EdgeKey, dict[str, str]] = {}
    for row in delta_rows:
        fixture = fixture_key(row)
        lane = int(row["lane"])
        edge_key = (fixture, row["comparison"], lane)
        if edge_key in edges:
            raise ValueError(f"duplicate transition row for {edge_key}")
        edges[edge_key] = row

        for side in ("from", "to"):
            pose = row[f"{side}_pose"]
            endpoint_key = (fixture, pose, lane)
            candidate = endpoint_geometry(row, side)
            if endpoint_key in endpoints:
                require_equal(endpoints[endpoint_key], candidate, str(endpoint_key))
            else:
                endpoints[endpoint_key] = candidate

    ablations: dict[EndpointKey, dict[str, str]] = {}
    for row in ablation_rows:
        key = (fixture_key(row), row["pose"], int(row["lane"]))
        if key in ablations:
            raise ValueError(f"duplicate ablation row for {key}")
        ablations[key] = row

    if set(endpoints) != set(ablations):
        missing_ablation = len(set(endpoints) - set(ablations))
        missing_endpoint = len(set(ablations) - set(endpoints))
        raise ValueError(
            f"endpoint join is incomplete: {missing_ablation} without ablation, "
            f"{missing_endpoint} without transition geometry"
        )

    fixtures = sorted({key[0] for key in endpoints})
    families: dict[str, list[FixtureKey]] = defaultdict(list)
    for fixture in fixtures:
        families[fixture[0]].append(fixture)

    for family_id, observations in families.items():
        if len(observations) != 4:
            raise ValueError(f"{family_id} has {len(observations)} observations; expected 4")

    ranks: dict[EndpointKey, int] = {}
    for fixture in fixtures:
        for pose in POSES:
            ordered = sorted(
                LANES,
                key=lambda lane: (
                    -float(ablations[(fixture, pose, lane)]["removed_delta_rms_db"]),
                    lane,
                ),
            )
            for rank, lane in enumerate(ordered, start=1):
                ranks[(fixture, pose, lane)] = rank

    recipes = []
    for recipe_number, family_id in enumerate(sorted(families, key=family_sort_key), start=1):
        observations = sorted(families[family_id], key=lambda item: (int(item[1]), int(item[2])))
        lane_records = []
        for lane in LANES:
            topology_by_pose = []
            zero_by_pose = []
            effect_by_pose = []
            for pose in POSES:
                endpoint_set = [endpoints[(fixture, pose, lane)] for fixture in observations]
                ablation_set = [ablations[(fixture, pose, lane)] for fixture in observations]

                topology_by_pose.append(
                    {
                        "pose": pose,
                        "pole": topology_summary(item["poleTopology"] for item in endpoint_set),
                        "zero": topology_summary(item["zeroTopology"] for item in endpoint_set),
                    }
                )

                zero_to_pole = [
                    octave_interval(
                        item["zeroRepresentativeHz"], item["poleRepresentativeHz"]
                    )
                    for item in endpoint_set
                ]
                nearest_intervals = [nearest_root_interval(item) for item in endpoint_set]
                radius_offsets = [
                    item["zeroRepresentativeRadius"] - item["poleRepresentativeRadius"]
                    if item["zeroRepresentativeRadius"] is not None
                    and item["poleRepresentativeRadius"] is not None
                    else None
                    for item in endpoint_set
                ]
                remote_support = [value for value in zero_to_pole if value is not None]
                zero_by_pose.append(
                    {
                        "pose": pose,
                        "representativeZeroToPoleOctaves": summary(zero_to_pole),
                        "nearestRootIntervalOctaves": summary(nearest_intervals),
                        "zeroMinusPoleRadius": summary(radius_offsets),
                        "remoteAtLeastOneOctaveRate": rounded(
                            sum(abs(value) >= 1.0 for value in remote_support)
                            / len(remote_support)
                        )
                        if remote_support
                        else None,
                    }
                )

                effect_by_pose.append(
                    {
                        "pose": pose,
                        "removedRmsDb": summary(
                            number(item, "removed_delta_rms_db") for item in ablation_set
                        ),
                        "removedMaxAbsDb": summary(
                            number(item, "removed_delta_max_abs_db") for item in ablation_set
                        ),
                        "laneAloneSpanDb": summary(
                            number(item, "lane_alone_span_db") for item in ablation_set
                        ),
                        "withinPoseRmsRank": summary(
                            float(ranks[(fixture, pose, lane)]) for fixture in observations
                        ),
                    }
                )

            movement = []
            for edge_name in EDGES:
                edge_set = [edges[(fixture, edge_name, lane)] for fixture in observations]
                first = edge_set[0]
                movement.append(
                    {
                        "edge": edge_name,
                        "fromPose": first["from_pose"],
                        "toPose": first["to_pose"],
                        "scaleDbDelta": summary(
                            number(item, "delta_gain_db") for item in edge_set
                        ),
                        "poleOctaves": summary(
                            number(item, "delta_pole_octaves") for item in edge_set
                        ),
                        "poleRadiusDelta": summary(
                            number(item, "delta_pole_radius") for item in edge_set
                        ),
                        "zeroOctaves": summary(
                            number(item, "delta_zero_octaves") for item in edge_set
                        ),
                        "zeroRadiusDelta": summary(
                            number(item, "delta_zero_radius") for item in edge_set
                        ),
                        "packedWordChangeCount": {
                            "observedValues": sorted(
                                {int(item["packed_words_changed"]) for item in edge_set}
                            ),
                            **summary(
                                float(item["packed_words_changed"]) for item in edge_set
                            ),
                        },
                    }
                )

            lane_records.append(
                {
                    "lane": lane,
                    "topologyByPose": topology_by_pose,
                    "relativeMovement": movement,
                    "zeroBehaviorByPose": zero_by_pose,
                    "audibleEffectByPose": effect_by_pose,
                }
            )

        recipes.append(
            {
                "recipeId": f"R{recipe_number:03d}",
                "observationCount": len(observations),
                "lanes": lane_records,
            }
        )

    result = {
        "format": FORMAT,
        "contract": {
            "status": "INFERRED_FROM_OBSERVED_REGISTERED_LANES",
            "studyEvidenceOnly": True,
            "stageCorrespondencePreserved": True,
            "recipeDoesNotSupplyPoleScaffolds": True,
            "recipeAppliesToFrozenPolesThroughZeroOnlyAuthoring": True,
            "containsPresetNames": False,
            "containsPerRecipeSourceOrBodyIdentifiers": False,
            "containsPackedRowsOrWords": False,
            "containsAbsoluteReferenceGeometry": False,
            "topologyBoundary": (
                "conjugate vs independent-real is retained where the root projection proves it; "
                "DC/Nyquist repeated pairs remain ambiguous"
            ),
            "audibilityBoundary": (
                "lane-removal dB is an exact serial-cascade ablation on the registered grid; "
                "it is not a recovered vendor role label"
            ),
        },
        "evidence": {
            "sourceRepositoryCommit": source_commit,
            "poseLaneDeltas": {
                "file": "p2k_pose_lane_deltas.csv",
                "sha256": delta_hash,
                "rowCount": len(delta_rows),
            },
            "laneAblation": {
                "file": "p2k_lane_ablation.csv",
                "sha256": ablation_hash,
                "rowCount": len(ablation_rows),
            },
        },
        "join": {
            "fixturePoseLaneRows": len(endpoints),
            "transitionRows": len(edges),
            "unmatchedRows": 0,
            "sourceFixtureObservations": len(fixtures),
            "recipeFamilies": len(recipes),
            "observationsPerRecipe": 4,
        },
        "normalization": {
            "frequencyMovement": "signed log2 ratio in octaves",
            "zeroPlacement": "signed zero-to-pole log2 ratio; no absolute Hz retained",
            "radiusMovement": "signed endpoint difference",
            "familyAggregation": "median plus observed min/max across four source observations",
            "audibleEffect": "observed lane-removal dB plus within-pose rank",
            "numericPrecision": "six decimal places",
        },
        "recipes": recipes,
    }
    validate_output(result)
    return result


def validate_output(index: dict[str, Any]) -> None:
    if index["format"] != FORMAT:
        raise ValueError("wrong recipe index format")
    if len(index["recipes"]) != 33:
        raise ValueError("recipe index must contain 33 anonymized recipe families")
    if index["join"]["unmatchedRows"] != 0:
        raise ValueError("recipe index contains unmatched evidence")

    forbidden_keys = {
        "family_id",
        "family_name",
        "source_path",
        "body_sha256",
        "packed_words",
        "packedWords",
        "poleHz",
        "zeroHz",
        "absoluteHz",
    }
    serialized = json.dumps(index, sort_keys=True)
    forbidden_fragments = ("Ace of Bass", "ref/p2k_variants/", "variant_0_dat_")
    if any(fragment in serialized for fragment in forbidden_fragments):
        raise ValueError("recipe index leaked a source name or path")

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            overlap = forbidden_keys.intersection(value)
            if overlap:
                raise ValueError(f"recipe index contains forbidden fields: {sorted(overlap)}")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(index)
    for expected_number, recipe in enumerate(index["recipes"], start=1):
        if recipe["recipeId"] != f"R{expected_number:03d}":
            raise ValueError("recipe IDs are not deterministic and contiguous")
        if recipe["observationCount"] != 4 or len(recipe["lanes"]) != 6:
            raise ValueError("recipe family must contain four observations and six lanes")
        for expected_lane, lane in enumerate(recipe["lanes"], start=1):
            if lane["lane"] != expected_lane:
                raise ValueError("registered lane ordering changed")
            if [item["pose"] for item in lane["topologyByPose"]] != list(POSES):
                raise ValueError("topology pose ordering changed")
            if [item["edge"] for item in lane["relativeMovement"]] != list(EDGES):
                raise ValueError("transition ordering changed")
            if [item["pose"] for item in lane["zeroBehaviorByPose"]] != list(POSES):
                raise ValueError("zero-behavior pose ordering changed")
            if [item["pose"] for item in lane["audibleEffectByPose"]] != list(POSES):
                raise ValueError("ablation pose ordering changed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pose-lane-deltas", required=True, type=Path)
    parser.add_argument("--lane-ablation", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="build and validate in memory without writing the output",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    delta_rows = read_csv(args.pose_lane_deltas)
    ablation_rows = read_csv(args.lane_ablation)
    index = build_index(
        delta_rows,
        ablation_rows,
        delta_hash=sha256(args.pose_lane_deltas),
        ablation_hash=sha256(args.lane_ablation),
        source_commit=args.source_commit,
    )
    if not args.check_only:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(index, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
    print(
        f"OBSERVED joined={index['join']['fixturePoseLaneRows']} "
        f"unmatched={index['join']['unmatchedRows']} "
        f"recipes={index['join']['recipeFamilies']} "
        f"lanes={len(index['recipes']) * 6}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
