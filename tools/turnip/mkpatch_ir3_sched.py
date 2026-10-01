#!/usr/bin/env python3
"""Apply the ir3 scheduler kill/demote deadlock fix to a Mesa source tree.

    python mkpatch_ir3_sched.py <mesa-src-root>

Anchored on source text rather than line numbers so it survives a Mesa bump.
Idempotent: re-running on an already-patched tree is a no-op.

THE BUG
-------
`check_instr()` refuses to schedule a kill/demote until EVERY bary.f in
`ir->baryfs[]` has been scheduled.  The hw wants the end-input (ei) flag hit
before a thread dies:

    if (is_kill_or_demote(instr)) {
       for (unsigned i = 0; i < ir->baryfs_count; i++) { ... }
    }

But `ir->baryfs` is SHADER-global while `sched_block()` schedules ONE block.
A bary.f that lives in a LATER block can never be scheduled before this
block's demote, so the condition is unsatisfiable.  `choose_instr()` then
returns NULL forever, `sched_block()` sets `ctx->error`, and the shader dies
with "compile failed!".  In a release build `assert(0)` and the `di()` dump
both compile out, so the reason is never logged.  The only symptom is
`E MESA : compile failed! ((null):(null))`.

Observed on an AYN Thor (a7xx / Adreno 740), Mesa 26.1.0, with WoW 1.60.1
arm64's ~90-block uber fragment shader: exactly ONE instruction left
unscheduled, opc=47 (OPC_DEMOTE), parent_count=0, no addr0/addr1 conflict.

THE FIX
-------
Restrict the bary.f check to the kill's OWN block.  A bary.f in an earlier
block is already scheduled (no-op); one in a later block is the unsatisfiable
case.  The real hw constraint is preserved.  Also turns the silent
`ctx->error = true` path into a logged error, so a future deadlock is not
invisible again.

NOT the earlier "relax the heuristics and retry" approach.  That was built on
the wrong diagnosis (that the guards rejecting candidates were heuristic ones)
and it does NOT fix this: the bary.f guard is not bypassed by it.  Verified:
with relax alone the shader still failed 8x per run.
"""
import sys
import pathlib

BARY_OLD = """      for (unsigned i = 0; i < ir->baryfs_count; i++) {
         struct ir3_instruction *baryf = ir->baryfs[i];
         if (baryf->flags & IR3_INSTR_UNUSED)
            continue;
         if (!is_scheduled(baryf)) {"""

BARY_NEW = """      for (unsigned i = 0; i < ir->baryfs_count; i++) {
         struct ir3_instruction *baryf = ir->baryfs[i];
         if (baryf->flags & IR3_INSTR_UNUSED)
            continue;
         /* FF PATCH: ir->baryfs is SHADER-global, but sched_block() schedules a
          * single block.  A bary.f that lives in a LATER block can never be
          * scheduled before this block's kill/demote, so this condition is
          * unsatisfiable: choose_instr() returns NULL forever, sched_block()
          * sets ctx->error, and the whole shader fails with "compile failed!".
          * A bary.f in an EARLIER block is already scheduled, so restricting
          * the check to the kill's own block is a no-op in the healthy case
          * while preserving the real hw constraint (end-input must be hit
          * before the thread dies).  Hit by WoW 1.60.1 arm64's 90-block
          * fragment shader on a7xx; verified on an AYN Thor 2026-09-20.
          */
         if (baryf->block != instr->block)
            continue;
         if (!is_scheduled(baryf)) {"""

LOG_OLD = """            assert(0);
            ctx->error = true;"""

LOG_NEW = """            /* FF PATCH: in release builds assert(0) and the di() dump above
             * both compile out, so this path set ctx->error with NOTHING
             * logged -- "compile failed! ((null):(null))" and no reason.
             */
            mesa_loge("ir3_sched: no schedulable instruction (deadlock); "
                      "addr0_conflict=%d addr1_conflict=%d",
                      notes.addr0_conflict, notes.addr1_conflict);
            assert(0);
            ctx->error = true;"""


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    f = pathlib.Path(sys.argv[1]) / "src/freedreno/ir3/ir3_sched.c"
    s = f.read_text()
    if "FF PATCH: ir->baryfs is SHADER-global" in s:
        print("already patched")
        return
    for old, new, what in ((BARY_OLD, BARY_NEW, "bary.f block scope"),
                           (LOG_OLD, LOG_NEW, "deadlock logging")):
        if old not in s:
            sys.exit(f"anchor for '{what}' not found. Mesa moved, re-anchor by hand")
        s = s.replace(old, new, 1)
        print(f"applied: {what}")
    f.write_text(s)


if __name__ == "__main__":
    main()
