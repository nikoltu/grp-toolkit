#!/usr/bin/env python3
"""
casc.py — StarCraft: Remastered (and other NGDP) LOCAL CASC reader / extractor.

Validated low-level layers (against retail SC:R data): config parsing,
local .idx (v7) parsing, data.### blob header, and BLTE decode (N / Z / F).

What it does now, reliably:
  * Index every EKey in Data/data/*.idx  ->  (data.### file, offset, size)
  * Read + BLTE-decode any blob by EKey
  * Enumerate & extract graphics by content sniff (GRP / DDS / PCX / ANIM),
    named by EKey (no filenames needed)

Name-based extraction (filename -> content) additionally needs the encoding
file (build-config `encoding` EKey) and the SC:R root file (`root` CKey ->
via encoding -> EKey). This script implements the encoding parser to spec;
the SC:R root parser is left as a stub because it could not be validated here.
For named extraction today, CascView is the pragmatic route, then point the
sc-asset-browser at the extracted folder.

Usage:
  python3 casc.py <Data/data dir> --list                 # count/index
  python3 casc.py <Data/data dir> --graphics OUTDIR       # extract all GRP/DDS/PCX/ANIM
  python3 casc.py <Data/data dir> --ekey <hex> -o out.bin # extract one blob
"""
import os, sys, struct, zlib, glob, argparse

# ---------------- config ----------------
def parse_config(text):
    o={}
    for line in text.splitlines():
        t=line.strip()
        if not t or t.startswith('#'): continue
        if '=' in t:
            k,v=t.split('=',1); o[k.strip()]=v.strip()
    return o

