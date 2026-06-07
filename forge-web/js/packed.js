const SR=39062.5, TAU=Math.PI*2;

const CORNER_KEYS=["M0_Q0","M100_Q0","M0_Q100","M100_Q100"];
const STAGES=6, WORDS=5;

export function bytesFromHex(hex){
  const clean=String(hex||"").replace(/[^0-9a-fA-F]/g,"");
  const out=new Uint8Array(clean.length/2);
  for(let i=0;i<out.length;i++) out[i]=parseInt(clean.slice(i*2,i*2+2),16);
  return out;
}

export function wordsFromBytes(bytes){
  const out={};
  let p=0;
  for(const key of CORNER_KEYS){
    out[key]=[];
    for(let s=0;s<STAGES;s++){
      const row=[];
      for(let w=0;w<WORDS;w++,p+=2) row.push(bytes[p]|(bytes[p+1]<<8));
      out[key].push(row);
    }
  }
  return out;
}

export function wordsFromHex(hex){
  return wordsFromBytes(bytesFromHex(hex));
}

export function hexFromWords(words){
  const parts=[];
  for(const key of CORNER_KEYS){
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

export function decodeWord(word){
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

export function lerpU16(a,b,frac){
  const diff=(b|0)-(a|0);
  const delta=i16Wrap(Math.trunc(Math.fround(diff*Math.fround(frac))));
  return (delta+(a|0))&0xffff;
}

export function stageWordsToKernel(row){
  const d0=decodeWord(row[0]), d1=decodeWord(row[1]), d2=decodeWord(row[2]);
  const d3=decodeWord(row[3]), d4=decodeWord(row[4]);
  return [4*d0+d1,d1,4*d2+d3,d3,4*d4];
}

export function kernelToBiquad(k){
  const [c0,c1,c2,c3,c4]=k;
  return [c4,(c0-2)*c4,(1-c1)*c4,c2-2,1-c3];
}

export function wordsAt(words,morph,q){
  const out=[];
  const A=words.M0_Q0, B=words.M100_Q0, C=words.M0_Q100, D=words.M100_Q100;
  for(let s=0;s<STAGES;s++){
    const row=[];
    for(let w=0;w<WORDS;w++){
      const e0=lerpU16(A[s][w],B[s][w],morph);
      const e1=lerpU16(C[s][w],D[s][w],morph);
      row.push(lerpU16(e0,e1,q));
    }
    out.push(row);
  }
  return out;
}

export function biquadDbCoeffs(bq,f){
  const [b0,b1,b2,a1,a2]=bq;
  const w=TAU*f/SR, c=Math.cos(w), s=Math.sin(w), c2=Math.cos(2*w), s2=Math.sin(2*w);
  const nr=b0+b1*c+b2*c2, ni=-(b1*s+b2*s2);
  const dr=1+a1*c+a2*c2, di=-(a1*s+a2*s2);
  return 20*Math.log10(Math.max(1e-12,Math.hypot(nr,ni)/Math.max(1e-12,Math.hypot(dr,di))));
}

export function packedDb(words,morph,q,f){
  let sum=0;
  for(const row of wordsAt(words,morph,q)) sum+=biquadDbCoeffs(kernelToBiquad(stageWordsToKernel(row)),f);
  return sum;
}

export function compiledFromPacked(body){
  return body.compiled || {
    format:"compiled-v1",
    name:body.name,
    sampleRate:SR,
    authoring_sample_rate_hz:SR,
    stages:STAGES,
    cornerOrder:CORNER_KEYS,
    keyframes:CORNER_KEYS.map((label,idx)=>({
      label,
      morph:idx&1?1:0,
      q:idx&2?1:0,
      boost:1,
      packedWords:body.words[label],
      stages:[],
    })),
  };
}

export function downloadText(filename,text,type="application/json"){
  const blob=new Blob([text],{type});
  const a=document.createElement("a");
  a.href=URL.createObjectURL(blob);
  a.download=filename;
  a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href),1000);
}

export function downloadBody(filename,hex){
  downloadText(filename,bytesFromHex(hex),"application/octet-stream");
}
