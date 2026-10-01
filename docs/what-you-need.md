# What you need

## What I used

- **AYN Thor** (Snapdragon 8 Gen 2, Adreno 740 GPU, two screens). Mine is rooted with Magisk.
- **GameNative 1.2.1**, `gamenative-v1.2.1.apk` from its release page. That's the standard download, built from GameNative's legacy flavor (`targetSdk 28`). The other file on that page, `-legacy-xr`, is the build for VR headsets.
- **A Windows PC with Battle.net** and the game installed. I copy the game data from it to the Thor.
- **A Linux PC** for building the Wine, Turnip and DXVK pieces. I don't provide the built files, so you build them yourself ([quick-path.md](quick-path.md)).
- **adb** on the PC.
- **A World of Warcraft account.** Retail ran on a free trial account for me. I haven't tried Classic on one.
- **Storage.** Free space on the Thor for the game, as much as its `Data/` and `_retail_/` folders take on your PC. The game lives on the Thor at `/storage/emulated/0/Games/WoW`.

Copying was not the slow part for me. On my network, adb over Wi-Fi measured 56 MB/s to the Thor. The Battle.net download on the PC took longer.

## Which pieces need root

My own setup is rooted. I first got the Wine side working by copying files into GameNative's private data as root. Later I packaged the same files so GameNative can import them itself, and tested that without root, as far as the login screen ([quick-path.md](quick-path.md)).

| Piece | Needs root? | Why |
|---|---|---|
| Copying the game to `/storage/emulated/0/Games/WoW` | No | Shared storage. |
| Adding WoW as a custom game in GameNative | No | GameNative's own UI. |
| Addons (FFScale, FFBinds, FFSpan) and the `WTF` config files | No | They live in the game folder on shared storage. |
| The rebuilt proton-10, with patched `ntdll.dll` and `winevulkan.dll` | No, imported as a `.wcp` you build | Imported in GameNative's Wine/Proton Manager. GameNative builds the game's Wine prefix from it, patched `ntdll.dll` included. My own setup copied these in as root. |
| Pure ARM64 DXVK DLLs | No, imported as a `.wcp` you build | GameNative copies DXVK into the game's prefix on every launch. With the imported DXVK selected, it copies the ARM64 ones. My own setup uses a Magisk boot script that checks them every 0.3 s and copies them back when they differ. |
| Custom Turnip driver | No, imported as a `.zip` you build | Imported in GameNative's Driver Manager, it stays selected. A driver copied in by hand and pinned by editing the container file only lasted one launch for me, because GameNative rewrote that file on exit. My launcher re-pins it every launch as root. |
| The launcher tiles and scripts in [launcher/](../launcher/) | Yes | They edit GameNative's container file and run in the global mount namespace (`su --mount-master`). |
| The "WoW Dual Screen" picker app and its backend | Yes | The app runs its backend script with `su --mount-master` ([launcher.md](launcher.md)). |
| Battle.net on the Thor, the way I did it | Yes | I replaced `wineserver` in an installed Wine with the patched build, as root ([battle-net.md](battle-net.md)). I haven't tried importing a Wine package that has it. |
| Installing the dual-screen fork | No | An APK you build yourself from the patches ([dual-screen.md](dual-screen.md#getting-it-on-the-device)). My dual-screen setup still copies the DLLs as root. The fork has the same import menus. I imported the three files into the Span Test build (patch 12) and reached the login screen, but not into my main `span` build ([dual-screen.md](dual-screen.md#without-root-experimental)). |
| Dual screen with the no-root test build (fork patch 12, Span Test) | No, experimental | Span mode is on by default, and the only dual-screen setting is **Screen Size** in the app's own **Edit container**. On my device it reached the login screen without root, 3 of 3 times. During login the bottom screen showed AYN's own control panel instead of black. I haven't played it in the world ([dual-screen.md](dual-screen.md#without-root-experimental)). |

## One Magisk setting that mattered

When the Thor loads into the game world it briefly runs out of memory, and Android's low-memory killer kills anything that isn't in the foreground. Once, it killed the Magisk app while Magisk was logging a root request. Magisk then opened its own window over the game, which pushed the game into the background, and the game was killed too.

After that I turned off logging and notifications on every Magisk root policy, so Magisk never needs to open its app during a root request.
