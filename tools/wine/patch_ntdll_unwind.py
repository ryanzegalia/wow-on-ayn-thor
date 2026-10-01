#!/usr/bin/env python3
"""Patch Wine's aarch64 ntdll.dll so call_seh_handlers cannot spin forever.

THE BUG
-------
ntdll's `call_seh_handlers` walks the stack with the loop below. All RVAs here are
for the July 2026 proton-10.0-arm64ec lib/wine/aarch64-windows/ntdll.dll, where the
function sits at 0x53c8c. A rebuilt ntdll.dll has different offsets and this tool
refuses it.

    for (;;) {
        virtual_unwind(UNW_FLAG_EHANDLER, &dispatch, &context);   +0x53d30
        ...
        if (context.Sp == NtCurrentTeb()->Tib.StackBase) break;   +0x53ff0..+0x53ffc
    }

Its exits are `dispatch.EstablisherFrame == 0`, `context.Sp == StackBase`, an
invalid frame or a failed unwind, and none of them fires here. When the frame's PC
lies in Blizzard's anonymous RWX anti-tamper region there is no PE and no .pdata,
RtlLookupFunctionEntry returns NULL, RtlVirtualUnwind2 falls back to the
leaf-function case and leaves Sp untouched. So Sp never reaches StackBase and the
thread spins forever. Measured: 8.1 million
`warn:seh:virtual_unwind backtrace: <ADDR>: unknown module.` lines, nearly all of
them the SAME address. The frame does not advance.

THE FIX
-------
Add the missing no-progress guard: remember context.Sp across iterations and, if
an unwind step did not move it, take ntdll's own "invalid frame" exit (+0x54004),
which sets EXCEPTION_STACK_INVALID and returns STATUS_UNHANDLED_EXCEPTION. That is
exactly what Wine already does for a corrupt stack -- the exception fails cleanly
instead of hanging.

Implemented with two redirects into 56 bytes of NOP alignment padding at 0x53ac8
(outside every .pdata range, unreachable). Scratch slot sp+0x3b0 is the 8 bytes of
padding between the on-stack CONTEXT (sp+0x20, 0x390 bytes) and DISPATCHER_CONTEXT
(sp+0x3b8); no instruction in the function touches it and no pointer to it escapes.

ARM64X: this ntdll.dll is ARM64X and carries a dynamic value relocation table
(LoadConfig DynamicValueRelocTableOffset/Section, .reloc +0x74c on the July 2026
build). Wine applies it only when it maps the image for x64 (update_arm64x_mapping
in dlls/ntdll/unix/virtual.c). I walked it on that build: its 9 fixups rewrite PE
header fields and one .rdata word, and none of them touches the cave or the two
redirect sites. `patch_ntdll_syscall.py --report` shows whether an ntdll.dll has one.

Usage:  patch_ntdll_unwind.py <ntdll.dll> [-o out.dll] [--verify]
"""
import shutil
import struct
import sys

CAVE = 0x53AC8          # 14 NOP slots, 0x53ac8..0x53b00
INIT_SITE = 0x53D00     # str xzr,[sp,#0x3d8]   (dispatch.TargetPc = 0, runs once pre-loop)
TAIL_SITE = 0x53FF0     # ldr x8,[sp,#0x120]    (first insn of the loop-exit test)
LOOP_HEAD = 0x53D0C
BREAK_OK = 0x54068      # mov w0,w19 ; epilogue  -> return STATUS_UNHANDLED_EXCEPTION
BREAK_BAD = 0x54004     # ERR "invalid frame" ; ExceptionFlags |= EH_STACK_INVALID ; -> 0x54068

NOP = 0xD503201F
# original words that must be there before touching anything
EXPECT = {
    INIT_SITE: 0xF901EFFF,   # str  xzr, [sp, #0x3d8]
    TAIL_SITE: 0xF94093E8,   # ldr  x8,  [sp, #0x120]
    TAIL_SITE + 4: 0xF9400649,   # ldr  x9,  [x18, #8]
    TAIL_SITE + 8: 0xEB09011F,   # cmp  x8, x9
    TAIL_SITE + 12: 0x54FFE881,  # b.ne #0x53d0c
    TAIL_SITE + 16: 0x1400001A,  # b    #0x54068
}


def b(pc, target):
    off = (target - pc) >> 2
    assert -(1 << 25) <= off < (1 << 25)
    return 0x14000000 | (off & 0x03FFFFFF)


def bcond(pc, target, cond):
    off = (target - pc) >> 2
    assert -(1 << 18) <= off < (1 << 18)
    return 0x54000000 | ((off & 0x7FFFF) << 5) | cond


EQ, NE = 0, 1


