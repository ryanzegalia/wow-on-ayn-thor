"""Disassemble an RVA range of an ARM64 PE, with .pdata function-bounds lookup.

usage:
  pe_dis.py <pe> fn <rva>           -> find enclosing RUNTIME_FUNCTION, disasm whole function
  pe_dis.py <pe> dis <rva> <len>    -> disasm raw range
  pe_dis.py <pe> pdata <rva>        -> just print the .pdata entry for rva
"""
import struct, sys
import capstone

P = sys.argv[1]
d = open(P, 'rb').read()
e = struct.unpack_from('<I', d, 0x3c)[0]
nsec = struct.unpack_from('<H', d, e + 6)[0]
optsz = struct.unpack_from('<H', d, e + 20)[0]
magic = struct.unpack_from('<H', d, e + 24)[0]
opt = e + 24
imgbase = struct.unpack_from('<Q', d, opt + 24)[0] if magic == 0x20b else struct.unpack_from('<I', d, opt+28)[0]
ddoff = opt + (112 if magic == 0x20b else 96)
EXC_RVA, EXC_SZ = struct.unpack_from('<II', d, ddoff + 3*8)
sec = opt + optsz
secs = []
for i in range(nsec):
    o = sec + i * 40
    name = d[o:o+8].rstrip(b'\0').decode('ascii','replace')
    vs, va, rs, raw = struct.unpack_from('<IIII', d, o+8)
    secs.append((name, va, vs, raw, rs))

def r2o(rva):
    for name, va, vs, raw, rs in secs:
        if va <= rva < va + max(vs, 1):
            off = raw + (rva - va)
            if off < raw + rs:
                return off
    return None

md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
md.detail = False

def pdata_lookup(rva):
    n = EXC_SZ // 8
    base = r2o(EXC_RVA)
    lo, hi = 0, n - 1
    best = None
    while lo <= hi:
        mid = (lo + hi)//2
        beg, data = struct.unpack_from('<II', d, base + mid*8)
        if beg <= rva:
            best = (mid, beg, data); lo = mid + 1
        else:
            hi = mid - 1
    if not best: return None
    mid, beg, data = best
    # packed unwind if low 2 bits != 0
    if data & 3:
        flag = data & 3
        funclen = ((data >> 2) & 0x7FF) * 4
        return beg, funclen, data, 'packed'
    else:
        xoff = r2o(data)
        hdr = struct.unpack_from('<I', d, xoff)[0]
        funclen = (hdr & 0x3FFFF) * 4
        return beg, funclen, data, 'xdata'

def disas(rva, ln, marks=()):
    o = r2o(rva)
    for ins in md.disasm(d[o:o+ln], rva):
        m = '   <==' if ins.address in marks else ''
        raw = struct.unpack_from('<I', d, r2o(ins.address))[0]
        print(f"  +0x{ins.address:06x}  {raw:08x}  {ins.mnemonic:<10} {ins.op_str}{m}")

cmd = sys.argv[2]
if cmd == 'fn':
    rva = int(sys.argv[3], 0)
    r = pdata_lookup(rva)
    print(f"# pdata: start=+0x{r[0]:x} len=0x{r[1]:x} ({r[3]}) end=+0x{r[0]+r[1]:x}")
    disas(r[0], r[1], marks={rva})
elif cmd == 'dis':
    disas(int(sys.argv[3],0), int(sys.argv[4],0))
elif cmd == 'pdata':
    print(pdata_lookup(int(sys.argv[3],0)))
