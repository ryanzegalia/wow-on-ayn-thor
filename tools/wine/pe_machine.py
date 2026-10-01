import sys,struct,os
MACH={0x8664:'x86_64',0xAA64:'ARM64',0x14c:'x86',0x1c0:'ARM',0xA641:'ARM64EC(hdr)'}
for p in sys.argv[1:]:
    d=open(p,'rb').read()
    e=struct.unpack_from('<I',d,0x3c)[0]
    mach=struct.unpack_from('<H',d,e+4)[0]
    nsec=struct.unpack_from('<H',d,e+6)[0]
    optsz=struct.unpack_from('<H',d,e+20)[0]
    magic=struct.unpack_from('<H',d,e+24)[0]
    # data dir 14 = CLR, 10 = load config; ARM64EC detected via load config CHPEMetadata
    ddoff=e+24+(112 if magic==0x20b else 96)
    lc_rva,lc_sz=struct.unpack_from('<II',d,ddoff+10*8)
    # section table to map rva->off
    secoff=e+24+optsz
    def r2o(rva):
        for i in range(nsec):
            o=secoff+i*40
            va=struct.unpack_from('<I',d,o+12)[0]; vs=struct.unpack_from('<I',d,o+8)[0]
            raw=struct.unpack_from('<I',d,o+20)[0]
            if va<=rva<va+max(vs,1): return raw+(rva-va)
        return None
    chpe=0
    if lc_rva:
        off=r2o(lc_rva)
        if off and lc_sz>=0xc8:
            try: chpe=struct.unpack_from('<Q',d,off+0xC8)[0]
            except: chpe=0
    kind='ARM64EC/ARM64X' if (mach==0xAA64 and chpe) else MACH.get(mach,hex(mach))
    print(f"{os.path.basename(p):16s} machine={MACH.get(mach,hex(mach)):8s} chpe={'yes' if chpe else 'no':3s} -> {kind}  {len(d)} bytes")
