# Research: what I looked at and what I found

This is the outside reading behind these notes. Anything I measured on my own device is on the other pages. Anything here is from a source, linked.

## Has anyone done this before?

- **Illustrious-Cat-4281, r/AynThor, ["WoW classic native on Blizzard servers"](https://www.reddit.com/r/AynThor/comments/1wj4b5r/wow_classic_native_on_blizzard_servers/) (17 September 2026).** WoW Classic Anniversary running on a Thor on Blizzard's servers, through GameHub Lite with a customized DXVK and ConsolePort. In a reply on 18 September they explained it uses the ARM64 build of WoW that Blizzard ships each release, so Wine runs it with no CPU translation. They also wrote that they had been testing for a couple of weeks without a suspension. This is where I learned about the ARM64 build.
- **FrontMage ran retail WoW on Android before me.** FrontMage made winlator-llm, a Winlator fork that runs retail WoW through the official Battle.net client (an x86 program, so it runs under FEX emulation). It was posted to r/EmulationOnAndroid on 27 July 2026, and the post links FrontMage's GitHub. My first retail login was 20 September 2026. I couldn't tell from the post or the repos whether the game itself runs as the x86 or the ARM64 executable. They describe fixing FEX, Wine/ARM64EC, DXVK, Turnip and the Android Vulkan wrapper, and say the project was built with an LLM-assisted workflow.
  - Repo: [FrontMage/winlator-llm](https://github.com/FrontMage/winlator-llm) (MIT, APK in its releases)
  - Post: [r/EmulationOnAndroid, "World of Warcraft Retail Is Running on Android! | Official Battle.net, No Streaming"](https://www.reddit.com/r/EmulationOnAndroid/comments/1v7of42/) (27 July 2026)
  - Video: [YouTube](https://www.youtube.com/watch?v=FjyuUxPZ3Fg)
  - On 20 September 2026 the same poster wrote on Reddit that GameHub had adopted some of their fixes. I haven't checked whether GameHub runs WoW now.
- **BryTheGuy06, a Retroid Pocket 6 owner, in the same r/AynThor thread ([comment](https://www.reddit.com/r/AynThor/comments/1wj4b5r/comment/pb02xuj/), 20 September 2026).** They got Classic Era and then the Forever beta running through GameHub Lite. Their comment says the ARM64 client couldn't load GameHub's ARM64EC DXVK, so they built plain ARM64 DXVK 2.4.1 and patched Proton 11's Wine to handle WoW's copied ARM64 syscall stubs. Forever then crashed at the photosensitivity warning, which they traced to Turnip's shader compiler "getting stuck waiting for instructions in a later block" and fixed with "a patch to that scheduling check". They reported about 60 FPS for about 10 minutes, unchanged game files, and that they did it with ChatGPT through Codex. Those are the same three problems I hit. I found and fixed them separately over the same days: the ARM64 DXVK build and the two `ntdll` fixes on 19 September, the Turnip fix on 20 September.
  - On 23 September they posted a setup guide ([r/retroid post](https://www.reddit.com/r/retroid/comments/1wobe1u/i_got_wow_forever_beta_running_on_the_rp6_with/)): GameHub Lite 5.1.8, a custom Wine runtime, plain ARM64 DXVK and a patched Turnip driver. They say the custom files aren't packaged for download yet.
- **jaredgei, [wow-forever-android](https://github.com/jaredgei/wow-forever-android) (GPL-3.0), posted to r/AynThor by Reddit user Buns4 ([post](https://www.reddit.com/r/AynThor/comments/1wupt0w/wow_forever_standalone_apk_for_ayn_thor/), 1 October 2026).** Its README describes a standalone Android app (package `app.wowforever`) built on a stripped-down GameNative v1.2.1, for the Forever beta. It uses Proton 11 ARM64EC, DXVK 2.4.1 for aarch64 and a patched Turnip from what it calls "the WoW Forever RP6 community bundle", which the Reddit post credits to BryTheGuy06's work, and it downloads the ARM64 client from Blizzard's CDN. It lists the AYN Thor as tested.
- **GameHub Lite**, the app Illustrious-Cat-4281 and BryTheGuy06 used, is a community-modified build of GameHub. Its repo has no license file and says it's "for educational and personal privacy purposes only" ([repo](https://github.com/Producdevity/gamehub-lite)). I didn't use it.
- **Before those,** everything I found about WoW under Winlator or GameNative was about private servers, not Blizzard's.

## Game client

- All four WoW products I checked ship a native ARM64 executable. I checked this myself by pulling each one with [TACTSharp](https://github.com/wowdev/TACTSharp)'s TACTTool and reading the PE header ([game-client.md](game-client.md)).

## DXVK on ARM64

- The DXVK builds I found for Android handhelds were ARM64EC or regular x86 builds, not plain ARM64. For example [Arihany/WinlatorWCPHub](https://github.com/Arihany/WinlatorWCPHub) packages DXVK as ARM64EC builds for FEX next to regular builds for Box64.
- A request for ARM64EC/ARM64X builds on the DXVK tracker was closed as not planned: [doitsujin/dxvk issue 5423](https://github.com/doitsujin/dxvk/issues/5423).

## Blizzard: terms, policies, statements

- [Blizzard legal documents](https://www.blizzard.com/en-us/legal/) (End User License Agreement and Terms). Relevant parts: the prohibition on automation software, the mention of access through unauthorized third-party software, and the statement that the platform may monitor memory for unauthorized third-party programs.
- [UI Add-On Development Policy](https://us.forums.blizzard.com/en/wow/t/ui-add-on-development-policy/24534): addons must be free and their code must not be obfuscated. My addons are free and plain Lua.
- [EU forum thread, "Is there a risk of ban for running on Linux? VM, Wine, anything else?"](https://eu.forums.blizzard.com/en/wow/t/is-there-a-risk-of-ban-for-running-on-linux-vm-wine-anything-else/573892): the reply quoted on [ban-risk.md](ban-risk.md), 22 May 2025.
- Cedega bans, November 2006: [Slashdot, bans reported](https://slashdot.org/story/06/11/15/1652222/linux-users-banned-from-world-of-warcraft), [Techgage, bans lifted](https://techgage.com/news/blizzard_unbans_linux_world_of_warcraft_players/), [Blue Tracker thread](https://www.bluetracker.gg/wow/topic/us-en/48667165-so-linux-users-*were*-unfairly-banned-gg/).
- ReShade `dxgi.dll` block, July 2025: [ReShade forum](https://reshade.me/forum/troubleshooting/10065-world-of-warcraft-blocking-reshade-dxgi-dll-after-7-14-2025-11-1-7-61965-patch), [Blizzard forum](https://us.forums.blizzard.com/en/wow/t/reshade-post-processing-filter-app-now-blocked-after-7142025-111761965-hotfix-patch/2132149).
- Forever beta ban report: [r/wow, "Banned from WoW: Forever Beta"](https://www.reddit.com/r/wow/comments/1wlacup/) (20 September 2026). One player's account, with no stated reason.

## Warden

- [wowdev.wiki: Warden](https://wowdev.wiki/Warden). Documents module scans that hash regions of the game's memory, and checks against known cheat tools. The detailed material is from a 2008 client (2.4.3).

## Precedent for patched Wine `ntdll`

- Valve's [Wine fork for Proton](https://github.com/ValveSoftware/wine) carries fsync changes to `ntdll`'s synchronization code (and esync up to Proton 10).
- [wine-staging](https://gitlab.winehq.org/wine/wine-staging) carried an `ntdll-Syscall_Emulation` patch set up to version 11.4 ([the patch set at v11.4](https://github.com/wine-staging/wine-staging/tree/v11.4/patches/ntdll-Syscall_Emulation), GitHub mirror). It was removed in March 2026.
- GameNative's [proton-wine](https://github.com/GameNative/proton-wine) carries its own arm64ec patches to `ntdll`, on top of Proton's.

## Licenses I checked

- GameNative: GPL-3.0, from the LICENSE file in [the repo](https://github.com/utkarshdalal/GameNative).
- ConsolePort: Artistic-2.0 ([repo](https://github.com/seblindfors/ConsolePort)).
- TACTSharp: MIT ([repo](https://github.com/wowdev/TACTSharp)).
- Offhand: personal use only, no redistribution, no public derivatives ([LICENSE](https://github.com/N4UX-GIT/Offhand-DualMonitor/blob/main/LICENSE)). That's why it isn't in this repo.

## Not researched yet

- Whether GameHub or current Winlator builds run retail WoW out of the box now.
- Wine's bug tracker, for the `ntdll` syscall-dispatcher pattern.
- The GitHub Discussions for GameNative and Winlator.
