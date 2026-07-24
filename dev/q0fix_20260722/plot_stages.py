import sys, numpy as np
from pathlib import Path
sys.path.insert(0,"C:/Users/hooki/df2"); sys.path.insert(0,"C:/Users/hooki/df2/pyruntime")
from pyruntime import trench_ffi
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

f=np.logspace(np.log10(30),np.log10(19200),512); SR=39062.5
w=2*np.pi*f/SR; z1=np.exp(-1j*w); z2=z1*z1
def sdb(c):
    b0,b1,b2,a1,a2=c
    return 20*np.log10(np.maximum(np.abs(b0+b1*z1+b2*z2)/np.maximum(np.abs(1+a1*z1+a2*z2),1e-12),1e-9))

def plot_body(path, name, outpng):
    bb=Path(path).read_bytes()
    corners=[(0,0,"M0 Q0","#5b9bd5"),(1,0,"M100 Q0","#e0555f"),(0,1,"M0 Q100","#5bef6f"),(1,1,"M100 Q100","#ffd23e")]
    probes={lbl:trench_ffi.packed_probe(bb,m,q)["biquad"] for m,q,lbl,_ in corners}
    fig,axes=plt.subplots(3,2,figsize=(11,10),dpi=110)
    fig.patch.set_facecolor("#0e1512")
    for s in range(6):
        ax=axes[s//2][s%2]; ax.set_facecolor("#0e1512")
        for (m,q,lbl,col) in corners:
            ax.semilogx(f,sdb(probes[lbl][s]),color=col,lw=1.5,label=lbl)
        ax.set_title(f"Stage {s+1}",color="#cfe8de",fontsize=12,loc="left")
        ax.set_xlim(30,19200); ax.set_ylim(-40,45)
        ax.grid(True,which="both",color="#1c2722",lw=0.5); ax.tick_params(colors="#7a8a82",labelsize=8)
        if s==0: ax.legend(facecolor="#12201b",edgecolor="#1c2722",labelcolor="#cfe8de",fontsize=8,loc="upper right")
    fig.suptitle(f"{name} - 6 stages isolated (each biquad, all 4 corners)",color="#cfe8de",fontsize=14)
    fig.tight_layout()
    fig.savefig(outpng,facecolor="#0e1512"); plt.close(fig)
    print("wrote",outpng)

plot_body("C:/Users/hooki/df2/dev/tmp/factory/P2k_013.body240","Talking Hedz (P2k_013)","dev/q0fix_20260722/stages_talking_hedz.png")

import glob
GOLD="C:/Users/hooki/surface-forge/out/foundry/ROM_GOLD"
for bp in sorted(glob.glob(GOLD+"/P2k_*.body240")):
    nm=Path(bp).stem
    plot_body(bp, nm.replace("_"," "), f"dev/q0fix_20260722/stages_{nm}.png")
