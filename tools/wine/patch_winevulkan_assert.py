#!/usr/bin/env python3
"""Make winevulkan's vkCreateGraphicsPipelines thunk non-fatal.

WHY
---
On the Thor, Mesa's ir3 scheduler deadlocks on one of WoW's uber-shaders
(`ir3_sched` -> `choose_instr` returns NULL -> `ctx->error = true`), Turnip's
failure path then dereferences NULL+0x68 and SEGVs.  Wine catches that SEGV in
its syscall dispatcher and hands the PE side `c0000005` as the unix call's
NTSTATUS.  winevulkan's generated thunk does:

    NTSTATUS status = UNIX_CALL(vkCreateGraphicsPipelines, &params);
    assert(!status && "vkCreateGraphicsPipelines");
    /* loader_thunks.c:3154 on the July 2026 build, 3216 on the rebuild */
    return params.result;

and that assert is what actually kills the process (abort -> GameNative 137).
DXVK copes fine with a pipeline that fails to compile -- it logs and moves on --
so turning the abort into a returned VkResult converts a fatal crash into (at
worst) a missing visual effect.

WHAT IT DOES
------------
The thunk's tail looks like:

    blr  x8                      ; the unix call
    cbnz w0, assert_path         ; status != 0
    ldr  w0, [sp, #imm]          ; normal: return params.result
    ldr  x30, [sp, #imm]
    add  sp, sp, #imm
    ret
  assert_path:
    adrp x8, ...  / adrp x0, <"!status && \"vkCreateGraphicsPipelines\"">
    ...
    mov  w2, #3154
    blr  x8                      ; _assert
    brk  #1

The patch overwrites the first 16 bytes of `assert_path` with

    movn w0, #12                 ; w0 = -13 = VK_ERROR_UNKNOWN
    <the function's own 3 epilogue words: ldr x30 / add sp / ret>

The `cbnz` is left alone, so the success path is untouched; only the
previously-fatal branch changes.  The epilogue words are COPIED from this
function's real epilogue rather than hardcoded, so the frame layout always
matches and the existing .pdata/xdata unwind info stays valid.

NOTE: a plain NOP of the `cbnz` would be wrong -- `params.result` is never
written when the unix call faults, so it would return uninitialised stack, and
a chance 0 there reads as VK_SUCCESS with null pipeline handles.

usage:
  patch_winevulkan_assert.py <winevulkan.dll> --report
  patch_winevulkan_assert.py <in.dll> --out <out.dll>
"""
import struct
import sys

ASSERT_STR = b'!status && "vkCreateGraphicsPipelines"\x00'

MOVN_W0_12 = 0x12800180   # movn w0, #12  -> w0 = 0xfffffff3 = -13 (VK_ERROR_UNKNOWN)
RET = 0xD65F03C0
BRK1 = 0xD4200020


def die(msg):
    sys.exit("REFUSED: " + msg)


class PE:
    def __init__(self, data):
        self.d = data
        e = struct.unpack_from("<I", data, 0x3C)[0]
        if data[e:e + 4] != b"PE\0\0":
            die("not a PE file")
        self.machine, = struct.unpack_from("<H", data, e + 4)
        nsec, = struct.unpack_from("<H", data, e + 6)
        optsz, = struct.unpack_from("<H", data, e + 20)
        opt = e + 24
        magic, = struct.unpack_from("<H", data, opt)
        self.imgbase = (struct.unpack_from("<Q", data, opt + 24)[0] if magic == 0x20B
                        else struct.unpack_from("<I", data, opt + 28)[0])
        self.secs = []
        sec = opt + optsz
        for i in range(nsec):
            o = sec + i * 40
            name = data[o:o + 8].rstrip(b"\0").decode("latin1")
            vs, va, rs, raw = struct.unpack_from("<IIII", data, o + 8)
            chars, = struct.unpack_from("<I", data, o + 36)
            self.secs.append((name, va, vs, raw, rs, chars))

    def off(self, rva):
        for _n, va, vs, raw, rs, _c in self.secs:
            if va <= rva < va + max(vs, rs):
                return raw + (rva - va)
        return None

    def rva(self, off):
        for _n, va, _vs, raw, rs, _c in self.secs:
            if raw <= off < raw + rs:
                return va + (off - raw)
        return None

    def word(self, rva):
        return struct.unpack_from("<I", self.d, self.off(rva))[0]


