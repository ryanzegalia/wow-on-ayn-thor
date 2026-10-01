#!/usr/bin/env python3
"""Second FFEXT trace layer: prove WHERE a DXVK -13 is born (2026-09-22).

First trace build (mkpatch_ffext_variant_trace.py) showed: every DXVK `-13` follows a
`FFEXT tu_shader_create stage=4` entry marker by ~1 ms, and the NULL-variant guard
NEVER fires.  The only other VK_ERROR_UNKNOWN literal in Turnip is a GPU-timestamp
helper.  So the -13 is not produced by Turnip's return statements.  Candidates:
  (a) a fault INSIDE the driver during that fragment-shader compile, turned into -13
      by my winevulkan assert patch,
  (b) GameNative's Vulkan "Wrapper" layer manufacturing the code,
  (c) Turnip returning some OTHER error that a layer above remaps to -13.

This adds markers that separate them:
  - `FFEXT tu_shader_create OK`        success exit of tu_shader_create
  - `FFEXT tu_upload_shader FAIL=<r>`  the one non-guard failure exit
  - `FFEXT CGP enter count=N`          tu_CreateGraphicsPipelines entry
  - `FFEXT CGP[i] result=<r>`          per pipeline when result != VK_SUCCESS
  - `FFEXT CGP leave final=<r>`        tu_CreateGraphicsPipelines exit

Reading:  entry markers but no matching OK/leave  -> (a) fault inside the driver
          CGP leave final=0 yet DXVK prints -13   -> (b) the layer above lies
          CGP[i] result=<not -13>                 -> (c) remapped error, code shown

usage: mkpatch_ffext_pipeline_trace.py <mesa_src_root>   (idempotent)
"""
import sys
import pathlib

root = pathlib.Path(sys.argv[1])
tu_shader = root / "src/freedreno/vulkan/tu_shader.cc"
tu_pipe = root / "src/freedreno/vulkan/tu_pipeline.cc"
MARK = "FFEXT pipeline trace"


def edit(path, pairs, marker=MARK):
    s = path.read_text()
    if marker in s:
        print(f"  {path.name}: already instrumented, skipping")
        return
    for old, new in pairs:
        if s.count(old) != 1:
            sys.exit(f"anchor not unique in {path.name} (count={s.count(old)}):\n{old}")
        s = s.replace(old, new)
    path.write_text(s)
    print(f"  {path.name}: instrumented ({len(pairs)} edits)")


edit(tu_shader, [
    (
        """   VkResult result = tu_upload_shader(dev, shader);
   if (result != VK_SUCCESS) {
      vk_free(&dev->vk.alloc, shader);
      return result;
   }

   *shader_out = shader;
   return VK_SUCCESS;
}
""",
        """   VkResult result = tu_upload_shader(dev, shader);
   if (result != VK_SUCCESS) {
      mesa_loge("FFEXT tu_upload_shader FAIL=%d (stage=%d)", (int)result,
                (int)nir->info.stage); /* FFEXT pipeline trace */
      vk_free(&dev->vk.alloc, shader);
      return result;
   }

   mesa_logi("FFEXT tu_shader_create OK stage=%d", (int)nir->info.stage);
   *shader_out = shader;
   return VK_SUCCESS;
}
""",
    ),
])

edit(tu_pipe, [
    (
        """   MESA_TRACE_FUNC();
   VkResult final_result = VK_SUCCESS;
   uint32_t i = 0;

   for (; i < count; i++) {
      VkPipelineCreateFlags2KHR flags =
         vk_graphics_pipeline_create_flags(&pCreateInfos[i]);

      VkResult result =
         tu_graphics_pipeline_create<CHIP>(device, pipelineCache,
                                           &pCreateInfos[i], flags,
                                           pAllocator, &pPipelines[i]);

      if (result != VK_SUCCESS) {
         final_result = result;
         pPipelines[i] = VK_NULL_HANDLE;
""",
        """   MESA_TRACE_FUNC();
   VkResult final_result = VK_SUCCESS;
   uint32_t i = 0;

   mesa_logi("FFEXT CGP enter count=%u", count); /* FFEXT pipeline trace */
   for (; i < count; i++) {
      VkPipelineCreateFlags2KHR flags =
         vk_graphics_pipeline_create_flags(&pCreateInfos[i]);

      VkResult result =
         tu_graphics_pipeline_create<CHIP>(device, pipelineCache,
                                           &pCreateInfos[i], flags,
                                           pAllocator, &pPipelines[i]);

      if (result != VK_SUCCESS) {
         mesa_loge("FFEXT CGP[%u] result=%d flags=0x%llx", i, (int)result,
                   (unsigned long long)flags);
         final_result = result;
         pPipelines[i] = VK_NULL_HANDLE;
""",
    ),
    (
        """   for (; i < count; i++)
      pPipelines[i] = VK_NULL_HANDLE;

   return final_result;
}
TU_GENX(tu_CreateGraphicsPipelines);
""",
        """   for (; i < count; i++)
      pPipelines[i] = VK_NULL_HANDLE;

   mesa_logi("FFEXT CGP leave final=%d", (int)final_result);
   return final_result;
}
TU_GENX(tu_CreateGraphicsPipelines);
""",
    ),
])

s = tu_pipe.read_text()
if '#include "util/log.h"' not in s:
    s = s.replace('#include "tu_pipeline.h"', '#include "tu_pipeline.h"\n#include "util/log.h" /* FFEXT */', 1)
    tu_pipe.write_text(s)
    print("  tu_pipeline.cc: added util/log.h include")
print("done")
