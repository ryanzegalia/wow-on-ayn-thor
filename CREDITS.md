# Credits

Everything this setup runs on was made by other people. This page lists each project, its license, whether this repo includes anything from it, and what I changed.

"Included" means files from that project, or patches to it, are in this repo. "Used" means you install it yourself and nothing of it is here. None of the files built from these projects are provided here. The build scripts are.

## Runtime

| Project | By | License | In this repo | What I changed |
|---|---|---|---|---|
| [GameNative](https://github.com/utkarshdalal/GameNative) | Utkarsh Dalal and contributors | GPL-3.0 | Included: patches in [patches/gamenative/](patches/gamenative/) and [patches/gamenative-standalone/](patches/gamenative-standalone/) | Added a dual-screen "span" mode with a home screen on the bottom, a two-finger mouse wheel, a side-by-side build (package `app.gamenative.span`), and a few fixes the side-by-side install needed. The patches are made against [GameNative commit aa03ebc0](https://github.com/utkarshdalal/GameNative/commit/aa03ebc0b3d91cf54eca562b07eb61485fde3230) (legacy flavor), 15 commits before its v1.2.1 tag, and I built from that commit. All twelve patches also apply cleanly to v1.2.1 (`git apply --check`), but I haven't built from the tag. Patch 12 adds an experimental test build (`app.gamenative.spantest`) with span mode on by default. Three more patches in [patches/gamenative-standalone/](patches/gamenative-standalone/) make a build without GameNative's closed binaries, under its own app id. Details in [docs/dual-screen.md](docs/dual-screen.md) and [patches/README.md](patches/README.md). The Wine package that [tools/release/make_release.sh](tools/release/make_release.sh) builds contains GameNative's own starting prefix (`prefixPack.tzst` from its stock proton-10 package), unchanged. |
| [Winlator](https://github.com/brunodev85/winlator) | brunodev85 | LGPL-2.1 | Used (GameNative is built on it) | Nothing directly. |
| [Box64](https://github.com/ptitSeb/box64) | ptitSeb and contributors | MIT | Used (it comes with GameNative) | Nothing. On my Battle.net route the Battle.net installer runs under it ([docs/battle-net.md](docs/battle-net.md)). |
| [FEX](https://github.com/FEX-Emu/FEX) | The FEX-Emu contributors | MIT | Used (it comes with GameNative) | Nothing. On my Battle.net route the Battle.net app runs under it ([docs/battle-net.md](docs/battle-net.md)). |
| [Wine](https://www.winehq.org/) | The Wine project | LGPL-2.1-or-later | Included: byte-patch tools in [tools/wine/](tools/wine/). | Three small binary patches to `ntdll.dll` and `winevulkan.dll`. `make_release.sh` applies two of them, the `ntdll` syscall-stub patch and the `winevulkan` one, to the Wine package it builds. See [docs/wine.md](docs/wine.md). |
| [proton-wine](https://github.com/GameNative/proton-wine) (GameNative's Proton-based Wine) | GameNative, on top of Valve's [Proton](https://github.com/ValveSoftware/Proton) and Wine, with the arm64ec patch set from bylaws | LGPL-2.1-or-later (Wine) | Included: a build-script change and two source fixes in [patches/proton-wine/](patches/proton-wine/), and the build script I ran in [tools/proton/](tools/proton/). | Rebuilt proton-10 with 12 of the arm64ec patches left out (the 7 in its Thread Suspension set plus 5 related ones it files under Process and Virtual Memory Management and Server and Threading Infrastructure) so WoW's SkipThreadAttach handling works without hanging wineboot. Two source fixes: crypt32 closing a file descriptor twice, which crashed WoW at Log In, and wineserver treating files on Android shared storage as owned by the prefix user, which the Battle.net app needed. See [docs/wine.md](docs/wine.md). |
| [Mesa](https://gitlab.freedesktop.org/mesa/mesa) (Turnip / freedreno / ir3) | The Mesa project | MIT | Included: [patches/mesa/ff-turnip.patch](patches/mesa/ff-turnip.patch) and build scripts in [tools/turnip/](tools/turnip/). | Three fixes: an ir3 scheduler deadlock, a NULL guard in `tu_shader.cc`, and skipping a descriptor prefetch instead of crashing when there's no block to put it in. See [docs/graphics.md](docs/graphics.md). |
| [DXVK](https://github.com/doitsujin/dxvk) | Philip Rebohle and contributors | zlib | Included: build recipe in [tools/dxvk/](tools/dxvk/). | Nothing in the source. I cross-compiled it for plain ARM64 Windows (not ARM64EC). |
| [llvm-mingw](https://github.com/mstorsjo/llvm-mingw) | Martin Storsjo | ISC for its build scripts. The toolchain it builds is LLVM's Apache-2.0 with LLVM exceptions, plus its other parts' licenses. | Used (the toolchain the DXVK build runs in) | Nothing. |
| [Magisk](https://github.com/topjohnwu/Magisk) | topjohnwu and contributors | GPL-3.0 | Used (root). The launcher scripts in [launcher/](launcher/) run under it. | Nothing. |

## Game client

| Project | By | License | In this repo | What I did with it |
|---|---|---|---|---|
| [TACTSharp](https://github.com/wowdev/TACTSharp) (TACTTool) | wowdev | MIT | Used | Downloaded Blizzard's ARM64 retail executable from Blizzard's CDN, because Battle.net on my x86 PC didn't install it for retail. See [docs/game-client.md](docs/game-client.md). |
| World of Warcraft | Blizzard Entertainment | Blizzard's EULA | Nothing | The game is unmodified. You need your own account and copy. |
| Battle.net | Blizzard Entertainment | Blizzard's EULA | Nothing | Installed and run on the Thor inside GameNative, unmodified. My tool in [tools/battlenet/](tools/battlenet/) writes its install records so it finds the game I copied from the PC. See [docs/battle-net.md](docs/battle-net.md). |

## Addons

| Addon | By | License | In this repo | Notes |
|---|---|---|---|---|
| [ConsolePort](https://github.com/seblindfors/ConsolePort) | Sebastian Lindfors | Artistic-2.0 (its embedded LibActionButton-1.0 is BSD 3-clause, by Hendrik Leppkes) | Used. Included: two small fixes in [patches/addons/](patches/addons/README.md) | The controller UI. One download installs nine folders (ConsolePort and its ConsolePort_ modules). My FFBinds addon writes bindings for ConsolePort's gamepad buttons. On Forever my launcher fixes two Lua errors in it, in ConsolePort_Menu and in its copy of LibActionButton-1.0. |
| [Immersion](https://github.com/seblindfors/Immersion) | Sebastian Lindfors | Artistic-2.0 on GitHub. Its CurseForge page says All Rights Reserved. | Used | Dialogue UI. |
| [Glassy](https://github.com/Solessfir/Glassy) (CurseForge project 1695833) | Solessfir, a fork of [Glass](https://github.com/mixxorz/Glass) by mixxorz | MIT | Used. Included: one small fix in [patches/addons/](patches/addons/README.md) | Chat UI. On the dual-screen home screen, FFSpan moves its chat frame into place. My launcher skips its cosmetic chat re-anchor where Glassy treats the client as retail, to stop a startup Lua error. |
| Offhand - Dual-Screen and Multi-Monitor UI ([repo](https://github.com/N4UX-GIT/Offhand-DualMonitor)) | N4UX | Personal use only, no redistribution, no public derivatives, no commercial use | **Not included** | I used it in my first dual-screen version. It is not included and not needed now. FFSpan still contains code that switches Offhand off if you have it installed, because Offhand changes some settings at login even when disabled. |
| [Baganator](https://www.curseforge.com/wow/addons/baganator) | plusmouse | All rights reserved | Used, dual screen only | Bags. On the dual-screen home screen FFSpan uses it if it's installed, by name, without any of its code. It needs Syndicator. |
| [Syndicator](https://www.curseforge.com/wow/addons/syndicator) | plusmouse | All rights reserved | Used, dual screen only | Baganator needs it. Its .toc lists it as optional, but Baganator stopped with an error for me without it. |
| [Leatrix Maps](https://www.curseforge.com/wow/addons/leatrix-maps) | Leatrix | All rights reserved | Used, dual screen only | World map, with its default settings. FFSpan places the map on the bottom screen. |
| [Talent Tree Tweaks](https://www.curseforge.com/wow/addons/talent-tree-tweaks) | Numy | All rights reserved | Used | I had it installed. Its Scale Talent Frame module resets the talent window's scale, so I turned that one module off. |
| FFScale, FFBinds, FFSpan | Me | MIT | Included: [addons/](addons/) | My own addons. Free and readable, per Blizzard's [UI Add-On Development Policy](https://us.forums.blizzard.com/en/wow/t/ui-add-on-development-policy/24534). |

## People whose work pointed the way

- **Illustrious-Cat-4281.** Their r/AynThor thread ([WoW classic native on Blizzard servers](https://www.reddit.com/r/AynThor/comments/1wj4b5r/wow_classic_native_on_blizzard_servers/), 17 September 2026) is where I learned that Blizzard ships an ARM64 build of WoW that runs without x86 translation. They explained it in a reply the next day. Everything in this guide is built on that route.
- **FrontMage**, who made [winlator-llm](https://github.com/FrontMage/winlator-llm) (MIT), a Winlator fork that runs retail WoW through the official Battle.net client. The r/EmulationOnAndroid [post](https://www.reddit.com/r/EmulationOnAndroid/comments/1v7of42/) showing it, on 27 July 2026, links FrontMage's GitHub.

## Working on the same thing at the same time

- **BryTheGuy06**, on a Retroid Pocket 6 through GameHub Lite. In the same r/AynThor thread ([comment](https://www.reddit.com/r/AynThor/comments/1wj4b5r/comment/pb02xuj/), 20 September 2026) they described building plain ARM64 DXVK 2.4.1, patching Proton 11's Wine for WoW's copied ARM64 syscall stubs, and patching Turnip's shader scheduler. Those are the three problems I hit. I fixed them separately, over the same days. Their post linking a draft setup guide: [r/retroid](https://www.reddit.com/r/retroid/comments/1wobe1u/i_got_wow_forever_beta_running_on_the_rp6_with/), 23 September 2026.

If I've left anyone out or got a license wrong, please open an issue and I'll fix it.
