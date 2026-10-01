# Ban risk: what I know and what I don't

I can't tell you this is safe. Nobody outside Blizzard can. This page lists what is modified, what I found in public sources, what I don't know, and what I do on my own account. Sources are linked in [research.md](research.md).

## What is modified, measured on my device

| File | Where | Change |
|---|---|---|
| `ntdll.dll` | Wine install and Wine prefix | On my original build: 1,034 bytes of 6,340,608 changed (the dispatcher pin and the unwind guard). On the rebuilt Wine I run now, and in the package my release script builds: 968 bytes, the dispatcher pin only ([wine.md](wine.md)). |
| `winevulkan.dll` | Wine install and Wine prefix | 29 bytes (assert replaced with an error return). |
| `crypt32.so` | Wine install (the Unix side of crypt32) | Rebuilt from source with the double-close fix ([wine.md](wine.md)). |
| `wineserver` | Wine install, on the Wine I use for Battle.net | Rebuilt from source with the shared-storage ownership patch ([wine.md](wine.md)). |
| DXVK DLLs | Wine prefix `system32` | Built from upstream source, in the place Proton normally puts them. |
| The game executable | Game folder | Unmodified. The beta exe's md5 matched the copy Battle.net installed on my PC. The retail exe is the file TACTTool pulled, unchanged. |
| The game folder | Game folder | Only Blizzard's own DLLs. No proxy DLLs. |

The anti-tamper still runs. The `ntdll` patch changes where the syscall stubs in its private copy of `ntdll` look for Wine's dispatcher, so they stop calling address 0. It doesn't skip or disable any check.

## What I found in public sources

- Wine ships its own implementation of `ntdll.dll` ([its source](https://gitlab.winehq.org/wine/wine/-/tree/master/dlls/ntdll)), not Microsoft's file. So anyone playing through Wine or Proton already runs an `ntdll` that differs from the one on Windows.
- Valve's Proton has shipped deep `ntdll` changes (fsync, esync) for years. wine-staging carried an `ntdll` syscall-emulation patch set up to version 11.4 and dropped it in March 2026. GameNative's proton-wine carries its own arm64ec patches to `ntdll`, on top of Proton's.
- Public reverse-engineering notes on Warden describe it hashing regions of WoW's own code and checking loaded modules against known cheat tools. Those notes are from 2008 (client 2.4.3). I found nothing saying Warden checks system DLLs like `ntdll`. That doesn't mean it doesn't: its scans are pushed by the server and can change.
- A reply on Blizzard's EU forum (poster Meadow, 22 May 2025): "You'll likely not get banned for merely using SteamOS or Linux. Any programs that may be used for cheating though, will still be detected nonetheless." The poster is a forum MVP, not Blizzard staff.
- In November 2006 some Linux players using Cedega (a Wine-based product) were banned for "Use of Third Party Automation Software". After an investigation with the Cedega developers, Blizzard lifted those bans as an error, reported as tied to one Cedega build, and compensated the affected players with free play time.
- On 14 July 2025, build 11.1.7.61965 refused to start with a `dxgi.dll` in the game folder (where ReShade installs), with the error "Your 3D accelerator card is not supported". According to the ReShade forum, build 11.1.7.61967 about an hour later allowed it again. My game folder has no `dxgi.dll`.
- Illustrious-Cat-4281, who ran Classic on a Thor through GameHub Lite, wrote on 17 September 2026 that they had tested for a couple of weeks on Blizzard's servers without a suspension ([post](https://www.reddit.com/r/AynThor/comments/1wj4b5r/wow_classic_native_on_blizzard_servers/)). One person's report.
- I searched for cases of anyone banned because a Wine or Proton binary was modified, as opposed to running an actual cheat. I didn't find any.

## What I don't know

- **Whether Blizzard treats Android this way.** When I started, I believed this was the first retail login from Android. It wasn't: FrontMage's winlator-llm ran retail in a Reddit post from 27 July 2026, Illustrious-Cat-4281 posted Classic on a Thor on 17 September 2026, and my first retail login was on 20 September 2026. Either way, there's very little history.
- **The GPU name is unusual.** The game sees `Wrapper(Turnip Adreno (TM) 740)`. "Wrapper" and "Turnip" are strings I wouldn't expect a Windows-on-ARM PC to report. I have no evidence Blizzard acts on this, but it is a visible difference.
- **The Classic beta.** In September 2026 a player on r/wow reported an unexplained ban on the "Forever" beta. Their post also mentions long repetitive farming, a VPN and an overlay, so the cause isn't clear. Beta enforcement isn't documented.

## Three things I did that you should know about

1. **The ARM64 executable came from TACTTool, not Battle.net.** See [game-client.md](game-client.md). Blizzard's terms mention access through unauthorized third-party software. This is Blizzard's own file for a game on an account I own, and Battle.net offers no way to get it on an x86 PC. It might still count.
2. **Early on, I drove a character with scripted input for a few seconds while testing the controller**, on a free trial account. Blizzard's terms prohibit automation software. Nothing in this repo sends input to the game, and I don't do that anymore.
3. **Battle.net on the Thor reads install records my tool wrote.** [tools/battlenet/wow_productdb.py](../tools/battlenet/wow_productdb.py) writes the records Battle.net keeps about installed games, so it finds the game I copied from the PC. With `--arm64` it changes the installed tag in them from `Windows x86_64` to `Windows arm64`. Battle.net itself is unmodified. These are Battle.net's own files, edited by a tool that isn't Blizzard's, so it might count the same way TACTTool might ([battle-net.md](battle-net.md)).

## What I do on my own account

- Play only with my own hands. No scripted input while logged in.
- No VPN. My Thor runs Tailscale. Since 24 September 2026 GameNative and my fork are excluded from it in Tailscale's app settings, after Android killed Tailscale during a load and took the game's connection with it ([troubleshooting.md](troubleshooting.md)). Before that, the game's traffic went straight out over Wi-Fi only because no exit node was selected. I checked the routing on the device. An exit node would have taken the game's traffic without any warning. I checked before logging in: `ip route show table tun1 | grep -c default` should print 0 (as root).
- No overlays.
- No DLLs or executables in the game folder except Blizzard's. The only other files there are addons and `WTF` config. I re-check after every patch.
- Retail, MoP Classic and, since 24 September 2026, the Forever beta.
- I tested on a free trial account before using my real one.
