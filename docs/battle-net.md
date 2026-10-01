# Battle.net on the Thor

What I wanted: a way to log in on the Thor while Blizzard's servers refused logins typed into the game's own login screen.

For most of 24 September 2026, every login I typed into WoW's own login screen failed with "You have been disconnected (BLZ51914403)". WoW's `Logs/Aurora.log` showed the server refusing the login form before the password was sent. It failed the same way on my PC, and pressing Play in the Battle.net launcher on the PC logged in. So that day only launcher-started sessions got in. That evening typed logins worked again: a normal password login reached Forever's character select at 22:44.

While it was blocked I got Blizzard's own Battle.net app running on the Thor inside GameNative, and its Play button started the native ARM64 client. This page is what that took and what I measured. Every result here is from my own device. The setup files are in [tools/battlenet/](../tools/battlenet/README.md) and the launch side is in [launcher/scripts/](../launcher/scripts/README.md) (see [launcher.md](launcher.md)).

## What it needs

I didn't find an ARM64 build of the Battle.net app. The Windows app is 32-bit x86, so it runs through one of GameNative's x86 translators. Wine picks the translator per process from `HODLL` in the Windows environment, so a batch file can choose it for each program it starts.

- **Its own container.** Battle.net has its own GameNative container on my install (my install's id `1835007374`), with the WoW folder as drive B:. I first tried my original WoW container. There, the DLL overrides I use for the ARM64 DXVK stopped the 32-bit Battle.net Agent from starting (`dxgi.dll` not found), and I didn't find the cause.
- **The installer under Box64.** Under FEX, Blizzard's `Battle.net-Setup.exe` died about 15 ms in with a stack overflow and wrote nothing. Under Box64 it installed in about 2 minutes. [bnet-setup.bat](../tools/battlenet/bnet-setup.bat) runs it under Box64, closes Battle.net, and starts it again under FEX.
- **The app under FEX.** Under Box64 the app's built-in browser failed TLS and the sign-in page stayed blank. Under FEX the sign-in page loaded. [launch-bnet.bat](../tools/battlenet/launch-bnet.bat) is the container's `launch.bat` and starts Battle.net under FEX.
- **DXVK for both architectures.** The ARM64 DXVK package only has ARM64 DLLs, so the 32-bit Battle.net got Wine's built-in stubs and its window stayed blank. [provision_graphics.py](../tools/battlenet/provision_graphics.py) gives the container the ARM64 DXVK in `system32` for WoW and GameNative's 32-bit DXVK 2.7.1 in `syswow64` for Battle.net. It also sets `HardwareAcceleration` to `"false"` in Battle.net's settings file, after a backup. With both in place Battle.net drew its whole window. In my first test container, without the 32-bit DXVK, that same setting left the page blank.
- **The wineserver patch.** [wineserver-android-shared-owner.patch](../patches/proton-wine/wineserver-android-shared-owner.patch). Every Battle.net start ran an update of WoW, and it failed with `Unable to create game subfolder`. Before it writes, the Agent checks the folder's security. Wine maps any file whose Linux owner isn't the current user to Anonymous Logon, and every file on Android's shared storage reports the media provider as its owner, so the prefix user never owned anything in the game folder. The patch treats the owner of files on that storage as the current user, and doesn't fail a security write when Android refuses the `chmod`. With it the update ran and Play came up. The update touched only `.flavor.info`, `Utils` and `.battle.net/` in the game folder. The game's exe, `Interface`, `WTF` and `Cache` weren't changed. I built `wineserver` with the patch and replaced the one in my Wine package. [tools/proton/build.sh](../tools/proton/build.sh) doesn't apply it, so it has to go into the Wine tree by hand ([patches/README.md](../patches/README.md)).
- **[wow_productdb.py](../tools/battlenet/wow_productdb.py).** My WoW folder on the Thor is a copy from my PC ([game-client.md](game-client.md)), not a Battle.net install. Battle.net's Scan and Locate didn't find it, because the Agent needs a `.product.db` file in the install folder and my copy didn't have one. The script runs on the PC and writes the records the Agent would have written, from the PC install's records: the Agent's own `product.db` and the install's `.product.db`. Stop Battle.net first, because the Agent rewrites its file. `--arm64` changes the installed tags from "Windows x86_64" to "Windows arm64". After that the Agent listed Retail, Classic and Forever as installed, with their ARM64 exes.

Sign-in is by hand inside Battle.net. "Keep me logged in" kept me signed in across restarts.

My setup uses root: provision_graphics.py and the picker app's backend run as root. I haven't tried this route without root.

## How Play starts the game

On 24 September, Play in Battle.net started `Wow-ARM64.exe -launcherlogin -uid wow` about 5 seconds later. That's the native ARM64 client, and Battle.net picked it itself. The first time, the login ended with WOW51900319 (see the VPN trap below). After the VPN fix I pressed Play at 16:07 and was in the world at 16:09, on one screen.

The picker app has a Battle.net mode ([launcher.md](launcher.md)). In that mode [wowgo.sh](../launcher/scripts/wowgo.sh) starts the Battle.net container in the dual-screen fork and follows the log of the running Battle.net. It shows "Finish signing in to Battle.net" until Battle.net logs a successful sign-in, then waits until Battle.net reports the flavor playable. At least 15 seconds after sign-in it asks GameNative's `winhandler.exe` to run a small batch file, and that batch file runs the already-running Battle.net with `--exec="launch WoW"` (`WoWC` for Classic, `WoWF` for Forever). For Forever it first selects the Forever product. [make_launch_packets.py](../launcher/scripts/make_launch_packets.py) writes those requests and batch files. Nothing in it makes or reuses login tokens, so Battle.net has to be signed in already.

On 24 September that one-tap route reached the world in dual screen on Classic, Retail and Forever.

## What I measured

| Thing | What I saw |
|---|---|
| `--exec` on the first start | Starting Battle.net with `--exec="launch WoW"` broke it. It jumped to the WoW page mid-load, the page never finished, and the launch waited behind the update pass. Starting it plain and sending the launch to the running Battle.net later worked. That's why wowgo.sh waits. |
| Main page | Drew about 60 seconds after a plain start. |
| Update pass | On every start: an update of `wow` for about 1 to 1.5 minutes, then `wow_classic` for about 1 minute, with nothing downloaded. Play came up after the `wow` pass. The first pass after the wineserver patch did download files (63 MB for Classic). |
| Renderer | Battle.net's browser renderer crashed every 4 to 6 minutes ("Render process was terminated and reloaded"), and sometimes didn't draw again. A launch queued at that moment was canceled. I measured this in my first test container, before the DXVK change above. |
| Memory | Battle.net held about 1.7 GB while WoW was loading. |
| `GameLaunchWindowBehavior` | `"Client.GameLaunchWindowBehavior": "2"` in `Battle.net.config` is "exit Battle.net completely" when a game starts. With it, every Battle.net process was gone about 15 seconds after WoW started. I checked this once. |
| Saved sign-in | After I force-stopped Battle.net several times, its saved sign-in was rejected ("login session expired") and I had to sign in again. Seen once. |
| Show-password button | Tapping it before Log in made the form send an empty password. Seen once. |

## The VPN trap

The first launcher login on the Thor ended with WOW51900319 (disconnected). The server sent the character list and the connection dropped 28 ms later. Android's log showed why. Memory ran critically low while WoW loaded, with Battle.net holding about 1.7 GB, and Android's low-memory killer killed my VPN app (Tailscale). When the VPN went away, Android destroyed every socket tagged with it. Android tags every app's sockets with the VPN's network, even when the VPN doesn't route that traffic, so the game's connection went too. Battle.net logged its own socket closed 200 ms later. I saw this once.

The fix was in the VPN app's split tunneling setting: I excluded the GameNative apps from the VPN. The next Play got me into the world. If a VPN runs on your Thor, that exclusion is the first thing I'd check after a WOW51900319.

## What I'm not sure of

- Why Battle.net runs an update pass on every start.
- Whether Battle.net can take over game patches on the Thor. Its first update pass wrote 63 MB for Classic, but I haven't watched it install a new game version.
- How often the renderer crashes with the DXVK change.
- Why the 32-bit Agent couldn't start in my original WoW container.
