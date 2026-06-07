const PARAMS_PER_STAGE=7;
const STAGES=6;
const CORNERS=4;

let wasmReady=null;

async function loadWasm(){
  if(wasmReady) return wasmReady;
  wasmReady=(async()=>{
    const res=await fetch("wasm/forge_web_wasm.wasm");
    const bytes=await res.arrayBuffer();
    const mod=await WebAssembly.instantiate(bytes,{});
    return mod.instance.exports;
  })();
  return wasmReady;
}

export async function packWithCore(corners){
  const ex=await loadWasm();
  const paramsPtr=ex.forge_params_ptr();
  const paramsLen=Number(ex.forge_params_len());
  const memory=ex.memory;
  const params=new Float64Array(memory.buffer,paramsPtr,paramsLen);
  let p=0;
  for(let ci=0;ci<CORNERS;ci++){
    for(let si=0;si<STAGES;si++){
      const s=corners[ci][si];
      params[p++]=s.on?1:0;
      params[p++]=s.hz;
      params[p++]=s.r;
      params[p++]=s.gain;
      params[p++]=s.cutOn?1:0;
      params[p++]=s.cutHz;
      params[p++]=s.cutDepth;
    }
  }
  const rc=ex.forge_pack_params();
  if(rc!==0) throw new Error(`pack failed: ${rc}`);
  const bodyPtr=ex.forge_body_ptr();
  const bodyLen=Number(ex.forge_body_len());
  return new Uint8Array(memory.buffer,bodyPtr,bodyLen).slice();
}

export function bodyHex(bytes){
  return [...bytes].map(b=>b.toString(16).padStart(2,"0")).join("");
}
