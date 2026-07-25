# The 4 archetypes — decoded fingerprints

Decoded from `df2/bodies/rom/P2k_*.json` (compiled-v1, packed words, SR 39062.5)
via `words_to_coeffs` → DF2T → pole roots. **Behavior study only** (teacher
manifold). Per stage: resonant freq / pole-Q. maxPoleR = sharpest pole in corner.
These are the *moves* to rebuild on measured data — never the bytes to ship.

## FuzziFace — P2k_007 — DST (distortion)
Manual: "Nasty clipped distortion. Q functions as mid-frequency tone control."
```
M0_Q0     maxR 0.9983  4036Hz/Q190  548/Q3.9  600/Q8.5  376/Q12  322/Q6.8  580/Q3.2
M100_Q0   maxR 0.9929   935/Q9.6  1103/Q12  1171/Q9.1  803/Q8.5  688/Q7.0 1170/Q3.2
M0_Q100   maxR 0.9983  4036/Q190 2206/Q4.0 2367/Q8.7 1515/Q12  1267/Q6.9 2317/Q3.2
M100_Q100 maxR 0.9723  3755/Q9.4 4404/Q13  4729/Q9.4 3184/Q8.5 2750/Q6.9 4717/Q3.2
```
Move: ONE razor ~4 kHz / Q≈190 pole = the saturator-driver, riding a low cluster
(320–600 Hz). Morph glides the stack up. **Hot at baseline** (Q0 keeps the razor
pole). Q sharpens/moves the driven band = "mid-freq tone control."

## LucifersQ — P2k_029 — REZ (violent mid-Q)
Manual: "Violent mid Q filter! Take care with Q values 40-90."
```
M0_Q0     maxR 0.9902    79/Q0.2 17683/Q144  479/Q1.6 13058/Q42 15675/Q35   ---
M100_Q0   maxR 0.9693  9433/Q17   357/Q0.9 3162/Q0.9 6629/Q3.5 4275/Q1.8 1036/Q0.7
M0_Q100   maxR 0.9990  5093/Q5.4 1377/Q79  2282/Q44  4139/Q25  3250/Q43   257/Q20
M100_Q100 maxR 0.9887 12781/Q24  1172/Q8.3 10124/Q31 11370/Q30 8593/Q17 14876/Q2.8
```
Move: tame-ish at Q0, but Q100 ignites a spray of mid Q40–80 peaks across
250 Hz–5 kHz simultaneously. The "violence" is multiple mid resonances blooming
together — danger zone Q40–90.

## Meaty Gizmo — P2k_004 — Q-bloom monster
Iconic big-bloom body (secondary-contrast ~33.9 dB).
```
M0_Q0     maxR 0.9988    59/Q4.1 10329/Q14 12893/Q3.8 13615/Q34 14670/Q37 16277/Q13
M0_Q100   maxR 0.9997 13480/Q3230 2377/Q0.2 10349/Q1948 16822/Q3410 13482/Q2292 2632/Q6.2
M100_Q100 maxR 0.9917 5849/Q40  4521/Q29  2483/Q24  16163/Q2.9 9573/Q7.1  511/Q1.9
```
Move: identical poles go Q~4–37 at rest → **Q~2000–3400 razor** at Q100 (r 0.9997).
Pure Q *contrast* — body to needle — is the entire identity.

## DJ Alkaline — P2k_015 — bright multi-resonant
```
M0_Q0     maxR 0.9912 11617/Q95 1794/Q14 3157/Q25 13587/Q117 5471/Q43 8636/Q78
M0_Q100   maxR 0.9990 11747/Q967 1787/Q147 3143/Q259 13488/Q1110 5444/Q448 8793/Q724
M100_Q100 maxR 0.9843 13591/Q21  427/Q2.2 6246/Q21 15425/Q21  9713/Q33 11469/Q22
```
Move: already sharp at baseline (Q80–120 @ Q0), peaks spread 1.7–13.5 kHz, blooming
to Q1000+. A bright, multi-peak resonant comb.

---

### Re-decode (df2-side, for the authoring phase)
```python
import json, numpy as np, math
from pyruntime.packed_interp import words_to_coeffs   # df2 kernel
d = json.load(open('df2/bodies/rom/P2k_007_fuzzi_face.json'))
kf = {k['label']: k for k in d['keyframes']}           # M0_Q0 etc -> packedWords[6][5]
# c0..c4 = words_to_coeffs(words); a1=c2-2, a2=1-c3; pole r=sqrt(a2), f=acos(-a1/2r)/2pi*SR
```
