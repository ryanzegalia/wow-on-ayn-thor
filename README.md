# World of Warcraft on the AYN Thor

My notes on getting World of Warcraft to run natively on my AYN Thor, and on making it use both screens.

This is a guide, not a product. I built it for myself and I'm sharing how I did it in case it's useful to someone else.

## Credits

I didn't make the software this runs on. I took what other people built and modified it to do what I wanted. None of it works without them.

- [GameNative](https://github.com/utkarshdalal/GameNative), built on [Winlator](https://github.com/brunodev85/winlator). The Android app that runs the game.
- [Wine](https://www.winehq.org/), [Proton](https://github.com/ValveSoftware/Proton), and GameNative's [proton-wine](https://github.com/GameNative/proton-wine) build, including its arm64ec patch set.
- [Mesa](https://gitlab.freedesktop.org/mesa/mesa) Turnip, the open source Vulkan driver for Adreno GPUs.
- [DXVK](https://github.com/doitsujin/dxvk), built with [llvm-mingw](https://github.com/mstorsjo/llvm-mingw).
- [ConsolePort](https://github.com/seblindfors/ConsolePort) and [Immersion](https://github.com/seblindfors/Immersion), the controller and dialogue addons the UI sits on.
- [TACTSharp](https://github.com/wowdev/TACTSharp) (TACTTool), used to fetch Blizzard's ARM64 game executable.
- [Magisk](https://github.com/topjohnwu/Magisk), for root.

Every upstream, its license, and exactly what I changed: [CREDITS.md](CREDITS.md).

## What I wanted

1. Retail WoW on the Thor, running on the device, not streamed from a PC.
2. The built-in controller working, with one button layout across Retail and Classic.
3. The game on the top screen and the UI (bags, map, chat, quest tracker) on the bottom touchscreen.

## What works on my device

| Thing | Status |
|---|---|
| Retail 12.1.0 (ARM64 client) logs in and plays on live servers | Works. I tested it on a free trial account first, then on my own account. |
| Cold start reaches the login screen, my rooted setup | 8 of 8 cold starts after the Wine rebuild. Before it, about half hung. |
| The same files without root, imported through GameNative's own menus ([quick path](docs/quick-path.md)) | 3 of 3 cold starts reached the login screen on a new game entry in the standard GameNative 1.2.1. I didn't log in from that entry. |
| Mists of Pandaria Classic 5.5.4 | Works, same setup, same controls. |
| Classic beta ("Forever") | Logs in and plays, in dual screen, since 24 September 2026. See [docs/ban-risk.md](docs/ban-risk.md). |
| Built-in controller, one layout for all flavors | Works. |
| Dual screen, first version: game centred on top, two side strips on the bottom | Worked on my device, with fork patches 01 to 09 and an earlier FFSpan (2.0.0, not in this repo). The home-screen layout replaced it. |
| Dual screen, current version: game on the top screen, a "home screen" on the bottom with quest tracker, minimap, always-open bags and chat that dims when idle, and WoW's windows opening over it | In the world on Retail, MoP Classic and the Forever beta. On 25 September 2026 I checked FFSpan 2.9.0 and FFBinds 1.8.4 in the world on all three. FFScale 1.11.0 went on after that check. Some things are still open, listed in [dual-screen.md](docs/dual-screen.md). It uses third-party addons you get yourself. |
| The "WoW Dual Screen" picker app: pick Retail, Classic or Forever, and it prepares and starts that flavor in dual screen, with the game's own login or through Battle.net | Works for all three flavors. It needs root ([launcher.md](docs/launcher.md)). |
| The real Battle.net app running on the Thor | Its Play button started `Wow-ARM64.exe`, and I logged in and played on one screen on 24 September 2026. Later that day it started all three flavors in dual screen through the picker. See [battle-net.md](docs/battle-net.md). |

Performance: I have not measured frame rates in a way I'd publish.

Dual screen on my Thor, from an earlier version of the home layout (details in [dual-screen.md](docs/dual-screen.md)):

![The Thor's two screens stacked. Top: WoW in the world with ConsolePort's controls. Bottom: quest tracker, minimap and bags.](docs/images/dual-screen/on-device-early-home.png)

## What is rooted

My own setup is rooted with Magisk, because that's how I got it working the first time. The game itself doesn't need root anymore: the Wine, DXVK and driver files can be imported through GameNative's own menus, and GameNative kept them selected for me. That's the [quick path](docs/quick-path.md). My launcher scripts, the picker app and my dual-screen setup still use root. A test build of the fork started in dual-screen mode and reached the login screen without root, 3 of 3 times ([dual-screen.md](docs/dual-screen.md#without-root-experimental)), but I haven't logged in with it or seen the home screen in the world. The full table is in [docs/what-you-need.md](docs/what-you-need.md).

## The guide

Start with the [quick path](docs/quick-path.md) if you just want retail running on one screen. The pages below are the long version: what I found, what I changed and why.

1. [What you need](docs/what-you-need.md)
2. [Getting the ARM64 game client](docs/game-client.md)
3. [Wine: the four fixes](docs/wine.md)
4. [Graphics: DXVK and the Turnip driver](docs/graphics.md)
5. [Controls and UI](docs/controls-and-ui.md)
6. [Dual screen](docs/dual-screen.md)
7. [Launcher and scripts](docs/launcher.md)
8. [Battle.net on the Thor](docs/battle-net.md)
9. [Ban risk: what I know and what I don't](docs/ban-risk.md)
10. [Troubleshooting](docs/troubleshooting.md)
11. [Research: what I looked at and what I found](docs/research.md)

## Other people running WoW on handhelds

- **Illustrious-Cat-4281** posted WoW Classic running on a Thor against Blizzard's servers on 17 September 2026, through GameHub Lite, and explained in a reply the next day that it uses the ARM64 build Blizzard ships with each release. That thread is where I learned the ARM64 build existed. It's the route this whole guide uses. [The post](https://www.reddit.com/r/AynThor/comments/1wj4b5r/wow_classic_native_on_blizzard_servers/).
- **FrontMage** made [winlator-llm](https://github.com/FrontMage/winlator-llm), a Winlator fork that runs retail WoW through the official Battle.net client. The r/EmulationOnAndroid post showing it, on 27 July 2026, links FrontMage's GitHub. [The post](https://www.reddit.com/r/EmulationOnAndroid/comments/1v7of42/).
- **BryTheGuy06** was working on the same thing at the same time, on a Retroid Pocket 6 through GameHub Lite. They posted Classic Era and the Forever beta running on 20 September 2026 ([their comment](https://www.reddit.com/r/AynThor/comments/1wj4b5r/comment/pb02xuj/)) and a post on 23 September linking their draft setup guide ([their post](https://www.reddit.com/r/retroid/comments/1wobe1u/i_got_wow_forever_beta_running_on_the_rp6_with/)). They hit the same three problems I did: ARM64EC DXVK, WoW's copied syscall stubs, and a Turnip shader-compiler hang. I fixed them separately, over the same days.
- **jaredgei** made [wow-forever-android](https://github.com/jaredgei/wow-forever-android) (GPL-3.0), a standalone app for the Forever beta built on a stripped-down GameNative 1.2.1, with the Wine, DXVK and Turnip files from BryTheGuy06's Retroid Pocket 6 setup. Its README lists the AYN Thor as tested. Reddit user Buns4 posted it on r/AynThor on 1 October 2026. [The post](https://www.reddit.com/r/AynThor/comments/1wupt0w/wow_forever_standalone_apk_for_ayn_thor/).

My first retail login on the Thor was 20 September 2026. More detail on each in [docs/research.md](docs/research.md).

## How this was built

I built this with AI-assisted development (Claude). The investigation, the patches, the addons and these notes were all done that way. I tested them on my own device, except where a page says I haven't yet. It has only been tested on one AYN Thor, so treat everything here as notes from one setup. More detail: [docs/how-this-was-built.md](docs/how-this-was-built.md).

I haven't sent any of these changes upstream ([why](docs/how-this-was-built.md)). Everything is here if someone who knows these codebases wants to look.

## What's not in this repo

- The built Wine, DXVK and driver files. I don't provide them. [tools/release/make_release.sh](tools/release/make_release.sh) is how I packaged them, from builds made with [tools/proton/](tools/proton/), [tools/dxvk/](tools/dxvk/) and [tools/turnip/](tools/turnip/).
- No Blizzard files. You need your own account and your own copy of the game.
- No APK. The dual-screen app is a GameNative fork. Its source changes are in [patches/gamenative/](patches/gamenative/), and you build the app yourself from them ([dual-screen.md](docs/dual-screen.md#getting-it-on-the-device)). GameNative contains closed-source parts I don't have the right to redistribute, and an APK built from it includes them, unless it's built with the extra series in [patches/gamenative-standalone/](patches/gamenative-standalone/), which removes them ([patches/README.md](patches/README.md)). The picker app is source only too, in [launcher/android/wowspan/](launcher/android/wowspan/).
- No third-party addons. ConsolePort, Immersion, Glassy, Baganator, Syndicator, Leatrix Maps and Talent Tree Tweaks are other people's work, and several don't allow redistribution. Get them from their own pages, linked in [CREDITS.md](CREDITS.md). [tools/addons/check_addons.py](tools/addons/check_addons.py) checks your copies against the versions I tested ([how](docs/dual-screen.md#checking-the-versions-i-tested)). [patches/addons/](patches/addons/README.md) has small fixes to ConsolePort and Glassy that my launcher makes on launch.
- No Offhand addon. I used it early on for the dual-screen UI. Its license doesn't allow redistribution or public derivatives, so it isn't here, and the current layout doesn't use it.

## License

My own files (addons, scripts, tools, the text of the docs) are MIT, see [LICENSE](LICENSE). The screenshots in [docs/images/](docs/images/) aren't covered: they show Blizzard's game and GameNative's app. Patches to other projects, and the files built from them, keep those projects' licenses: GameNative GPL-3.0, Wine and proton-wine LGPL-2.1-or-later, Mesa MIT, DXVK zlib, and the addon fixes their addons' licenses. See [CREDITS.md](CREDITS.md).

World of Warcraft is a trademark of Blizzard Entertainment. AYN and Thor are AYN's. This project isn't affiliated with or endorsed by either.
