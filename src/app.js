
"use strict";
function grayPalette(){const p=new Uint8Array(256*3);for(let i=0;i<256;i++){p[i*3]=p[i*3+1]=p[i*3+2]=i;}return p;}
function greenPalette(){ // wireframe-ish: dark->teal->amber for status feel
  const p=new Uint8Array(256*3);
  for(let i=0;i<256;i++){const t=i/255;
    p[i*3]=Math.round(20+t*t*235); p[i*3+1]=Math.round(30+t*200); p[i*3+2]=Math.round(30+t*120);}
  return p;
}
// auto palette: distinct, high-contrast colors keyed by index so shapes are visible
function autoPalette(usedSet){
  const p=new Uint8Array(256*3);
  const used=[...usedSet].filter(i=>i!==0).sort((a,b)=>a-b);
  const n=Math.max(used.length,1);
  used.forEach((idx,k)=>{
    const h=(k/n)*300; // spread hue
    const [r,g,b]=hsl(h,.72,.6); p[idx*3]=r;p[idx*3+1]=g;p[idx*3+2]=b;
  });
  return p;
}
function hsl(h,s,l){h/=360;const q=l<.5?l*(1+s):l+s-l*s,pp=2*l-q;
  const f=t=>{t=(t+1)%1;if(t<1/6)return pp+(q-pp)*6*t;if(t<.5)return q;if(t<2/3)return pp+(q-pp)*(2/3-t)*6;return pp;};
  return [Math.round(f(h+1/3)*255),Math.round(f(h)*255),Math.round(f(h-1/3)*255)];}

// parse an uploaded palette file -> Uint8Array(768) or null
function parsePaletteFile(buf,name){
  const b=new Uint8Array(buf); const asc=new TextDecoder().decode(b.slice(0,16));
  if(asc.startsWith('JASC-PAL')){
    const lines=new TextDecoder().decode(b).split(/\r?\n/); const out=new Uint8Array(768);
    const cnt=parseInt(lines[2])||256;
    for(let i=0;i<Math.min(cnt,256);i++){const p=(lines[3+i]||'').trim().split(/\s+/);
      out[i*3]=+p[0]||0;out[i*3+1]=+p[1]||0;out[i*3+2]=+p[2]||0;}
    return out;
  }
  // RIFF PAL
  if(asc.startsWith('RIFF')){const dv=new DataView(buf);
    // find 'data'
    for(let o=12;o<b.length-8;o+=2){if(b[o]===0x64&&b[o+1]===0x61&&b[o+2]===0x74&&b[o+3]===0x61){
      const entries=dv.getUint16(o+8,true); const out=new Uint8Array(768);
      for(let i=0;i<Math.min(entries,256);i++){const base=o+10+i*4;out[i*3]=b[base];out[i*3+1]=b[base+1];out[i*3+2]=b[base+2];}
      return out;}}
  }
  // PCX embedded VGA palette (last 769 bytes, marker 0x0C) — for .pcx uploads
  if(name.toLowerCase().endsWith('.pcx') && b.length>769 && b[b.length-769]===0x0C){
    return b.slice(b.length-768);
  }
  // raw sizes
  if(b.length===768) return b.slice(0,768);                 // 256 * RGB
  if(b.length===1024){const out=new Uint8Array(768);        // 256 * RGBA / BGRA style
    for(let i=0;i<256;i++){out[i*3]=b[i*4];out[i*3+1]=b[i*4+1];out[i*3+2]=b[i*4+2];}return out;}
  if(b.length===772) return b.slice(0,768);                 // Adobe .act with trailer
  return null;
}

// ---------- classic GRP ----------
// Frame anomaly flags — reported, never silently repaired. Same meaning as
// scgrp/grp.hpp so the two agree.
const F_CLAMP=1, F_BADOFF=2, F_SHORT=4, F_FLAT=8;

// Not every .grp is RLE: game\icons.grp stores flat uncompressed bitmaps with
// no row table. Discriminator: frame 1's data begins exactly w0*h0 after
// frame 0's. Decoding such a file as RLE yields nothing at all.
function classicIsFlat(b,dv,N){
  if(N<6+16) return false;
  const fc=dv.getUint16(0,true);
  if(fc<2 || 6+fc*8>N) return false;
  const w0=b[6+2], h0=b[6+3];
  if(!w0||!h0) return false;
  return dv.getUint32(6+8+4,true)===(dv.getUint32(6+4,true)+w0*h0)>>>0;
}

function parseClassicGRP(buf){
  const dv=new DataView(buf), b=new Uint8Array(buf), N=b.length;
  const u16=o=>(o>=0&&o+2<=N)?dv.getUint16(o,true):0;
  const u32=o=>(o>=0&&o+4<=N)?dv.getUint32(o,true):0;
  const frameCount=u16(0), maxW=u16(2), maxH=u16(4);
  // validity guard — helps diagnose a misidentified / non-classic file
  if(frameCount===0) throw new Error('0 frames — probably not a classic GRP');
  if(6+frameCount*8>N) throw new Error('frame headers exceed file size (frameCount='+frameCount+', size='+N+') — probably not a classic GRP or a different format');
  const flat=classicIsFlat(b,dv,N);
  const frames=[]; const used=new Set(); let bad=0, clamped=0;
  for(let i=0;i<frameCount;i++){
    const o=6+i*8;
    const fx=b[o], fy=b[o+1], fw=b[o+2], fh=b[o+3], foff=u32(o+4);
    const idx=new Uint8Array(fw*fh); let flags=0;
    const need=fw*fh;
    if(foff<=0||foff>=N||(flat&&foff+need>N)){
      flags|=F_BADOFF; bad++;
    } else if(flat){
      flags|=F_FLAT;
      idx.set(b.subarray(foff,foff+need));
      for(const v of idx) if(v) used.add(v);
    } else {
      for(let row=0;row<fh;row++){
        const lo=u16(foff+row*2);
        let p=foff+lo, x=0;
        while(x<fw && p<N){
          const c=b[p++];
          if(c>=0x80){ let n=c-0x80; if(n>fw-x){n=fw-x;flags|=F_CLAMP;} x+=n; }
          else if(c>=0x40){ let n=c-0x40; const val=b[p++];
            if(n>fw-x){n=fw-x;flags|=F_CLAMP;}
            for(let k=0;k<n;k++){idx[row*fw+x++]=val; if(val)used.add(val);} }
          else { let n=c; if(n>fw-x){n=fw-x;flags|=F_CLAMP;}
            for(let k=0;k<n&&p<N;k++){const val=b[p++]; idx[row*fw+x++]=val; if(val)used.add(val);} }
        }
        if(x<fw) flags|=F_SHORT;
      }
    }
    if(flags&F_CLAMP) clamped++;
    frames.push({x:fx,y:fy,w:fw,h:fh,idx,flags});
  }
  const lbl='Classic GRP · '+(flat?'flat (non-RLE)':'RLE indexed')
    +(bad?` · ${bad} frames with a bad offset`:'')
    +(clamped?` · ${clamped} frames with clamped rows`:'');
  return {type:'classic',frameCount,maxW,maxH,frames,used,badFrames:bad,flat,fmtLabel:lbl};
}
// render a classic frame -> ImageData sized w*h using palette (Uint8Array768)
function classicToImageData(fr,pal){
  const out=new ImageData(fr.w,fr.h); const d=out.data;
  for(let i=0;i<fr.w*fr.h;i++){const v=fr.idx[i];
    if(v===0){d[i*4+3]=0;} else {d[i*4]=pal[v*3];d[i*4+1]=pal[v*3+1];d[i*4+2]=pal[v*3+2];d[i*4+3]=255;}}
  return out;
}

// ---------- SC:R DDS GRP (DXT1/3/5) ----------
// 12-byte header, then per frame {u16 w, u16 h, u32 ddsSize} + blob + u32
// trailer. Corrected 2026-07-21: there are NO per-frame x/y offsets — the old
// reading split the header 8/12 instead of 12/8, which lands on the same DDS
// offsets but invents x/y out of the trailer (measured zero in 627 frames).
function parseDdsGRP(buf){
  const dv=new DataView(buf), N=buf.byteLength;
  const frameCount=dv.getUint16(4,true);
  const frames=[]; let o=12, maxW=0,maxH=0;
  for(let i=0;i<frameCount;i++){
    if(o+8>N) break;
    const fw=dv.getUint16(o,true), fh=dv.getUint16(o+2,true);
    const size=dv.getUint32(o+4,true); o+=8;
    if(o+size>N) break;
    const ddsOff=o; o+=size; o+=4;              // blob + u32 trailer
    frames.push({x:0,y:0,w:fw,h:fh,ddsOff,size});
    maxW=Math.max(maxW,fw); maxH=Math.max(maxH,fh);
  }
  return {type:'dds',frameCount:frames.length,maxW,maxH,frames,fmtLabel:'SC:R DDS GRP · DXT1/DXT5'};
}
function color565(c){const r=(c>>11)&31,g=(c>>5)&63,bl=c&31;
  return [(r<<3)|(r>>2),(g<<2)|(g>>4),(bl<<3)|(bl>>2)];}
// decode one DDS block (DXT1/3/5) from buffer at off -> ImageData
function ddsToImageData(buf,off){
  const dv=new DataView(buf);
  const h=dv.getUint32(off+12,true), w=dv.getUint32(off+16,true);
  const fourcc=String.fromCharCode(dv.getUint8(off+84),dv.getUint8(off+85),dv.getUint8(off+86),dv.getUint8(off+87));
  const data=off+128;
  const out=new ImageData(w,h), px=out.data;
  const blocksX=Math.ceil(w/4), blocksY=Math.ceil(h/4);
  let dxt=5; if(fourcc==='DXT1')dxt=1; else if(fourcc==='DXT3')dxt=3;
  const blkSize=(dxt===1)?8:16;
  let p=data;
  for(let by=0;by<blocksY;by++)for(let bx=0;bx<blocksX;bx++){
    let alpha=null, cOff=p;
    if(dxt===5){
      const a0=dv.getUint8(p),a1=dv.getUint8(p+1); const at=new Array(8);
      at[0]=a0;at[1]=a1;
      if(a0>a1){for(let k=1;k<=6;k++)at[k+1]=Math.round(((7-k)*a0+k*a1)/7);}
      else{for(let k=1;k<=4;k++)at[k+1]=Math.round(((5-k)*a0+k*a1)/5);at[6]=0;at[7]=255;}
      // 48 bits of 3-bit indices
      let bits=0n; for(let k=0;k<6;k++)bits|=BigInt(dv.getUint8(p+2+k))<<BigInt(8*k);
      alpha=new Uint8Array(16); for(let k=0;k<16;k++){alpha[k]=at[Number((bits>>BigInt(3*k))&7n)];}
      cOff=p+8;
    } else if(dxt===3){
      alpha=new Uint8Array(16);
      for(let k=0;k<16;k++){const nib=(dv.getUint8(p+((k>>1)))>>((k&1)*4))&0xF; alpha[k]=nib*17;}
      cOff=p+8;
    }
    const c0=dv.getUint16(cOff,true), c1=dv.getUint16(cOff+2,true);
    const rgb0=color565(c0), rgb1=color565(c1); const pal=[rgb0,rgb1,[0,0,0],[0,0,0]];
    let a3=255;
    if(dxt===1 && c0<=c1){ // 1-bit alpha mode
      pal[2]=[(rgb0[0]+rgb1[0])>>1,(rgb0[1]+rgb1[1])>>1,(rgb0[2]+rgb1[2])>>1]; pal[3]=[0,0,0];
    } else {
      pal[2]=[Math.round((2*rgb0[0]+rgb1[0])/3),Math.round((2*rgb0[1]+rgb1[1])/3),Math.round((2*rgb0[2]+rgb1[2])/3)];
      pal[3]=[Math.round((rgb0[0]+2*rgb1[0])/3),Math.round((rgb0[1]+2*rgb1[1])/3),Math.round((rgb0[2]+2*rgb1[2])/3)];
    }
    const idxBits=dv.getUint32(cOff+4,true);
    for(let k=0;k<16;k++){
      const ci=(idxBits>>(2*k))&3; const col=pal[ci];
      const lx=bx*4+(k&3), ly=by*4+(k>>2); if(lx>=w||ly>=h)continue;
      const di=(ly*w+lx)*4; px[di]=col[0];px[di+1]=col[1];px[di+2]=col[2];
      let a=255;
      if(dxt===1 && c0<=c1 && ci===3)a=0;
      else if(alpha)a=alpha[k];
      px[di+3]=a;
    }
    p+=blkSize;
  }
  return out;
}

// ---------- SC:R .anim (HD, version 0x0204) ----------
// Format validated byte-exact against retail main_000.anim.
//   Header: "ANIM", u16 version, u16 unused, u16 layerCount, u16 entryCount
//   0x0C: layer-name table (10 slots x 32 bytes)
//   0x14C: entry table (entryCount x 12): u16 frameCount, u16 unused,
//          u16 refW, u16 refH, u32 frameTableOffset
//   then TexRef table (layerCount x 12): u32 ddsOffset, u32 ddsSize, u16 w, u16 h
//   then DDS blobs (DXT1/DXT5)
//   frame table (at frameTableOffset): frameCount x 16:
//     u16 atlasX, u16 atlasY, i16 xoff, i16 yoff, u16 w, u16 h, u32 flags
function findDdsBlocks(buf){
  const b=new Uint8Array(buf); const offs=[];
  for(let i=0;i+4<=b.length;i++) if(b[i]===0x44&&b[i+1]===0x44&&b[i+2]===0x53&&b[i+3]===0x20) offs.push(i);
  return offs;
}
function cropImageData(atlas,x,y,w,h){
  const out=new ImageData(w,h); const src=atlas.data, dst=out.data, aw=atlas.width;
  if(x<0||y<0||x+w>atlas.width||y+h>atlas.height) return out;
  for(let ry=0;ry<h;ry++){ const so=((y+ry)*aw+x)*4; dst.set(src.subarray(so,so+w*4),ry*w*4); }
  return out;
}
function sliceAnimFrames(file,layerIdx){
  if(layerIdx==='composite'){ animComposite(file,[244,4,4]); return; }
  const atlas=file.layerAtlas[layerIdx];
  file.frames=file.rects.map(r=>({x:r.xo,y:r.yo,w:r.w,h:r.h,_img:cropImageData(atlas,r.ax,r.ay,r.w,r.h)}));
  file.activeLayer=layerIdx;
}
/* HD layer composite — JS twin of tools/anim_composite.py: diffuse -> teamcolor
   src-over (player tint) -> additive emissive. Integer math matches the Python
   op-for-op (byte-identical primitives, verified on the same test vectors); the
   layer recipe is the documented reference until the engine's exact blend lands. */
function animComposite(file,playerRGB){
  const di=file.layers.indexOf('diffuse');
  if(di<0){ sliceAnimFrames(file,0); return; }
  const ti=file.layers.indexOf('teamcolor'), ei=file.layers.indexOf('emissive');
  const pr=playerRGB[0],pg=playerRGB[1],pb=playerRGB[2];
  file.frames=file.rects.map(r=>{
    const base=cropImageData(file.layerAtlas[di],r.ax,r.ay,r.w,r.h), d=base.data;
    if(ti>=0){ const tc=cropImageData(file.layerAtlas[ti],r.ax,r.ay,r.w,r.h).data;
      for(let i=0;i<d.length;i+=4){ const m=tc[i]; if(!m)continue;      // grayscale mask weight
        // tint = playerColour * (m/255), alpha = m  (player_colors.apply_team_color)
        const tr=Math.floor(pr*m/255+0.5),tg=Math.floor(pg*m/255+0.5),tb=Math.floor(pb*m/255+0.5),at=m;
        if(at===255){ d[i]=tr;d[i+1]=tg;d[i+2]=tb;d[i+3]=255; continue; }
        const ab=d[i+3], inv=255-at, floorInv=Math.floor(ab*inv/255), oa=at+floorInv;
        if(oa===0){ d[i]=d[i+1]=d[i+2]=d[i+3]=0; continue; }
        d[i]  =Math.floor((tr*at+Math.floor(d[i]  *ab*inv/255))/oa+0.5);
        d[i+1]=Math.floor((tg*at+Math.floor(d[i+1]*ab*inv/255))/oa+0.5);
        d[i+2]=Math.floor((tb*at+Math.floor(d[i+2]*ab*inv/255))/oa+0.5);
        d[i+3]=oa;
      } }
    if(ei>=0){ const em=cropImageData(file.layerAtlas[ei],r.ax,r.ay,r.w,r.h).data;
      for(let i=0;i<d.length;i+=4){ const aa=em[i+3]; if(!aa)continue;   // additive self-glow, clamped
        d[i]  =Math.min(255,d[i]  +Math.floor(em[i]  *aa/255));
        d[i+1]=Math.min(255,d[i+1]+Math.floor(em[i+1]*aa/255));
        d[i+2]=Math.min(255,d[i+2]+Math.floor(em[i+2]*aa/255));
      } }
    return {x:r.xo,y:r.yo,w:r.w,h:r.h,_img:base};
  });
  file.activeLayer='composite';
}
function parseAnim(buf){
  const dv=new DataView(buf), b=new Uint8Array(buf);
  const version=dv.getUint16(4,true), layerCount=dv.getUint16(8,true), entryCount=dv.getUint16(10,true);
  const label0='SC:R ANIM v'+(version>>8)+'.'+(version&0xFF);
  const NAME=0x0C, slots=10, entryOff=NAME+slots*32, texRefOff=entryOff+entryCount*12;
  const ok=layerCount>0&&layerCount<=slots&&entryCount>0&&texRefOff+layerCount*12<=b.length;
  if(!ok){
    const offs=findDdsBlocks(buf);
    const frames=offs.map(o=>{const im=ddsToImageData(buf,o);return{x:0,y:0,w:im.width,h:im.height,_img:im};});
    let mw=0,mh=0;frames.forEach(f=>{mw=Math.max(mw,f.w);mh=Math.max(mh,f.h);});
    return {type:'anim',frameCount:frames.length,maxW:mw,maxH:mh,frames,rects:[],layers:[],layerAtlas:[],
      fmtLabel:label0+' · atlas preview (unexpected layout)'};
  }
  const names=[];
  for(let i=0;i<layerCount;i++){let o=NAME+i*32,s='';for(let k=0;k<32&&b[o+k];k++)s+=String.fromCharCode(b[o+k]);names.push(s);}
  const layers=[],layerAtlas=[];
  for(let i=0;i<layerCount;i++){
    const o=texRefOff+i*12, ddsOff=dv.getUint32(o,true), ddsSize=dv.getUint32(o+4,true);
    if(!ddsOff||!ddsSize||ddsOff+4>b.length)continue;
    layers.push(names[i]); layerAtlas.push(ddsToImageData(buf,ddsOff));
  }
  if(!layerAtlas.length) return {type:'anim',frameCount:0,maxW:0,maxH:0,frames:[],rects:[],layers:[],layerAtlas:[],
    fmtLabel:label0+' · no decodable layers'};
  const diffuse=layerAtlas[0], aw=diffuse.width, ah=diffuse.height;
  const rects=[];
  for(let e=0;e<entryCount;e++){
    const eo=entryOff+e*12, frameCount=dv.getUint16(eo,true), ft=dv.getUint32(eo+8,true);
    if(ft+frameCount*16>b.length)continue;
    for(let i=0;i<frameCount;i++){
      const o=ft+i*16;
      const ax=dv.getUint16(o,true),ay=dv.getUint16(o+2,true);
      const xo=dv.getInt16(o+4,true),yo=dv.getInt16(o+6,true);
      const w=dv.getUint16(o+8,true),h=dv.getUint16(o+10,true);
      if(w<=0||h<=0||ax+w>aw||ay+h>ah)continue;
      rects.push({ax,ay,w,h,xo,yo});
    }
  }
  const file={type:'anim',rects,layers,layerAtlas,activeLayer:0};
  sliceAnimFrames(file,0);
  let mw=0,mh=0;file.frames.forEach(f=>{mw=Math.max(mw,f.x+f.w);mh=Math.max(mh,f.y+f.h);});
  file.frameCount=file.frames.length; file.maxW=mw||aw; file.maxH=mh||ah;
  file.fmtLabel=label0+' · '+layers.length+' layers ['+layers.join(',')+'] · '+file.frameCount+' frames · atlas '+aw+'x'+ah;
  return file;
}


/* ========================= PCX ========================= */
// 8-bit paletted (SC standard) with embedded VGA palette -> true colour.
// Also handles 24-bit (3-plane) PCX. Returns a sprite-like object.
function parsePCX(buf){
  const d=new Uint8Array(buf), dv=new DataView(buf);
  if(d[0]!==0x0A) throw new Error('not a PCX (bad signature)');
  const enc=d[2], bpp=d[3];
  const xmin=dv.getUint16(4,true),ymin=dv.getUint16(6,true),xmax=dv.getUint16(8,true),ymax=dv.getUint16(10,true);
  const nplanes=d[65], bpl=dv.getUint16(66,true);
  const w=xmax-xmin+1, h=ymax-ymin+1;
  const totalPerLine=bpl*nplanes;
  // RLE decode all scanlines
  const raw=new Uint8Array(totalPerLine*h);
  let p=128, oi=0;
  while(oi<raw.length && p<d.length){
    let b=d[p++];
    if((b&0xC0)===0xC0){ const cnt=b&0x3F, val=d[p++]; for(let k=0;k<cnt&&oi<raw.length;k++)raw[oi++]=val; }
    else raw[oi++]=b;
  }
  const img=new ImageData(w,h), px=img.data;
  if(bpp===8 && nplanes===1){
    // palette: last 769 bytes, marker 0x0C
    let pal=null;
    if(d.length>769 && d[d.length-769]===0x0C) pal=d.subarray(d.length-768);
    for(let y=0;y<h;y++)for(let x=0;x<w;x++){
      const idx=raw[y*bpl+x], di=(y*w+x)*4;
      if(pal){ px[di]=pal[idx*3];px[di+1]=pal[idx*3+1];px[di+2]=pal[idx*3+2]; }
      else { px[di]=px[di+1]=px[di+2]=idx; }
      px[di+3]=255;
    }
  } else if(nplanes>=3){ // 24-bit: planes R,G,B per line
    for(let y=0;y<h;y++)for(let x=0;x<w;x++){
      const di=(y*w+x)*4, base=y*totalPerLine;
      px[di]=raw[base+x]; px[di+1]=raw[base+bpl+x]; px[di+2]=raw[base+2*bpl+x]; px[di+3]=255;
    }
  } else { throw new Error('unsupported PCX bpp='+bpp+' planes='+nplanes); }
  return {type:'pcx',frameCount:1,maxW:w,maxH:h,frames:[{x:0,y:0,w,h,_img:img}],fmtLabel:'PCX '+bpp+'-bit · '+w+'×'+h};
}

/* ========================= SMK (full decoder) =========================
   Smacker SMK2/SMK4. Written from the format description and validated on all
   519 portrait clips in the retail archives (5369 frames, zero failures).
   Two things cost the most to find, both recorded here so nobody re-derives them:
     1. a 16-bit code book has its OWN leading "present" bit before the two
        8-bit sub-books — miss it and the tree collapses after a few entries;
     2. the 3-slot MRU cache is per FRAME. Carrying it across frames decodes
        fine for a while and then silently diverges.                        */
const SMK_NODE=0x80000000;
const SMK_RUNS=(()=>{const r=[];for(let i=1;i<60;i++)r.push(i);return r.concat([128,256,512,1024,2048]);})();
const SMK_PAL6=new Uint8Array([
  0x00,0x04,0x08,0x0C,0x10,0x14,0x18,0x1C,0x20,0x24,0x28,0x2C,0x30,0x34,0x38,0x3C,
  0x41,0x45,0x49,0x4D,0x51,0x55,0x59,0x5D,0x61,0x65,0x69,0x6D,0x71,0x75,0x79,0x7D,
  0x82,0x86,0x8A,0x8E,0x92,0x96,0x9A,0x9E,0xA2,0xA6,0xAA,0xAE,0xB2,0xB6,0xBA,0xBE,
  0xC3,0xC7,0xCB,0xCF,0xD3,0xD7,0xDB,0xDF,0xE3,0xE7,0xEB,0xEF,0xF3,0xF7,0xFB,0xFF]);

function SmkBits(d,start){this.d=d;this.pos=start*8;}
SmkBits.prototype.bit=function(){const p=this.pos++;return (this.d[p>>3]>>(p&7))&1;};
SmkBits.prototype.bits=function(n){let v=0;for(let i=0;i<n;i++)v|=this.bit()<<i;return v;};

function smkTree8(b){
  if(b.bit()){const a=smkTree8(b),c=smkTree8(b);return [a,c];}
  return b.bits(8);
}
function smkWalk8(b,t){while(Array.isArray(t))t=t[b.bit()];return t;}

function SmkBigTree(b){
  this.vals=[0]; this.last=[0,0,0];
  if(!b.bit()) return;                       // (1) the book's own present bit
  let lo=null,hi=null;
  if(b.bit()){lo=smkTree8(b);b.bit();}
  if(b.bit()){hi=smkTree8(b);b.bit();}
  const esc=[0,0,0];
  for(let i=0;i<3;i++) esc[i]=b.bits(8)|(b.bits(8)<<8);
  const vals=[], last=[-1,-1,-1];
  const build=()=>{
    if(!b.bit()){
      const a=lo!==null?smkWalk8(b,lo):0, c=hi!==null?smkWalk8(b,hi):0;
      let v=a|(c<<8);
      for(let k=0;k<3;k++) if(v===esc[k]){last[k]=vals.length;v=0;break;}
      vals.push(v); return 1;
    }
    const t=vals.length; vals.push(0);
    const r=build(); vals[t]=SMK_NODE|r;
    return r+1+build();
  };
  build(); b.bit();
  for(let k=0;k<3;k++) if(last[k]===-1){last[k]=vals.length;vals.push(0);}
  this.vals=vals; this.last=last;
}
SmkBigTree.prototype.reset=function(){for(const k of this.last)this.vals[k]=0;};
SmkBigTree.prototype.get=function(b){
  const v=this.vals; let i=0;
  while(v[i]&SMK_NODE){ if(b.bit()) i+=v[i]&~SMK_NODE; i++; }
  const r=v[i], L=this.last;
  if(r!==v[L[0]]){ v[L[2]]=v[L[1]]; v[L[1]]=v[L[0]]; v[L[0]]=r; }
  return r;
};

function parseSMK(buf){
  const d=new Uint8Array(buf), dv=new DataView(buf);
  const sig=String.fromCharCode(d[0],d[1],d[2],d[3]);
  if(sig!=='SMK2'&&sig!=='SMK4') throw new Error('not a Smacker file');
  const version=sig==='SMK4'?4:2;
  const w=dv.getUint32(4,true), h=dv.getUint32(8,true), nf=dv.getUint32(12,true);
  const rate=dv.getInt32(16,true);
  const fps = rate>0 ? 1000/rate : (rate<0 ? 100000/(-rate) : 10);
  const treesSize=dv.getUint32(52,true);
  const rawSizes=[], ftypes=[];
  for(let i=0;i<nf;i++) rawSizes.push(dv.getUint32(104+i*4,true));
  const ftOff=104+nf*4;
  for(let i=0;i<nf;i++) ftypes.push(d[ftOff+i]);
  const treeOff=ftOff+nf;
  const bits=new SmkBits(d,treeOff);
  const tMmap=new SmkBigTree(bits), tMclr=new SmkBigTree(bits),
        tFull=new SmkBigTree(bits), tType=new SmkBigTree(bits);
  const offs=[treeOff+treesSize];
  for(const s of rawSizes) offs.push(offs[offs.length-1]+(s&0xFFFFFFFC));

  const pal=new Uint8Array(768), px=new Uint8Array(w*h);
  const bw=(w+3)>>2, bh=(h+3)>>2, blocks=bw*bh;
  const frames=[];
  for(let fi=0;fi<nf;fi++){
    for(const t of [tMmap,tMclr,tFull,tType]) t.reset();   // (2) per-frame MRU
    let p=offs[fi]; const ftype=ftypes[fi];
    if(ftype&1){                                            // palette chunk
      const end=p+d[p]*4; let q=p+1; const old=pal.slice(); let o=0;
      while(o<768&&q<end){
        const t=d[q++];
        if(t&0x80){ const c=((t&0x7F)+1)*3; pal.set(old.subarray(o,o+c),o); o+=c; }
        else if(t&0x40){ let c=(t&0x3F)+1, s=d[q++]*3;
          while(c-->0&&o<768){ pal[o]=old[s];pal[o+1]=old[s+1];pal[o+2]=old[s+2]; o+=3; s+=3; } }
        else { pal[o++]=SMK_PAL6[t&0x3F]; pal[o++]=SMK_PAL6[d[q++]&0x3F]; pal[o++]=SMK_PAL6[d[q++]&0x3F]; }
      }
      p=end;
    }
    for(let t=0;t<7;t++) if(ftype&(2<<t)) p+=dv.getUint32(p,true);
    const b=new SmkBits(d,p);
    let blk=0;
    while(blk<blocks){
      const typ=tType.get(b); let run=SMK_RUNS[(typ>>2)&0x3F]; const mode=typ&3;
      if(mode===0){
        while(run-->0&&blk<blocks){
          const clr=tMclr.get(b); let mp=tMmap.get(b);
          const hiC=clr>>8, loC=clr&0xFF, ox=(blk%bw)*4, oy=((blk/bw)|0)*4;
          for(let y=0;y<4;y++){ const row=(oy+y)*w+ox;
            for(let x=0;x<4;x++){ px[row+x]=(mp&1)?hiC:loC; mp>>=1; } }
          blk++;
        }
      } else if(mode===1){
        let sub=0;
        if(version===4){ if(b.bit()) sub=1; else if(b.bit()) sub=2; }
        while(run-->0&&blk<blocks){
          const ox=(blk%bw)*4, oy=((blk/bw)|0)*4;
          if(sub===0){
            for(let y=0;y<4;y++){ const row=(oy+y)*w+ox;
              let v=tFull.get(b); px[row+2]=v&0xFF; px[row+3]=v>>8;
              v=tFull.get(b);     px[row]  =v&0xFF; px[row+1]=v>>8; }
          } else if(sub===1){
            for(let y=0;y<4;y+=2){ const row=(oy+y)*w+ox;
              let v=tFull.get(b); px[row+2]=v&0xFF; px[row+3]=v>>8;
              v=tFull.get(b);     px[row]  =v&0xFF; px[row+1]=v>>8;
              px.copyWithin(row+w,row,row+4); }
          } else {
            for(let y=0;y<4;y++){ const row=(oy+y)*w+ox; const v=tFull.get(b);
              px[row]=px[row+1]=v&0xFF; px[row+2]=px[row+3]=v>>8; }
          }
          blk++;
        }
      } else if(mode===2){ while(run-->0&&blk<blocks) blk++; }
      else {
        const col=(typ>>8)&0xFF;
        while(run-->0&&blk<blocks){
          const ox=(blk%bw)*4, oy=((blk/bw)|0)*4;
          for(let y=0;y<4;y++) px.fill(col,(oy+y)*w+ox,(oy+y)*w+ox+4);
          blk++;
        }
      }
    }
    const img=new ImageData(w,h);
    for(let i=0,n=w*h;i<n;i++){ const s=px[i]*3, o=i*4;
      img.data[o]=pal[s]; img.data[o+1]=pal[s+1]; img.data[o+2]=pal[s+2]; img.data[o+3]=255; }
    frames.push({x:0,y:0,w,h,_img:img});
  }
  return {type:'smk',frameCount:frames.length,maxW:w,maxH:h,frames,
    fmtLabel:'Smacker '+sig+' · '+w+'×'+h+' · '+nf+' frames · '+(Math.round(fps*10)/10)+' fps',
    smkFps:fps};
}

/* ========================= WebM / Matroska (container only) =========================
   Structure and metadata only. VP8/VP9 frame decoding is left to the browser —
   a hand-written VP9 decoder would be thousands of unverifiable lines, and
   <video> already does it correctly. */
function parseWebM(buf){
  const d=new Uint8Array(buf), dv=new DataView(buf);
  if(!(d[0]===0x1a&&d[1]===0x45&&d[2]===0xdf&&d[3]===0xa3)) throw new Error('not EBML/Matroska');
  // 0xA0 = BlockGroup; without it, files using Block (0xA1) inside a BlockGroup
  // rather than a bare SimpleBlock parse to zero frames.
  const MASTER=new Set([0x1A45DFA3,0x18538067,0x1549A966,0x1654AE6B,0xAE,0xE0,0x1F43B675,0xA0]);
  function vint(p,keep){
    const b=d[p]; if(!b) throw new Error('bad EBML vint');
    let n=1,mask=0x80;
    while(!(b&mask)){mask>>=1;n++;}
    let v=keep?b:(b&(mask-1));
    for(let i=1;i<n;i++) v=v*256+d[p+i];
    if(!keep && v===Math.pow(2,7*n)-1) v=null;
    return [v,p+n];
  }
  const info={scale:1000000,duration:null,tracks:[],blocks:0,muxer:null};
  let track=null;
  (function walk(p,end){
    while(p<end){
      let eid,size,q,r;
      try{ [eid,q]=vint(p,true); [size,r]=vint(q,false); }catch(e){ return; }
      if(size===null){ walk(r,end); return; }
      const be=Math.min(r+size,end);
      if(MASTER.has(eid)){
        if(eid===0xAE){ track={}; walk(r,be); info.tracks.push(track); track=null; }
        else walk(r,be);
      } else {
        const uint=()=>{let v=0;for(let i=0;i<size;i++)v=v*256+d[r+i];return v;};
        if(eid===0x2AD7B1) info.scale=uint();
        else if(eid===0x4489) info.duration = size===4?dv.getFloat32(r):(size===8?dv.getFloat64(r):null);
        else if(eid===0x4D80 && !info.muxer) info.muxer=new TextDecoder().decode(d.subarray(r,r+size));
        else if(track){
          if(eid===0x83) track.type=uint();
          else if(eid===0x86) track.codec=new TextDecoder().decode(d.subarray(r,r+size));
          else if(eid===0xB0) track.w=uint();
          else if(eid===0xBA) track.h=uint();
          else if(eid===0x23E383) track.dur=uint();
        }
        else if(eid===0xA3||eid===0xA1) info.blocks++;
      }
      p=be;
    }
  })(0,d.length);
  const v=info.tracks.find(t=>t.type===1)||{};
  const secs=info.duration!==null?info.duration*info.scale/1e9:null;
  return {type:'webm',video:true,buf,
    codec:v.codec||'?',width:v.w||0,height:v.h||0,
    frames:info.blocks,duration:secs,muxer:info.muxer,
    fps: (secs&&info.blocks)? info.blocks/secs : null,
    fmtLabel:'WebM '+(v.codec||'?')+' · '+(v.w||'?')+'×'+(v.h||'?')};
}

/* ========================= MPQ WAVE (Huffman + ADPCM) =========================
   How the 1998 archives store every voice line: sector 0 is PKWARE, the rest
   are 0x41 (mono) or 0x81 (stereo) — StormLib adaptive Huffman over IMA ADPCM.

   PROVENANCE: the nine 258-byte weight tables below (and the ADPCM step tables)
   are FORMAT DATA — they cannot be derived, and without them the initial tree
   cannot be built. They come from StormLib
   (https://github.com/ladislav-zezula/StormLib, MIT, (c) 1999-2013 Ladislav
   Zezula). The code is a port of tools/mpq_wave.py, written from the algorithm's
   structure. This is the one borrowed piece in this toolkit; it is nonetheless
   verified against a source that shares nothing with StormLib — SC:R keeps the
   same audio uncompressed under sd/sound/, and 300/300 files matched byte for
   byte. */
const SMPQ_WT_B64=
  'CgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAVBYWDQwIBgUGBQYDBAQDBQ4LFBMTCQsGBQQD'+
  'AgMCAgINBwkGBgQDAgQDAwMDAwICCQYEBAQEAwIDAgICAgMCBAgDBAcJBQMDAwMCAgIDAgIDAgIC'+
  'AgICAgIBAQECAQICBgoICAYHBAMEBAICBAIDAwQDBwcJBgQDAwIBAgICAgIKAgIDAgIBAQICAgYD'+
  'BQIDAgEBAQEBAQEBAQECAwEBAQIBAQEBAQECBAQEBwkIDAIBAQEBAQEBAQEBAQECAQEDBAECBAUB'+
  'AQEBAQEBAgEBAQQBAQEBAQIBAQEBAQEBAQECAQEBAQEBAQMBAQEBAQEBAgEBAQEBAQICAQECAgIG'+
  'SwAAAAAAAAAAAAAAAycAACMAAAAAAAAAAAAAAAAAAAAAAAD/AQEBAQEBAQICAQEGDhAEBggFBAQD'+
  'AwICAwMBAQIBAQEEAgQCAgIBAQQBAQIDAwIDAQMGBAEBAQEBAQIBAgEBASkHFhJACgoRJQEDFxAm'+
  'KhABIyMvEAYHAgkBAQEBAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/wsHBQsCAgIGAgIBBAIBAwkBAQEDBAEB'+
  'AgEBAQIBAQEFAQEBDQEBAQEBAQEBAQEBAgEBAwEBAQEBAQECAQEBAQoEAgEGAwIBAQEBAQMBAQEF'+
  'AgMEAwMDAgEBAQIBAgMDAQMBAQIFAQEEAwUBAwEDAwIBBAMKBgEBAQEBAQEBAQECAgEKAgUBAQIH'+
  'AhcBBQEBDgEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBBgIB'+
  'BAUBAQIBAQEBAgEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQcBAQIBAQEBAgEBAQEBAQECAQEB'+
  'AQEBEQAA//uYmoSFY2Q+PiIiExMYFwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//GdnpqbmpeTk4yOhoiAgnx8cnNp'+
  'a19gVVZKS0BBNzcvLycnISEbHBcXExMQEA0NCwsJCQgIBwcGBQUEBAQZGAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAw8v1Qf979yEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAL/M8kD9fPciAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB6RgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAw9nvPfl86R79q/Es/Fv+FwAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAL3Z7D31fegd+67w'+
  'LPtc/xgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABwbAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAusXaM+Nt2BjllNoj30rREO6v5CzqWt4V9IfpIfZD/BIAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAALDH2DPja9YY55XYI9tJ0BHpsuIr6FzdFfGH5yD3RP8TAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABfngAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'+
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const SMPQ_WT=(()=>{ const s=atob(SMPQ_WT_B64), a=new Uint8Array(s.length);
  for(let i=0;i<s.length;i++) a[i]=s.charCodeAt(i);
  const out=[]; for(let t=0;t<9;t++) out.push(a.subarray(t*258,(t+1)*258)); return out; })();

const SMPQ_STEP=new Int32Array([7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,
  50,55,60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,
  494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,2749,
  3024,3327,3660,4026,4428,4871,5358,5894,6484,7132,7845,8630,9493,10442,11487,12635,13899,
  15289,16818,18500,20350,22385,24623,27086,29794,32767]);
const SMPQ_NEXT=new Int32Array([-1,0,-1,4,-1,2,-1,6,-1,1,-1,5,-1,3,-1,7,
  -1,1,-1,5,-1,3,-1,7,-1,2,-1,4,-1,6,-1,8]);

function SmpqBits(d){this.d=d;this.p=0;this.buf=0;this.cnt=0;}
SmpqBits.prototype.bit=function(){
  if(this.cnt===0){ if(this.p>=this.d.length) return null;
    this.buf=this.d[this.p++]; this.cnt=8; }
  const v=this.buf&1; this.buf>>=1; this.cnt--; return v;
};
SmpqBits.prototype.byte=function(){
  if(this.cnt<8){ if(this.p>=this.d.length) return null;
    this.buf|=this.d[this.p++]<<this.cnt; this.cnt+=8; }
  const v=this.buf&0xFF; this.buf>>=8; this.cnt-=8; return v;
};

// Weight-ordered circular list (descending from the head) with tree links on
// top. A node's children are adjacent: child_lo, and child_lo.prev as sibling.
function SmpqTree(dataType){
  this.head={prev:null,next:null,parent:null,lo:null,w:0,v:0};
  this.head.prev=this.head.next=this.head;
  this.byVal={};
  this._build(dataType&0x0F);
}
SmpqTree.prototype._unlink=function(n){ if(n.prev){n.prev.next=n.next;n.next.prev=n.prev;} n.prev=n.next=null; };
SmpqTree.prototype._after=function(a,b){ b.next=a.next; b.prev=a; a.next.prev=b; a.next=b; };
SmpqTree.prototype._findGE=function(n,w){
  while(n&&n!==this.head){ if(n.w>=w) return n; n=n.prev; } return this.head; };
SmpqTree.prototype._new=function(v,w,before){
  const n={prev:null,next:null,parent:null,lo:null,w:w,v:v};
  this._after(before?this.head.prev:this.head,n); return n; };
SmpqTree.prototype._fixup=function(n,mw){
  if(n.w<mw){ const h=this._findGE(this.head.prev,n.w); this._unlink(n); this._after(h,n); return mw; }
  return n.w; };
SmpqTree.prototype._build=function(dt){
  const t=SMPQ_WT[dt]; let mw=0;
  for(let i=0;i<256;i++) if(t[i]){ const n=this._new(i,t[i],false); this.byVal[i]=n; mw=this._fixup(n,mw); }
  this.byVal[0x100]=this._new(0x100,1,true);
  this.byVal[0x101]=this._new(0x101,1,true);
  let lo=this.head.prev;
  while(lo!==this.head){
    const hi=lo.prev; if(hi===this.head) break;
    const p=this._new(0,hi.w+lo.w,false);
    lo.parent=p; hi.parent=p; p.lo=lo;
    mw=this._fixup(p,mw);
    lo=hi.prev;
  }
};
SmpqTree.prototype.inc=function(n){
  while(n){
    n.w++;
    const higher=this._findGE(n.prev,n.w), sib=higher.next;
    if(sib!==n){
      this._unlink(sib); this._after(n,sib);
      this._unlink(n);   this._after(higher,n);
      const sibParentLo=sib.parent?sib.parent.lo:null;
      const parent=n.parent;
      if(parent&&parent.lo===n) parent.lo=sib;
      if(sibParentLo===sib&&sib.parent) sib.parent.lo=n;
      const tmp=n.parent; n.parent=sib.parent; sib.parent=tmp;
    }
    n=n.parent;
  }
};
SmpqTree.prototype.insertBranch=function(v1,v2){
  const last=this.head.prev;
  const hi=this._new(v1,last.w,true); hi.parent=last; this.byVal[v1]=hi;
  const lo=this._new(v2,0,true); lo.parent=last; last.lo=lo; this.byVal[v2]=lo;
  this.inc(lo);
};
SmpqTree.prototype.decode=function(b){
  let n=this.head.next; if(n===this.head) return null;
  while(n.lo){ const bit=b.bit(); if(bit===null) return null; n=bit?n.lo.prev:n.lo; }
  return n.v;
};

function smpqHuff(data,outSize){
  const bits=new SmpqBits(data);
  const dt=bits.byte(); if(dt===null) return new Uint8Array(0);
  const sparse=(dt===0);
  const tree=new SmpqTree(dt);
  const out=new Uint8Array(outSize); let n=0;
  while(n<outSize){
    let v=tree.decode(bits);
    if(v===null||v===0x100) break;
    if(v===0x101){
      v=bits.byte(); if(v===null) break;
      tree.insertBranch(tree.head.prev.v,v);
      if(!sparse) tree.inc(tree.byVal[v]);
    }
    out[n++]=v&0xFF;
    if(sparse) tree.inc(tree.byVal[v]);
  }
  return out.subarray(0,n);
}

function smpqAdpcm(data,channels){
  if(data.length<2) return new Uint8Array(0);
  let p=1; const shift=data[p++];
  const pred=[0,0], si=[0x2C,0x2C];
  const out=[];
  const push=v=>{ out.push(v&0xFF,(v>>8)&0xFF); };
  for(let c=0;c<channels;c++){
    if(p+2>data.length) break;
    const s=(data[p]|(data[p+1]<<8))<<16>>16; p+=2;
    pred[c]=s; push(s);
  }
  let ch=channels-1;
  while(p<data.length){
    const e=data[p++];
    ch=(ch+1)%channels;
    if(e===0x80){ if(si[ch]) si[ch]--; push(pred[ch]); }
    else if(e===0x81){ si[ch]+=8; if(si[ch]>0x58) si[ch]=0x58; ch=(ch+1)%channels; }
    else {
      const step=SMPQ_STEP[si[ch]];
      let diff=step>>shift;
      for(let b=0;b<6;b++) if(e&(1<<b)) diff+=step>>b;
      let v=pred[ch];
      if(e&0x40){ v-=diff; if(v<=-32768) v=-32768; }
      else      { v+=diff; if(v>= 32767) v= 32767; }
      pred[ch]=v; push(v);
      let x=si[ch]+SMPQ_NEXT[e&0x1F];
      si[ch]= x<0?0:(x>88?88:x);
    }
  }
  return Uint8Array.from(out);
}

function smpqWave(data,outSize,mask){
  let d=data;
  if(mask&0x01) d=smpqHuff(d,outSize);
  if(mask&0x80) d=smpqAdpcm(d,2);
  else if(mask&0x40) d=smpqAdpcm(d,1);
  return d.subarray?d.subarray(0,outSize):d.slice(0,outSize);
}

/* ========================= audio =========================
   SC:R stores sound as plain PCM RIFF (and Ogg Vorbis for campaign speech), so
   the browser plays it directly. Measured: sd/sound/ is byte-for-byte the same
   audio the 1998 MPQ keeps ADPCM+Huffman compressed — 1123/1127 sizes match
   exactly — so nothing has to be decompressed to hear the original. */
function parseAudio(buf,name){
  const d=new Uint8Array(buf), dv=new DataView(buf);
  const isOgg=d[0]===0x4F&&d[1]===0x67&&d[2]===0x67&&d[3]===0x53;
  if(isOgg) return {type:'audio',audio:true,buf,mime:'audio/ogg',codec:'Ogg Vorbis',
    bytes:buf.byteLength,fmtLabel:'Ogg Vorbis · '+(buf.byteLength/1024|0)+' KB'};
  if(!(d[0]===0x52&&d[1]===0x49&&d[2]===0x46&&d[3]===0x46)) throw new Error('not RIFF/Ogg audio');
  let p=12,info={};
  while(p+8<=d.length){
    const cid=String.fromCharCode(d[p],d[p+1],d[p+2],d[p+3]);
    const sz=dv.getUint32(p+4,true); p+=8;
    if(cid==='fmt '){ info.tag=dv.getUint16(p,true); info.ch=dv.getUint16(p+2,true);
      info.rate=dv.getUint32(p+4,true); info.bits=dv.getUint16(p+14,true); }
    else if(cid==='data') info.data=sz;
    p+=sz+(sz&1);
  }
  const tag={1:'PCM',2:'ADPCM',85:'MP3'}[info.tag]||('tag '+info.tag);
  const dur=info.data&&info.rate?info.data/(info.rate*info.ch*(info.bits/8)):0;
  return {type:'audio',audio:true,buf,mime:'audio/wav',codec:tag,
    rate:info.rate,ch:info.ch,bits:info.bits,bytes:buf.byteLength,dur,
    fmtLabel:'WAV '+tag+' · '+(info.rate/1000)+' kHz · '+info.bits+'-bit · '+info.ch+'ch'};
}

/* ========================= MPQ reader (validated vs retail BrooDat.mpq) ========================= */
// Container reader: header, encrypted hash/block tables, file decryption
// (ENCRYPTED / FIX_KEY), sector decompression (zlib via native
// DecompressionStream, PKWARE explode, or stored), (listfile) enumeration.
// Crypt table, hashes, decrypt key-schedule and PKWARE explode all verified
// byte-exact against retail Brood War data (BrooDat.mpq).
const MPQ=(function(){
  const T=new Uint32Array(0x500);
  (function(){let seed=0x00100001>>>0;
    for(let i=0;i<0x100;i++){let idx=i;
      for(let k=0;k<5;k++){seed=(seed*125+3)%0x2AAAAB;const a=(seed&0xFFFF)<<0x10;
        seed=(seed*125+3)%0x2AAAAB;const b=(seed&0xFFFF);T[idx]=(a|b)>>>0;idx+=0x100;}}})();
  const OFF={hash:0,nameA:0x100,nameB:0x200,key:0x300};
  function hashStr(s,w){let s1=0x7FED7FED>>>0,s2=0xEEEEEEEE>>>0,off=OFF[w];s=s.toUpperCase();
    for(let i=0;i<s.length;i++){let c=s.charCodeAt(i);if(c===47)c=92;
      s1=(T[off+c]^((s1+s2)>>>0))>>>0;s2=(c+s1+s2+((s2<<5)>>>0)+3)>>>0;}return s1>>>0;}
  function decrypt(arr,key){let k=key>>>0,s2=0xEEEEEEEE>>>0;
    for(let i=0;i<arr.length;i++){s2=(s2+T[0x400+(k&0xFF)])>>>0;
      const v=(arr[i]^((k+s2)>>>0))>>>0;arr[i]=v;
      let t=((((~k)>>>0)<<0x15)>>>0);t=(t+0x11111111)>>>0;k=(t|(k>>>0x0B))>>>0;
      s2=(v+s2+((s2<<5)>>>0)+3)>>>0;}}
  async function inflateRaw(bytes){const ds=new DecompressionStream('deflate');
    const w=ds.writable.getWriter();w.write(bytes);w.close();
    return new Uint8Array(await new Response(ds.readable).arrayBuffer());}
  // ---- PKWARE DCL explode (blast) — bit-inverted canonical Huffman ----
  const MAXBITS=13;
  function build(rep){const lengths=[];for(const e of rep){const num=(e>>4)+1,ln=e&0xF;for(let j=0;j<num;j++)lengths.push(ln);}
    const count=new Array(MAXBITS+1).fill(0);for(const L of lengths)count[L]++;
    const offs=new Array(MAXBITS+2).fill(0);for(let L=1;L<=MAXBITS;L++)offs[L+1]=offs[L]+count[L];
    const symbol=new Array(lengths.length).fill(0);for(let i=0;i<lengths.length;i++){const L=lengths[i];if(L)symbol[offs[L]++]=i;}
    return {count,symbol};}
  const litlen=[11,124,8,7,28,7,188,13,76,4,10,8,12,10,12,10,8,23,8,9,7,6,7,8,7,6,55,8,23,24,12,11,7,9,11,12,6,7,22,5,7,24,6,11,9,6,7,22,7,11,38,7,9,8,25,11,8,11,9,12,8,12,5,38,5,38,5,11,7,5,6,21,6,10,53,8,7,24,10,27,44,253,253,253,252,252,252,13,12,45,12,45,12,61,12,45,44,173];
  const lenlen=[2,35,36,53,38,23],distlen=[2,20,53,230,247,151,248];
  const cbase=[3,2,4,5,6,7,8,9,10,12,16,24,40,72,136,264],cextra=[0,0,0,0,0,0,0,0,1,2,3,4,5,6,7,8];
  const litC=build(litlen),lenC=build(lenlen),distC=build(distlen);
  function explode(data){let ip=0,bitbuf=0,bitcnt=0;
    function bits(need){let val=bitbuf;while(bitcnt<need){val|=data[ip++]<<bitcnt;bitcnt+=8;}bitbuf=val>>>need;bitcnt-=need;return val&((1<<need)-1);}
    function decode(h){let code=0,first=0,index=0,len=1;
      for(;;){code|=(bits(1)^1);const c=h.count[len];
        if(code<first+c)return h.symbol[index+(code-first)];
        index+=c;first+=c;first<<=1;code<<=1;len++;if(len>MAXBITS)return -9;}}
    const litcode=data[ip++],dictbits=data[ip++];const out=[];
    for(;;){ if(bits(1)){const sym=decode(lenC);const length=cbase[sym]+bits(cextra[sym]);
        if(length===519)break;const sb=length===2?2:dictbits;const dist=(decode(distC)<<sb)+bits(sb)+1;const frm=out.length-dist;
        for(let i=0;i<length;i++)out.push(out[frm+i]); }
      else out.push(litcode?decode(litC):bits(8));
      if(ip>=data.length&&bitcnt<1)break; }
    return Uint8Array.from(out);}
  const FLAG={IMPLODE:0x100,COMPRESS:0x200,ENCRYPTED:0x10000,FIX_KEY:0x20000,SINGLE:0x1000000,EXISTS:0x80000000};
  async function open(buf){
    const d=new Uint8Array(buf),dv=new DataView(buf);
    let base=-1;for(let o=0;o+4<=d.length;o+=512){if(d[o]===0x4D&&d[o+1]===0x50&&d[o+2]===0x51&&d[o+3]===0x1A){base=o;break;}}
    if(base<0)throw new Error('MPQ signature not found');
    const bshift=dv.getUint16(base+14,true),sectorSize=512<<bshift,formatVer=dv.getUint16(base+12,true);
    const htp=base+dv.getUint32(base+16,true),btp=base+dv.getUint32(base+20,true);
    const hts=dv.getUint32(base+24,true),bts=dv.getUint32(base+28,true);
    const hashRaw=new Uint32Array(hts*4);for(let i=0;i<hashRaw.length;i++)hashRaw[i]=dv.getUint32(htp+i*4,true);decrypt(hashRaw,hashStr('(hash table)','key'));
    const blockRaw=new Uint32Array(bts*4);for(let i=0;i<blockRaw.length;i++)blockRaw[i]=dv.getUint32(btp+i*4,true);decrypt(blockRaw,hashStr('(block table)','key'));
    function find(name){const idx=hashStr(name,'hash')%hts,a=hashStr(name,'nameA'),b=hashStr(name,'nameB');
      for(let i=0;i<hts;i++){const e=(idx+i)%hts,o=e*4,bi=hashRaw[o+3];if(bi===0xFFFFFFFF)return -1;
        if(hashRaw[o]===a&&hashRaw[o+1]===b&&bi!==0xFFFFFFFE)return bi;}return -1;}
    async function readFile(name){
      const bi=find(name);if(bi<0)throw new Error('not in archive: '+name);
      const o=bi*4,blockOffset=blockRaw[o],filePos=base+blockOffset,fSize=blockRaw[o+2],flags=blockRaw[o+3];
      if(!(flags&FLAG.EXISTS))throw new Error('no EXISTS');
      let key=0;const enc=(flags&FLAG.ENCRYPTED)!==0,comp=(flags&(FLAG.COMPRESS|FLAG.IMPLODE))!==0;
      if(enc){key=hashStr(name.split('\\').pop(),'key');if(flags&FLAG.FIX_KEY)key=((key+blockOffset)^fSize)>>>0;}
      async function decomp(bytes,outSize){
        if(!comp||bytes.length>=outSize)return bytes.subarray(0,outSize);
        if(flags&FLAG.IMPLODE)return explode(bytes).subarray(0,outSize);
        const m=bytes[0],body=bytes.subarray(1);
        if(m&0x02)return (await inflateRaw(body)).subarray(0,outSize);
        if(m&0x08)return explode(body).subarray(0,outSize);
        if(m&0xC1)return smpqWave(body,outSize,m);          // WAVE: Huffman/ADPCM
        if(m===0)return body.subarray(0,outSize);
        throw new Error('nepalaikomas MPQ metodas 0x'+m.toString(16));}
      const single=(flags&FLAG.SINGLE)!==0;
      function decSector(bytes,idx){if(!enc)return bytes;const n=bytes.length>>2;const w=new Uint32Array(n);
        for(let j=0;j<n;j++)w[j]=bytes[j*4]|(bytes[j*4+1]<<8)|(bytes[j*4+2]<<16)|(bytes[j*4+3]<<24);
        decrypt(w,idx>>>0);for(let j=0;j<n;j++){bytes[j*4]=w[j]&0xFF;bytes[j*4+1]=(w[j]>>>8)&0xFF;bytes[j*4+2]=(w[j]>>>16)&0xFF;bytes[j*4+3]=(w[j]>>>24)&0xFF;}return bytes;}
      if(single){let bytes=d.slice(filePos,filePos+blockRaw[o+1]);bytes=decSector(bytes,key);return await decomp(bytes,fSize);}
      // An uncompressed file (no COMPRESS/IMPLODE) has NO sector offset table —
      // the payload sits raw at the block offset. Parsing a table anyway reads
      // garbage lengths; this is what hid every portrait .smk, which are all
      // stored with flags 0x80000000 (EXISTS only).
      if(!comp){
        const out=d.slice(filePos,filePos+fSize);
        if(enc) for(let i=0;i*sectorSize<fSize;i++)
          decSector(out.subarray(i*sectorSize,Math.min(fSize,(i+1)*sectorSize)),(key+i)>>>0);
        return out;
      }
      const nSectors=Math.ceil(fSize/sectorSize);
      const sot=new Uint32Array(nSectors+1);for(let i=0;i<=nSectors;i++)sot[i]=dv.getUint32(filePos+i*4,true);
      if(enc)decrypt(sot,(key-1)>>>0);
      const out=new Uint8Array(fSize);
      for(let i=0;i<nSectors;i++){let bytes=d.slice(filePos+sot[i],filePos+sot[i+1]);
        const thisSize=Math.min(sectorSize,fSize-i*sectorSize);bytes=decSector(bytes,(key+i)>>>0);
        const dec=await decomp(bytes,thisSize);out.set(dec.subarray(0,thisSize),i*sectorSize);}
      return out;}
    let names=[];try{const lf=await readFile('(listfile)');names=new TextDecoder().decode(lf).split(/\r?\n/).map(x=>x.trim()).filter(Boolean);}catch(e){names=[];}
    return {formatVer,sectorSize,hashTableSize:hts,blockTableSize:bts,names,readFile,find};}
  return {open,hashStr,explode};
})();

/* ========================= CASC (local storage) ========================= */
// Low-level layers validated byte-exact vs retail SC:R data (config, .idx v7,
// data.### blob header, BLTE N/Z/F). Browses assets by EKey and decodes on
// click. Filename mapping (root/encoding) needs the full install + SC:R root
// format — not resolved here; use CascView for named extraction if needed.
const CASC=(function(){
  async function inflateRaw(bytes){const ds=new DecompressionStream('deflate');
    const w=ds.writable.getWriter();w.write(bytes);w.close();
    return new Uint8Array(await new Response(ds.readable).arrayBuffer());}
  function parseIdx(buf){
    const d=new Uint8Array(buf),dv=new DataView(buf);
    const spanSizeB=d[12],spanOffB=d[13],keyB=d[14],segBits=d[15];
    const entriesSize=dv.getUint32(0x20,true),entriesOff=0x28,elen=keyB+spanOffB+spanSizeB;
    const n=Math.floor(entriesSize/elen),out=[];const SEG=Math.pow(2,segBits);
    for(let i=0;i<n;i++){const o=entriesOff+i*elen;
      let ekey='';for(let k=0;k<keyB;k++)ekey+=d[o+k].toString(16).padStart(2,'0');
      let packed=0;for(let k=0;k<spanOffB;k++)packed=packed*256+d[o+keyB+k];
      let size=0;for(let k=spanSizeB-1;k>=0;k--)size=size*256+d[o+keyB+spanOffB+k];
      out.push({ekey,fileIdx:Math.floor(packed/SEG),offset:packed%SEG,size});}
    return out;}
  async function blte(data){
    if(!(data[0]===0x42&&data[1]===0x4C&&data[2]===0x54&&data[3]===0x45))throw new Error('ne BLTE');
    const dv=new DataView(data.buffer,data.byteOffset,data.byteLength);
    const hsize=dv.getUint32(4,false);let chunks=[],start;
    if(hsize>0){const cnt=(data[9]<<16)|(data[10]<<8)|data[11];let p=12;
      for(let i=0;i<cnt;i++){chunks.push(dv.getUint32(p,false));p+=8+16;}start=hsize;}
    else{chunks=[data.length-8];start=8;}
    const parts=[];let p=start;
    for(const cs of chunks){const chunk=data.subarray(p,p+cs);p+=cs;const mode=chunk[0],body=chunk.subarray(1);
      if(mode===0x4E)parts.push(body);
      else if(mode===0x5A)parts.push(await inflateRaw(body));
      else if(mode===0x46)parts.push(await blte(body));
      else if(mode===0x45)throw new Error('encrypted BLTE chunk (E)');
      else throw new Error('BLTE mode '+String.fromCharCode(mode));}
    let tot=0;for(const q of parts)tot+=q.length;const out=new Uint8Array(tot);let off=0;
    for(const q of parts){out.set(q,off);off+=q.length;}return out;}
  return {parseIdx,blte,inflateRaw};
})();

/* ---- CASC folder mode ---- */
async function readCascBlob(entry){
  const file=S.cascData.get(entry.fileIdx);
  if(!file) throw new Error('missing data.'+String(entry.fileIdx).padStart(3,'0'));
  const raw=new Uint8Array(await file.slice(entry.offset,entry.offset+entry.size).arrayBuffer());
  return (await CASC.blte(raw.subarray(30))).buffer;
}
// sniff a raw decoded blob and parse into a viewable sprite
async function openBufferSniff(name,buf){
  const d=new Uint8Array(buf),dv=new DataView(buf);
  if(d[0]===0x1a&&d[1]===0x45&&d[2]===0xdf&&d[3]===0xa3)return parseWebM(buf);
  if(d[0]===0x53&&d[1]===0x4D&&d[2]===0x4B)return parseSMK(buf);
  if((d[0]===0x52&&d[1]===0x49&&d[2]===0x46&&d[3]===0x46)||
     (d[0]===0x4F&&d[1]===0x67&&d[2]===0x67&&d[3]===0x53))return parseAudio(buf,name);
  if(d[0]===0x41&&d[1]===0x4E&&d[2]===0x49&&d[3]===0x4D)return parseAnim(buf);
  if(d[0]===0x44&&d[1]===0x44&&d[2]===0x53&&d[3]===0x20){ // raw single DDS
    const img=ddsToImageData(buf,0);
    return {type:'dds',frameCount:1,maxW:img.width,maxH:img.height,frames:[{x:0,y:0,w:img.width,h:img.height,_img:img}],fmtLabel:'DDS '+img.width+'×'+img.height};
  }
  if(d[0]===0x0A)return parsePCX(buf);
  const first=dv.getUint32(0,true);
  if(first===buf.byteLength){const s=parseDdsGRP(buf);precomputeDds(s,buf);return s;}
  const fc=dv.getUint16(0,true),w=dv.getUint16(2,true),h=dv.getUint16(4,true);
  if(fc>0&&fc<10000&&w>0&&w<=800&&h>0&&h<=800)return parseClassicGRP(buf);
  throw new Error('unrecognized content (sig '+[...d.slice(0,4)].map(x=>x.toString(16)).join(' ')+')');
}

/* ---- CASC encoding + root (SC:R) ---- */
function parseEncoding(buf){
  const d=new Uint8Array(buf),dv=new DataView(buf);
  if(d[0]!==0x45||d[1]!==0x4E)throw new Error('not encoding (EN)');
  const ckeyPageKB=dv.getUint16(5,false),ckeyPageCount=dv.getUint32(9,false),especSize=dv.getUint32(18,false);
  const pageSize=ckeyPageKB*1024,pagesOff=22+especSize+ckeyPageCount*32,map=new Map();
  for(let pg=0;pg<ckeyPageCount;pg++){let p=pagesOff+pg*pageSize;const end=p+pageSize;
    while(p<end){const kc=d[p];if(kc===0)break;
      let ck='';for(let i=0;i<16;i++)ck+=d[p+6+i].toString(16).padStart(2,'0');
      let ek='';for(let i=0;i<16;i++)ek+=d[p+22+i].toString(16).padStart(2,'0');
      map.set(ck,ek);p+=22+kc*16;}}
  return map;
}
function parseRoot(buf){
  const txt=new TextDecoder('latin1').decode(new Uint8Array(buf));const map=new Map();
  let i=0;const n=txt.length;
  while(i<n){let j=txt.indexOf('\n',i);if(j<0)j=n;let line=txt.slice(i,j);i=j+1;
    if(line.endsWith('\r'))line=line.slice(0,-1);if(!line)continue;
    const bar=line.lastIndexOf('|');if(bar<0)continue;
    map.set(line.slice(0,bar).toLowerCase(),line.slice(bar+1));}
  return map;
}
async function readCascByEKey(ekeyHex){
  const entry=S.cascIndex.get(ekeyHex.slice(0,18));
  if(!entry)throw new Error('EKey '+ekeyHex.slice(0,12)+' not found in .idx');
  if(!S.cascData.has(entry.fileIdx))throw new Error('needs data.'+String(entry.fileIdx).padStart(3,'0'));
  return await readCascBlob(entry);
}
async function findBuildConfig(files){
  const cands=files.filter(f=>{const rp=f.webkitRelativePath||f.name;
    return (/^[0-9a-f]{32}$/i.test(f.name)||f.name==='.build.info'||/config/i.test(rp))&&f.size>100&&f.size<8192;});
  for(const f of cands.slice(0,80)){
    try{const t=await f.text();
      if(/\broot\s*=/.test(t)&&/\bencoding\s*=/.test(t)){
        const enc=(t.match(/encoding\s*=\s*[0-9a-f]{32}\s+([0-9a-f]{32})/i)||[])[1];
        const root=(t.match(/root\s*=\s*([0-9a-f]{32})/i)||[])[1];
        if(enc&&root)return {encoding:enc,root:root};}
    }catch(e){}
  }
  return null;
}
function buildCascEKeyTree(index){
  const root=newFolder('CASC ('+index.size+' EKeys, data.###: '+[...S.cascData.keys()].sort((a,b)=>a-b).join(',')+')');
  for(const [ekey,e] of index){const grp=ekey.slice(0,2);
    if(!root.folders.has(grp))root.folders.set(grp,newFolder(grp));
    const avail=S.cascData.has(e.fileIdx);
    root.folders.get(grp).files.push({kind:'file',name:ekey.slice(0,12)+(avail?'':' \u2300'),ext:'casc',casc:true,entry:e,avail,path:'casc::'+ekey});}
  S.root=root;S.totalFiles=index.size;S.expanded.clear();renderTree();
}
function buildCascNamedTree(){
  // Graphics plus the media the app can play: portraits and cinematics are
  // .webm, some UI is .smk, sounds are .wav/.ogg.
  const VG=new Set(['grp','dds','anim','pcx','webm','smk','wav','ogg']);
  const root=newFolder('CASC graphics + media ('+S.cascRoot.size+' root names)');
  let count=0;
  for(const [name,ck] of S.cascRoot){
    let ext=extOf(name); if(name.endsWith('.dds'))ext='dds';
    if(!VG.has(ext))continue;
    const parts=name.split('/');let node=root;
    for(let i=0;i<parts.length-1;i++){const seg=parts[i];if(!node.folders.has(seg))node.folders.set(seg,newFolder(seg));node=node.folders.get(seg);}
    node.files.push({kind:'file',name:parts[parts.length-1],ext,casc:true,cascNamed:true,cascName:name,path:'cascn::'+name});
    count++;
  }
  S.root=root;S.totalFiles=count;S.expanded.clear();renderTree();return count;
}
async function openCascNamed(f,row){
  S.activePath=f.path;$$('.row.file-row').forEach(r=>r.classList.remove('on'));if(row)row.classList.add('on');
  showLoad('Searching '+f.name+'…');
  try{
    const ck=S.cascRoot.get(f.cascName.toLowerCase());if(!ck)throw new Error('name not found in root');
    const ek=S.cascEnc.get(ck);if(!ek)throw new Error('CKey not found in encoding');
    const buf=await readCascByEKey(ek);
    const sprite=await openBufferSniff(f.cascName,buf);
    hideLoad();setActive(sprite);
  }catch(e){hideLoad();console.error(e);
    showInfo(`<div class="mk">// CASC</div><div>${f.cascName}</div><div style="color:var(--amber)">${e.message}</div>`);setStatus('CASC: '+e.message);}
}

async function cascFolder(files){
  showLoad('Indexing CASC .idx files…');
  try{
    const idxFiles=files.filter(f=>/\.idx$/i.test(f.name));
    const dataFiles=files.filter(f=>/(^|\/)data\.\d{3}$/i.test(f.webkitRelativePath||f.name));
    if(!idxFiles.length)throw new Error('no .idx files found (specify Data/data or the install folder)');
    S.cascData=new Map();
    for(const f of dataFiles){const m=(f.name).match(/data\.(\d{3})/i);if(m)S.cascData.set(parseInt(m[1]),f);}
    const index=new Map();
    for(const f of idxFiles){const buf=await f.arrayBuffer();for(const e of CASC.parseIdx(buf))index.set(e.ekey,e);}
    S.cascIndex=index;
    $('#cascExtract').style.display='block';
    if(!$('#ekeyIn').value)$('#ekeyIn').value='0c6d7ed43751b8541a5b020c0cfa1708';
    const cfg=await findBuildConfig(files);
    if(cfg&&cfg.encoding&&cfg.root){
      try{
        showLoad('Reading encoding…');
        S.cascEnc=parseEncoding(await readCascByEKey(cfg.encoding));
        const rootEKey=S.cascEnc.get(cfg.root); if(!rootEKey)throw new Error('root CKey not found in encoding');
        showLoad('Reading root…');
        S.cascRoot=parseRoot(await readCascByEKey(rootEKey));
        const cnt=buildCascNamedTree(); hideLoad();
        setStatus('CASC by name: <b>'+cnt+'</b> graphics and media files (of '+S.cascRoot.size+' root names). data['+[...S.cascData.keys()].sort((a,b)=>a-b).join(',')+']');
        return;
      }catch(err){console.warn('named mode',err);setStatus('Named mode failed: '+err.message+' — falling back to EKey.',true);}
    }
    buildCascEKeyTree(index); hideLoad();
    setStatus('CASC by EKey: <b>'+index.size+'</b> entries. For names, specify the install folder (so it finds the build config).');
  }catch(e){hideLoad();showInfo(`<div class="mk">// CASC ERROR</div><div style="color:var(--red)">${e.message}</div>`);setStatus('CASC error: '+e.message,true);}
}
async function openCascNode(f,row){
  if(!f.avail){setStatus('This EKey data (data.'+String(f.entry.fileIdx).padStart(3,'0')+') is not in the loaded files.',true);return;}
  S.activePath=f.path;$$('.row.file-row').forEach(r=>r.classList.remove('on'));if(row)row.classList.add('on');
  showLoad('BLTE decoding '+f.name+'…');
  try{
    const buf=await readCascBlob(f.entry);
    const sprite=await openBufferSniff(f.name,buf);
    hideLoad();setActive(sprite);
  }catch(e){hideLoad();console.error(e);
    showInfo(`<div class="mk">// CASC BLOB</div><div>EKey ${f.entry.ekey}</div><div style="color:var(--amber)">${e.message}</div><div style="max-width:420px;color:var(--ink-dim)">This blob was decrypted, but it is not graphics (probably audio/data) or unrecognized.</div>`);
    setStatus('CASC: '+e.message);}
}

/* ========================= app ========================= */
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const S={active:null,sel:0,bg:'checker',zoom:2,tab:'grid',palMode:'auto',customPal:null,
  playing:false,fps:12,align:true,animT:null,vidZoom:2,vidUrl:null,audUrl:null,frameCache:new Map(),parsedCache:new Map(),externalListfile:null,builtinListfile:false,cascEnc:null,cascRoot:null,cascIndex:null,
  root:null,expanded:new Set(),filter:''};

function setStatus(t,warn){$('#statText').innerHTML=t;const c=warn?'var(--red)':'var(--teal)';
  $('#statDot').style.background=c;$('#statDot').style.boxShadow='0 0 8px '+c;}
function extOf(n){n=n.toLowerCase();
  if(n.endsWith('aiscript.bin')||n.endsWith('bwscript.bin'))return 'ai';
  if(n.endsWith('.chk'))return 'chk';
  if(n.endsWith('.scm')||n.endsWith('.scx'))return 'mpq';   // a map is an MPQ
  if(n.endsWith('.dds.grp')||n.endsWith('_dds.grp'))return 'dds'; if(n.endsWith('.grp'))return 'grp';
  if(n.endsWith('.dds'))return 'dds';   // loose .dds (e.g. casc.py --named-graphics output)
  if(n.endsWith('.anim'))return 'anim'; if(n.endsWith('.pcx'))return 'pcx';
  if(n.endsWith('.smk'))return 'smk'; if(n.endsWith('.webm'))return 'webm';
  if(n.endsWith('.wav')||n.endsWith('.ogg'))return 'wav';
  if(n.endsWith('.mpq')||n.endsWith('.w3x')||n.endsWith('.w3m')||n.endsWith('.s2ma'))return 'mpq';
  return 'other';}
const VIEWABLE=new Set(['grp','dds','anim','pcx','smk','webm','wav','ai','chk']);

/* ---- tree model ---- */
function newFolder(name){return {kind:'folder',name,folders:new Map(),files:[]};}
function addPath(root,parts,file){
  let node=root;
  for(let i=0;i<parts.length-1;i++){
    const seg=parts[i];
    if(!node.folders.has(seg)) node.folders.set(seg,newFolder(seg));
    node=node.folders.get(seg);
  }
  const name=parts[parts.length-1];
  node.files.push({kind:'file',name,ext:extOf(name),file,path:parts.join('/')});
}
function buildTreeFromFiles(fileList){
  const root=newFolder('');
  for(const f of fileList){
    const rel=f.webkitRelativePath||f.name;
    addPath(root,rel.split('/'),f);
  }
  return root;
}

/* ---- tree render ---- */
// StarCraft hero portraits sit in folders with cryptic codes ("ujim" for
// Raynor) and file prefixes that match neither the folder nor the character's
// English name ("ura*" under ujim). This maps common names to the codes so a
// search finds them. Confirmed by cross-referencing the sound folders, which
// DO spell the names, against the portrait file prefixes; a few (Stukov,
// DuGalle, Raszagal) have no sound folder and are from established lore.
const NAME_ALIASES={
  raynor:['ujim','/ura','/urv','raynorm','raynorv'], jim:['ujim'],
  kerrigan:['ukerr','uikerr','/uke','/uik','zergkerri'],
  'queen of blades':['uikerr','/uik'], 'infested kerrigan':['uikerr','/uik'],
  tassadar:['utassadar','/uta'], zeratul:['uzeratul','/uze'],
  fenix:['ufendrag','ufenzeal','fenixd','fenixz','/ufd','/ufe'],
  duke:['uduke','udtemplar','dukeb','duket','/udu','/udt'],
  artanis:['partanis','/pat'], mengsk:['umengsk','/ume'], arcturus:['umengsk'],
  zasz:['uzasz'], stukov:['talex','/tax'], alexei:['talex'],
  dugalle:['tdugal','/udg'], gerard:['tdugal'],
  raszagal:['praz','/prz'], duran:['tsam','duran','zergduran','/tsm'],
  samir:['tsam','duran'], advisor:['advisor'],
};
function aliasTargets(q){
  if(S._alQ===q)return S._alT;
  const out=[]; for(const k in NAME_ALIASES){ if(k.includes(q)||q.includes(k)) out.push(...NAME_ALIASES[k]); }
  S._alQ=q; S._alT=out; return out;
}
// Match against the whole path, not just the leaf name, so a search like
// "kerr" finds files under folder "ukerr" even though the files are "uke*";
// and hero name aliases so "raynor" or "fenix" find their coded folders.
function matchFilter(f){if(!S.filter)return true;const s=((f&&f.path)||(f&&f.name)||f||'').toLowerCase();
  if(s.includes(S.filter))return true;
  const al=aliasTargets(S.filter); for(let i=0;i<al.length;i++)if(s.includes(al[i]))return true;
  return false;}
function folderHasMatch(node){
  if(!S.filter) return true;
  for(const f of node.files) if(f.ext!=='other' && matchFilter(f)) return true;
  for(const [,c] of node.folders) if(folderHasMatch(c)) return true;
  return false;
}
function badge(ext){const map={grp:'GRP',dds:'DDS',anim:'ANIM',pcx:'PCX',smk:'SMK',webm:'WEBM',wav:'AUDIO',mpq:'MPQ',casc:'EKEY'};
  return map[ext]?`<span class="badge b-${ext}">${map[ext]}</span>`:'';}
function renderTree(){
  const host=$('#tree'); host.innerHTML='';
  if(!S.root){host.innerHTML='<div style="padding:14px;color:var(--ink-dim);font-size:12px">Nothing loaded.</div>';return;}
  const frag=document.createDocumentFragment();
  renderFolder(S.root,frag,'',true);
  host.appendChild(frag);
  const shown=$('#tree').querySelectorAll('.row.file-row').length;
  $('#statMeta').textContent=S.totalFiles?`${S.totalFiles} files · ${shown} shown`:'';
}
function renderFolder(node,host,prefix,isRoot){
  // folders first
  const folders=[...node.folders.values()].sort((a,b)=>a.name.localeCompare(b.name));
  for(const f of folders){
    if(!folderHasMatch(f))continue;
    const key=prefix+'/'+f.name;
    const open=S.expanded.has(key)|| !!S.filter;
    const wrap=document.createElement('div'); wrap.className='node';
    const row=document.createElement('div'); row.className='row';
    row.innerHTML=`<span class="tw">${open?'▾':'▸'}</span><span class="ic">📁</span><span class="nm">${f.name}</span>`;
    row.onclick=()=>{ if(S.expanded.has(key))S.expanded.delete(key); else S.expanded.add(key); renderTree(); };
    wrap.appendChild(row);
    if(open){ const ch=document.createElement('div'); ch.className='children'; renderFolder(f,ch,key,false); wrap.appendChild(ch); }
    host.appendChild(wrap);
  }
  // files
  const files=node.files.filter(f=>f.ext!=='other' && matchFilter(f)).sort((a,b)=>a.name.localeCompare(b.name));
  for(const f of files){
    const row=document.createElement('div'); row.className='row file-row'+(S.activePath===f.path?' on':'');
    const icon=f.ext==='mpq'?'📦':(f.casc&&!f.cascNamed)?'🔑':(f.ext==='smk'?'🎞':'🖼');
    row.innerHTML=`<span class="tw"></span><span class="ic">${icon}</span><span class="nm" title="${f.name}">${f.name}</span>${badge(f.ext)}`;
    row.onclick=()=>openFileNode(f,row);
    host.appendChild(row);
    // if this mpq node was expanded, render its virtual children
    if(f.ext==='mpq' && f._children){
      const ch=document.createElement('div'); ch.className='children';
      renderFolder(f._children,ch,f.path,false);
      host.appendChild(ch);
    }
  }
}

/* ---- counting ---- */
function countFiles(node){let n=0;for(const f of node.files)if(f.ext!=='other')n++;for(const[,c]of node.folders)n+=countFiles(c);return n;}

/* ---- open a file node (lazy) ---- */
function showLoad(t){$('#loadText').textContent=t||'Loading…';$('#loadMsg').style.display='flex';}
function hideLoad(){$('#loadMsg').style.display='none';}
function showInfo(html){['gridView','detailView','animView','emptyState'].forEach(id=>$('#'+id).style.display='none');
  $('#infoMsg').style.display='flex';$('#infoMsg').innerHTML=html;}

async function readNode(f){
  if(f.mpq){ return (await f.mpq.readFile(f.mpqPath)).buffer; }
  return await f.file.arrayBuffer();
}
async function openFileNode(f,row){
  if(f.casc){ return f.cascNamed?openCascNamed(f,row):openCascNode(f,row); }
  if(f.ext==='mpq'){ return toggleMpq(f,row); }
  S.activePath=f.path; $$('.row.file-row').forEach(r=>r.classList.remove('on')); if(row)row.classList.add('on');
  if(S.parsedCache.has(f.path)){ setActive(S.parsedCache.get(f.path)); return; }
  showLoad('Decoding '+f.name+'…');
  try{
    const buf=await readNode(f);
    const sprite=await openBuffer(f.name,buf);
    S.parsedCache.set(f.path,sprite);
    hideLoad(); setActive(sprite);
  }catch(e){ hideLoad(); console.error(e);
    showInfo(`<div class="mk">// DECODE ERROR</div><div>${f.name}</div><div style="color:var(--red)">${e.message}</div>`);
    setStatus('Error: <b>'+f.name+'</b> — '+e.message,true);
  }
}

/* ---- AI scripts (aiscript.bin / bwscript.bin) ----
   Opcode table GENERATED from tools/ai/ai_opcodes.py (which is itself cut from
   PyMS AIBIN.py). Structure + arg sizes measured against BW 1.16.1; the CFG
   trace is the same corpus oracle as tests/ai/test_ai_disasm.py. */
const AI_OPCODES=[{"n":"goto","a":[["address",2]],"c":"jump"},{"n":"notowns_jump","a":[["unit",2],["address",2]],"c":"cond_jump"},{"n":"wait","a":[["word",2]],"c":""},{"n":"start_town","a":[],"c":""},{"n":"start_areatown","a":[],"c":""},{"n":"expand","a":[["byte",1],["address",2]],"c":"cond_jump"},{"n":"build","a":[["byte",1],["building",2],["byte",1]],"c":""},{"n":"upgrade","a":[["byte",1],["upgrade",2],["byte",1]],"c":""},{"n":"tech","a":[["technology",2],["byte",1]],"c":""},{"n":"wait_build","a":[["byte",1],["building",2]],"c":""},{"n":"wait_buildstart","a":[["byte",1],["unit",2]],"c":""},{"n":"attack_clear","a":[],"c":""},{"n":"attack_add","a":[["byte",1],["military",2]],"c":""},{"n":"attack_prepare","a":[],"c":""},{"n":"attack_do","a":[],"c":""},{"n":"wait_secure","a":[],"c":""},{"n":"capt_expand","a":[],"c":""},{"n":"build_bunkers","a":[],"c":""},{"n":"wait_bunkers","a":[],"c":""},{"n":"defensebuild_gg","a":[["byte",1],["gg_military",2]],"c":""},{"n":"defensebuild_ag","a":[["byte",1],["ag_military",2]],"c":""},{"n":"defensebuild_ga","a":[["byte",1],["ga_military",2]],"c":""},{"n":"defensebuild_aa","a":[["byte",1],["aa_military",2]],"c":""},{"n":"defenseuse_gg","a":[["byte",1],["gg_military",2]],"c":""},{"n":"defenseuse_ag","a":[["byte",1],["ag_military",2]],"c":""},{"n":"defenseuse_ga","a":[["byte",1],["ga_military",2]],"c":""},{"n":"defenseuse_aa","a":[["byte",1],["aa_military",2]],"c":""},{"n":"defenseclear_gg","a":[],"c":""},{"n":"defenseclear_ag","a":[],"c":""},{"n":"defenseclear_ga","a":[],"c":""},{"n":"defenseclear_aa","a":[],"c":""},{"n":"send_suicide","a":[["byte",1]],"c":""},{"n":"player_enemy","a":[],"c":""},{"n":"player_ally","a":[],"c":""},{"n":"default_min","a":[["byte",1]],"c":""},{"n":"defaultbuild_off","a":[],"c":""},{"n":"stop","a":[],"c":"terminate"},{"n":"switch_rescue","a":[],"c":""},{"n":"move_dt","a":[],"c":""},{"n":"debug","a":[["address",2],["string",-1]],"c":"cond_jump"},{"n":"fatal_error","a":[],"c":"terminate"},{"n":"enter_bunker","a":[],"c":""},{"n":"value_area","a":[],"c":""},{"n":"transports_off","a":[],"c":""},{"n":"check_transports","a":[],"c":""},{"n":"nuke_rate","a":[["byte",1]],"c":""},{"n":"max_force","a":[["word",2]],"c":""},{"n":"clear_combatdata","a":[],"c":""},{"n":"random_jump","a":[["byte",1],["address",2]],"c":"cond_jump"},{"n":"time_jump","a":[["byte",1],["address",2]],"c":"cond_jump"},{"n":"farms_notiming","a":[],"c":""},{"n":"farms_timing","a":[],"c":""},{"n":"build_turrets","a":[],"c":""},{"n":"wait_turrets","a":[],"c":""},{"n":"default_build","a":[],"c":""},{"n":"harass_factor","a":[["word",2]],"c":""},{"n":"start_campaign","a":[],"c":""},{"n":"race_jump","a":[["address",2],["address",2],["address",2]],"c":"multi_jump"},{"n":"region_size","a":[["byte",1],["address",2]],"c":"cond_jump"},{"n":"get_oldpeons","a":[["byte",1]],"c":""},{"n":"groundmap_jump","a":[["address",2]],"c":"cond_jump"},{"n":"place_guard","a":[["unit",2],["byte",1]],"c":""},{"n":"wait_force","a":[["byte",1],["military",2]],"c":""},{"n":"guard_resources","a":[["military",2]],"c":""},{"n":"call","a":[["address",2]],"c":"call"},{"n":"return","a":[],"c":"terminate"},{"n":"eval_harass","a":[["address",2]],"c":"cond_jump"},{"n":"creep","a":[["byte",1]],"c":""},{"n":"panic","a":[["address",2]],"c":"cond_jump"},{"n":"player_need","a":[["byte",1],["building",2]],"c":""},{"n":"do_morph","a":[["byte",1],["military",2]],"c":""},{"n":"wait_upgrades","a":[],"c":""},{"n":"multirun","a":[["address",2]],"c":"spawn"},{"n":"rush","a":[["byte",1],["address",2]],"c":"cond_jump"},{"n":"scout_with","a":[["military",2]],"c":""},{"n":"define_max","a":[["byte",1],["unit",2]],"c":""},{"n":"train","a":[["byte",1],["military",2]],"c":""},{"n":"target_expansion","a":[],"c":""},{"n":"wait_train","a":[["byte",1],["unit",2]],"c":""},{"n":"set_attacks","a":[["byte",1]],"c":""},{"n":"set_gencmd","a":[],"c":""},{"n":"make_patrol","a":[],"c":""},{"n":"give_money","a":[],"c":""},{"n":"prep_down","a":[["byte",1],["byte",1],["military",2]],"c":""},{"n":"resources_jump","a":[["word",2],["word",2],["address",2]],"c":"cond_jump"},{"n":"enter_transport","a":[],"c":""},{"n":"exit_transport","a":[],"c":""},{"n":"sharedvision_on","a":[["byte",1]],"c":""},{"n":"sharedvision_off","a":[["byte",1]],"c":""},{"n":"nuke_location","a":[],"c":""},{"n":"harass_location","a":[],"c":""},{"n":"implode","a":[],"c":""},{"n":"guard_all","a":[],"c":""},{"n":"enemyowns_jump","a":[["unit",2],["address",2]],"c":"cond_jump"},{"n":"enemyresources_jump","a":[["word",2],["word",2],["address",2]],"c":"cond_jump"},{"n":"if_dif","a":[["compare",1],["byte",1],["address",2]],"c":"cond_jump"},{"n":"easy_attack","a":[["byte",1],["military",2]],"c":""},{"n":"kill_thread","a":[],"c":"terminate"},{"n":"killable","a":[],"c":""},{"n":"wait_finishattack","a":[],"c":""},{"n":"quick_attack","a":[],"c":""},{"n":"junkyard_dog","a":[],"c":""},{"n":"fake_nuke","a":[],"c":""},{"n":"disruption_web","a":[],"c":""},{"n":"recall_location","a":[],"c":""},{"n":"set_randomseed","a":[["dword",4]],"c":""},{"n":"if_owned","a":[["unit",2],["address",2]],"c":"cond_jump"},{"n":"create_nuke","a":[],"c":""},{"n":"create_unit","a":[["unit",2],["word",2],["word",2]],"c":""},{"n":"nuke_pos","a":[["word",2],["word",2]],"c":""},{"n":"help_iftrouble","a":[],"c":""},{"n":"allies_watch","a":[["byte",1],["address",2]],"c":"cond_jump"},{"n":"try_townpoint","a":[["byte",1],["address",2]],"c":"cond_jump"},{"n":"if_towns","a":[],"c":""}];
const AI_MAXOP=AI_OPCODES.length-1;
function aiDecodeOne(d,pos){
  const op=d[pos]; if(op>AI_MAXOP) throw new Error('invalid opcode 0x'+op.toString(16)+' at 0x'+pos.toString(16));
  const spec=AI_OPCODES[op]; const args=[]; let o=pos+1;
  for(const [t,sz] of spec.a){
    if(sz<0){ let e=d.indexOf(0,o); if(e<0)throw new Error('unterminated string'); let s='';
      for(let i=o;i<e;i++)s+=String.fromCharCode(d[i]); args.push({t,v:s,sz:e+1-o}); o=e+1; }
    else{ let v; if(sz===1)v=d[o]; else if(sz===2)v=d[o]|(d[o+1]<<8);
      else v=(d[o]|(d[o+1]<<8)|(d[o+2]<<16))+(d[o+3]*16777216); args.push({t,v,sz}); o+=sz; }
  }
  return {address:pos,opcode:op,name:spec.n,cf:spec.c,args,size:o-pos};
}
function aiTrace(d,start,tableOff){
  const seen=new Set(); const work=[start];
  while(work.length){ let pos=work.pop();
    while(true){ if(seen.has(pos))break; if(pos<0||pos>=tableOff)throw new Error('flow left region at 0x'+pos.toString(16));
      const ins=aiDecodeOne(d,pos); seen.add(pos);
      for(const a of ins.args) if(a.t==='address') work.push(a.v);
      if(ins.cf==='jump'||ins.cf==='terminate')break; pos+=ins.size; }
  }
  return seen;
}
function parseAiScripts(buf,name){
  const d=new Uint8Array(buf), dv=new DataView(buf);
  const tableOff=dv.getUint32(0,true);
  const isBw=/bw/i.test(name); const esize=isBw?8:16;
  const scripts=[]; let off=tableOff;
  while(off+esize<=d.length){
    if(d[off]===0&&d[off+1]===0&&d[off+2]===0&&d[off+3]===0)break;
    const id=String.fromCharCode(d[off],d[off+1],d[off+2],d[off+3]);
    const codeOff=dv.getUint32(off+4,true);
    let stringId=0,flags=0; if(esize>=16){stringId=dv.getUint32(off+8,true);flags=dv.getUint32(off+12,true);}
    off+=esize;
    if(codeOff===0)continue;
    let ins=[],err=null;
    try{ const starts=[...aiTrace(d,codeOff,tableOff)].sort((a,b)=>a-b); ins=starts.map(p=>aiDecodeOne(d,p)); }
    catch(e){ err=e.message; }
    scripts.push({id,codeOff,stringId,flags,ins,err});
  }
  return {ai:true,source:isBw?'bwscript.bin':'aiscript.bin',fmtLabel:name,scripts,tableOff,bytes:d.length,_u8:d};
}
/* JS AI assembler — mirrors tools/ai/ai_asm.py. Difficulty scaling only changes
   argument VALUES (never sizes), so the scaled binary is the original with those
   bytes overwritten in place — no relocation, layout-safe by construction. */
function aiEncodeInstr(ins,srcD){        // one instruction -> byte array (round-trip)
  const out=[ins.opcode]; let o=ins.address+1;
  for(const a of ins.args){
    if(a.t==='string'){ for(let k=0;k<a.sz;k++)out.push(srcD[o+k]); }
    else if(a.sz===1)out.push(a.v&0xff);
    else if(a.sz===2)out.push(a.v&0xff,(a.v>>8)&0xff);
    else if(a.sz===4)out.push(a.v&0xff,(a.v>>8)&0xff,(a.v>>16)&0xff,(a.v>>>24)&0xff);
    o+=a.sz;
  }
  return out;
}
function aiBuildScaledBin(doc,profile){  // -> Uint8Array of the whole scaled .bin
  const out=doc._u8.slice();
  if(profile==='off')return out;
  for(const s of doc.scripts){
    if(s.err)continue;
    const m=aiScale(s.ins,profile);
    for(const i of s.ins){
      const nv=m[i.address+'#0'];
      if(nv===undefined)continue;
      const off=i.address+1, sz=i.args[0].sz;   // scalable arg is always arg 0
      out[off]=nv&0xff; if(sz===2)out[off+1]=(nv>>8)&0xff;
    }
  }
  return out;
}
/* JS twin of tools/ai/ai_gen.py — compile a tactic (steps) into a byte-exact,
   disasm-clean aiscript.bin. Steps: ['label',name] or [opname,...args] where an
   address arg is a label NAME (string) and every other arg is the raw numeric
   bytecode value. Verified byte-identical to the Python generator (same sample
   -> same sha256). merge_into keeps every stock script's bytes verbatim. */
const AI_OP_BY_NAME=(()=>{const m={};AI_OPCODES.forEach((o,i)=>{m[o.n]={op:i,a:o.a,c:o.c};});return m;})();
function aiOpSize(name,args){
  const spec=AI_OP_BY_NAME[name]; if(!spec)throw new Error('unknown opcode "'+name+'"');
  if(args.length!==spec.a.length)throw new Error(name+' takes '+spec.a.length+' args, got '+args.length);
  let size=1;
  for(let k=0;k<spec.a.length;k++){ const sz=spec.a[k][1];
    if(sz<0){ const v=args[k]; const b=(typeof v==='string')?v:String(v); size+=b.length+1; } else size+=sz; }
  return size;
}
function aiLayoutScript(steps,base){
  const labels={}; let pos=base;
  for(const st of steps){ if(st[0]==='label'){ if(st[1] in labels)throw new Error('duplicate label "'+st[1]+'"'); labels[st[1]]=pos; }
    else pos+=aiOpSize(st[0],st.slice(1)); }
  const out=[];
  for(const st of steps){ if(st[0]==='label')continue;
    const spec=AI_OP_BY_NAME[st[0]]; out.push(spec.op); const args=st.slice(1);
    for(let k=0;k<spec.a.length;k++){ const [t,sz]=spec.a[k]; const v=args[k];
      if(t==='address'){ if(!(v in labels))throw new Error('undefined label "'+v+'"'); const a=labels[v]&0xffff; out.push(a&0xff,(a>>8)&0xff); }
      else if(sz<0){ const b=(typeof v==='string')?v:String(v); for(let i=0;i<b.length;i++)out.push(b.charCodeAt(i)&0xff); out.push(0); }
      else if(sz===1)out.push(v&0xff);
      else if(sz===2)out.push(v&0xff,(v>>8)&0xff);
      else out.push(v&0xff,(v>>8)&0xff,(v>>16)&0xff,(v>>>24)&0xff);
    }
  }
  return {code:out,labels};
}
function aiPackEntry(out,id,off,sid,flags){
  for(let i=0;i<4;i++)out.push(i<id.length?id.charCodeAt(i)&0xff:0);
  out.push(off&0xff,(off>>8)&0xff,(off>>16)&0xff,(off>>>24)&0xff);
  out.push(sid&0xff,(sid>>8)&0xff,(sid>>16)&0xff,(sid>>>24)&0xff);
  out.push(flags&0xff,(flags>>8)&0xff,(flags>>16)&0xff,(flags>>>24)&0xff);
}
function aiBuildBin(scripts,base){
  base=base||4; const code=[]; for(let i=0;i<base;i++)code.push(0);
  const entries=[];
  for(const s of scripts){ const start=code.length;
    const {code:body}=aiLayoutScript(s.code,start);
    for(const b of body)code.push(b);
    entries.push([s.id,start,s.name|0,s.flags|0]); }
  const tableOff=code.length; const out=code.slice();
  for(const [id,off,sid,fl] of entries)aiPackEntry(out,id,off,sid,fl);
  out.push(0,0,0,0);
  out[0]=tableOff&0xff;out[1]=(tableOff>>8)&0xff;out[2]=(tableOff>>16)&0xff;out[3]=(tableOff>>>24)&0xff;
  return new Uint8Array(out);
}
function aiMergeInto(baseU8,scripts){
  const dv=new DataView(baseU8.buffer,baseU8.byteOffset,baseU8.byteLength);
  const oldTable=dv.getUint32(0,true);
  const ents=[]; const ids=new Set(); let off=oldTable;  // keep EVERY entry incl. unused
  while(off+16<=baseU8.length){
    if(baseU8[off]===0&&baseU8[off+1]===0&&baseU8[off+2]===0&&baseU8[off+3]===0)break;
    const id=String.fromCharCode(baseU8[off],baseU8[off+1],baseU8[off+2],baseU8[off+3]);
    ents.push([id,dv.getUint32(off+4,true),dv.getUint32(off+8,true),dv.getUint32(off+12,true)]);
    ids.add(id); off+=16;
  }
  const newCode=[]; const newEnts=[];
  for(const s of scripts){ if(ids.has(s.id))throw new Error('ID "'+s.id+'" already exists in the stock file'); ids.add(s.id);
    const start=oldTable+newCode.length; const {code:body}=aiLayoutScript(s.code,start);
    for(const b of body)newCode.push(b); newEnts.push([s.id,start,s.name|0,s.flags|0]); }
  const newTable=oldTable+newCode.length;
  const out=[]; for(let i=0;i<oldTable;i++)out.push(baseU8[i]);
  for(const b of newCode)out.push(b);
  for(const [id,o,sid,fl] of ents)aiPackEntry(out,id,o,sid,fl);
  for(const [id,o,sid,fl] of newEnts)aiPackEntry(out,id,o,sid,fl);
  out.push(0,0,0,0);
  out[0]=newTable&0xff;out[1]=(newTable>>8)&0xff;out[2]=(newTable>>16)&0xff;out[3]=(newTable>>>24)&0xff;
  return new Uint8Array(out);
}
/* tactic text -> steps. Address args stay label names; the rest parse as ints. */
function aiParseSteps(text){
  const steps=[]; const lines=text.split('\n');
  lines.forEach((raw,li)=>{
    const line=raw.replace(/#.*$/,'').trim(); if(!line)return;
    if(line[0]===':'){ steps.push(['label',line.slice(1).trim()]); return; }
    const tok=line.split(/[\s,]+/).filter(Boolean); const name=tok[0]; const spec=AI_OP_BY_NAME[name];
    if(!spec)throw new Error('line '+(li+1)+': unknown opcode "'+name+'"');
    const ra=tok.slice(1);
    if(ra.length!==spec.a.length)throw new Error('line '+(li+1)+': '+name+' needs '+spec.a.length+' args, got '+ra.length);
    const args=spec.a.map(([t,sz],k)=>{ const r=ra[k];
      if(t==='address')return r; if(sz<0)return r;
      const v=/^0x/i.test(r)?parseInt(r,16):parseInt(r,10);
      if(Number.isNaN(v))throw new Error('line '+(li+1)+': bad number "'+r+'"'); return v; });
    steps.push([name,...args]);
  });
  return steps;
}
function aiArgText(a){
  if(a.t==='address')return '→0x'+a.v.toString(16);
  if(a.t==='string')return JSON.stringify(a.v);
  return a.t+'='+a.v;
}
/* semantic summary (mirrors tools/ai/ai_semantics.py) */
const AI_PRODUCTION=new Set(['build','train','define_max','wait_train','do_morph','create_unit']);
const AI_TECH=new Set(['tech','upgrade']);
const AI_DEFENCE=new Set(['defensebuild_gg','defensebuild_ag','defensebuild_ga','defensebuild_aa','defenseuse_gg','defenseuse_ag','defenseuse_ga','defenseuse_aa','build_bunkers','build_turrets']);
function aiSemantics(ins){
  let camp=false,towns=0,prod=0,tech=0,def=0,waves=0,wave=0;
  for(const i of ins){
    const n=i.name;
    if(n==='start_campaign')camp=true;
    else if(n==='start_town'||n==='start_areatown')towns++;
    else if(AI_PRODUCTION.has(n))prod++;
    else if(AI_TECH.has(n))tech++;
    else if(AI_DEFENCE.has(n))def++;
    else if(n==='attack_add'||n==='easy_attack')wave++;
    else if(n==='attack_do'){if(wave){waves++;wave=0;}}
    else if(n==='attack_clear')wave=0;
  }
  if(wave)waves++;
  return {camp,towns,prod,tech,def,waves};
}
/* difficulty scaler (mirrors tools/ai/ai_scaler.py) */
const AI_PROFILES={off:{wave:1,def:1,prod:1,maxf:1,delay:1},
  hard:{wave:1.35,def:1.2,prod:1.2,maxf:1.25,delay:0.85},
  brutal:{wave:1.6,def:1.4,prod:1.3,maxf:1.5,delay:0.7}};
const AI_COUNT_KNOB={attack_add:'wave',easy_attack:'wave',defensebuild_gg:'def',defensebuild_ag:'def',
  defensebuild_ga:'def',defensebuild_aa:'def',defenseuse_gg:'def',defenseuse_ag:'def',defenseuse_ga:'def',
  defenseuse_aa:'def',define_max:'prod',wait_train:'prod'};
const AI_WORD_KNOB={max_force:'maxf',wait:'delay'};
let aiProfile='off';
function aiScale(ins,pr){ // returns Map(instr_addr+'#'+argIdx -> newVal)
  const p=AI_PROFILES[pr]||AI_PROFILES.off; const m={};
  for(const i of ins){
    if(AI_COUNT_KNOB[i.name]&&i.args[0]&&i.args[0].t==='byte'){
      const nv=Math.max(0,Math.min(255,Math.round(i.args[0].v*p[AI_COUNT_KNOB[i.name]])));
      if(nv!==i.args[0].v)m[i.address+'#0']=nv;
    } else if(AI_WORD_KNOB[i.name]&&i.args[0]&&i.args[0].t==='word'){
      let nv=Math.round(i.args[0].v*p[AI_WORD_KNOB[i.name]]); if(i.name==='wait')nv=Math.max(1,nv);
      nv=Math.max(0,Math.min(65535,nv)); if(nv!==i.args[0].v)m[i.address+'#0']=nv;
    }
  }
  return m;
}
function aiLoops(ins){ let n=0; for(const i of ins)for(const a of i.args)if(a.t==='address'&&a.v<=i.address)n++; return n; }
/* ---- pure-JS STORED zip writer (no external libs; deterministic) ---- */
const _crcTable=(()=>{const t=new Uint32Array(256);for(let n=0;n<256;n++){let c=n;
  for(let k=0;k<8;k++)c=c&1?(0xEDB88320^(c>>>1)):(c>>>1); t[n]=c>>>0;} return t;})();
function crc32(u8){let c=0xFFFFFFFF;for(let i=0;i<u8.length;i++)c=_crcTable[(c^u8[i])&0xff]^(c>>>8);return (c^0xFFFFFFFF)>>>0;}
function zipStore(entries){        // entries: [{name, data:Uint8Array}] -> Uint8Array
  const enc=s=>new TextEncoder().encode(s);
  const parts=[], central=[]; let offset=0;
  const DOSDATE=0x21, DOSTIME=0;   // 1980-01-01 00:00 (deterministic)
  const push=(arr,...b)=>{for(const x of b)arr.push(x);};
  const u16=(arr,v)=>push(arr,v&0xff,(v>>8)&0xff);
  const u32=(arr,v)=>push(arr,v&0xff,(v>>8)&0xff,(v>>16)&0xff,(v>>>24)&0xff);
  for(const e of [...entries].sort((a,b)=>a.name<b.name?-1:1)){
    const name=enc(e.name), data=e.data, crc=crc32(data), h=[];
    u32(h,0x04034b50); u16(h,20); u16(h,0); u16(h,0); u16(h,DOSTIME); u16(h,DOSDATE);
    u32(h,crc); u32(h,data.length); u32(h,data.length); u16(h,name.length); u16(h,0);
    for(const c of name)h.push(c);
    parts.push(new Uint8Array(h), data);
    const c=[];
    u32(c,0x02014b50); u16(c,20); u16(c,20); u16(c,0); u16(c,0); u16(c,DOSTIME); u16(c,DOSDATE);
    u32(c,crc); u32(c,data.length); u32(c,data.length); u16(c,name.length);
    u16(c,0); u16(c,0); u16(c,0); u16(c,0); u32(c,0); u32(c,offset);
    for(const ch of name)c.push(ch);
    central.push(new Uint8Array(c));
    offset+=h.length+data.length;
  }
  const cdStart=offset; let cdSize=0; for(const c of central)cdSize+=c.length;
  const eocd=[]; u32(eocd,0x06054b50); u16(eocd,0); u16(eocd,0);
  u16(eocd,central.length); u16(eocd,central.length); u32(eocd,cdSize); u32(eocd,cdStart); u16(eocd,0);
  const all=[...parts,...central,new Uint8Array(eocd)];
  let total=0; for(const p of all)total+=p.length;
  const out=new Uint8Array(total); let o=0; for(const p of all){out.set(p,o);o+=p.length;}
  return out;
}
function renderAiHtml(f){
  window._aiFile=f;
  const used=f.scripts; const ok=used.filter(s=>!s.err).length;
  let h='<div class="mk">// '+f.source+' — '+used.length+' scripts with code, '+ok+' decoded cleanly (0 unknown opcodes)</div>';
  h+='<div style="max-width:760px;margin-bottom:6px;font:12px ui-monospace,monospace">Difficulty scaler: '
    +'<select onchange="aiProfile=this.value;showInfo(renderAiHtml(window._aiFile))" style="background:var(--panel);color:var(--ink);border:1px solid var(--edge);padding:2px 6px">'
    +['off','hard','brutal'].map(p=>'<option value="'+p+'"'+(p===aiProfile?' selected':'')+'>'+p+'</option>').join('')+'</select>'
    +(aiProfile!=='off'?' <span style="color:#c8b878">— scaled values marked <b>old→new</b>; sizes unchanged → layout-safe ✓</span>':'')+'</div>';
  h+='<div style="max-width:760px;max-height:70vh;overflow:auto;font:12px/1.55 ui-monospace,Consolas,monospace;text-align:left">';
  for(const s of used){
    const fl=[]; if(s.flags&1)fl.push('loc'); if(s.flags&2)fl.push('hidden'); if(s.flags&4)fl.push('bw');
    h+='<details style="margin:2px 0;border-bottom:1px solid var(--edge)"><summary style="cursor:pointer;color:var(--teal);padding:2px 0">'
      +s.id+'  <span style="color:var(--ink-dim);font-weight:400">@0x'+s.codeOff.toString(16)+' · '+s.ins.length+' instr'
      +(fl.length?' · ['+fl.join(',')+']':'')+(s.err?' · <span style="color:var(--red)">ERR '+s.err+'</span>':'')+'</span></summary>';
    h+='<div style="padding:2px 0 8px 14px;color:var(--ink)">';
    const scaled=(aiProfile!=='off')?aiScale(s.ins,aiProfile):{};
    if(s.ins.length){
      const sm=aiSemantics(s.ins);
      const bits=[];
      if(sm.camp)bits.push('campaign');
      if(sm.towns)bits.push(sm.towns+' town'+(sm.towns>1?'s':''));
      if(sm.prod)bits.push(sm.prod+' production');
      if(sm.tech)bits.push(sm.tech+' tech');
      if(sm.def)bits.push(sm.def+' defence');
      if(sm.waves)bits.push(sm.waves+' attack wave'+(sm.waves>1?'s':''));
      const lp=aiLoops(s.ins); if(lp)bits.push(lp+' loop'+(lp>1?'s':''));
      const nch=Object.keys(scaled).length;
      if(nch)bits.push('<span style="color:#c8b878">'+nch+' scaled</span>');
      h+='<div style="color:var(--teal);margin-bottom:4px">// '+bits.join(' · ')+'</div>';
    }
    for(const i of s.ins){
      const args=i.args.map((a,ai)=>{
        const key=i.address+'#'+ai;
        if(scaled[key]!==undefined) return a.t+'=<span style="color:#c8b878;font-weight:600">'+a.v+'→'+scaled[key]+'</span>';
        return aiArgText(a);
      }).join(', ');
      const col=(i.cf==='terminate')?'#e0708a':(i.cf?'#c8b878':'var(--ink)');
      h+='<div><span style="color:var(--ink-dim)">0x'+i.address.toString(16).padStart(5,'0')+'</span>  '
        +'<span style="color:'+col+'">'+i.name+'</span>'+(args?'  '+args:'')+'</div>';
    }
    h+='</div></details>';
  }
  h+='</div>';
  return h;
}

/* ---- CHK campaign analyzer (mirrors tools/ai/chk.py + chk_ai_links.py) ---- */
/* Campaign mission analysis — JS twins of tools/ai/briefing.py + mission_actions.py.
   Trigger action names from PyMS TRG.py (attributed); field layout MEASURED. */
const CHK_TRIG_ACTIONS=['NoAction','Victory','Defeat','PreserveTrigger','Wait','PauseGame','UnpauseGame','Transmission','PlayWAV','DisplayTextMessage','CenterView','CreateUnitWithProperties','SetMissionObjectives','SetSwitch','SetCountdownTimer','RunAIScript','RunAIScriptAtLocation','LeaderBoardControl','LeaderBoardControlAtLocation','LeaderBoardResources','LeaderBoardKills','LeaderBoardPoints','KillUnit','KillUnitsAtLocation','RemoveUnit','RemoveUnitAtLocation','SetResources','SetScore','MinimapPing','TalkingPortrait','MuteUnitSpeech','UnmuteUnitSpeech','LeaderboardComputerPlayers','LeaderboardGoalControl','LeaderboardGoalControlAtLocation','LeaderboardGoalResources','LeaderboardGoalKills','LeaderboardGoalPoints','MoveLocation','MoveUnit','LeaderboardGreed','SetNextScenario','SetDoodadState','SetInvincibility','CreateUnit','SetDeaths','Order','Comment','GiveUnitstoPlayer','ModifyUnitHitPoints','ModifyUnitEnergy','ModifyUnitShieldPoints','ModifyUnitResourceAmount','ModifyUnitHangerCount','PauseTimer','UnpauseTimer','Draw','SetAllianceStatus','DisableDebugMode','EnableDebugMode'];
const CHK_UNIT_CMD={11:'create',22:'kill',23:'kill',24:'remove',25:'remove',39:'move',44:'create',45:'deaths',46:'order',48:'give',49:'modify',50:'modify',51:'modify',52:'modify',53:'modify'};
const CHK_ORDER={0:'Move',1:'Patrol',2:'Attack'};
const CHK_BRIEF={1:'Wait',2:'PlayWAV',3:'TextMessage',4:'MissionObjectives',5:'ShowPortrait',6:'HidePortrait',7:'DisplaySpeakingPortrait',8:'Transmission'};
const CHK_BRIEF_TIMED={1:1,2:1,8:1};
function chkCommands(secs,d,dv,str,locName){
  const out=[]; const tr=secs['TRIG']; if(!tr)return out;
  const nt=(tr.len/2400)|0;
  for(let t=0;t<nt;t++){ const tb=tr.o+t*2400;
    for(let a=0;a<64;a++){ const ab=tb+320+a*32; const aid=d[ab+26]; const kind=CHK_UNIT_CMD[aid]; if(!kind)continue;
      const player=dv.getUint32(ab+16,true), second=dv.getUint32(ab+20,true), unit=dv.getUint16(ab+24,true), n27=d[ab+27];
      const r={trigger:t,action:CHK_TRIG_ACTIONS[aid]||('act'+aid),kind,player,unit,source_loc:dv.getUint32(ab,true)};
      r.source_loc_name=locName(r.source_loc);
      if(kind==='order'){ r.order=CHK_ORDER[n27]||('order'+n27); r.target_loc=second; r.target_loc_name=locName(second); }
      else if(kind==='move'){ r.dest_loc=second; r.dest_loc_name=locName(second); r.count=n27===0?'All':n27; }
      else if(kind==='give'){ r.to_player=second; r.count=n27===0?'All':n27; }
      else if(kind==='kill'||kind==='remove'){ r.count=n27===0?'All':n27; }
      else r.count=n27;
      out.push(r);
    } }
  return out;
}
function chkBriefing(secs,d,dv,str){
  const mb=secs['MBRF']; if(!mb)return [];
  const res=[]; const nt=(mb.len/2400)|0;
  for(let t=0;t<nt;t++){ const tb=mb.o+t*2400; let clock=0,cur=null; const events=[];
    for(let a=0;a<64;a++){ const ab=tb+320+a*32; const aid=d[ab+26]; if(!aid)continue;
      const ev={t_ms:clock,action:CHK_BRIEF[aid]||('act'+aid),action_id:aid};
      const time=dv.getUint32(ab+12,true);
      if(aid===5){ cur=dv.getUint16(ab+24,true); ev.portrait_unit=cur; }
      else if(aid===6){ ev.portrait_unit=cur; cur=null; }
      else if(aid===8){ ev.speaker_unit=cur; ev.text=str(dv.getUint32(ab+4,true)); ev.wav=str(dv.getUint32(ab+8,true)); ev.dur_ms=time; ev.end_ms=clock+time; }
      else if(aid===3||aid===4){ ev.text=str(dv.getUint32(ab+4,true)); if(time)ev.dur_ms=time; }
      else if(aid===2){ ev.wav=str(dv.getUint32(ab+8,true)); ev.dur_ms=time; }
      else if(aid===1){ ev.dur_ms=time; }
      events.push(ev); if(CHK_BRIEF_TIMED[aid])clock+=time;
    }
    const lines=events.filter(e=>e.action==='Transmission');
    res.push({events,n_lines:lines.length,total_ms:clock});
  }
  return res;
}
// Mission spec sheet — JS twin of tools/ai/mission_spec.py. Condition type @+15 in
// each 20-B condition (16 @ trigger+0); victory=action1, defeat=2, objectives=12/MBRF4,
// give_units=48, set_alliance=57, create_props=11. Ownership transfer surfaced so the
// engine can diff (e.g. Revolution = rescue OWNR + create, NOT alliance/give).
const CHK_COND={1:'CountdownTimer',2:'Command',3:'Bring',4:'Accumulate',5:'Kills',
 11:'Switch',12:'ElapsedTime',14:'Opponents',15:'Deaths',21:'Score',22:'Always',23:'Never'};
const CHK_CMP={0:'AtLeast',1:'AtMost',10:'Exactly'};
const CHK_PG={13:'CurrentPlayer',14:'Foes',15:'Allies',17:'AllPlayers',18:'Force1',
 19:'Force2',20:'Force3',21:'Force4'};
function chkPg(p){return CHK_PG[p]||('P'+(p+1));}
const CHK_QC=new Set(['Bring','Command','Accumulate','Kills','Deaths','Opponents','Score','CommandsTheMostAt','CommandsTheLeastAt']);
// full condition + action name tables (twin of chk.py COND_TYPES + mission_actions.TRIGGER_ACTIONS)
Object.assign(CHK_COND,{6:'CommandTheMost',7:'CommandsTheMostAt',8:'MostKills',9:'HighestScore',10:'MostResources',
 13:'Never?',16:'CommandTheLeast',17:'CommandsTheLeastAt',18:'LeastKills',19:'LowestScore',20:'LeastResources'});
const CHK_ACT=['NoAction','Victory','Defeat','PreserveTrigger','Wait','PauseGame','UnpauseGame','Transmission','PlayWAV',
 'DisplayTextMessage','CenterView','CreateUnitWithProperties','SetMissionObjectives','SetSwitch','SetCountdownTimer',
 'RunAIScript','RunAIScriptAtLocation','LeaderBoardControl','LeaderBoardControlAtLocation','LeaderBoardResources',
 'LeaderBoardKills','LeaderBoardPoints','KillUnit','KillUnitsAtLocation','RemoveUnit','RemoveUnitAtLocation','SetResources',
 'SetScore','MinimapPing','TalkingPortrait','MuteUnitSpeech','UnmuteUnitSpeech','LeaderboardComputerPlayers',
 'LeaderboardGoalControl','LeaderboardGoalControlAtLocation','LeaderboardGoalResources','LeaderboardGoalKills',
 'LeaderboardGoalPoints','MoveLocation','MoveUnit','LeaderboardGreed','SetNextScenario','SetDoodadState','SetInvincibility',
 'CreateUnit','SetDeaths','Order','Comment','GiveUnitstoPlayer','ModifyUnitHitPoints','ModifyUnitEnergy',
 'ModifyUnitShieldPoints','ModifyUnitResourceAmount','ModifyUnitHangerCount','PauseTimer','UnpauseTimer','Draw',
 'SetAllianceStatus','DisableDebugMode','EnableDebugMode'];
function chkActName(id){return CHK_ACT[id]||('act'+id);}
// Full resolved trigger list for a mission (IF/DO), twin of trigger_corpus.mission_triggers.
function chkAllTriggers(secs,d,dv,str,locName,un){
  const tr=secs['TRIG']; if(!tr)return []; const out=[]; const nt=(tr.len/2400)|0;
  const fourcc=ab=>String.fromCharCode(d[ab+20],d[ab+21],d[ab+22],d[ab+23]);
  for(let t=0;t<nt;t++){ const tb=tr.o+t*2400; const players=[];
    for(let p=0;p<27;p++) if(d[tb+2372+p]!==0)players.push(p);
    const C=[],A=[];
    for(let c=0;c<16;c++){const b=tb+c*20; const ct=d[b+15]; if(!ct)continue;
      const tn=CHK_COND[ct]||('cond'+ct);
      if(CHK_QC.has(tn)){const pl=dv.getUint32(b+4,true),qty=dv.getUint32(b+8,true),u=dv.getUint16(b+12,true),
        cmp=CHK_CMP[d[b+14]]||('c'+d[b+14]),lc=dv.getUint32(b,true);
        C.push(tn+'(P'+pl+' '+cmp+' '+qty+' '+un(u)+(lc?' @'+locName(lc):'')+')');}
      else if(tn==='CountdownTimer'||tn==='ElapsedTime')C.push(tn+'('+(CHK_CMP[d[b+14]]||'')+' '+dv.getUint32(b+8,true)+'s)');
      else C.push(tn);}
    for(let a=0;a<64;a++){const ab=tb+320+a*32; const aid=d[ab+26]; if(!aid)continue;
      const nm=chkActName(aid); const loc=dv.getUint32(ab,true),pl=dv.getUint32(ab+16,true),
        g2=dv.getUint32(ab+20,true),unit=dv.getUint16(ab+24,true),strn=dv.getUint32(ab+4,true),mod=d[ab+27];
      let det=[];
      if(aid===15||aid===16){det.push('script='+fourcc(ab)); if(pl)det.push('P'+pl); if(loc)det.push('@'+locName(loc));}
      else if(aid===48){det.push('P'+pl+'->P'+g2); det.push(un(unit)+' x'+(mod||'all')); if(loc)det.push('@'+locName(loc));}
      else if(aid===46){det.push('P'+pl+' '+un(unit)); det.push(CHK_ORDER[mod]||('order'+mod)); if(loc)det.push('@'+locName(loc));}
      else if(aid===7||aid===29){ if(unit)det.push('speaker='+un(unit)); if(strn)det.push('"'+str(strn).replace(/\n/g,' ').slice(0,40)+'"'); }
      else { if(pl)det.push('P'+pl); if(unit)det.push(un(unit)); if(loc)det.push('@'+locName(loc)); if(strn)det.push('"'+str(strn).replace(/\n/g,' ').slice(0,40)+'"'); }
      A.push(nm+(det.length?'('+det.join(' ')+')':''));}
    out.push({index:t,players,conditions:C,actions:A});
  }
  return out;
}
function chkSpec(secs,d,dv,str,locName){
  const tr=secs['TRIG']; const victory=[],defeat=[]; let give=[],alliance=0,createProps=0,createUnit=0;
  function conds(tb){ const out=[];   // unit ids kept raw; names resolved at render via CAI.uname
    for(let c=0;c<16;c++){const b=tb+c*20; const ct=d[b+15]; if(!ct)continue;
      const tn=CHK_COND[ct]||('cond'+ct);
      if(CHK_QC.has(tn)){const player=dv.getUint32(b+4,true),qty=dv.getUint32(b+8,true),
        unit=dv.getUint16(b+12,true),cmp=CHK_CMP[d[b+14]]||('c'+d[b+14]),loc=dv.getUint32(b,true);
        out.push({t:tn,player,qty,unit,cmp,loc});}
      else if(tn==='CountdownTimer'||tn==='ElapsedTime')out.push({t:tn,cmp:CHK_CMP[d[b+14]]||'',qty:dv.getUint32(b+8,true)});
      else out.push({t:tn}); }
    return out; }
  if(tr){ const nt=(tr.len/2400)|0;
    for(let t=0;t<nt;t++){ const tb=tr.o+t*2400;
      const players=[]; for(let p=0;p<27;p++) if(d[tb+2372+p]!==0)players.push(p);
      let hasV=false,hasD=false;
      for(let a=0;a<64;a++){ const ab=tb+320+a*32; const aid=d[ab+26];
        if(aid===1)hasV=true; else if(aid===2)hasD=true;
        else if(aid===48){const toP=dv.getUint32(ab+20,true);
          give.push({from:players.map(chkPg)[0]||'?',to:chkPg(toP),unit:dv.getUint16(ab+24,true),
            count:d[ab+27]||'all',loc:locName(dv.getUint32(ab,true))});}
        else if(aid===57)alliance++; else if(aid===11)createProps++; else if(aid===44)createUnit++;
      }
      if(hasV)victory.push({players:players.map(chkPg),conditions:conds(tb)});
      if(hasD)defeat.push({players:players.map(chkPg),conditions:conds(tb)});
    }
  }
  // objectives: TRIG action 12 + MBRF action 4
  const objs=[]; const seen=new Set();
  const scanObj=(sec,aid)=>{ if(!sec)return; const nt=(sec.len/2400)|0;
    for(let t=0;t<nt;t++){const tb=sec.o+t*2400; for(let a=0;a<64;a++){const ab=tb+320+a*32;
      if(d[ab+26]===aid){const s=str(dv.getUint32(ab+4,true)); if(s&&!seen.has(s)){seen.add(s);objs.push(s);}}}}};
  scanObj(secs['TRIG'],12); scanObj(secs['MBRF'],4);
  const rescue=[]; if(secs['OWNR'])for(let i=0;i<12;i++)if(d[secs['OWNR'].o+i]===3)rescue.push(i);
  return {objectives:objs,victory,defeat,give,alliance,createProps,createUnit,rescue};
}
function parseChk(buf,name){
  const d=new Uint8Array(buf), dv=new DataView(buf);
  const secs={}; let off=0;
  while(off+8<=d.length){
    const nm=String.fromCharCode(d[off],d[off+1],d[off+2],d[off+3]);
    const ln=dv.getInt32(off+4,true); off+=8; if(ln<0)break;
    secs[nm]={o:off,len:ln}; off+=ln;
  }
  // STR
  let strCount=0, strSec=secs['STR '];
  if(strSec&&strSec.len>=2)strCount=dv.getUint16(strSec.o,true);
  const str=i=>{ if(!strSec||i<1||i>strCount)return '';
    const o=dv.getUint16(strSec.o+2+(i-1)*2,true)+strSec.o; let e=d.indexOf(0,o);
    if(e<0)e=strSec.o+strSec.len; let s=''; for(let k=o;k<e;k++)s+=String.fromCharCode(d[k]); return s; };
  // MRGN locations
  const locs=[]; const mr=secs['MRGN'];
  if(mr){ const nl=(mr.len/20)|0; for(let i=0;i<nl;i++){ const b=mr.o+i*20;
    locs.push({i:i+1,name:str(dv.getUint16(b+16,true))}); } }
  const locName=i=>(i>=1&&i<=locs.length)?locs[i-1].name:'';
  const own=[],side=[]; if(secs['OWNR'])for(let i=0;i<12;i++)own.push(d[secs['OWNR'].o+i]);
  if(secs['SIDE'])for(let i=0;i<12;i++)side.push(d[secs['SIDE'].o+i]);
  // TRIG: 2400-B triggers; actions[64]x32 @320; action id @+26; players @+2372
  const links=[]; const tr=secs['TRIG'];
  if(tr){ const nt=(tr.len/2400)|0;
    for(let t=0;t<nt;t++){ const tb=tr.o+t*2400;
      const players=[]; for(let p=0;p<8;p++) if(d[tb+2372+p]!==0)players.push(p);
      for(let a=0;a<64;a++){ const ab=tb+320+a*32; const aid=d[ab+26];
        if(aid===15||aid===16){
          const loc=dv.getUint32(ab,true);
          const fcc=String.fromCharCode(d[ab+20],d[ab+21],d[ab+22],d[ab+23]);
          links.push({trigger:t,players,action:aid===16?'run@loc':'run',
            script:fcc,loc,locName:locName(loc)});
        }
      }
    }
  }
  const commands=chkCommands(secs,d,dv,str,locName);
  const briefing=chkBriefing(secs,d,dv,str);
  // UNIT — pre-placed units (36-B records: unitId@8, owner@16)
  const placed=[]; const uSec=secs['UNIT'];
  if(uSec){ const nu=(uSec.len/36)|0; for(let i=0;i<nu;i++){ const o=uSec.o+i*36;
    placed.push({unit:dv.getUint16(o+8,true),owner:d[o+16]}); } }
  // SPEC SHEET: victory/defeat conditions + ownership transfer + objectives (twin of mission_spec.py)
  const spec=chkSpec(secs,d,dv,str,locName);
  // FULL trigger corpus (IF/DO), twin of trigger_corpus.py — names via CAI.uname if loaded
  const _un=(typeof CAI!=='undefined'&&CAI.uname)?CAI.uname:(u=>'unit '+u);
  const triggersFull=chkAllTriggers(secs,d,dv,str,locName,_un);
  return {chk:true,fmtLabel:name.split(/[\\/]/).pop(),name,secCount:Object.keys(secs).length,
    strCount,locs:locs.length,triggers:tr?((tr.len/2400)|0):0,links,own,side,commands,briefing,placed,spec,triggersFull};
}
function renderChkHtml(f){
  const SIDE={0:'Zerg',1:'Terran',2:'Protoss',4:'Neutral',7:'Inactive'};
  let h='<div class="mk">// '+f.fmtLabel+' — CHK: '+f.secCount+' sections, '+f.triggers+' triggers, '
    +f.locs+' locations, <b>'+f.links.length+'</b> AI-script actions</div>';
  if(!f.links.length){ h+='<div style="max-width:520px;color:var(--ink-dim)">This map has no "Run AI Script" triggers.</div>'; return h; }
  // usage summary
  const byScript={}; for(const l of f.links){(byScript[l.script]=byScript[l.script]||[]).push(l);}
  h+='<div style="max-width:820px;max-height:72vh;overflow:auto;text-align:left;font:12px/1.6 ui-monospace,Consolas,monospace">';
  h+='<table style="border-collapse:collapse;width:100%"><thead><tr style="color:var(--teal);border-bottom:1px solid var(--edge)">'
    +'<th style="text-align:left;padding:3px 8px">Player</th><th style="text-align:left;padding:3px 8px">Race</th>'
    +'<th style="text-align:left;padding:3px 8px">Script</th><th style="text-align:left;padding:3px 8px">Action</th>'
    +'<th style="text-align:left;padding:3px 8px">Location</th></tr></thead><tbody>';
  for(const l of f.links){
    const pl=l.players.length?l.players.join(','):'—';
    const race=l.players.length?(SIDE[f.side[l.players[0]]]||'?'):'';
    h+='<tr style="border-bottom:1px solid var(--edge)">'
      +'<td style="padding:3px 8px">P'+pl+'</td><td style="padding:3px 8px;color:var(--ink-dim)">'+race+'</td>'
      +'<td style="padding:3px 8px;color:#c8b878">'+l.script+'</td>'
      +'<td style="padding:3px 8px;color:var(--ink-dim)">'+l.action+'</td>'
      +'<td style="padding:3px 8px">'+(l.locName||(l.loc?('loc '+l.loc):'—'))+'</td></tr>';
  }
  h+='</tbody></table>';
  h+='<div class="mk" style="margin-top:10px">// Script usage in this mission</div>';
  for(const sid in byScript){ h+='<div><span style="color:#c8b878">'+sid+'</span> <span style="color:var(--ink-dim)">— '
    +byScript[sid].length+'× ('+[...new Set(byScript[sid].map(l=>'P'+l.players.join(',')))].join(' ')+')</span></div>'; }
  h+='</div>';
  return h;
}

/* ---- parse dispatch ---- */
async function openBuffer(name,buf){
  const d=new Uint8Array(buf), dv=new DataView(buf);
  const ext=extOf(name);
  if(ext==='ai') return parseAiScripts(buf,name);
  if(ext==='chk') return parseChk(buf,name);
  if(ext==='pcx') return parsePCX(buf);
  if(ext==='smk') return parseSMK(buf);
  if(ext==='webm'||(d[0]===0x1a&&d[1]===0x45&&d[2]===0xdf&&d[3]===0xa3)) return parseWebM(buf);
  if(ext==='wav'||(d[0]===0x52&&d[1]===0x49&&d[2]===0x46&&d[3]===0x46)||
     (d[0]===0x4F&&d[1]===0x67&&d[2]===0x67&&d[3]===0x53)) return parseAudio(buf,name);
  // ANIM magic
  if(d[0]===0x41&&d[1]===0x4E&&d[2]===0x49&&d[3]===0x4D){ const s=parseAnim(buf); return s; }
  // standalone .dds (not a dds.grp container) — must precede the GRP guesses,
  // otherwise its 'DDS ' magic falls through and gets decoded as a classic GRP
  if(d[0]===0x44&&d[1]===0x44&&d[2]===0x53&&d[3]===0x20){
    const img=ddsToImageData(buf,0);
    return {type:'dds',frameCount:1,maxW:img.width,maxH:img.height,
      frames:[{x:0,y:0,w:img.width,h:img.height,_img:img}],
      fmtLabel:'DDS '+img.width+'×'+img.height};
  }
  // GRP: dds vs classic
  const first=dv.getUint32(0,true);
  if(first===buf.byteLength){ const s=parseDdsGRP(buf); precomputeDds(s,buf); return s; }
  // classic
  return parseClassicGRP(buf);
}
function precomputeDds(s,buf){ for(const fr of s.frames){ fr._img=ddsToImageData(buf,fr.ddsOff); } }

/* ---- MPQ expand ---- */
async function toggleMpq(f,row){
  if(f._children){ f._children=null; renderTree(); return; }
  showLoad('Atveriamas archyvas '+f.name+'…');
  try{
    const buf=await f.file.arrayBuffer();
    const mpq=await MPQ.open(buf);
    S.lastMpq=mpq;   // lets the palette panel pull ticon.pcx / *.wpe straight out
    // merge external listfile: add any name that actually resolves in this archive
    let names=mpq.names.slice(); let addedExt=0;
    if(S.externalListfile){ const seen=new Set(names.map(n=>n.toLowerCase()));
      for(const nm of S.externalListfile){ if(seen.has(nm.toLowerCase()))continue;
        if(mpq.find(nm)>=0){ names.push(nm); seen.add(nm.toLowerCase()); addedExt++; } } }
    if(!names.length){ hideLoad();
      showInfo(`<div class="mk">// MPQ WITHOUT LISTFILE</div><div>${f.name}</div><div>Archive opened (${mpq.hashTableSize} hash entries), but no matching names were found inside it or in the loaded listfile. Load a proper StarCraft listfile (the "Open files" button → .txt).</div>`);
      setStatus('MPQ without listfile: <b>'+f.name+'</b>',true); return; }
    // build a virtual sub-tree from names
    const vroot=newFolder(f.name);
    for(const nm of names){
      const parts=nm.split('\\').join('/').split('/');
      let node=vroot;
      for(let i=0;i<parts.length-1;i++){const seg=parts[i];if(!node.folders.has(seg))node.folders.set(seg,newFolder(seg));node=node.folders.get(seg);}
      const leaf=parts[parts.length-1];
      node.files.push({kind:'file',name:leaf,ext:extOf(leaf),mpq,mpqPath:nm,path:f.path+'::'+nm});
    }
    f._children=vroot;
    hideLoad(); renderTree();
    setStatus('Archive: <b>'+f.name+'</b> — '+names.length+' files'+(addedExt?' (+'+addedExt+' from external listfile)':'')+' (v'+mpq.formatVer+')');
  }catch(e){ hideLoad(); console.error(e);
    showInfo(`<div class="mk">// MPQ ERROR</div><div>${f.name}</div><div style="color:var(--red)">${e.message}</div>`);
    setStatus('MPQ error: '+e.message,true);
  }
}

/* ---- palette / frames ---- */
function resolvePalette(file){
  if(file.type!=='classic')return null;
  if(S.palMode==='gray')return grayPalette();
  if(S.palMode==='green')return greenPalette();
  if(S.palMode==='custom'&&S.customPal)return S.customPal;
  return (file.used&&file.used.size<=24)?autoPalette(file.used):grayPalette();
}
function frameImage(file,i){
  if(file.type==='classic'){
    const key=file._id+'#'+i+'#'+S.palMode+(S.customPal?'C':'');
    if(S.frameCache.has(key))return S.frameCache.get(key);
    const img=classicToImageData(file.frames[i],resolvePalette(file));
    S.frameCache.set(key,img);return img;
  }
  return file.frames[i]._img;
}

/* ---- set active + render ---- */
let _idc=0;
function setActive(sprite){
  sprite._id=sprite._id||('s'+(++_idc));
  S.active=sprite; S.sel=0; stopAnim();
  render();
}
function render(){
  const f=S.active;
  $('#emptyState').style.display=f?'none':'flex';
  $('#infoMsg').style.display='none';
  $('#ctlPanel').style.display=f?'block':'none';
  ['gridView','detailView','animView','videoView','audioView'].forEach(id=>$('#'+id).style.display='none');
  if(!f)return;
  if(f.audio){
    $('#ctlPanel').style.display='none';
    $('#audioView').style.display='flex';
    if(S.audUrl) URL.revokeObjectURL(S.audUrl);
    S.audUrl=URL.createObjectURL(new Blob([f.buf],{type:f.mime}));
    $('#audEl').src=S.audUrl;
    $('#audFmt').textContent=f.fmtLabel;
    const rows=[['Codec',f.codec],['Size',(f.bytes/1024).toFixed(1)+' KB']];
    if(f.rate) rows.push(['Rate',f.rate+' Hz'],['Bits',f.bits],['Channels',f.ch],
                         ['Duration',f.dur?f.dur.toFixed(2)+' s':'—']);
    $('#audTele').innerHTML=rows.map(r=>`<div class="k">${r[0]}</div><div class="v">${r[1]}</div>`).join('');
    drawWaveform(f);
    setStatus('Loaded — '+f.fmtLabel);
    return;
  }
  if(f.video){                                   // WebM: the browser decodes it
    $('#ctlPanel').style.display='none';
    $('#videoView').style.display='flex';
    const el=$('#vidEl');
    if(S.vidUrl) URL.revokeObjectURL(S.vidUrl);
    S.vidUrl=URL.createObjectURL(new Blob([f.buf],{type:'video/webm'}));
    el.src=S.vidUrl;
    el.style.width=(f.width*S.vidZoom)+'px'; el.style.height=(f.height*S.vidZoom)+'px';
    $('#vidFmt').textContent=f.fmtLabel;
    const rows=[['Codec',f.codec],['Dimensions',f.width+' × '+f.height],
      ['Blocks (frames)',f.frames],
      ['Duration',f.duration?f.duration.toFixed(3)+' s':'—'],
      ['FPS',f.fps?(Math.round(f.fps*100)/100):'—'],
      ['Muxer',f.muxer||'—']];
    $('#vidTele').innerHTML=rows.map(r=>`<div class="k">${r[0]}</div><div class="v">${r[1]}</div>`).join('');
    setStatus('Loaded — '+f.fmtLabel+' · decoded by the browser');
    return;
  }
  // AI scripts (aiscript.bin / bwscript.bin) — disassembly listing
  if(f.ai){
    $('#ctlPanel').style.display='none';
    showInfo(renderAiHtml(f));
    setStatus('AI: <b>'+f.scripts.length+'</b> scripts with code — '+f.source);
    return;
  }
  // CHK scenario — campaign AI mission linkage
  if(f.chk){
    $('#ctlPanel').style.display='none';
    showInfo(renderChkHtml(f));
    setStatus('CHK: <b>'+f.links.length+'</b> AI-script actions — '+f.fmtLabel);
    return;
  }
  // info-only types (SMK)
  if(f.info){
    $('#ctlPanel').style.display='none';
    showInfo(`<div class="mk">// ${f.fmtLabel}</div>
      <div class="tele" style="max-width:280px"><div class="k">Dimensions</div><div class="v">${f.width}×${f.height}</div>
      <div class="k">Frames</div><div class="v">${f.frames}</div><div class="k">FPS</div><div class="v">${f.fps}</div></div>
      <div style="max-width:460px">Smacker video frame decoding (Huffman trees + block predictors) — a separate codec, not yet implemented. Header metadata above.</div>`);
    setStatus('SMK: <b>'+f.width+'×'+f.height+'</b>, '+f.frames+' frames.');
    return;
  }
  $('#palCtl').style.display=(f.type==='classic')?'block':'none';
  const showLayers=f.type==='anim'&&f.layers&&f.layers.length>1;
  $('#layerCtl').style.display=showLayers?'block':'none';
  if(showLayers){const sel=$('#animLayer');
    const canComposite=f.layers.includes('diffuse')&&f.layers.includes('teamcolor');
    const nOpts=f.layers.length+(canComposite?1:0);
    if(sel.options.length!==nOpts||sel.dataset.for!==f._id){
      let html=f.layers.map((n,i)=>`<option value="${i}">${n}</option>`).join('');
      if(canComposite)html+=`<option value="composite">★ Composite (diffuse+teamcolor+emissive)</option>`;
      sel.innerHTML=html;sel.dataset.for=f._id;}
    sel.value=f.activeLayer===undefined?0:f.activeLayer;}
  setStatus('Loaded — '+f.fmtLabel);
  if(S.tab==='grid')buildGrid(f); else if(S.tab==='detail')buildDetail(f); else buildAnim(f);
}

/* ---- render helpers (reused) ---- */
function bgStyle(el){
  if(S.bg==='checker'){el.style.backgroundColor='#0d1420';
    el.style.backgroundImage='linear-gradient(45deg,#1a2434 25%,transparent 25%),linear-gradient(-45deg,#1a2434 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#1a2434 75%),linear-gradient(-45deg,transparent 75%,#1a2434 75%)';
    el.style.backgroundSize='16px 16px';el.style.backgroundPosition='0 0,0 8px,8px -8px,-8px 0';}
  else{el.style.backgroundImage='none';el.style.backgroundColor=S.bg;}
}
function drawScaled(canvas,img,scale){
  canvas.width=img.width*scale;canvas.height=img.height*scale;
  const ctx=canvas.getContext('2d');ctx.imageSmoothingEnabled=false;
  const t=document.createElement('canvas');t.width=img.width;t.height=img.height;t.getContext('2d').putImageData(img,0,0);
  ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(t,0,0,canvas.width,canvas.height);
}
function buildGrid(f){const g=$('#gridView');g.style.display='flex';g.innerHTML='';
  f.frames.forEach((fr,i)=>{const cell=document.createElement('div');cell.className='cell'+(i===S.sel?' on':'');bgStyle(cell);
    const cv=document.createElement('canvas');drawScaled(cv,frameImage(f,i),Math.min(S.zoom,4));
    const ix=document.createElement('div');ix.className='ix';ix.textContent=i;cell.append(cv,ix);
    cell.onclick=()=>{S.sel=i;S.tab='detail';setTab();};g.appendChild(cell);});}
function buildDetail(f){const v=$('#detailView');v.style.display='flex';
  const i=Math.min(S.sel,f.frameCount-1);S.sel=i;const fr=f.frames[i];
  const cv=$('#detCanvas');bgStyle(cv.parentElement);drawScaled(cv,frameImage(f,i),S.zoom);
  $('#detFmt').textContent=f.fmtLabel;
  const rows=[['Frame',i+' / '+(f.frameCount-1)],['Dimensions',fr.w+' × '+fr.h],['Offset X/Y',(fr.x||0)+', '+(fr.y||0)],['Canvas',f.maxW+' × '+f.maxH]];
  if(f.type==='anim')rows.push(['Layer',(f.layers&&f.layers[f.activeLayer||0])||'diffuse']);
  if(f.type==='classic')rows.push(['Palette',S.palMode]);
  $('#detTele').innerHTML=rows.map(r=>`<div class="k">${r[0]}</div><div class="v">${r[1]}</div>`).join('');}
function compositeFrame(f,i){const cv=document.createElement('canvas');cv.width=f.maxW;cv.height=f.maxH;
  const ctx=cv.getContext('2d');const img=frameImage(f,i);
  const t=document.createElement('canvas');t.width=img.width;t.height=img.height;t.getContext('2d').putImageData(img,0,0);
  const ox=S.align?(f.frames[i].x||0):Math.floor((f.maxW-img.width)/2), oy=S.align?(f.frames[i].y||0):Math.floor((f.maxH-img.height)/2);
  ctx.drawImage(t,ox,oy);return cv;}
function buildAnim(f){const v=$('#animView');v.style.display='flex';$('#animFmt').textContent=f.fmtLabel;
  $('#animTot').textContent=f.frameCount-1;const sc=$('#scrub');sc.max=f.frameCount-1;sc.value=Math.min(S.sel,f.frameCount-1);
  drawAnim(f,+sc.value);}
function drawAnim(f,i){S.sel=i;$('#animIx').textContent=i;$('#scrub').value=i;
  const src=compositeFrame(f,i);const cv=$('#animCanvas');bgStyle(cv.parentElement);
  const s=S.zoom;cv.width=src.width*s;cv.height=src.height*s;const ctx=cv.getContext('2d');ctx.imageSmoothingEnabled=false;
  ctx.clearRect(0,0,cv.width,cv.height);ctx.drawImage(src,0,0,cv.width,cv.height);}
function stopAnim(){S.playing=false;if(S.animT){clearInterval(S.animT);S.animT=null;}const b=$('#playBtn');if(b)b.textContent='▶ Play';}
function togglePlay(){const f=S.active;if(!f||!f.frameCount)return;if(S.playing){stopAnim();return;}
  S.playing=true;$('#playBtn').textContent='❚❚ Pause';let i=+$('#scrub').value;
  S.animT=setInterval(()=>{i=(i+1)%f.frameCount;drawAnim(f,i);},1000/S.fps);}
function dl(url,name){const a=document.createElement('a');a.href=url;a.download=name;a.click();}
function exportFrame(){const f=S.active;if(!f)return;const img=frameImage(f,S.sel);
  const cv=document.createElement('canvas');cv.width=img.width;cv.height=img.height;cv.getContext('2d').putImageData(img,0,0);
  dl(cv.toDataURL('image/png'),'frame'+S.sel+'.png');}
function exportSheet(){const f=S.active;if(!f)return;const cols=Math.ceil(Math.sqrt(f.frameCount)),rows=Math.ceil(f.frameCount/cols);
  const cw=f.maxW,ch=f.maxH,cv=document.createElement('canvas');cv.width=cols*cw;cv.height=rows*ch;const ctx=cv.getContext('2d');
  f.frames.forEach((fr,i)=>ctx.drawImage(compositeFrame(f,i),(i%cols)*cw,Math.floor(i/cols)*ch));
  dl(cv.toDataURL('image/png'),'sheet.png');setStatus('Sprite sheet eksportuotas.');}
// GRPI v1 — expanded palette indices, no colour applied. Byte-for-byte the
// same layout grp2png --dump-idx writes.
function exportGrpi(){
  const f=S.active;
  if(!f||f.type!=='classic'){setStatus('.grpi only works for a classic GRP (indices).',true);return;}
  let total=16; for(const fr of f.frames) total+=12+fr.w*fr.h;
  const buf=new ArrayBuffer(total), dv=new DataView(buf), out=new Uint8Array(buf);
  out[0]=71;out[1]=82;out[2]=80;out[3]=73;                 // 'GRPI'
  dv.setUint16(4,1,true); dv.setUint16(6,f.frames.length,true);
  dv.setUint16(8,f.maxW,true); dv.setUint16(10,f.maxH,true); dv.setUint32(12,0,true);
  let o=16;
  for(const fr of f.frames){
    dv.setUint16(o,fr.x,true); dv.setUint16(o+2,fr.y,true);
    dv.setUint16(o+4,fr.w,true); dv.setUint16(o+6,fr.h,true);
    dv.setUint16(o+8,fr.flags||0,true); dv.setUint16(o+10,0,true);
    o+=12; out.set(fr.idx,o); o+=fr.w*fr.h;
  }
  const url=URL.createObjectURL(new Blob([buf]));
  dl(url,(S.activePath||'sprite').split(/[\\/]/).pop().replace(/\.grp$/i,'')+'.grpi');
  URL.revokeObjectURL(url);
  setStatus('Exported <b>.grpi</b> — '+f.frames.length+' frames, '+total+' B (indices, no colour).');
}

async function paletteFromMpq(path){
  if(!path) return;
  if(!S.lastMpq){setStatus('Open a .mpq archive first (click it in the tree).',true);return;}
  try{
    const bytes=await S.lastMpq.readFile(path);
    const pal=parsePaletteFile(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),path);
    if(!pal){setStatus('Could not recognize palette: '+path,true);return;}
    S.customPal=pal; S.palMode='custom'; $('#palMode').value='custom';
    $('#palName').textContent=path.split('\\').pop();
    S.frameCache.clear(); render();
    setStatus('Authentic palette from MPQ: <b>'+path+'</b>');
  }catch(e){setStatus('Palette not found in archive: '+path+' ('+e.message+')',true);}
}

// Waveform straight from the PCM samples — a broken decode looks like noise,
// speech looks like speech, so this doubles as a correctness check.
function drawWaveform(f){
  const cv=$('#wavCanvas'), W=420, H=110;
  cv.width=W; cv.height=H;
  const ctx=cv.getContext('2d');
  ctx.fillStyle='#0b1220'; ctx.fillRect(0,0,W,H);
  ctx.strokeStyle='#1d3a4a'; ctx.beginPath(); ctx.moveTo(0,H/2); ctx.lineTo(W,H/2); ctx.stroke();
  if(f.codec!=='PCM'||f.bits!==16){ ctx.fillStyle='#7f93a8'; ctx.font='11px monospace';
    ctx.fillText('(waveform shown only for 16-bit PCM)',12,H/2-8); return; }
  const d=new Uint8Array(f.buf), dv=new DataView(f.buf);
  let p=12, off=0, len=0;
  while(p+8<=d.length){ const cid=String.fromCharCode(d[p],d[p+1],d[p+2],d[p+3]);
    const sz=dv.getUint32(p+4,true); p+=8;
    if(cid==='data'){ off=p; len=sz; break; } p+=sz+(sz&1); }
  if(!len) return;
  const n=(len/2)|0, step=Math.max(1,(n/W)|0);
  ctx.strokeStyle='#4fe3c4'; ctx.beginPath();
  for(let x=0;x<W;x++){
    let lo=32767, hi=-32768;
    for(let k=0;k<step;k++){
      const i=x*step+k; if(i>=n) break;
      const v=dv.getInt16(off+i*2,true);
      if(v<lo)lo=v; if(v>hi)hi=v;
    }
    ctx.moveTo(x+.5,H/2-(hi/32768)*(H/2-4));
    ctx.lineTo(x+.5,H/2-(lo/32768)*(H/2-4));
  }
  ctx.stroke();
}

// Real decoded pixels out of a WebM without writing a codec: seek the <video>
// frame by frame and read it back through a canvas.
async function exportWebmFrames(){
  const f=S.active; if(!f||!f.video) return;
  const el=$('#vidEl'), msg=$('#vidExportMsg');
  const n=Math.max(1,f.frames||1), dur=f.duration||(n/10);
  const cols=Math.min(n,10), rows=Math.ceil(n/cols);
  const sheet=document.createElement('canvas');
  sheet.width=f.width*cols; sheet.height=f.height*rows;
  const sctx=sheet.getContext('2d');
  const tmp=document.createElement('canvas'); tmp.width=f.width; tmp.height=f.height;
  const tctx=tmp.getContext('2d');
  const wasLoop=el.loop; el.loop=false; el.pause();
  try{
    for(let i=0;i<n;i++){
      msg.textContent='frame '+(i+1)+' / '+n+'…';
      const t=Math.min(dur-1e-4,(i+0.5)*dur/n);
      await new Promise(res=>{ const h=()=>{el.removeEventListener('seeked',h);res();};
        el.addEventListener('seeked',h); el.currentTime=t; });
      tctx.drawImage(el,0,0,f.width,f.height);
      sctx.drawImage(tmp,(i%cols)*f.width,((i/cols)|0)*f.height);
    }
    const url=sheet.toDataURL('image/png');
    dl(url,(S.activePath||'video').split(/[\\/]/).pop().replace(/\.webm$/i,'')+'_frames.png');
    msg.innerHTML='<span style="color:var(--teal)">✓ '+n+' frames, '+sheet.width+'×'+sheet.height+'</span>';
  }catch(e){ msg.innerHTML='<span style="color:var(--red)">'+e.message+'</span>'; }
  finally{ el.loop=wasLoop; el.play().catch(()=>{}); }
}

function setTab(){$$('.tab').forEach(t=>t.classList.toggle('on',t.dataset.tab===S.tab));if(S.tab!=='anim')stopAnim();render();}

/* ---- inputs ---- */
$('#dirInput').addEventListener('change',e=>{
  const files=[...e.target.files]; if(!files.length)return;
  S.root=buildTreeFromFiles(files); S.totalFiles=countFiles(S.root); S.expanded.clear();
  // auto-expand top level
  for(const [,c] of S.root.folders){ S.expanded.add('/'+c.name); }
  renderTree(); setStatus('Folder loaded — <b>'+S.totalFiles+'</b> valid files.');
});
$('#cascInput').addEventListener('change',e=>{const files=[...e.target.files];if(files.length)cascFolder(files);});
async function loadListfile(file){
  const txt=await file.text();
  S.externalListfile=txt.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
  setStatus('External listfile loaded: <b>'+S.externalListfile.length+'</b> names. Open a .mpq to apply it.');
}
$('#fileInput').addEventListener('change',e=>{
  const files=[...e.target.files]; if(!files.length)return;
  const lists=files.filter(f=>/\.(txt|lst)$/i.test(f.name)), assets=files.filter(f=>!/\.(txt|lst)$/i.test(f.name));
  if(lists.length){ loadListfile(lists[0]); }
  if(assets.length){ S.root=S.root||newFolder(''); for(const f of assets){ S.root.files.push({kind:'file',name:f.name,ext:extOf(f.name),file:f,path:'@/'+f.name}); }
    S.totalFiles=countFiles(S.root); renderTree(); setStatus(assets.length+' files loaded.'); }
});
$('#filter').addEventListener('input',e=>{S.filter=e.target.value.toLowerCase().trim();renderTree();});
$('#expandAll').addEventListener('click',()=>{
  if(S.expanded.size){S.expanded.clear();}else{ (function walk(node,pfx){for(const[,c]of node.folders){const k=pfx+'/'+c.name;S.expanded.add(k);walk(c,k);}})(S.root,''); }
  renderTree();});
$('#palMode').addEventListener('change',e=>{S.palMode=e.target.value;S.frameCache.clear();render();});
$('#palInput').addEventListener('change',e=>{const f=e.target.files[0];if(!f)return;const r=new FileReader();
  r.onload=()=>{const pal=parsePaletteFile(r.result,f.name);if(pal){S.customPal=pal;S.palMode='custom';$('#palMode').value='custom';$('#palName').textContent=f.name;S.frameCache.clear();render();}
  else setStatus('Could not recognize palette: '+f.name,true);};r.readAsArrayBuffer(f);});
$('#animLayer').addEventListener('change',e=>{const f=S.active;if(f&&f.type==='anim'){const v=e.target.value;sliceAnimFrames(f,v==='composite'?'composite':+v);render();}});
$('#zoom').addEventListener('input',e=>{S.zoom=+e.target.value;$('#zoomVal').textContent=S.zoom+'×';render();});
$('#vidZoom').addEventListener('input',e=>{S.vidZoom=+e.target.value;$('#vidZoomV').textContent=S.vidZoom+'×';
  const f=S.active,el=$('#vidEl'); if(f&&f.video){el.style.width=(f.width*S.vidZoom)+'px';el.style.height=(f.height*S.vidZoom)+'px';}});
$('#fps').addEventListener('input',e=>{S.fps=+e.target.value;$('#fpsVal').textContent=S.fps;if(S.playing){stopAnim();togglePlay();}});
$('#scrub').addEventListener('input',e=>{const f=S.active;if(f)drawAnim(f,+e.target.value);});
$('#alignChk').addEventListener('change',e=>{S.align=e.target.checked;const f=S.active;if(f)drawAnim(f,+$('#scrub').value);});
$('#playBtn').addEventListener('click',togglePlay);
$('#expFrame').addEventListener('click',exportFrame);
$('#expSheet').addEventListener('click',exportSheet);
$('#expGrpi').addEventListener('click',exportGrpi);
$('#vidExport').addEventListener('click',exportWebmFrames);
$('#palFromMpq').addEventListener('change',e=>{const v=e.target.value;e.target.selectedIndex=0;paletteFromMpq(v);});
$$('.tab').forEach(t=>t.addEventListener('click',()=>{S.tab=t.dataset.tab;setTab();}));
$$('#bgSw .sw').forEach(sw=>{ if(sw.dataset.bg==='checker'){bgStyle(sw);} 
  sw.addEventListener('click',()=>{$$('#bgSw .sw').forEach(s=>s.classList.remove('on'));sw.classList.add('on');S.bg=sw.dataset.bg;render();});});
window.addEventListener('keydown',e=>{const f=S.active;if(!f||!f.frameCount)return;
  if(e.key==='ArrowRight'){S.sel=(S.sel+1)%f.frameCount;e.preventDefault();render();}
  if(e.key==='ArrowLeft'){S.sel=(S.sel-1+f.frameCount)%f.frameCount;e.preventDefault();render();}
  if(e.key===' '&&S.tab==='anim'){e.preventDefault();togglePlay();}});
// drag & drop (files or folders via items)
const drop=$('#drop');let dc=0;
window.addEventListener('dragenter',e=>{e.preventDefault();dc++;drop.classList.add('on');});
window.addEventListener('dragover',e=>e.preventDefault());
window.addEventListener('dragleave',e=>{dc--;if(dc<=0){dc=0;drop.classList.remove('on');}});
window.addEventListener('drop',e=>{e.preventDefault();dc=0;drop.classList.remove('on');
  const fl=[...e.dataTransfer.files]; if(!fl.length)return;
  const lists=fl.filter(f=>/\.(txt|lst)$/i.test(f.name)),assets=fl.filter(f=>!/\.(txt|lst)$/i.test(f.name));
  if(lists.length)loadListfile(lists[0]);
  if(assets.length){S.root=S.root||newFolder('');for(const f of assets){S.root.files.push({kind:'file',name:f.name,ext:extOf(f.name),file:f,path:'@/'+f.name});}
    S.totalFiles=countFiles(S.root);renderTree();setStatus(assets.length+' files loaded (drag&drop).');}});

$('#ekeyExtract').addEventListener('click',async()=>{
  const st=$('#ekeyStatus');
  let hex=($('#ekeyIn').value||'').toLowerCase().replace(/[^0-9a-f]/g,'');
  if(hex.length<18){st.textContent='EKey too short (needs ≥9 bytes).';return;}
  if(!S.cascIndex){st.textContent='Load a CASC folder first.';return;}
  const entry=S.cascIndex.get(hex.slice(0,18));
  if(!entry){st.innerHTML='<span style="color:var(--red)">EKey not found in the index.</span>';return;}
  if(!S.cascData.has(entry.fileIdx)){st.innerHTML='<span style="color:var(--red)">needs data.'+String(entry.fileIdx).padStart(3,'0')+' (not in the folder)</span>';return;}
  st.textContent='extracting from data.'+String(entry.fileIdx).padStart(3,'0')+'…';
  try{
    const buf=await readCascBlob(entry);
    const blob=new Blob([buf]);const url=URL.createObjectURL(blob);
    const a=document.createElement('a');a.href=url;a.download=hex.slice(0,16)+'.bin';a.click();URL.revokeObjectURL(url);
    st.innerHTML='<span style="color:var(--teal)">✓ '+buf.byteLength+' B downloaded</span>';
  }catch(e){st.innerHTML='<span style="color:var(--red)">'+e.message+'</span>';}
});
/* ========================= wireframe colour tester =========================
   Mirrors the engine's model instead of inventing one: a wireframe is not
   "layers" in the abstract, it is palette-index families, and the HD art is
   the same families expressed as mask cells.
     SD  wirefram.grp  : 208..211 / 216..219 damage bands, 192/193 structure
     HD  wirefram.dds.grp : frame = strip of square cells; 0..N-2 are white
                            masks (matching the SD families 1:1), N-1 is the
                            finished colour art.
   Colours are derived, not stored: the Zerg bands slide over a 9-entry ramp
   with HP (top = 4 + hp*4/100), the Protoss shield picks ramp[hi/2].
   Defaults are the authentic game\twire.pcx values, measured from the file. */

// An MPQ CHAIN, like Python's MpqChain: no single BW archive holds everything —
// original campaigns live in StarCraft.mpq, Brood War ones in BroodWar.mpq, and
// aiscript.bin/*.dat/*.tbl in StarDat/BrooDat/patch_rt. So a lookup must try
// every .mpq the user loaded, not just the last one clicked. Archives are opened
// lazily (the big data MPQs are ~600 MB) and cached.
function collectMpqNodes(){
  const out=[]; if(!S.root) return out;
  (function walk(f){ for(const file of f.files) if(file.ext==='mpq'&&file.file) out.push(file);
    for(const [,c] of f.folders) walk(c); })(S.root);
  return out;
}
function mpqPriority(name){ name=(name||'').toLowerCase();
  if(name.startsWith('patch_rt'))return 0; if(name.startsWith('patch'))return 1;
  if(name.startsWith('broodat'))return 2; if(name.startsWith('stardat'))return 3;
  return 4; }   // BroodWar.mpq / StarCraft.mpq (campaign data) tried last
async function openMpqNode(node){
  if(!S.mpqOpened)S.mpqOpened=new Map();
  if(S.mpqOpened.has(node.name))return S.mpqOpened.get(node.name);
  const m=await MPQ.open(await node.file.arrayBuffer());
  S.mpqOpened.set(node.name,m); return m;
}
async function mpqChainRead(bs){       // bs = backslash path; returns ArrayBuffer or null
  const tryRead=async m=>{ if(!m||m.find(bs)<0)return null;
    try{ const b=await m.readFile(bs); return b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength); }catch(e){return null;} };
  const first=await tryRead(S.lastMpq); if(first)return first;
  const nodes=collectMpqNodes().sort((a,b)=>mpqPriority(a.name)-mpqPriority(b.name));
  for(const node of nodes){
    let m; try{ m=await openMpqNode(node); }catch(e){continue;}
    if(m===S.lastMpq)continue;
    const r=await tryRead(m); if(r)return r;
  }
  return null;
}
async function readGameFile(path){
  const bs=path.replace(/\//g,'\\'), fs=path.replace(/\\/g,'/').toLowerCase();
  const fromMpq=await mpqChainRead(bs); if(fromMpq)return fromMpq;
  if(S.cascRoot&&S.cascEnc){
    const ck=S.cascRoot.get(fs);
    if(ck){ const ek=S.cascEnc.get(ck); if(ek) return await readCascByEKey(ek); }
  }
  throw new Error('not found in any source: '+path);
}
function parseTbl(buf){
  const dv=new DataView(buf), b=new Uint8Array(buf), n=dv.getUint16(0,true), out=[];
  const td=new TextDecoder('latin1');
  for(let i=1;i<=n;i++){
    const o=dv.getUint16(2+(i-1)*2,true); let e=o;
    while(e<b.length&&b[e])e++;
    out.push(td.decode(b.subarray(o,e)));
  }
  return out;                      // out[0] is string #1 == unit id 0
}
// units.dat is a struct-of-arrays; group_flags sits at 16684 (verified: the
// field walk predicts a 19876-byte file and the real file is exactly that).
const UNITS_DAT_GROUP_FLAGS=16684, UNIT_COUNT=228;
function unitRace(dat,id){
  const g=new Uint8Array(dat)[UNITS_DAT_GROUP_FLAGS+id];
  return (g&1)?'zerg':(g&2)?'terran':(g&4)?'protoss':'neutral';
}

// Authentic twire.pcx values. Kept as a
// frozen template so "atstatyti" always returns to the file's own colours.
const WF_DEFAULTS={
  zerg:['#080808','#840404','#a80808','#c81818','#a0541c','#e85014','#f88c14','#fcfc38','#10fc18'],
  // Terran/Protoss get a ramp too. The engine currently hard-codes four fixed
  // band colours for them, so this is a tester extension -- exported as
  // tp_ramp.
  tp:['#080808','#840404','#a80808','#c81818','#a0541c','#e85014','#f88c14','#fcfc38','#10fc18'],
  shield:['#001034','#042064','#042064','#083498','#083498','#0c48cc','#0c48cc'],
  structure:['#0c1424','#243c64'],
  line:'#cdd9e6',
  maskCol:[null,null,null,null,null,null,null,null]   // null = derived
};
const WF={
  zerg:WF_DEFAULTS.zerg.slice(), tp:WF_DEFAULTS.tp.slice(),
  shield:WF_DEFAULTS.shield.slice(), structure:WF_DEFAULTS.structure.slice(),
  line:WF_DEFAULTS.line, maskCol:WF_DEFAULTS.maskCol.slice(),
  bandMode:'auto',
  hp:100, sp:100, pick:null, unit:-1, ready:false,
  sd:null, hd:null, hdBuf:null, units:[], names:[], twire:[], cellCount:0
};
function wfReset(){
  WF.zerg=WF_DEFAULTS.zerg.slice(); WF.tp=WF_DEFAULTS.tp.slice();
  WF.shield=WF_DEFAULTS.shield.slice(); WF.structure=WF_DEFAULTS.structure.slice();
  WF.line=WF_DEFAULTS.line; WF.maskCol=WF_DEFAULTS.maskCol.slice();
  WF.hp=100; WF.sp=100; WF.pick=null; WF.bandMode='auto';
  $('#wfHp').value=100; $('#wfHpV').textContent='100%';
  $('#wfSp').value=100; $('#wfSpV').textContent='100%';
  $('#wfMode').value='auto';
  wfBuildControls(); wfRender();
  setStatus('Wireframe colours reset to authentic <b>twire.pcx</b> values.');
}
const hex2rgb=h=>[parseInt(h.slice(1,3),16),parseInt(h.slice(3,5),16),parseInt(h.slice(5,7),16)];
const rgb2hex=(r,g,b)=>'#'+[r,g,b].map(x=>x.toString(16).padStart(2,'0')).join('');

/* --- derivation ---------------------------------------------------------
   The four index families are NOT the same kind of thing for every race, and
   this was measured on the real wirefram.grp, not assumed:

     Terran/Protoss 208..211 -- BODY PARTS. Neighbour mixing is only 1.5-18%,
       i.e. contiguous separate regions (Zealot 211: 1.5%). Handing them four
       different ramp entries at once paints a full-health Ghost as a rainbow.
       At full HP the whole wireframe must be ONE colour, sliding down the ramp
       as it takes damage.

     Zerg 216..219 -- NESTED SHELLS. Mixing is 24-59% and the mean radius from
       the centre grows monotonically (Zergling 8.6/9.1/12.9/16.8 px, Drone
       8.1/12.3/15.2/17.3). That is a gradient, so the engine's 4-wide sliding
       window (top = 4 + hp*4/100) is meaningful here and a flat colour would
       destroy it.

   Hence two models, defaulted per race, switchable so both can be compared. */
function wfRampFor(race){ return race==='zerg'?WF.zerg:WF.tp; }
function wfModeFor(race){
  // AUTHENTIC default is PER-PART for every race: the 4 band indices are four
  // separate regions (Terran/Protoss body parts; Zerg nested shells), and the
  // original recolours them independently. At full HP all four sit at the top
  // of the ramp (healthy green); as HP drops the parts drain progressively, so
  // a damaged unit shows some parts still green and others already red - never
  // one flat colour across the whole wireframe. 'solid'/'window' stay available
  // for comparison but 'solid' (whole wireframe one colour) is the wrong model.
  return WF.bandMode==='auto' ? 'parts' : WF.bandMode;
}
// Two authentic looks, measured against retail wireframes:
//  - ZERG nested shells recolour as a SMOOTH GRADIENT down the full 9-entry ramp
//    (green core -> yellow -> ORANGE -> red outer), the organic layered look in
//    the retail Drone wireframe. depth 0=inner..1=outer; the whole gradient
//    slides toward red as HP drops.
//  - TERRAN/PROTOSS scattered body parts use THREE crisp stages
//    green(8)/yellow(7)/red(2) - a gradient on scattered parts looks random.
const WF_STAGES=[8,7,2];                    // green, yellow, red -> ramp index
const WF_ZERG_GRAD=5, WF_ZERG_SHIFT=6;      // gradient span / HP shift for Zerg
function wfShellLevel(depth, race){         // depth 0=inner..1=outer -> ramp index
  const hpf=WF.hp/100;
  if(race==='zerg'){
    const k=Math.round(8 - depth*WF_ZERG_GRAD - (1-hpf)*WF_ZERG_SHIFT);
    return k<0?0:(k>8?8:k);
  }
  const t=hpf - depth*(1-hpf);             // outer parts degrade first
  return t>0.66 ? WF_STAGES[0] : (t>0.33 ? WF_STAGES[1] : WF_STAGES[2]);
}
function wfPartLevels(race){                 // the 4 SD bands (208-211 / 216-219)
  return [0,1,2,3].map(i=>wfShellLevel(i/3, race));
}
function wfWindow(){                        // sliding window: ramp[4..8] (comparison model)
  const top=4+Math.floor(WF.hp*4/100), ix=[];
  for(let i=0;i<4;i++){let k=top-i; if(k<0)k=0; if(k>8)k=8; ix.push(k);}
  return ix;
}
function wfSolidIndex(){                    // one colour, spanning the whole ramp
  return Math.max(0,Math.min(8,Math.round(WF.hp*8/100)));
}
function wfActiveRampIdx(race){
  const m=wfModeFor(race);
  return m==='solid' ? [wfSolidIndex()] : (m==='window' ? wfWindow() : wfPartLevels(race));
}
function wfLayers(race){
  const r=wfRampFor(race), m=wfModeFor(race);
  if(m==='solid'){ const c=r[wfSolidIndex()]; return [c,c,c,c]; }
  const ix=(m==='window')?wfWindow():wfPartLevels(race);
  return ix.map(k=>r[k]);
}
function wfShieldIndex(){
  const n=WF.shield.length, hi=Math.floor(WF.sp*(n-1)/100);
  return Math.min(n-1,Math.floor(hi/2));
}
function wfShieldLo(){ return WF.shield[wfShieldIndex()]; }

async function wfLoad(){
  if(WF.ready) return;
  showLoad('Loading wireframe data…');
  try{
    const dat=await readGameFile('arr\\units.dat');
    const tbl=parseTbl(await readGameFile('rez\\stat_txt.tbl'));
    WF.names=tbl;
    WF.units=[];
    for(let i=0;i<UNIT_COUNT;i++)
      WF.units.push({id:i,race:unitRace(dat,i),name:tbl[i]||('unit '+i)});
    WF.sd=parseClassicGRP(await readGameFile('unit\\wirefram\\wirefram.grp'));
    // HD wireframes are SC:R only — absent from the 1998 MPQs. Try the half
    // resolution pack first (that is what the port ships), then full HD.
    for(const p of ['hd2/unit/wirefram/wirefram.dds.grp','unit/wirefram/wirefram.dds.grp']){
      try{ WF.hdBuf=await readGameFile(p); WF.hd=parseDdsGRP(WF.hdBuf); WF.hdPath=p; break; }catch(e){}
    }
    try{
      const tw=await readGameFile('game\\twire.pcx'), s=parsePCX(tw), im=s.frames[0]._img;
      WF.twire=[]; for(let x=0;x<im.width;x++){const o=x*4; WF.twire.push(rgb2hex(im.data[o],im.data[o+1],im.data[o+2]));}
    }catch(e){ WF.twire=[]; }
    WF.ready=true;
    $('#wfSrc').textContent='SD '+WF.sd.frameCount+' frames'
      +(WF.hd?(' · HD '+WF.hd.frameCount+' frames ('+WF.hdPath+')'):' · HD none (needs CASC — SC:R)')
      +(WF.twire.length?(' · twire '+WF.twire.length+' entries'):'');
    hideLoad();
  }catch(e){ hideLoad(); throw e; }
}

/* ---- rendering ---- */
function wfDrawSd(unit){
  const cv=$('#wfSd'), f=WF.sd&&WF.sd.frames[unit.id];
  if(!f){cv.width=cv.height=1;return;}
  const L=wfLayers(unit.race), S4=WF.structure, lo=wfShieldLo();
  // Shield tints the Protoss structure indices whenever the unit has a shield.
  // Gating this on the rim checkbox made the shield slider look dead.
  const useShield=(unit.race==='protoss');
  const img=new ImageData(f.w,f.h), d=img.data;
  const put=(i,h)=>{const c=hex2rgb(h);d[i]=c[0];d[i+1]=c[1];d[i+2]=c[2];d[i+3]=255;};
  for(let i=0;i<f.w*f.h;i++){
    const v=f.idx[i], o=i*4;
    if(!v) continue;
    if(v===208||v===216) put(o,L[0]);
    else if(v===209||v===217) put(o,L[1]);
    else if(v===210||v===218) put(o,L[2]);
    else if(v===211||v===219) put(o,L[3]);
    else if(v===192) put(o,useShield?lo:S4[0]);
    else if(v===193) put(o,useShield?WF.shield[WF.shield.length-1]:S4[1]);
    else { d[o]=255;d[o+1]=0;d[o+2]=255;d[o+3]=255; }   // outside every family — show it
  }
  drawScaled(cv,img,3);
}
// Cell roles are NOT fixed by position -- measured on the retail HD2 atlas:
//   Terran         K K K K S S S .    4 masks, cells 4-6 already coloured
//   Zerg/Protoss   K K K K K K S .    6 masks, cell 6 coloured
//   Probe          K K K K K K K .    7 masks, no coloured cell at all
//   Command Center K K K K S S S S    4 masks, cells 4-7 coloured
// So classify by saturation at load time instead of assuming "last cell is the
// art"; assuming it made the tester tint the artwork and show nothing for it.
function wfClassify(img){
  const d=img.data; let op=0, sat=0;
  for(let i=0;i<d.length;i+=4){
    const a=d[i+3]; if(a<16) continue;
    op++;
    const mx=Math.max(d[i],d[i+1],d[i+2]), mn=Math.min(d[i],d[i+1],d[i+2]);
    sat += mx?((mx-mn)*255/mx):0;
  }
  if(!op) return 'empty';
  return (sat/op)<25 ? 'mask' : 'art';
}
function wfCells(unit){
  if(!WF.hd||!WF.hd.frames[unit.id]) return null;
  const fr=WF.hd.frames[unit.id];
  const atlas=ddsToImageData(WF.hdBuf,fr.ddsOff);
  const cs=atlas.height, n=cs?Math.floor(atlas.width/cs):0;
  const cells=[], kind=[];
  for(let i=0;i<n;i++){
    const c=cropImageData(atlas,i*cs,0,cs,cs);
    cells.push(c); kind.push(wfClassify(c));
  }
  return {cells,kind,size:cs};
}
// Default family mapping, overridable per mask so every cell of every unit is
// reachable -- some units carry more than the six documented masks, and those
// used to collapse into one shared colour.
// Measured on the SC:R HD atlas (hd2/unit/wirefram/wirefram.dds.grp): the mask
// cells are NESTED SHELLS, and their count/role varies by race --
//   Terran : 4 masks, all HP bands
//   Zerg   : 6 masks, ALL HP shells (inner->outer), NOT 4 + structure
//   Protoss: 6 masks = 4 inner HP shells + 2 OUTERMOST shells = the SHIELD
// so colour by radius-derived role, not by cell index. (The old code mapped
// masks 4,5 to a dark "structure" colour, which hid the 2 outer Zerg shells and
// the whole Protoss shield.)
function wfShellStage(i,N,race){            // HP shell i of N, inner(0)->outer
  return wfShellLevel(N>1?i/(N-1):0, race);
}
function wfMaskRadii(cells,maskIdx,size){
  return maskIdx.map(m=>{const s=cells[m].data; let xs=0,ys=0,n=0;
    for(let p=0;p<size*size;p++){if(s[p*4+3]<8)continue; xs+=p%size; ys+=(p/size)|0; n++;}
    if(!n)return 0; const cx=xs/n,cy=ys/n; let r=0;
    for(let p=0;p<size*size;p++){if(s[p*4+3]<8)continue; const x=p%size,y=(p/size)|0; r+=Math.hypot(x-cx,y-cy);}
    return r/n;});
}
function wfComputeMaskColors(cells,maskIdx,race,size){
  const rad=wfMaskRadii(cells,maskIdx,size);
  const items=maskIdx.map((m,k)=>({m,r:rad[k]}));
  let shield=[];
  if(race==='protoss'&&items.length>4)      // 2 outermost masks = shield shell
    shield=[...items].sort((a,b)=>b.r-a.r).slice(0,2).map(x=>x.m);
  const hp=items.filter(x=>!shield.includes(x.m)).sort((a,b)=>a.r-b.r).map(x=>x.m);
  const ramp=wfRampFor(race), out={};
  hp.forEach((m,i)=>out[m]=ramp[wfShellStage(i,hp.length,race)]);
  const sc=wfShieldLo();
  shield.forEach(m=>out[m]=sc);            // shield shell follows the shield slider
  return out;
}
function wfCellDefault(i,L){                 // fallback when no computed role
  if(i<4) return L[i];
  if(i===4) return WF.structure[0];
  if(i===5) return WF.structure[1];
  return WF.line;
}
function wfCellColor(i,L){
  return (WF.maskCol[i]||null) || (WF.maskColors&&WF.maskColors[i]) || wfCellDefault(i,L);
}
function wfDrawHd(unit){
  const cv=$('#wfHd'), info=$('#wfCellInfo'), cvc=$('#wfCells');
  const got=wfCells(unit);
  if(!got){ cv.width=cv.height=1; cvc.width=cvc.height=1; WF.cellCount=0;
    info.textContent=WF.hd?'no HD frame for this unit':'no HD source — open the SC:R CASC folder'; return; }
  const {cells,kind,size}=got;
  WF.cellCount=cells.length;
  WF.maskIdx=kind.map((k,i)=>k==='mask'?i:-1).filter(i=>i>=0);
  const artIdx=kind.map((k,i)=>k==='art'?i:-1).filter(i=>i>=0);
  const L=wfLayers(unit.race), heat=$('#wfHeat').checked;
  WF.maskColors=wfComputeMaskColors(cells,WF.maskIdx,unit.race,size);   // radius-based roles
  const out=new ImageData(size,size), d=out.data;
  const owner=new Int8Array(size*size).fill(-1), best=new Float32Array(size*size);
  for(const m of WF.maskIdx){
    const src=cells[m].data, col=hex2rgb(wfCellColor(m,L));
    for(let p=0;p<size*size;p++){
      const a=src[p*4+3]; if(a<8) continue;
      const lum=(src[p*4]*77+src[p*4+1]*150+src[p*4+2]*29)>>8;
      const s=lum*a/255/255;
      if(s<=0.02) continue;
      if(s>best[p]){ best[p]=s; owner[p]=m; }
      const o=p*4;
      d[o]  =Math.round(d[o]  *(1-s)+col[0]*s);
      d[o+1]=Math.round(d[o+1]*(1-s)+col[1]*s);
      d[o+2]=Math.round(d[o+2]*(1-s)+col[2]*s);
      d[o+3]=Math.max(d[o+3],Math.round(255*s));
    }
  }
  if(heat){
    // Which mask owns each pixel, painted flat in that mask's CURRENT colour --
    // so the map follows the HP/shield sliders instead of showing only geometry.
    for(let p=0;p<size*size;p++){
      const m=owner[p], o=p*4;
      if(m<0){d[o+3]=0;continue;}
      const col=hex2rgb(wfCellColor(m,L));
      d[o]=col[0];d[o+1]=col[1];d[o+2]=col[2];d[o+3]=255;
    }
  }
  if($('#wfArt').checked){
    for(const ai of artIdx){
      const art=cells[ai].data;
      for(let p=0;p<size*size;p++){const o=p*4,a=art[o+3]; if(a<8)continue;
        d[o]=art[o];d[o+1]=art[o+1];d[o+2]=art[o+2];d[o+3]=a;}
    }
  }
  if($('#wfRim').checked && unit.race==='protoss' && !heat){
    const rim=hex2rgb(wfShieldLo()), solid=new Uint8Array(size*size);
    for(let p=0;p<size*size;p++) solid[p]=d[p*4+3]>24?1:0;
    for(let y=0;y<size;y++)for(let x=0;x<size;x++){
      const p=y*size+x; if(solid[p]) continue;
      let near=0;
      for(let dy=-1;dy<=1&&!near;dy++)for(let dx=-1;dx<=1;dx++){
        const nx=x+dx, ny=y+dy;
        if(nx<0||ny<0||nx>=size||ny>=size) continue;
        if(solid[ny*size+nx]){near=1;break;}
      }
      if(near){const o=p*4;d[o]=rim[0];d[o+1]=rim[1];d[o+2]=rim[2];d[o+3]=255;}
    }
  }
  drawScaled(cv,out,Math.max(1,Math.min(3,Math.floor(192/size))));

  // cell strip
  const sc=Math.max(1,Math.floor(72/size));
  cvc.width=cells.length*(size*sc+6); cvc.height=size*sc+18;
  const ctx=cvc.getContext('2d'); ctx.imageSmoothingEnabled=false;
  ctx.clearRect(0,0,cvc.width,cvc.height);
  cells.forEach((c,i)=>{
    const t=document.createElement('canvas'); t.width=size;t.height=size;
    t.getContext('2d').putImageData(c,0,0);
    ctx.drawImage(t,i*(size*sc+6),14,size*sc,size*sc);
    ctx.fillStyle=kind[i]==='mask'?wfCellColor(i,L):(kind[i]==='art'?'#f5b642':'#44506080');
    ctx.font='10px monospace';
    ctx.fillText(kind[i]==='mask'?('k'+i):(kind[i]==='art'?'art':'empty'),i*(size*sc+6)+2,10);
  });
  info.innerHTML='cells <b>'+cells.length+'</b> of '+size+'×'+size+' px · masks <b>'
    +WF.maskIdx.length+'</b> ('+WF.maskIdx.join(',')+') · art '+artIdx.length
    +(artIdx.length?(' ('+artIdx.join(',')+')'):'')
    +' · empty '+kind.filter(k=>k==='empty').length
    +'<br>roles by radius (nested shells): Terran 4 HP · Zerg 6 HP · Protoss 4 HP + 2 shield (outermost)';
}
function wfRender(){
  const u=WF.units[WF.unit]; if(!u) return;
  wfDrawSd(u); wfDrawHd(u);
  // Rebuild the mask pickers only when the set actually changes -- doing it on
  // every render would tear down the colour input mid-drag.
  const sig=u.id+'/'+(WF.maskIdx||[]).join(',');
  if(WF._maskSig!==sig){ WF._maskSig=sig; wfMaskSlots(); }
  wfMarkLive(); wfSyncJson();
}

/* ---- controls ---- */
function wfSlot(host,label,get,set,live){
  const row=document.createElement('div'); row.className='slot'+(live?' live':'');
  const inp=document.createElement('input'); inp.type='color'; inp.value=get();
  const lbl=document.createElement('span'); lbl.className='lbl'; lbl.textContent=label;
  const hx=document.createElement('span'); hx.className='hex'; hx.textContent=get();
  inp.addEventListener('input',()=>{set(inp.value);hx.textContent=inp.value;wfRender();});
  row.addEventListener('click',e=>{                   // click a slot to paste the picked twire colour
    if(e.target===inp) return;
    if(WF.pick){ set(WF.pick); inp.value=WF.pick; hx.textContent=WF.pick; wfRender(); }
  });
  row.append(inp,lbl,hx); host.appendChild(row);
  return row;
}
function wfBuildControls(){
  const tw=$('#wfTwire'); tw.innerHTML='';
  WF.twire.forEach((h,i)=>{
    const s=document.createElement('i'); s.style.background=h; s.title=i+': '+h;
    s.addEventListener('click',()=>{
      WF.pick=h; [...tw.children].forEach(c=>c.classList.remove('sel')); s.classList.add('sel');
      setStatus('Picked authentic colour <b>'+h+'</b> — click a ramp cell to assign it.');
    });
    tw.appendChild(s);
  });
  const z=$('#wfZerg'); z.innerHTML=''; WF.zergSlots=[];
  WF.zerg.forEach((_,i)=>WF.zergSlots.push(
    wfSlot(z,'zerg ramp['+i+']'+(i===0?' (fill)':''),()=>WF.zerg[i],v=>WF.zerg[i]=v)));
  const tp=$('#wfTp'); tp.innerHTML=''; WF.tpSlots=[];
  WF.tp.forEach((_,i)=>WF.tpSlots.push(
    wfSlot(tp,'T/P ramp['+i+']'+(i===0?' (fill)':''),()=>WF.tp[i],v=>WF.tp[i]=v)));
  const sh=$('#wfShield'); sh.innerHTML=''; WF.shieldSlots=[];
  WF.shield.forEach((_,i)=>WF.shieldSlots.push(
    wfSlot(sh,'shield['+i+']',()=>WF.shield[i],v=>WF.shield[i]=v)));
  const m=$('#wfMisc'); m.innerHTML='';
  wfSlot(m,'192 structure (dark)',()=>WF.structure[0],v=>WF.structure[0]=v);
  wfSlot(m,'193 structure (light)',()=>WF.structure[1],v=>WF.structure[1]=v);
  wfSlot(m,'hd_line (remaining masks)',()=>WF.line,v=>WF.line=v);
  wfMaskSlots();
}

// One picker per actual mask cell of the selected unit. Masks 0..5 follow the
// ramps unless overridden here; 6+ had no control at all before.
function wfMaskSlots(){
  const host=$('#wfMask'); if(!host) return;
  host.innerHTML='';
  const u=WF.units[WF.unit];
  const idxs=WF.maskIdx||[];
  if(!u||!idxs.length){ host.innerHTML='<div style="color:var(--ink-dim);font-size:10px">no HD masks (needs CASC)</div>'; return; }
  const L=wfLayers(u.race);
  for(const i of idxs){
    const row=wfSlot(host,'mask '+i+(WF.maskCol[i]?' (own)':' (from ramp)'),
      ()=>wfCellColor(i,L), v=>{WF.maskCol[i]=v;}, false);
    const x=document.createElement('span');
    x.textContent='×'; x.title='reset to ramp colour';
    x.style.cssText='cursor:pointer;color:var(--ink-dim);font-size:12px;padding:0 3px';
    x.addEventListener('click',ev=>{ev.stopPropagation();WF.maskCol[i]=null;wfRender();wfMaskSlots();});
    row.appendChild(x);
  }
}
// Mark which ramp entries the sliders are currently selecting, so moving a
// slider always shows feedback even when the preview barely changes.
function wfMarkLive(){
  const u=WF.units[WF.unit]; if(!u) return;
  const act=wfActiveRampIdx(u.race), si=wfShieldIndex(), isZerg=(u.race==='zerg');
  (WF.zergSlots||[]).forEach((r,i)=>r.classList.toggle('live',isZerg&&act.includes(i)));
  (WF.tpSlots||[]).forEach((r,i)=>r.classList.toggle('live',!isZerg&&act.includes(i)));
  (WF.shieldSlots||[]).forEach((r,i)=>r.classList.toggle('live',i===si));
  const m=wfModeFor(u.race);
  const parts=isZerg?'nested shells (216–219)':'body parts (208–211)';
  $('#wfModeNote').innerHTML = m==='solid'
    ? '<b style="color:#e0708a">solid (wrong)</b> — the whole mask gets <b>ramp['+wfSolidIndex()+']</b>; in the original the colour changes per part'
    : m==='window'
    ? '<b style="color:var(--teal)">window</b> — 4 adjacent ramp['+act.join(',')+']'
    : (isZerg
      ? '<b style="color:var(--teal)">gradient</b> — '+parts+': smooth green→yellow→orange→red across shells (retail organic look), the gradient slides down as HP falls; now ramp['+act.join(',')+']'
      : '<b style="color:var(--teal)">3 stages</b> — '+parts+': green/yellow/red, scattered body parts change from the outside; now ramp['+act.join(',')+']');
}
function wfBuildList(){
  const host=$('#wfUnits'), q=($('#wfFilter').value||'').toLowerCase();
  host.innerHTML='';
  const order=['zerg','terran','protoss','neutral'];
  const LBL={zerg:'Zerg',terran:'Terran',protoss:'Protoss',neutral:'Other'};
  for(const race of order){
    const list=WF.units.filter(u=>u.race===race&&(!q||u.name.toLowerCase().includes(q)||(''+u.id)===q));
    if(!list.length) continue;
    const h=document.createElement('div'); h.className='rhead'; h.textContent=LBL[race]+' ('+list.length+')';
    host.appendChild(h);
    for(const u of list){
      const r=document.createElement('div'); r.className='urow'+(u.id===WF.unit?' on':'');
      r.innerHTML='<span class="uid">'+u.id+'</span><span>'+u.name+'</span>';
      r.addEventListener('click',()=>{WF.unit=u.id;wfBuildList();wfRender();});
      host.appendChild(r);
    }
  }
}
/* ---- export ---- */
function wfJsonObject(){
  return {
    version:2,
    source:'sc-asset-browser wireframe tester',
    note:'Full composition + engine reader spec: how each race’s wireframe is built from the SC:R assets and exactly how an engine must colour it to reproduce this tester. Colours are hex RGB. All indices/masks/formulas measured against BW 1.16.1 (SD) and SC:R HD (hd2/unit/wirefram/wirefram.dds.grp).',
    ramps:{
      hp:WF.zerg.slice(),                 // 9 entries, ramp[0]=dead(black) .. ramp[8]=green(healthy)
      hp_alt_tp:WF.tp.slice(),            // Terran/Protoss HP ramp (same by default; editable)
      shield:WF.shield.slice(),           // 7 blue entries, [0]=low .. [n-1]=full
      structure:{index192:WF.structure[0],index193:WF.structure[1]},
      hd_line:WF.line,
      ramp_semantics:'ramp[8] green(healthy) 7 yellow 6 amber 5 orange 4 orange-brown 3 bright-red 2 red 1 dark-red 0 black(dead)'
    },
    races:{
      terran:{ sd_hp_indices:[208,209,210,211], sd_base:[192,193],
        hd_mask_count:4, hd_mask_roles:'4 HP shells (by radius)',
        hp_model:'stages', uses_shield:false, uses_heatmap:true },
      protoss:{ sd_hp_indices:[208,209,210,211], sd_shield:[192,193],
        hd_mask_count:6, hd_mask_roles:'4 inner HP shells + 2 OUTERMOST (largest radius) = SHIELD',
        hp_model:'stages', uses_shield:true, uses_heatmap:true },
      zerg:{ sd_hp_indices:[216,217,218,219], sd_base:[192,193],
        hd_mask_count:6, hd_mask_roles:'all 6 = HP shells (nested inner->outer, by radius)',
        hp_model:'gradient', uses_shield:false, uses_heatmap:true }
    },
    models:{
      gradient:{ applies:['zerg'],
        formula:'k = round(8 - depth*'+WF_ZERG_GRAD+' - (1-hp/100)*'+WF_ZERG_SHIFT+'); clamp 0..8; colour = hp_ramp[k]',
        params:{grad:WF_ZERG_GRAD,shift:WF_ZERG_SHIFT},
        note:'depth 0=innermost shell .. 1=outermost. Smooth green-core->red-outer even at full HP (outer shells have the largest area, so a healthy unit reads warm with a green core). The whole gradient slides toward red as HP falls.' },
      stages:{ applies:['terran','protoss'],
        formula:'t = hp/100 - depth*(1-hp/100); stage = t>0.66?green(ramp['+WF_STAGES[0]+']) : t>0.33?yellow(ramp['+WF_STAGES[1]+']) : red(ramp['+WF_STAGES[2]+'])',
        stages:WF_STAGES,
        note:'3 crisp stages for scattered body parts (a gradient would look random). Outer part (depth 1) degrades first; at full HP every part is green.' }
    },
    shield_model:{ applies_to:'protoss: the 2 outermost HD masks, and SD indices 192/193',
      formula:'shield_ramp[floor(hi/2)], hi = floor(shield%*(shield_ramp.length-1)/100)',
      note:'Blue shield shell over the HP shells; follows shield%.' },
    hd_mask_assignment:'Decode wirefram.dds.grp frame = 8 cells of size H; classify each cell mask(low saturation) vs art/colored(high). Sort MASK cells by mean opaque-pixel radius. Protoss (>4 masks): the 2 largest-radius masks = shield; the rest = HP shells inner->outer. Terran/Zerg: all masks = HP shells inner->outer. depth = rank/(N-1).',
    heatmap:'Debug view: each pixel painted flat in the CURRENT colour of the mask that owns it (owner = mask with max luminance*alpha at that pixel). Not a game element; use it to verify region assignment.',
    engine_reader:[
      '1. Race from units.dat group_flags@16684: bit1 zerg, bit2 terran, bit4 protoss, else neutral.',
      '2. SD path (wirefram.grp, palette-indexed): HP pixels are the 4 indices in races[race].sd_hp_indices; band j maps to depth j/3. Colour via models[races[race].hp_model]. 192/193: Protoss -> shield_model, others -> ramps.structure.',
      '3. HD path (wirefram.dds.grp): follow hd_mask_assignment; colour each HP shell by depth via the race model; Protoss shield shells via shield_model.',
      '4. HP% and shield% are the only runtime inputs; everything else is static asset geometry.',
      '5. To match this tester exactly, use ramps.hp (9 entries) and the given params; results are deterministic.'
    ],
    current_state:{hp_pct:WF.hp, shield_pct:WF.sp, tester_mode:WF.bandMode, heatmap_on:!!(document.getElementById('wfHeat')||{}).checked},
    mask_colors_override:WF.maskCol.map(c=>c||null)   // manual per-cell overrides; null = derive
  };
}
function wfSyncJson(){ $('#wfJson').value=JSON.stringify(wfJsonObject(),null,2); }

$('#wfOpen').addEventListener('click',async()=>{
  if(!S.lastMpq&&!S.cascRoot){
    setStatus('Open a .mpq archive or CASC folder first — the tester reads its data from them.',true);
    return;
  }
  try{
    await wfLoad();
    if(WF.unit<0) WF.unit=WF.units.findIndex(u=>u.race!=='neutral');
    wfBuildControls(); wfBuildList(); wfRender();
    $('#wf').classList.add('on');
  }catch(e){ setStatus('Wireframe tester: '+e.message,true); }
});
$('#wfClose').addEventListener('click',()=>$('#wf').classList.remove('on'));
$('#wfResetBtn').addEventListener('click',wfReset);
$('#wfFilter').addEventListener('input',wfBuildList);
$('#wfHp').addEventListener('input',e=>{WF.hp=+e.target.value;$('#wfHpV').textContent=WF.hp+'%';wfRender();});
$('#wfSp').addEventListener('input',e=>{WF.sp=+e.target.value;$('#wfSpV').textContent=WF.sp+'%';wfRender();});
['#wfHeat','#wfArt','#wfRim'].forEach(id=>$(id).addEventListener('change',wfRender));
$('#wfMode').addEventListener('change',e=>{WF.bandMode=e.target.value;wfRender();});
$('#wfExport').addEventListener('click',()=>{
  const url=URL.createObjectURL(new Blob([JSON.stringify(wfJsonObject(),null,2)],{type:'application/json'}));
  dl(url,'wireframe-colors.json'); URL.revokeObjectURL(url);
  setStatus('Eksportuota <b>wireframe-colors.json</b>.');
});

/* ========================= Campaign AI Oracle ========================= */
const CAI={ai:{},missions:[],usage:{},byId:{},ready:false,sel:null,missionsOnly:false};

/* Curated walkthrough FACTS (enemy faction / attack units / pattern / objective +
   source URLs) — twin of assets/campaign_walkthroughs.json. Facts only, attributed;
   cross-referenced against the mission's own AI-script attack composition below. */
const CAMPAIGN_WALKTHROUGHS={"terran/terran03":{name:"Desperate Alliance",objective:"Survive 30 minutes; no offensive objective (pure defence)",factions:["Zerg"],units:["Zergling","Hydralisk","Mutalisk"],pattern:"escalating waves against two choke points until the 30-minute timer",sources:["strategywiki.org","gamepressure.com"]},
"terran/terran05":{name:"Revolution",objective:"Destroy the Confederate Alpha Squadron base on Antiga Prime",factions:["Terran (Confederate Alpha Squadron)"],units:["Marine","Vulture","Wraith","Firebat","Siege Tank"],pattern:"ground pushes plus occasional Siege Tanks; bunkers and spider mines on defence",sources:["gamepressure.com","strategywiki.org"]},
"terran/terran07":{name:"The Trump Card",objective:"Deliver the Psi Emitter to the beacon (it lures the Zerg onto Delta Squadron)",factions:["Terran (Confederate Delta Squadron)","Zerg"],units:["Zergling","Hydralisk","Mutalisk","Ultralisk","Wraith"],pattern:"Delta Squadron ground + cloaked Wraiths early; the Psi Emitter then draws heavy Zerg waves",sources:["strategywiki.org","portforward.com"]},
"zerg/zerg02":{name:"Egression",objective:"Escort the Chrysalis to the beacon in the bottom-right corner",factions:["Protoss"],units:["Zealot","Dragoon","Scout"],pattern:"Photon-cannon/Zealot defences on the path; Dragoons and Scouts join as you advance",sources:["gamepressure.com","strategywiki.org"]},
"protoss/protoss01":{name:"First Strike",objective:"Meet Fenix at Antioch, then wipe out the Zerg base",factions:["Zerg"],units:["Zergling","Hydralisk","Mutalisk"],pattern:"scattered Zergling/Hydralisk groups on the approach; base defended by a sunken colony",sources:["strategywiki.org","portforward.com"]}};

// JS twin of tools/ai/mission_bot.py — what the mission's bots build/train/attack
// with, straight from the linked AI-script bytecode (sha-verified vs Python).
const AI_UNIT_ARG=new Set(['building','military','unit','gg_military','ag_military','ga_military','aa_military']);
const AI_BUILD_OPS=new Set(['build','defensebuild_gg','defensebuild_ag','defensebuild_ga','defensebuild_aa','build_bunkers','build_turrets']);
const AI_TRAIN_OPS=new Set(['train','do_morph','wait_train','create_unit','define_max']);
function caiScriptById(id){ for(const src in CAI.ai){ for(const s of CAI.ai[src].scripts) if(s.id===id) return s; } return null; }
function caiUnitArg(ins){ for(const a of ins.args) if(AI_UNIT_ARG.has(a.t)) return a.v; return null; }
function caiCountArg(ins){ for(const a of ins.args) if(a.t==='byte') return a.v; return null; }
function caiMissionBot(m){
  const un=CAI.uname||(u=>'unit '+u); const seen=new Set();
  const builds={},trains={},attacks={};
  for(const l of (m.links||[])){ if(seen.has(l.script))continue; seen.add(l.script);
    const s=caiScriptById(l.script); if(!s||s.err)continue;
    for(const ins of s.ins){ const n=ins.name;
      if(n==='attack_add'||n==='easy_attack'){ const u=caiUnitArg(ins); if(u!=null)attacks[u]=(attacks[u]||0)+(caiCountArg(ins)||1); }
      else if(AI_BUILD_OPS.has(n)){ const u=caiUnitArg(ins); if(u!=null)builds[u]=(builds[u]||0)+(caiCountArg(ins)||1); }
      else if(AI_TRAIN_OPS.has(n)){ const u=caiUnitArg(ins); if(u!=null)trains[u]=(trains[u]||0)+(caiCountArg(ins)||1); }
    } }
  const named=d=>Object.keys(d).map(k=>({unit:+k,name:un(+k),count:d[k]})).sort((a,b)=>b.count-a.count);
  return {builds:named(builds),trains:named(trains),attacks:named(attacks)};
}
function caiNormUnit(name){ let s=(name||'').trim().toLowerCase();
  for(const r of ['zerg ','terran ','protoss ']) if(s.startsWith(r)){s=s.slice(r.length);break;}
  if(s.endsWith('s')&&!s.endsWith('ss'))s=s.slice(0,-1); return s; }
function caiWalkthrough(m){
  const bot=caiMissionBot(m); const e=CAMPAIGN_WALKTHROUGHS[m.fmtLabel];
  const script=new Map(); for(const r of bot.attacks) script.set(caiNormUnit(r.name),r.name);
  if(!e) return {has:false,bot};
  const wt=new Map(); for(const u of e.units) wt.set(caiNormUnit(u),u);
  const S=new Set(script.keys()),W=new Set(wt.keys());
  return {has:true,e,bot,
    confirmed:[...S].filter(x=>W.has(x)).map(x=>script.get(x)).sort(),
    script_only:[...S].filter(x=>!W.has(x)).map(x=>script.get(x)).sort(),
    walkthrough_only:[...W].filter(x=>!S.has(x)).map(x=>wt.get(x)).sort()};
}
function caiSpecHtml(m){
  const sp=m.spec; if(!sp)return '';
  const un=CAI.uname||(u=>'unit '+u); const esc=t=>(t||'').replace(/[<&]/g,c=>c==='<'?'&lt;':'&amp;');
  const cond=c=>{ if(['Bring','Command','Accumulate','Kills','Deaths','Opponents'].includes(c.t))
      return c.t+': '+chkPg(c.player)+' '+c.cmp+' '+c.qty+' '+esc(un(c.unit));
    if(c.t==='CountdownTimer'||c.t==='ElapsedTime')return c.t+' '+(c.cmp||'')+' '+c.qty+'s';
    return c.t; };
  let h='<div style="max-width:820px;text-align:left"><div class="rhead" style="margin-top:14px">📋 Spec sheet (engine bug-diff reference)</div>';
  h+='<div style="font-size:12px;line-height:1.7">';
  h+='<div><span style="color:#5fe07a">WIN when:</span> '+(sp.victory.map(v=>'['+v.players.join(',')+'] '+v.conditions.map(cond).join(' & ')).join(' · ')||'—')+'</div>';
  h+='<div><span style="color:#e0708a">LOSE when:</span> '+(sp.defeat.map(v=>'['+v.players.join(',')+'] '+(v.conditions.map(cond).join(' & ')||'Always')).join(' · ')||'—')+'</div>';
  h+='<div style="margin-top:4px"><span style="color:var(--ink-dim)">Ownership transfer:</span> give_units <b>'+sp.give.length+'</b> · set_alliance <b>'+sp.alliance+'</b> · create_props <b>'+sp.createProps+'</b> · rescue-players '+(sp.rescue.length?('P'+sp.rescue.map(p=>p+1).join(',P')):'—')+'</div>';
  for(const g of sp.give)h+='<div style="font:11px ui-monospace,monospace;color:#c8b878">  GIVE '+g.from+'→'+g.to+' : '+esc(un(g.unit))+' ×'+g.count+'</div>';
  if(sp.alliance===0&&sp.give.length===0&&sp.rescue.length)
    h+='<div style="color:var(--ink-dim);font-size:10px">→ no alliance/give — control passes via RESCUE OWNR (+create). The engine must model this as a control-transfer, not an ally.</div>';
  h+='</div></div>';
  return h;
}
function caiTriggersHtml(m){
  const tg=m.triggersFull; if(!tg||!tg.length)return '';
  const esc=t=>(t||'').replace(/[<&]/g,c=>c==='<'?'&lt;':'&amp;');
  let h='<div style="max-width:900px;text-align:left"><div class="rhead" style="margin-top:14px">🔧 All triggers — IF/DO ('+tg.length+') <span style="color:var(--ink-dim);font-size:10px">(full corpus, like trigger_corpus.py)</span></div>';
  h+='<details><summary style="cursor:pointer;color:var(--teal);font-size:12px;margin:4px 0">show / hide</summary>';
  for(const t of tg){
    h+='<div style="margin:6px 0;border-left:2px solid var(--edge);padding-left:8px">';
    h+='<div style="color:#567;font:11px ui-monospace,monospace">T'+t.index+' · P'+t.players.slice(0,6).join(',')+'</div>';
    for(const c of t.conditions)h+='<div style="font:11px ui-monospace,monospace"><span style="color:#c8b878">IF</span> '+esc(c)+'</div>';
    for(const a of t.actions)h+='<div style="font:11px ui-monospace,monospace"><span style="color:#5fe07a">DO</span> '+esc(a)+'</div>';
    h+='</div>';
  }
  h+='</details></div>';
  return h;
}
function caiBotHtml(m){
  const x=caiWalkthrough(m); const b=x.bot;
  if(!b.attacks.length&&!b.builds.length&&!x.has)return '';
  const esc=t=>(t||'').replace(/[<&]/g,c=>c==='<'?'&lt;':'&amp;');
  const chips=arr=>arr.slice(0,12).map(r=>'<span style="color:#c8b878">'+esc(r.name)+'</span>×'+r.count).join('  ')||'—';
  let h='<div style="max-width:820px;text-align:left"><div class="rhead" style="margin-top:14px">🤖 Bot behaviour (from AI scripts — bytecode)</div>';
  h+='<div style="font:12px ui-monospace,monospace;line-height:1.7">';
  h+='<div><span style="color:var(--teal)">attack:</span> '+chips(b.attacks)+'</div>';
  if(b.builds.length)h+='<div><span style="color:var(--teal)">build:</span> '+chips(b.builds)+'</div>';
  if(b.trains.length)h+='<div><span style="color:var(--teal)">trains:</span> '+chips(b.trains)+'</div>';
  h+='</div>';
  if(x.has){
    h+='<div class="rhead" style="margin-top:14px">📖 Walkthrough cross-reference — '+esc(x.e.name)+'</div>';
    h+='<div style="font-size:12px;line-height:1.7">';
    h+='<div><span style="color:var(--ink-dim)">objective:</span> '+esc(x.e.objective)+'</div>';
    h+='<div><span style="color:var(--ink-dim)">enemy faction:</span> '+esc(x.e.factions.join(', '))+'</div>';
    h+='<div><span style="color:var(--ink-dim)">wave pattern:</span> '+esc(x.e.pattern)+'</div>';
    h+='<div style="margin-top:4px"><span style="color:#5fe07a">✓ confirmed (both agree):</span> '+(x.confirmed.map(esc).join(', ')||'—')+'</div>';
    h+='<div><span style="color:#e8c828">script→ (bot fields it, not mentioned in the guide):</span> '+(x.script_only.map(esc).join(', ')||'—')+'</div>';
    h+='<div><span style="color:#e0708a">→walkthrough (seen in guide, no AI attack — trigger/defense):</span> '+(x.walkthrough_only.map(esc).join(', ')||'—')+'</div>';
    h+='<div style="color:var(--ink-dim);font-size:10px;margin-top:4px">sources: '+esc(x.e.sources.join(', '))+' · facts, not a prose copy</div>';
    h+='</div>';
  } else {
    h+='<div style="color:var(--ink-dim);font-size:11px;margin-top:8px">📖 No walkthrough facts entered for this mission yet (see assets/campaign_walkthroughs.json) — only script-derived behaviour is shown.</div>';
  }
  return h+'</div>';
}
async function caiLoad(){
  if(CAI.ready)return;
  showLoad('Loading AI scripts + campaigns…');
  try{
    CAI.ai={}; CAI.byId={};
    for(const nm of ['scripts\\aiscript.bin','scripts\\bwscript.bin']){
      try{ const b=await readGameFile(nm); const f=parseAiScripts(b,nm.split('\\').pop());
        CAI.ai[f.source]=f; for(const s of f.scripts) if(!CAI.byId[s.id])CAI.byId[s.id]=f.source; }catch(e){}
    }
    // unit names for the mission analysis (briefing speakers, unit commands)
    CAI.uname=(u=>'unit '+u); try{ const tblb=await readGameFile('rez\\stat_txt.tbl'); const st=parseTbl(tblb);
      CAI.uname=(u=>st[u]||('unit '+u)); }catch(e){}
    CAI.heroSet=new Set(); try{ const ub=await readGameFile('arr\\units.dat'); const ud=datParse('units.dat',new Uint8Array(ub));
      for(let i=0;i<228;i++){ if((ud.get('special_ability_flags',i)>>6)&1)CAI.heroSet.add(i); } }catch(e){}
    CAI.missions=[]; CAI.usage={};
    const races=['terran','zerg','protoss'], sufs=['','a','b','c','d','e','f'];
    for(const exp of [false,true]) for(const race of races)
      for(let i=0;i<=12;i++) for(const suf of sufs){
        const folder=(exp?'exp':'')+race;   // terran|zerg|protoss | expterran|expzerg|expprotoss
        const mission=race+String(i).padStart(2,'0')+suf;
        const rel=folder+'\\'+mission+'\\staredit\\scenario.chk';
        // BW MPQ: campaign\... ; SC:R CASC: locales\enus\assets\campaign\...
        const candidates=['campaign\\'+rel,'locales\\enus\\assets\\campaign\\'+rel];
        let buf=null; for(const nm of candidates){ try{ buf=await readGameFile(nm); break; }catch(e){} }
        if(!buf)continue;
        let chk; try{ chk=parseChk(buf, folder+'/'+mission); }catch(e){continue;}
        CAI.missions.push(chk);   // list EVERY campaign mission found in the packages, not only AI ones
        for(const l of chk.links){(CAI.usage[l.script]=CAI.usage[l.script]||[]).push(chk.fmtLabel);}
      }
    CAI.ready=true;
    const nsc=Object.values(CAI.ai).reduce((a,f)=>a+f.scripts.length,0);
    const withAi=CAI.missions.filter(m=>m.links.length).length;
    $('#caiSrc').textContent=nsc+' scripts · '+CAI.missions.length+' missions ('+withAi+' with AI)';
    hideLoad();
  }catch(e){hideLoad();throw e;}
}
function caiBuildList(){
  const q=($('#caiFilter').value||'').toLowerCase(), host=$('#caiList'); host.innerHTML='';
  const mk=(label,cb,on)=>{const el=document.createElement('div');el.className='mrow'+(on?' on':'');el.textContent=label;el.onclick=cb;host.appendChild(el);};
  const hd=t=>{const el=document.createElement('div');el.className='rhead';el.textContent=t;host.appendChild(el);};
  hd('Campaign missions ('+CAI.missions.length+')');
  if(!CAI.missions.length){
    const el=document.createElement('div'); el.style.cssText='padding:10px;color:var(--ink-dim);font-size:11px;line-height:1.6';
    el.innerHTML='No missions found. Campaigns live in the LARGE archives (StarCraft.mpq / BroodWar.mpq), and aiscript.bin — StarDat.mpq. Open the whole <b>BW installation folder</b> („Open folder"), so ALL .mpq become available (or the SC:R CASC folder).';
    host.appendChild(el); return;
  }
  for(const m of CAI.missions){ if(q&&!m.fmtLabel.toLowerCase().includes(q))continue;
    const nb=(m.briefing||[]).reduce((a,b)=>a+b.n_lines,0);
    const tag=[m.links.length?m.links.length+' AI':'',m.commands.length?m.commands.length+' cmd':'',nb?nb+' rep':''].filter(Boolean).join(' · ')||'—';
    mk(m.fmtLabel+'  ('+tag+')',()=>{CAI.sel={t:'mission',m};caiRender();},CAI.sel&&CAI.sel.m===m); }
  if(CAI.missionsOnly)return;   // dedicated "Campaign missions" view hides the raw AI-script list
  hd('AI scripts');
  for(const src in CAI.ai) for(const s of CAI.ai[src].scripts){ if(q&&!(s.id.toLowerCase().includes(q)))continue;
    mk(s.id+'  ('+s.ins.length+' instr)',()=>{CAI.sel={t:'script',s,src};caiRender();},CAI.sel&&CAI.sel.s===s); }
}
function caiFmtMs(ms){ return (ms/60000|0)+':'+String((ms%60000)/1000).padStart(5,'0'); }
function caiBriefingHtml(m){
  const bs=m.briefing||[]; if(!bs.length||!bs.some(b=>b.events.length))return '';
  const un=CAI.uname||(u=>'unit '+u);
  let h='<div style="max-width:820px;text-align:left"><div class="rhead" style="margin-top:14px">🎙 Briefing (dialogue timeline)</div>';
  for(const b of bs){ if(!b.events.length)continue;
    h+='<div style="color:var(--ink-dim);font-size:11px;margin:2px 0">'+b.n_lines+' lines · '+caiFmtMs(b.total_ms)+'</div>';
    for(const e of b.events){ let x='';
      if(e.action==='Transmission')x='<span style="color:#c8b878">'+un(e.speaker_unit)+'</span> <span style="color:var(--ink)">'+(e.text||'').replace(/[<&]/g,c=>c==='<'?'&lt;':'&amp;').slice(0,60)+'</span> <span style="color:#5f88c0">'+(e.wav||'').split('\\').pop()+'</span> <span style="color:var(--ink-dim)">'+(e.dur_ms/1000).toFixed(1)+'s</span>';
      else if(e.action==='ShowPortrait')x='<span style="color:#8fd15a">portrait: '+un(e.portrait_unit)+'</span>';
      else if(e.text)x='<span style="color:var(--ink-dim)">'+(e.text||'').replace(/[<&]/g,c=>c==='<'?'&lt;':'&amp;').slice(0,60)+'</span>';
      h+='<div style="font:11px ui-monospace,monospace"><span style="color:#567">'+caiFmtMs(e.t_ms)+'</span> <span style="color:var(--teal)">'+e.action+'</span> '+x+'</div>';
    } }
  return h+'</div>';
}
function caiCommandsHtml(m){
  const cs=m.commands||[]; if(!cs.length)return '';
  const un=CAI.uname||(u=>'unit '+u);
  const kinds={}; for(const c of cs)kinds[c.kind]=(kinds[c.kind]||0)+1;
  let h='<div style="max-width:820px;text-align:left"><div class="rhead" style="margin-top:14px">🎯 Unit actions from triggers ('+cs.length+': '+Object.entries(kinds).map(([k,v])=>k+' '+v).join(', ')+')</div>';
  for(const c of cs.slice(0,120)){ let tgt='';
    if(c.kind==='order')tgt=' → <span style="color:#e8c828">'+c.order+'</span> '+(c.target_loc_name||c.target_loc);
    else if(c.kind==='move')tgt=' → '+(c.dest_loc_name||c.dest_loc);
    else if(c.kind==='give')tgt=' → player '+c.to_player;
    h+='<div style="font:11px ui-monospace,monospace">T'+c.trigger+' P'+c.player+' <span style="color:var(--teal)">'+c.action+'</span> <span style="color:#c8b878">'+un(c.unit)+'</span>'+(c.count!==undefined?' ×'+c.count:'')+' @'+(c.source_loc_name||c.source_loc)+tgt+'</div>';
  }
  if(cs.length>120)h+='<div style="color:var(--ink-dim);font-size:10px">…'+(cs.length-120)+' more</div>';
  return h+'</div>';
}
function caiHeroesHtml(m){
  if(!CAI.heroSet||!CAI.heroSet.size)return '';
  const un=CAI.uname||(u=>'unit '+u); const hu={};
  for(const p of (m.placed||[])) if(CAI.heroSet.has(p.unit)){ const h=hu[p.unit]=hu[p.unit]||{placed:0,cmd:0,owners:new Set()}; h.placed++; h.owners.add(p.owner); }
  for(const c of (m.commands||[])) if(CAI.heroSet.has(c.unit)){ const h=hu[c.unit]=hu[c.unit]||{placed:0,cmd:0,owners:new Set()}; h.cmd++; }
  const ids=Object.keys(hu); if(!ids.length)return '';
  let h='<div style="max-width:820px;text-align:left"><div class="rhead" style="margin-top:14px">⭐ Heroes ('+ids.length+')</div>';
  for(const id of ids){ const v=hu[id];
    h+='<div style="font:12px ui-monospace,monospace"><span style="color:#e8c828">'+un(+id)+'</span> <span style="color:var(--ink-dim)">'
      +(v.placed?'placed×'+v.placed+(v.owners.size?' (owner '+[...v.owners].join(',')+')':''):'')+(v.cmd?(v.placed?' · ':'')+'trigger×'+v.cmd:'')+'</span></div>'; }
  return h+'</div>';
}
function caiRender(){
  caiBuildList();
  const d=$('#caiDetail');
  if(!CAI.sel){d.innerHTML='<div style="color:var(--ink-dim);padding:20px">Select a mission (campaign AI linkage) or a script (disasm + semantics + scaler).</div>';return;}
  if(CAI.sel.t==='mission'){
    let h=renderChkHtml(CAI.sel.m);
    h+='<div style="max-width:820px;text-align:left"><div class="rhead" style="margin-top:12px">Script → table + shared</div>';
    const seen={};
    for(const l of CAI.sel.m.links){ if(seen[l.script])continue; seen[l.script]=1;
      const src=CAI.byId[l.script]; const shared=(CAI.usage[l.script]||[]).filter((v,i,a)=>a.indexOf(v)===i);
      h+='<div style="font:12px ui-monospace,monospace"><span style="color:#c8b878">'+l.script+'</span> '
        +(src?'<span style="color:#5fe07a">✓ '+src+'</span>':'<span style="color:#e0708a">not found in table</span>')
        +(shared.length>1?' <span style="color:var(--ink-dim)">— shared '+shared.length+' missions (clone before editing)</span>':'')+'</div>'; }
    h+='</div>';
    h+=caiSpecHtml(CAI.sel.m);
    h+=caiBotHtml(CAI.sel.m);
    h+=caiTriggersHtml(CAI.sel.m);
    h+=caiHeroesHtml(CAI.sel.m);
    h+=caiBriefingHtml(CAI.sel.m);
    h+=caiCommandsHtml(CAI.sel.m);
    d.innerHTML=h;
  } else { d.innerHTML=renderAiHtml({source:CAI.sel.src,scripts:[CAI.sel.s]}); }
}
function caiHasSource(){ return !!(S.lastMpq||S.cascRoot||collectMpqNodes().length); }
$('#caiOpen').addEventListener('click',async()=>{
  if(!caiHasSource()){ setStatus('Open the BW installation <b>folder</b> first (all .mpq) or SC:R CASC — Campaign AI reads aiscript.bin + campaigns from them.',true); return; }
  try{ CAI.missionsOnly=false; await caiLoad(); caiRender(); $('#cai').classList.add('on'); }
  catch(e){ setStatus('Campaign AI: '+e.message,true); }
});
// Dedicated "Campaign missions": same panel, mission list only, first mission auto-selected.
$('#campOpen').addEventListener('click',async()=>{
  if(!caiHasSource()){ setStatus('Open the BW installation <b>folder</b> first (all .mpq: StarCraft/BroodWar+StarDat) or SC:R CASC — missions are filtered from them.',true); return; }
  try{ CAI.missionsOnly=true; await caiLoad();
    if(!(CAI.sel&&CAI.sel.t==='mission')&&CAI.missions.length)CAI.sel={t:'mission',m:CAI.missions[0]};
    caiRender(); $('#cai').classList.add('on'); }
  catch(e){ setStatus('Campaign missions: '+e.message,true); }
});
$('#caiClose').addEventListener('click',()=>$('#cai').classList.remove('on'));
$('#caiFilter').addEventListener('input',caiBuildList);

/* ========================= Replay (.rep) viewer =========================
   Browser twin of tools/rep/ (rep_read + rep_commands + rep_actions), byte-exact
   vs Python: container (reRS PKWARE explode / seRS zlib), the MEASURED command
   table (arg sizes solved by the tiling constraint), storm-id attribution. */
const REP={parsed:null,cmds:null,uname:(u=>'unit '+u),showLog:false};
// id -> arg size (fixed). Select families are variable (see below). MEASURED,
// matches screp byte-for-byte (names borrowed from screp, attributed in tools/rep).
const REP_SIZE={0x05:0,0x06:-2,0x07:-2,0x08:0,0x09:-1,0x0a:-1,0x0b:-1,0x0c:7,0x0d:2,
 0x0e:8,0x0f:1,0x10:0,0x11:0,0x12:4,0x13:2,0x14:9,0x15:10,0x18:0,0x19:0,0x1a:1,0x1b:0,
 0x1c:0,0x1d:2,0x1e:1,0x1f:2,0x20:2,0x21:1,0x22:1,0x23:2,0x25:1,0x26:1,0x27:0,0x28:1,
 0x29:2,0x2a:0,0x2b:1,0x2c:1,0x2d:1,0x2e:1,0x2f:4,0x30:1,0x31:0,0x32:1,0x33:0,0x34:0,
 0x35:2,0x36:0,0x37:6,0x38:0,0x39:0,0x3a:1,0x3b:1,0x3c:0,0x3d:1,0x3e:5,0x3f:7,0x40:17,
 0x41:2,0x42:1,0x43:1,0x44:2,0x45:2,0x48:12,0x54:0,0x55:1,0x56:9,0x57:1,0x58:4,0x5a:0,
 0x5b:0,0x5c:81,0x60:11,0x61:12,0x62:4,0x63:-1,0x64:-1,0x65:-1};
const REP_NAME={0x09:'select',0x0a:'select_add',0x0b:'select_remove',0x0c:'build',
 0x0e:'alliance',0x13:'hotkey',0x14:'right_click',0x15:'targeted_order',0x18:'cancel_build',
 0x19:'cancel_morph',0x1a:'stop',0x1c:'reaver_stop',0x1e:'return_cargo',0x1f:'train',
 0x20:'cancel_train',0x23:'unit_morph',0x25:'unsiege',0x26:'siege',0x27:'train_fighter',
 0x28:'unload_all',0x29:'unload',0x2a:'merge_archon',0x2b:'hold_position',0x2c:'burrow',
 0x2d:'unburrow',0x2f:'lift_off',0x30:'tech',0x32:'upgrade',0x33:'cancel_upgrade',
 0x34:'cancel_addon',0x35:'building_morph',0x36:'stim',0x57:'leave_game',0x58:'minimap_ping',
 0x5c:'chat',0x60:'right_click_121',0x61:'targeted_order_121',0x62:'unload_121',
 0x63:'select_121',0x64:'select_add_121',0x65:'select_remove_121'};
const REP_SEL2=new Set([0x09,0x0a,0x0b]),REP_SEL4=new Set([0x63,0x64,0x65]);
const REP_PRODUCE=new Set(['build','train','unit_morph','building_morph','train_fighter']);
const REP_NONEFF=new Set(['select','select_add','select_remove','select_121','select_add_121',
 'select_remove_121','keep_alive','sync','chat','vision','minimap_ping']);
function repU32(d,o){return (d[o]|(d[o+1]<<8)|(d[o+2]<<16)|(d[o+3]*16777216))>>>0;}
function repU16(d,o){return d[o]|(d[o+1]<<8);}
async function repInflate(bytes){const ds=new DecompressionStream('deflate');
  const w=ds.writable.getWriter();w.write(bytes);w.close();
  return new Uint8Array(await new Response(ds.readable).arrayBuffer());}
async function repSection(d,o,expected,useZlib){
  const nch=repU32(d,o+4);o+=8;const parts=[];let got=0;
  for(let i=0;i<nch;i++){const want=Math.min(8192,expected-got);const csz=repU32(d,o);o+=4;
    const chunk=d.subarray(o,o+csz);o+=csz;
    let dec; if(csz===want)dec=chunk; else if(useZlib)dec=await repInflate(chunk); else dec=MPQ.explode(chunk);
    parts.push(dec);got+=dec.length;}
  const total=parts.reduce((a,b)=>a+b.length,0),res=new Uint8Array(total);let p=0;
  for(const c of parts){res.set(c,p);p+=c.length;}
  return [res,o];
}
async function repParse(buf){
  const d=new Uint8Array(buf);const magic=String.fromCharCode(d[12],d[13],d[14],d[15]);
  if(magic!=='reRS'&&magic!=='seRS')throw new Error('ne .rep (magic '+magic+')');
  const useZlib=magic==='seRS';let o=0,r;
  r=await repSection(d,o,4,useZlib);o=r[1];
  if(useZlib)o+=4;
  r=await repSection(d,o,633,useZlib);const hdr=r[0];o=r[1];
  r=await repSection(d,o,4,useZlib);const cmdLen=repU32(r[0],0);o=r[1];
  r=await repSection(d,o,cmdLen,useZlib);const cmds=r[0];o=r[1];
  r=await repSection(d,o,4,useZlib);const mapLen=repU32(r[0],0);o=r[1];
  r=await repSection(d,o,mapLen,useZlib);const chk=r[0];o=r[1];
  const cstr=(off,n)=>{let s='';for(let i=0;i<n&&hdr[off+i];i++)s+=String.fromCharCode(hdr[off+i]);return s;};
  const strip=s=>s.split('').filter(c=>c.charCodeAt(0)>=32).join('').trim();
  const RN={0:'Zerg',1:'Terran',2:'Protoss',6:'Random'};
  const players=[];
  for(let i=0;i<12;i++){const po=0xA1+i*36;const name=cstr(po+11,25);if(!name)continue;
    players.push({slot:i,pid:repU32(hdr,po),storm:repU32(hdr,po+4),type:hdr[po+8],
      race:hdr[po+9],raceName:RN[hdr[po+9]]||('?'+hdr[po+9]),team:hdr[po+10],name});}
  return {magic,remastered:useZlib,frames:repU32(hdr,1),mapName:strip(cstr(0x61,32)),
    players,cmds,chk,parsedTo:o,size:d.length};
}
function repVarSize(cmd,d,ao){ if(REP_SEL2.has(cmd))return 1+d[ao]*2; if(REP_SEL4.has(cmd))return 1+d[ao]*4;
  if(cmd===0x06||cmd===0x07){let e=ao+4;while(d[e])e++;return e-ao+1;} throw new Error('var '+cmd);}
function repDecode(cmds){
  const out=[];let o=0;const n=cmds.length;
  while(o+5<=n){const frame=repU32(cmds,o);const ln=cmds[o+4];o+=5;const end=o+ln;
    let p=o; while(p<end){const player=cmds[p];const cmd=cmds[p+1];
      if(!(cmd in REP_SIZE))throw new Error('unknown command 0x'+cmd.toString(16)+' frame '+frame);
      let sz=REP_SIZE[cmd];const ao=p+2; if(sz<0)sz=repVarSize(cmd,cmds,ao);
      if(ao+sz>end)throw new Error('overrun 0x'+cmd.toString(16)+' frame '+frame);
      out.push({frame,player,cmd,name:REP_NAME[cmd]||('cmd_'+cmd.toString(16)),args:cmds.subarray(ao,ao+sz)});
      p=ao+sz;}
    o=end;}
  return [out,o];
}
function repFrameTime(f){const s=f/23.81;return (s/60|0)+':'+(s%60).toFixed(2).padStart(5,'0');}
function repUnitType(c){ if(['train','unit_morph','building_morph','cancel_train'].includes(c.name))return repU16(c.args,0);
  if(c.name==='build')return repU16(c.args,5); return null;}
function repAnalyze(rp,cmds){
  const un=REP.uname;const minutes=Math.max(rp.frames/23.81/60,1e-9);
  const who={},reps={};
  for(const p of rp.players){who[p.storm]=p;reps[p.storm]={name:p.name,race:p.raceName,acts:0,eff:0,bo:[],units:{},tech:[],ups:[],left:null,hist:{}};}
  for(const c of cmds){const pr=reps[c.player];if(!pr)continue;pr.acts++;pr.hist[c.name]=(pr.hist[c.name]||0)+1;
    if(!REP_NONEFF.has(c.name))pr.eff++;
    if(REP_PRODUCE.has(c.name)){const ut=repUnitType(c);if(ut!=null){const nm=un(ut);
      const b=pr.bo; if(!(b.length&&b[b.length-1].unit===nm&&b[b.length-1].action===c.name&&c.frame-b[b.length-1].frame<24)){
        b.push({frame:c.frame,t:repFrameTime(c.frame),action:c.name,unit:nm});pr.units[nm]=(pr.units[nm]||0)+1;}}}
    else if(c.name==='leave_game'&&pr.left===null)pr.left=c.frame;}
  const players=Object.keys(reps).map(k=>{const pr=reps[k];
    return {name:pr.name,race:pr.race,apm:+(pr.acts/minutes).toFixed(1),eapm:+(pr.eff/minutes).toFixed(1),
      acts:pr.acts,left:pr.left,leftT:pr.left!==null?repFrameTime(pr.left):null,bo:pr.bo,
      units:Object.entries(pr.units).sort((a,b)=>b[1]-a[1]),hist:Object.entries(pr.hist).sort((a,b)=>b[1]-a[1])};});
  const humans=rp.players.filter(p=>p.type===2);
  const matchup=humans.map(p=>p.raceName[0]).join('v');
  const leavers=players.filter(p=>p.left!==null).sort((a,b)=>a.left-b.left);
  return {map:rp.mapName,matchup,frames:rp.frames,duration:repFrameTime(rp.frames),
    remastered:rp.remastered,players,firstLeave:leavers.length?leavers[0].name:null};
}
function repCommandLog(rp,cmds){const un=REP.uname;const who={};for(const p of rp.players)who[p.storm]=p;
  const lines=[];for(const c of cmds){const p=who[c.player];const tag=p?p.name:('P'+c.player);let det='';
    const ut=repUnitType(c); if(REP_PRODUCE.has(c.name)&&ut!=null)det=un(ut);
    else if(REP_SEL2.has(c.cmd)||REP_SEL4.has(c.cmd))det=c.args[0]+' unit(s)';
    else if(['right_click','targeted_order','right_click_121','targeted_order_121','minimap_ping'].includes(c.name))det='@('+repU16(c.args,0)+','+repU16(c.args,2)+')';
    else if(c.name==='leave_game')det='reason '+c.args[0];
    lines.push(repFrameTime(c.frame).padEnd(9)+' '+tag.padEnd(14)+' '+c.name.padEnd(18)+' '+det);}
  return lines;}
async function repLoad(buf){
  showLoad('Decoding replay…');
  try{
    REP.uname=(u=>'unit '+u);
    try{const tb=await readGameFile('rez\\stat_txt.tbl');const st=parseTbl(tb);REP.uname=(u=>st[u]||('unit '+u));}catch(e){}
    const rp=await repParse(buf);const [cmds,consumed]=repDecode(rp.cmds);
    REP.parsed=rp;REP.cmds=cmds;REP.analysis=repAnalyze(rp,cmds);REP.consumed=consumed;
    REP.fname=(REP.fname||'replay');
    $('#repSrc').textContent=(rp.remastered?'SC:R':'classic')+' · '+cmds.length+' commands · consume '+consumed+'/'+rp.cmds.length+(consumed===rp.cmds.length?' ✓':' ⚠');
    $('#repTransBtn').style.display=rp.remastered?'':'none';
    hideLoad();repRender();
  }catch(e){hideLoad();$('#repDetail').innerHTML='<div style="color:#e0708a;padding:20px">Error: '+e.message+'</div>';}
}
function repRender(){
  const a=REP.analysis;if(!a){$('#repDetail').innerHTML='<div style="color:var(--ink-dim);padding:20px">Open a .rep file.</div>';return;}
  const esc=t=>(t||'').replace(/[<&]/g,c=>c==='<'?'&lt;':'&amp;');
  // left: summary
  let L='<div class="rhead">'+esc(a.map||'—')+'</div><div style="font-size:12px;line-height:1.7">'+
    '<div><span style="color:var(--ink-dim)">type:</span> '+(a.remastered?'SC:R (seRS)':'classic (reRS)')+'</div>'+
    '<div><span style="color:var(--ink-dim)">matchup:</span> '+esc(a.matchup)+'</div>'+
    '<div><span style="color:var(--ink-dim)">duration:</span> '+a.duration+' ('+a.frames+' frames)</div>'+
    (a.firstLeave?'<div><span style="color:var(--ink-dim)">first left:</span> <span style="color:#e0708a">'+esc(a.firstLeave)+'</span></div>':'')+'</div>';
  L+='<div class="rhead" style="margin-top:12px">Players</div>';
  for(const p of a.players){ if(!p.bo.length&&p.apm<10)continue;
    L+='<div style="font:12px ui-monospace,monospace;margin:4px 0"><span style="color:#c8b878">'+esc(p.name)+'</span> '+esc(p.race)+
      ' <span style="color:var(--teal)">APM '+p.apm+'</span> EAPM '+p.eapm+(p.leftT?' <span style="color:#e0708a">LEFT '+p.leftT+'</span>':'')+'</div>';}
  $('#repList').innerHTML=L;
  // right: build orders or command log
  if(REP.showLog){
    const lines=repCommandLog(REP.parsed,REP.cmds);
    $('#repDetail').innerHTML='<div class="rhead">Command log ('+lines.length+')</div><div class="repline">'+
      lines.slice(0,4000).map(esc).join('\n')+(lines.length>4000?'\n… '+(lines.length-4000)+' more':'')+'</div>';
    return;
  }
  let R='';
  for(const p of a.players){ if(!p.bo.length&&p.apm<10)continue;
    R+='<div class="rhead" style="margin-top:8px">'+esc(p.name)+' ('+esc(p.race)+') — build order</div>';
    R+='<div class="repline">'+p.bo.slice(0,40).map(b=>b.t.padEnd(9)+' '+b.action.padEnd(15)+' '+esc(b.unit)).join('\n')+'</div>';
    if(p.units.length){R+='<div style="font-size:11px;color:var(--ink-dim);margin:4px 0 8px">Produced: '+
      p.units.slice(0,14).map(([n,c])=>esc(n.split(' ').pop())+'×'+c).join(', ')+'</div>';}
  }
  $('#repDetail').innerHTML=R||'<div style="color:var(--ink-dim);padding:20px">No production actions.</div>';
}
/* SC:R (seRS) -> classic 1.16.1 (reRS) transcode — JS twin of tools/rep/rep_transcode.py.
   Re-container with UNCOMPRESSED chunks (no PKWARE compressor needed) + remap the _121
   commands to classic with 4-byte->2-byte unit-tag truncation (measured: tag hi16 ~0). */
const REP_REMAP={0x60:0x14,0x61:0x15,0x62:0x29,0x63:0x09,0x64:0x0a,0x65:0x0b};
function repU16b(v){return [v&255,(v>>8)&255];}
function repTranscodeCmd(player,cmd,a){
  if(cmd===0x63||cmd===0x64||cmd===0x65){const n=a[0];const out=[player,REP_REMAP[cmd],n];
    for(let i=0;i<n;i++)out.push(...repU16b(repU32(a,1+i*4)&0xFFFF));return out;}
  if(cmd===0x60)return [player,0x14,a[0],a[1],a[2],a[3],...repU16b(repU32(a,4)&0xFFFF),a[8],a[9],a[10]];
  if(cmd===0x61)return [player,0x15,a[0],a[1],a[2],a[3],...repU16b(repU32(a,4)&0xFFFF),a[8],a[9],a[10],a[11]];
  if(cmd===0x62)return [player,0x29,...repU16b(repU32(a,0)&0xFFFF)];
  return [player,cmd,...a];
}
function repU32b(v){return [v&255,(v>>8)&255,(v>>16)&255,(v>>>24)&255];}
function repTranscode(rp){
  // rebuild command section (block grouping + frames preserved)
  const cmds=rp.cmds,body=[];let o=0;const n=cmds.length;
  while(o+5<=n){const frame=repU32(cmds,o);const ln=cmds[o+4];o+=5;const end=o+ln;
    const blk=[];let p=o;
    while(p<end){const player=cmds[p],cmd=cmds[p+1];let sz=REP_SIZE[cmd];const ao=p+2;
      if(sz<0)sz=repVarSize(cmd,cmds,ao);
      blk.push(...repTranscodeCmd(player,cmd,cmds.subarray(ao,ao+sz)));p=ao+sz;}
    for(let i=0;i<Math.max(blk.length,1);i+=255){const chunk=blk.slice(i,i+255);
      body.push(...repU32b(frame),chunk.length,...chunk);if(!blk.length)break;}
    o=end;}
  const cmdBytes=new Uint8Array(body);
  // container: sections [magic "reRS" crc=0x2b7e7ea7][header 633][size cmdLen][cmds][size mapLen][chk]
  const out=[];
  const emit=(payload,crc)=>{const N=payload.length,nch=Math.max(1,Math.ceil(N/8192));
    out.push(...repU32b((crc||0)>>>0),...repU32b(nch));let q=0;
    for(let i=0;i<nch;i++){const want=Math.min(8192,N-q);out.push(...repU32b(want));
      for(let k=0;k<want;k++)out.push(payload[q+k]);q+=want;}};
  emit(new Uint8Array([0x72,0x65,0x52,0x53]),0x2b7e7ea7);   // "reRS"
  emit(rp.header);
  emit(new Uint8Array(repU32b(cmdBytes.length)));
  emit(cmdBytes);
  emit(new Uint8Array(repU32b(rp.chk.length)));
  emit(rp.chk);
  return new Uint8Array(out);
}
$('#repOpen').addEventListener('click',()=>{ $('#rep').classList.add('on'); if(!REP.analysis)repRender(); });
$('#repClose').addEventListener('click',()=>$('#rep').classList.remove('on'));
$('#repLogBtn').addEventListener('click',()=>{REP.showLog=!REP.showLog;repRender();});
$('#repInput').addEventListener('change',async e=>{const f=e.target.files[0];if(!f)return;
  REP.showLog=false;REP.fname=f.name.replace(/\.rep$/i,'');repLoad(await f.arrayBuffer());});
$('#repTransBtn').addEventListener('click',()=>{
  if(!REP.parsed||!REP.parsed.remastered){setStatus('Transcoding only for SC:R (seRS) replays.',true);return;}
  try{ const out=repTranscode(REP.parsed);
    const url=URL.createObjectURL(new Blob([out],{type:'application/octet-stream'}));
    dl(url,(REP.fname||'replay')+'.116.rep');URL.revokeObjectURL(url);
    setStatus('Converted to 1.16.1: <b>'+(REP.fname||'replay')+'.116.rep</b> ('+out.length+' B). Test the BW launch yourself.');
  }catch(e){setStatus('Transcoding error: '+e.message,true);}
});

/* ========================= Reference: cheats (wiki) =========================
   Static library — twin of assets/cheats.json. Public single-player codes. */
const CHEATS=[
 {code:"show me the money",effect:"10 000 minerals + 10 000 vespene gas",cat:"resources"},
 {code:"whats mine is mine",effect:"Free minerals (adds)",cat:"resources"},
 {code:"breathe deep",effect:"Free vespene gas (adds)",cat:"resources"},
 {code:"power overwhelming",effect:"God mode — your units/buildings are invulnerable",cat:"combat"},
 {code:"operation cwal",effect:"Near-instant build/train/upgrade",cat:"production"},
 {code:"the gathering",effect:"Unlimited energy — spells cost no mana",cat:"combat"},
 {code:"something for nothing",effect:"Grants all upgrades (attack/armor/…)",cat:"tech"},
 {code:"medieval man",effect:"Free upgrades — no cost",cat:"tech"},
 {code:"modify the phase variance",effect:"Lets you build all buildings (ignores the tech tree)",cat:"tech"},
 {code:"food for thought",effect:"Build units above the supply/psi/control limit",cat:"production"},
 {code:"black sheep wall",effect:"Reveals the whole map (removes the unexplored fog)",cat:"visibility"},
 {code:"war aint what it used to be",effect:"Disables the fog of war (permanent visibility of explored areas)",cat:"visibility"},
 {code:"there is no cow level",effect:"Instantly wins (completes) the current mission",cat:"mission"},
 {code:"game over man",effect:"Ends the game in a loss",cat:"mission"},
 {code:"staying alive",effect:"Disables the victory/defeat conditions — the mission never ends",cat:"mission"},
 {code:"ophelia",effect:"Enables mission skipping; then type the mission name (e.g. 'terran5', 'zerg3', 'protoss7')",cat:"mission"},
 {code:"radio free zerg",effect:"Plays a hidden Zerg song — only works while playing Zerg",cat:"fun"}];
function cheatRender(){
  const q=($('#cheatFilter').value||'').toLowerCase();
  const rows=CHEATS.filter(c=>!q||c.code.includes(q)||c.effect.toLowerCase().includes(q)||c.cat.includes(q));
  const esc=t=>(t||'').replace(/[<&]/g,c=>c==='<'?'&lt;':'&amp;');
  let h='<div style="color:var(--ink-dim);font-size:11px;margin-bottom:10px">Single-player: press Enter, type the code, Enter again. Case-insensitive. There are NO cheats in multiplayer.</div>';
  h+='<table><thead><tr><th>Code</th><th>Effect</th><th>Category</th></tr></thead><tbody>';
  for(const c of rows) h+='<tr><td><code>'+esc(c.code)+'</code></td><td>'+esc(c.effect)+'</td><td>'+esc(c.cat)+'</td></tr>';
  h+='</tbody></table>';
  h+='<div style="color:var(--ink-dim);font-size:10px;margin-top:8px">Sources: gamefaqs.gamespot.com · starcraft.fandom.com · staredit-network.fandom.com (assets/cheats.json).</div>';
  $('#cheatBody').innerHTML=h; $('#cheatSrc').textContent=rows.length+'/'+CHEATS.length+' codes';
}
$('#cheatOpen').addEventListener('click',()=>{ $('#cheat').classList.add('on'); cheatRender(); });
$('#cheatClose').addEventListener('click',()=>$('#cheat').classList.remove('on'));
$('#cheatFilter').addEventListener('input',cheatRender);

/* ================= Campaign walkthrough (spreadsheet) =================
   One row per mission; columns from the oracle fields (spec/briefing/bot/heroes).
   Reuses CAI (loads all campaign missions). Click → full mission in the Campaign analyzer.
   CSV eksportas = spreadsheet. */
function cwtRows(){
  const rows=[];
  for(const m of (CAI.missions||[])){
    const sp=m.spec||{};
    const bo=(m.briefing||[]).reduce((a,b)=>a+b.n_lines,0);
    const bot=caiMissionBot(m);
    const un=CAI.uname||(u=>'unit '+u);
    const shortCond=arr=>(arr||[]).map(t=>(t.conditions||[]).map(c=>{
      if(['Bring','Command','Accumulate','Kills','Deaths','Opponents'].includes(c.t))return c.t+' '+c.cmp+' '+c.qty+' '+un(c.unit);
      if(c.t==='CountdownTimer'||c.t==='ElapsedTime')return c.t+' '+c.qty+'s';
      return c.t;}).join(' & ')).join(' | ');
    rows.push({
      mission:m.fmtLabel,
      objectives:(sp.objectives||[]).join(' ').replace(/\s+/g,' ').trim().slice(0,120),
      win:shortCond(sp.victory).slice(0,80),
      lose:shortCond(sp.defeat).slice(0,80),
      transfer:sp?('give '+(sp.give?sp.give.length:0)+' / ally '+(sp.alliance||0)+' / rescue '+((sp.rescue||[]).length?sp.rescue.join(','):'-')):'',
      heroes:Object.keys(caiHeroSetOf(m)).join(', '),
      attack:bot.attacks.slice(0,4).map(r=>r.name.split(' ').pop()+'×'+r.count).join(' '),
      ai:m.links.length, cmds:(m.commands||[]).length, brief:bo
    });
  }
  return rows;
}
function caiHeroSetOf(m){ // heroes present (pre-placed or commanded), names
  const un=CAI.uname||(u=>'unit '+u); const hs={};
  if(CAI.heroSet){ for(const p of (m.placed||[])) if(CAI.heroSet.has(p.unit))hs[un(p.unit)]=1;
    for(const c of (m.commands||[])) if(CAI.heroSet.has(c.unit))hs[un(c.unit)]=1; }
  return hs;
}
function cwtRender(){
  const q=($('#cwtFilter').value||'').toLowerCase();
  const esc=t=>(''+(t==null?'':t)).replace(/[<&]/g,c=>c==='<'?'&lt;':'&amp;');
  const rows=cwtRows().filter(r=>!q||r.mission.toLowerCase().includes(q)||r.objectives.toLowerCase().includes(q));
  CWT.rows=rows;
  let h='<table><thead><tr>'+
    ['Mission','Objectives','WIN when','LOSE when','Transfer','Heroes','Enemy attack','AI','Cmd','Repl.'].map(x=>'<th>'+x+'</th>').join('')+
    '</tr></thead><tbody>';
  for(let i=0;i<rows.length;i++){ const r=rows[i];
    h+='<tr data-i="'+i+'" style="cursor:pointer">'+
      ['mission','objectives','win','lose','transfer','heroes','attack','ai','cmds','brief'].map(k=>'<td>'+esc(r[k])+'</td>').join('')+'</tr>';
  }
  h+='</tbody></table>';
  $('#cwtBody').innerHTML=h; $('#cwtSrc').textContent=rows.length+' missions · click a row → full mission';
  $('#cwtBody').querySelectorAll('tr[data-i]').forEach(tr=>tr.onclick=()=>{
    const m=CAI.missions.find(x=>x.fmtLabel===rows[+tr.dataset.i].mission);
    if(m){ CAI.sel={t:'mission',m}; CAI.missionsOnly=false; $('#cwt').classList.remove('on'); $('#cai').classList.add('on'); caiRender(); }
  });
}
const CWT={rows:[]};
function cwtCsv(){
  const cols=['mission','objectives','win','lose','transfer','heroes','attack','ai','cmds','brief'];
  const esc=v=>'"'+(''+(v==null?'':v)).replace(/"/g,'""')+'"';
  const lines=[cols.join(',')].concat((CWT.rows||[]).map(r=>cols.map(k=>esc(r[k])).join(',')));
  const url=URL.createObjectURL(new Blob(['﻿'+lines.join('\r\n')],{type:'text/csv'}));
  dl(url,'campaign-walkthrough.csv'); URL.revokeObjectURL(url);
  setStatus('Eksportuota <b>campaign-walkthrough.csv</b> ('+(CWT.rows||[]).length+' missions).');
}
$('#cwtOpen').addEventListener('click',async()=>{
  if(!caiHasSource()){ setStatus('Open the BW installation folder or SC:R CASC first.',true); return; }
  try{ await caiLoad(); cwtRender(); $('#cwt').classList.add('on'); }
  catch(e){ setStatus('Walkthrough: '+e.message,true); }
});
$('#cwtClose').addEventListener('click',()=>$('#cwt').classList.remove('on'));
$('#cwtFilter').addEventListener('input',cwtRender);
$('#cwtCsv').addEventListener('click',cwtCsv);

/* ========================= HUD v2 layout editor =========================
   Panel geometry (ui/ui.h formulas). Drag a panel
   — output: normalized rects + regenerated hud2_* formulas. */
const HUD={W:2560,H:1600,scale:0.4,panels:[],drag:null,sel:null,locked:false,
  font:{name:30,detector:20,rank:22,kills:22},   // Unit Display font sizes, px @basis
  history:[],histIdx:-1};
// ---- undo/redo: snapshot panels + fonts before each committed change ----
function hudState(){ return JSON.stringify({panels:HUD.panels,font:HUD.font}); }
function hudApply(js){ const st=JSON.parse(js); HUD.panels=st.panels; HUD.font=st.font;
  HUD.sel=null; ['name','detector','rank','kills'].forEach(k=>{const el=$('#hudFont'+k[0].toUpperCase()+k.slice(1)); if(el)el.value=HUD.font[k];});
  hudDraw(); hudOut(); }
function hudCommit(){ HUD.history=HUD.history.slice(0,HUD.histIdx+1); HUD.history.push(hudState());
  if(HUD.history.length>60)HUD.history.shift(); HUD.histIdx=HUD.history.length-1; hudUpdateUndo(); }
function hudUndo(){ if(HUD.histIdx>0){ HUD.histIdx--; hudApply(HUD.history[HUD.histIdx]); hudUpdateUndo(); } }
function hudRedo(){ if(HUD.histIdx<HUD.history.length-1){ HUD.histIdx++; hudApply(HUD.history[HUD.histIdx]); hudUpdateUndo(); } }
function hudUpdateUndo(){ const u=$('#hudUndo'),r=$('#hudRedo');
  if(u)u.disabled=HUD.histIdx<=0; if(r)r.disabled=HUD.histIdx>=HUD.history.length-1; }
// Every panel/element from the ui.h layout, positioned from the ui.h
// formulas. `grp` groups them for colour-coding; `fn` is the ui.h function the
// output regenerates; `resizable`/`production`/etc. drive the preview.
function hudDefault(W,H){
  const bar=Math.max(Math.min(H*0.24,H*0.32),96);      // hud2_bar_h 24% [96..32%]
  const edge=Math.max(W*0.04,12), mar=Math.round(4*H/1600);  // hud2_edge / margin
  const grpH=bar*0.15, pad=bar*0.05, utilH=Math.round(30*H/1600);
  const bottom=H-bar-mar;
  const P=[];
  const add=o=>{P.push(o);return o;};
  // ---- bottom-bar panels ----
  const mm=add({key:'minimap',label:'Minimap',grp:'bar',fn:'hud2_minimap_panel',x:edge,y:bottom,w:bar,h:bar});
  const card=add({key:'card',label:'Command card 3×3',grp:'bar',fn:'hud2_card_panel',x:W-edge-bar,y:bottom,w:bar,h:bar,card:1});
  // Portrait = a SQUARE (the SMK video); the LAN latency strip sits below it, so
  // the two never overlap. side = bar*0.55.
  const pside=bar*0.55;
  const port=add({key:'portrait',label:'Portrait (SMK)',grp:'bar',fn:'hud2_portrait_panel',w:pside,h:pside});
  port.x=card.x-mar*3-port.w; port.y=bottom+bar*0.22;
  add({key:'menu',label:'MENU',grp:'bar',fn:'hud2_menu_panel',x:port.x,y:bottom,w:port.w,h:bar*0.2});
  add({key:'latency',label:'LAN latency',grp:'bar',fn:'hud2_latency_strip',x:port.x,y:port.y+pside,w:port.w,h:(bottom+bar)-(port.y+pside),latency:1});
  const unit=add({key:'unit',label:'Unit Display',grp:'bar',fn:'hud2_unit_panel',x:mm.x+mm.w+mar*3,y:bottom+grpH,w:(port.x-mar*3)-(mm.x+mm.w+mar*3),h:bar-grpH});
  // ---- Unit Display inner elements (draggable within) ----
  add({key:'wireframe',label:'Wireframe',grp:'unit',fn:'hud2_wireframe_box',x:unit.x+pad,y:unit.y+pad,w:bar*0.4,h:bar*0.4,resizable:1});
  add({key:'name',label:'Name / Rank / Kills',grp:'unit',fn:'draw_hud2_unit_display (rx)',x:unit.x+bar*0.45,y:unit.y+pad,w:bar*0.5,h:bar*0.36,nameblock:1});
  add({key:'status',label:'HP / SH / EN',grp:'unit',fn:'draw_hud2_unit_display (wcx)',x:unit.x+pad,y:unit.y+bar*0.45,w:bar*0.4,h:bar*0.3,status:1});
  add({key:'production',label:'Production',grp:'unit',fn:'production_slot_rects',x:unit.x+bar*0.45,y:unit.y+bar*0.28,w:bar*0.62,h:bar*0.22,resizable:1,production:1});
  add({key:'badges',label:'Equipment badges',grp:'unit',fn:'draw_hud2_unit_display (es)',x:unit.x+unit.w-bar*0.34,y:unit.y+unit.h-bar*0.18,w:bar*0.3,h:bar*0.14,badges:1});
  // ---- util row (PING/IDLE/ARMY) above minimap ----
  add({key:'util',label:'PING / IDLE / ARMY',grp:'strip',fn:'hud2_util_cell',x:mm.x,y:mm.y-utilH-2,w:mm.w,h:utilH,util:1});
  // ---- groups strip 0-9 + QUEUE above unit display ----
  add({key:'groups',label:'Groups 0–9 + QUEUE',grp:'strip',fn:'hud2_groups_strip',x:unit.x,y:unit.y-grpH,w:unit.w,h:grpH,groups:1});
  // ---- top overlays ----
  add({key:'fps',label:'FPS',grp:'top',fn:'draw_fps',x:mar+2,y:mar,w:W*0.06,h:utilH});
  add({key:'timer',label:'Time',grp:'top',fn:'draw_game_timer',x:W/2-W*0.05,y:mar,w:W*0.1,h:utilH});
  add({key:'apm',label:'APM',grp:'top',fn:'draw_apm',x:W/2-W*0.04,y:mar+utilH+2,w:W*0.08,h:utilH*0.8});
  add({key:'resources',label:'Resources',grp:'top',fn:'draw_hud2_resources',x:W-edge-W*0.18,y:mar,w:W*0.18,h:H*0.03});
  return P.map(p=>({...p,x:Math.round(p.x),y:Math.round(p.y),w:Math.round(p.w),h:Math.round(p.h)}));
}
const HUD_GRP_FILL={bar:'#20282c',unit:'#182430',strip:'#141a20',top:'#12181c'};
function hudFit(){ const maxW=Math.min(1100,window.innerWidth-420), maxH=window.innerHeight-140;
  HUD.scale=Math.min(maxW/HUD.W,maxH/HUD.H); }
function hudDrawProduction(g,p,s){
  // Row 1: active slot on the left; a status word (training/warping/morphing/
  // researching/evolving) sits ABOVE a progress bar. Row 2: 4 queue slots
  // (build_queue is static_vector<...,5> = 1 active + 4 waiting).
  const x=p.x*s,y=p.y*s,w=p.w*s,h=p.h*s, gap=Math.max(2,w*0.015);
  const rowH=(h-gap)/2, aslot=Math.min(rowH,w*0.28);
  // active slot
  g.fillStyle='#101820'; g.fillRect(x,y,aslot,aslot);
  g.strokeStyle='#40c0d0'; g.lineWidth=1; g.strokeRect(x,y,aslot,aslot);
  // status word + progress bar (to the right of / across the active slot area)
  const barX=x+aslot+gap, barW=w-aslot-gap, pbH=Math.max(3,rowH*0.18);
  g.fillStyle='#c8b878'; g.font=Math.max(8,rowH*0.34)+'px ui-monospace,monospace'; g.textBaseline='alphabetic';
  g.fillText('training…', barX, y+rowH*0.55);
  g.fillStyle='#0e141a'; g.fillRect(barX,y+rowH-pbH,barW,pbH);
  g.fillStyle='#40ff70'; g.fillRect(barX,y+rowH-pbH,barW*0.6,pbH);   // 60% progress
  g.textBaseline='top';
  // row 2: 4 queue slots
  const qslot=Math.min(rowH,(w-gap*3)/4), qy=y+rowH+gap;
  for(let i=0;i<4;i++){ const qx=x+i*(qslot+gap);
    g.fillStyle='#0e141a'; g.fillRect(qx,qy,qslot,qslot);
    g.strokeStyle='#405060'; g.strokeRect(qx,qy,qslot,qslot); }
}
function hudCardCell(){                          // 3×3 card icon size in screen px
  const c=HUD.panels.find(p=>p.key==='card'); if(!c)return 40;
  return (c.w-(c.w/20)*4)/3;                     // matches hudCells2d geometry
}
function hudDrawBadges(g,p,s){
  // equipment badges = grey cmdicons at the SAME size as the 3×3 card icons,
  // each with a small level badge (armour / shield / weapon).
  const cell=hudCardCell()*s, gap=Math.max(2,cell*0.12), x=p.x*s, y=p.y*s;
  for(let i=0;i<3;i++){ const cx=x+i*(cell+gap);
    g.fillStyle='#141a1e'; g.fillRect(cx,y,cell,cell);
    g.strokeStyle='#4c5860'; g.lineWidth=1; g.strokeRect(cx,y,cell,cell);
    g.fillStyle='#c8b878'; g.font=Math.max(7,cell*0.28)+'px ui-monospace,monospace';
    g.fillText(String(i+1),cx+cell-cell*0.34,y+cell-cell*0.34);   // level badge
  }
}
function hudDrawName(g,p,s){
  // name (large, centred) then rank and "Kills: N" on their own lines, each at
  // its own editable font size (HUD.font, px @basis).
  const cx=(p.x+p.w/2)*s, y=p.y*s; let cy=y+2;
  const line=(txt,px,col)=>{ const fs=Math.max(6,px*s); g.font=fs+'px ui-monospace,monospace';
    g.fillStyle=col; g.textAlign='center'; g.fillText(txt,cx,cy+fs*0.9); g.textAlign='left'; cy+=fs*1.15; };
  line('Unit Name',HUD.font.name,'#d8dee2');
  line('Detector',HUD.font.detector,'#e8c828');   // yellow status line
  line('Rank',HUD.font.rank,'#c8b878');
  line('Kills: 12',HUD.font.kills,'#c8b878');
}
function hudCells(g,p,s,n,label,color){       // n equal cells across the panel
  const x=p.x*s,y=p.y*s,w=p.w*s,h=p.h*s,gap=Math.max(1,w*0.006),cw=(w-gap*(n+1))/n;
  for(let i=0;i<n;i++){ const cx=x+gap+i*(cw+gap);
    g.fillStyle='#1c242c'; g.fillRect(cx,y+1,cw,h-2);
    g.strokeStyle='#3a444c'; g.strokeRect(cx,y+1,cw,h-2); }
  if(color){g.fillStyle=color;g.font='9px ui-monospace,monospace';g.fillText(label,x+3,y+h/2-4);}
}
function hudDraw(){
  const cv=$('#hudCanvas'), s=HUD.scale; cv.width=HUD.W*s; cv.height=HUD.H*s;
  const g=cv.getContext('2d');
  g.fillStyle='#16202a'; g.fillRect(0,0,cv.width,cv.height);
  g.strokeStyle='#233240'; for(let i=1;i<4;i++){g.beginPath();g.moveTo(0,cv.height*i/4);g.lineTo(cv.width,cv.height*i/4);g.stroke();}
  g.textBaseline='top';
  for(const p of HUD.panels){
    const on=p===HUD.sel;
    g.fillStyle=on?'#183040':(HUD_GRP_FILL[p.grp]||'#20282c'); g.fillRect(p.x*s,p.y*s,p.w*s,p.h*s);
    g.strokeStyle=on?'#40c0d0':(p.grp==='unit'?'#3a5a70':'#4a5458'); g.lineWidth=on?2:1; g.strokeRect(p.x*s,p.y*s,p.w*s,p.h*s);
    if(p.production) hudDrawProduction(g,p,s);
    else if(p.card){ hudCells2d(g,p,s,3,3); }
    else if(p.util) hudCells(g,p,s,3,'',null);
    else if(p.groups) hudCells(g,p,s,11,'',null);
    else if(p.badges) hudDrawBadges(g,p,s);
    else if(p.latency){ const x=p.x*s,y=p.y*s,w=p.w*s,h=p.h*s;
      g.fillStyle='#0e141a'; g.fillRect(x+2,y+h*0.45,w-4,h*0.4);
      g.fillStyle='#40c060'; g.fillRect(x+2,y+h*0.45,(w-4)*0.7,h*0.4);   // green latency fill
      g.fillStyle='#6a7480'; g.font=Math.max(7,h*0.28)+'px ui-monospace,monospace'; g.fillText('latency',x+3,y+2); }
    else if(p.nameblock) hudDrawName(g,p,s);
    else if(p.status){ const x=p.x*s,y=p.y*s,w=p.w*s; const bars=[['#30f030','120/120'],['#5cb0ff','60/60'],['#c890ff','50/50']];
      bars.forEach((b,i)=>{g.fillStyle=b[0];g.font='9px ui-monospace,monospace';g.textAlign='center';g.fillText(b[1],x+w/2,y+6+i*11);g.textAlign='left';}); }
    else if(p.key==='wireframe'){ g.strokeStyle='#30506a'; g.strokeRect(p.x*s+3,p.y*s+3,p.w*s-6,p.h*s-6);
      g.fillStyle='#40b0a0'; g.font='10px ui-monospace,monospace'; g.fillText('WF',p.x*s+6,p.y*s+p.h*s/2-6); }
    if(!p.nameblock){ g.fillStyle=on?'#cfe0ee':'#9fb0c0'; g.font='11px ui-monospace,monospace'; g.fillText(p.label,p.x*s+4,p.y*s+3); }
    if(p.resizable){                             // resize handle (bottom-right)
      const hx=(p.x+p.w)*s, hy=(p.y+p.h)*s;
      g.fillStyle=on?'#40c0d0':'#66788a'; g.beginPath();
      g.moveTo(hx,hy); g.lineTo(hx-9,hy); g.lineTo(hx,hy-9); g.closePath(); g.fill();
    }
  }
}
function hudCells2d(g,p,s,cols,rows){          // grid (command card 3×3)
  const x=p.x*s,y=p.y*s,w=p.w*s,h=p.h*s,gp=w/20,cw=(w-gp*(cols+1))/cols,ch=(h-gp*(rows+1))/rows;
  g.strokeStyle='#4a5458';
  for(let r=0;r<rows;r++)for(let c=0;c<cols;c++){g.fillStyle='#1c242c';
    const cx=x+gp+c*(cw+gp),cy=y+gp+r*(ch+gp); g.fillRect(cx,cy,cw,ch); g.strokeRect(cx,cy,cw,ch);}
}
function hudFormula(p){                          // one-line summary for the side panel
  const fx=(v,tot)=>(v/tot*100).toFixed(1)+'%';
  return p.fn+' → x='+fx(p.x,HUD.W)+' y='+fx(p.y,HUD.H)+' w='+fx(p.w,HUD.W)+' h='+fx(p.h,HUD.H);
}
function hudCpp(p){                              // a ui.h hud2_* function body
  const f=(v,d)=>(v/d).toFixed(4);
  return 'rect '+p.fn+'() {   // '+p.label+'\n'
    +'  return { int(screen_width*'+f(p.x,HUD.W)+'), int(screen_height*'+f(p.y,HUD.H)+'),\n'
    +'           int(screen_width*'+f(p.w,HUD.W)+'), int(screen_height*'+f(p.h,HUD.H)+') };\n}';
}
function hudOut(){
  const obj={version:2,screen:{w:HUD.W,h:HUD.H},
    note:'Normalized rects (0..1) per element + regenerated ui.h hud2_* bodies. Handles: bar_h=24% [96..32%], edge=4% [min 12px], margin=4px.',
    handles:{bar_h_pct:0.24,bar_h_min_px:96,edge_pct:0.04,edge_min_px:12,margin_px:4},
    unit_display_fonts_px:{name:HUD.font.name,detector:HUD.font.detector,rank:HUD.font.rank,kills:HUD.font.kills},
    elements:{}};
  for(const p of HUD.panels) obj.elements[p.key]={fn:p.fn,group:p.grp,
    x:+(p.x/HUD.W).toFixed(4),y:+(p.y/HUD.H).toFixed(4),w:+(p.w/HUD.W).toFixed(4),h:+(p.h/HUD.H).toFixed(4)};
  // one C++ body per unique ui.h function (skip the draw_* text-anchored ones)
  const seen={}, cpp=[];
  for(const p of HUD.panels){ if(p.fn.startsWith('draw_')||seen[p.fn])continue; seen[p.fn]=1; cpp.push(hudCpp(p)); }
  $('#hudJson').value='// ==== ui.h hud2_* (paste + adapt; basis '+HUD.W+'×'+HUD.H+') ====\n'
    +cpp.join('\n\n')+'\n\n// ==== JSON ====\n'+JSON.stringify(obj,null,2);
  if(HUD.sel){ $('#hudSel').textContent=HUD.sel.label+'  ['+HUD.sel.fn+']';
    $('#hudProps').innerHTML='x '+HUD.sel.x+' · y '+HUD.sel.y+' · '+HUD.sel.w+'×'+HUD.sel.h+' px<br><span style="color:#8a93a0">'+hudFormula(HUD.sel)+'</span>'; }
}
function hudReset(){ [HUD.W,HUD.H]=$('#hudPreset').value.split('x').map(Number); HUD.panels=hudDefault(HUD.W,HUD.H); HUD.sel=null; hudFit(); hudDraw(); hudOut();
  HUD.history=[hudState()]; HUD.histIdx=0; hudUpdateUndo(); }
(function hudDragInit(){
  const cv=$('#hudCanvas');
  const pos=(e)=>{const r=cv.getBoundingClientRect(),s=HUD.scale;return {mx:(e.clientX-r.left)/s,my:(e.clientY-r.top)/s};};
  const at=(e)=>{const {mx,my}=pos(e);
    for(let i=HUD.panels.length-1;i>=0;i--){const p=HUD.panels[i];if(mx>=p.x&&mx<=p.x+p.w&&my>=p.y&&my<=p.y+p.h)return {p,mx,my};}return null;};
  cv.addEventListener('mousedown',e=>{const h=at(e);if(!h)return; HUD.sel=h.p;
    if(HUD.locked){ hudDraw(); hudOut(); return; }    // selection only when locked
    const handle=12/HUD.scale;
    if(h.p.resizable && h.mx>h.p.x+h.p.w-handle && h.my>h.p.y+h.p.h-handle){
      HUD.drag={p:h.p,mode:'resize',moved:false};
    } else { HUD.drag={p:h.p,mode:'move',ox:h.mx-h.p.x,oy:h.my-h.p.y,moved:false}; }
    hudDraw();hudOut();});
  window.addEventListener('mousemove',e=>{if(!HUD.drag)return; const {mx,my}=pos(e), p=HUD.drag.p;
    HUD.drag.moved=true;
    if(HUD.drag.mode==='resize'){
      p.w=Math.max(24,Math.min(HUD.W-p.x,Math.round(mx-p.x)));
      p.h=Math.max(16,Math.min(HUD.H-p.y,Math.round(my-p.y)));
    } else {
      p.x=Math.max(0,Math.min(HUD.W-p.w,Math.round(mx-HUD.drag.ox)));
      p.y=Math.max(0,Math.min(HUD.H-p.h,Math.round(my-HUD.drag.oy)));
    }
    hudDraw();hudOut();});
  window.addEventListener('mouseup',()=>{ if(HUD.drag&&HUD.drag.moved)hudCommit(); HUD.drag=null;});
  cv.addEventListener('mousemove',e=>{const h=at(e); const handle=12/HUD.scale;
    cv.style.cursor=HUD.locked?(h?'not-allowed':'default'):((h&&h.p.resizable&&h.mx>h.p.x+h.p.w-handle&&h.my>h.p.y+h.p.h-handle)?'nwse-resize':(h?'move':'default'));});
})();
$('#hudOpen').addEventListener('click',()=>{ hudReset(); $('#hud').classList.add('on'); });
$('#hudClose').addEventListener('click',()=>$('#hud').classList.remove('on'));
$('#hudReset').addEventListener('click',hudReset);
$('#hudPreset').addEventListener('change',hudReset);
$('#hudUndo').addEventListener('click',hudUndo);
$('#hudRedo').addEventListener('click',hudRedo);
$('#hudLock').addEventListener('change',e=>{HUD.locked=e.target.checked;});
document.addEventListener('keydown',e=>{ if(!$('#hud').classList.contains('on'))return;
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault(); e.shiftKey?hudRedo():hudUndo();}
  else if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='y'){e.preventDefault(); hudRedo();}});
[['hudFontName','name'],['hudFontDetector','detector'],['hudFontRank','rank'],['hudFontKills','kills']].forEach(([id,k])=>
  $('#'+id).addEventListener('change',e=>{HUD.font[k]=+e.target.value||HUD.font[k];hudDraw();hudOut();hudCommit();}));
[['hudFontName','name'],['hudFontDetector','detector'],['hudFontRank','rank'],['hudFontKills','kills']].forEach(([id,k])=>
  $('#'+id).addEventListener('input',e=>{HUD.font[k]=+e.target.value||HUD.font[k];hudDraw();hudOut();}));
$('#hudExport').addEventListener('click',()=>{
  hudOut();   // ensure current
  const url=URL.createObjectURL(new Blob([$('#hudJson').value],{type:'text/plain'}));
  dl(url,'hud2-layout.txt'); URL.revokeObjectURL(url);
  setStatus('Eksportuota <b>hud2-layout.txt</b> (hud2_* C++ formulas + JSON).');
});

/* ========================= Mod Builder ========================= */
const MOD={files:[]};   // [{path (game path), source, data:Uint8Array}]
function modNorm(p){ return p.replace(/\\/g,'/').replace(/^\/+/,'').toLowerCase(); }
function modAdd(path,source,data){
  path=modNorm(path);
  MOD.files=MOD.files.filter(f=>f.path!==path);   // replace same path
  MOD.files.push({path,source,data}); modRender();
}
function modValidateAll(){
  const warns=[];
  for(const f of MOD.files){
    try{
      if(/aiscript\.bin$|bwscript\.bin$/.test(f.path)){
        const d=parseAiScripts(f.data.buffer.slice(f.data.byteOffset,f.data.byteOffset+f.data.byteLength),f.path);
        const bad=d.scripts.filter(s=>s.err);
        if(bad.length)warns.push(f.path+': '+bad.length+' scripts do not decode');
      } else if(/\.grp$/.test(f.path)){
        const dv=new DataView(f.data.buffer,f.data.byteOffset);
        const fc=dv.getUint16(0,true),w=dv.getUint16(2,true),h=dv.getUint16(4,true);
        if(!(fc>0&&fc<10000&&w>0&&w<=800&&h>0&&h<=800))warns.push(f.path+': suspicious GRP header');
      }
    }catch(e){ warns.push(f.path+': validation error '+e.message); }
  }
  return warns;
}
function modZipName(){ return ($('#modId').value.trim()||'mod').replace(/[^A-Za-z0-9._-]/g,'_'); }
function modManifest(){   // ONLY launcher-read fields (no id/priority — engine
  // takes id from the zip name, priority from --mods order)
  const m={name:$('#modName').value||'Mod', version:$('#modVer').value||'1.0',
    type:$('#modType').value};
  const au=$('#modAuthor').value.trim(); if(au)m.author=au;
  const ds=$('#modDesc').value.trim(); if(ds)m.description=ds;
  return m;
}
function modRender(){
  const tb=$('#modFiles'); tb.innerHTML=''; $('#modCount').textContent=MOD.files.length;
  for(let i=0;i<MOD.files.length;i++){ const f=MOD.files[i];
    const tr=document.createElement('tr');
    tr.innerHTML='<td>data/'+f.path+'</td><td style="color:var(--ink-dim)">'+f.source+'</td><td>'+f.data.length+' B</td>'
      +'<td class="rm" title="remove">✕</td>';
    tr.querySelector('.rm').onclick=()=>{MOD.files.splice(i,1);modRender();};
    tb.appendChild(tr);
  }
  const warns=modValidateAll();
  const wfNote=MOD.files.some(f=>f.path==='wireframe-colors.json')
    ?['wireframe-colors.json: the engine DOES NOT READ IT YET (needs an engine feature)']:[];
  const allw=warns.concat(wfNote);
  $('#modWarn').innerHTML=allw.length?('⚠ '+allw.join(' · ')):'';
  const man=modManifest(), zn=modZipName();
  $('#modPreview').value='// '+zn+'.zip  (id = file name; contents at the root)\n'
    +'mod.json:\n'+JSON.stringify(man,null,2)+'\n\n// contents:\n'
    +MOD.files.map(f=>'  data/'+f.path+'  ('+f.data.length+' B)').join('\n');
}
$('#modOpen').addEventListener('click',()=>{ modRender(); $('#mod').classList.add('on'); });
$('#modClose').addEventListener('click',()=>$('#mod').classList.remove('on'));
['#modId','#modName','#modVer','#modDesc','#modType','#modAuthor'].forEach(id=>$(id).addEventListener('input',modRender));
$('#modAddWf').addEventListener('click',()=>{
  if(!WF.ready){ setStatus('Open the Wireframe tester first (so there are colours).',true); return; }
  const data=new TextEncoder().encode(JSON.stringify(wfJsonObject(),null,2));
  modAdd('wireframe-colors.json','wireframe ⚠ (engine does not read it yet)',data);
  setStatus('Added wireframe-colors.json — ⚠ the engine DOES NOT READ IT YET; an engine feature is needed for it to take effect.',true);
});
$('#modAiFile').addEventListener('change',async e=>{ const file=e.target.files[0]; if(!file)return;
  const buf=await file.arrayBuffer(); const doc=parseAiScripts(buf,file.name);
  const prof=$('#modAiProfile').value; const scaled=aiBuildScaledBin(doc,prof);
  modAdd('scripts/'+(/bw/i.test(file.name)?'bwscript.bin':'aiscript.bin'),'AI scaler ('+prof+')',scaled);
  e.target.value='';
});
$('#modFile').addEventListener('change',async e=>{ const file=e.target.files[0]; if(!file)return;
  const buf=new Uint8Array(await file.arrayBuffer());
  const gp=prompt('Game path (without data/), e.g. unit\\wirefram\\wirefram.grp:',file.name);
  if(gp)modAdd(gp,'override ('+file.name+')',buf);
  e.target.value='';
});
$('#modPack').addEventListener('click',()=>{
  if(!MOD.files.length){ setStatus('Add at least one file.',true); return; }
  const man=modManifest(), zn=modZipName();
  // contents at the ROOT — the launcher extracts straight into files/mods/<zipname>/
  const entries=[{name:'mod.json',data:new TextEncoder().encode(JSON.stringify(man,null,2))}];
  const prov={generator:'grp-toolkit Mod Builder',intended_id:zn,storage:'loose',overrides:MOD.files.map(f=>f.path)};
  entries.push({name:'toolkit-provenance.json',data:new TextEncoder().encode(JSON.stringify(prov,null,2))});
  for(const f of MOD.files) entries.push({name:'data/'+f.path,data:f.data});
  const zip=zipStore(entries);
  const url=URL.createObjectURL(new Blob([zip],{type:'application/zip'})); dl(url,zn+'.zip'); URL.revokeObjectURL(url);
  const warns=modValidateAll();
  setStatus('Packaged <b>'+zn+'.zip</b> (id = file name) — '+MOD.files.length+' files'+(warns.length?(' · ⚠ '+warns.length+' warnings'):' · validation OK'));
});
$('#modUseMpq').addEventListener('change',e=>{ if(e.target.checked){
  setStatus('data.mpq packaging — via Python <b>tools/mod_pack.py --use-mpq</b>. In the browser only loose for now.',true);
  e.target.checked=false; }});

/* ---- Build-order library (Miro cards, V) + measured name->id map ---- */
const BUILD_ORDERS=[{"id":"t-bunker-rush-vz","race":"T","name":"Bunker Rush","matchup":"VS Zerg","aggression":7,"economy":3,"build":[{"name":"Barracks","supply":8,"condition":null,"note":null,"action":false},{"name":"Supply Depot","supply":9,"condition":null,"note":null,"action":false},{"name":"Scout","supply":10,"condition":null,"note":null,"action":true},{"name":"Marine","supply":null,"condition":"100% Barracks","note":"Set Barracks rally on Zerg natural, push at 2 Marines","action":false},{"name":"Supply Depot","supply":15,"condition":null,"note":null,"action":false}],"countered_by":["4 Pool","9 Pool","12 Pool"],"counter_to":["12 Hatch"],"notable_maps":{"good":["Short Walking Distance","Two Player Maps"],"bad":["Long Walking Distance"]},"description":"Early aggressive build to damage a fast-expanding Zerg by killing Drones or the expansion. Usually an 8 Rax build; sometimes the all-in BBS."},{"id":"t-1-fact-fast-expand-vt","race":"T","name":"1 Fact Fast Expand","matchup":"VS Terran","aggression":3,"economy":7,"build":[{"name":"Supply Depot","supply":9,"condition":null,"note":null,"action":false},{"name":"Barracks","supply":12,"condition":null,"note":"Build 1-2 Marines, then lift off the Barracks and scout with it.","action":false},{"name":"Refinery","supply":null,"condition":null,"note":null,"action":false},{"name":"Scout","supply":13,"condition":null,"note":"Can be delayed to 14 or 15 supply.","action":true},{"name":"Supply Depot","supply":16,"condition":null,"note":null,"action":false},{"name":"Factory","supply":null,"condition":null,"note":"Take 2 SCVs off gas at this point.","action":false},{"name":"Command Center","supply":20,"condition":null,"note":null,"action":false},{"name":"Vulture","supply":null,"condition":null,"note":"Add 2 SCVs back on gas.","action":false},{"name":"Supply Depot","supply":23,"condition":null,"note":null,"action":false},{"name":"Machine Shop","supply":24,"condition":null,"note":"Second Vulture if necessary.","action":false},{"name":"Factory","supply":26,"condition":null,"note":null,"action":false}],"countered_by":["Greedy Builds","Aggressive Builds"],"counter_to":["Nothing in particular"],"notable_maps":{"good":[],"bad":[]},"description":"The One Factory Fast Expand is a safe, standard opening in TvT. It builds an early Factory and secures a quick expansion."},{"id":"t-1-rax-fast-expand-vp","race":"T","name":"1 Rax Fast Expand","matchup":"VS Protoss","aggression":2,"economy":8,"build":[{"name":"Supply Depot","supply":9,"condition":null,"note":null,"action":false},{"name":"Barracks","supply":11,"condition":null,"note":null,"action":false},{"name":"Command Center","supply":15,"condition":null,"note":null,"action":false},{"name":"Supply Depot","supply":16,"condition":null,"note":null,"action":false},{"name":"Refinery","supply":null,"condition":null,"note":null,"action":false},{"name":"2 Marines","supply":null,"condition":null,"note":null,"action":false},{"name":"Factory","supply":21,"condition":null,"note":null,"action":false},{"name":"Bunker at Natural","supply":null,"condition":null,"note":null,"action":false},{"name":"Factory","supply":25,"condition":null,"note":null,"action":false},{"name":"Supply Depot","supply":28,"condition":null,"note":null,"action":false},{"name":"Refinery at Natural","supply":30,"condition":null,"note":null,"action":false},{"name":"Siege Tank","supply":31,"condition":null,"note":null,"action":false},{"name":"Siege Mode","supply":null,"condition":null,"note":null,"action":false},{"name":"Supply Depot","supply":37,"condition":null,"note":null,"action":false},{"name":"Engineering Bay","supply":44,"condition":null,"note":null,"action":false}],"countered_by":["Proxy Gateway(s) Rush","Fast Tech (DTs, Reaver, etc)"],"counter_to":["12 Nexus","2 Gate Dragoon Obs"],"notable_maps":{"good":["Small Chokes"],"bad":["Wide Chokes"]},"description":"The 1 Barracks Fast Expand creates an economic advantage without being as risky as 14 CC. It negates the 12 Nexus build and can respond to a Protoss gas steal."},{"id":"t-14-cc-vt","race":"T","name":"14 CC","matchup":"VS Terran","aggression":1,"economy":9,"build":[{"name":"Supply Depot","supply":9,"condition":null,"note":null,"action":false},{"name":"Take Natural","supply":14,"condition":null,"note":null,"action":true},{"name":"Barracks","supply":15,"condition":null,"note":null,"action":false},{"name":"Refinery","supply":16,"condition":null,"note":null,"action":false},{"name":"Supply Depot","supply":null,"condition":null,"note":null,"action":false},{"name":"Marine","supply":23,"condition":null,"note":null,"action":false},{"name":"Bunker","supply":null,"condition":null,"note":null,"action":false},{"name":"Marine","supply":26,"condition":null,"note":null,"action":false},{"name":"Natural Refinery","supply":null,"condition":null,"note":null,"action":false}],"countered_by":["Proxy Rax","Barracks Barracks Supply","Double Expand"],"counter_to":["1 Fact FE"],"notable_maps":{"good":["4 Player or Big Maps"],"bad":["Small Maps"]},"description":"14 CC is the most risky non-cheese Terran opening. A rare opening, but feasible depending on the circumstances and map."},{"id":"t-2-fact-vulture-mines-vp","race":"T","name":"2 Fact Vulture Mines","matchup":"VS Protoss","aggression":7,"economy":3,"build":[{"name":"Supply Depot","supply":9,"condition":null,"note":null,"action":false},{"name":"Barracks","supply":11,"condition":null,"note":null,"action":false},{"name":"Refinery","supply":11,"condition":null,"note":null,"action":false},{"name":"Factory","supply":16,"condition":null,"note":null,"action":false},{"name":"Supply Depot","supply":null,"condition":null,"note":null,"action":false},{"name":"Factory","supply":18,"condition":null,"note":null,"action":false},{"name":"Supply Depot","supply":22,"condition":null,"note":null,"action":false},{"name":"Pump Vultures","supply":null,"condition":"100% Factory","note":null,"action":false},{"name":"Vulture Speed","supply":null,"condition":"100% Machine Shop 1","note":null,"action":false},{"name":"Spider Mines","supply":null,"condition":"100% Machine Shop 2","note":null,"action":false},{"name":"Supply Depot","supply":28,"condition":null,"note":null,"action":false}],"countered_by":["2 Gateway Builds","1 Gateway Expand"],"counter_to":["Dark Templar Rushes","Reaver Drop Play","General Drop Play"],"notable_maps":{"good":["Wide Chokes"],"bad":["Backdoor Expansions"]},"description":"A very aggressive Terran opening to punish greedy Protoss expansions or tech like a DT Rush, sacrificing macro to obtain map control within the first ten minutes."},{"id":"t-2-port-wraith-vt","race":"T","name":"2 Port Wraith","matchup":"VS Terran","aggression":8,"economy":2,"build":[{"name":"Supply Depot","supply":9,"condition":null,"note":null,"action":false},{"name":"Barracks","supply":11,"condition":null,"note":null,"action":false},{"name":"Refinery","supply":12,"condition":null,"note":null,"action":false},{"name":"Supply Depot","supply":13,"condition":null,"note":null,"action":false},{"name":"Factory","supply":16,"condition":null,"note":null,"action":false},{"name":"3-4 Marines","supply":null,"condition":"100% Barracks","note":null,"action":false},{"name":"Vulture","supply":null,"condition":"100% Factory","note":null,"action":false},{"name":"Machine Shop","supply":null,"condition":null,"note":null,"action":false},{"name":"Spider Mines","supply":null,"condition":"100% Machine Shop","note":null,"action":false},{"name":"Pump Vultures","supply":null,"condition":null,"note":null,"action":false},{"name":"2 Starports","supply":22,"condition":null,"note":null,"action":false},{"name":"Supply Depot","supply":null,"condition":null,"note":null,"action":false},{"name":"2 Wraiths","supply":null,"condition":"100% Starports","note":null,"action":false},{"name":"Control Tower","supply":null,"condition":"100% 2 Wraiths","note":null,"action":false},{"name":"Pump Wraiths","supply":null,"condition":null,"note":null,"action":false}],"countered_by":["Early Goliaths","Good or Aggressive Scout","Mass Turrets"],"counter_to":["Poor or Denied Scout"],"notable_maps":{"good":["Harassable Mineral Line"],"bad":["Defendable Mineral Line"]},"description":"A surprise opener designed to harass, be annoying and gain an economic edge while sniping objectives in small skirmishes."},{"id":"t-4-rax-sunken-break-vz","race":"T","name":"4 Rax Sunken Break","matchup":"VS Zerg","aggression":8,"economy":2,"build":[{"name":"Supply Depot","supply":9,"condition":null,"note":null,"action":false},{"name":"Barracks","supply":11,"condition":null,"note":null,"action":false},{"name":"1st Scout","supply":12,"condition":null,"note":null,"action":true},{"name":"Supply Depot","supply":14,"condition":null,"note":null,"action":false},{"name":"2nd Scout","supply":15,"condition":null,"note":null,"action":true},{"name":"Pump Marines","supply":null,"condition":"100% Barracks","note":null,"action":false},{"name":"Take Natural","supply":21,"condition":null,"note":null,"action":true},{"name":"3 Barracks","supply":null,"condition":"450 Minerals","note":null,"action":false},{"name":"Refinery","supply":26,"condition":null,"note":null,"action":false},{"name":"Academy","supply":26,"condition":null,"note":null,"action":false},{"name":"Stim Pack","supply":null,"condition":"100% Academy","note":null,"action":false},{"name":"4 Medics","supply":35,"condition":null,"note":null,"action":false},{"name":"4 Marines","supply":39,"condition":null,"note":null,"action":false},{"name":"Range Upgrade","supply":null,"condition":null,"note":null,"action":false},{"name":"Engineering Bay","supply":null,"condition":null,"note":null,"action":false},{"name":"Pump Marine/Medic","supply":null,"condition":null,"note":null,"action":false}],"countered_by":["3 Hatch Zergling","2 Hatch Muta","2 Hatch Lurker","9 Pool"],"counter_to":["3 Hatch Muta","3 Hatch Lurker"],"notable_maps":{"good":["Short Walking Distance"],"bad":["Narrow Chokes","Long Walking Distance"]},"description":"A TvZ build to counter the standard 3 Hatch Muta. Under a 1 Rax FE facade, Terran breaks the Zerg with four Barracks before Mutalisk or Lurker tech arrives."},{"id":"t-siege-expand-vp","race":"T","name":"Siege Expand","matchup":"VS Protoss","aggression":2,"economy":8,"build":[{"name":"Supply Depot","supply":9,"condition":null,"note":null,"action":false},{"name":"Scout","supply":null,"condition":null,"note":null,"action":true},{"name":"Barracks","supply":12,"condition":null,"note":null,"action":false},{"name":"Refinery","supply":12,"condition":null,"note":null,"action":false},{"name":"Supply Depot","supply":16,"condition":null,"note":null,"action":false},{"name":"Factory","supply":null,"condition":null,"note":null,"action":false},{"name":"Machine Shop","supply":null,"condition":"100% Factory","note":null,"action":false},{"name":"Siege Tank","supply":null,"condition":"100% Machine Shop","note":null,"action":false},{"name":"Take Natural","supply":21,"condition":null,"note":null,"action":true},{"name":"Supply Depot","supply":24,"condition":null,"note":null,"action":false},{"name":"Siege Mode","supply":25,"condition":null,"note":null,"action":false},{"name":"Engineering Bay","supply":28,"condition":null,"note":null,"action":false}],"countered_by":["Bulldog Strats","Fast Expand Variations"],"counter_to":["Nothing in particular"],"notable_maps":{"good":["Close or In-Base 3rd"],"bad":["Nothing in particular"]},"description":"One of the oldest, most reliable TvP openings. A conservative build to help a Fast Expansion while staying safe against most Protoss aggression."},{"id":"p-1-gate-reaver-vt","race":"P","name":"1 Gate Reaver","matchup":"VS Terran","aggression":6,"economy":4,"build":[{"name":"Pylon","supply":8,"condition":null,"note":null,"action":false},{"name":"Gateway","supply":10,"condition":null,"note":null,"action":false},{"name":"Assimilator","supply":11,"condition":null,"note":null,"action":false},{"name":"Cybernetics Core","supply":13,"condition":null,"note":null,"action":false},{"name":"Pylon","supply":15,"condition":null,"note":null,"action":false},{"name":"Dragoon","supply":18,"condition":null,"note":"You can build 4 or 5 Dragoons here.","action":false},{"name":"Dragoon Range","supply":20,"condition":null,"note":null,"action":false},{"name":"Pylon","supply":21,"condition":null,"note":null,"action":false},{"name":"Robotics Facility","supply":26,"condition":"200 Gas","note":null,"action":false},{"name":"Shuttle","supply":null,"condition":"100% Robotics Facility","note":null,"action":false},{"name":"Robotics Support Bay","supply":null,"condition":"100% Robotics Facility","note":"Start Reaver production as soon as the Support Bay finishes.","action":false},{"name":"Pylon","supply":29,"condition":null,"note":null,"action":false},{"name":"Observatory","supply":34,"condition":null,"note":null,"action":false},{"name":"Observer","supply":null,"condition":"100% Observatory","note":null,"action":false},{"name":"Take Natural","supply":37,"condition":null,"note":null,"action":true}],"countered_by":["Drop Play / Wraiths","2 Fact Rushes","Siege Expand"],"counter_to":["2 Fact Vulture","Fake Double"],"notable_maps":{"good":["Large Main","Long Walking Distance"],"bad":["Nothing in particular"]},"description":"One of the most traditional forms of Protoss harassment. Aggressive, designed to deal economic damage to Terran; the Reaver threat keeps Terran from attacking early."},{"id":"p-12-nexus-5-zealot-fast-expansion-vp","race":"P","name":"12 Nexus 5 Zealot Fast Expansion","matchup":"VS Protoss","aggression":4,"economy":6,"build":[{"name":"Pylon","supply":8,"condition":null,"note":"Send a probe to scout after the first pylon.","action":false},{"name":"Nexus","supply":12,"condition":null,"note":null,"action":false},{"name":"Gateway","supply":12,"condition":null,"note":null,"action":false},{"name":"Gateway","supply":14,"condition":null,"note":null,"action":false},{"name":"Pylon at Natural","supply":15,"condition":null,"note":null,"action":false},{"name":"5 Zealots","supply":null,"condition":null,"note":"Zealot production has highest priority.","action":false},{"name":"Assimilator","supply":null,"condition":"100 Minerals","note":null,"action":false},{"name":"Cybernetics Core","supply":null,"condition":"200 Minerals","note":null,"action":false},{"name":"Forge","supply":null,"condition":"150 Minerals","note":null,"action":false},{"name":"Photon Cannon","supply":null,"condition":"100% Forge","note":"Cannon count depends on opponent pressure.","action":false}],"countered_by":["2 Proxy Gate","2 Gate Variations","Proxy Robo"],"counter_to":["Nothing in particular"],"notable_maps":{"good":["Large Maps","Long Walking Distance"],"bad":["Small Maps","Short Walking Distance"]},"description":"A modern PvP opening for an economic advantage without falling behind in tech, but the expanding player must play passively early due to a lower unit count."},{"id":"p-2-gate-dt-rush-vp","race":"P","name":"2 Gate DT Rush","matchup":"VS Protoss","aggression":6,"economy":4,"build":[{"name":"Pylon","supply":8,"condition":null,"note":null,"action":false},{"name":"Gateway","supply":10,"condition":null,"note":"Use that probe to scout.","action":false},{"name":"Assimilator","supply":12,"condition":null,"note":null,"action":false},{"name":"Zealot","supply":13,"condition":null,"note":null,"action":false},{"name":"Pylon","supply":16,"condition":null,"note":null,"action":false},{"name":"Cybernetics Core","supply":18,"condition":null,"note":null,"action":false},{"name":"Zealot","supply":19,"condition":null,"note":null,"action":false},{"name":"Pylon","supply":22,"condition":null,"note":null,"action":false},{"name":"Dragoon","supply":23,"condition":null,"note":null,"action":false},{"name":"Citadel of Adun","supply":26,"condition":null,"note":null,"action":false},{"name":"Dragoon","supply":27,"condition":null,"note":"Stop all production incl. Probes for the next three buildings.","action":false},{"name":"Gateway","supply":29,"condition":null,"note":null,"action":false},{"name":"Templar Archives","supply":null,"condition":null,"note":null,"action":false},{"name":"2 Zealots","supply":null,"condition":null,"note":null,"action":false},{"name":"2 Dark Templars","supply":null,"condition":null,"note":null,"action":false},{"name":"Forge","supply":null,"condition":null,"note":null,"action":false},{"name":"Take Natural","supply":null,"condition":null,"note":"First cannon and first 2 DTs out around the 6 minute mark.","action":true},{"name":"Photon Cannons","supply":null,"condition":null,"note":null,"action":false}],"countered_by":["4 Gate Goon"],"counter_to":["Fast Expansions","DT Rushes"],"notable_maps":{"good":["Narrow Chokes"],"bad":["Nothing in particular"]},"description":"A group of openings enabling early Dark Templar. A one-base timed attack threatens or kills the opponent while preparing an expansion."},{"id":"p-2-gate-range-expand-vt","race":"P","name":"2 Gate Range Expand","matchup":"VS Terran","aggression":3,"economy":7,"build":[{"name":"Pylon","supply":8,"condition":null,"note":"Scout after the first pylon.","action":false},{"name":"Gateway","supply":10,"condition":null,"note":null,"action":false},{"name":"Assimilator","supply":12,"condition":null,"note":null,"action":false},{"name":"Cybernetics Core","supply":13,"condition":null,"note":null,"action":false},{"name":"Pylon","supply":15,"condition":null,"note":null,"action":false},{"name":"Dragoon Range","supply":17,"condition":null,"note":"Pull one probe off gas.","action":false},{"name":"Gateway","supply":18,"condition":null,"note":null,"action":false},{"name":"Nexus","supply":20,"condition":null,"note":"Stop Probe production; focus Dragoons.","action":false},{"name":"2 Dragoons","supply":null,"condition":null,"note":null,"action":false},{"name":"Pylon","supply":24,"condition":null,"note":"Third probe back on gas; resume probes.","action":false},{"name":"2 Dragoons","supply":25,"condition":null,"note":null,"action":false},{"name":"Robotics Facility","supply":31,"condition":null,"note":null,"action":false}],"countered_by":["Three Factory All-Ins","Barracks Barracks Supply (BBS)","14 CC"],"counter_to":["FD Build","Rush Builds"],"notable_maps":{"good":["Large Maps","Long Walking Distance"],"bad":["Small Maps","Short Walking Distance"]},"description":"A specialized PvT build for an early expansion while staying safe against Terran early rush builds."},{"id":"p-2-gate-reaver-vp","race":"P","name":"2 Gate Reaver","matchup":"VS Protoss","aggression":6,"economy":4,"build":[{"name":"Pylon","supply":8,"condition":null,"note":"Scout on 8 or 10.","action":false},{"name":"Gateway","supply":10,"condition":null,"note":null,"action":false},{"name":"Assimilator","supply":11,"condition":null,"note":null,"action":false},{"name":"Cybernetics Core","supply":13,"condition":null,"note":null,"action":false},{"name":"Zealot","supply":14,"condition":null,"note":null,"action":false},{"name":"Pylon","supply":16,"condition":null,"note":"Place by the ramp for the Robotics Facility.","action":false},{"name":"Dragoon Range","supply":21,"condition":"100% Cybernetics Core","note":null,"action":false},{"name":"Dragoon","supply":22,"condition":null,"note":null,"action":false},{"name":"Robotics Facility","supply":25,"condition":null,"note":null,"action":false},{"name":"Dragoon","supply":25,"condition":null,"note":"Produce Dragoons continuously (occasionally a Zealot if gas-short).","action":false},{"name":"Gateway","supply":29,"condition":null,"note":null,"action":false},{"name":"Observatory","supply":null,"condition":"100% Robotics Facility","note":null,"action":false},{"name":"Observer","supply":null,"condition":"100% Observatory","note":"Resume probe production.","action":false},{"name":"Robotics Support Bay","supply":40,"condition":null,"note":null,"action":false},{"name":"Reaver","supply":41,"condition":null,"note":"Prioritize the Reaver ASAP.","action":false},{"name":"Reaver","supply":null,"condition":"100% 1st Reaver","note":null,"action":false},{"name":"Shuttle","supply":null,"condition":"100% 2nd Reaver","note":null,"action":false},{"name":"Take Natural","supply":65,"condition":null,"note":"Push with ~12 goons and 2 reavers in a shuttle at ~7:50-8:00.","action":true}],"countered_by":["4 Gate Goon"],"counter_to":["Fast Expansions","DT Rushes"],"notable_maps":{"good":["Narrow Chokes"],"bad":["Nothing in particular"]},"description":"An army of Dragoons with Range and a Shuttle+Reaver where the Reaver supports the ground forces rather than harassing."},{"id":"p-bulldog-vt","race":"P","name":"Bulldog","matchup":"VS Terran","aggression":7,"economy":3,"build":[{"name":"Pylon","supply":8,"condition":null,"note":null,"action":false},{"name":"Gateway","supply":10,"condition":null,"note":null,"action":false},{"name":"Assimilator","supply":11,"condition":null,"note":null,"action":false},{"name":"Cybernetics Core","supply":13,"condition":null,"note":null,"action":false},{"name":"Scout","supply":null,"condition":null,"note":null,"action":true},{"name":"Dragoon","supply":17,"condition":null,"note":null,"action":false},{"name":"Dragoon Range","supply":20,"condition":null,"note":null,"action":false},{"name":"Gateway","supply":20,"condition":null,"note":null,"action":false},{"name":"Pylon","supply":22,"condition":null,"note":null,"action":false},{"name":"2 Dragoons","supply":24,"condition":null,"note":null,"action":false},{"name":"Robotics Facility","supply":29,"condition":null,"note":null,"action":false},{"name":"2 Dragoons","supply":null,"condition":null,"note":null,"action":false},{"name":"Pylon","supply":33,"condition":null,"note":null,"action":false},{"name":"2 Zealots","supply":null,"condition":null,"note":null,"action":false},{"name":"Pylon","supply":37,"condition":null,"note":null,"action":false},{"name":"Shuttle","supply":38,"condition":null,"note":"After the first Shuttle you may start the Observatory to prevent Spidermine fields.","action":false},{"name":"2 Zealots","supply":40,"condition":null,"note":"Initiate the attack as soon as possible after these finish.","action":false}],"countered_by":["2 Factory Builds"],"counter_to":["Siege Expand","Well Fortified Terran"],"notable_maps":{"good":["Wide Chokes","No Ramps"],"bad":["Nothing in particular"]},"description":"An aggressive opening that sacrifices economy to break Terran defenses early. A more committing variation of the 10/15 Gateway build."},{"id":"p-forge-fast-expand-vz","race":"P","name":"Forge Fast Expand","matchup":"VS Zerg","aggression":2,"economy":8,"build":[{"name":"Pylon at Natural","supply":8,"condition":"BASE BUILD","note":"Correct FFE formation assists a safe fast expand vs Zerg.","action":false},{"name":"Scout","supply":8,"condition":"BASE BUILD","note":null,"action":true},{"name":"Forge","supply":10,"condition":"BASE BUILD","note":null,"action":false},{"name":"2 Cannons","supply":14,"condition":"VS 9 POOL","note":null,"action":false},{"name":"Nexus","supply":15,"condition":"VS 9 POOL","note":"Stop probe production here.","action":false},{"name":"Gateway","supply":15,"condition":"VS 9 POOL","note":"Resume probe production.","action":false},{"name":"Pylon","supply":16,"condition":"VS 9 POOL","note":null,"action":false},{"name":"Assimilator","supply":17,"condition":"VS 9 POOL","note":null,"action":false},{"name":"Cybernetics Core","supply":18,"condition":"VS 9 POOL","note":null,"action":false},{"name":"Zealot","supply":19,"condition":"VS 9 POOL","note":null,"action":false}],"countered_by":["All-In Rushes","2 Hatch before Spawning Pool"],"counter_to":["Nothing in particular"],"notable_maps":{"good":["Easy to Wall-In","Wide Chokes"],"bad":["Hard to Wall-In","Small Chokes"]},"description":"A safe, defensive PvZ opening. Fast expand behind a Forge and Cannons to quickly secure a second geyser and reach a strong mid game. (Card also lists VS 12 POOL / 12 HATCH / OVERPOOL variations.)"},{"id":"z-7-pool-vt","race":"Z","name":"7 Pool","matchup":"VS Terran","aggression":9,"economy":1,"build":[{"name":"Spawning Pool","supply":7,"condition":null,"note":null,"action":false},{"name":"Overlord","supply":7,"condition":null,"note":null,"action":false},{"name":"Drone","supply":null,"condition":null,"note":null,"action":false},{"name":"Scout","supply":null,"condition":null,"note":null,"action":true},{"name":"6 Zerglings","supply":null,"condition":"100% Spawning Pool","note":null,"action":false},{"name":"2 Zerglings","supply":11,"condition":null,"note":null,"action":false},{"name":"Take Natural","supply":12,"condition":null,"note":null,"action":true},{"name":"Extractor","supply":14,"condition":null,"note":null,"action":false}],"countered_by":["Zergling Tight Walls","8 Rax in Main","2 Rax FE","Block at Choke or Ramp"],"counter_to":["14 CC","Barracks Barracks Supply","1 Rax FE"],"notable_maps":{"good":["No ramps at main base","Hard to wall","Short Walking Distance"],"bad":["Ramps at main base","Easy to wall","Long Walking Distance"]},"description":"A highly aggressive, modern Zerg rush. Unlike a 4/5 Pool all-in, the 7 Pool morphs an early Overlord to transition into macro if the rush fails."},{"id":"z-9-pool-vt","race":"Z","name":"9 Pool","matchup":"VS Terran","aggression":6,"economy":4,"build":[{"name":"Spawning Pool","supply":9,"condition":null,"note":null,"action":false},{"name":"Drone","supply":null,"condition":null,"note":null,"action":false},{"name":"Extractor","supply":9,"condition":null,"note":null,"action":false},{"name":"Overlord","supply":10,"condition":null,"note":null,"action":false},{"name":"6 Zerglings","supply":null,"condition":"100% Spawning Pool","note":null,"action":false},{"name":"Take Natural","supply":15,"condition":null,"note":null,"action":true},{"name":"Zergling Speed","supply":null,"condition":"100 Gas","note":null,"action":false}],"countered_by":["Zergling Tight Walls","2 Rax FE","Non-Proxy 8 Rax"],"counter_to":["14 CC","Proxy Barracks","1 Rax FE"],"notable_maps":{"good":["No ramps at main base","Hard to wall"],"bad":["Ramps at main base","Small chokes"]},"description":"An early Zergling build giving a safe opening vs Terran cheese like 8 Rax or BBS. Can outright win or delay a Terran FE; the faster pool gives quicker tech. (Card lists Economy and Speed variations.)"},{"id":"z-12-hatch-vz","race":"Z","name":"12 Hatch","matchup":"VS Zerg","aggression":1,"economy":9,"build":[{"name":"Overlord","supply":9,"condition":null,"note":null,"action":false},{"name":"Hatchery","supply":12,"condition":null,"note":"2nd Hatchery","action":false},{"name":"Spawning Pool","supply":11,"condition":null,"note":null,"action":false},{"name":"Extractor","supply":10,"condition":null,"note":null,"action":false},{"name":"2 Drones","supply":null,"condition":null,"note":null,"action":false},{"name":"6 Zerglings","supply":12,"condition":null,"note":null,"action":false},{"name":"Lair","supply":null,"condition":"100 Gas","note":null,"action":false},{"name":"Pump Zerglings","supply":null,"condition":null,"note":null,"action":false},{"name":"Overlord","supply":16,"condition":null,"note":null,"action":false},{"name":"Zergling Speed","supply":null,"condition":"100 Gas","note":null,"action":false}],"countered_by":["4-5 Pool","9 Pool","Overpool"],"counter_to":["12 Pool","9/10 Hatch","Overgas"],"notable_maps":{"good":["Long Walking Distance","Backdoor Expansions"],"bad":["Short Walking distance"]},"description":"One of the most greedy and risky ZvZ strategies. An early economic advantage with a much faster second Hatchery, at the cost of a later pool vulnerable to 9 Pool or faster."},{"id":"z-12-pool-vz","race":"Z","name":"12 Pool","matchup":"VS Zerg","aggression":4,"economy":6,"build":[{"name":"Overlord","supply":9,"condition":null,"note":null,"action":false},{"name":"Spawning Pool","supply":12,"condition":null,"note":null,"action":false},{"name":"Extractor","supply":12,"condition":null,"note":null,"action":false},{"name":"Take Natural","supply":11,"condition":null,"note":null,"action":true},{"name":"2-X Zerglings","supply":null,"condition":null,"note":null,"action":false},{"name":"Zergling Speed","supply":null,"condition":"100 Gas","note":null,"action":false},{"name":"Lair","supply":null,"condition":null,"note":"Lair when possible","action":false},{"name":"Spire","supply":null,"condition":"100% Lair","note":null,"action":false}],"countered_by":["4-7 Pool","12 Hatch"],"counter_to":["9 Pool","Overpool"],"notable_maps":{"good":["Wide chokes"],"bad":["Short travel distance"]},"description":"A very safe, versatile ZvZ opening. Protects from most early Zergling rushes while keeping a superior economy — trading some economy vs 12 Hatch for safety."},{"id":"z-overpool-vz","race":"Z","name":"Overpool","matchup":"VS Zerg","aggression":5,"economy":5,"build":[{"name":"Overlord","supply":9,"condition":null,"note":null,"action":false},{"name":"Spawning Pool","supply":9,"condition":null,"note":null,"action":false},{"name":"Extractor","supply":9,"condition":null,"note":null,"action":false},{"name":"6 Zerglings","supply":null,"condition":"100% Spawning Pool","note":null,"action":false},{"name":"Zergling Speed","supply":null,"condition":"100 Gas","note":null,"action":false},{"name":"Lair","supply":null,"condition":"100 Gas","note":null,"action":false},{"name":"Overlord","supply":18,"condition":null,"note":null,"action":false},{"name":"Spire","supply":null,"condition":"100% Lair","note":null,"action":false},{"name":"3 Mutalisks","supply":null,"condition":"100% Spire","note":null,"action":false},{"name":"Take Natural","supply":null,"condition":"300 Minerals","note":null,"action":true}],"countered_by":["12 Pool"],"counter_to":["12 Hatch","5 Pool","9 Pool"],"notable_maps":{"good":["Air Harassable","Long Walking Distance"],"bad":["Air Defendable","Short Walking Distance"]},"description":"Standard ZvZ build. Overpool gets Zerglings out in time to defend a quicker Pool, while getting Mutalisks out in time to defend all-ins."},{"id":"z-3-hatch-hydralisk-vp","race":"Z","name":"3 Hatch Hydralisk","matchup":"VS Protoss","aggression":7,"economy":3,"build":[{"name":"Overlord","supply":9,"condition":null,"note":null,"action":false},{"name":"Spawning Pool","supply":9,"condition":null,"note":null,"action":false},{"name":"Take Natural","supply":11,"condition":null,"note":null,"action":true},{"name":"Scout","supply":null,"condition":null,"note":null,"action":true},{"name":"4 Zerglings","supply":12,"condition":null,"note":null,"action":false},{"name":"Take 3rd","supply":15,"condition":null,"note":null,"action":true},{"name":"Drone","supply":14,"condition":null,"note":null,"action":false},{"name":"Extractor","supply":15,"condition":null,"note":null,"action":false},{"name":"Overlord","supply":16,"condition":null,"note":null,"action":false},{"name":"Hydralisk Den","supply":null,"condition":"50 Gas","note":null,"action":false},{"name":"Hydralisk Speed","supply":null,"condition":"100% Hydralisk Den","note":null,"action":false},{"name":"Hydralisk Range","supply":null,"condition":"100% Hydralisk Speed","note":null,"action":false},{"name":"Move Out","supply":null,"condition":null,"note":null,"action":true}],"countered_by":["4 or more Cannons on Natural"],"counter_to":["Protoss Fast Expand"],"notable_maps":{"good":["Wide chokes"],"bad":["Narrow Chokes"]},"description":"A timing attack to hit Protoss before Zealot speed or Templar tech. Disguises itself as a 3 Hatch Lair build; strong on maps with large chokes."},{"id":"z-3-base-spire-5-hatch-hydralisk-vp","race":"Z","name":"3 Base Spire 5 Hatch Hydralisk","matchup":"VS Protoss","aggression":2,"economy":8,"build":[{"name":"Play Standard Opening","supply":null,"condition":null,"note":null,"action":true},{"name":"2-6 Zerglings","supply":null,"condition":"100% Spawning Pool","note":null,"action":false},{"name":"Lair","supply":null,"condition":"100 Gas","note":null,"action":false},{"name":"Zergling Speed","supply":null,"condition":"100 Gas","note":null,"action":false},{"name":"Spire","supply":null,"condition":"100% Lair","note":null,"action":false},{"name":"Hatchery","supply":null,"condition":null,"note":"3rd Hatchery","action":false},{"name":"Natural Extractor","supply":32,"condition":null,"note":null,"action":false},{"name":"Hydralisk Den","supply":35,"condition":null,"note":null,"action":false},{"name":"Hydralisk Speed","supply":null,"condition":"100% Hydralisk Den","note":null,"action":false},{"name":"Evolution Chamber","supply":null,"condition":null,"note":null,"action":false},{"name":"4 Scourge","supply":null,"condition":"100% Spire","note":null,"action":false},{"name":"2 Sunken Colonies","supply":null,"condition":null,"note":null,"action":false},{"name":"Pump Hydralisk","supply":42,"condition":null,"note":null,"action":false},{"name":"9-11 Mutalisk","supply":110,"condition":null,"note":null,"action":false},{"name":"Late Game Transition","supply":null,"condition":null,"note":null,"action":true}],"countered_by":["1 Base Protoss","+1 Speedlot Rush","Fast Maelstrom","Mass Goon/Templar Mid Game","Corsair/Reaver"],"counter_to":["4 Gate 2 Archon Rush","Zealot/High Templar"],"notable_maps":{"good":["Gas on 3rd Expansion"],"bad":["Gasless 3rd Expansion"]},"description":"A versatile, standard modern ZvP build. Reaching Lair tech faster, Zerg halts heavy Corsair play with Scourge while keeping a sizable economic advantage."}];
const UNIT_IDS={"names":{"Barracks":111,"Supply Depot":109,"Refinery":110,"Command Center":106,"Factory":113,"Machine Shop":120,"Starport":114,"Control Tower":115,"Bunker":125,"Academy":112,"Engineering Bay":122,"Marine":0,"Firebat":32,"Medic":34,"Vulture":2,"Siege Tank":5,"Goliath":3,"Wraith":8,"SCV":7,"Pylon":156,"Gateway":160,"Assimilator":157,"Nexus":154,"Forge":166,"Photon Cannon":162,"Cybernetics Core":164,"Robotics Facility":155,"Robotics Support Bay":171,"Observatory":159,"Citadel of Adun":163,"Templar Archives":165,"Zealot":65,"Dragoon":66,"Dark Templar":61,"Reaver":83,"Observer":84,"Shuttle":69,"Probe":64,"Hatchery":131,"Lair":132,"Spawning Pool":142,"Extractor":149,"Evolution Chamber":139,"Hydralisk Den":135,"Spire":141,"Sunken Colony":146,"Creep Colony":143,"Drone":41,"Overlord":42,"Zergling":37,"Hydralisk":38,"Mutalisk":43,"Scourge":47},"kinds":{"Barracks":"building","Supply Depot":"building","Refinery":"building","Command Center":"building","Factory":"building","Machine Shop":"building","Starport":"building","Control Tower":"building","Bunker":"building","Academy":"building","Engineering Bay":"building","Marine":"unit","Firebat":"unit","Medic":"unit","Vulture":"unit","Siege Tank":"unit","Goliath":"unit","Wraith":"unit","SCV":"unit","Pylon":"building","Gateway":"building","Assimilator":"building","Nexus":"building","Forge":"building","Photon Cannon":"building","Cybernetics Core":"building","Robotics Facility":"building","Robotics Support Bay":"building","Observatory":"building","Citadel of Adun":"building","Templar Archives":"building","Zealot":"unit","Dragoon":"unit","Dark Templar":"unit","Reaver":"unit","Observer":"unit","Shuttle":"unit","Probe":"unit","Hatchery":"building","Lair":"building","Spawning Pool":"building","Extractor":"building","Evolution Chamber":"building","Hydralisk Den":"building","Spire":"building","Sunken Colony":"building","Creep Colony":"building","Drone":"unit","Overlord":"unit","Zergling":"unit","Hydralisk":"unit","Mutalisk":"unit","Scourge":"unit"}};
/* ========================= Bot builder ========================= */
/* Tactic tables are illustrative skeletons: the CONTROL FLOW is real, the unit/
   building/upgrade IDs are numeric placeholders (0, 106…) to be set from the
   user's own units.dat / stat_txt.tbl. The generator encodes whatever value it
   is given, so every template compiles disasm-clean regardless. */
const BOT_TPL={
rush:`# Rush bot — attacks early. IDs are numeric; adjust to your own units.dat / stat_txt.
start_town
start_areatown
farms_timing
transports_off
build 1 106 0        # 106 = production building
train 5 0            # 0 = military unit (military-group idx)
:main
time_jump 1200 push  # after time -> attack
wait 200
goto main
:push
attack_clear
attack_add 8 0
attack_prepare
attack_do
wait 600
goto main`,
defensive:`# Defensive bot — waits, defends, counterattacks.
start_town
start_areatown
farms_timing
transports_off
build 2 106 0
:main
panic defend         # if attacked -> defense
time_jump 3600 counter
wait 300
goto main
:defend
defensebuild_gg 4 0
defensebuild_ga 2 0
goto main
:counter
attack_clear
attack_add 12 0
attack_prepare
attack_do
goto main`,
adaptive:`# Adaptive bot — changes tactics based on enemy / resources / difficulty.
start_town
start_areatown
farms_timing
transports_off
build 1 106 0
train 4 0
:main
enemyowns_jump 9 antiair            # enemy has unit 9 -> anti-air
enemyresources_jump 800 800 turtle  # rich enemy -> defense
random_jump 50 harass
time_jump 3600 push
wait 300
goto main
:antiair
defensebuild_ga 4 0
goto main
:turtle
defensebuild_gg 6 0
goto main
:harass
attack_clear
attack_add 4 0
attack_prepare
attack_do
goto main
:push
attack_clear
attack_add 14 0
attack_prepare
attack_do
wait 600
goto main`,
economic:`# Economic bot — expands, tech, late push.
start_town
start_areatown
farms_timing
transports_off
build 3 106 0
player_need 2 106
upgrade 1 0 0        # 0 = upgrade id
tech 0 0            # 0 = tech id
define_max 30 0
:main
resources_jump 1500 800 push
wait 400
goto main
:push
attack_clear
attack_add 18 0
attack_prepare
attack_do
wait 800
goto main`
};
const BOT={bin:null,base:null,id:null,lib:null};
function botCompile(){
  const stat=$('#botStat'), dis=$('#botDis');
  let idPad=($('#botId').value||'Bot1').slice(0,4); while(idPad.length<4)idPad+='_';
  const name=+$('#botName').value||0, flags=+$('#botFlags').value||0;
  let steps;
  try{ steps=aiParseSteps($('#botSrc').value); }
  catch(e){ BOT.bin=null; stat.innerHTML='<span class="bad">✕ '+e.message+'</span>'; dis.textContent=''; return; }
  const merged=$('#botMerge').checked;
  let bin;
  try{
    const script={id:idPad,name,flags,code:steps};
    if(merged){ if(!BOT.base)throw new Error('no stock aiscript.bin loaded'); bin=aiMergeInto(BOT.base,[script]); }
    else bin=aiBuildBin([script]);
  }catch(e){ BOT.bin=null; stat.innerHTML='<span class="bad">✕ '+e.message+'</span>'; dis.textContent=''; return; }
  // ORACLE (mirror of tests/ai/test_ai_gen.py): parse back, trace must be clean.
  try{
    const parsed=parseAiScripts(bin.buffer,'aiscript.bin');
    const tgt=parsed.scripts[parsed.scripts.length-1];   // ours is appended last
    if(!tgt)throw new Error('scriptas nerastas');
    if(tgt.err)throw new Error('disasm desync: '+tgt.err);
    dis.textContent=tgt.ins.map(i=>'0x'+i.address.toString(16).padStart(4,'0')+'  '+i.name
      +(i.args.length?'  '+i.args.map(aiArgText).join(' '):'')).join('\n');
    BOT.bin=bin; BOT.id=idPad;
    stat.innerHTML='<span class="ok">✓ CLEAN</span> · '+tgt.ins.length+' instr · '+bin.length+' B'
      +(merged?(' · merge → '+parsed.scripts.length+' scripts'):' · standalone');
  }catch(e){ BOT.bin=null; stat.innerHTML='<span class="bad">✕ '+e.message+'</span>'; dis.textContent=''; }
}
$('#botOpen').addEventListener('click',()=>{ if(!$('#botSrc').value)$('#botSrc').value=BOT_TPL.adaptive; botCompile(); $('#bot').classList.add('on'); });
$('#botClose').addEventListener('click',()=>$('#bot').classList.remove('on'));
document.querySelectorAll('#bot .chip[data-tpl]').forEach(c=>c.addEventListener('click',()=>{ $('#botSrc').value=BOT_TPL[c.dataset.tpl]; BOT.lib=null; $('#botSpec').innerHTML=''; $('#botLib').value=''; botCompile(); }));
['#botSrc','#botId','#botName','#botFlags'].forEach(id=>$(id).addEventListener('input',botCompile));
$('#botMerge').addEventListener('change',async e=>{
  if(e.target.checked){
    try{ const buf=await readGameFile('scripts\\aiscript.bin'); BOT.base=new Uint8Array(buf);
      $('#botMergeInfo').textContent='stock aiscript.bin loaded: '+BOT.base.length+' B.'; }
    catch(err){ BOT.base=null; e.target.checked=false;
      $('#botMergeInfo').innerHTML='<span class="bad">failed: '+err.message+' — open MPQ/CASC.</span>'; }
  } else { BOT.base=null; $('#botMergeInfo').textContent=''; }
  botCompile();
});
$('#botDl').addEventListener('click',()=>{ if(!BOT.bin){ setStatus('Compile a clean bot first.',true); return; }
  const url=URL.createObjectURL(new Blob([BOT.bin],{type:'application/octet-stream'})); dl(url,'aiscript.bin'); URL.revokeObjectURL(url);
  setStatus('Eksportuota <b>aiscript.bin</b> ('+BOT.bin.length+' B).'); });
$('#botToMod').addEventListener('click',()=>{ if(!BOT.bin){ setStatus('Compile a clean bot first.',true); return; }
  modAdd('scripts/aiscript.bin','bot builder'+($('#botMerge').checked?' (merge)':' (standalone)'),BOT.bin);
  // bot packaging: prefill the mod manifest as a bot mod (from the build order if one is loaded)
  $('#modType').value='bot';
  if(BOT.lib){ const bo=BOT.lib;
    $('#modName').value=bo.name+' Bot ('+bo.matchup+')';
    $('#modId').value=('bot-'+bo.id).replace(/[^A-Za-z0-9._-]/g,'-');
    $('#modVer').value=$('#modVer').value||'1.0';
    $('#modDesc').value=bo.description+'  [Aggression '+bo.aggression+'/10 · Economy '+bo.economy+'/10 · '+bo.matchup+']';
  } else if(!$('#modName').value||$('#modName').value==='My Mod'){
    $('#modName').value='Training Bot'; $('#modId').value='training-bot';
  }
  $('#bot').classList.remove('on'); modRender(); $('#mod').classList.add('on');
  setStatus('Bot packaged → Mod Builder (<b>type: bot</b>, data/scripts/aiscript.bin'+(BOT.lib?', description from the build order':'')+').'); });

/* ---- Build-order library: card -> compilable tactic + spec panel ---- */
const BO_UPG=/\b(range|speed|mode|mines?|pack|upgrade|carapace|attack|maelstrom)\b/i;
const BO_LEAD=/^(pump\s+|save\s+larvae\s*|natural\s+|take\s+|add\s+|extra\s+|1st\s+|2nd\s+|3rd\s+|\d+[-\dx]*\s+|\+\d+\s+)/i;
const BO_SUF=/\s+(at\s+.*|when\s+.*|if\s+.*|\d+)$/i;
const BO_ALIAS={Cannon:'Photon Cannon',Cannons:'Photon Cannon'};
function boNormalize(nm){                       // mirror of tools/gen_unit_ids.py
  let s=(nm||'').trim(); let t;
  while((t=s.replace(BO_LEAD,''))!==s)s=t;
  s=s.split('/')[0].trim().replace(BO_SUF,'').trim();
  if(/ies$/.test(s))s=s.slice(0,-3)+'y';
  else if(/s$/.test(s)&&(s.slice(0,-1) in UNIT_IDS.names))s=s.slice(0,-1);
  s=BO_ALIAS[s]||s;
  if(/s$/.test(s)&&(s.slice(0,-1) in UNIT_IDS.names))s=s.slice(0,-1);
  return s;
}
function boCount(nm){ if(/^pump/i.test(nm))return 20; const m=nm.match(/^(\d+)(?:-(\d+|x))?/i);
  if(m)return (m[2]&&/^\d+$/.test(m[2]))?+m[2]:+m[1]; return 1; }
const BO_NONARMY=new Set(['SCV','Probe','Drone','Overlord']);
function boGenTactic(bo){
  const L=['# '+bo.name+' '+bo.matchup+' — generated from build order (Miro).',
    '# Production taken from the card; supply/worker timing handled by the AI town-management.',
    '# Upgrades/actions shown in comments (the aiscript town-AI often does not handle them).',
    'start_town','start_areatown','farms_timing','transports_off'];
  const bcount={},tcount={}; const army=[];
  for(const row of bo.build){
    if(row.action){ L.push('# ['+row.name+'] — action'); continue; }
    if(BO_UPG.test(row.name)){ L.push('# ['+row.name+'] — upgrade'); continue; }
    const core=boNormalize(row.name);
    if(!(core in UNIT_IDS.names)){ L.push('# ['+row.name+'] — ID not found'); continue; }
    const id=UNIT_IDS.names[core], kind=UNIT_IDS.kinds[core], cnt=Math.max(1,boCount(row.name));
    if(kind==='building'){ bcount[id]=(bcount[id]||0)+cnt; L.push('build '+bcount[id]+' '+id+' 100  # '+row.name); }
    else { tcount[id]=Math.max(tcount[id]||0,cnt); if(!BO_NONARMY.has(core)&&!army.includes(id))army.push(id);
      L.push('train '+tcount[id]+' '+id+'  # '+row.name); }
  }
  L.push(':main');
  if(army.length){ L.push('attack_clear'); for(const id of army)L.push('attack_add 12 '+id); L.push('attack_prepare','attack_do'); }
  else L.push('# (no combat units on the card — macro bot; defense handled by AI)');
  L.push('wait 600','goto main');
  return L.join('\n');
}
function boFourcc(bo){ return (bo.race+bo.name.replace(/[^A-Za-z0-9]/g,'')).slice(0,4).padEnd(4,'0'); }
function boBar(lab,val,color){ return '<div class="bar"><span class="lab">'+lab+'</span>'+
  '<span class="track"><span class="fill" style="width:'+(val*10)+'%;background:'+color+'"></span></span><span>'+val+'/10</span></div>'; }
function boRenderSpec(bo){
  const tags=a=>(a&&a.length?a:['—']).map(x=>'<span class="tag">'+x+'</span>').join('');
  const steps=bo.build.map(r=>{ const cls=r.action?'act':(BO_UPG.test(r.name)?'upg':'');
    return '<div class="st"><span class="sup">'+(r.supply!=null?r.supply:'')+'</span><span class="'+cls+'">'+r.name+
      (r.condition?' <span style="color:#6a8">['+r.condition+']</span>':'')+'</span></div>'; }).join('');
  $('#botSpec').innerHTML='<div class="card"><h4>'+bo.name+'</h4><div class="mu">'+bo.matchup+' · '+({T:'Terran',P:'Protoss',Z:'Zerg'}[bo.race])+'</div>'+
    boBar('Aggression',bo.aggression,'#e0708a')+boBar('Economy',bo.economy,'#5ad18a')+
    '<div class="desc">'+bo.description+'</div>'+
    '<div class="grid2"><div><div class="sect">Countered by</div>'+tags(bo.countered_by)+'</div>'+
    '<div><div class="sect">Counter to</div>'+tags(bo.counter_to)+'</div></div>'+
    '<div class="grid2"><div><div class="sect">Good maps</div>'+tags(bo.notable_maps&&bo.notable_maps.good)+'</div>'+
    '<div><div class="sect">Bad maps</div>'+tags(bo.notable_maps&&bo.notable_maps.bad)+'</div></div>'+
    '<div class="sect" style="margin-top:10px">Build order</div><div class="steps">'+steps+'</div></div>';
}
(function botLibInit(){
  const sel=$('#botLib'); const groups={T:'Terran',P:'Protoss',Z:'Zerg'};
  for(const r of ['T','P','Z']){ const og=document.createElement('optgroup'); og.label=groups[r];
    BUILD_ORDERS.filter(b=>b.race===r).forEach(b=>{ const o=document.createElement('option');
      o.value=b.id; o.textContent=b.name+' — '+b.matchup; og.appendChild(o); });
    sel.appendChild(og); }
})();
$('#botLib').addEventListener('change',e=>{
  const bo=BUILD_ORDERS.find(b=>b.id===e.target.value);
  if(!bo){ BOT.lib=null; $('#botSpec').innerHTML=''; return; }
  BOT.lib=bo;
  $('#botId').value=boFourcc(bo); $('#botName').value=0; $('#botFlags').value=0;
  $('#botSrc').value=boGenTactic(bo);
  boRenderSpec(bo); botCompile();
});

/* ========================= DAT editor ========================= */
/* JS twin of tools/dat.py. Field tables generated from the Python spec (same
   ordering/widths/counts), so the SoA layout is identical; round-trip is
   byte-exact (verified sha-equal to Python). Offsets are resolved from field
   sizes and re-checked against the four measured anchors in the oracle. */
const DAT_FIELDS_UNITS=[["flingy",1,228,0,1],["subunit1",2,228,0,1],["subunit2",2,228,0,1],["infestation",2,96,106,1],["construction_animation",4,228,0,1],["unit_direction",1,228,0,1],["shield_enable",1,228,0,1],["shield_amount",2,228,0,256],["hitpoints",4,228,0,256],["elevation_level",1,228,0,1],["movement_flags",1,228,0,1],["rank",1,228,0,1],["comp_ai_idle",1,228,0,1],["human_ai_idle",1,228,0,1],["return_to_idle",1,228,0,1],["attack_unit",1,228,0,1],["attack_move",1,228,0,1],["ground_weapon",1,228,0,1],["max_ground_hits",1,228,0,1],["air_weapon",1,228,0,1],["max_air_hits",1,228,0,1],["ai_internal",1,228,0,1],["special_ability_flags",4,228,0,1],["target_acquisition_range",1,228,0,1],["sight_range",1,228,0,1],["armor_upgrade",1,228,0,1],["unit_size",1,228,0,1],["armor",1,228,0,1],["right_click_action",1,228,0,1],["ready_sound",2,106,0,1],["what_sound_first",2,228,0,1],["what_sound_last",2,228,0,1],["piss_sound_first",2,106,0,1],["piss_sound_last",2,106,0,1],["yes_sound_first",2,106,0,1],["yes_sound_last",2,106,0,1],["placement_box_width",2,228,0,1],["placement_box_height",2,228,0,1],["addon_horizontal",2,96,106,1],["addon_vertical",2,96,106,1],["dimension_left",2,228,0,1],["dimension_up",2,228,0,1],["dimension_right",2,228,0,1],["dimension_down",2,228,0,1],["portrait",2,228,0,1],["mineral_cost",2,228,0,1],["vespene_cost",2,228,0,1],["build_time",2,228,0,1],["requirements",2,228,0,1],["group_flags",1,228,0,1],["supply_provided",1,228,0,1],["supply_required",1,228,0,1],["space_required",1,228,0,1],["space_provided",1,228,0,1],["build_score",2,228,0,1],["destroy_score",2,228,0,1],["unit_map_string",2,228,0,1],["broodwar_flag",1,228,0,1],["staredit_availability",2,228,0,1]];
const DAT_FIELDS_WEAPONS=[["label",2,130,0,1],["graphics",4,130,0,1],["unused",1,130,0,1],["target_flags",2,130,0,1],["min_range",4,130,0,1],["max_range",4,130,0,1],["damage_upgrade",1,130,0,1],["weapon_type",1,130,0,1],["weapon_behavior",1,130,0,1],["remove_after",1,130,0,1],["weapon_effect",1,130,0,1],["inner_splash_range",2,130,0,1],["median_splash_range",2,130,0,1],["outer_splash_range",2,130,0,1],["damage_amount",2,130,0,1],["damage_bonus",2,130,0,1],["weapon_cooldown",1,130,0,1],["damage_factor",1,130,0,1],["attack_angle",1,130,0,1],["launch_spin",1,130,0,1],["forward_offset",1,130,0,1],["upward_offset",1,130,0,1],["target_error_message",2,130,0,1],["icon",2,130,0,1]];
const DAT_FIELDS_FLINGY=[["sprite",2,209,0,1],["top_speed",4,209,0,1],["acceleration",2,209,0,1],["halt_distance",4,209,0,1],["turn_radius",1,209,0,1],["unused",1,209,0,1],["move_control",1,209,0,1]];
const DAT_FIELDS_SPRITES=[["image",2,517,0,1],["health_bar",1,387,130,1],["unknown_0",1,517,0,1],["is_visible",1,517,0,1],["selection_circle_image",1,387,130,1],["selection_circle_offset",1,387,130,1]];
const DAT_FIELDS_IMAGES=[["grp_file",4,999,0,1],["graphic_turns",1,999,0,1],["clickable",1,999,0,1],["use_full_iscript",1,999,0,1],["draw_if_cloaked",1,999,0,1],["draw_function",1,999,0,1],["remapping",1,999,0,1],["iscript_id",4,999,0,1],["shield_overlay",4,999,0,1],["attack_overlay",4,999,0,1],["damage_overlay",4,999,0,1],["special_overlay",4,999,0,1],["landing_dust_overlay",4,999,0,1],["liftoff_dust_overlay",4,999,0,1]];
const DAT_SPECS={'units.dat':[DAT_FIELDS_UNITS,228,19876],'weapons.dat':[DAT_FIELDS_WEAPONS,130,5460],
  'flingy.dat':[DAT_FIELDS_FLINGY,209,3135],'sprites.dat':[DAT_FIELDS_SPRITES,517,3229],'images.dat':[DAT_FIELDS_IMAGES,999,37962]};
const DAT_COMMON={
 'units.dat':['hitpoints','shield_amount','armor','armor_upgrade','sight_range','target_acquisition_range','mineral_cost','vespene_cost','build_time','supply_provided','supply_required','space_required','ground_weapon','air_weapon','unit_size'],
 'weapons.dat':['damage_amount','damage_bonus','damage_factor','weapon_cooldown','min_range','max_range','inner_splash_range','median_splash_range','outer_splash_range','damage_upgrade','weapon_type','weapon_behavior']};
function datParse(kind,u8){
  const spec=DAT_SPECS[kind]; if(!spec)throw new Error('unknown dat '+kind);
  const [fr,count,expect]=spec;
  if(u8.length!==expect)throw new Error(kind+': expected '+expect+' B, got '+u8.length);
  const fields=fr.map(a=>({name:a[0],w:a[1],count:a[2],base:a[3],scale:a[4],offset:-1}));
  let off=0; for(const f of fields){ f.offset=off; off+=f.w*f.count; }
  const byName={}; fields.forEach(f=>byName[f.name]=f);
  const dv=new DataView(u8.buffer,u8.byteOffset,u8.byteLength);
  return {kind,count,fields,byName,u8,dv,
    get(n,id){const f=byName[n]; if(!f||id<f.base||id>=f.base+f.count)return null;
      const p=f.offset+(id-f.base)*f.w; return f.w===1?dv.getUint8(p):f.w===2?dv.getUint16(p,true):dv.getUint32(p,true);},
    set(n,id,v){const f=byName[n]; if(!f||id<f.base||id>=f.base+f.count)throw new Error('field '+n+' does not cover id '+id);
      const p=f.offset+(id-f.base)*f.w, val=(v>>>0);
      if(f.w===1)dv.setUint8(p,val&0xff); else if(f.w===2)dv.setUint16(p,val&0xffff,true); else dv.setUint32(p,val>>>0,true);},
    display(n,id){const r=this.get(n,id); if(r===null)return null; const f=byName[n]; return f.scale!==1?Math.floor(r/f.scale):r;},
    toBytes(){return u8.slice();}};
}
const DATE={doc:null,stock:null,kind:'units.dat',names:[],sel:-1};
async function datLoad(kind){
  const buf=new Uint8Array(await readGameFile('arr\\'+kind));
  DATE.kind=kind; DATE.doc=datParse(kind,buf.slice()); DATE.stock=datParse(kind,buf.slice());
  let tbl=null; try{ tbl=parseTbl(await readGameFile('rez\\stat_txt.tbl')); }catch(e){}
  DATE.names=[];
  for(let i=0;i<DATE.doc.count;i++){
    if(kind==='units.dat') DATE.names.push(tbl&&tbl[i]?tbl[i]:('unit '+i));
    else { const lab=DATE.doc.get('label',i); DATE.names.push(tbl&&tbl[lab-1]?tbl[lab-1]:('weapon '+i)); }
  }
  DATE.sel=0; datRenderList(); datSelect(0);
}
function datChangedIds(){
  const d=DATE.doc,s=DATE.stock,set=new Set();
  for(let i=0;i<d.u8.length;i++){ if(d.u8[i]!==s.u8[i]){
    for(const f of d.fields){ if(i>=f.offset&&i<f.offset+f.w*f.count){ set.add(f.base+Math.floor((i-f.offset)/f.w)); break; } } } }
  return set;
}
function datRenderList(){
  if(!DATE.doc)return;
  const q=($('#datSearch').value||'').toLowerCase().trim();
  const chg=datChangedIds();
  const host=$('#datList'); host.innerHTML=''; let shown=0;
  for(let i=0;i<DATE.doc.count;i++){
    const nm=DATE.names[i]||('#'+i);
    if(q&&!(nm.toLowerCase().includes(q)||(''+i)===q))continue;
    shown++;
    const row=document.createElement('div'); row.className='erow'+(i===DATE.sel?' on':'');
    row.innerHTML='<span class="eid">'+i+'</span><span>'+nm+'</span>'+(chg.has(i)?'<span style="color:#8fd15a;margin-left:auto">●</span>':'');
    row.onclick=()=>datSelect(i); host.appendChild(row);
  }
  $('#datCount').textContent=shown;
  let bytes=0; for(let i=0;i<DATE.doc.u8.length;i++)if(DATE.doc.u8[i]!==DATE.stock.u8[i])bytes++;
  $('#datStat').textContent=chg.size+' changed · '+bytes+' B';
}
function datSelect(id){
  DATE.sel=id; $$('#datList .erow').forEach(r=>r.classList.toggle('on',+r.querySelector('.eid').textContent===id));
  $('#datTitle').textContent='#'+id+'  '+(DATE.names[id]||'');
  datRenderFields(id);
  datRenderChain(id);
}
/* Graphics chain: units.dat.flingy -> flingy.sprite -> sprites.image ->
   images.grp_file -> images.tbl name. Mirror of tools/dat.py graphics_chain +
   the test_dat_chain oracle. Lazy-loads the 3 extra .dat + images.tbl. */
const DGRAPH={flingy:null,sprites:null,images:null,tbl:null,loading:false};
async function datLoadGraph(){
  if(DGRAPH.images&&DGRAPH.tbl)return true;
  if(DGRAPH.loading)return false; DGRAPH.loading=true;
  try{
    DGRAPH.flingy=datParse('flingy.dat',new Uint8Array(await readGameFile('arr\\flingy.dat')));
    DGRAPH.sprites=datParse('sprites.dat',new Uint8Array(await readGameFile('arr\\sprites.dat')));
    DGRAPH.images=datParse('images.dat',new Uint8Array(await readGameFile('arr\\images.dat')));
    DGRAPH.tbl=parseTbl(await readGameFile('arr\\images.tbl'));
    return true;
  }catch(e){ DGRAPH.images=null; return false; } finally { DGRAPH.loading=false; }
}
function datChainResolve(unitId){
  if(!DGRAPH.images||!DGRAPH.tbl)return null;
  const fl=DATE.doc.get('flingy',unitId);
  const sp=DGRAPH.flingy.get('sprite',fl);
  const im=DGRAPH.sprites.get('image',sp);
  const gi=DGRAPH.images.get('grp_file',im);
  const name=(gi>=1&&gi<=DGRAPH.tbl.length)?DGRAPH.tbl[gi-1]:null;
  return {flingy:fl,sprite:sp,image:im,grp_file:gi,grp_name:name,imageId:im};
}
function datRenderChain(id){
  const host=$('#datChain'); host.innerHTML='';
  if(DATE.kind!=='units.dat'){ return; }
  if(!DGRAPH.images){ datLoadGraph().then(ok=>{ if(ok&&DATE.sel===id&&DATE.kind==='units.dat')datRenderChain(id); });
    host.innerHTML='<div class="cc" style="color:var(--ink-dim)">Graphics chain loading… (needs an open MPQ/CASC)</div>'; return; }
  const c=datChainResolve(id); if(!c){ return; }
  const path=c.grp_name?('unit\\'+c.grp_name):'?';
  host.innerHTML='<div class="cc"><div class="hop">unit <b>'+id+'</b> → flingy <b>'+c.flingy+
    '</b> → sprite <b>'+c.sprite+'</b> → image <b>'+c.image+'</b> → grp_file <b>'+c.grp_file+
    '</b></div><div class="grp" style="margin-top:3px">SD GRP: '+(c.grp_name||'—')+'</div>'+
    '<div class="hop" style="margin-top:2px" title="SD↔HD bridge: image id → anim/main_NNN.anim; SD frame i ↔ HD frame i (measured 214/214 units, 0 mismatches — tools/sd_hd_bridge.py)">HD ANIM: <b>anim/main_'+String(c.image).padStart(3,'0')+'.anim</b> · SD frame i ↔ HD frame i (×4 HD)</div>'+
    '<button id="datReskin">🎨 Redraw this sprite (→ Sprite importer)</button> '+
    '<button id="datRetarget" title="retarget to a different images.tbl GRP (changes images.dat)">↪ grp_file</button>'+
    '</div>';
  $('#datReskin').onclick=()=>{ if(!c.grp_name){ setStatus('This unit has no GRP chain.',true); return; }
    $('#dat').classList.remove('on'); $('#spr').classList.add('on');
    $('#sprPath').value=path; sprRender();
    setStatus('Sprite importer path set: <b>data/'+path.replace(/\\/g,'/').toLowerCase()+'</b> — load a PNG.'); };
  $('#datRetarget').onclick=()=>{
    const v=prompt('New images.tbl GRP index (1..'+DGRAPH.tbl.length+') for image '+c.image+':',c.grp_file);
    if(v===null)return; const gi=parseInt(v,10); if(!(gi>=1&&gi<=DGRAPH.tbl.length)){ setStatus('Bad index.',true); return; }
    DGRAPH.images.set('grp_file',c.image,gi);
    modAdd('arr/images.dat','DAT chain (retarget)',DGRAPH.images.toBytes());
    datRenderChain(id);
    setStatus('image '+c.image+' → GRP '+DGRAPH.tbl[gi-1]+'. images.dat added to Mod Builder.'); };
}
function datRenderFields(id){
  const d=DATE.doc,s=DATE.stock; const tb=$('#datFields'); tb.innerHTML='';
  const showAll=$('#datAllFields').checked;
  const names=showAll?d.fields.map(f=>f.name):DAT_COMMON[DATE.kind];
  for(const n of names){
    const f=d.byName[n]; if(!f)continue; if(id<f.base||id>=f.base+f.count)continue;   // subset guard
    const cur=d.display(n,id), stock=s.display(n,id), changed=d.get(n,id)!==s.get(n,id);
    const tr=document.createElement('tr'); if(changed)tr.className='changed';
    const scaleNote=f.scale!==1?' <span class="fscale">×1/'+f.scale+'</span>':'';
    tr.innerHTML='<td class="fn">'+n+scaleNote+'</td><td></td><td style="color:var(--ink-dim)">'+stock+'</td>';
    const inp=document.createElement('input'); inp.type='number'; inp.value=cur; inp.min=0;
    inp.max=(f.w===4?4294967295:f.w===2?65535:255)/(f.scale||1);
    inp.oninput=()=>{ let v=Math.round((+inp.value||0)*f.scale); d.set(n,id,v);
      tr.classList.toggle('changed',d.get(n,id)!==s.get(n,id)); datListMark(id); };
    tr.children[1].appendChild(inp); tb.appendChild(tr);
  }
}
function datListMark(id){ // refresh the ● marker + counters without full rebuild
  const chg=datChangedIds();
  $$('#datList .erow').forEach(r=>{ const i=+r.querySelector('.eid').textContent;
    let m=r.querySelector('.dmark'); if(chg.has(i)){ if(!m){m=document.createElement('span');m.className='dmark';m.style.cssText='color:#8fd15a;margin-left:auto';m.textContent='●';r.appendChild(m);} }
    else if(m)m.remove(); });
  let bytes=0; for(let i=0;i<DATE.doc.u8.length;i++)if(DATE.doc.u8[i]!==DATE.stock.u8[i])bytes++;
  $('#datStat').textContent=chg.size+' changed · '+bytes+' B';
}
$('#datOpen').addEventListener('click',async()=>{
  try{ if(!DATE.doc||DATE.kind!==$('#datKind').value) await datLoad($('#datKind').value);
    else datRenderList(); $('#dat').classList.add('on'); }
  catch(e){ setStatus('DAT: '+e.message+' — open MPQ/CASC.',true); }
});
$('#datClose').addEventListener('click',()=>$('#dat').classList.remove('on'));
$('#datKind').addEventListener('change',async e=>{ try{ await datLoad(e.target.value); }catch(err){ setStatus('DAT: '+err.message,true); } });
$('#datSearch').addEventListener('input',datRenderList);
$('#datAllFields').addEventListener('change',()=>{ if(DATE.sel>=0)datRenderFields(DATE.sel); });
$('#datRevert').addEventListener('click',()=>{ if(!DATE.doc||DATE.sel<0)return; const id=DATE.sel;
  for(const f of DATE.doc.fields){ if(id>=f.base&&id<f.base+f.count)DATE.doc.set(f.name,id,DATE.stock.get(f.name,id)); }
  datRenderFields(id); datListMark(id); });
$('#datDl').addEventListener('click',()=>{ if(!DATE.doc){ setStatus('Load DAT first.',true); return; }
  const url=URL.createObjectURL(new Blob([DATE.doc.toBytes()],{type:'application/octet-stream'})); dl(url,DATE.kind); URL.revokeObjectURL(url);
  setStatus('Exported <b>'+DATE.kind+'</b> ('+DATE.doc.u8.length+' B).'); });
$('#datToMod').addEventListener('click',()=>{ if(!DATE.doc){ setStatus('Load DAT first.',true); return; }
  modAdd('arr/'+DATE.kind,'DAT editor',DATE.doc.toBytes());
  $('#dat').classList.remove('on'); modRender(); $('#mod').classList.add('on');
  setStatus('DAT → Mod Builder as <b>data/arr/'+DATE.kind+'</b>.'); });

// ---- TBL string-table editor (browser twin of tools/tbl.py) ----
// raw[i] = the FULL slice to the next offset (keeps stat_txt's extended NUL-parts);
// strings[i] = display name up to first NUL. Unedited -> to_bytes() is byte-identical
// (offset order); edited -> index-order content-deduped (valid, semantic round-trip).
const TBLE={doc:null,path:null,sel:-1,stock:null};
function enc1(s){const a=new Uint8Array(s.length);for(let i=0;i<s.length;i++)a[i]=s.charCodeAt(i)&0xff;return a;}
function tblParseFull(buf){
  const b=new Uint8Array(buf),dv=new DataView(buf.buffer||buf,buf.byteOffset||0),n=dv.getUint16(0,true);
  const offs=[];for(let i=0;i<n;i++)offs.push(dv.getUint16(2+i*2,true));
  const uniq=[...new Set(offs)].sort((a,c)=>a-c);
  const nextb={};uniq.forEach((o,i)=>nextb[o]=(i+1<uniq.length)?uniq[i+1]:b.length);
  const raw=offs.map(o=>b.slice(o,nextb[o]));
  const td=new TextDecoder('latin1');
  const strings=raw.map(r=>{let e=0;while(e<r.length&&r[e])e++;return td.decode(r.subarray(0,e));});
  return {count:n,offs,raw,strings,dirty:false};
}
function tblSetText(t,i,name){
  const old=t.raw[i];let k=0;while(k<old.length&&old[k])k++;
  let tail=old.subarray(k);if(tail.length===0)tail=Uint8Array.of(0);
  const nb=enc1(name),m=new Uint8Array(nb.length+tail.length);m.set(nb,0);m.set(tail,nb.length);
  t.raw[i]=m;t.strings[i]=name;t.dirty=true;
}
function tblAssemble(count,outoffs,parts,base,len){
  const out=new Uint8Array(base+len),dv=new DataView(out.buffer);
  dv.setUint16(0,count,true);for(let i=0;i<count;i++)dv.setUint16(2+i*2,outoffs[i],true);
  let p=base;for(const part of parts){out.set(part,p);p+=part.length;}return out;
}
function tblToBytes(t){
  const count=t.count,base=2+2*count;
  if(!t.dirty){
    const uniq=[...new Set(t.offs)].sort((a,c)=>a-c),first={};
    t.offs.forEach((o,i)=>{if(!(o in first))first[o]=i;});
    let pos={},parts=[],len=0;
    for(const o of uniq){pos[o]=base+len;parts.push(t.raw[first[o]]);len+=t.raw[first[o]].length;}
    return tblAssemble(count,t.offs.map(o=>pos[o]),parts,base,len);
  }
  const pos=new Map(),parts=[],outoffs=[];let len=0;
  for(const r of t.raw){const key=r.join(',');if(!pos.has(key)){pos.set(key,base+len);parts.push(r);len+=r.length;}outoffs.push(pos.get(key));}
  return tblAssemble(count,outoffs,parts,base,len);
}
async function tblLoad(path){
  const buf=new Uint8Array(await readGameFile(path));
  TBLE.doc=tblParseFull(buf);TBLE.path=path;TBLE.sel=-1;
  TBLE.stock=TBLE.doc.raw.map(r=>r.slice());
  const bi=tblToBytes(TBLE.doc).length===buf.length && tblToBytes(TBLE.doc).every((v,i)=>v===buf[i]);
  $('#tblStat').innerHTML=TBLE.doc.count+' entries · '+buf.length+' B · round-trip '+(bi?'✓ byte-identical':'≈ semantic');
  $('#tblCount').textContent=TBLE.doc.count;tblRenderList();
  $('#tblEdit').innerHTML='Select an entry on the left.';$('#tblTitle').textContent='—';
}
function tblChanged(i){const a=TBLE.doc.raw[i],b=TBLE.stock[i];if(a.length!==b.length)return true;for(let k=0;k<a.length;k++)if(a[k]!==b[k])return true;return false;}
function tblRenderList(){
  const q=($('#tblSearch').value||'').toLowerCase(),host=$('#tblList');host.innerHTML='';
  const d=TBLE.doc;if(!d)return;const frag=document.createDocumentFragment();
  for(let i=0;i<d.count;i++){
    const nm=d.strings[i];
    if(q&&!(nm.toLowerCase().includes(q)||(''+i).includes(q)))continue;
    const extra=d.raw[i].length-nm.length-1;
    const row=document.createElement('div');row.className='erow'+(i===TBLE.sel?' on':'')+(tblChanged(i)?' changed':'');
    row.innerHTML='<span class="eid">'+i+'</span><span class="etx"></span>'+(extra>0?'<span class="ext" title="'+extra+' extra bytes (tooltip/hotkey) preserved">+'+extra+'</span>':'');
    row.querySelector('.etx').textContent=nm||'∅';
    row.addEventListener('click',()=>tblSelect(i));frag.appendChild(row);
  }
  host.appendChild(frag);
}
function tblSelect(i){TBLE.sel=i;tblRenderList();tblRenderEdit(i);}
function tblRenderEdit(i){
  const d=TBLE.doc,nm=d.strings[i],extra=d.raw[i].length-nm.length-1;
  $('#tblTitle').textContent='#'+i+(TBLE.path.includes('stat_txt')?' — '+(nm||'∅'):'');
  const note=extra>0?'<div class="note">This entry has <b>'+extra+' extra bytes</b> after the name (tooltip / hotkey / extended text) — they are <b>preserved</b> when you change only the name.</div>':'';
  $('#tblEdit').innerHTML='<label style="font-size:11px;color:var(--ink-dim)">Text (name)</label>'+
    '<textarea id="tblText" spellcheck="false"></textarea>'+note+
    '<div class="note">The in-game index is usually 1-based: this entry = string #'+(i+1)+'.</div>';
  const ta=$('#tblText');ta.value=nm;
  ta.addEventListener('input',()=>{tblSetText(d,i,ta.value);$('#tblTitle').textContent='#'+i+(TBLE.path.includes('stat_txt')?' — '+(ta.value||'∅'):'');
    const row=[...$('#tblList').children].find(r=>r.querySelector('.eid')&&r.querySelector('.eid').textContent==(''+i));
    if(row){row.classList.toggle('changed',tblChanged(i));row.querySelector('.etx').textContent=ta.value||'∅';}});
}
$('#tblOpen').addEventListener('click',async()=>{
  try{ if(!TBLE.doc||TBLE.path!==$('#tblKind').value) await tblLoad($('#tblKind').value);
    else tblRenderList(); $('#tbl').classList.add('on'); }
  catch(e){ setStatus('TBL: '+e.message+' — open MPQ/CASC.',true); }
});
$('#tblClose').addEventListener('click',()=>$('#tbl').classList.remove('on'));
$('#tblKind').addEventListener('change',async e=>{ try{ await tblLoad(e.target.value); }catch(err){ setStatus('TBL: '+err.message,true); } });
$('#tblSearch').addEventListener('input',tblRenderList);
$('#tblRevert').addEventListener('click',()=>{ if(!TBLE.doc||TBLE.sel<0)return; const i=TBLE.sel;
  TBLE.doc.raw[i]=TBLE.stock[i].slice(); let e=0;const r=TBLE.doc.raw[i];while(e<r.length&&r[e])e++;
  TBLE.doc.strings[i]=new TextDecoder('latin1').decode(r.subarray(0,e)); tblRenderList(); tblRenderEdit(i); });
$('#tblDl').addEventListener('click',()=>{ if(!TBLE.doc){ setStatus('Load TBL first.',true); return; }
  const name=TBLE.path.split(/[\\/]/).pop(); const url=URL.createObjectURL(new Blob([tblToBytes(TBLE.doc)],{type:'application/octet-stream'})); dl(url,name); URL.revokeObjectURL(url);
  setStatus('Exported <b>'+name+'</b> ('+tblToBytes(TBLE.doc).length+' B).'); });
$('#tblToMod').addEventListener('click',()=>{ if(!TBLE.doc){ setStatus('Load TBL first.',true); return; }
  const p=TBLE.path.replace(/\\/g,'/'); modAdd(p,'TBL editor',tblToBytes(TBLE.doc));
  $('#tbl').classList.remove('on'); modRender(); $('#mod').classList.add('on');
  setStatus('TBL → Mod Builder as <b>data/'+p+'</b>.'); });

/* ========================= Sprite importer ========================= */
/* JS twin of tools/grp.py — encode indexed frames to a classic RLE GRP and
   decode it back for preview. Same RLE (skip/run/literal) + frame dedup, so the
   in-browser preview is the pixel round-trip the Python oracle proves. */
function grpEncRow(row,w){ const out=[]; let x=0;
  while(x<w){ const v=row[x];
    if(v===0){ let c=0; while(x<w&&row[x]===0&&c<0x7f){c++;x++;} out.push(0x80|c); continue; }
    let rep=0; while(x+rep<w&&row[x+rep]===v&&rep<0x3f)rep++;
    if(rep>=2){ out.push(0x40|rep,v); x+=rep; continue; }
    const lit=[]; while(x<w&&row[x]!==0&&lit.length<0x3f){ let r2=0;
      while(x+r2<w&&row[x+r2]===row[x]&&r2<0x3f)r2++; if(r2>=2)break; lit.push(row[x]); x++; }
    out.push(lit.length,...lit);
  } return out; }
function grpEncFrame(fr){ const h=fr.h,w=fr.w,rows=[];
  for(let r=0;r<h;r++)rows.push(grpEncRow(fr.pixels.slice(r*w,r*w+w),w));
  const table=2*h,offs=[],body=[];
  for(const rb of rows){ offs.push(table+body.length); for(const b of rb)body.push(b); }
  const out=[]; for(const o of offs)out.push(o&0xff,(o>>8)&0xff); for(const b of body)out.push(b);
  return out; }
function grpWrite(cw,ch,frames){
  const fc=frames.length,header=[fc&0xff,fc>>8,cw&0xff,cw>>8,ch&0xff,ch>>8];
  const dataStart=6+fc*8,table=[],blocks=[],seen=new Map();
  for(const fr of frames){ const blk=grpEncFrame(fr),key=blk.join(',');
    let off; if(seen.has(key))off=seen.get(key); else { off=dataStart+blocks.length; for(const b of blk)blocks.push(b); seen.set(key,off); }
    table.push(fr.x&0xff,fr.y&0xff,fr.w&0xff,fr.h&0xff,off&0xff,(off>>8)&0xff,(off>>16)&0xff,(off>>>24)&0xff);
  }
  return new Uint8Array([...header,...table,...blocks]); }
function grpDecode(u8){
  const dv=new DataView(u8.buffer,u8.byteOffset,u8.byteLength);
  const fc=dv.getUint16(0,true),cw=dv.getUint16(2,true),ch=dv.getUint16(4,true),frames=[];
  for(let i=0;i<fc;i++){ const o=6+i*8,x=u8[o],y=u8[o+1],w=u8[o+2],h=u8[o+3],off=dv.getUint32(o+4,true);
    const px=new Array(w*h).fill(0);
    for(let row=0;row<h;row++){ let p=off+dv.getUint16(off+row*2,true),cx=0;
      while(cx<w){ const b=u8[p++];
        if(b>=0x80)cx+=b-0x80;
        else if(b>=0x40){ const cnt=b-0x40,val=u8[p++]; for(let k=0;k<cnt;k++)if(cx<w)px[row*w+cx++]=val; }
        else { for(let k=0;k<b;k++){ if(cx<w)px[row*w+cx]=u8[p]; p++; cx++; } } }
    }
    frames.push({x,y,w,h,px});
  } return {cw,ch,frames}; }

const SPR={pal:null,frames:[]};   // frames: {name,w,h,rgba(Uint8ClampedArray),x,y}
function sprPalette(){ return SPR.pal||S.customPal||grayPalette(); }
function sprQuant(rgba,w,h,pal){ const px=new Array(w*h);
  for(let i=0;i<w*h;i++){ const a=rgba[i*4+3];
    if(a<128){ px[i]=0; continue; }
    const r=rgba[i*4],g=rgba[i*4+1],b=rgba[i*4+2]; let best=1,bd=1e12;
    for(let c=1;c<256;c++){ const dr=r-pal[c*3],dg=g-pal[c*3+1],db=b-pal[c*3+2],d=dr*dr+dg*dg+db*db; if(d<bd){bd=d;best=c;} }
    px[i]=best; }
  return px; }
function sprDrawPx(px,w,h,pal,scale){ const cv=document.createElement('canvas'); cv.width=w*scale; cv.height=h*scale;
  const ctx=cv.getContext('2d'); const img=ctx.createImageData(w,h);
  for(let i=0;i<w*h;i++){ const v=px[i]; if(v===0){img.data[i*4+3]=0;} else {img.data[i*4]=pal[v*3];img.data[i*4+1]=pal[v*3+1];img.data[i*4+2]=pal[v*3+2];img.data[i*4+3]=255;} }
  const tmp=document.createElement('canvas'); tmp.width=w; tmp.height=h; tmp.getContext('2d').putImageData(img,0,0);
  ctx.imageSmoothingEnabled=false; ctx.drawImage(tmp,0,0,w*scale,h*scale); return cv; }
function sprPalStrip(){ const pal=sprPalette(); const host=$('#sprPalStrip'); host.innerHTML='';
  const cv=document.createElement('canvas'); cv.width=256; cv.height=8; const ctx=cv.getContext('2d');
  for(let c=0;c<256;c++){ ctx.fillStyle='rgb('+pal[c*3]+','+pal[c*3+1]+','+pal[c*3+2]+')'; ctx.fillRect(c,0,1,8); }
  cv.style.width='100%'; cv.style.height='10px'; cv.style.imageRendering='pixelated'; host.appendChild(cv); }
function sprBuild(){ if(!SPR.frames.length)return null;
  const pal=sprPalette();
  const gframes=SPR.frames.map(f=>({x:f.x|0,y:f.y|0,w:f.w,h:f.h,pixels:sprQuant(f.rgba,f.w,f.h,pal)}));
  let cw=0,ch=0; for(const f of gframes){ cw=Math.max(cw,(f.x|0)+f.w); ch=Math.max(ch,(f.y|0)+f.h); }
  const bin=grpWrite(Math.min(cw,65535),Math.min(ch,65535),gframes);
  return {bin,gframes,cw,ch,pal}; }
function sprRender(){
  sprPalStrip();
  const host=$('#sprFrames'); host.innerHTML='';
  const oversize=SPR.frames.some(f=>f.w>255||f.h>255);
  SPR.frames.forEach((f,i)=>{ const row=document.createElement('div'); row.className='frow';
    const th=sprDrawPx(sprQuant(f.rgba,f.w,f.h,sprPalette()),f.w,f.h,sprPalette(),Math.max(1,Math.min(3,Math.floor(40/Math.max(f.w,f.h)))||1));
    th.style.maxWidth='40px'; th.style.maxHeight='40px'; row.appendChild(th);
    const lab=document.createElement('span'); lab.style.flex='1'; lab.style.overflow='hidden';
    lab.innerHTML=(i)+' · '+f.w+'×'+f.h+(f.w>255||f.h>255?' <span class="bad">&gt;255!</span>':'');
    row.appendChild(lab);
    for(const k of ['x','y']){ const inp=document.createElement('input'); inp.type='number'; inp.value=f[k]; inp.title=k+' offset';
      inp.oninput=()=>{ f[k]=+inp.value||0; sprPreview(); }; row.appendChild(inp); }
    const rm=document.createElement('span'); rm.textContent='✕'; rm.style.cssText='color:var(--red);cursor:pointer';
    rm.onclick=()=>{ SPR.frames.splice(i,1); sprRender(); }; row.appendChild(rm);
    host.appendChild(row); });
  if(oversize)setStatus('A GRP frame cannot exceed 255×255 — shrink the PNG.',true);
  sprPreview();
}
function sprPreview(){
  const built=sprBuild(); const host=$('#sprPreview'); host.innerHTML='';
  if(!built){ $('#sprStat').textContent=''; return; }
  const dec=grpDecode(built.bin);
  dec.frames.forEach(fr=>{ const cell=document.createElement('div'); cell.className='cell';
    cell.appendChild(sprDrawPx(fr.px,fr.w,fr.h,built.pal,3)); host.appendChild(cell); });
  $('#sprStat').textContent=dec.frames.length+' frames · '+built.cw+'×'+built.ch+' · '+built.bin.length+' B';
  SPR.bin=built.bin;
}
function loadImg(file){ return new Promise((res,rej)=>{ const img=new Image(); img.onload=()=>{URL.revokeObjectURL(img.src);res(img);}; img.onerror=rej; img.src=URL.createObjectURL(file); }); }
$('#sprOpen').addEventListener('click',()=>{ sprRender(); $('#spr').classList.add('on'); });
$('#sprClose').addEventListener('click',()=>$('#spr').classList.remove('on'));
$('#sprPng').addEventListener('change',async e=>{ const files=[...e.target.files]; if(!files.length)return;
  for(const file of files){ try{ const img=await loadImg(file);
    const cv=document.createElement('canvas'); cv.width=img.naturalWidth; cv.height=img.naturalHeight;
    const ctx=cv.getContext('2d'); ctx.drawImage(img,0,0);
    const rgba=ctx.getImageData(0,0,cv.width,cv.height).data;
    SPR.frames.push({name:file.name,w:cv.width,h:cv.height,rgba,x:0,y:0});
  }catch(err){ setStatus('Failed to load '+file.name,true); } }
  e.target.value=''; sprRender(); });
$('#sprPalUnit').addEventListener('click',async()=>{
  try{ const buf=await readGameFile('unit\\tunit.pcx'); const pal=parsePaletteFile(buf,'tunit.pcx');
    if(!pal)throw new Error('could not recognize'); SPR.pal=pal;
    $('#sprPalInfo').innerHTML='<span class="ok" style="color:#5ad18a">unit palette from tunit.pcx</span>'; sprRender(); }
  catch(err){ setStatus('Unit palette: '+err.message+' — open MPQ/CASC.',true); } });
$('#sprPalFile').addEventListener('change',e=>{ const f=e.target.files[0]; if(!f)return;
  const r=new FileReader(); r.onload=()=>{ const pal=parsePaletteFile(r.result,f.name);
    if(pal){ SPR.pal=pal; $('#sprPalInfo').textContent='palette: '+f.name; sprRender(); }
    else setStatus('Could not recognize palette: '+f.name,true); };
  r.readAsArrayBuffer(f); e.target.value=''; });
$('#sprDl').addEventListener('click',()=>{ const b=sprBuild(); if(!b){ setStatus('Load PNG frames first.',true); return; }
  const nm=($('#sprPath').value.split(/[\\/]/).pop()||'sprite.grp');
  const url=URL.createObjectURL(new Blob([b.bin],{type:'application/octet-stream'})); dl(url,nm); URL.revokeObjectURL(url);
  setStatus('Exported <b>'+nm+'</b> ('+b.bin.length+' B, '+b.gframes.length+' frames).'); });
$('#sprToMod').addEventListener('click',()=>{ const b=sprBuild(); if(!b){ setStatus('Load PNG frames first.',true); return; }
  const gp=$('#sprPath').value.trim()||'unit\\custom.grp';
  modAdd(gp,'sprite importer (GRP)',b.bin);
  $('#spr').classList.remove('on'); modRender(); $('#mod').classList.add('on');
  setStatus('Sprite → Mod Builder as <b>data/'+gp.replace(/\\/g,'/').toLowerCase()+'</b>.'); });

/* ========================= iscript viewer ========================= */
/* Opcode table + header map GENERATED from tools/iscript/iscript_opcodes.py
   (itself cut from PyMS IScriptBIN.py). Disasm mirrors tools/iscript/
   iscript_disasm.py; the same coverage oracle (398 scripts / 9763 opcodes clean)
   runs in-browser. */
const ISC_OPCODES=[{"n":"playfram","a":[["frame",2]],"c":""},{"n":"playframtile","a":[["frame",2]],"c":""},{"n":"sethorpos","a":[["sbyte",1]],"c":""},{"n":"setvertpos","a":[["sbyte",1]],"c":""},{"n":"setpos","a":[["sbyte",1],["sbyte",1]],"c":""},{"n":"wait","a":[["byte",1]],"c":""},{"n":"waitrand","a":[["byte",1],["byte",1]],"c":""},{"n":"goto","a":[["label",2]],"c":"jump"},{"n":"imgol","a":[["imageid",2],["sbyte",1],["sbyte",1]],"c":""},{"n":"imgul","a":[["imageid",2],["sbyte",1],["sbyte",1]],"c":""},{"n":"imgolorig","a":[["imageid",2]],"c":""},{"n":"switchul","a":[["imageid",2]],"c":""},{"n":"__0c","a":[],"c":""},{"n":"imgoluselo","a":[["imageid",2],["sbyte",1],["sbyte",1]],"c":""},{"n":"imguluselo","a":[["imageid",2],["sbyte",1],["sbyte",1]],"c":""},{"n":"sprol","a":[["spriteid",2],["sbyte",1],["sbyte",1]],"c":""},{"n":"highsprol","a":[["spriteid",2],["sbyte",1],["sbyte",1]],"c":""},{"n":"lowsprul","a":[["spriteid",2],["sbyte",1],["sbyte",1]],"c":""},{"n":"uflunstable","a":[["flingyid",2]],"c":""},{"n":"spruluselo","a":[["spriteid",2],["sbyte",1],["sbyte",1]],"c":""},{"n":"sprul","a":[["spriteid",2],["sbyte",1],["sbyte",1]],"c":""},{"n":"sproluselo","a":[["spriteid",2],["overlayid",1]],"c":""},{"n":"end","a":[],"c":"terminate"},{"n":"setflipstate","a":[["flipstate",1]],"c":""},{"n":"playsnd","a":[["soundid",2]],"c":""},{"n":"playsndrand","a":[["sounds",-1],["soundid",2]],"c":""},{"n":"playsndbtwn","a":[["soundid",2],["soundid",2]],"c":""},{"n":"domissiledmg","a":[],"c":""},{"n":"attackmelee","a":[["sounds",-1],["soundid",2]],"c":""},{"n":"followmaingraphic","a":[],"c":""},{"n":"randcondjmp","a":[["byte",1],["label",2]],"c":"cond_jump"},{"n":"turnccwise","a":[["byte",1]],"c":""},{"n":"turncwise","a":[["byte",1]],"c":""},{"n":"turn1cwise","a":[],"c":""},{"n":"turnrand","a":[["byte",1]],"c":""},{"n":"setspawnframe","a":[["byte",1]],"c":""},{"n":"sigorder","a":[["signalid",1]],"c":""},{"n":"attackwith","a":[["weapon",1]],"c":""},{"n":"attack","a":[],"c":""},{"n":"castspell","a":[],"c":""},{"n":"useweapon","a":[["weaponid",1]],"c":""},{"n":"move","a":[["byte",1]],"c":""},{"n":"gotorepeatattk","a":[],"c":""},{"n":"engframe","a":[["bframe",1]],"c":""},{"n":"engset","a":[["frameset",1]],"c":""},{"n":"__2d","a":[],"c":""},{"n":"nobrkcodestart","a":[],"c":""},{"n":"nobrkcodeend","a":[],"c":""},{"n":"ignorerest","a":[],"c":""},{"n":"attkshiftproj","a":[["byte",1]],"c":""},{"n":"tmprmgraphicstart","a":[],"c":""},{"n":"tmprmgraphicend","a":[],"c":""},{"n":"setfldirect","a":[["byte",1]],"c":""},{"n":"call","a":[["label",2]],"c":"call"},{"n":"return","a":[],"c":"terminate"},{"n":"setflspeed","a":[["speed",2]],"c":""},{"n":"creategasoverlays","a":[["gasoverlay",1]],"c":""},{"n":"pwrupcondjmp","a":[["label",2]],"c":"cond_jump"},{"n":"trgtrangecondjmp","a":[["short",2],["label",2]],"c":"cond_jump"},{"n":"trgtarccondjmp","a":[["short",2],["short",2],["label",2]],"c":"cond_jump"},{"n":"curdirectcondjmp","a":[["short",2],["short",2],["label",2]],"c":"cond_jump"},{"n":"imgulnextid","a":[["sbyte",1],["sbyte",1]],"c":""},{"n":"__3e","a":[],"c":""},{"n":"liftoffcondjmp","a":[["label",2]],"c":"cond_jump"},{"n":"warpoverlay","a":[["frame",2]],"c":""},{"n":"orderdone","a":[["signalid",1]],"c":""},{"n":"grdsprol","a":[["spriteid",2],["sbyte",1],["sbyte",1]],"c":""},{"n":"__43","a":[],"c":""},{"n":"dogrddamage","a":[],"c":""}];
const ISC_HEADER=["Init","Death","GndAttkInit","AirAttkInit","Unused1","GndAttkRpt","AirAttkRpt","CastSpell","GndAttkToIdle","AirAttkToIdle","Unused2","Walking","WalkingToIdle","SpecialState1","SpecialState2","AlmostBuilt","Built","Landing","LiftOff","IsWorking","WorkingToIdle","WarpIn","Unused3","StarEditInit","Disable","Burrow","UnBurrow","Enable"];
const ISC_ENTRY_TYPES={"0":2,"1":2,"2":4,"12":14,"13":14,"14":16,"15":16,"20":22,"21":22,"23":24,"24":26,"26":28,"27":28,"28":28,"29":28};
const ISC_MAXOP=ISC_OPCODES.length-1;
function iscDecodeOne(d,pos){
  const op=d[pos]; if(op>ISC_MAXOP)throw new Error('invalid opcode 0x'+op.toString(16)+' at 0x'+pos.toString(16));
  const spec=ISC_OPCODES[op]; const args=[]; let o=pos+1; const sa=spec.a; let k=0;
  while(k<sa.length){ const [t,sz]=sa[k];
    if(sz<0){ const cnt=d[o]; args.push({t,v:cnt,sz:1}); o++; const [nt,nsz]=sa[k+1];
      for(let i=0;i<cnt;i++){ let v=0; for(let b=0;b<nsz;b++)v|=d[o+b]<<(8*b); args.push({t:nt,v,sz:nsz}); o+=nsz; } k+=2; continue; }
    let v=0; for(let b=0;b<sz;b++)v|=d[o+b]<<(8*b); args.push({t,v,sz}); o+=sz; k++;
  }
  return {address:pos,opcode:op,name:spec.n,cf:spec.c,args,size:o-pos,
    targets:args.filter(a=>a.t==='label').map(a=>a.v)};
}
function iscTrace(d,start,limit){
  const seen=new Set(); const work=[start];
  while(work.length){ let pos=work.pop();
    while(true){ if(seen.has(pos))break; if(pos<0||pos>=limit)throw new Error('flow left region at 0x'+pos.toString(16));
      const ins=iscDecodeOne(d,pos); seen.add(pos);
      for(const t of ins.targets)work.push(t);
      if(ins.cf==='jump'||ins.cf==='terminate')break; pos+=ins.size; }
  }
  return seen;
}
function iscParse(buf){
  const d=new Uint8Array(buf), dv=new DataView(buf);
  const idTable=dv.getUint16(0,true); const entries=[]; let off=idTable;
  while(off+4<=d.length){ const id=dv.getUint16(off,true); if(id===0xffff)break;
    const hoff=dv.getUint16(off+2,true); off+=4;
    if(d[hoff]!==0x53||d[hoff+1]!==0x43||d[hoff+2]!==0x50||d[hoff+3]!==0x45)continue; // SCPE
    const type=d[hoff+4]; const n=ISC_ENTRY_TYPES[type]; if(n===undefined)continue;
    const anims=[]; for(let i=0;i<n;i++){ const ao=dv.getUint16(hoff+8+i*2,true); anims.push([ISC_HEADER[i]||('anim'+i),ao||null]); }
    entries.push({id,hoff,type,anims});
  }
  return {isc:true,d,idTable,entries};
}
function iscArgText(a){ return a.t==='label'?('→0x'+a.v.toString(16)):(a.t+'='+a.v); }
const ISC={doc:null,sel:null,edited:false};
/* in-place, same-size arg edit (safe/layout-preserving — like the AI scaler).
   Overwrites the arg's bytes in the buffer; labels are not editable (would need
   the target to stay a valid opcode boundary — that's the reassembler's job). */
function iscEditArg(addr,k){
  const d=ISC.doc.d; const ins=iscDecodeOne(d,addr);
  const a=ins.args[k]; if(!a||a.t==='label')return;
  let o=addr+1; for(let i=0;i<k;i++)o+=ins.args[i].sz;
  const cur=a.v, max=(1<<(8*a.sz))-1;
  const v=prompt(a.t+' (0..'+max+') ties 0x'+addr.toString(16)+':',cur);
  if(v===null)return; let nv=/^0x/i.test(v)?parseInt(v,16):parseInt(v,10);
  if(Number.isNaN(nv)||nv<0||nv>max){ setStatus('Bad value (0..'+max+').',true); return; }
  for(let b=0;b<a.sz;b++)d[o+b]=(nv>>(8*b))&0xff;
  ISC.edited=true; iscSelect(ISC.sel);
  $('#iscStat').innerHTML=ISC.doc.entries.length+' scripts · <span style="color:#8fd15a">edited</span>';
}
function iscRenderList(){
  if(!ISC.doc)return; const q=($('#iscSearch').value||'').trim();
  const host=$('#iscList'); host.innerHTML=''; let shown=0;
  for(const e of ISC.doc.entries){ if(q&&(''+e.id)!==q&&!(''+e.id).includes(q))continue; shown++;
    const row=document.createElement('div'); row.className='erow'+(ISC.sel===e.id?' on':'');
    const na=e.anims.filter(a=>a[1]).length;
    row.innerHTML='<span class="eid">'+e.id+'</span><span>type '+e.type+' · '+na+' anim</span>';
    row.onclick=()=>iscSelect(e.id); host.appendChild(row);
  }
  $('#iscCount').textContent=shown;
}
function iscSelect(id){
  ISC.sel=id; $$('#isc .erow').forEach(r=>r.classList.toggle('on',+r.querySelector('.eid').textContent===id));
  const e=ISC.doc.entries.find(x=>x.id===id); if(!e)return;
  $('#iscTitle').textContent='iscript '+id+'  (header 0x'+e.hoff.toString(16)+', type '+e.type+')';
  const d=ISC.doc.d, limit=ISC.doc.idTable; const out=[];
  for(const [name,off] of e.anims){ if(!off)continue;
    out.push('<span class="anim">'+name+':</span>  (0x'+off.toString(16)+')');
    try{ const starts=[...iscTrace(d,off,limit)].sort((a,b)=>a-b);
      for(const p of starts){ const ins=iscDecodeOne(d,p);
        const at=ins.args.map((a,k)=>a.t==='label'
          ? '<span class="jmp">'+iscArgText(a)+'</span>'
          : '<span class="argv" data-a="'+p+'" data-k="'+k+'">'+iscArgText(a)+'</span>').join(' ');
        out.push('  0x'+p.toString(16).padStart(5,'0')+'  '+ins.name.padEnd(18)+' '+at); }
    }catch(err){ out.push('  <span style="color:#e0708a">desync: '+err.message+'</span>'); }
    out.push('');
  }
  $('#iscDis').innerHTML=out.join('\n');
  $$('#iscDis .argv').forEach(s=>s.onclick=()=>iscEditArg(+s.dataset.a,+s.dataset.k));
}
$('#iscOpen').addEventListener('click',async()=>{
  if(!ISC.doc){ try{ const buf=await readGameFile('scripts\\iscript.bin'); ISC.doc=iscParse(buf);
      // in-browser coverage sanity
      let ops=0,anims=0,bad=0; for(const e of ISC.doc.entries){ for(const [,off] of e.anims){ if(!off)continue; anims++;
        try{ ops+=iscTrace(ISC.doc.d,off,ISC.doc.idTable).size; }catch(e){ bad++; } } }
      $('#iscStat').textContent=ISC.doc.entries.length+' scripts · '+anims+' anim · '+(bad?bad+' DESYNC':'coverage OK');
    }catch(err){ setStatus('iscript: '+err.message+' — open MPQ/CASC.',true); return; } }
  iscRenderList(); if(ISC.doc.entries.length)iscSelect(ISC.doc.entries[0].id); $('#isc').classList.add('on');
});
$('#iscClose').addEventListener('click',()=>$('#isc').classList.remove('on'));
$('#iscSearch').addEventListener('input',iscRenderList);
function iscBytes(){ return ISC.doc.d.slice(); }
$('#iscDl').addEventListener('click',()=>{ if(!ISC.doc){ setStatus('Open iscript.bin first.',true); return; }
  const url=URL.createObjectURL(new Blob([iscBytes()],{type:'application/octet-stream'})); dl(url,'iscript.bin'); URL.revokeObjectURL(url);
  setStatus('Eksportuota <b>iscript.bin</b> ('+ISC.doc.d.length+' B'+(ISC.edited?', edited':'')+').'); });
$('#iscToMod').addEventListener('click',()=>{ if(!ISC.doc){ setStatus('Open iscript.bin first.',true); return; }
  modAdd('scripts/iscript.bin','iscript editor'+(ISC.edited?' (edited)':''),iscBytes());
  $('#isc').classList.remove('on'); $('#modType').value='data'; modRender(); $('#mod').classList.add('on');
  setStatus('iscript → Mod Builder as <b>data/scripts/iscript.bin</b>.'); });

/* ---- iscript TEXT ASSEMBLER (twin of tools/iscript/iscript_gen.py) ---- */
const ISC_OP_BY_NAME=(()=>{const m={};ISC_OPCODES.forEach((o,i)=>m[o.n]={op:i,a:o.a});return m;})();
function iscParseText(text){
  let iid=null,itype=null; const animMap={}; const steps=[]; let section='header';
  text.split('\n').forEach((raw,li)=>{
    const line=raw.split('#')[0].trim(); if(!line)return;
    if(line.startsWith('.header')){ for(const t of line.split(/\s+/).slice(1)){
      if(t.startsWith('id='))iid=parseInt(t.slice(3),0)||parseInt(t.slice(3),10);
      else if(t.startsWith('type='))itype=parseInt(t.slice(5),10); }
      if(!(itype in ISC_ENTRY_TYPES))throw new Error('line '+(li+1)+': type must be one of '+Object.keys(ISC_ENTRY_TYPES).join(',')); return; }
    if(line==='.code'){ section='code'; return; }
    if(section==='header'&&line.includes('->')){ const [n,l]=line.split('->').map(s=>s.trim());
      if(!ISC_HEADER.includes(n))throw new Error('line '+(li+1)+': unknown animation "'+n+'"'); animMap[n]=l; return; }
    if(line.endsWith(':')){ steps.push({label:line.slice(0,-1).trim()}); return; }
    const tok=line.split(/\s+/); const name=tok[0]; const spec=ISC_OP_BY_NAME[name];
    if(!spec)throw new Error('line '+(li+1)+': unknown opcode "'+name+'"');
    const args=[]; const ra=tok.slice(1); let ai=0;
    for(let k=0;k<spec.a.length;k++){ const [typ,sz]=spec.a[k];
      if(sz<0){ const cnt=parseInt(ra[ai++],0); args.push({t:'count',v:cnt,sz:1}); const [nt,nsz]=spec.a[k+1];
        for(let i=0;i<cnt;i++)args.push({t:nt,v:parseInt(ra[ai++],0),sz:nsz}); break; }
      if(typ==='label')args.push({t:'label',v:ra[ai++],sz:2});
      else args.push({t:typ,v:parseInt(ra[ai++],0),sz}); }
    steps.push({op:name,args});
  });
  if(iid===null||itype===null)throw new Error('missing ".header id=.. type=.."');
  return {iid,itype,animMap,steps};
}
function iscAssembleEntry(p,base){
  const labels={}; let pos=base;
  for(const s of p.steps){ if(s.label!==undefined){ if(s.label in labels)throw new Error('duplicate label "'+s.label+'"'); labels[s.label]=pos; }
    else pos+=1+s.args.reduce((a,x)=>a+x.sz,0); }
  const codeLen=pos-base; const code=[];
  for(const s of p.steps){ if(s.label!==undefined)continue; const spec=ISC_OP_BY_NAME[s.op]; code.push(spec.op);
    for(const a of s.args){ if(a.t==='label'){ if(!(a.v in labels))throw new Error('undefined label "'+a.v+'"'); const v=labels[a.v]; code.push(v&0xff,(v>>8)&0xff); }
      else { for(let b=0;b<a.sz;b++)code.push((a.v>>(8*b))&0xff); } } }
  const headerOff=base+codeLen; const hdr=[0x53,0x43,0x50,0x45,p.itype&0xff,0,0,0];
  const n=ISC_ENTRY_TYPES[p.itype];
  for(let i=0;i<n;i++){ const nm=ISC_HEADER[i]; const lbl=p.animMap[nm]; const off=(lbl&&lbl in labels)?labels[lbl]:0; hdr.push(off&0xff,(off>>8)&0xff); }
  return {code,hdr,headerOff};
}
function iscMergeText(stockU8,text){
  const p=iscParseText(text); const dv=new DataView(stockU8.buffer,stockU8.byteOffset,stockU8.byteLength);
  const base=dv.getUint16(0,true); const {code,hdr,headerOff}=iscAssembleEntry(p,base);
  const newTable=headerOff+hdr.length; if(newTable>0xffff)throw new Error('merged iscript.bin exceeds u16 (>65535 B)');
  const doc=iscParse(stockU8.buffer.slice(stockU8.byteOffset,stockU8.byteOffset+stockU8.byteLength));
  const out=[]; for(let i=0;i<base;i++)out.push(stockU8[i]);
  for(const b of code)out.push(b); for(const b of hdr)out.push(b);
  let seen=false;
  for(const e of doc.entries){ const off=e.id===p.iid?headerOff:e.hoff; if(e.id===p.iid)seen=true;
    out.push(e.id&0xff,(e.id>>8)&0xff,off&0xff,(off>>8)&0xff); }
  if(!seen)out.push(p.iid&0xff,(p.iid>>8)&0xff,headerOff&0xff,(headerOff>>8)&0xff);
  out.push(0xff,0xff,0,0);
  out[0]=newTable&0xff; out[1]=(newTable>>8)&0xff;
  return {bin:new Uint8Array(out),iid:p.iid};
}
function iscTextFromEntry(e){
  const d=ISC.doc.d, limit=ISC.doc.idTable; const all=new Set();
  for(const [,off] of e.anims){ if(!off)continue; for(const p of iscTrace(d,off,limit))all.add(p); }
  const starts=[...all].sort((a,b)=>a-b); const lab=p=>'L'+p.toString(16);
  const L=['.header id='+e.id+' type='+e.type];
  for(const [nm,off] of e.anims){ if(off)L.push(nm+' -> '+lab(off)); }
  L.push('.code');
  for(const p of starts){ const ins=iscDecodeOne(d,p); L.push(lab(p)+':');
    const a=ins.args.map(x=>x.t==='label'?lab(x.v):x.v).join(' ');
    L.push('    '+ins.name+(a?' '+a:'')); }
  return L.join('\n');
}
$('#iscAsmToggle').addEventListener('click',()=>{
  const on=$('#iscAsm').style.display==='none'; $('#iscAsm').style.display=on?'block':'none'; $('#iscDis').style.display=on?'none':'block';
  if(on&&!$('#iscAsmText').value&&ISC.sel!=null){ const e=ISC.doc.entries.find(x=>x.id===ISC.sel); if(e)$('#iscAsmText').value=iscTextFromEntry(e); }
});
$('#iscAsmFromSel').addEventListener('click',()=>{ if(ISC.sel==null){ setStatus('Select a script first.',true); return; }
  const e=ISC.doc.entries.find(x=>x.id===ISC.sel); if(e)$('#iscAsmText').value=iscTextFromEntry(e); });
$('#iscAsmCompile').addEventListener('click',()=>{
  const stat=$('#iscAsmStat');
  try{ const {bin,iid}=iscMergeText(ISC.doc.d,$('#iscAsmText').value);
    // ORACLE: reparse + coverage
    const doc=iscParse(bin.buffer); let bad=0; const all=new Set();
    for(const e of doc.entries)for(const [,off] of e.anims){ if(!off)continue; try{ for(const q of iscTrace(doc.d,off,doc.idTable))all.add(q); }catch(e){ bad++; } }
    if(bad){ stat.innerHTML='<span class="bad" style="color:#e0708a">✕ desync ('+bad+')</span>'; return; }
    ISC.doc=doc; ISC.edited=true; iscRenderList(); iscSelect(iid);
    stat.innerHTML='<span class="ok" style="color:#5ad18a">✓ merge OK · id '+iid+' · '+bin.length+' B · '+all.size+' opcodes clean</span>';
  }catch(err){ stat.innerHTML='<span class="bad" style="color:#e0708a">✕ '+err.message+'</span>'; }
});

// welcome dashboard cards -> trigger the matching (hidden) tool button
document.querySelectorAll('.dcard.act[data-open]').forEach(c=>c.addEventListener('click',()=>{
  const el=document.getElementById(c.dataset.open); if(el)el.click();
}));
// clicking the logo returns to the welcome dashboard (no page reload needed)
function goHome(){
  S.active=null; stopAnim();
  ['wf','cai','hud','mod','bot','dat','spr','isc'].forEach(id=>{const el=document.getElementById(id); if(el)el.classList.remove('on');});
  $('#infoMsg').style.display='none';
  render();   // S.active null -> emptyState (dashboard) shown
}
(function(){ const lg=document.querySelector('.logo'); if(lg){ lg.style.cursor='pointer'; lg.title='Home (toolkit menu)';
  lg.addEventListener('click',goHome); } })();
// header "Tools" dropdown — reachable from any view; items trigger the same hidden buttons
(function(){
  const dd=$('#toolsDD'), tog=$('#toolsToggle');
  tog.addEventListener('click',e=>{ e.stopPropagation(); dd.classList.toggle('on'); });
  dd.querySelectorAll('.ti[data-open]').forEach(it=>it.addEventListener('click',()=>{
    dd.classList.remove('on'); const el=document.getElementById(it.dataset.open); if(el)el.click(); }));
  document.addEventListener('click',e=>{ if(!e.target.closest('.toolsmenu'))dd.classList.remove('on'); });
  document.addEventListener('keydown',e=>{ if(e.key==='Escape')dd.classList.remove('on'); });
})();

// light / dark theme toggle — persists to localStorage, else follows the OS
(function(){
  const btn=document.getElementById('themeBtn'); if(!btn) return;
  const root=document.documentElement;
  const mq=window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)');
  const eff=()=>{ const a=root.getAttribute('data-theme'); return a?a:((mq&&mq.matches)?'light':'dark'); };
  const paint=()=>{ btn.textContent = eff()==='light' ? '☀' : '🌙'; };
  try{ const s=localStorage.getItem('scab-theme'); if(s==='light'||s==='dark') root.setAttribute('data-theme',s); }catch(e){}
  paint();
  btn.addEventListener('click',()=>{ const next=eff()==='light'?'dark':'light'; root.setAttribute('data-theme',next);
    try{ localStorage.setItem('scab-theme',next); }catch(e){} paint(); });
  if(mq&&mq.addEventListener) mq.addEventListener('change',paint);
})();

// command palette — fuzzy tool launcher (Ctrl/⌘+K). Reads the same tool list the
// dropdown uses, so a new tool added there appears here automatically.
(function(){
  const ov=document.getElementById('cmdk'); if(!ov) return;
  const inp=document.getElementById('cmdkInput'), list=document.getElementById('cmdkList');
  const items=[...document.querySelectorAll('#toolsDD .ti[data-open]')].map(t=>{
    const icon=((t.querySelector('.tii')||{}).textContent||'•').trim();
    // textContent includes the .tii icon; strip it so it isn't shown twice
    const label=(t.textContent||'').trim().replace(new RegExp('^'+icon.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')),'').trim();
    return {id:t.dataset.open, icon, label};
  });
  const norm=s=>s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g,'');
  let cur=0, view=items;
  function markSel(){ [...list.children].forEach((c,i)=>c.classList.toggle('sel',i===cur));
    const el=list.children[cur]; if(el&&el.scrollIntoView)el.scrollIntoView({block:'nearest'}); }
  function draw(){
    list.innerHTML='';
    if(!view.length){ const e=document.createElement('div'); e.className='cmdk-empty'; e.textContent='no matches'; list.appendChild(e); return; }
    cur=Math.max(0,Math.min(cur,view.length-1));
    view.forEach((it,i)=>{ const d=document.createElement('div'); d.className='cmdk-item'+(i===cur?' sel':'');
      const ic=document.createElement('span'); ic.className='ci'; ic.textContent=it.icon;
      const lb=document.createElement('span'); lb.textContent=it.label;
      d.appendChild(ic); d.appendChild(lb);
      d.addEventListener('click',()=>choose(i));
      d.addEventListener('mousemove',()=>{ if(cur!==i){cur=i;markSel();} });
      list.appendChild(d); }); }
  function filter(){ const q=norm(inp.value.trim());
    view=q?items.filter(it=>norm(it.label).includes(q)):items; cur=0; draw(); }
  function open(){ ov.classList.add('on'); inp.value=''; view=items; cur=0; draw(); setTimeout(()=>inp.focus(),0); }
  function close(){ ov.classList.remove('on'); }
  function choose(i){ const it=view[i]; if(!it)return; close(); const b=document.getElementById(it.id); if(b)b.click(); }
  inp.addEventListener('input',filter);
  inp.addEventListener('keydown',e=>{
    if(e.key==='ArrowDown'){e.preventDefault();cur=Math.min(cur+1,view.length-1);markSel();}
    else if(e.key==='ArrowUp'){e.preventDefault();cur=Math.max(cur-1,0);markSel();}
    else if(e.key==='Enter'){e.preventDefault();choose(cur);}
    else if(e.key==='Escape'){e.preventDefault();close();} });
  ov.addEventListener('click',e=>{ if(e.target===ov)close(); });
  document.addEventListener('keydown',e=>{
    if((e.ctrlKey||e.metaKey)&&(e.key==='k'||e.key==='K')){ e.preventDefault(); ov.classList.contains('on')?close():open(); } });
  const pb=document.getElementById('cmdkBtn'); if(pb)pb.addEventListener('click',open);
})();

(function(){const el=document.getElementById('builtinListfile');
  if(el&&el.textContent){S.externalListfile=el.textContent.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);S.builtinListfile=true;}})();
setStatus('Ready. Select a tool or open data.');
