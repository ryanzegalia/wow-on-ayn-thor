#!/usr/bin/env python3
"""Stop ir3_nir_opt_prefetch_descriptors() faulting when no legal insert block exists.

THE BUG (Mesa 26.1.0 Turnip, a7xx, found 2026-09-22 on an AYN Thor running retail WoW):
  ir3_nir_opt_preamble.c, _rematerialize_def():
      nir_block *insert_block = find_insert_block(instr, ...);
      assert(insert_block);                 // compiled out in release
      b->cursor = nir_after_block(insert_block);
      nir_builder_instr_insert(b, instr);   // SIGSEGV, addr = NULL + 0x38
  find_insert_block() returns NULL when one of the instruction's sources is not
  dominated by a candidate block.  ir3_def_is_rematerializable_for_preamble() had
  already said yes, so the pass assumes an insert point must exist.  For ~9 large
  (37-block) WoW fragment shaders per session it does not.  The fault reached
  winevulkan, whose assert->return patch turned it into VK_ERROR_UNKNOWN, and DXVK
  dropped the pipeline.
  Workaround that proved it: IR3_SHADER_DEBUG=nodescprefetch -> 0 failures.

THE FIX: degrade gracefully.
  * _rematerialize_def(): if find_insert_block() is NULL, free the un-inserted clone
    and return NULL.  Recursion propagates naturally: callers ignore child return
    values, so a parent's deep clone keeps an unremapped source, fails its own
    dominance check, and returns NULL as well.
  * the prefetch loop: if a descriptor that was requested came back NULL, skip the
    prefetch for that instruction (the shader simply loads the descriptor at use, as
    it did before this optimisation existed).

usage: mkpatch_ir3_prefetch_nullblock.py <mesa_src_root>   (idempotent)
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1])
f = root / "src/freedreno/ir3/ir3_nir_opt_preamble.c"
MARK = "FF PATCH: no legal insert block"

s = f.read_text()

# ---- site 2 (found 2026-09-22: v1 of this patch still faulted 9x per session.  The
# fault symbol was the nearest non-static name, and BOTH static helpers are inlined into
# ir3_nir_opt_prefetch_descriptors): emit_descriptor_prefetch() has the same shape:
# find_insert_block_for_defs() -> NULL -> assert -> nir_after_block(NULL).
MARK2 = "FF PATCH: no legal insert block for the prefetch"
old0 = """   if (descs[1]) {
      insert_block = find_insert_block_for_defs(descs, 2);

      /* Since the preamble control flow was reconstructed from the original
       * one, and the two descriptor defs were used by the same instruction, we
       * must be able to find a legal place to insert the prefetch.
       */
      assert(insert_block);
   }

   b->cursor = nir_after_block(insert_block);
"""
new0 = """   if (descs[1]) {
      insert_block = find_insert_block_for_defs(descs, 2);

      /* Since the preamble control flow was reconstructed from the original
       * one, and the two descriptor defs were used by the same instruction, we
       * must be able to find a legal place to insert the prefetch.
       *
       * FF PATCH: no legal insert block for the prefetch -- same broken
       * invariant as in _rematerialize_def (retail WoW a7xx fragment shaders);
       * skip this prefetch instead of faulting on nir_after_block(NULL).
       */
      if (!insert_block)
         return false;
   }

   b->cursor = nir_after_block(insert_block);
"""
if MARK2 in s:
    print("  ir3_nir_opt_preamble.c: site 2 already patched")
else:
    if s.count(old0) != 1:
        sys.exit(f"anchor 0 (emit_descriptor_prefetch) count={s.count(old0)}")
    s = s.replace(old0, new0)
    f.write_text(s)
    print("  ir3_nir_opt_preamble.c: site 2 (emit_descriptor_prefetch) guarded")

if MARK in s:
    print("  ir3_nir_opt_preamble.c: site 1 already patched, skipping")
    sys.exit(0)

old1 = """   nir_block *insert_block =
      find_insert_block(instr, nir_cursor_current_block(b->cursor));

   /* Since the preamble control flow was reconstructed from the original one,
    * we must be able to find a legal place to insert the instruction.
    */
   assert(insert_block);
   b->cursor = nir_after_block(insert_block);
   nir_builder_instr_insert(b, instr);
"""
new1 = """   nir_block *insert_block =
      find_insert_block(instr, nir_cursor_current_block(b->cursor));

   /* Since the preamble control flow was reconstructed from the original one,
    * we must be able to find a legal place to insert the instruction.
    *
    * FF PATCH: no legal insert block -- in practice that invariant breaks:
    * retail WoW's large (37-block) fragment shaders on a7xx hit
    * find_insert_block() == NULL for ~9 shaders per session, and in a release
    * build the assert below is gone, so nir_after_block(NULL) faulted inside
    * nir_instr_insert (addr NULL+0x38).  Give up on rematerializing this def
    * instead: free the clone that was never inserted and return NULL.  Callers
    * that clone a parent of this def keep an unremapped source, fail their own
    * dominance check and return NULL too, so the failure propagates up to
    * ir3_rematerialize_def_for_preamble(), whose caller skips the prefetch.
    */
   if (!insert_block) {
      nir_instr_free(instr);
      return NULL;
   }
   b->cursor = nir_after_block(insert_block);
   nir_builder_instr_insert(b, instr);
"""
if s.count(old1) != 1:
    sys.exit(f"anchor 1 count={s.count(old1)}")
s = s.replace(old1, new1)

old2 = """         for (unsigned i = 0; i < 2; i++) {
            if (!descs[i])
               continue;

            preamble_descs[i] =
               ir3_rematerialize_def_for_preamble(&b, descs[i], &instr_set,
                                                  preamble_defs);
         }

         progress |= emit_descriptor_prefetch(&b, instr, preamble_descs, &state);
"""
new2 = """         bool ff_remat_failed = false;
         for (unsigned i = 0; i < 2; i++) {
            if (!descs[i])
               continue;

            preamble_descs[i] =
               ir3_rematerialize_def_for_preamble(&b, descs[i], &instr_set,
                                                  preamble_defs);
            if (!preamble_descs[i])
               ff_remat_failed = true;
         }

         /* FF PATCH: no legal insert block for one of the descriptor chains
          * (see _rematerialize_def) -- leave this access un-prefetched rather
          * than emit a prefetch of a NULL def.  Any clones already placed in
          * the preamble for the partial chain are dead and DCE'd later.
          */
         if (ff_remat_failed)
            continue;

         progress |= emit_descriptor_prefetch(&b, instr, preamble_descs, &state);
"""
if s.count(old2) != 1:
    sys.exit(f"anchor 2 count={s.count(old2)}")
s = s.replace(old2, new2)
f.write_text(s)
print("  ir3_nir_opt_preamble.c: NULL insert-block guard + prefetch skip added")
print("done")
