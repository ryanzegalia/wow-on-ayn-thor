#!/usr/bin/env python3
"""Stop Turnip dereferencing a NULL ir3 variant when a shader fails to compile.

THE BUG
-------
`tu_shader_create()` in src/freedreno/vulkan/tu_shader.cc does:

    shader->variant = ir3_shader_create_variant(ir3_shader, ir3_key, ...);
    if (ir3_exceeds_safe_constlen(shader->variant)) {   <-- first NULL deref
    ...
    ir3_shader_destroy(ir3_shader);
    shader->view_mask = key->multiview_mask;
    switch (shader->variant->type) {                    <-- and again here

`ir3_shader_create_variant()` returns NULL whenever the ir3 compile fails,
e.g. the `sched_block()` deadlock I hit on WoW's uber fragment shader.
Nothing checks it, and `ir3_exceeds_safe_constlen()` reads `v->constlen`, so
the very next use reads off a null pointer.

On the Thor that faulted at NULL+0x68 inside vkCreateGraphicsPipelines.  Wine
caught the SIGSEGV in its syscall dispatcher, returned it to the PE side as
NTSTATUS c0000005, and winevulkan's `assert(!status)` then aborted the whole
process (GameNative "Exit called" -> status 137).

So a shader the compiler merely cannot compile took the game down.  DXVK copes
with a pipeline that fails to build (it logs and carries on).  It cannot cope
with a SIGSEGV inside the driver.

THE FIX
-------
Check the variant and fail the shader cleanly with VK_ERROR_UNKNOWN.

Cleanup: the patch frees `shader` with vk_free(), which is exactly the inverse of
tu_shader_init() (a vk_multialloc_zalloc plus vk_pipeline_cache_object_init)
and exactly what tu_shader_destroy() itself ends with.  It deliberately does NOT
call the full tu_shader_destroy(): at this point tu_upload_shader() has not
run, so shader->cs and shader->bo were never set up, and running their teardown
against zeroed structs would be a new risk on an error path.  Nothing between
tu_shader_init() and here allocates cs/bo, so this leaks nothing.

This is a defence-in-depth fix: with the ir3_sched patch applied the shader
should compile, but ANY future shader ir3 cannot handle would otherwise crash
the game rather than lose one pipeline.

usage: mkpatch_tu_nullvariant.py <mesa_src_root>
"""
import io
import os
import sys

if len(sys.argv) < 2:
    sys.exit(__doc__)
root = sys.argv[1]
p = os.path.join(root, "src", "freedreno", "vulkan", "tu_shader.cc")
s = io.open(p, encoding="utf-8").read()

if "FF PATCH: ir3_shader_create_variant" in s:
    sys.exit("REFUSED: tree already patched")

ANCHOR = """   shader->variant =
      ir3_shader_create_variant(ir3_shader, ir3_key, executable_info);
"""

NEW = """   shader->variant =
      ir3_shader_create_variant(ir3_shader, ir3_key, executable_info);

   /* FF PATCH: ir3_shader_create_variant() returns NULL when the ir3 compile
    * fails (e.g. the sched_block() deadlock).  Upstream walks straight into
    * `switch (shader->variant->type)` below and dereferences NULL -- on the
    * Thor that faulted at NULL+0x68 inside vkCreateGraphicsPipelines, Wine
    * turned the SIGSEGV into NTSTATUS c0000005, and winevulkan's assert then
    * aborted the whole process.  Fail the shader cleanly instead: DXVK copes
    * with a pipeline that will not compile, it cannot cope with a SIGSEGV.
    *
    * vk_free() alone is the correct inverse of tu_shader_init() here -- this
    * is before tu_upload_shader(), so shader->cs / shader->bo were never set
    * up and the full tu_shader_destroy() teardown must not be run on them.
    */
   if (!shader->variant) {
      ir3_shader_destroy(ir3_shader);
      vk_free(&dev->vk.alloc, shader);
      return VK_ERROR_UNKNOWN;
   }
"""

n = s.count(ANCHOR)
if n != 1:
    sys.exit(f"REFUSED: anchor found {n}x, expected exactly 1")

s = s.replace(ANCHOR, NEW, 1)
io.open(p, "w", encoding="utf-8").write(s)
print(f"patched {p}")
print("  added NULL-variant guard after ir3_shader_create_variant()")
