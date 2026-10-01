#!/usr/bin/env python3
"""Patch Wine's aarch64 ntdll.dll so Blizzard's PRIVATE COPY of it can still reach
the real __wine_syscall_dispatcher.

THE BUG
-------
WoW's anti-tamper reads ntdll.dll off disk into an anonymous RWX mapping (exactly
the file's byte size), relocates it to its own base, and calls Wine's ARM64 syscall
thunks inside that private copy -- the classic "unhooked ntdll" trick. Each thunk is

    mov  x8, #<syscall nr>
    mov  x9, lr
    ldr  x16, =<literal>          ; 8-byte literal, DIR64-relocated
    ldr  x16, [x16]               ; __wine_syscall_dispatcher
    blr  x16
    ret

The literal on disk is 0x18011f750 (ImageBase 0x180000000 + RVA 0x11f750). That
.data slot is ALL ZEROS in the file -- only the live Wine loader fills it in. The
anti-tamper's loader faithfully applies the DIR64 reloc, rebasing the literal into
its own zeroed copy, so `blr x16` runs with x16 = 0 -> EXCEPTION_ACCESS_VIOLATION
at pc=0, forever.

THE FIX: pinslot (what works)
-----------------------------
On my device Wine mapped this ntdll at a DETERMINISTIC base, identical in every wine
process and across sessions (no ASLR). So the live dispatcher slot has a fixed address,
and it is populated (verified by reading /proc/<pid>/mem: it holds the unix-side
dispatcher). The base moves between builds. Measure yours (see FAILURE MODE below).
  July 2026 build:        base 0x4fffa50000, slot 0x4fffa50000 + 0x11f750 = 0x4fffb6f750
  my rebuilt proton-10:   base 0x7fffa50000, slot 0x7fffb6f750 (the build I ship)

  --pinslot <addr>   Rewrite every thunk literal from 0x18011f750 to <addr>, AND
                     neutralise the DIR64 relocs that cover them (rewrite the type
                     nibble to IMAGE_REL_BASED_ABSOLUTE = 0, the documented no-op
                     padding type, so every block's SizeOfBlock stays valid).
                     That is 245 thunks on the July 2026 build, 242 on my rebuild.

Both halves are required and they are only correct together:
  * real ntdll, loaded at the measured base: reloc stripped, so the literal stays
    <addr>, which is its own slot. Correct.
  * Blizzard's private copy, at any base: reloc stripped, so its loader cannot rebase
    the literal into its own zeroed .data. It reads the REAL ntdll's slot. Correct.

Every DIR64 reloc targeting .text points at this one value. The thunk literal is the
only relocated thing in .text, so the rewrite is exactly surgical. The other DIR64
relocs (.rdata/.data/.mrdata) are untouched, and DllCharacteristics is left alone, so
Wine still relocates the rest of the image normally. Counts: 245 to .text and 591
others on the July 2026 build, 242 and 588 on my rebuild.

FAILURE MODE: if ntdll's base ever moves, every syscall thunk reads an address that is
not the slot. I expect wine to die at startup then. Revert by restoring the unpatched
ntdll.dll. Re-measure the base with:
    grep aarch64-windows/ntdll.dll /proc/<pid>/maps

basepin -- TRIED 2026-09-19, DEAD. Clearing DYNAMIC_BASE|HIGH_ENTROPY_VA so ntdll would
land on its preferred 0x180000000 makes Wine refuse the image outright:
    wine: failed to load .../ntdll.dll error c000007b   (STATUS_INVALID_IMAGE_FORMAT)
Wine wants to relocate ntdll out of 0x180000000 (that address is not available inside
the GameNative app process) and, with no DYNAMIC_BASE, it will not. Kept here only so
nobody re-runs the experiment.

On the July 2026 build I applied it on top of the unwind fix (the two patches are
disjoint). On the rebuild I apply it alone (tools/release/make_release.sh).

Usage:
  patch_ntdll_syscall.py <ntdll.dll> --report
  patch_ntdll_syscall.py <ntdll.dll> -o out.dll --pinslot 0x7fffb6f750   # my rebuild
  patch_ntdll_syscall.py <ntdll.dll> -o out.dll --basepin          # DEAD, see above
"""
import argparse
import struct
import sys

