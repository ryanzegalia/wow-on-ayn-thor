# Turnip build tools

- `build.sh` builds Turnip (Mesa's Vulkan driver for Adreno) for Android with `android-aarch64.txt` as the Meson cross file. With `--patch` it applies every patch in its `patches/` folder first: copy [../../patches/mesa/ff-turnip.patch](../../patches/mesa/ff-turnip.patch) there.
- `mkpatch_ir3_sched.py`, `mkpatch_tu_nullvariant.py` and `mkpatch_ir3_prefetch_nullblock.py` make the three fixes in that patch, one each.
- `deploy_driver.sh` copies a built driver onto the device as a GameNative driver.
- `diagnostics/` holds the six `mkpatch_ffext_*.py` scripts I used to find where the driver crashed (logging and tracing only, not needed for a normal build).

The `mkpatch_*.py` scripts here and in `diagnostics/` patch Mesa's source by exact text match. The anchor strings are copied byte for byte from Mesa, including Mesa's own code comments, so they keep Mesa's wording (for example the "we must be able to find a legal place" comments in `mkpatch_ir3_prefetch_nullblock.py`, which stops unless it finds each anchor exactly once). Changing an anchor breaks the match.