# ---------------- local .idx (v7) ----------------
def parse_idx(path):
    d=open(path,'rb').read()
    span_size_b=d[12]; span_off_b=d[13]; key_b=d[14]; seg_bits=d[15]
    entries_size=struct.unpack('<I',d[0x20:0x24])[0]
    off=0x28; elen=key_b+span_off_b+span_size_b
    out=[]
    for i in range(entries_size//elen):
        o=off+i*elen
        ekey=d[o:o+key_b]
        packed=int.from_bytes(d[o+key_b:o+key_b+span_off_b],'big')
        size=int.from_bytes(d[o+key_b+span_off_b:o+key_b+span_off_b+span_size_b],'little')
        out.append((ekey.hex(), packed>>seg_bits, packed&((1<<seg_bits)-1), size))
    return out

def build_index(data_dir):
    index={}
    for p in sorted(glob.glob(os.path.join(data_dir,'*.idx'))):
        for ekey,fi,off,size in parse_idx(p):
            index[ekey]=(fi,off,size)   # last write wins (newest .idx)
    return index

# ---------------- BLTE ----------------
def blte_decode(data):
    if data[:4]!=b'BLTE': raise ValueError('not BLTE')
    hsize=struct.unpack('>I',data[4:8])[0]
    chunks=[]
    if hsize>0:
        cnt=int.from_bytes(data[9:12],'big'); p=12
        for _ in range(cnt):
            cs=struct.unpack('>I',data[p:p+4])[0]; ds=struct.unpack('>I',data[p+4:p+8])[0]
            p+=8+16; chunks.append((cs,ds))
        start=hsize
    else:
        chunks=[(len(data)-8,0)]; start=8
    out=bytearray(); p=start
    for cs,ds in chunks:
        chunk=data[p:p+cs]; p+=cs; mode=chunk[0]; body=chunk[1:]
        if mode==0x4E: out+=body
        elif mode==0x5A: out+=zlib.decompress(body)
        elif mode==0x46: out+=blte_decode(body)
        elif mode==0x45: raise ValueError('encrypted BLTE chunk (needs key)')
        else: raise ValueError('BLTE mode %r'%chr(mode))
    return bytes(out)

class Storage:
    def __init__(self, data_dir):
        self.dir=data_dir
        self.index=build_index(data_dir)
        self._fh={}
    def _file(self, idx):
        if idx not in self._fh:
            self._fh[idx]=open(os.path.join(self.dir,'data.%03d'%idx),'rb')
        return self._fh[idx]
    def read_ekey(self, ekey_hex9):
        e=self.index.get(ekey_hex9[:18])
        if not e: raise KeyError(ekey_hex9)
        fi,off,size=e
        f=self._file(fi); f.seek(off); raw=f.read(size)
        return blte_decode(raw[30:])   # skip 30-byte blob header

# ---------------- encoding + root (name resolution) ----------------
def parse_encoding(buf):
    ckey_page_kb=struct.unpack('>H',buf[5:7])[0]
    ckey_page_count=struct.unpack('>I',buf[9:13])[0]
    espec=struct.unpack('>I',buf[18:22])[0]
    page=ckey_page_kb*1024; pages_off=22+espec+ckey_page_count*32
    m={}
    for pg in range(ckey_page_count):
        p=pages_off+pg*page; end=p+page
        while p<end:
            kc=buf[p]
            if kc==0: break
            ck=buf[p+6:p+22].hex(); ek=buf[p+22:p+38].hex()
            m[ck]=ek; p+=22+kc*16
    return m

def parse_root(buf):
    m={}
    for line in buf.decode('latin-1').replace('\r','').split('\n'):
        if '|' in line:
            name,ck=line.rsplit('|',1); m[name.lower()]=ck.strip()
    return m

def find_build_config(root_dir):
    import re as _re
    for dp,_,fns in os.walk(root_dir):
        for fn in fns:
            if _re.match(r'^[0-9a-f]{32}$',fn):
                p=os.path.join(dp,fn)
                try:
                    if os.path.getsize(p)<8192:
                        t=open(p,'r',errors='ignore').read()
                        if 'root =' in t and 'encoding =' in t:
                            enc=_re.search(r'encoding\s*=\s*[0-9a-f]{32}\s+([0-9a-f]{32})',t)
                            rt=_re.search(r'root\s*=\s*([0-9a-f]{32})',t)
                            if enc and rt: return enc.group(1),rt.group(1)
                except Exception: pass
    return None,None

class NamedStorage(Storage):
    """Storage + name resolution via build config -> encoding -> root."""
    def __init__(self, data_dir, install_root=None):
        super().__init__(data_dir)
        self.enc=None; self.root=None
        ir=install_root or os.path.dirname(os.path.dirname(os.path.abspath(data_dir)))
        enc_ek,root_ck=find_build_config(ir)
        if enc_ek and root_ck:
            self.enc=parse_encoding(self.read_ekey(enc_ek))
            self.root=parse_root(self.read_ekey(self.enc[root_ck]))
    def read_name(self,name):
        ck=self.root[name.lower().replace('\\','/')]; ek=self.enc[ck]; return self.read_ekey(ek)


def sniff(b):
    if len(b)<6: return None
    if b[:4]==b'DDS ': return 'dds'
    if b[:4]==b'ANIM': return 'anim'
    if b[0]==0x0A and b[2] in (0,1): return 'pcx'
    # classic GRP: u16 frames, u16 w<=256, u16 h<=256, plausible
    fc,w,h=struct.unpack('<HHH',b[:6])
    if 0<fc<10000 and 0<w<=800 and 0<h<=800: return 'grp'
    return None

# ---------------- main ----------------
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('data_dir')
    ap.add_argument('--list',action='store_true')
    ap.add_argument('--graphics',metavar='OUTDIR')
    ap.add_argument('--ekey')
    ap.add_argument('--name',help='extract by filename via build config->encoding->root')
    ap.add_argument('--named-graphics',metavar='OUTDIR',help='extract all GRP/DDS/ANIM/PCX by real name')
    ap.add_argument('--install',help='install root (for build config); default: 2 levels above data_dir')
    ap.add_argument('-o',dest='out')
    a=ap.parse_args()
    if a.name or a.named_graphics:
        st=NamedStorage(a.data_dir, a.install)
        if not st.root:
            print('could not locate build config/encoding/root — is --install correct?'); return
        print('resolved %d names via root'%len(st.root))
        if a.name:
            data=st.read_name(a.name)
            open(a.out or os.path.basename(a.name),'wb').write(data)
            print('wrote',len(data),'bytes for',a.name); return
        outdir=a.named_graphics; os.makedirs(outdir,exist_ok=True); n=0
        for name in st.root:
            if name.rsplit('.',1)[-1] in ('grp','dds','anim','pcx'):
                try:
                    data=st.read_name(name)
                    dst=os.path.join(outdir,name.replace('/',os.sep))
                    os.makedirs(os.path.dirname(dst),exist_ok=True)
                    open(dst,'wb').write(data); n+=1
                except Exception: pass
        print('extracted %d named graphics -> %s'%(n,outdir)); return
    st=Storage(a.data_dir)
    print('indexed %d EKeys across %d data files'%(len(st.index),
          len(set(v[0] for v in st.index.values()))))
    if a.ekey:
        data=st.read_ekey(a.ekey)
        open(a.out or (a.ekey[:16]+'.bin'),'wb').write(data)
        print('wrote',len(data),'bytes'); return
    if a.graphics:
        os.makedirs(a.graphics,exist_ok=True)
        counts={}; n=0
        for ekey,(fi,off,size) in st.index.items():
            try:
                data=st.read_ekey(ekey)
                k=sniff(data)
                if k:
                    ext={'grp':'.grp','dds':'.dds.grp','pcx':'.pcx','anim':'.anim'}[k]
                    open(os.path.join(a.graphics,ekey[:16]+ext),'wb').write(data)
                    counts[k]=counts.get(k,0)+1; n+=1
            except Exception:
                pass
        print('extracted %d graphic assets:'%n, counts)
        print('(named by EKey — open the folder in sc-asset-browser to view)')
        return
    if a.list:
        by_file={}
        for ekey,(fi,off,size) in st.index.items():
            by_file[fi]=by_file.get(fi,0)+1
        for fi in sorted(by_file): print('  data.%03d: %d entries'%(fi,by_file[fi]))

if __name__=='__main__':
    main()
