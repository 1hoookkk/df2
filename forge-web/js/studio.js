/* TRENCH · forge — self-contained authoring instrument.
   Poles come from a real fit (sources.js); you author a ZERO onto each pole.
   Pack through WASM forge_pack_params, plot via packed.js (plot==engine), play
   through the worklet drive chain (AGC + Mackie slam). Server-backed SAVE/SCORE
   when served by tools/forge_author_server.py. */
/* inline packed-runtime helpers */
const PACKED_SR=39062.5, PACKED_TAU=Math.PI*2;

const PACKED_CORNER_KEYS=["M0_Q0","M100_Q0","M0_Q100","M100_Q100"];
const PACKED_STAGES=6, PACKED_WORDS=5;

function bytesFromHex(hex){
  const clean=String(hex||"").replace(/[^0-9a-fA-F]/g,"");
  const out=new Uint8Array(clean.length/2);
  for(let i=0;i<out.length;i++) out[i]=parseInt(clean.slice(i*2,i*2+2),16);
  return out;
}

function wordsFromBytes(bytes){
  const out={};
  let p=0;
  for(const key of PACKED_CORNER_KEYS){
    out[key]=[];
    for(let s=0;s<PACKED_STAGES;s++){
      const row=[];
      for(let w=0;w<PACKED_WORDS;w++,p+=2) row.push(bytes[p]|(bytes[p+1]<<8));
      out[key].push(row);
    }
  }
  return out;
}

function wordsFromHex(hex){
  return wordsFromBytes(bytesFromHex(hex));
}

function hexFromWords(words){
  const parts=[];
  for(const key of PACKED_CORNER_KEYS){
    for(const row of words[key]){
      for(const word of row){
        const v=word&0xffff;
        parts.push((v&255).toString(16).padStart(2,"0"));
        parts.push((v>>8).toString(16).padStart(2,"0"));
      }
    }
  }
  return parts.join("");
}

function decodeWord(word){
  const u=(word&0xffff)+1;
  if(u===65536) return 1.0;
  if(u===1) return 0.0;
  const e=(u>>12)&0xf, m=u&0xfff;
  if(e===0) return (m/4096)*Math.pow(2,-15);
  return ((m+4096)/8192)*Math.pow(2,e-15);
}

function i16Wrap(n){
  const u=n&0xffff;
  return u>=0x8000 ? u-0x10000 : u;
}

function lerpU16(a,b,frac){
  const diff=(b|0)-(a|0);
  const delta=i16Wrap(Math.trunc(Math.fround(diff*Math.fround(frac))));
  return (delta+(a|0))&0xffff;
}

function stageWordsToKernel(row){
  const d0=decodeWord(row[0]), d1=decodeWord(row[1]), d2=decodeWord(row[2]);
  const d3=decodeWord(row[3]), d4=decodeWord(row[4]);
  return [4*d0+d1,d1,4*d2+d3,d3,4*d4];
}

function kernelToBiquad(k){
  const [c0,c1,c2,c3,c4]=k;
  return [c4,(c0-2)*c4,(1-c1)*c4,c2-2,1-c3];
}

function wordsAt(words,morph,q){
  const out=[];
  const A=words.M0_Q0, B=words.M100_Q0, C=words.M0_Q100, D=words.M100_Q100;
  for(let s=0;s<PACKED_STAGES;s++){
    const row=[];
    for(let w=0;w<PACKED_WORDS;w++){
      const e0=lerpU16(A[s][w],B[s][w],morph);
      const e1=lerpU16(C[s][w],D[s][w],morph);
      row.push(lerpU16(e0,e1,q));
    }
    out.push(row);
  }
  return out;
}

function biquadDbCoeffs(bq,f){
  const [b0,b1,b2,a1,a2]=bq;
  const w=PACKED_TAU*f/PACKED_SR, c=Math.cos(w), s=Math.sin(w), c2=Math.cos(2*w), s2=Math.sin(2*w);
  const nr=b0+b1*c+b2*c2, ni=-(b1*s+b2*s2);
  const dr=1+a1*c+a2*c2, di=-(a1*s+a2*s2);
  return 20*Math.log10(Math.max(1e-12,Math.hypot(nr,ni)/Math.max(1e-12,Math.hypot(dr,di))));
}

function packedDb(words,morph,q,f){
  let sum=0;
  for(const row of wordsAt(words,morph,q)) sum+=biquadDbCoeffs(kernelToBiquad(stageWordsToKernel(row)),f);
  return sum;
}


