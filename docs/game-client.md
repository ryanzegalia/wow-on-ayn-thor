# Getting the ARM64 game client

## What I found

Every WoW flavor I checked ships a native ARM64 Windows executable. I read the PE header of each one (machine type `0xAA64`, plain ARM64, not ARM64EC):

| Product | Build I checked (September 2026) | Executable | Size |
|---|---|---|---|
| Retail (`wow`) | 12.1.0.69875 | `Wow-ARM64.exe` | 73.6 MB |
| MoP Classic (`wow_classic`) | 5.5.4.69585 | `WowClassic-ARM64.exe` | 60.2 MB |
| Classic Era (`wow_classic_era`) | 1.15.9.69722 | `WowClassic-ARM64.exe` | 60.0 MB |
| Classic beta (`wow_classic_beta`) | 1.60.1.69913 | `WowB-ARM64.exe` | 98.5 MB |

These are the builds I checked in September 2026. Builds move on every patch, so yours will be newer. The exe names stay the same. Retail on my Thor is 12.1.0.69933 as of 23 September 2026.

Blizzard ships these for Windows on ARM PCs. Running the ARM64 executable means no x86 emulation is involved.

Battle.net on my x86 PC did **not** install `Wow-ARM64.exe` for retail. A finished retail install on my PC had only `Wow.exe` (x86-64). The Classic beta install did include `WowB-ARM64.exe` alongside the x86 one. Battle.net also didn't update the beta's ARM64 exe after a patch. The install moved to build 69977 and `WowB-ARM64.exe` stayed at 69913.

On the Thor, the Battle.net app running inside GameNative started `Wow-ARM64.exe` when I pressed Play ([battle-net.md](battle-net.md)).

## What I did

I used TACTTool from [TACTSharp](https://github.com/wowdev/TACTSharp) to download the ARM64 executable from Blizzard's public CDN:

```
TACTTool.exe -p wow -m name -i "Wow-ARM64.exe" -o Wow-ARM64.exe
```

In `name` mode `-o` is the output file name, not a folder.

The file it gave me reported FileVersion 12.1.0.69875, the same build as the `Wow.exe` Battle.net had installed.

[tools/wow_arm64.py](../tools/wow_arm64.py) does this for every installed flavor. It reads each product's build from `.build.info`, pulls the matching ARM64 exe, checks it's ARM64 with [tools/wine/pe_machine.py](../tools/wine/pe_machine.py), and writes a sidecar file with the build number. [tools/wow_sync.py](../tools/wow_sync.py) refuses to push an ARM64 exe whose sidecar doesn't match `.build.info`. [tools/stage_flavor.py](../tools/stage_flavor.py) doesn't check the sidecar, so run wow_arm64.py before it.

**Please read this before doing the same.** This downloads a file with a third-party tool instead of the Battle.net app. It's Blizzard's own file, for a game on an account I own, and Battle.net offers no way to get it on an x86 PC. Blizzard's terms still mention access through unauthorized third-party software, and this could arguably fall under that. I'm stating it so you can decide for yourself. See [ban-risk.md](ban-risk.md).

## Copying the game to the Thor

A WoW install isn't one folder per flavor. The game data (`Data/`) and `.build.info` sit at the install root and are shared by every flavor. So copying retail means copying `Data/`, `.build.info` and `_retail_/`, not `_retail_/` alone.

The Thor gets the same layout at `/storage/emulated/0/Games/WoW`.

[tools/stage_flavor.py](../tools/stage_flavor.py) does this with `adb push --sync`, which only sends files whose timestamps differ, so an interrupted copy can be resumed. Set `WOW_PC_INSTALL` to your PC's `World of Warcraft` folder and `THOR_SERIAL` to the Thor's adb serial.

## After every Blizzard patch

For me, the first sign of a patch was realm selection marking the realm **incompatible**. The PC had updated and the Thor still had the old build.

What fixed it for me:

1. Let Battle.net update the PC install.
2. Pull the new ARM64 exe ([tools/wow_arm64.py](../tools/wow_arm64.py)). Battle.net won't update it.
3. Copy the changed `Data/` files, `.build.info` and the new exe to the Thor.

## Which executable GameNative runs

The container's executable path points at the ARM64 exe, for example `_retail_/Wow-ARM64.exe`. I use one GameNative container for all flavors and change that one setting to switch between them. My launcher does that on every launch ([launcher.md](launcher.md)). The older [tools/wow_flavor.py](../tools/wow_flavor.py) did it by hand through [tools/gn_patch_container.py](../tools/gn_patch_container.py), which always keeps a backup of the container file.

I didn't make a second container per flavor. GameNative keeps custom games in its own settings store, so a copied container folder doesn't show up in the app. The dual-screen picker does use copies, one per login mode, and starts them by id instead of from the app's list ([launcher.md](launcher.md#the-containers)).
