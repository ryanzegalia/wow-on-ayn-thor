# Launcher and scripts

The scripts in [launcher/scripts/](../launcher/scripts/) run as root (Magisk), on the Thor or over adb. These are the scripts I actually use. They're written for my install, so read the values at the top of each one before running it.

You don't need them to run the game. The [quick path](quick-path.md) gets the same Wine, DXVK and driver files into GameNative without root. The scripts are how I run every flavor from one container, with shared settings and addons.

## Values that are specific to my install

- **The GameNative custom game id**, `1285328983` (container `CUSTOM_GAME_1285328983`). GameNative assigns this when you add a custom game, so yours will be different. It appears in the launcher scripts, both DLL scripts, the dual-screen app, wow_controls.py and wow_flavor.py.
- **The picker's two other containers**, `1835007375` (WoW Direct) and `1835007374` (Battle.net), in wowgo.sh, provision_direct.py and the files in [tools/battlenet/](../tools/battlenet/README.md). These are my install's ids too ([the containers](#the-containers)).
- **Your game account name** (`WOW_ACCOUNT`, used for the `WTF/Account/<name>/` folder) and your Battle.net login in [launcher/config/overlay.wtf](../launcher/config/overlay.wtf) and the `overlay-*.wtf` files. I replaced mine with placeholders.
- **The driver name**, `Turnip FF 26.1.0 patched v2` (`DRIVER` in wowlaunch.sh, `DRIVER_NAME` in migrate_to_span.sh). It has to match the name of the driver you imported into GameNative. If you imported the driver from the quick path, that name is `Turnip 26.1.0 WoW patch`.
- **The seed account and character** for wow_mirror.py (`WOW_SEED_ACCOUNT`, and `WOW_SEED_CHAR` as `Realm/Character`). `push` copies the shared saved variables and the ConsolePort bar layout from there once. Set both before the first `push`.
- **The region**, `SET portal "US"` in overlay-retail.wtf and overlay-classic.wtf.

## The DLL scripts (Magisk boot scripts)

GameNative copies its DXVK DLLs into the game's Wine prefix on every launch, and sets up the rest of the prefix from its own files on first boot and whenever the Wine version, the container variant or GameNative's system image changes. Its DXVK is x64, and the ARM64 game can't load that. [launcher/scripts/wow-gl-fix.sh](../launcher/scripts/wow-gl-fix.sh) runs from Magisk's `service.d` and copies the right ones back for the WoW container only:

- `d3d11`, `d3d10core`, `dxgi`: my ARM64 DXVK build ([graphics.md](graphics.md))
- `opengl32`: Wine's own ARM64 build (GameNative puts an ARM64EC one there)
- `ntdll`: the patched one ([wine.md](wine.md)), in the prefix, which is where the game's anti-tamper read it from on my device

The DXVK and `ntdll` master copies live in `/data/adb/wow/`. The `opengl32` copy comes from the proton-10 install's own `aarch64-windows` folder. [launcher/scripts/wow-gl-fix-span.sh](../launcher/scripts/wow-gl-fix-span.sh) does the same for the dual-screen fork.

On my device the `opengl32` part has done nothing for a while. Its source path names the `proton-10.0-arm64ec` folder, my container runs `proton-10.0-arm64ec-2`, and the script logs an empty `gl=` at every boot, so it never finds a file to copy. The game has run fine for me with GameNative's own `opengl32`.

wow_mirror.py doesn't install these scripts. Copy them into `/data/adb/service.d/` yourself and make them executable (wow-gl-fix-span.sh only if you use the fork).

With the imported files from the quick path I didn't need this script. GameNative copies the imported ARM64 DXVK in on every launch, the patched `ntdll` comes with the imported Wine package, and the game reached the login screen with GameNative's own `opengl32` left in place.

## One launcher for every flavor

[launcher/scripts/wowlaunch.sh](../launcher/scripts/wowlaunch.sh) takes `retail`, `classic` or `beta`. It runs as root in the global mount namespace (`su --mount-master`). On every launch it:

1. Refuses to do anything if a WoW client is running. Force-stopping would lose saved variables, because WoW only writes them when you log out, reload the UI or quit.
2. Re-applies the shared settings in that flavor's `Config.wtf` ([launcher/config/overlay.wtf](../launcher/config/overlay.wtf) plus the per-flavor file). It sets the graphics preset level but none of the individual settings under it, because on my device the game rewrote those from the preset when it loaded.
3. Copies `GamePadConfig_Thor.json` into the flavor's `WTF`.
4. Copies the shared addons ([launcher/config/addons.list](../launcher/config/addons.list)) from `_retail_` to the other flavors when a `.toc` differs. The list now also has FFBinds, FFSpan, Syndicator and Baganator. It names folders only, so you install the third-party ones yourself.
5. Copies account-wide saved variables ([launcher/config/shared-sv.list](../launcher/config/shared-sv.list)) between flavors, newest file wins. `ConsolePort_Cursor.lua` is left out on purpose: it lists flavor-specific windows.
6. Gives each character the tuned ConsolePort action bar layout once.
7. Points the one GameNative container at the flavor's ARM64 exe and re-pins the graphics driver.
8. Starts the game through GameNative's `LAUNCH_GAME` intent.
9. Watches logcat in the background while the game runs and, when it exits, logs how many DXVK `pipeline: -13` lines it saw (pipelines the driver failed to build). This needs `DXVK_LOG_LEVEL=info` in the container's environment variables.

`--no-launch` stops after step 6. The dual-screen launchers use that.

Log: `/sdcard/wowlaunch.log`.

**Always launch through this script, not GameNative's launch intent directly.** The container's executable is set per launch, so launching GameNative directly boots whichever flavor ran last.

This is the single-screen launcher, in stock GameNative. It's still there and still works. For dual screen I use the picker below, which runs this script's preparation and then starts the fork.

## The WoW Dual Screen picker

The "WoW Dual Screen" app ([launcher/android/wowspan/](../launcher/android/wowspan/README.md), `com.ff.wowspan`) and its root backend [launcher/scripts/wowgo.sh](../launcher/scripts/wowgo.sh) start any flavor in dual screen with one tap.

- Three tiles, Retail, Classic and Forever, and two mode buttons. **Direct** starts the game at its own login screen. **Battle.net** lets Battle.net sign in and start the game ([battle-net.md](battle-net.md)). The app remembers the mode.
- A tap runs `wowgo.sh <flavor> <mode>` as root (`su --mount-master`). While the app is showing, it asks `wowgo.sh --status` every 2 seconds and shows the phase and message it gets back. If `/data/adb/wow/wowgo.sh` isn't there, it says the launcher preparation isn't installed. If the backend doesn't answer within 30 seconds, it shows an error.
- With the controller, the D-pad moves between the five controls, A picks and B goes back.
- The tile pictures I use are game art, so they aren't in this repo. Without them the app draws plain tiles. Its README lists the files you supply.

On each launch wowgo.sh:

1. Brings the game to the front if a WoW client is already running, and resumes a session I paused, instead of starting another.
2. Takes a lock, so a second tap attaches to the launch already running instead of starting a second one.
3. Checks, before it changes anything, that the flavor's ARM64 exe, wowlaunch.sh, the shared files and the fork are there, that no other GameNative Wine session is running, and that Battle.net isn't open in Direct mode or in another app.
4. Runs `wowlaunch.sh <flavor> --no-launch` for the shared preparation (above).
5. Refuses to start a flavor that doesn't have FFSpan, FFScale, FFBinds, Syndicator and Baganator in its `Interface/AddOns` ("Missing <addon> for <flavor>"). That's my setup's requirement. To change it, edit the `for ADDON in ...` list in wowgo.sh.
6. For Forever, removes the window-size settings it inherits from the shared `Config.wtf`, after a backup, because they stretched a 1920-wide render across the 4400 canvas.
7. Moves Offhand out of `Interface/AddOns` into `Interface/_disabled` in every flavor, if it's there. It also makes the small ConsolePort fixes (Forever only) and the Glassy fix from [patches/addons/](../patches/addons/README.md), after backing up each file. My own copy also changes one line in Syndicator for Forever, which isn't in this repo ([dual-screen.md](dual-screen.md#third-party-addons)).
8. Direct mode: writes the Direct container's `launch.bat` to start the chosen exe. Battle.net mode: checks that the Battle.net container and the flavor's launch request are there.
9. Starts the fork with GameNative's `LAUNCH_GAME` intent and the container id. In Battle.net mode it then waits for the sign-in and sends the launch ([battle-net.md](battle-net.md)).
10. Reports "running" once the right client process appears in the fork. When the game exits and Battle.net is closed, it stops the fork and opens the picker again.

On my device, on 25 September 2026, after a reboot: one tap on Retail in Direct mode brought up the login screen on the top screen, and quitting from the login screen went back to the picker in under 30 seconds.

### The containers

All three are in the fork (`app.gamenative.span`). The ids are my install's.

- `1285328983`: my original WoW container, the one wowlaunch.sh points at each flavor. wowgo.sh doesn't change it.
- `1835007375`, "WoW Direct": a copy of the original for the picker's Direct mode. [provision_direct.py](../launcher/scripts/provision_direct.py) makes it over adb, as root. It copies the original container's folder, gives the copy its own id and name, sets drive A: to `CustomGames/WoWDirect` (with its `launch.bat`) and B: to the game folder, selects the ARM64 DXVK package, writes a `.gamenative` file with the new id into the A: folder, and sets the owner and SELinux label. It refuses to run while WoW or Battle.net is running, and afterwards checks that the original container's file and the wineserver are byte for byte the same. wowgo.sh starts this container by its id through the launch intent, so it doesn't need an entry in GameNative's own list. I haven't checked whether it shows up there.
- `1835007374`: the Battle.net container ([battle-net.md](battle-net.md)).

### What goes in `/data/adb/wow/`

- `wowgo.sh` and `wowlaunch.sh`. wow_mirror.py copies `wowlaunch.sh` but not `wowgo.sh`, so put that one there yourself.
- For Battle.net mode: `exec-retail.bin`, `exec-classic.bin`, `exec-beta.bin` and `select-beta.bin`, which [make_launch_packets.py](../launcher/scripts/make_launch_packets.py) writes. It also writes the matching `go-<flavor>.bat` and `select-beta.bat`, which go in the folder the Battle.net container has as drive A:.
- The DXVK and `ntdll` master copies for the DLL scripts (above).
- wowgo.sh's lock file, `launch.guard`, and its backups in `backups/compat`.

## The launcher tiles

Two tiny Android apps give the launchers home-screen icons:

- [launcher/android/wowlaunch/](../launcher/android/wowlaunch/): `com.ff.wowlaunch`, with one launcher icon per flavor (`.Retail`, `.Classic`, `.Beta`). Each runs `wowlaunch.sh <flavor>` as root.
- [launcher/android/wowspan/](../launcher/android/wowspan/): `com.ff.wowspan`, "WoW Dual Screen", the picker above. It runs wowgo.sh. Before the picker it ran [launcher/scripts/wowspan.sh](../launcher/scripts/wowspan.sh), which is still in the repo. wow_mirror.py doesn't copy that one, so put it at `/data/adb/wow/wowspan.sh` yourself if you use it.

Build them with the `build.sh` in each folder, from Git Bash on Windows (they call the `.exe` and `.bat` Android build tools). They need `JAVA_HOME` (JDK 17) and `ANDROID_HOME` set, with build-tools 35.0.0 and platform 35 for wowlaunch, 36.0.0 and platform 36 for wowspan. No Android Studio. The picker's `build.sh` here is a cleaned-up copy of the one I use. On 1 October 2026 I built both apps from a clean copy of this repo, without the picker's pictures or icon. I didn't install those test builds.

## PC-side tools

All in [tools/](../tools/). They talk to the Thor over adb. Set `ADB` if `adb` isn't on your PATH, and `THOR_SERIAL` to the device. Most of them also read `THOR_ADB`. gn_patch_container.py reads only `THOR_SERIAL` and otherwise picks the first AYN Thor that adb lists.

- [wow_mirror.py](../tools/wow_mirror.py) `push` copies the config files, the launcher script and my addons to the device, and seeds the shared saved variables once. It refuses while WoW is running. `launch <flavor>` runs the launcher from the PC.
- [wow_flavor.py](../tools/wow_flavor.py) is the older by-hand flavor switch. `wow_mirror.py launch` replaced it, and it only runs with `--legacy` because it pins an old driver.
- [wow_controls.py](../tools/wow_controls.py) applies and checks the controller settings.
- [stage_flavor.py](../tools/stage_flavor.py), [wow_arm64.py](../tools/wow_arm64.py) and [wow_sync.py](../tools/wow_sync.py) copy the game and keep it in step with the PC after a patch ([game-client.md](game-client.md)).
- [gn_patch_container.py](../tools/gn_patch_container.py) edits a GameNative container file as root and always leaves a backup. It force-stops GameNative before it writes.

## Checking whether WoW is running

Match the process **name** (`ps -A -o NAME`) against `wow[a-z]*-arm64\.exe$`. Don't match the arguments. After a clean exit, GameNative's `explorer.exe` and `winhandler.exe` stay up with the game's path in their arguments, and an arguments match says the game is still running.
