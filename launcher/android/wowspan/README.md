# WoW Dual Screen (com.ff.wowspan)

A small Android app with three tiles (Retail, Classic, Forever) and a Direct / Battle.net switch. It needs root. A tap runs `/data/adb/wow/wowgo.sh <flavor> <mode> <request id>` as root through `su --mount-master` and the app shows the progress lines that script reports. The script's source is [launcher/scripts/wowgo.sh](../../scripts/wowgo.sh), described in [launcher/scripts/README.md](../../scripts/README.md).

It only runs the backend. Without `/data/adb/wow/wowgo.sh` on the device it shows "Launcher preparation is not installed".

## Building

Set `JAVA_HOME` to a JDK 17 and `ANDROID_HOME` to an Android SDK with build-tools 36.0.0 and platform android-36, then run `build.sh`. It uses the bare SDK tools, no Gradle. I wrote it for Git Bash on Windows, so it calls `javac.exe`, `d8.bat`, `aapt.exe`, `zipalign.exe` and `apksigner.bat`. On Linux or macOS drop those suffixes.

It signs with `~/.android/debug.keystore` and creates that key if it doesn't exist. Android only updates an installed app signed with the same key, so an older build signed with another key has to be uninstalled first.

## Files you supply

None of these are in this repo. All three are optional and the app builds and runs without them.

| File | What it is | Without it |
|---|---|---|
| `assets/retail.jpg`, `assets/classic.jpg`, `assets/beta.jpg` | The tile pictures. Mine are game art, so they aren't here. | Plain dark tiles with the title text |
| `res/drawable/app_icon.png` | The launcher icon. Mine isn't here because I don't know where it came from. | `build.sh` builds from a copy of the manifest without the icon line and Android shows its default icon |
| `assets/heading.ttf` | A font for the headings | A bold serif |

The pictures are drawn cropped to fill the tile, top-aligned, so any landscape or portrait image works.
