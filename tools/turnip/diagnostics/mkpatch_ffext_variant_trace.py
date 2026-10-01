#!/usr/bin/env python3
"""Instrument Turnip/ir3 so a NULL shader variant SAYS WHY (-13 hunt).

Background (2026-09-22): DXVK logs ~20-30 `Failed to compile pipeline: -13`
(VK_ERROR_UNKNOWN) per WoW session, on both stock and patched Turnip.  -13 is
the code MY patches return (the tu_shader_create NULL-variant guard and the
winevulkan assert patch), so a bare -13 cannot tell which fired.  An earlier
capture had ZERO `compile failed!` / `assemble failed!` lines, which are the
only ir3 compile-failure paths that log, so the NULL (if it is the guard) comes
from a path that says nothing.

This adds `FFEXT` mesa_loge lines (logcat tag MESA) at:
  - every `goto fail` in ir3 create_variant()   -> which path, stage, shader id
  - the tu_shader_create NULL-variant guard      -> stage, shader id
  - the safe_constlen re-create right after it   -> was unchecked upstream
  - tu_shader_create entry                       -> lets a -13 with NO matching
                                                    FFEXT line prove the failure
                                                    happened somewhere else
                                                    (crash -> winevulkan -13)

usage: mkpatch_ffext_variant_trace.py <mesa_src_root>
Idempotent: refuses to re-apply if the FFEXT marker is already present.
Applied on top of ff-turnip.patch (needs the NULL-variant guard text).
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1])
ir3 = root / "src/freedreno/ir3/ir3_shader.c"
tu = root / "src/freedreno/vulkan/tu_shader.cc"

MARK = "FFEXT variant trace"


def edit(path, pairs):
    s = path.read_text()
    if MARK in s:
        print(f"  {path.name}: already instrumented, skipping")
        return
    for old, new in pairs:
        if s.count(old) != 1:
            sys.exit(f"anchor not unique in {path}: {old!r} (count={s.count(old)})")
        s = s.replace(old, new)
    path.write_text(s)
    print(f"  {path.name}: instrumented ({len(pairs)} edits)")


# ---------------------------------------------------------------- ir3_shader.c
edit(ir3, [
    # tag the fail label so each goto can name itself
    (
        """   struct ir3_shader_variant *v = alloc_variant(shader, key, NULL, mem_ctx);

   if (!v)
      goto fail;
""",
        """   struct ir3_shader_variant *v = alloc_variant(shader, key, NULL, mem_ctx);
   const char *ffext_why = "?"; /* FFEXT variant trace */

   if (!v) {
      ffext_why = "alloc_variant(main) returned NULL";
      goto fail;
   }
""",
    ),
    (
        """      v->binning = alloc_variant(shader, key, v, mem_ctx);
      if (!v->binning)
         goto fail;
""",
        """      v->binning = alloc_variant(shader, key, v, mem_ctx);
      if (!v->binning) {
         ffext_why = "alloc_variant(binning) returned NULL";
         goto fail;
      }
""",
    ),
    (
        """   if (!compile_variant(shader, v))
      goto fail;

   if (needs_binning_variant(v) && !compile_variant(shader, v->binning))
      goto fail;
""",
        """   if (!compile_variant(shader, v)) {
      ffext_why = "compile_variant(main) failed";
      goto fail;
   }

   if (needs_binning_variant(v) && !compile_variant(shader, v->binning)) {
      ffext_why = "compile_variant(binning) failed";
      goto fail;
   }
""",
    ),
    (
        """fail:
   ralloc_free(v);
   return NULL;
}

struct ir3_shader_variant *
ir3_shader_create_variant(struct ir3_shader *shader,
""",
        """fail:
   mesa_loge("FFEXT create_variant FAIL: %s (shader id=%u type=%d nir=%s)",
             ffext_why, shader->id, shader->type,
             shader->nir && shader->nir->info.name ? shader->nir->info.name
                                                    : "(null)");
   ralloc_free(v);
   return NULL;
}

struct ir3_shader_variant *
ir3_shader_create_variant(struct ir3_shader *shader,
""",
    ),
])

# ---------------------------------------------------------------- tu_shader.cc
edit(tu, [
    (
        """   shader->variant =
      ir3_shader_create_variant(ir3_shader, ir3_key, executable_info);

   /* FF PATCH: ir3_shader_create_variant() returns NULL when the ir3 compile
""",
        """   /* FFEXT variant trace: entry marker, so a DXVK -13 with no FFEXT line
    * after it means the failure was NOT a NULL variant (crash path). */
   mesa_logi("FFEXT tu_shader_create stage=%d ir3 id=%u",
             (int)nir->info.stage, ir3_shader->id);

   shader->variant =
      ir3_shader_create_variant(ir3_shader, ir3_key, executable_info);

   /* FF PATCH: ir3_shader_create_variant() returns NULL when the ir3 compile
""",
    ),
    (
        """   if (!shader->variant) {
      ir3_shader_destroy(ir3_shader);
      vk_free(&dev->vk.alloc, shader);
      return VK_ERROR_UNKNOWN;
   }
""",
        """   if (!shader->variant) {
      mesa_loge("FFEXT NULL variant -> VK_ERROR_UNKNOWN (stage=%d ir3 id=%u)",
                (int)nir->info.stage, ir3_shader->id);
      ir3_shader_destroy(ir3_shader);
      vk_free(&dev->vk.alloc, shader);
      return VK_ERROR_UNKNOWN;
   }
""",
    ),
])

# the safe_constlen re-create right after the guard is unchecked upstream
s = tu.read_text()
anchor = """      shader->variant =
         ir3_shader_create_variant(ir3_shader, &safe_constlen_key,
                                   executable_info);
"""
if s.count(anchor) == 1 and "FFEXT safe_constlen" not in s:
    s = s.replace(anchor, anchor + """      if (!shader->variant) { /* FFEXT safe_constlen guard */
         mesa_loge("FFEXT NULL variant on safe_constlen retry -> VK_ERROR_UNKNOWN "
                   "(stage=%d ir3 id=%u)", (int)nir->info.stage, ir3_shader->id);
         ir3_shader_destroy(ir3_shader);
         vk_free(&dev->vk.alloc, shader);
         return VK_ERROR_UNKNOWN;
      }
""")
    tu.write_text(s)
    print("  tu_shader.cc: safe_constlen retry guarded")
else:
    print("  tu_shader.cc: safe_constlen anchor not found as expected -- check by hand:")
    import re
    for m in re.finditer(r"safe_constlen_key", s):
        print("    ", s[max(0, m.start()-120):m.end()+160].replace("\n", "\n     "))
        break

if '#include "util/log.h"' not in tu.read_text():
    s = tu.read_text()
    s = s.replace('#include "tu_shader.h"', '#include "tu_shader.h"\n#include "util/log.h" /* FFEXT */', 1)
    tu.write_text(s)
    print("  tu_shader.cc: added util/log.h include")
print("done")