def find_site(pe):
    """RVA of the `adrp x0, <assert string>` in an executable section."""
    str_rvas = []
    i = 0
    while True:
        i = pe.d.find(ASSERT_STR, i)
        if i < 0:
            break
        r = pe.rva(i)
        if r is not None:
            str_rvas.append(r)
        i += 1
    if not str_rvas:
        die("assert string not present -- wrong DLL?")

    hits = []
    for name, va, _vs, raw, rs, chars in pe.secs:
        if not chars & 0x20000000:
            continue
        blob = pe.d[raw:raw + rs]
        for o in range(0, len(blob) - 8, 4):
            w = struct.unpack_from("<I", blob, o)[0]
            if (w & 0x9F000000) != 0x90000000:      # ADRP
                continue
            imm = (((w >> 5) & 0x7FFFF) << 2) | ((w >> 29) & 3)
            if imm & (1 << 20):
                imm -= (1 << 21)
            rd = w & 0x1F
            pc = va + o
            page = (pc & ~0xFFF) + (imm << 12)
            w2 = struct.unpack_from("<I", blob, o + 4)[0]
            if (w2 & 0xFFC00000) == 0x91000000 and (w2 & 0x1F) == rd and ((w2 >> 5) & 0x1F) == rd:
                if page + ((w2 >> 10) & 0xFFF) in str_rvas:
                    hits.append((name, pc))
    if not hits:
        die("no code reference to the assert string found")
    # An ARM64X image carries two code streams (native ARM64 + ARM64EC), each
    # with its own copy of this thunk and its own string literals. Patch both.
    # They are structurally identical.
    if len(hits) > 2:
        die(f"expected 1-2 code references to the assert string, found {len(hits)}: {hits}")
    return [pc for _n, pc in hits]


def find_site_count(pe):
    """Like find_site() but tolerates zero hits -- used to verify a patched file."""
    try:
        return len(find_site(pe))
    except SystemExit:
        return 0


