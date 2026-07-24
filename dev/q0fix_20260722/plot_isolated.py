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
def isolated(path,name,tag):
    bb=Path(path).read_bytes()
    corners=[(0,0,"M0 Q0","#5b9bd5"),(1,0,"M100 Q0","#e0555f"),(0,1,"M0 Q100","#5bef6f"),(1,1,"M100 Q100","#ffd23e")]
    probes={lbl:trench_ffi.packed_probe(bb,m,q)["biquad"] for m,q,lbl,_ in corners}
    for s in range(6):
        fig,ax=plt.subplots(figsize=(9,3.2),dpi=110); fig.patch.set_facecolor("#0e1512"); ax.set_facecolor("#0e1512")
        for (m,q,lbl,col) in corners:
            ax.semilogx(f,sdb(probes[lbl][s]),color=col,lw=1.8,label=lbl)
        ax.set_xlim(30,19200); ax.set_ylim(-40,45)
        ax.grid(True,which="both",color="#1c2722",lw=0.5); ax.tick_params(colors="#7a8a82")
        ax.set_title(f"{name}  -  Stage {s+1} (isolated)",color="#cfe8de",fontsize=13,loc="left")
        ax.legend(facecolor="#12201b",edgecolor="#1c2722",labelcolor="#cfe8de",fontsize=8,loc="upper right")
        fig.tight_layout(); fig.savefig(f"dev/q0fix_20260722/iso_{tag}_S{s+1}.png",facecolor="#0e1512"); plt.close(fig)
    print("wrote 6 isolated stage plots for",name)
isolated("C:/Users/hooki/df2/dev/tmp/factory/P2k_013.body240","Talking Hedz","hedz")
