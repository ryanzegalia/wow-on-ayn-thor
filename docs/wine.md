# Wine: the four fixes

GameNative runs Windows games through Wine. With the ARM64 WoW executable, four separate problems stopped it from reaching the login screen reliably. This page covers each one: what I saw, what I found, what I changed, and what I'm not sure about. Two later fixes, for a crash at Log In and for the Battle.net app, are after Fix 4.

Base: GameNative's `proton-10.0-arm64ec` Wine. Every offset below is for the builds I had. They move between builds. The syscall and winevulkan tools find their targets by pattern. The unwind tool only knows my original build and refuses anything else. My release script ([tools/release/make_release.sh](../tools/release/make_release.sh)) runs the syscall tool with `--force`, because the rebuilt `ntdll.dll` has a different size and 242 stubs, not 245. `--force` also skips every other safety check in that tool except the image base check. The script also replaces the build machine's home folder name, which the build compiles into about 1,500 of the package's files, with a neutral name of the same length.

## The constraint behind all of this

`Wow-ARM64.exe` is a plain ARM64 program (machine `0xAA64`, no CHPE). A plain ARM64 process can load ARM64 and ARM64X DLLs. It can't load ARM64EC or x64 DLLs. They fail with "Bad EXE format".

What that meant:

- Every community DXVK and VKD3D-Proton build I found for Android handhelds is ARM64EC. I checked their PE headers. None of them load here.
- GameNative installs x64/ARM64EC versions of several DLLs into the game's Wine prefix on every launch. Each one the game needs has to be replaced with a real ARM64 build. See [launcher.md](launcher.md) for how I keep them replaced.

## Fix 1: an unwind loop in `ntdll`

**What I saw.** The game hung, with the main thread spinning inside `ntdll.dll`. With `WINEDEBUG=+seh` the log filled with `warn:seh:virtual_unwind backtrace: <addr>: unknown module.` lines, almost always with the same address. (Wine logs these as `warn:seh`, not `trace:seh`.)

**What I found.** The address was in an anonymous read/write/execute memory region with no file behind it: code generated at runtime by the game's anti-tamper. There is no unwind data for that region. The loop is in Wine's `call_seh_handlers`, which keeps calling `virtual_unwind` until the stack pointer reaches the stack base. When a frame can't be unwound the stack pointer doesn't move, so the loop never ends. There's no check for "no progress".

**What I changed.** [tools/wine/patch_ntdll_unwind.py](../tools/wine/patch_ntdll_unwind.py) adds that check. It remembers the stack pointer between iterations and, if an unwind step didn't move it, takes the exit `ntdll` already has for an invalid stack. The new code sits in 56 bytes of unused alignment padding inside `ntdll.dll`. The tool checks six anchor instructions and the padding before writing anything.

**What happened.** The loop stopped: about 8.1 million of those log lines before the patch, about 500 after (a finite walk). It exposed Fix 2.

**Not sure.** I only re-tested WoW after this, not other games. On my later rebuilt Wine (Fix 4) I deployed the Fix 2 patch. I haven't confirmed whether the Fix 1 guard is still needed on that build. The `ntdll.dll` I run on it, and the one in the package my release script builds, have the Fix 2 patch and not the Fix 1 guard, and the game reaches the login screen with both. The Fix 1 tool only matches my original build, so it refuses the rebuilt `ntdll.dll`.

## Fix 2: the anti-tamper's copy of `ntdll` calls a NULL pointer

**What I saw.** With the loop gone, the game repeatedly crashed on an access violation at address 0. The register values matched a call to `NtProtectVirtualMemory`.

**What I found.** The anti-tamper reads `ntdll.dll` off disk into its own memory and calls the system call stubs in that private copy. On Windows those stubs make the system call themselves. In Wine each stub loads a function pointer (`__wine_syscall_dispatcher`) from a slot that only Wine's loader fills in when it loads `ntdll` normally. In the file on disk that slot is zero, so the private copy calls address 0.

Two more things I found:

- The game reads `ntdll.dll` from the Wine **prefix** (`drive_c/windows/system32`), not from the Wine install. Patching only the Wine install copy did nothing.
- Wine loaded `ntdll` at the same address in every process and every session on my device, so the real slot's address was predictable.

