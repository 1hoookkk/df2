"""Extract type patterns from all E-mu XML filter templates."""
import xml.etree.ElementTree as ET
import os
from collections import Counter

FILTER_DIR = "C:/Users/hooki/trenchwork/scratch/resources/Filter"

results = []
for f in sorted(os.listdir(FILTER_DIR)):
    if not f.endswith('.xml'):
        continue
    try:
        tree = ET.parse(os.path.join(FILTER_DIR, f))
        root = tree.getroot()
        name = root.get('name', f.replace('.xml', ''))
        filt = root.find('filter')
        if filt is None:
            continue
        types = []
        for i in range(1, 7):
            sec = filt.find(f"designer-section[@index='{i}']")
            if sec is not None:
                t = int(sec.findtext('type', '0'))
                types.append(t)
            else:
                types.append(0)
        results.append((name, types))
    except Exception as e:
        print(f"  ERROR: {f}: {e}")

# Print all
print("=== TYPE PATTERNS (all templates) ===")
for name, types in results:
    active = [t for t in types if t != 0]
    pattern = ",".join(str(t) for t in types)
    print(f"  {name:35s} [{pattern}]  active={len(active)}")

# Group by active-type pattern
print("\n=== PATTERN GROUPS ===")
patterns = Counter()
pattern_members = {}
for name, types in results:
    active = tuple(t for t in types if t != 0)
    if not active:
        active = (0,)
    patterns[active] += 1
    pattern_members.setdefault(active, []).append(name)

for pat, count in patterns.most_common():
    members = pattern_members[pat]
    pat_str = ",".join(str(t) for t in pat)
    print(f"\n  Pattern [{pat_str}] x{count}:")
    for m in members:
        print(f"    - {m}")

# Type mixing analysis
print("\n=== SINGLE vs MIXED TYPE ===")
single = [(n, t) for n, t in results if len(set(x for x in t if x != 0)) <= 1]
mixed = [(n, t) for n, t in results if len(set(x for x in t if x != 0)) > 1]
print(f"  Single type: {len(single)}")
print(f"  Mixed types: {len(mixed)}")
print("\n  MIXED:")
for name, types in mixed:
    active_types = sorted(set(x for x in types if x != 0))
    type_str = ",".join(str(t) for t in types)
    at_str = "+".join(str(t) for t in active_types)
    print(f"    {name:35s} types={at_str}  [{type_str}]")

# Type frequency
print("\n=== TYPE FREQUENCY (across all active stages) ===")
type_counts = Counter()
for _, types in results:
    for t in types:
        if t != 0:
            type_counts[t] += 1
for t, c in sorted(type_counts.items()):
    print(f"  Type {t}: {c} stages")
