# Patches

These are the source changes behind the guide. They are plain `git apply` diffs. Nothing here is a build, and nothing is provided as a binary.

## gamenative/

The dual-screen fork of GameNative, one file per commit, in order. All twelve apply to GameNative commit aa03ebc0 (the legacy flavor, version 1.2.1 line). All twelve also apply in order to the v1.2.1 tag.

- 01 adds a `span` build type that installs next to stock GameNative as `app.gamenative.span`.
- 02 splits the X screen across both displays and routes touch to the right one.
- 03 is review fixes for 02: presentation re-create, a use-after-free on release timeout, clearing the touch region.
- 04 treats stored credentials that cannot be decrypted as logged out, which the side-by-side install needs.
- 05 and 06 make the gamepad shared memory path race-safe and point the controller shim at this package.
- 07 and 08 are the glue mode probe that detects the game window. 07 is a work-in-progress commit and the probe did not fire yet, 08 fixes it.
- 09 centres the game on the top screen and puts the bottom screen on both side strips.
- 10 puts a home screen on the left bottom strip and adds right-click by long press on the bottom panel.
- 11 makes a two-finger drag a mouse wheel on both screens.
- 12 is the `spantest` build type, span on by default with no root. It was built on top of 10, not on the fork branch, and it applies before or after 11. It is listed last because it is optional.

Order that I applied them in for the apply check: 01 to 12 on aa03ebc0.

On my device, the span fork runs WoW in span mode and I have logged in and played on it. The two-finger wheel (11) has one record, the commit message, which says the Shop scrolls on the top screen on my device on 2026-09-25. The `spantest` build (12) ran three cold starts to the login screen with no root on 2026-09-23. On that run the bottom screen showed the AYN control panel instead of black.

## gamenative-standalone/

Three more patches for a build that needs no root, has no closed binaries, and does not pretend to be GameNative. They apply on top of 12 and also directly on the `spantest` commit that 12 was exported from.

- 0001 turns span mode on by default only when the container screen size is 4400x1080. Any other size runs like stock single screen.
- 0002 removes the closed binaries that upstream ships (`libredirect`, `libsteambootstrap`, `libkgslshim`, the Samsung performance SDK) and the code that loads them. The patch holds only the text changes. Run `remove-blobs.sh` in the checkout to delete the binary files, so no copy of them lives here. Without them real Steam launch mode is gone, Faster external loading is off, and only the legacy flavor works.
- 0003 adds a `thorspan` build type with its own app id, label, an "unofficial fork" notice in Settings, and the update check and bug report upload switched off.

The app id in 0003 is `io.github.example.wowspan` and the label is "WoW Span". Both are placeholders. Set your own.

On my device, a build of this series reached the WoW login screen in span mode with no root and no libredirect on 2026-09-24. The first Play hung for 20 minutes on "Installing Mono", and the retry installed it in 25 seconds. I did not play in-world on that exact build. The version tested used a different app id than the placeholder here.

## proton-wine/

- `build-step-arm64ec.diff` comments out the 12 thread-suspension patches in GameNative's proton-wine arm64ec build step. See [docs/wine.md](../docs/wine.md).
- `crypt32-double-close.patch` fixes a double close in crypt32's root store import. The second close can hit another thread's descriptor, and bionic's fdsan kills the process. WoW died at Log In because of it. It is written against proton-wine 4f1adc72. On my device a 12-thread stress test of the root store import ran 20 of 20 times with no fdsan abort after the fix. It also ran 20 of 20 times before the fix, so that test did not reproduce the crash and does not prove the fix. The crash itself was seen at the WoW login. I applied and built this patch on my own proton-wine build tree and did not re-check it against a tree here.
- `wineserver-android-shared-owner.patch` makes wineserver treat files on Android shared storage as owned by the prefix user. Without it the Battle.net Agent cannot update or launch a game installed there. On my device the Agent got past its Update step with it on 2026-09-24. I applied this patch on my own proton-wine build tree and did not re-check it against a tree here.

## addons/

Small fixes to two third-party WoW addons, ConsolePort and Glassy, for Lua errors I hit on Forever. [launcher/scripts/wowgo.sh](../launcher/scripts/wowgo.sh) makes the same edits on launch. Details and licenses in [addons/README.md](addons/README.md).

## mesa/

`ff-turnip.patch` is the Turnip (Mesa freedreno Vulkan) patch. It has six FF PATCH hunks across three files. See [docs/graphics.md](../docs/graphics.md) for what each one fixes. It is meant for Mesa tag mesa-26.1.0. The build scripts that generate it are in [tools/turnip/](../tools/turnip/).