**What I changed.** [tools/wine/patch_ntdll_syscall.py](../tools/wine/patch_ntdll_syscall.py) with `--pinslot <address>` rewrites each stub's pointer to point at the real `ntdll`'s filled-in slot, and neutralises the relocation entries for those pointers so the anti-tamper's copy can't rebase them. On my original build that was 245 stubs and 980 changed bytes. On the rebuilt one it's 242 stubs and 968 bytes. The patched file has to go in both the Wine install and the prefix. With the imported package that happens by itself: GameNative copies `ntdll.dll` from the package into the prefix when it builds the prefix.

**What happened.** The private copy's stubs read the real dispatcher and the crash stopped. The anti-tamper still runs. It just doesn't fault anymore.

**Not sure / watch out.** The slot address depends on where Wine loads `ntdll`, and that changed when I rebuilt Wine (Fix 4). If it's wrong, I expect Wine to fail at startup. Measure it for your build: start the game and look for `aarch64-windows/ntdll.dll` in `/proc/<pid>/maps`. The dispatcher's offset inside `ntdll` (`0x11f750` for me) didn't change between my builds.

## Fix 3: `winevulkan` aborts the game on a driver error

**What I saw.** About 15 seconds in, the game exited with `_wassert vkCreateGraphicsPipelines`.

**What I found.** The GPU driver crashed while compiling a very large shader, inside that call (that driver bug is on [graphics.md](graphics.md)). Wine caught the crash and turned it into an error status. Then Wine's generated `winevulkan` code asserts the status is success, and the assert aborts the process. Only the assert killed the game, not the crash.

**What I changed.** [tools/wine/patch_winevulkan_assert.py](../tools/wine/patch_winevulkan_assert.py) replaces the assert path with "return `VK_ERROR_UNKNOWN`" (-13), using the function's own epilogue so the unwind info stays valid. `winevulkan.dll` is ARM64X and has two copies of that code. The tool patches both. Use `--out` to write the output. Without it the tool only reports.

**What happened.** DXVK logged `Failed to compile pipeline: -13`, skipped that pipeline and carried on. Since the driver fixes on [graphics.md](graphics.md), the count of `-13` lines in a session is 0 for me, and I use that count as a health check for any driver.

I didn't just skip the check. If the call faults, the result value is never written, so skipping the check could return leftover stack memory. That could look like success with no pipeline behind it.

## Fix 4: a loader-lock deadlock on about half of cold starts

**What I saw.** About half of cold launches hung forever before a window appeared. The process sat at the same memory size every time.

**What I found.** Wine logged `RtlpWaitForCriticalSection ... loader_section wait timed out`. The game creates worker threads with the flag `THREAD_CREATE_FLAGS_SKIP_THREAD_ATTACH`. Wine logged a `fixme:thread:NtCreateThreadEx Unsupported flags` line for them and ran the DLL thread-attach callbacks anyway, under the loader lock. Sometimes one of those threads never finished its attach, still holding the lock, and every other thread waited behind it.

GameNative's proton-wine source has an arm64ec patch set (in its `android/patches/test-bylaws` folder) that includes SkipThreadAttach support. On the commit I built from, the arm64ec build script also applies 12 patches from that set: the 7 under its "Thread Suspension Patches" heading plus 5 related ones it files under "Process and Virtual Memory Management" and "Server and Threading Infrastructure". With those in, the first process Wine starts (wineboot) was created suspended and never resumed, so every launch waited five minutes and failed.

**What I changed.** [patches/proton-wine/build-step-arm64ec.diff](../patches/proton-wine/build-step-arm64ec.diff) comments out those 12 patches and keeps the SkipThreadAttach ones. The base commit is recorded at the bottom of that file. Then I rebuilt proton-10 (about 22 minutes on my Linux PC). [tools/proton/build.sh](../tools/proton/build.sh) is the build script I ran.

**What happened.** 8 of 8 cold starts reached the login screen.

Things that cost me time while doing this:

