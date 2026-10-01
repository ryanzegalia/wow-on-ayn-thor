#!/usr/bin/env python3
"""FFEXT experiment/fix: compile ir3 shader variants on a helper thread with a 16 MB stack.

Why (2026-09-22, -13 hunt, layers 1-4):
  * ~9 fragment shaders per WoW session (all ~37-block, 1061-1175 NIR lines) enter
    tu_shader_create(), reach `phase=start` (the line before ir3_context_init) and
    never come back: no `ci=lower_variant`, no error, no "compile failed!".  The
    enclosing vkCreateGraphicsPipelines never returns either.  My winevulkan assert
    patch turns that fault into VK_ERROR_UNKNOWN (-13) and DXVK drops the pipeline.
  * The stack probe at tu_shader_create entry read headroom=1037127 bytes on EVERY
    shader.  DXVK creates its pipeline-compiler threads with an explicit 1 MB stack
    (CreateThread(nullptr, 0x100000, ...)).  Mesa's NIR/ir3 compiler is normally run on
    8 MB Linux threads.  Large shaders dying silently inside NIR lowering on a 1 MB
    stack is the signature of a stack overflow (guard page -> SIGSEGV).

What this does: in tu_shader_create(), the main ir3_shader_create_variant() call runs
on a pthread created with a 16 MB stack; the caller joins it.  Disable at run time with
env FFEXT_BIGSTACK=0 (container envVars) to A/B against the same binary.
  -13s disappear with it on  -> stack overflow confirmed, and this IS the fix (keep
                                it, or shrink to 4-8 MB)
  WoW dies hard instead       -> a real fault on a thread Wine does not own; go back to
                                markers inside ir3_nir_lower_variant

Caveat: the helper thread has no Wine TEB, so a genuine fault there kills the process
instead of becoming -13.  That is intended for the experiment.

The stack theory turned out wrong.  With the 16 MB thread the compile got past
ir3_nir_lower_variant and then faulted anyway.  mkpatch_ffext_faulttrace.py showed a
NULL insert block in ir3_nir_opt_preamble.c, not a stack overflow (the real fix is
mkpatch_ir3_prefetch_nullblock.py).  I kept this layer because the fault handler
runs on its helper thread.

usage: mkpatch_ffext_bigstack.py <mesa_src_root>   (idempotent)
Requires layer 1 (mkpatch_ffext_variant_trace.py) for the surrounding markers.
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1])
tu_shader = root / "src/freedreno/vulkan/tu_shader.cc"
MARK = "FFEXT bigstack"

t = tu_shader.read_text()
if MARK in t:
    print("  tu_shader.cc: bigstack already present, skipping")
    sys.exit(0)

anchor = """   shader->variant =
      ir3_shader_create_variant(ir3_shader, ir3_key, executable_info);
"""
if t.count(anchor) != 1:
    sys.exit(f"anchor count={t.count(anchor)} for the main ir3_shader_create_variant call")

helper = """
/* FFEXT bigstack: run the ir3 compile on a thread with a large stack.  DXVK's
 * pipeline-compiler threads carry a 1 MB stack (CreateThread(nullptr, 0x100000)),
 * in case the ~9 large fragment shaders per WoW session that fault silently inside
 * ir3_context_init() were overflowing that budget (they weren't, see
 * mkpatch_ir3_prefetch_nullblock.py).  See mkpatch_ffext_bigstack.py. */
#include <pthread.h>
#include <stdlib.h>
struct ffext_variant_job {
   struct ir3_shader *shader;
   const struct ir3_shader_key *key;
   bool executable_info;
   struct ir3_shader_variant *out;
};
static void *
ffext_variant_thread(void *p)
{
   struct ffext_variant_job *j = (struct ffext_variant_job *)p;
   j->out = ir3_shader_create_variant(j->shader, j->key, j->executable_info);
   return NULL;
}
static struct ir3_shader_variant *
ffext_create_variant_bigstack(struct ir3_shader *shader,
                              const struct ir3_shader_key *key,
                              bool executable_info)
{
   const char *e = getenv("FFEXT_BIGSTACK");
   if (e && e[0] == '0')
      return ir3_shader_create_variant(shader, key, executable_info);

   struct ffext_variant_job j = { shader, key, executable_info, NULL };
   pthread_attr_t attr;
   pthread_t th;
   pthread_attr_init(&attr);
   pthread_attr_setstacksize(&attr, (size_t)16 << 20);
   if (pthread_create(&th, &attr, ffext_variant_thread, &j) != 0) {
      pthread_attr_destroy(&attr);
      mesa_loge("FFEXT bigstack: pthread_create failed, compiling inline");
      return ir3_shader_create_variant(shader, key, executable_info);
   }
   pthread_join(th, NULL);
   pthread_attr_destroy(&attr);
   return j.out;
}

"""

new_call = """   shader->variant =
      ffext_create_variant_bigstack(ir3_shader, ir3_key, executable_info);
"""
t = t.replace(anchor, new_call)

# place the helper right before tu_shader_create's definition
fn = "\ntu_shader_create(struct tu_device *dev,"
idx = t.find(fn)
if idx < 0:
    sys.exit("tu_shader_create definition not found")
# back up to the start of the return-type line(s) preceding the function name
line_start = t.rfind("\n", 0, idx - 1)
# find the start of the previous non-blank line (return type), keep it attached
prev = t.rfind("\n", 0, line_start)
t = t[:prev + 1] + helper + t[prev + 1:]
tu_shader.write_text(t)
print("  tu_shader.cc: bigstack helper installed around ir3_shader_create_variant")
print("done")
