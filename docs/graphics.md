# Graphics: DXVK and the Turnip driver

## DXVK built for plain ARM64

**What I found.** The Android DXVK builds I could find are all ARM64EC, and the ARM64 game can't load them (see [wine.md](wine.md)). I didn't find a published plain ARM64 build. A request for ARM64EC/ARM64X builds on the DXVK tracker (issue 5423) was closed as not planned.

**What I did.** I cross-compiled upstream DXVK for `aarch64-w64-mingw32` with [llvm-mingw](https://github.com/mstorsjo/llvm-mingw), inside its `mstorsjo/llvm-mingw` Docker image. [tools/dxvk/build.sh](../tools/dxvk/build.sh) is the script I ran in that container. Its header has the DXVK checkout steps and the `docker run` line. The cross file is [tools/dxvk/build-aarch64.txt](../tools/dxvk/build-aarch64.txt). It's the same shape as DXVK's own `build-win64.txt`, with `cpu_family='aarch64'` and the aarch64 compilers, and without that file's `needs_exe_wrapper` line. The build took about 6 minutes for me, with the container limited to 4 CPUs.

The output DLLs (`d3d11.dll`, `dxgi.dll`, `d3d10core.dll`, and others) report machine ARM64 with no CHPE.

I set `SET GxApi "D3D11"` in the game's `Config.wtf` (my launcher's [overlay.wtf](../launcher/config/overlay.wtf) has it too). In my rooted setup I also set `WINEDLLOVERRIDES=dxgi,d3d11,d3d10core=n` on the container. With the imported package from the [quick path](quick-path.md) it worked without that, because GameNative already sets those DLLs to "native, then builtin" in the prefix's registry.

