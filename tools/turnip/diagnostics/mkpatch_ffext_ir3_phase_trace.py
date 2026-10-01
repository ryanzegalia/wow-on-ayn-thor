#!/usr/bin/env python3
"""Third FFEXT trace layer: bracket the ir3 compiler CRASH by phase, and dump the NIR
of every fragment shader before it is compiled (-13 hunt, 2026-09-22).

Layer 2 proved: per WoW session ~9 fragment-shader tu_shader_create() calls are
ENTERED and never EXIT (no OK, no guard, no fail log, and the enclosing
tu_CreateGraphicsPipelines never returns either).  Turnip does not return -13.
The driver FAULTS inside the fragment compile and my winevulkan assert patch
turns the fault into VK_ERROR_UNKNOWN.  "compile failed!" never prints, so the
ir3 compiler crashes rather than erroring.

This adds:
  - `FFEXT ir3 id=<n> stage=<s> phase=<p>` before each major phase of
    ir3_compile_shader_nir(): emit, opt, sched, ra, postsched, legalize, and a
    `done ret=<r>` at the out: label.  The crash sits between the last phase
    printed for that id and the missing next one.
  - In tu_shader_create(), for FRAGMENT shaders only, the NIR is written as text to
    /data/data/app.gamenative/files/ffext-nir/<ir3 id>.nir BEFORE the variant is
    compiled.  The dir must exist and be writable by the app: owned by GameNative's
    Android user (install-specific, `ls -ld /data/user/0/app.gamenative` shows it),
    mode 771, app_data_file context.  Afterwards, the ids that
    entered but never printed OK name the crashing shaders; pull those files.

usage: mkpatch_ffext_ir3_phase_trace.py <mesa_src_root>   (idempotent)
Requires layers 1+2 (mkpatch_ffext_variant_trace.py, mkpatch_ffext_pipeline_trace.py).
"""
import re
import sys
import pathlib

root = pathlib.Path(sys.argv[1])
ir3c = root / "src/freedreno/ir3/ir3_compiler_nir.c"
tu_shader = root / "src/freedreno/vulkan/tu_shader.cc"
MARK = "FFEXT ir3 phase trace"
DUMP_DIR = "/data/data/app.gamenative/files/ffext-nir"


def phase(p):
    return (f'   mesa_logi("FFEXT ir3 id=%u stage=%d phase={p}", so->shader->id, '
            f'(int)so->type); /* {MARK} */\n')


s = ir3c.read_text()
if MARK in s:
    print("  ir3_compiler_nir.c: already instrumented, skipping")
else:
    start = s.index("\nir3_compile_shader_nir(")
    body_end = s.index("\n}\n", start)
    body = s[start:body_end]

    def before(anchor, p):
        global body
        if body.count(anchor) != 1:
            sys.exit(f"anchor not unique in ir3_compile_shader_nir (count={body.count(anchor)}): {anchor!r}")
        body = body.replace(anchor, phase(p) + anchor)

    before("   emit_instructions(ctx);\n", "emit")
    before("   IR3_PASS(ir, ir3_remove_unreachable);\n", "opt")
    before("   ret = ir3_sched(ir);\n", "sched")
    before("   ret = ir3_ra(so);\n", "ra")
    before("   IR3_PASS(ir, ir3_remove_noop_subreg_moves);\n", "postsched")
    before("   IR3_PASS(ir, ir3_legalize, so, &max_bary);\n", "legalize")
    # the out: label -- log the final ret
    m = re.search(r"\nout:\n", body)
    if not m:
        sys.exit("no out: label found in ir3_compile_shader_nir")
    body = body[:m.end()] + (
        f'   mesa_logi("FFEXT ir3 id=%u stage=%d phase=done ret=%d", so->shader->id, '
        f'(int)so->type, ret); /* {MARK} */\n') + body[m.end():]
    s = s[:start] + body + s[body_end:]
    if '#include "util/log.h"' not in s:
        s = s.replace('#include "ir3_compiler.h"', '#include "ir3_compiler.h"\n#include "util/log.h" /* FFEXT */', 1)
    ir3c.write_text(s)
    print("  ir3_compiler_nir.c: 7 phase markers added")

# ---- NIR dump of fragment shaders before compile (tu_shader_create entry marker)
t = tu_shader.read_text()
if "FFEXT nir dump" in t:
    print("  tu_shader.cc: nir dump already present, skipping")
else:
    anchor = ('   mesa_logi("FFEXT tu_shader_create stage=%d ir3 id=%u",\n'
              '             (int)nir->info.stage, ir3_shader->id);\n')
    if t.count(anchor) != 1:
        sys.exit("layer-1 entry marker not found in tu_shader.cc; apply mkpatch_ffext_variant_trace.py first")
    dump = f'''   if (nir->info.stage == MESA_SHADER_FRAGMENT) {{ /* FFEXT nir dump */
      char ffext_path[256];
      snprintf(ffext_path, sizeof(ffext_path), "{DUMP_DIR}/%u.nir", ir3_shader->id);
      FILE *ffext_f = fopen(ffext_path, "w");
      if (ffext_f) {{
         char *ffext_txt = nir_shader_as_str(nir, NULL);
         if (ffext_txt) {{
            fputs(ffext_txt, ffext_f);
            ralloc_free(ffext_txt);
         }}
         fclose(ffext_f);
      }} else {{
         mesa_loge("FFEXT nir dump: cannot open %s", ffext_path);
      }}
   }}
'''
    t = t.replace(anchor, anchor + dump)
    if "#include <stdio.h>" not in t:
        t = t.replace('#include "util/log.h" /* FFEXT */', '#include "util/log.h" /* FFEXT */\n#include <stdio.h> /* FFEXT */', 1)
    tu_shader.write_text(t)
    print("  tu_shader.cc: fragment NIR dump added")
print("done")