const SR = 39062.5, F_LO = 40, F_HI = 18000, MAX_RADIUS = 0.999999999999999;
const WASM_URL = "wasm/forge_web_wasm.wasm?v=maxr999999999999999";
const SECCOL = ["#ff6a2e", "#ff9a4d", "#ffd7ad", "#9fe7d0", "#37d6c4", "#6fb0e8"];
const $ = (id) => document.getElementById(id);
const V1_LINEUP = [
  {
    "label": "808 Tear",
    "source": "vowel oo",
    "status": "PASS",
    "failures": [],
    "metrics": {
      "objective": 196.819,
      "max_pole_radius": 0.9998999933065588,
      "center_span_db": 139.76232081823372,
      "endpoint_span_db_mean": 118.08597014776211,
      "morph_contrast_rms_db": 54.26507499541276,
      "secondary_contrast_rms_db": 17.864722029097333,
      "center_response_peaks": 4,
      "center_response_valleys": 4,
      "median_zero_motion_octaves": 0.4316469310941182,
      "grid_unstable_rows": 0,
      "interior_unstable_rows": 0
    },
    "lanes": [
      {
        "role": "foundation sub",
        "on": true,
        "pf": 270.0,
        "pfB": 270.0,
        "pr": 0.757230041,
        "prHi": 0.881068315,
        "gain": 0.176151937,
        "zA": {
          "on": true,
          "hz": 139.407185,
          "depth": 0.767271546
        },
        "zB": {
          "on": true,
          "hz": 74.656939,
          "depth": 0.796559557
        }
      },
      {
        "role": "foundation body",
        "on": true,
        "pf": 513.0,
        "pfB": 513.0,
        "pr": 0.811065925,
        "prHi": 0.914393488,
        "gain": 0.11254853,
        "zA": {
          "on": true,
          "hz": 433.91779,
          "depth": 0.858394034
        },
        "zB": {
          "on": true,
          "hz": 800.129685,
          "depth": 0.851006443
        }
      },
      {
        "role": "foundation cap",
        "on": true,
        "pf": 972.0,
        "pfB": 972.0,
        "pr": 0.763799993,
        "prHi": 0.90155033,
        "gain": 0.206501167,
        "zA": {
          "on": true,
          "hz": 1711.387722,
          "depth": 0.718085703
        },
        "zB": {
          "on": true,
          "hz": 735.652016,
          "depth": 0.73211831
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 4523.6,
        "pfB": 6069.014096,
        "pr": 0.9985,
        "prHi": 1.0025,
        "gain": 4.0,
        "zA": {
          "on": true,
          "hz": 2191.914371,
          "depth": 0.979536728
        },
        "zB": {
          "on": true,
          "hz": 5048.023522,
          "depth": 0.999
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 12498.0,
        "pfB": 18359.375,
        "pr": 0.979575322,
        "prHi": 0.998439821,
        "gain": 2.753517333,
        "zA": {
          "on": true,
          "hz": 6386.200932,
          "depth": 0.965545409
        },
        "zB": {
          "on": true,
          "hz": 1673.054877,
          "depth": 0.992461422
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 3600.0,
        "pfB": 11972.48141,
        "pr": 0.77151063,
        "prHi": 0.995723363,
        "gain": 2.197278326,
        "zA": {
          "on": true,
          "hz": 2900.806789,
          "depth": 0.984964668
        },
        "zB": {
          "on": true,
          "hz": 412.171664,
          "depth": 0.997554721
        }
      }
    ]
  },
  {
    "label": "Talking Mouth",
    "source": "vowel ah",
    "status": "PASS",
    "failures": [],
    "metrics": {
      "objective": 197.347,
      "max_pole_radius": 0.9998999933065588,
      "center_span_db": 114.53478407302153,
      "endpoint_span_db_mean": 108.02949195323126,
      "morph_contrast_rms_db": 65.92438203619017,
      "secondary_contrast_rms_db": 23.92699018908206,
      "center_response_peaks": 3,
      "center_response_valleys": 3,
      "median_zero_motion_octaves": 0.4075546157947757,
      "grid_unstable_rows": 0,
      "interior_unstable_rows": 0
    },
    "lanes": [
      {
        "role": "foundation sub",
        "on": true,
        "pf": 270.0,
        "pfB": 270.0,
        "pr": 0.813667597,
        "prHi": 0.948659843,
        "gain": 0.079961365,
        "zA": {
          "on": true,
          "hz": 231.587662,
          "depth": 0.912294456
        },
        "zB": {
          "on": true,
          "hz": 129.722805,
          "depth": 0.762283923
        }
      },
      {
        "role": "foundation body",
        "on": true,
        "pf": 513.0,
        "pfB": 513.0,
        "pr": 0.840571261,
        "prHi": 0.975671884,
        "gain": 0.153625234,
        "zA": {
          "on": true,
          "hz": 598.887942,
          "depth": 0.80423633
        },
        "zB": {
          "on": true,
          "hz": 308.069259,
          "depth": 0.78022972
        }
      },
      {
        "role": "foundation cap",
        "on": true,
        "pf": 972.0,
        "pfB": 972.0,
        "pr": 0.816821606,
        "prHi": 0.952034275,
        "gain": 0.187515973,
        "zA": {
          "on": true,
          "hz": 462.773223,
          "depth": 0.729653849
        },
        "zB": {
          "on": true,
          "hz": 815.231896,
          "depth": 0.789105971
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 1410.7,
        "pfB": 2550.107778,
        "pr": 0.924370678,
        "prHi": 0.99495782,
        "gain": 1.037084779,
        "zA": {
          "on": true,
          "hz": 594.988982,
          "depth": 0.993834798
        },
        "zB": {
          "on": true,
          "hz": 196.055178,
          "depth": 0.999
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 5104.5,
        "pfB": 12869.393015,
        "pr": 0.9985,
        "prHi": 1.0025,
        "gain": 4.0,
        "zA": {
          "on": true,
          "hz": 6788.98368,
          "depth": 0.952716611
        },
        "zB": {
          "on": true,
          "hz": 2541.877911,
          "depth": 0.838762827
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 12445.5,
        "pfB": 18359.375,
        "pr": 0.994707588,
        "prHi": 0.999,
        "gain": 4.0,
        "zA": {
          "on": true,
          "hz": 8079.298001,
          "depth": 0.95795242
        },
        "zB": {
          "on": true,
          "hz": 2290.913253,
          "depth": 0.949995288
        }
      }
    ]
  },
  {
    "label": "Epoch Bank",
    "source": "vlf whistler",
    "status": "PASS",
    "failures": [],
    "metrics": {
      "objective": 203.754,
      "max_pole_radius": 0.9998999933065588,
      "center_span_db": 119.38685215197458,
      "endpoint_span_db_mean": 105.70922706307267,
      "morph_contrast_rms_db": 75.55238904865848,
      "secondary_contrast_rms_db": 18.341181612394628,
      "center_response_peaks": 3,
      "center_response_valleys": 3,
      "median_zero_motion_octaves": 0.4001862140835012,
      "grid_unstable_rows": 0,
      "interior_unstable_rows": 0
    },
    "lanes": [
      {
        "role": "foundation sub",
        "on": true,
        "pf": 270.0,
        "pfB": 270.0,
        "pr": 0.792591252,
        "prHi": 0.920107074,
        "gain": 0.181010611,
        "zA": {
          "on": true,
          "hz": 179.678014,
          "depth": 0.801685186
        },
        "zB": {
          "on": true,
          "hz": 81.553661,
          "depth": 0.781771103
        }
      },
      {
        "role": "foundation body",
        "on": true,
        "pf": 513.0,
        "pfB": 513.0,
        "pr": 0.866353646,
        "prHi": 0.941775531,
        "gain": 0.094014781,
        "zA": {
          "on": true,
          "hz": 653.334109,
          "depth": 0.893108846
        },
        "zB": {
          "on": true,
          "hz": 1313.061725,
          "depth": 0.735033475
        }
      },
      {
        "role": "foundation cap",
        "on": true,
        "pf": 972.0,
        "pfB": 972.0,
        "pr": 0.83075029,
        "prHi": 0.966718339,
        "gain": 0.234802485,
        "zA": {
          "on": true,
          "hz": 629.337767,
          "depth": 0.947194179
        },
        "zB": {
          "on": true,
          "hz": 1824.953048,
          "depth": 0.893714531
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 3195.4,
        "pfB": 4096.829658,
        "pr": 0.9985,
        "prHi": 1.0025,
        "gain": 4.0,
        "zA": {
          "on": true,
          "hz": 1871.85069,
          "depth": 0.930724669
        },
        "zB": {
          "on": true,
          "hz": 1074.842628,
          "depth": 0.931424202
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 5748.1,
        "pfB": 13867.807155,
        "pr": 0.920118128,
        "prHi": 0.997868418,
        "gain": 4.0,
        "zA": {
          "on": true,
          "hz": 2337.031656,
          "depth": 0.908879002
        },
        "zB": {
          "on": true,
          "hz": 466.815365,
          "depth": 0.963663593
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 8748.3,
        "pfB": 18359.375,
        "pr": 0.9985,
        "prHi": 1.0025,
        "gain": 4.0,
        "zA": {
          "on": true,
          "hz": 7469.434839,
          "depth": 0.925714238
        },
        "zB": {
          "on": true,
          "hz": 1700.906152,
          "depth": 0.947886876
        }
      }
    ]
  },
  {
    "label": "Abyss Cut",
    "source": "reactor hall",
    "status": "PASS",
    "failures": [],
    "metrics": {
      "objective": 203.668,
      "max_pole_radius": 0.9998999933065588,
      "center_span_db": 165.04804078298505,
      "endpoint_span_db_mean": 152.1000101711781,
      "morph_contrast_rms_db": 44.24233283597091,
      "secondary_contrast_rms_db": 26.526859354954546,
      "center_response_peaks": 3,
      "center_response_valleys": 3,
      "median_zero_motion_octaves": 0.3669087098184315,
      "grid_unstable_rows": 0,
      "interior_unstable_rows": 0
    },
    "lanes": [
      {
        "role": "foundation sub",
        "on": true,
        "pf": 270.0,
        "pfB": 270.0,
        "pr": 0.824392657,
        "prHi": 0.984727079,
        "gain": 0.124371784,
        "zA": {
          "on": true,
          "hz": 207.831602,
          "depth": 0.951254797
        },
        "zB": {
          "on": true,
          "hz": 94.177685,
          "depth": 0.999
        }
      },
      {
        "role": "foundation body",
        "on": true,
        "pf": 513.0,
        "pfB": 559.397066,
        "pr": 0.805084729,
        "prHi": 0.944425576,
        "gain": 0.06599072,
        "zA": {
          "on": true,
          "hz": 278.9667,
          "depth": 0.96454431
        },
        "zB": {
          "on": true,
          "hz": 167.733844,
          "depth": 0.999
        }
      },
      {
        "role": "foundation cap",
        "on": true,
        "pf": 972.0,
        "pfB": 1060.016418,
        "pr": 0.78144326,
        "prHi": 0.890682536,
        "gain": 0.285013549,
        "zA": {
          "on": true,
          "hz": 592.362673,
          "depth": 0.897150621
        },
        "zB": {
          "on": true,
          "hz": 1150.521725,
          "depth": 0.829729925
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 1081.5,
        "pfB": 1497.678138,
        "pr": 0.9985,
        "prHi": 1.0025,
        "gain": 1.937430331,
        "zA": {
          "on": true,
          "hz": 1864.318214,
          "depth": 0.968026421
        },
        "zB": {
          "on": true,
          "hz": 901.200848,
          "depth": 0.999
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 11437.9,
        "pfB": 18359.375,
        "pr": 0.720481666,
        "prHi": 0.992161604,
        "gain": 4.0,
        "zA": {
          "on": true,
          "hz": 3957.691511,
          "depth": 0.877841882
        },
        "zB": {
          "on": true,
          "hz": 250.977246,
          "depth": 0.916885031
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 16662.3,
        "pfB": 18359.375,
        "pr": 0.747251665,
        "prHi": 0.99564139,
        "gain": 4.0,
        "zA": {
          "on": true,
          "hz": 5513.382198,
          "depth": 0.919429938
        },
        "zB": {
          "on": true,
          "hz": 3197.425211,
          "depth": 0.89950459
        }
      }
    ]
  },
  {
    "label": "Warehouse Acid",
    "source": "vowel ee",
    "status": "PASS",
    "failures": [],
    "metrics": {
      "objective": 184.636,
      "max_pole_radius": 0.9998999933065588,
      "center_span_db": 85.88900137202802,
      "endpoint_span_db_mean": 93.38295134636039,
      "morph_contrast_rms_db": 69.53699887467475,
      "secondary_contrast_rms_db": 18.44344988158242,
      "center_response_peaks": 3,
      "center_response_valleys": 3,
      "median_zero_motion_octaves": 0.5053356131119495,
      "grid_unstable_rows": 0,
      "interior_unstable_rows": 0
    },
    "lanes": [
      {
        "role": "foundation sub",
        "on": true,
        "pf": 270.0,
        "pfB": 253.080473,
        "pr": 0.755376785,
        "prHi": 0.90753446,
        "gain": 0.205141698,
        "zA": {
          "on": true,
          "hz": 198.026605,
          "depth": 0.764792613
        },
        "zB": {
          "on": true,
          "hz": 72.545606,
          "depth": 0.818718849
        }
      },
      {
        "role": "foundation body",
        "on": true,
        "pf": 513.0,
        "pfB": 513.0,
        "pr": 0.848516165,
        "prHi": 0.914979993,
        "gain": 0.070758773,
        "zA": {
          "on": true,
          "hz": 577.219531,
          "depth": 0.706563542
        },
        "zB": {
          "on": true,
          "hz": 1165.352447,
          "depth": 0.575420405
        }
      },
      {
        "role": "foundation cap",
        "on": true,
        "pf": 972.0,
        "pfB": 972.0,
        "pr": 0.785406789,
        "prHi": 0.915829092,
        "gain": 0.213239587,
        "zA": {
          "on": true,
          "hz": 2157.876362,
          "depth": 0.749171126
        },
        "zB": {
          "on": true,
          "hz": 876.018522,
          "depth": 0.624300004
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 2855.8,
        "pfB": 4169.282064,
        "pr": 0.9985,
        "prHi": 1.0025,
        "gain": 4.0,
        "zA": {
          "on": true,
          "hz": 3698.966427,
          "depth": 0.933867505
        },
        "zB": {
          "on": true,
          "hz": 999.186996,
          "depth": 0.782897635
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 12357.5,
        "pfB": 18359.375,
        "pr": 0.923728888,
        "prHi": 0.996362317,
        "gain": 4.0,
        "zA": {
          "on": true,
          "hz": 4624.449665,
          "depth": 0.886303413
        },
        "zB": {
          "on": true,
          "hz": 532.602024,
          "depth": 0.855645878
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 3600.0,
        "pfB": 11309.265411,
        "pr": 0.764193029,
        "prHi": 0.992528517,
        "gain": 1.346845307,
        "zA": {
          "on": true,
          "hz": 8070.520748,
          "depth": 0.860391798
        },
        "zB": {
          "on": true,
          "hz": 259.257681,
          "depth": 0.960240921
        }
      }
    ]
  },
  {
    "label": "Needle Comb",
    "source": "tunnel",
    "status": "PASS",
    "failures": [],
    "metrics": {
      "objective": 178.277,
      "max_pole_radius": 0.9981307201663492,
      "center_span_db": 85.22693753145909,
      "endpoint_span_db_mean": 88.58269190870132,
      "morph_contrast_rms_db": 70.07659923041902,
      "secondary_contrast_rms_db": 26.707186292033647,
      "center_response_peaks": 3,
      "center_response_valleys": 3,
      "median_zero_motion_octaves": 0.6368090559135274,
      "grid_unstable_rows": 0,
      "interior_unstable_rows": 0
    },
    "lanes": [
      {
        "role": "foundation sub",
        "on": true,
        "pf": 270.0,
        "pfB": 270.0,
        "pr": 0.79460349,
        "prHi": 0.979900546,
        "gain": 0.122929233,
        "zA": {
          "on": true,
          "hz": 457.639065,
          "depth": 0.817215158
        },
        "zB": {
          "on": true,
          "hz": 1109.261237,
          "depth": 0.837299239
        }
      },
      {
        "role": "foundation body",
        "on": true,
        "pf": 513.0,
        "pfB": 572.098218,
        "pr": 0.841190354,
        "prHi": 0.929599598,
        "gain": 0.123789998,
        "zA": {
          "on": true,
          "hz": 265.890594,
          "depth": 0.707675367
        },
        "zB": {
          "on": true,
          "hz": 76.423885,
          "depth": 0.636103146
        }
      },
      {
        "role": "foundation cap",
        "on": true,
        "pf": 972.0,
        "pfB": 972.0,
        "pr": 0.850152278,
        "prHi": 0.931399416,
        "gain": 0.236868928,
        "zA": {
          "on": true,
          "hz": 1434.424853,
          "depth": 0.738420052
        },
        "zB": {
          "on": true,
          "hz": 3468.164212,
          "depth": 0.582020816
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 9790.4,
        "pfB": 15129.089983,
        "pr": 0.72,
        "prHi": 0.998130735,
        "gain": 4.0,
        "zA": {
          "on": true,
          "hz": 3965.044027,
          "depth": 0.955875552
        },
        "zB": {
          "on": true,
          "hz": 398.554006,
          "depth": 0.956753627
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 16353.3,
        "pfB": 18359.375,
        "pr": 0.78640713,
        "prHi": 0.992923362,
        "gain": 4.0,
        "zA": {
          "on": true,
          "hz": 15357.555013,
          "depth": 0.899485495
        },
        "zB": {
          "on": true,
          "hz": 5743.248241,
          "depth": 0.831936011
        }
      },
      {
        "role": "source actor",
        "on": true,
        "pf": 3600.0,
        "pfB": 8254.179056,
        "pr": 0.755392007,
        "prHi": 0.996653716,
        "gain": 1.407751464,
        "zA": {
          "on": true,
          "hz": 1565.143838,
          "depth": 0.972520201
        },
        "zB": {
          "on": true,
          "hz": 369.074194,
          "depth": 0.970977353
        }
      }
    ]
  }
];
const state = {
  sources: window.SOURCES || [], si: -1, name: "—",
  sections: [],                 // {on,pf,pr,prSharp,gain,zA:{on,hz,depth},zB:{on,hz,depth}}
  frame: 0, morph: 0, q: 0, src: 0, drive: 0.40, playing: false, loop: false,
  body: null, words: null, maxr: 0, drag: null, selected: 0, loopT0: 0,
  scoring: false, score: null, scoreTimer: 0, scoreSeq: 0, saving: false,
};

// ---------- main-thread WASM (packing only) ----------
let ex = null, mem = null, paramsV = null;
async function initWasm() {
  const buf = await (await fetch(WASM_URL)).arrayBuffer();
  const m = await WebAssembly.instantiate(buf, {});
  ex = m.instance.exports; mem = ex.memory;
  paramsV = new Float64Array(mem.buffer, ex.forge_params_ptr(), Number(ex.forge_params_len()));
}
function packBody() {
  // corners 0=A·broad 1=B·broad 2=A·sharp 3=B·sharp ; param=[on,pf,pr,gain,zon,zhz,zdepth]
  for (let ci = 0; ci < 4; ci++) {
    const useB = (ci === 1 || ci === 3), sharp = (ci === 2 || ci === 3);
    for (let si = 0; si < 6; si++) {
      const s = state.sections[si], z = useB ? s.zB : s.zA, base = (ci * 6 + si) * 7;
      paramsV[base] = s.on ? 1 : 0; paramsV[base + 1] = useB ? (s.pfB ?? s.pf) : s.pf;
      paramsV[base + 2] = sharp ? s.prSharp : s.pr; paramsV[base + 3] = s.gain;
      paramsV[base + 4] = (z.on && z.depth > 0.02) ? 1 : 0; paramsV[base + 5] = z.hz; paramsV[base + 6] = z.depth;
    }
  }
  ex.forge_pack_params();
  const out = new Uint8Array(240);
  out.set(new Uint8Array(mem.buffer, ex.forge_body_ptr(), 240));
  return out;
}
function worstRadius(words) {
  let w = 0;
  for (const [m, q] of [[0, 0], [1, 0], [0, 1], [1, 1], [0.5, 0.5]])
    for (const row of wordsAt(words, m, q)) {
      const bq = kernelToBiquad(stageWordsToKernel(row)), a1 = bq[3], a2 = bq[4], d = a1 * a1 - 4 * a2;
      const r = d < 0 ? Math.sqrt(Math.max(0, a2)) : Math.max(Math.abs((-a1 + Math.sqrt(d)) / 2), Math.abs((-a1 - Math.sqrt(d)) / 2));
      w = Math.max(w, r);
    }
  return w;
}

function responsePeakDb(words) {
  let peak = -1e9;
  for (const [m, q] of [[0, 0], [1, 0], [0, 1], [1, 1], [0.5, 0.5]]) {
    for (let i = 0; i < 96; i++) {
      const f = Math.exp(Math.log(F_LO) + (i / 95) * (Math.log(F_HI) - Math.log(F_LO)));
      peak = Math.max(peak, packedDb(words, m, q, f));
    }
  }
  return peak;
}

function fmtHz(hz) {
  return hz >= 1000 ? `${(hz / 1000).toFixed(hz >= 10000 ? 1 : 2)}k` : `${Math.round(hz)}`;
}
function fmtDb(v) {
  return Number.isFinite(v) ? v.toFixed(1) : "—";
}
function fmtOct(v) {
  return Number.isFinite(v) ? v.toFixed(2) : "—";
}
function bodyHex() {
  return state.body ? [...state.body].map(b => b.toString(16).padStart(2, "0")).join("") : "";
}
function postJson(path, payload) {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then(async res => {
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw new Error(data.error || `${path} failed`);
    return data;
  });
}
function authorPayload() {
  return {
    name: state.name || "untitled",
    foundation: Number($("foundation").value) || null,
    source: state.sources[state.si]?.name || null,
    morph: state.morph,
    q: state.q,
    lanes: state.sections.map(s => ({
      on: !!s.on,
      role: s.role || "lane",
      pf: s.pf,
      pfB: s.pfB ?? s.pf,
      pr: s.pr,
      prHi: s.prSharp,
      gain: s.gain,
      zA: { on: !!s.zA.on, hz: s.zA.hz, depth: s.zA.depth },
      zB: { on: !!s.zB.on, hz: s.zB.hz, depth: s.zB.depth },
    })),
  };
}

function normalizeSourceGains(targetPeak = -24) {
  if (!ex || !state.sections.length) return;
  const body = packBody();
  const words = wordsFromBytes(body);
  const peak = responsePeakDb(words);
  if (!Number.isFinite(peak)) return;
  const neededDb = Math.max(-18, Math.min(30, targetPeak - peak));
  const perStage = Math.pow(10, neededDb / (20 * 6));
  state.sections.forEach(s => { s.gain = Math.max(0.05, Math.min(4.0, s.gain * perStage)); });
}
function driveParams() {
  const d = Math.max(0, Math.min(1, state.drive));
  return {
    agc: 4.0 + 4.0 * d,
    slam: 0.25 * d * d,
    wide: 0,
    inputGain: 1.0,
    makeup: 1.5 + 2.5 * d,
  };
}
function auditionDbOffset() {
  return 20 * Math.log10(driveParams().makeup);
}

// ---------- rebuild body on edit ----------
function rebuild() {
  if (!ex) return;
  state.body = packBody();
  state.words = wordsFromBytes(state.body);
  state.maxr = worstRadius(state.words);
  const v = $("verdict");
  v.textContent = state.maxr >= 1 ? "UNSTABLE" : `max r ${state.maxr.toFixed(6)}`;
  v.className = "pill " + (state.maxr >= 1 ? "hot" : "ok");
  $("rMaxr").textContent = state.maxr.toFixed(6);
  if (anode) anode.port.postMessage({ body: state.body.buffer.slice(0) });
  drawCurve();
  renderLaneDeck();
  scheduleScore();
}

function loadSource(i) {
  const src = state.sources[i]; if (!src) return;
  state.si = i; state.name = src.name; $("srcName").textContent = src.name;
  state.sections = lawSectionsFromSource(src);
  normalizeSourceGains();
  document.querySelectorAll(".src").forEach((el, k) => el.classList.toggle("on", k === i));
  state.dbHi = null;                 // re-freeze the dB frame for this source
  rebuild();
}
function cloneLaneSeed(s) {
  return {
    on: true,
    role: s.role,
    pf: clampHz(s.pf),
    pfB: clampHz(s.pfB ?? s.pf),
    pr: Math.max(0.5, Math.min(MAX_RADIUS, s.pr)),
    prSharp: Math.max(s.pr, Math.min(0.999, s.prHi)),
    gain: Math.max(0.05, Math.min(4.0, s.gain)),
    zA: { on: !!s.zA.on, hz: clampHz(s.zA.hz), depth: Math.max(0, Math.min(0.999, s.zA.depth)) },
    zB: { on: !!s.zB.on, hz: clampHz(s.zB.hz), depth: Math.max(0, Math.min(0.999, s.zB.depth)) },
  };
}
function applyLineupPreset(preset) {
  if (!preset) return;
  const idx = state.sources.findIndex(s => s.name === preset.source);
  if (idx >= 0) {
    state.si = idx;
    state.name = state.sources[idx].name;
    $("srcName").textContent = state.name;
    document.querySelectorAll(".src").forEach((el, k) => el.classList.toggle("on", k === idx));
  } else {
    state.name = preset.source || preset.label || "lineup";
    $("srcName").textContent = state.name;
  }
  state.sections = preset.lanes.map(cloneLaneSeed);
  state.selected = 0;
  state.frame = 0;
  state.morph = 0;
  state.q = 0;
  state.dbHi = null;
  $("saveStatus").textContent = `${preset.label} loaded: ${preset.source} fitted poles, all six lanes zero-bearing`;
  rebuild();
  setMorphQ(0, 0);
}
function clampHz(hz) { return Math.max(F_LO, Math.min(F_HI, hz)); }
function dcpin(pf, r) {   // gain that pins an all-pole section to 0 dB at DC (kills the low-end runaway)
  const th = 2 * Math.PI * clampHz(pf) / SR;
  return Math.max(0.03, Math.min(4.0, (1 - 2 * r * Math.cos(th) + r * r) / Math.max(1e-4, 1 - r * r)));
}
function lane(pf, pfB, pr, prHi, gain, zAhz, zAdepth, zBhz, zBdepth, role) {
  const loR = Math.max(0.5, Math.min(MAX_RADIUS, pr));
  const hiR = Math.max(loR, Math.min(0.999, prHi));
  return {
    on: true, role,
    pf: clampHz(pf), pfB: clampHz(pfB ?? pf),
    pr: loR,
    prSharp: hiR,       // AUTHORED hi-Q radius, per lane (Q is musical, not a slam)
    gain,
    zA: { on: zAdepth > 0.02, hz: clampHz(zAhz), depth: Math.max(0, Math.min(0.985, zAdepth)) },
    zB: { on: zBdepth > 0.02, hz: clampHz(zBhz), depth: Math.max(0, Math.min(0.985, zBdepth)) },
  };
}

function laneWaste(s) {
  const zeroLive = (s.zA?.on && s.zA.depth > 0.02) || (s.zB?.on && s.zB.depth > 0.02);
  const poleTravel = Math.abs(Math.log2((s.pfB ?? s.pf) / s.pf)) > 0.025;
  const qTravel = Math.abs((s.prSharp ?? s.pr) - s.pr) > 0.015;
  return {
    zeroLive,
    poleTravel,
    qTravel,
    live: !!s.on && zeroLive && (poleTravel || qTravel),
  };
}
function renderWaste() {
  if (!$("wasteRead")) return;
  const waste = state.sections.filter(s => !laneWaste(s).live).length;
  $("wasteRead").textContent = `${waste}/6`;
  $("wasteRead").style.color = waste ? "var(--flood)" : "var(--good)";
}
function semitoneTravel(a, b) {
  return Math.round(120 * Math.log2((b || a) / a)) / 10;
}
function cornerTelemetry(s, corner) {
  const useB = corner === 1 || corner === 3;
  const sharp = corner === 2 || corner === 3;
  const z = useB ? s.zB : s.zA;
  return {
    p: useB ? (s.pfB ?? s.pf) : s.pf,
    r: sharp ? s.prSharp : s.pr,
    z: z.hz,
    d: z.depth,
  };
}
function renderLaneDeck() {
  const deck = $("laneDeck");
  if (!deck || !state.sections.length) return;
  renderWaste();
  deck.innerHTML = state.sections.map((s, i) => {
    const w = laneWaste(s);
    const poleTravel = semitoneTravel(s.pf, s.pfB ?? s.pf);
    const zeroTravel = semitoneTravel(s.zA.hz, s.zB.hz);
    const depth = Math.round(100 * Math.max(s.zA.depth || 0, s.zB.depth || 0));
    const cells = ["C0", "C1", "C2", "C3"].map((label, ci) => {
      const c = cornerTelemetry(s, ci);
      return `<div class="cornerCell"><b>${label}</b>p ${fmtHz(c.p)} r ${c.r.toFixed(3)}<br>z ${fmtHz(c.z)} d ${Math.round(c.d * 100)}</div>`;
    }).join("");
    return `<div class="laneRow ${i === state.selected ? "on" : ""}" data-i="${i}">
      <div class="laneTop">
        <div class="laneNo">L${i + 1}</div>
        <div class="laneRole">${s.role || "lane"}</div>
        <div class="laneState ${w.live ? "live" : "waste"}">${w.live ? "live" : "waste"}</div>
      </div>
      <div class="rollerGrid">
        <div class="roller"><label>pole travel <span>${poleTravel.toFixed(1)} st</span></label><input data-k="poleTravel" type="range" min="-24" max="24" step="0.1" value="${poleTravel}"></div>
        <div class="roller"><label>zero travel <span>${zeroTravel.toFixed(1)} st</span></label><input data-k="zeroTravel" type="range" min="-36" max="36" step="0.1" value="${zeroTravel}"></div>
        <div class="roller"><label>zero depth <span>${depth}</span></label><input data-k="zeroDepth" type="range" min="0" max="99" step="1" value="${depth}"></div>
        <div class="roller"><label>radius loQ <span>${s.pr.toFixed(3)}</span></label><input data-k="radiusLo" type="range" min="500" max="999" step="1" value="${Math.round(s.pr * 1000)}"></div>
        <div class="roller"><label>radius hiQ <span>${s.prSharp.toFixed(3)}</span></label><input data-k="radiusHi" type="range" min="520" max="999" step="1" value="${Math.round(s.prSharp * 1000)}"></div>
        <div class="roller"><label>gain <span>${s.gain.toFixed(2)}</span></label><input data-k="gain" type="range" min="5" max="400" step="1" value="${Math.round(s.gain * 100)}"></div>
      </div>
      <div class="cornerStrip">${cells}</div>
    </div>`;
  }).join("");
}
function editLane(index, key, raw) {
  const s = state.sections[index];
  if (!s) return;
  state.selected = index;
  const v = Number(raw);
  if (key === "poleTravel") s.pfB = clampHz(s.pf * Math.pow(2, v / 12));
  if (key === "zeroTravel") {
    const base = s.zA.hz || s.pf;
    s.zB.hz = clampHz(base * Math.pow(2, v / 12));
    s.zB.on = true;
    if (s.zB.depth <= 0.02) s.zB.depth = Math.max(0.70, s.zA.depth || 0);
  }
  if (key === "zeroDepth") {
    const d = Math.max(0, Math.min(0.99, v / 100));
    s.zA.depth = d; s.zB.depth = d; s.zA.on = d > 0.02; s.zB.on = d > 0.02;
  }
  if (key === "radiusLo") s.pr = Math.max(0.5, Math.min(MAX_RADIUS, v / 1000));
  if (key === "radiusHi") s.prSharp = Math.max(0.52, Math.min(0.999, v / 1000));
  if (key === "gain") s.gain = Math.max(0.05, Math.min(4.0, v / 100));
  if (s.prSharp < s.pr) s.prSharp = s.pr;
  state.dbHi = null;
  rebuild();
}
// Source = 3 foundation sections (measured-rail body) + 3 LPC source sections = 12 poles.
// Foundation: held across morph, near-static under Q (weight-bearing, never destroyed).
// Source: travels on morph (pf->pfB) and sharpens on Q; zeros move A->B = the character.
function lawSectionsFromSource(src) {
  const anchorOverride = Number($("foundation").value);
  const PRHI = [0.985, 0.991, 0.996];                     // per-actor hi-Q ceiling; only the last nears the tear
  let k = 0;
  return (src.sections || []).map((s, i) => {
    const role = s.role || (i < 3 ? "foundation body" : "source actor");
    const found = role.indexOf("foundation") === 0;
    let pf = s.pf, pr = s.pr ?? 0.85;
    if (found && anchorOverride > 0 && role.indexOf("sub") >= 0) pf = anchorOverride;
    if (found) {
      const prHi = Math.min(0.90, pr + 0.03);             // Q barely lifts the body -> stays stable
      return lane(pf, pf, pr, prHi, dcpin(pf, pr), pf * 6, 0.0, pf * 6, 0.0, role);   // held body, DC-pinned, no zero
    }
    const j = Math.min(2, k++);
    const away = clampHz(pf * (1.7 + 0.5 * j));            // poles travel A->B (the morph)
    const prHi = Math.min(0.999, Math.max(PRHI[j], pr + 0.012));
    return lane(pf, away, pr, prHi, dcpin(pf, pr), clampHz(pf * 1.6), 0.0, clampHz(pf * 0.62), 0.0, role);  // zeros OFF — you design them
  });
}

// ---------- source rail ----------
function buildRail() {
  const list = $("srclist"); let html = "", grp = "";
  state.sources.forEach((s, i) => {
    if (s.group !== grp) { grp = s.group; html += `<div class="grp">${grp}</div>`; }
    const mx = Math.max(...s.sections.map(x => x.pf));
    const bars = s.sections.map(x => `<i style="height:${20 + 80 * Math.log2(x.pf / 40) / Math.log2(F_HI / 40)}%"></i>`).join("");
    html += `<button class="src" data-i="${i}">${s.name}<div class="poles">${bars}</div></button>`;
  });
  list.innerHTML = html;
  list.querySelectorAll(".src").forEach(b => b.onclick = () => loadSource(+b.dataset.i));
}
function buildLineupGrid() {
  const grid = $("lineupGrid");
  if (!grid) return;
  if (!V1_LINEUP.length) {
    grid.innerHTML = `<button class="lineupBtn" disabled><b>No lineup</b><span>data/v1-lineup.js missing</span></button>`;
    return;
  }
  grid.innerHTML = V1_LINEUP.map((p, i) => {
    const m = p.metrics || {};
    return `<button class="lineupBtn" data-i="${i}"><b>${p.label}</b><span>${p.source} · obj ${fmtDb(m.objective)} · ${m.center_response_peaks ?? "—"}/${m.center_response_valleys ?? "—"} · z ${fmtOct(m.median_zero_motion_octaves)}</span></button>`;
  }).join("");
}

// ---------- curve canvas ----------
const cv = $("curve"), cx = cv.getContext("2d");
let CW = 0, CH = 0, dpr = 1;
const fx = (f, w) => (Math.log(Math.max(F_LO, Math.min(F_HI, f))) - Math.log(F_LO)) / (Math.log(F_HI) - Math.log(F_LO)) * w;
const ifx = (px, w) => Math.exp(Math.log(F_LO) + (px / w) * (Math.log(F_HI) - Math.log(F_LO)));
function curveSamples(m, q, n, w, auditionLevel = true) {
  const a = new Array(n);
  const offset = auditionLevel ? auditionDbOffset() : 0;
  for (let i = 0; i < n; i++) { const f = ifx((i / (n - 1)) * w, w); a[i] = packedDb(state.words, m, q, f) + offset; }
  return a;
}
function tracePath(samples, padL, w, fy) {
  samples.forEach((v, i) => {
    const x = padL + i / (samples.length - 1) * w, y = fy(v);
    i ? cx.lineTo(x, y) : cx.moveTo(x, y);
  });
}
function drawCurve() {
  if (!state.words) return;
  cx.setTransform(dpr, 0, 0, dpr, 0, 0); cx.clearRect(0, 0, CW, CH);
  const padL = 10, padR = 10, padT = 16, padB = 18, w = CW - padL - padR, h = CH - padT - padB;
  const live = curveSamples(state.morph, state.q, Math.max(120, w | 0), w);
  let mx = -1e9; for (const v of live) if (v > mx) mx = v;
  if (state.dbHi == null || mx > state.dbHi - 4) {
    state.dbHi = Math.ceil((mx + 12) / 6) * 6;
    state.dbLo = state.dbHi - 96;
  }
  const HI = state.dbHi, LO = state.dbLo, fy = db => padT + (1 - (Math.max(LO, Math.min(HI, db)) - LO) / (HI - LO)) * h;
  cx.font = "10px Spline Sans Mono";
  // dB grid — locked per source so Q-cranks visibly rise into a stable frame
  for (let db = Math.ceil(LO / 12) * 12; db <= HI - 2; db += 12) {
    const y = fy(db); cx.strokeStyle = db === 0 ? "#27313d" : "#10151c"; cx.lineWidth = 1;
    cx.beginPath(); cx.moveTo(padL, y); cx.lineTo(padL + w, y); cx.stroke();
    cx.fillStyle = "#3a4250"; cx.fillText((db > 0 ? "+" : "") + db, padL + 3, y - 3);
  }
  // freq grid
  cx.strokeStyle = "#141a22"; cx.lineWidth = 1;
  for (const f of [100, 1000, 10000]) { const x = padL + fx(f, w); cx.beginPath(); cx.moveTo(x, padT); cx.lineTo(x, padT + h); cx.stroke();
    cx.fillStyle = "#3a4250"; cx.fillText(f >= 1000 ? f / 1000 + "k" : f, x + 3, padT + h - 4); }
  // corner ghosts
  for (const [m, q, c] of [[0, 0, "rgba(255,106,46,.18)"], [1, 0, "rgba(55,214,196,.18)"], [1, 1, "rgba(255,210,166,.13)"]]) {
    const g = curveSamples(m, q, Math.max(120, w | 0), w); cx.strokeStyle = c; cx.lineWidth = 1; cx.beginPath();
    g.forEach((v, i) => { const x = padL + i / (g.length - 1) * w, y = fy(v); i ? cx.lineTo(x, y) : cx.moveTo(x, y); }); cx.stroke();
  }
  // live curve: packed .body240 magnitude, drawn as a crude instrument plotter trace
  cx.save();
  cx.lineJoin = "miter";
  cx.lineCap = "butt";
  cx.strokeStyle = "#050608";
  cx.lineWidth = 6.0;
  cx.beginPath(); tracePath(live, padL, w, fy); cx.stroke();
  cx.strokeStyle = "#8a3416";
  cx.lineWidth = 3.8;
  cx.beginPath(); tracePath(live, padL, w, fy); cx.stroke();
  cx.strokeStyle = "#ffb26b";
  cx.lineWidth = 1.55;
  cx.beginPath(); tracePath(live, padL, w, fy); cx.stroke();
  cx.fillStyle = "#f4c18a";
  const step = Math.max(14, Math.floor(live.length / 72));
  for (let i = 0; i < live.length; i += step) {
    const x = padL + i / (live.length - 1) * w, y = fy(live[i]);
    cx.fillRect(Math.round(x) - 1, Math.round(y) - 1, 2, 2);
  }
  cx.restore();
  // poles (top ticks) + zero handles (active frame)
  state.sections.forEach((s, i) => {
    if (!s.on) return; const col = SECCOL[i], px = padL + fx(s.pf, w);
    const sel = i === state.selected;
    cx.strokeStyle = col; cx.globalAlpha = sel ? .95 : .55; cx.lineWidth = sel ? 2.5 : 1.5; cx.beginPath(); cx.moveTo(px, padT); cx.lineTo(px, padT + (sel ? 15 : 9)); cx.stroke(); cx.globalAlpha = 1;
    cx.fillStyle = sel ? "#e8ecf2" : "#697384"; cx.font = "10px Spline Sans Mono"; cx.fillText(`L${i + 1}`, px + 4, padT + (sel ? 24 : 18));
    const z = state.frame ? s.zB : s.zA; const zx = padL + fx(z.hz, w); const zy = padT + 12 + z.depth * (h - 24);
    cx.fillStyle = z.depth > 0.02 ? col : "#2a323d"; cx.strokeStyle = col;
    cx.beginPath(); cx.moveTo(zx, zy - 7); cx.lineTo(zx + 6, zy); cx.lineTo(zx, zy + 7); cx.lineTo(zx - 6, zy); cx.closePath();
    cx.fill(); cx.lineWidth = 1.2; cx.stroke();
    if (sel) { cx.strokeStyle = "rgba(255,255,255,.55)"; cx.lineWidth = 1; cx.beginPath(); cx.arc(zx, zy, 13, 0, Math.PI * 2); cx.stroke(); }
  });
  const selected = state.sections[state.selected];
  if (selected) {
    cx.fillStyle = "#697384"; cx.font = "11px Spline Sans Mono";
    cx.fillText(`L${state.selected + 1} · ${selected.role || "lane"} · pole pair + zero pair`, padL + 8, padT + h - 24);
  }
  $("rMorph").textContent = state.morph.toFixed(2); $("rQ").textContent = state.q.toFixed(2);
  $("rMorph2").textContent = Math.round(state.morph * 100);
  $("rQ2").textContent = Math.round(state.q * 100);
}

function renderScore(score) {
  const grid = $("gateGrid");
  if (!grid) return;
  if (!score) {
    grid.innerHTML = ["stable", "radius", "span", "morph", "q", "peaks", "valleys", "zeros"]
      .map(k => `<div class="gate">${k}</div>`).join("");
    return;
  }
  const gates = score.gates || {};
  grid.innerHTML = ["stable", "radius", "span", "morph", "q", "peaks", "valleys", "zeros"].map(k =>
    `<div class="gate ${gates[k] ? "pass" : "fail"}">${k}<br>${gates[k] ? "PASS" : "FAIL"}</div>`
  ).join("");
  const m = score.metrics || {};
  $("scoreRead").textContent = score.verdict === "PASS" ? `PASS ${fmtDb(m.objective)}` : `FAIL ${fmtDb(m.objective)}`;
  $("scoreRead").style.color = score.verdict === "PASS" ? "var(--good)" : "var(--flood)";
  $("scoreMorph").textContent = fmtDb(m.morph_contrast_rms_db);
  $("scoreQ").textContent = fmtDb(m.secondary_contrast_rms_db);
  $("scorePeaks").textContent = m.center_response_peaks ?? "—";
  $("scoreValleys").textContent = m.center_response_valleys ?? "—";
  $("scoreZero").textContent = fmtOct(m.median_zero_motion_octaves);
}
function scheduleScore() {
  if (!$("gateGrid") || !state.body) return;
  clearTimeout(state.scoreTimer);
  state.scoreTimer = setTimeout(scoreNow, 280);
}
async function scoreNow() {
  if (!state.body || location.protocol === "file:") {
    renderScore(null);
    return;
  }
  const seq = ++state.scoreSeq;
  try {
    state.scoring = true;
    const score = await postJson("/score", { hex: bodyHex(), grid: 9 });
    if (seq !== state.scoreSeq) return;
    state.score = score;
    renderScore(score);
  } catch (err) {
    if ($("saveStatus")) $("saveStatus").textContent = "score offline: run python tools/forge_author_server.py";
    renderScore(null);
  } finally {
    state.scoring = false;
  }
}
function curveHit(px, py) {
  const padL = 10, padT = 16, padB = 18, w = CW - 20, h = CH - padT - padB;
  let best = -1, bd = 34;
  state.sections.forEach((s, i) => { if (!s.on) return; const z = state.frame ? s.zB : s.zA;
    const zx = padL + fx(z.hz, w), zy = padT + 12 + z.depth * (h - 24), d = Math.hypot(px - zx, py - zy);
    if (d < bd) { bd = d; best = i; } });
  return best;
}
function nearestSection(px) {
  const padL = 10, w = CW - 20;
  let best = 0, bd = Infinity;
  state.sections.forEach((s, i) => {
    if (!s.on) return;
    const z = state.frame ? s.zB : s.zA;
    const anchor = z.on && z.depth > 0.02 ? z.hz : s.pf;
    const d = Math.abs(px - (padL + fx(anchor, w)));
    if (d < bd) { bd = d; best = i; }
  });
  return best;
}
cv.addEventListener("pointerdown", e => {
  const r = cv.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top, i = curveHit(px, py);
  state.drag = i >= 0 ? i : nearestSection(px);
  state.selected = state.drag;
  cv.setPointerCapture(e.pointerId);
  curveDrag(px, py);
});
cv.addEventListener("pointermove", e => { if (typeof state.drag !== "number") return; const r = cv.getBoundingClientRect(); curveDrag(e.clientX - r.left, e.clientY - r.top); });
cv.addEventListener("pointerup", () => { state.drag = null; });
function curveDrag(px, py) {
  const padL = 10, padT = 16, padB = 18, w = CW - 20, h = CH - padT - padB;
  const s = state.sections[state.drag], z = state.frame ? s.zB : s.zA;
  z.hz = Math.max(F_LO, Math.min(F_HI, ifx(px - padL, w)));
  if (!z.on || z.depth <= 0.02) z.depth = 0.78;
  else z.depth = Math.max(0.08, Math.min(MAX_RADIUS, (py - padT - 12) / (h - 24)));
  z.on = z.depth > 0.02;
  rebuild();
}

// ---------- morph × Q pad ----------
const pad = $("pad"), px2 = pad.getContext("2d"); let PW = 0, PH = 0;
function drawPad() {
  px2.setTransform(dpr, 0, 0, dpr, 0, 0); px2.clearRect(0, 0, PW, PH);
  px2.strokeStyle = "#1b2029"; for (let i = 1; i < 4; i++) { px2.beginPath(); px2.moveTo(PW * i / 4, 0); px2.lineTo(PW * i / 4, PH); px2.moveTo(0, PH * i / 4); px2.lineTo(PW, PH * i / 4); px2.stroke(); }
  const x = state.morph * PW, y = (1 - state.q) * PH;
  px2.strokeStyle = "rgba(255,106,46,.3)"; px2.beginPath(); px2.moveTo(x, 0); px2.lineTo(x, PH); px2.moveTo(0, y); px2.lineTo(PW, y); px2.stroke();
  px2.save(); px2.shadowColor = "#ff6a2e"; px2.shadowBlur = 18; px2.fillStyle = "#ffd2a6";
  px2.beginPath(); px2.arc(x, y, 9, 0, 7); px2.fill(); px2.restore();
  px2.fillStyle = "#120600"; px2.beginPath(); px2.arc(x, y, 3.5, 0, 7); px2.fill();
}
function setMorphQ(morph, q) {
  state.morph = Math.max(0, Math.min(1, morph));
  state.q = Math.max(0, Math.min(1, q));
  $("morphSlider").value = Math.round(state.morph * 100);
  $("qSlider").value = Math.round(state.q * 100);
  drawPad(); drawCurve(); pushParams();
}
function padSet(px, py) { setMorphQ(px / PW, 1 - py / PH); }
pad.addEventListener("pointerdown", e => { state.drag = "pad"; pad.setPointerCapture(e.pointerId); const r = pad.getBoundingClientRect(); padSet(e.clientX - r.left, e.clientY - r.top); });
pad.addEventListener("pointermove", e => { if (state.drag !== "pad") return; const r = pad.getBoundingClientRect(); padSet(e.clientX - r.left, e.clientY - r.top); });
pad.addEventListener("pointerup", () => { state.drag = null; });

// ---------- audio: worklet drive chain (mirrors forge.js) ----------
let actx = null, anode = null;
function pushParams() {
  if (!anode) return;
  const p = driveParams();
  anode.port.postMessage({ params: {
    morph: state.morph, q: state.q,
    agc: p.agc,
    slam: p.slam,
    wide: p.wide,
    inputGain: p.inputGain,
    makeup: p.makeup,
  } });
}
async function startAudio() {
  actx = new (window.AudioContext || window.webkitAudioContext)();
  const wasm = await (await fetch(WASM_URL)).arrayBuffer();
  await actx.audioWorklet.addModule("js/forge-worklet.js");
  anode = new AudioWorkletNode(actx, "forge-processor", { numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [2],
    processorOptions: { wasm, body: state.body ? state.body.buffer.slice(0) : null, src: state.src } });
  anode.port.onmessage = e => {
    if (e.data.ready) { pushParams(); if (state.playing) anode.port.postMessage({ playing: true }); }
    if (e.data.level != null) updateMeter(e.data.peak, e.data.level);
    if (e.data.error) $("verdict").textContent = "audio: " + e.data.error;
  };
  anode.connect(actx.destination);
}
async function toggleAudio() {
  try { if (!actx) await startAudio(); if (actx.state === "suspended") await actx.resume();
    state.playing = !state.playing; if (anode) anode.port.postMessage({ playing: state.playing });
    $("play").classList.toggle("on", state.playing); $("play").textContent = state.playing ? "❚❚ STOP" : "▶ PLAY";
  } catch (err) { $("verdict").textContent = "audio failed"; console.error(err); }
}
function updateMeter(peak, rms) {
  const m = $("meter"), bar = m.firstElementChild;
  bar.style.height = Math.min(100, rms * 140) + "%";
  m.classList.toggle("flood", peak > 0.985);
}

// ---------- transport ----------
$("play").onclick = toggleAudio;
$("drive").oninput = e => { state.drive = e.target.value / 100; $("rDrive").textContent = e.target.value; state.dbHi = null; pushParams(); drawCurve(); };
$("morphSlider").oninput = e => setMorphQ(e.target.value / 100, state.q);
$("qSlider").oninput = e => setMorphQ(state.morph, e.target.value / 100);
$("foundation").onchange = () => { if (state.si >= 0) { loadSource(state.si); } };
document.querySelectorAll(".chip").forEach(c => c.onclick = () => {
  document.querySelectorAll(".chip").forEach(x => x.classList.remove("on")); c.classList.add("on");
  state.src = +c.dataset.src; if (anode) anode.port.postMessage({ src: state.src });
});
document.querySelectorAll(".tab").forEach(tb => tb.onclick = () => {
  state.frame = +tb.dataset.frame; document.querySelectorAll(".tab").forEach(x => x.classList.toggle("on", x === tb)); drawCurve();
});
$("loop").onclick = () => { state.loop = !state.loop; $("loop").style.color = state.loop ? "var(--heat)" : ""; state.loopT0 = performance.now(); };
$("lineupGrid")?.addEventListener("click", e => {
  const btn = e.target.closest("button[data-i]");
  if (!btn) return;
  applyLineupPreset(V1_LINEUP[+btn.dataset.i]);
});
$("save").onclick = () => {
  saveBake();
};
async function saveBake() {
  if (!state.body || state.saving) return;
  const status = $("saveStatus");
  state.saving = true;
  $("save").textContent = "BAKING…";
  if (status) status.textContent = "baking through trench_core…";
  try {
    const res = await postJson("/bake", authorPayload());
    const score = res.score;
    if (score) { state.score = score; renderScore(score); }
    if (status) {
      const slot = res.audition || {};
      const slotLine = slot.json ? `<br>Forge Audition slot → ${slot.json}` : "";
      status.innerHTML = `saved ${res.verdict} · max r ${res.maxr.toFixed(6)} · <a href="/sessions/${res.session}/workbench.html">session ${res.session}</a><br>${res.dir}${slotLine}`;
    }
    $("verdict").textContent = `${res.verdict} baked`;
    $("verdict").className = "pill " + (res.verdict === "PASS" ? "ok" : "hot");
  } catch (err) {
    if (status) status.textContent = `bake failed: ${err.message}`;
    $("verdict").textContent = "bake failed";
    $("verdict").className = "pill hot";
  } finally {
    state.saving = false;
    $("save").textContent = "SAVE → BAKE";
  }
}

// ---------- fitter: open audio -> trim in/out -> LPC/LSP fit -> source ----------
const wc = $("waveCanvas"), wcx = wc ? wc.getContext("2d") : null;
let WW = 0, WH = 0;
state.audio = null; state.inSec = 0; state.outSec = 0;
state.fit = { found: 3, preemph: 0.97, crank: 0, qsource: "lpc", target: "new" };

function fitStatus(msg, cls = "") { const el = $("fitStatus"); if (el) { el.textContent = msg; el.className = cls; } }

function drawWave() {
  if (!wcx) return;
  wcx.setTransform(dpr, 0, 0, dpr, 0, 0); wcx.clearRect(0, 0, WW, WH);
  if (!state.audio) {
    wcx.fillStyle = "#3a4250"; wcx.font = "12px Spline Sans Mono";
    wcx.fillText("open an audio file to fit  →", 14, WH / 2);
    return;
  }
  const buf = state.audio.buf, n = buf.length, mid = WH / 2, cols = Math.max(1, Math.floor(WW));
  wcx.strokeStyle = "#243040"; wcx.lineWidth = 1; wcx.beginPath();
  for (let px = 0; px < cols; px++) {
    const a = Math.floor(px / cols * n), b = Math.max(a + 1, Math.floor((px + 1) / cols * n));
    let mn = 1, mx = -1;
    for (let i = a; i < b; i++) { const v = buf[i]; if (v < mn) mn = v; if (v > mx) mx = v; }
    wcx.moveTo(px + 0.5, mid - mx * mid * 0.92); wcx.lineTo(px + 0.5, mid - mn * mid * 0.92);
  }
  wcx.stroke();
  const dur = state.audio.dur || 1;
  const ix = state.inSec / dur * WW, ox = state.outSec / dur * WW;
  wcx.fillStyle = "rgba(255,106,46,.12)"; wcx.fillRect(ix, 0, ox - ix, WH);
  for (const [hx, col] of [[ix, "#ff6a2e"], [ox, "#37d6c4"]]) {
    wcx.strokeStyle = col; wcx.lineWidth = 2; wcx.beginPath(); wcx.moveTo(hx, 0); wcx.lineTo(hx, WH); wcx.stroke();
    wcx.fillStyle = col; wcx.fillRect(hx - 3, 0, 6, 6); wcx.fillRect(hx - 3, WH - 6, 6, 6);
  }
  wcx.fillStyle = "#8a93a3"; wcx.font = "10px Spline Sans Mono";
  wcx.fillText(`${(state.outSec - state.inSec).toFixed(3)} s`, Math.max(4, (ix + ox) / 2 - 18), 12);
}

async function openAudioFile(file) {
  if (!file) return;
  try {
    fitStatus("decoding…");
    const arr = await file.arrayBuffer();
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const buf = await ac.decodeAudioData(arr); ac.close();
    const ch = buf.numberOfChannels, n = buf.length, mono = new Float32Array(n);
    for (let c = 0; c < ch; c++) { const d = buf.getChannelData(c); for (let i = 0; i < n; i++) mono[i] += d[i] / ch; }
    const dur = n / buf.sampleRate, nm = file.name.replace(/\.[^.]+$/, "");
    state.audio = { buf: mono, sr: buf.sampleRate, dur, name: nm };
    const win = Math.min(0.30, dur);
    state.inSec = Math.max(0, dur / 2 - win / 2); state.outSec = Math.min(dur, state.inSec + win);
    if ($("waveName")) $("waveName").textContent = nm;
    if ($("waveMeta")) $("waveMeta").textContent = `${dur.toFixed(2)}s · ${(buf.sampleRate / 1000).toFixed(1)}k · ${ch}ch`;
    if ($("fitName") && !$("fitName").value) $("fitName").value = nm.slice(0, 24);
    drawWave();
    fitStatus("trim the slice, then FIT");
  } catch (err) { fitStatus("decode failed: " + err.message, "bad"); }
}

let waveDrag = null;
function waveMove(px) {
  const s = Math.max(0, Math.min(state.audio.dur, (px / WW) * state.audio.dur));
  if (waveDrag === "in") state.inSec = Math.min(s, state.outSec - 0.01);
  else state.outSec = Math.max(s, state.inSec + 0.01);
  drawWave();
}
if (wc) {
  wc.addEventListener("pointerdown", e => {
    if (!state.audio) return;
    const r = wc.getBoundingClientRect(), px = e.clientX - r.left;
    const ix = state.inSec / state.audio.dur * WW, ox = state.outSec / state.audio.dur * WW;
    waveDrag = Math.abs(px - ix) <= Math.abs(px - ox) ? "in" : "out";
    wc.setPointerCapture(e.pointerId); waveMove(px);
  });
  wc.addEventListener("pointermove", e => { if (!waveDrag) return; const r = wc.getBoundingClientRect(); waveMove(e.clientX - r.left); });
  wc.addEventListener("pointerup", () => { waveDrag = null; });
}

async function doFit() {
  if (!state.audio) { fitStatus("open an audio file first", "bad"); return; }
  if (location.protocol === "file:") { fitStatus("run from tools/forge_author_server.py to fit", "bad"); return; }
  const sr = state.audio.sr, a = Math.floor(state.inSec * sr), b = Math.floor(state.outSec * sr);
  const slice = Array.from(state.audio.buf.subarray(a, b));
  if (slice.length < 256) { fitStatus("selection too short — widen it", "bad"); return; }
  fitStatus("fitting…"); $("fitBtn").disabled = true;
  try {
    const res = await postJson("/fit", {
      samples: slice, sr,
      name: ($("fitName").value || state.audio.name || "fit").trim(),
      found: state.fit.found, preemph: state.fit.preemph, crank: state.fit.crank, qsource: state.fit.qsource,
    });
    applyFit(res);
  } catch (err) { fitStatus("fit failed: " + err.message, "bad"); }
  finally { $("fitBtn").disabled = false; }
}

function applyFit(res) {
  const src = res.source;
  const note = `${res.poles} · waste ${res.waste} · lsf ${res.lsf_stable ? "ok" : "BAD"}`;
  if (state.fit.target === "new") {
    const exist = state.sources.findIndex(s => s.name === src.name);
    if (exist >= 0) state.sources[exist] = src; else state.sources.push(src);
    buildRail();
    loadSource(state.sources.findIndex(s => s.name === src.name));
    fitStatus("loaded as new source · " + note, "ok");
  } else {
    const which = state.fit.target;
    const fitActors = (src.sections || []).filter(s => (s.role || "").startsWith("source"));
    const laneActors = state.sections.filter(s => (s.role || "").startsWith("source"));
    laneActors.forEach((s, k) => {
      const f = fitActors[k]; if (!f) return;
      if (which === "A") { s.pf = clampHz(f.pf); s.pr = Math.max(0.5, Math.min(MAX_RADIUS, f.pr)); if (s.prSharp < s.pr) s.prSharp = s.pr; }
      else { s.pfB = clampHz(f.pf); }
    });
    state.dbHi = null; rebuild();
    fitStatus(`applied to frame ${which} (${laneActors.length} actors) · ` + note, "ok");
  }
}

// fitter wiring
$("openAudio") && ($("openAudio").onclick = () => $("audioFile").click());
$("audioFile") && ($("audioFile").onchange = e => { openAudioFile(e.target.files[0]); e.target.value = ""; });
$("fitFound") && ($("fitFound").oninput = e => { state.fit.found = +e.target.value; $("fitFoundVal").textContent = e.target.value; });
$("fitPre") && ($("fitPre").oninput = e => { state.fit.preemph = +e.target.value / 100; $("fitPreVal").textContent = state.fit.preemph.toFixed(2); });
$("fitCrank") && ($("fitCrank").oninput = e => { state.fit.crank = +e.target.value / 100; $("fitCrankVal").textContent = e.target.value; });
$("fitQsource") && ($("fitQsource").onclick = e => { const b = e.target.closest("button[data-q]"); if (!b) return; state.fit.qsource = b.dataset.q;[...e.currentTarget.children].forEach(x => x.classList.toggle("on", x === b)); });
$("fitTarget") && ($("fitTarget").onclick = e => { const b = e.target.closest("button[data-t]"); if (!b) return; state.fit.target = b.dataset.t;[...e.currentTarget.children].forEach(x => x.classList.toggle("on", x === b)); });
$("fitBtn") && ($("fitBtn").onclick = doFit);

// ---------- loop + resize ----------
function tick(now) {
  if (state.loop) { const bar = (60 / 140) * 4 * 1000; setMorphQ(((now - state.loopT0) % bar) / bar, state.q); }
  requestAnimationFrame(tick);
}
function resize() {
  dpr = Math.min(2, window.devicePixelRatio || 1);
  for (const [c, setW] of [[cv, (w, h) => { CW = w; CH = h; }], [pad, (w, h) => { PW = w; PH = h; }], [wc, (w, h) => { WW = w; WH = h; }]]) {
    if (!c) continue;
    const r = c.getBoundingClientRect(); c.width = Math.round(r.width * dpr); c.height = Math.round(r.height * dpr); setW(r.width, r.height);
  }
  drawCurve(); drawPad(); drawWave();
}
window.addEventListener("resize", resize);
$("laneDeck")?.addEventListener("pointerdown", e => {
  const row = e.target.closest(".laneRow");
  if (!row) return;
  state.selected = +row.dataset.i;
  drawCurve();
});
$("laneDeck")?.addEventListener("input", e => {
  const input = e.target.closest("input[data-k]");
  if (!input) return;
  const row = input.closest(".laneRow");
  editLane(+row.dataset.i, input.dataset.k, input.value);
});

// ---------- boot ----------
(async () => {
  buildRail();
  buildLineupGrid();
  renderScore(null);
  $("save").textContent = "SAVE → BAKE";
  try { await initWasm(); } catch (e) { $("verdict").textContent = "wasm load failed"; console.error(e); }
  resize();
  if (state.sources.length) loadSource(0);
  requestAnimationFrame(tick);
})();