The `dxvk-3.1.1-40e0164-arm64.wcp` that [tools/release/make_release.sh](../tools/release/make_release.sh) packages holds `d3d11.dll`, `dxgi.dll` and `d3d10core.dll` from this build ([DXVK commit 40e0164](https://github.com/doitsujin/dxvk/commit/40e01640396d03f9fddeb697f5ee00ae893ecb75), after 3.1.1), unmodified.

**Tip.** `DXVK_LOG_LEVEL=info` gets DXVK to say why it rejected a GPU. It answered in one log what hours of Wine tracing didn't.

## Why I built my own Turnip

**What I saw.** The game kept failing to compile one very large fragment shader. With GameNative's bundled Turnip builds, the failure crashed inside the driver (see Fix 3 on [wine.md](wine.md)). After that fix the game ran, but DXVK still dropped about 9 pipelines per session with error `-13`.

**What I found.** I read the driver source (Mesa's ir3 compiler, the lineage GameNative's Turnip builds come from) and found three problems:

1. **Scheduler deadlock.** In `ir3_sched.c`, a `demote`/`kill` instruction can't be scheduled until every `bary.f` in the shader is scheduled. That list is shader-wide, but the scheduler works one block at a time. A `bary.f` in a later block can never be scheduled first, so the scheduler runs out of instructions and gives up. In a release build the reason is compiled out, so the only log is `compile failed!`. WoW has a fragment shader with about 90 blocks that hits it.
2. **A NULL dereference** in the driver's failure path (`tu_shader.cc`) when a shader variant fails.
3. **A missing insert point in the descriptor-prefetch pass** (`ir3_nir_opt_preamble.c`). When the pass looks for a block to insert a prefetch into, `find_insert_block()` (and `find_insert_block_for_defs()` at the second site) can return NULL. The code asserts it never does, but the assert is compiled out of release builds, so it inserted after a NULL block and crashed. About 9 large fragment shaders per session hit this. Each crash cost one pipeline, which DXVK logged as error `-13`. Setting `IR3_SHADER_DEBUG=nodescprefetch` made those failures go away, which is how I confirmed it.

**What I changed.** [patches/mesa/ff-turnip.patch](../patches/mesa/ff-turnip.patch):

1. The `bary.f` check only considers `bary.f` instructions in the same block as the `demote`. One in an earlier block is already scheduled, so in the normal case this changes nothing. The silent give-up is replaced with a logged error.
2. A NULL guard for the failed variant.
3. In the prefetch pass, the two asserts (in `_rematerialize_def` and `emit_descriptor_prefetch`) became "skip this prefetch", and `ir3_nir_opt_prefetch_descriptors` leaves an access un-prefetched when that happens. The shader compiles without that one prefetch.

The scripts that generate each part of the patch are in [tools/turnip/](../tools/turnip/): [mkpatch_ir3_sched.py](../tools/turnip/mkpatch_ir3_sched.py), [mkpatch_tu_nullvariant.py](../tools/turnip/mkpatch_tu_nullvariant.py) and [mkpatch_ir3_prefetch_nullblock.py](../tools/turnip/mkpatch_ir3_prefetch_nullblock.py).

**What happened.** On my Thor the shader compiles, with zero `compile failed!` lines. Over a session the count of DXVK `-13` pipeline errors is 0.

**Not sure.** I've only run this driver on my Thor with WoW. I haven't tested it with other games. I think the scheduler issue is a Mesa bug rather than something Thor-specific, but I haven't reported it and nobody from Mesa has looked at it.

## Building Turnip

[tools/turnip/build.sh](../tools/turnip/build.sh) builds Turnip for Android arm64 on a Linux x86-64 PC and packages it as an adrenotools driver zip. It downloads nothing. It expects:

- A Mesa git checkout in `~/wow-turnip/src`. The driver I use was built from the `mesa-26.1.0` tag (commit [1d7b6318b9](https://gitlab.freedesktop.org/mesa/mesa/-/commit/1d7b6318b9e4f86b4bb5a60c5d5fa873deb6e517)), and the patch is made against that tag.
- The cross file [tools/turnip/android-aarch64.txt](../tools/turnip/android-aarch64.txt) copied to `~/wow-turnip/android-aarch64.txt`, with its `pkg_config_libdir` line pointed at an empty directory.
- The Android NDK r27c in `~/android-ndk-r27c`, or `NDK` set to where yours is.
- meson, ninja, git and zip, with pkg-config at `/usr/bin/pkg-config`. Ubuntu's packaged meson was too old for me, so I used one from pip. The script adds `~/.local/bin` to `PATH` for that.

`bash build.sh --patch` reverts local changes to tracked files under the checkout's `src/` directory, then applies every `.patch` in `~/wow-turnip/patches/`. Copy [patches/mesa/ff-turnip.patch](../patches/mesa/ff-turnip.patch) there first. `--clean` deletes the build directory and configures from scratch. The output goes to `~/wow-turnip/out/`: `libvulkan_freedreno.so` and `turnip-ff-<version>-ffpatched.zip` (`-stock` without `--patch`). The script ends with a bionic symbol check that must print "clean". A driver that needs a bionic symbol newer than Android 13 fails to load on the Thor, and adrenotools then quietly falls back to the stock driver.

[tools/turnip/deploy_driver.sh](../tools/turnip/deploy_driver.sh) pushes a built `.so` to the Thor over adb, installs it as a GameNative driver and points the WoW container at it. It needs root on the device and `THOR_SERIAL` set to the Thor's adb serial. The values at the top of the script (`CID`, the container id, and `APP_UID`, GameNative's Android user) are from my install, so set yours first.

The `turnip-26.1.0-wow.zip` that `make_release.sh` packages is this build: Mesa 26.1.0 with the patch, repackaged with a plain name and Mesa's license file. It imports through GameNative's Driver Manager without root.

**The build option to know about:** Mesa's `android-strict` option defaults to true, and it hides 13 Vulkan extensions from the app, including `VK_KHR_load_store_op_none`, which DXVK 3.x requires. DXVK then reported "No adapters found". Build with `-Dandroid-strict=false`. `build.sh` does this.

From Wine's `WINEDEBUG=+vulkan` output on my device:

| Driver | Extensions Wine enabled |
|---|---|
| GameNative's default Turnip v26.2.0 R4 | 173 |
| Mine, `android-strict` left at default | 160 |
| Mine, `-Dandroid-strict=false` | 174 |

## Driver settings that mattered

- **GameNative resets a hand-pinned driver after one launch.** It rewrites the container file from its own state on exit. My launcher re-pins the driver every launch. A driver imported through GameNative's Driver Manager and picked in the container settings stays picked. Check what actually ran in the run's own environment line, `ADRENOTOOLS_DRIVER_PATH=.../adrenotools/<name>/`.
- **With adrenotools off,** DXVK rejected the stock driver for missing `storageBuffer8BitAccess`. Turning on `adrenotoolsTurnip=1` in the container's driver config fixed that.
- **The GPU name the game sees** is `Wrapper(Turnip Adreno (TM) 740)`. See [ban-risk.md](ban-risk.md).

## Diagnostics

[tools/turnip/diagnostics/](../tools/turnip/diagnostics/) has the instrumentation patches I used to find where the driver was failing: entry/exit markers per compile phase, a fault handler with a backtrace, and pipeline and variant tracing. They generate throwaway patches for debugging, not fixes.

I ran them in this order, each one narrowing down where the last one pointed:

1. `mkpatch_ffext_variant_trace.py`: makes a NULL shader variant log why it's NULL.
2. `mkpatch_ffext_pipeline_trace.py`: shows where a DXVK `-13` starts.
3. `mkpatch_ffext_ir3_phase_trace.py`: brackets the compiler crash by phase and dumps the NIR of every fragment shader before it compiles.
4. `mkpatch_ffext_preemit_trace.py`: narrows the crash window before emit and measures thread stack headroom.
5. `mkpatch_ffext_bigstack.py`: compiles shader variants on a helper thread with a 16 MB stack.
6. `mkpatch_ffext_faulttrace.py`: catches the fault on that thread and logs where it is, with a frame-pointer backtrace.

To turn an offset from the fault handler into a function name, use `llvm-symbolizer` (or `llvm-nm -n`) on the unstripped build output.