IMAGE_BASE = 0x180000000
DISPATCHER_RVA = 0x11F750          # __wine_syscall_dispatcher slot in .data
LITERAL = IMAGE_BASE + DISPATCHER_RVA
EXPECT_SIZE = 6340608              # July 2026 build. My rebuild is 6234112 (needs --force)
EXPECT_DLLCHAR = 0x0160            # HIGH_ENTROPY_VA | DYNAMIC_BASE | NX_COMPAT
PINNED_DLLCHAR = 0x0100            # NX_COMPAT only
EXPECT_THUNKS = 245                # July 2026 build. My rebuild has 242 (needs --force)
THUNK_FIRST_RVA = 0x518D8          # July 2026 build. My rebuild: 0x52048 (auto-located)
THUNK_STRIDE = 0x20

MOV_X9_LR = 0xAA1E03E9             # mov x9, lr
LDR_X16_LIT = 0x58000070           # ldr x16, <literal>  (imm19 varies)
LDR_X16_X16 = 0xF9400210           # ldr x16, [x16]
BLR_X16 = 0xD63F0200               # blr x16
RET = 0xD65F03C0                   # ret


class PE:
    def __init__(self, data):
        self.d = bytearray(data)
        self.e = struct.unpack_from('<I', self.d, 0x3C)[0]
        if self.d[self.e:self.e + 4] != b'PE\0\0':
            sys.exit('not a PE')
        self.opt = self.e + 24
        if struct.unpack_from('<H', self.d, self.opt)[0] != 0x20B:
            sys.exit('not PE32+')
        self.imgbase = struct.unpack_from('<Q', self.d, self.opt + 24)[0]
        self.dllchar_off = self.opt + 70
        self.dd = self.opt + 112
        nsec = struct.unpack_from('<H', self.d, self.e + 6)[0]
        optsz = struct.unpack_from('<H', self.d, self.e + 20)[0]
        self.secs = []
        for i in range(nsec):
            o = self.e + 24 + optsz + i * 40
            name = bytes(self.d[o:o + 8]).rstrip(b'\0').decode('ascii', 'replace')
            vs, va, rs, raw = struct.unpack_from('<IIII', self.d, o + 8)
            self.secs.append((name, va, vs, raw, rs))

    def dllchar(self):
        return struct.unpack_from('<H', self.d, self.dllchar_off)[0]

    def dir(self, i):
        return struct.unpack_from('<II', self.d, self.dd + i * 8)

    def r2o(self, rva):
        for name, va, vs, raw, rs in self.secs:
            if va <= rva < va + max(vs, 1):
                off = raw + (rva - va)
                if off < raw + rs:
                    return off
        return None

    def word(self, rva):
        return struct.unpack_from('<I', self.d, self.r2o(rva))[0]

    def qword_at_off(self, off):
        return struct.unpack_from('<Q', self.d, off)[0]

    def reloc_entries(self):
        """yield (entry_file_off, type, target_rva)"""
        rva, size = self.dir(5)
        base = self.r2o(rva)
        off, end = base, base + size
        while off < end:
            page, sz = struct.unpack_from('<II', self.d, off)
            if sz < 8:
                break
            for i in range((sz - 8) // 2):
                eo = off + 8 + i * 2
                w = struct.unpack_from('<H', self.d, eo)[0]
                yield eo, w >> 12, page + (w & 0xFFF)
            off += sz


def thunk_shape(pe, lit_rva):
    """The 5 instruction words preceding the 8-byte literal."""
    return [pe.word(lit_rva - 0x14 + 4 * i) for i in range(5)]


def is_thunk(pe, lit_rva):
    """True if lit_rva is the literal pool slot of a Wine ARM64 syscall thunk:
       mov x8,#nr / mov x9,lr / ldr x16,<lit> / ldr x16,[x16] / blr x16 / ret"""
    if pe.r2o(lit_rva) is None or pe.r2o(lit_rva - 0x14) is None:
        return False
    w = thunk_shape(pe, lit_rva)
    return (w[0] == MOV_X9_LR
            and (w[1] & 0xFF00001F) == (LDR_X16_LIT & 0xFF00001F)
            and w[2] == LDR_X16_X16
            and w[3] == BLR_X16
            and w[4] == RET)


def locate_first_thunk(pe):
    """Scan .text for the first syscall thunk. THUNK_FIRST_RVA is only valid for the
    July 2026 build. A rebuilt ntdll moves the table (e.g. 0x518D8 -> 0x52048 on the
    build I ship), and a stale constant silently yields ZERO thunks, which --force
    would then happily 'patch'. Auto-locating keeps the tool correct across rebuilds."""
    if is_thunk(pe, THUNK_FIRST_RVA):
        return THUNK_FIRST_RVA
    for name, va, vs, raw, rs in pe.secs:
        if name != '.text':
            continue
        end = va + min(vs, rs)
        rva = va + 0x14
        while rva < end - 8:
            if is_thunk(pe, rva):
                return rva
            rva += 4
    return None


def find_thunks(pe):
    """Walk the thunk table STRUCTURALLY (not by literal value, which this tool
    rewrites). Returns [(lit_rva, literal_value, reloc_entry_off_or_None)]."""
    relocs = {}
    for eo, typ, rva in pe.reloc_entries():
        if typ != 0:
            relocs[rva] = eo
    first = locate_first_thunk(pe)
    if first is None:
        return []
    if first != THUNK_FIRST_RVA:
        print('note: thunk table at rva 0x%x (not the built-in 0x%x) -- rebuilt ntdll' % (first, THUNK_FIRST_RVA), file=sys.stderr)
    out = []
    rva = first
    while is_thunk(pe, rva):
        out.append((rva, pe.qword_at_off(pe.r2o(rva)), relocs.get(rva)))
        rva += THUNK_STRIDE
    return out


IMAGE_DYNAMIC_RELOCATION_ARM64X = 6


def arm64x_dvrt(pe):
    """Read-only. Find the ARM64X dynamic value relocation table the way Wine's
    update_arm64x_mapping() does (dlls/ntdll/unix/virtual.c): LoadConfig
    DynamicValueRelocTableOffset at +0xE0 and DynamicValueRelocTableSection at +0xE4
    of the 64-bit layout. Walk it the way apply_arm64x_relocations() does.
    Returns None if the image has no table, else
    (section_number, offset, table_version, [(rva, nbytes), ...] for every fixup)."""
    lc_rva, lc_size = pe.dir(10)
    lo = pe.r2o(lc_rva) if lc_rva else None
    if lo is None:
        return None
    size = min(lc_size, struct.unpack_from('<I', pe.d, lo)[0])
    if size <= 0xE4:
        return None
    off, sec = struct.unpack_from('<IH', pe.d, lo + 0xE0)
    if not sec or sec > len(pe.secs) or off >= pe.secs[sec - 1][2]:
        return None
    t = pe.r2o(pe.secs[sec - 1][1] + off)
    if t is None:
        return None
    ver, tsize = struct.unpack_from('<II', pe.d, t)
    p, end, fix = t + 8, t + 8 + tsize, []
    while p < end and ver in (1, 2):
        if ver == 1:       # IMAGE_DYNAMIC_RELOCATION64, packed, 12 bytes
            sym, blen = struct.unpack_from('<QI', pe.d, p)
            first, step = p + 12, 12 + blen
        else:              # IMAGE_DYNAMIC_RELOCATION64_V2, packed, 24 bytes
            hsize, blen, sym = struct.unpack_from('<IIQ', pe.d, p)
            first, step = p + 24, hsize + blen
        if sym == IMAGE_DYNAMIC_RELOCATION_ARM64X:
            b, bend = first, first + blen
            while b < bend - 8:
                page, bsize = struct.unpack_from('<II', pe.d, b)
                if not bsize:
                    break
                r, rend = b + 8, b + bsize
                while r < rend:
                    w = struct.unpack_from('<H', pe.d, r)[0]
                    if not w:
                        break
                    r += 2
                    typ, arg, rva = (w >> 12) & 3, w >> 14, page + (w & 0xFFF)
                    if typ == 0:        # ZEROFILL
                        fix.append((rva, 1 << arg))
                    elif typ == 1:      # VALUE, the value follows
                        fix.append((rva, 1 << arg))
                        r += ((1 << arg) // 2) * 2
                    elif typ == 2:      # DELTA, one USHORT follows
                        fix.append((rva, 4))
                        r += 2
                b = rend
            break
        if step <= 0:
            break
        p += step
    return sec, off, ver, fix


def report(pe):
    dc = pe.dllchar()
    print('ImageBase           0x%x' % pe.imgbase)
    print('DllCharacteristics  0x%04x  (DYNAMIC_BASE=%s, HIGH_ENTROPY_VA=%s)'
          % (dc, 'SET' if dc & 0x40 else 'clear', 'SET' if dc & 0x20 else 'clear'))
    rr, rs = pe.dir(5)
    print('.reloc              rva=0x%x size=0x%x' % (rr, rs))
    th = find_thunks(pe)
    vals = sorted(set(v for _, v, _ in th))
    nrel = sum(1 for _, _, e in th if e is not None)
    print('syscall thunks found: %d  (rva 0x%x..0x%x, stride %d)'
          % (len(th), th[0][0], th[-1][0], THUNK_STRIDE) if th else 'syscall thunks found: 0')
    print('  literal value(s): %s' % ', '.join('0x%x' % v for v in vals[:4]))
    print('  still DIR64-relocated: %d / %d' % (nrel, len(th)))
    if th:
        print('  sample thunk @0x%x: %s'
              % (th[0][0] - 0x14, ' '.join('%08x' % w for w in thunk_shape(pe, th[0][0]))))
    slot = pe.r2o(DISPATCHER_RVA)
    print('dispatcher slot rva 0x%x (file 0x%x) = %s'
          % (DISPATCHER_RVA, slot, bytes(pe.d[slot:slot + 8]).hex()))
    dv = arm64x_dvrt(pe)
    if dv is None:
        print('ARM64X dynamic relocs: none (no LoadConfig DynamicValueRelocTableSection)')
    else:
        sec, off, ver, fix = dv
        rr, rs = pe.dir(5)

        def touching(ranges):
            return sum(1 for f, n in fix if any(f < z and f + n > a for a, z in ranges))
        print('ARM64X dynamic relocs: PRESENT in %s +0x%x (table version %d), %d fixup(s)'
              % (pe.secs[sec - 1][0], off, ver, len(fix)))
        print('  fixups touching the thunk literals: %d, touching the .reloc entries: %d'
              % (touching([(r, r + 8) for r, _, _ in th]), touching([(rr, rr + rs)])))
        print('  Wine applies them only when it maps this image for x64 '
              '(update_arm64x_mapping in dlls/ntdll/unix/virtual.c)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pe')
    ap.add_argument('-o', '--out')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--pinslot', metavar='ADDR',
                    help='absolute live address of __wine_syscall_dispatcher, '
                         'e.g. 0x7fffb6f750 (my rebuild, = ntdll live base + 0x11f750)')
    ap.add_argument('--basepin', action='store_true', help='DEAD -- see module docstring')
    ap.add_argument('--force', action='store_true',
                    help='skip every refusal except ImageBase: size, thunk count, '
                         'already patched, missing relocs, slot alignment and page offset')
    a = ap.parse_args()

    raw = open(a.pe, 'rb').read()
    pe = PE(raw)

    if a.report or not (a.basepin or a.pinslot):
        report(pe)
        return

    if not a.out:
        sys.exit('-o is required when patching')
    if len(raw) != EXPECT_SIZE and not a.force:
        sys.exit('refusing: size %d != expected %d' % (len(raw), EXPECT_SIZE))
    if pe.imgbase != IMAGE_BASE:
        sys.exit('refusing: ImageBase 0x%x != 0x%x' % (pe.imgbase, IMAGE_BASE))

    th = find_thunks(pe)
    changed = []

    if a.basepin:
        dc = pe.dllchar()
        if dc == PINNED_DLLCHAR and not a.force:
            sys.exit('refusing: DllCharacteristics already pinned (0x0100)')
        if dc != EXPECT_DLLCHAR and not a.force:
            sys.exit('refusing: DllCharacteristics 0x%04x != expected 0x%04x'
                     % (dc, EXPECT_DLLCHAR))
        struct.pack_into('<H', pe.d, pe.dllchar_off, PINNED_DLLCHAR)
        changed.append('basepin: DllCharacteristics 0x%04x -> 0x%04x' % (dc, PINNED_DLLCHAR))

    if a.pinslot:
        slot = int(a.pinslot, 0)
        if len(th) != EXPECT_THUNKS and not a.force:
            sys.exit('refusing: found %d syscall thunks, expected %d' % (len(th), EXPECT_THUNKS))
        bad = [r for r, v, _ in th if v != LITERAL]
        if bad and not a.force:
            sys.exit('refusing: %d thunk literal(s) are not 0x%x (already pinned? '
                     'first at rva 0x%x = 0x%x)'
                     % (len(bad), LITERAL, bad[0],
                        next(v for r, v, _ in th if r == bad[0])))
        unrel = [r for r, _, e in th if e is None]
        if unrel and not a.force:
            sys.exit('refusing: %d thunk literal(s) have no DIR64 reloc '
                     '(already stripped? first at rva 0x%x)' % (len(unrel), unrel[0]))
        if slot & 7 and not a.force:
            sys.exit('refusing: slot 0x%x is not 8-byte aligned' % slot)
        if (slot & 0xFFF) != (DISPATCHER_RVA & 0xFFF) and not a.force:
            sys.exit('refusing: slot 0x%x page offset 0x%x != dispatcher RVA page offset 0x%x '
                     '-- almost certainly the wrong address'
                     % (slot, slot & 0xFFF, DISPATCHER_RVA & 0xFFF))
        for rva, _, eo in th:
            struct.pack_into('<Q', pe.d, pe.r2o(rva), slot)
            w = struct.unpack_from('<H', pe.d, eo)[0]
            struct.pack_into('<H', pe.d, eo, w & 0x0FFF)   # type nibble -> ABSOLUTE
        changed.append('pinslot: %d literals 0x%x -> 0x%x, their DIR64 relocs -> ABSOLUTE '
                       '(rva 0x%x..0x%x)'
                       % (len(th), LITERAL, slot, th[0][0], th[-1][0]))
        changed.append('  implied live ntdll base: 0x%x' % (slot - DISPATCHER_RVA))

    open(a.out, 'wb').write(bytes(pe.d))

    v = PE(open(a.out, 'rb').read())
    print('WROTE %s' % a.out)
    for c in changed:
        print('   ' + c)
    print('--- verify ---')
    report(v)
    diffs = [i for i in range(len(raw)) if raw[i] != v.d[i]]
    expect = (2 if a.basepin else 0) + (10 * len(th) if a.pinslot else 0)
    print('bytes changed: %d (expected <= %d)' % (len(diffs), expect))
    if a.pinslot:
        rr, rs = v.dir(5)
        ro = v.r2o(rr)
        off, end, blocks = ro, ro + rs, 0
        while off < end:
            page, sz = struct.unpack_from('<II', v.d, off)
            if sz < 8:
                break
            blocks += 1
            off += sz
        print('.reloc walks cleanly: %d blocks, ends exactly at size: %s'
              % (blocks, 'YES' if off == end else 'NO -- CORRUPT'))


if __name__ == '__main__':
    main()
