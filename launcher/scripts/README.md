# Launcher scripts

These run on the Thor as root (Magisk), except the two Python provisioning scripts and the tests, which run on a PC. Device paths are the ones I use: the scripts live in `/data/adb/wow/` and the game in `/storage/emulated/0/Games/WoW`. The container ids in them (1285328983, 1835007374, 1835007375) are my install's ids. GameNative derives them per install, so change them to yours.

## Single screen, stock GameNative

| File | What it does |
|---|---|
| `wowlaunch.sh` | The per-launch prep for one flavor (Config.wtf overlay, gamepad config, shared addons and SavedVariables), then points the WoW container at that flavor's ARM64 exe and launches it. `--no-launch` does the prep only. `tools/wow_mirror.py` deploys it. |
| `wow-gl-fix.sh` | A Magisk service.d daemon that puts the ARM64 DXVK DLLs and the patched ntdll back into the WoW container after GameNative overwrites them on launch. It also has an opengl32 branch, which never fires on my device (see the note in the script). |

## Dual screen, the GameNative fork (`app.gamenative.span`)

| File | What it does |
|---|---|
| `wowgo.sh` | The backend of the picker app in [launcher/android/wowspan/](../android/wowspan/). `wowgo.sh <retail\|classic\|beta> <direct\|bnet> <request id>` starts one flavor, `wowgo.sh --status` prints three lines (phase, message, request id) for the picker. |
| `provision_direct.py` | Run once from a PC over adb. Copies the fork's WoW container to a new "WoW Direct" container with its own `launch.bat` folder, which `wowgo.sh` rewrites per flavor in Direct mode. |
| `make_launch_packets.py` | Writes the files Battle.net mode needs: `go-<flavor>.bat` and `select-beta.bat` (they ask the running Battle.net to launch a game) and the 64-byte `exec-<flavor>.bin` / `select-beta.bin` requests that `wowgo.sh` sends to GameNative's winhandler on UDP 127.0.0.1:7946. The .bat files go in the Battle.net container's A: folder, the .bin files in `/data/adb/wow/`. |
| `wowspan.sh` | The older one-flavor (retail) entry point for the fork. Runs `wowlaunch.sh --no-launch`, then launches the fork. |
| `migrate_to_span.sh` | Copies the WoW setup from stock GameNative into the fork (imagefs, container, Wine, Turnip, library entry). |
| `set_span_geometry.sh` | Switches the fork's WoW container between the supported canvas sizes. |
| `wow-gl-fix-span.sh` | `wow-gl-fix.sh` for the fork's container. |

`wowgo.sh` also makes small fixes to ConsolePort (Forever only) and Glassy on launch, after backing up each file. The same fixes are in [patches/addons/](../../patches/addons/README.md). My own copy also changes one line in Syndicator for Forever. Syndicator is All Rights Reserved, so that part isn't here, and a comment in `wowgo.sh` marks where it was. It refuses to start a flavor unless FFSpan, FFScale, FFBinds, Syndicator and Baganator are installed in it.

## Tests

`test_display_prep.py`, `test_launch_state.py` and `test_provision_direct.py` run pieces of `wowgo.sh` and `provision_direct.py` against temp folders. `test_consoleport_compat.py` and `test_glassy_compat.py` run the addon-fix blocks of `wowgo.sh` against small stand-in files. Their Lua checks need the `lupa` Python package. Nothing touches a device. From this folder:

```
python -m unittest test_display_prep test_launch_state test_provision_direct test_consoleport_compat test_glassy_compat
```

Two of them need `bash` on PATH (Git Bash on Windows) and skip without it. On my PC: 25 tests, all pass.