def build_stub():
    """(rva, word, comment) for the code that goes into the cave."""
    c = CAVE
    return [
        # --- once, pre-loop: original TargetPc=0 plus prevSp sentinel ---
        (c + 0x00, 0xF901EFFF, "str  xzr, [sp, #0x3d8]      ; dispatch.TargetPc = 0 (original)"),
        (c + 0x04, 0xF901DBFF, "str  xzr, [sp, #0x3b0]      ; prevSp = 0 (Sp is never 0)"),
        (c + 0x08, b(c + 0x08, INIT_SITE + 4), "b    #0x53d04               ; back"),
        # --- every iteration: the loop-exit test ---
        (c + 0x0C, 0xF94093E8, "ldr  x8,  [sp, #0x120]      ; x8 = context.Sp (original)"),
        (c + 0x10, 0xF9400649, "ldr  x9,  [x18, #8]         ; x9 = Teb->Tib.StackBase (original)"),
        (c + 0x14, 0xEB09011F, "cmp  x8, x9"),
        (c + 0x18, bcond(c + 0x18, BREAK_OK, EQ), "b.eq #0x54068               ; hit StackBase -> original break"),
        (c + 0x1C, 0xF941DBE9, "ldr  x9,  [sp, #0x3b0]      ; x9 = prevSp"),
        (c + 0x20, 0xF901DBE8, "str  x8,  [sp, #0x3b0]      ; prevSp = Sp"),
        (c + 0x24, 0xEB09011F, "cmp  x8, x9"),
        (c + 0x28, bcond(c + 0x28, LOOP_HEAD, NE), "b.ne #0x53d0c               ; Sp advanced -> keep unwinding"),
        (c + 0x2C, b(c + 0x2C, BREAK_BAD), "b    #0x54004               ; NO PROGRESS -> EH_STACK_INVALID, bail"),
    ]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = [a for a in sys.argv[1:] if a.startswith("-")]
    if not args:
        sys.exit(__doc__)
    src = args[0]
    out = args[1] if len(args) > 1 else None
    if "-o" in flags:
        out = sys.argv[sys.argv.index("-o") + 1]
    if out is None:
        out = src + ".unwindfix"

    d = bytearray(open(src, "rb").read())

    # .text has RAW == VA here, but resolve properly anyway.
    e = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, e + 6)[0]
    optsz = struct.unpack_from("<H", d, e + 20)[0]
    sec = e + 24 + optsz
    text = None
    for i in range(nsec):
        o = sec + i * 40
        if d[o:o + 8].rstrip(b"\0") == b".text":
            vs, va, rs, raw = struct.unpack_from("<IIII", d, o + 8)
            text = (va, vs, raw, rs)
    if not text:
        sys.exit("no .text")
    tva, tvs, traw, trs = text

    def off(rva):
        return traw + (rva - tva)

    # --- verify this is the binary it should be ---
    bad = []
    for rva, want in EXPECT.items():
        got = struct.unpack_from("<I", d, off(rva))[0]
        if got != want:
            bad.append(f"  +0x{rva:x}: expected {want:08x}, found {got:08x}")
    for i in range(12):
        got = struct.unpack_from("<I", d, off(CAVE + i * 4))[0]
        if got != NOP:
            bad.append(f"  cave +0x{CAVE + i * 4:x}: expected NOP, found {got:08x}")
    if bad:
        sys.exit("REFUSING -- this is not the expected ntdll build:\n" + "\n".join(bad))
    print(f"anchors OK ({len(EXPECT)} insns + 12 NOP cave slots)")

    stub = build_stub()
    for rva, word, comment in stub:
        struct.pack_into("<I", d, off(rva), word)
        print(f"  +0x{rva:06x}  {word:08x}  {comment}")
    for rva, word, what in ((INIT_SITE, b(INIT_SITE, CAVE), "-> cave init stub"),
                            (TAIL_SITE, b(TAIL_SITE, CAVE + 0x0C), "-> cave loop-tail stub")):
        struct.pack_into("<I", d, off(rva), word)
        print(f"  +0x{rva:06x}  {word:08x}  b  {what}")

    open(out, "wb").write(d)
    print(f"\nwrote {out} ({len(d)} bytes)")

    if "--verify" in flags:
        import capstone
        md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
        print("\n--- cave ---")
        for ins in md.disasm(bytes(d[off(CAVE):off(CAVE) + 0x38]), CAVE):
            print(f"  +0x{ins.address:06x}  {ins.mnemonic:<8} {ins.op_str}")
        for site in (INIT_SITE, TAIL_SITE):
            print(f"--- site +0x{site:x} ---")
            for ins in md.disasm(bytes(d[off(site):off(site) + 8]), site):
                print(f"  +0x{ins.address:06x}  {ins.mnemonic:<8} {ins.op_str}")


if __name__ == "__main__":
    main()