- **GameNative replaced my Wine version setting.** It rewrites the container file from its own state when it exits and resets `wineVersion` to a version it already knows. A Wine build installed under a new name was never used. What worked: replace the *contents* of the existing `proton-10.0-arm64ec` folder and keep its `profile.json` version fields. The field `extraData.appliedWineVersion` shows what actually ran. Later I found that importing the build as a package through GameNative's Wine/Proton Manager, under its own name, avoids this: GameNative then knows the version and keeps it selected. That's how the package my release script builds is meant to be used ([quick-path.md](quick-path.md)).
- **Don't let GameNative build a new prefix for the rebuilt Wine.** The rebuilt one was missing `winhandler.exe` and hundreds of files, and the game exited cleanly with no error. I copied my existing working prefix instead. The package my release script builds doesn't use the build's prefix. It carries GameNative's own starting prefix (`prefixPack.tzst`, unchanged, from GameNative's stock proton-10 package). A prefix GameNative built from it reached the login screen 3 of 3 times.
- **The build script doesn't revert patches between runs.** A leftover file from a previous run made a later patch fail, the build installed an empty `bin/`, and the script still exited 0. Reset with `git checkout -- .` and `git clean -fd` between builds.
- **proton-11 wasn't the answer.** It doesn't have the deadlock, but on my device WoW crashed about 20 seconds in with a stack overflow, every time.

## Two later fixes: crypt32 and wineserver

These came after the four fixes above, once the game reached the login screen. [tools/proton/build.sh](../tools/proton/build.sh) doesn't apply either of them. I applied each one to my own proton-wine build tree and rebuilt.

### A crash at Log In: crypt32 closes a file descriptor twice

**What I saw.** On 24 September 2026 WoW died at Log In, with no crash dump. Android's log had `fdsan: attempted to close file descriptor N ... owned by FILE*`.

**What I found.** In Wine's crypt32, `import_certs_from_file()` wraps the file descriptor it's given in a `FILE` with `fdopen()` and closes it with `fclose()`, which closes the descriptor. Its caller, `import_certs_from_path()`, then calls `close()` on the same number. If another thread opened a file in between and got that number, the second `close()` closes that thread's file. Android's fdsan aborts the process when that file belongs to a `FILE`. Wine reads the root certificate store the first time a process opens it, which for WoW is the first TLS check at Log In, and Android's `getaddrinfo()` opens a `FILE` on every lookup.

**What I changed.** [patches/proton-wine/crypt32-double-close.patch](../patches/proton-wine/crypt32-double-close.patch) reads the file through a `dup()` of the descriptor, so `fclose()` only closes the copy and the caller's `close()` stays the only close of the original. It's written against proton-wine 4f1adc72.

**What happened.** The next two login attempts on my device didn't crash. They stopped at Blizzard's login block that day instead ([troubleshooting.md](troubleshooting.md)). A 12-thread stress test of the root store import ran 20 of 20 times with no fdsan abort after the fix. It also ran 20 of 20 times before the fix, so that test didn't reproduce the crash and doesn't prove the fix.

**Not sure.** The crash was random, so two attempts without it don't prove it's gone either. I haven't re-checked the patch against a fresh proton-wine tree.

### Battle.net: wineserver and files on shared storage

**What I saw.** The Battle.net Agent refused to update or launch the game installed in `Games/WoW`, on the Thor's shared storage.

**What I found.** Android's shared storage (`/storage/emulated`) is a FUSE mount. Every file there reports Android's MediaProvider as its owner, and apps can't change the mode bits. wineserver maps that owner to Anonymous Logon, so Windows access checks on those files fail.

**What I changed.** [patches/proton-wine/wineserver-android-shared-owner.patch](../patches/proton-wine/wineserver-android-shared-owner.patch) makes wineserver treat files there as owned by the prefix user, and stops a security-descriptor write from failing just because `fchmod` is refused on that mount. It only touches `server/file.c`.

**What happened.** On my device, on 24 September 2026, the Battle.net Agent got past its Update step with it. The whole route is on [battle-net.md](battle-net.md).

**Not sure.** I've only used it for Battle.net. I haven't re-checked the patch against a fresh proton-wine tree.

## Also on my device: a one-instruction `dxgi.dll` patch

Before DXVK, Wine's own D3D12 swapchain refused GameNative's Vulkan surface because the surface doesn't offer opaque composite alpha. I changed one branch in Wine's `dxgi.dll` to always take the "opaque is supported" path. With DXVK in use, DXVK's `dxgi.dll` replaces Wine's, so this patch only matters for the fallback path. There's no tool for it in this repo. On my proton-10 build the instruction was located by the bytes `e8 33 41 39 88 08 00 37`. That pattern doesn't exist in proton-11's `dxgi.dll`.

## Tools used for this

- [tools/wine/pe_dis.py](../tools/wine/pe_dis.py) disassembles a whole function using the DLL's own unwind table bounds. That's how I found the loop was in the caller, not in `virtual_unwind`.
- [tools/wine/pe_machine.py](../tools/wine/pe_machine.py) prints a DLL's machine type and whether it carries ARM64EC (CHPE) metadata.
