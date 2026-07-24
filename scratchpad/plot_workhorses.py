#!/usr/bin/env python3
"""Contact sheet of the 10 real E-mu workhorse presets: 4 poses each on the
packed runtime (morph M0->M100 at Q0, resonance at Q100)."""
import sys, math
from pathlib import Path
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

DF2 = Path(r"C:\Users\hooki\df2"); sys.path.insert(0, str(DF2))
from pyruntime import trench_ffi

SR = 39062.5
F = np.logspace(math.log10(20), math.log10(18000), 700)
Z1 = np.exp(-2j*np.pi*F/SR); Z2 = Z1*Z1
BODIES = Path(r"C:\Users\hooki\df2-workstation")/"plugin"/"presets"/"bodies"

ORDER = [
 ("wh_six_pole_q","Six Pole Q"), ("wh_super_lopass","Super Lowpass"),
 ("wh_modern_lopass","Modern Lowpass"), ("wh_super_hipass","Super Highpass"),
 ("wh_contrary_sweeps","Contrary Sweeps"), ("wh_notch_sweeper","Notch Sweeper"),
 ("wh_peak_shifter","Peak Shifter"), ("wh_twin_peaks","Twin Peaks"),
 ("wh_three_point_morph","Three Point Morph"), ("wh_wah_wah","Wah Wah"),
]
POSES = [(0,0,"M0 Q0","#00e5ff",2.2),(1,0,"M100 Q0","#ff9100",2.2),
         (0,1,"M0 Q100","#7c4dff",1.3),(1,1,"M100 Q100","#ff1744",1.3)]

def db(body,m,q):
    pr=trench_ffi.packed_probe(body,float(m),float(q))
    mag=np.ones_like(F,dtype=complex)
    for b0,b1,b2,a1,a2 in pr["biquad"]:
        mag*=(b0+b1*Z1+b2*Z2)/(1.0+a1*Z1+a2*Z2)
    return 20*np.log10(np.abs(mag)+1e-12)

plt.style.use("dark_background")
fig,axes=plt.subplots(5,2,figsize=(15,18),dpi=120); fig.patch.set_facecolor("#0f1117")
for ax,(stem,name) in zip(axes.flat, ORDER):
    body=(BODIES/f"{stem}.body240").read_bytes()
    for m,q,lab,col,lw in POSES:
        ax.plot(F, db(body,m,q), color=col, lw=lw, label=lab, alpha=0.95 if q==0 else 0.6)
    ax.set_facecolor("#161822"); ax.set_xscale("log"); ax.set_xlim(20,18000); ax.set_ylim(-48,30)
    ax.set_xticks([50,100,500,1000,5000,10000]); ax.set_xticklabels(["50","100","500","1k","5k","10k"],fontsize=8,color="#90a4ae")
    ax.tick_params(colors="#90a4ae",labelsize=8)
    ax.set_title(name, color="#fff", fontsize=12, fontweight="bold")
    ax.grid(True,which="major",color="#263238",lw=0.6,alpha=0.7)
    ax.axhline(0,color="#37474f",lw=0.8)
    ax.legend(fontsize=7,facecolor="#1e2230",edgecolor="#37474f",loc="lower left",ncol=2)
fig.suptitle("TRENCH Workhorses — real E-mu heritage filters (4 poses: morph M0->M100, Q=resonance)",
             color="#fff", fontsize=15, fontweight="bold", y=0.995)
plt.tight_layout(rect=[0,0,1,0.985])
OUT=Path(r"C:\Users\hooki\df2-workstation")/"dev"/"tmp"/"workhorse_plots"; OUT.mkdir(parents=True,exist_ok=True)
p=OUT/"workhorses_contact_sheet.png"; plt.savefig(p,dpi=120,facecolor=fig.get_facecolor())
print(p)