def analyse(pe, site):
    assert_start = site - 4

    # Walk back for `cbnz w0, assert_start`.
    cbnz_rva = None
    for back in range(1, 24):
        r = assert_start - back * 4
        w = pe.word(r)
        if (w & 0xFF000000) != 0x35000000:          # CBNZ (32-bit)
            continue
        if (w & 0x1F) != 0:                          # Rt must be w0
            continue
        imm19 = (w >> 5) & 0x7FFFF
        if imm19 & (1 << 18):
            imm19 -= (1 << 19)
        if r + imm19 * 4 == assert_start:
            cbnz_rva = r
            break
    if cbnz_rva is None:
        die("could not find `cbnz w0, <assert path>` guarding the assert")

    fall = cbnz_rva + 4
    w_ldr_res = pe.word(fall)
    # ldr w0, [sp, #imm]  -> 1011 1001 01 imm12 11111 00000
    if (w_ldr_res & 0xFFC003FF) != 0xB94003E0:
        die(f"expected `ldr w0, [sp,#imm]` at rva 0x{fall:x}, got 0x{w_ldr_res:08x}")

    epi = [pe.word(fall + 4), pe.word(fall + 8), pe.word(fall + 12)]
    if epi[2] != RET:
        die(f"expected `ret` at rva 0x{fall + 12:x}, got 0x{epi[2]:08x}")
    if (epi[0] & 0xFFC003FF) != 0xF94003FE:          # ldr x30, [sp,#imm]
        die(f"expected `ldr x30, [sp,#imm]` at rva 0x{fall + 4:x}, got 0x{epi[0]:08x}")
    if (epi[1] & 0xFFC003FF) != 0x910003FF:          # add sp, sp, #imm
        die(f"expected `add sp, sp, #imm` at rva 0x{fall + 8:x}, got 0x{epi[1]:08x}")

    # Confirm the assert path really is the _assert call in loader_thunks.c
    # (line 3154 on the July 2026 build, 3216 on the rebuild).
    line_w = None
    brk_rva = None
    for k in range(0, 12):
        w = pe.word(assert_start + k * 4)
        if (w & 0xFFE0001F) == 0x52800002:           # movz w2, #imm16
            line_w = (w >> 5) & 0xFFFF
        if w == BRK1:
            brk_rva = assert_start + k * 4
            break
    if line_w is None or brk_rva is None:
        die("assert path does not look like _assert(expr, file, line); brk")

    already = pe.word(assert_start) == MOVN_W0_12
    return dict(site=site, assert_start=assert_start, cbnz=cbnz_rva, fall=fall,
                epi=epi, line=line_w, brk=brk_rva, already=already)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = sys.argv[1]
    data = bytearray(open(path, "rb").read())
    pe = PE(bytes(data))
    if pe.machine != 0xAA64:
        die(f"machine 0x{pe.machine:x} is not ARM64")

    sites = find_site(pe)
    infos = [analyse(pe, s) for s in sites]
    print(f"winevulkan.dll  ImageBase 0x{pe.imgbase:x}  size {len(data)}")
    print(f"found {len(infos)} copy/copies of the thunk "
          f"(an ARM64X image carries two code streams)")
    for a in infos:
        print(f"  --- copy with assert path at rva 0x{a['assert_start']:x} ---")
        print(f"      assert string ref   rva 0x{a['site']:x}")
        print(f"      cbnz w0, assert     rva 0x{a['cbnz']:x}")
        print(f"      normal return path  rva 0x{a['fall']:x}")
        print(f"      brk                 rva 0x{a['brk']:x}")
        print(f"      _assert line number {a['line']}  (3154 on the July 2026 build, 3216 on the rebuild)")
        print(f"      already patched     {a['already']}")
        if a["line"] not in (3154, 3216):
            print("      NOTE: line differs from both builds I checked. The anchors still matched.")

    if "--report" in sys.argv or "--out" not in sys.argv:
        return
    if any(a["already"] for a in infos):
        die("already patched -- refusing to patch twice")

    out = sys.argv[sys.argv.index("--out") + 1]
    changed = []
    for a in infos:
        off = pe.off(a["assert_start"])
        new = struct.pack("<IIII", MOVN_W0_12, a["epi"][0], a["epi"][1], a["epi"][2])
        old = bytes(data[off:off + 16])
        data[off:off + 16] = new
        changed.append((off, old, new))
    open(out, "wb").write(bytes(data))

    # Re-read and verify by ADDRESS, not by string reference: the `adrp x0,
    # <assert string>` that was overwritten WAS the string reference, so re-running
    # find_site() on the patched file correctly finds nothing.
    pe2 = PE(open(out, "rb").read())
    if find_site_count(pe2) != 0:
        die("verification failed: an assert string reference survived")
    for a in infos:
        want = struct.pack("<IIII", MOVN_W0_12, a["epi"][0], a["epi"][1], a["epi"][2])
        got = pe2.d[pe2.off(a["assert_start"]):pe2.off(a["assert_start"]) + 16]
        if got != want:
            die(f"verification failed at rva 0x{a['assert_start']:x}: {got.hex()}")
        # the success path and the guarding branch must be untouched
        for r in (a["cbnz"], a["fall"], a["fall"] + 4, a["fall"] + 8, a["fall"] + 12):
            if pe2.word(r) != pe.word(r):
                die(f"verification failed: success path changed at rva 0x{r:x}")
        # the old _assert call and its brk must no longer be reachable straight-line
        if pe2.word(a["assert_start"] + 12) != RET:
            die("verification failed: replacement does not end in ret")
    for off, old, new in changed:
        print(f"\nPATCHED {off:#x}: {old.hex()} -> {new.hex()}")
    print("  assert path now: movn w0,#12 (VK_ERROR_UNKNOWN); ldr x30; add sp; ret")
    print(f"  wrote {out}  ({16 * len(changed)} bytes changed)")


if __name__ == "__main__":
    main()
