#!/usr/bin/env python3
"""Fourth FFEXT trace layer: bisect the PRE-EMIT crash window + measure thread stack headroom.

Layer 3 result (2026-09-22): the 9 crashing fragment shaders (all ~37-block,
1061-1175 NIR lines; healthy fragments are tiny) never printed even the first
`phase=emit` marker.  So the fault is between the tu_shader_create entry marker and
emit_instructions(): alloc_variant -> ir3_disk_cache_retrieve -> ir3_nir_post_finalize
(first variant only) -> compile_variant -> ir3_compile_shader_nir -> ir3_context_init
(NIR lowering + opt loop + vectorize + opt_if + lcssa + divergence).

Two hypotheses this layer separates:
  A. a real bug in one NIR pass for these shaders   -> markers stop after a named pass
  B. stack overflow on DXVK's compile worker thread -> `FFEXT stack` headroom is small
     at entry, and the markers stop somewhere deep (recursion) with no pass to blame

Markers (all `mesa_logi`, tag TU/MESA, keyed by ir3 shader id + stage):
  create_variant:      cv=alloc | cv=cachemiss | cv=postfinalize | cv=precompile
  compile_shader_nir:  phase=start | phase=init      (init = ir3_context_init returned)
  ir3_context_init:    ci=lower_variant | ci=opt | ci=prefetch | ci=vectorize | ci=optif
                       | ci=lcssa | ci=divergence | ci=done
  tu_shader_create:    `FFEXT stack size=<bytes> headroom=<bytes>` (pthread_getattr_np)

usage: mkpatch_ffext_preemit_trace.py <mesa_src_root>   (idempotent, best-effort anchors:
a missing anchor is reported, not fatal, so the build still gives partial coverage)
Requires layers 1-3.
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1])
ir3s = root / "src/freedreno/ir3/ir3_shader.c"
ir3c = root / "src/freedreno/ir3/ir3_compiler_nir.c"
ir3x = root / "src/freedreno/ir3/ir3_context.c"
tu_shader = root / "src/freedreno/vulkan/tu_shader.cc"
MARK = "FFEXT preemit trace"
missing = []


def insert_before(path, text, anchor, line):
    """insert `line` before the unique `anchor` in `text`; returns new text"""
    n = text.count(anchor)
    if n != 1:
        missing.append(f"{path.name}: anchor count={n}: {anchor.strip()[:70]}")
        return text
    return text.replace(anchor, line + anchor)


def insert_after(path, text, anchor, line):
    n = text.count(anchor)
    if n != 1:
        missing.append(f"{path.name}: anchor count={n}: {anchor.strip()[:70]}")
        return text
    return text.replace(anchor, anchor + line)


# ------------------------------------------------------------ ir3_shader.c create_variant
s = ir3s.read_text()
if MARK in s:
    print("  ir3_shader.c: already instrumented")
else:
    cv = lambda p: (f'   mesa_logi("FFEXT ir3 id=%u stage=%d cv={p}", shader->id, (int)shader->type); '
                    f'/* {MARK} */\n')
    s = insert_before(ir3s, s, "   v->disasm_info.write_disasm = write_disasm;\n", cv("alloc"))
    s = insert_before(ir3s, s, "   if (!shader->nir_finalized) {\n      ir3_nir_post_finalize(shader);\n", cv("cachemiss"))
    s = insert_after(ir3s, s, "      shader->nir_finalized = true;\n   }\n", cv("postfinalize"))
    s = insert_before(ir3s, s, "   if (!compile_variant(shader, v)) {\n", cv("precompile"))
    ir3s.write_text(s)
    print("  ir3_shader.c: create_variant markers added")

# ------------------------------------------------------------ ir3_compiler_nir.c start/init
s = ir3c.read_text()
if MARK in s:
    print("  ir3_compiler_nir.c: already instrumented")
else:
    ph = lambda p: (f'   mesa_logi("FFEXT ir3 id=%u stage=%d phase={p}", so->shader->id, (int)so->type); '
                    f'/* {MARK} */\n')
    s = insert_before(ir3c, s, "   ctx = ir3_context_init(compiler, shader, so);\n", ph("start"))
    s = insert_after(ir3c, s,
                     "   ctx = ir3_context_init(compiler, shader, so);\n"
                     "   if (!ctx) {\n      DBG(\"INIT failed!\");\n      ret = -1;\n      goto out;\n   }\n",
                     ph("init"))
    ir3c.write_text(s)
    print("  ir3_compiler_nir.c: start/init markers added")

# ------------------------------------------------------------ ir3_context.c ir3_context_init
s = ir3x.read_text()
if MARK in s:
    print("  ir3_context.c: already instrumented")
else:
    ci = lambda p: (f'   mesa_logi("FFEXT ir3 id=%u stage=%d ci={p}", so->shader->id, (int)so->type); '
                    f'/* {MARK} */\n')
    s = insert_after(ir3x, s, "   ir3_nir_lower_variant(so, &shader->options.nir_options, ctx->s);\n", ci("lower_variant"))
    s = insert_before(ir3x, s, "   if (compiler->has_branch_and_or)\n", ci("opt"))
    s = insert_before(ir3x, s, "   if ((so->type == MESA_SHADER_FRAGMENT) && compiler->info->props.has_fs_tex_prefetch) {\n", ci("prefetch"))
    s = insert_before(ir3x, s, "   NIR_PASS(vectorized, ctx->s, nir_opt_vectorize, ir3_nir_vectorize_filter,\n", ci("vectorize"))
    s = insert_before(ir3x, s, "   NIR_PASS(progress, ctx->s, nir_convert_to_lcssa, true, true);\n", ci("optif"))
    s = insert_before(ir3x, s, "   nir_divergence_analysis(ctx->s);\n", ci("lcssa"))
    s = insert_after(ir3x, s, "   nir_divergence_analysis(ctx->s);\n", ci("divergence"))
    s = insert_before(ir3x, s, "   ir3_ibo_mapping_init(&so->image_mapping, ctx->s->info.num_textures);\n", ci("done"))
    if '#include "util/log.h"' not in s:
        s = s.replace('#include "ir3_context.h"', '#include "ir3_context.h"\n#include "util/log.h" /* FFEXT */', 1)
    ir3x.write_text(s)
    print("  ir3_context.c: context_init markers added")

# ------------------------------------------------------------ tu_shader.cc stack headroom
t = tu_shader.read_text()
if "FFEXT stack" in t:
    print("  tu_shader.cc: stack probe already present")
else:
    anchor = ('   mesa_logi("FFEXT tu_shader_create stage=%d ir3 id=%u",\n'
              '             (int)nir->info.stage, ir3_shader->id);\n')
    probe = '''   { /* FFEXT stack probe: how much of this thread's stack is left at entry */
      pthread_attr_t ffext_attr;
      if (pthread_getattr_np(pthread_self(), &ffext_attr) == 0) {
         void *ffext_base = NULL; size_t ffext_size = 0;
         pthread_attr_getstack(&ffext_attr, &ffext_base, &ffext_size);
         char ffext_here;
         size_t ffext_headroom = (size_t)((uintptr_t)&ffext_here - (uintptr_t)ffext_base);
         mesa_logi("FFEXT stack size=%zu headroom=%zu (ir3 id=%u stage=%d)",
                   ffext_size, ffext_headroom, ir3_shader->id, (int)nir->info.stage);
         pthread_attr_destroy(&ffext_attr);
      }
   }
'''
    if t.count(anchor) != 1:
        missing.append("tu_shader.cc: layer-1 entry marker anchor")
    else:
        t = t.replace(anchor, anchor + probe)
        if "#include <pthread.h>" not in t:
            t = t.replace('#include <stdio.h> /* FFEXT */', '#include <stdio.h> /* FFEXT */\n#include <pthread.h> /* FFEXT */', 1)
        tu_shader.write_text(t)
        print("  tu_shader.cc: stack probe added")

if missing:
    print("MISSING ANCHORS (partial coverage):")
    for m in missing:
        print("   ", m)
print("done")
