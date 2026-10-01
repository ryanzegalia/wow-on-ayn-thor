# Troubleshooting

What I ran into, what it looked like, and what fixed it on my device.

| What you see | What it was for me | Fix |
|---|---|---|
| Realm selection says **incompatible** | Blizzard patched. The PC updated, the Thor didn't. | [game-client.md](game-client.md), "After every Blizzard patch". |
| Game hangs before a window appears, about half of cold starts | Wine loader-lock deadlock. | Fix 4 on [wine.md](wine.md). |
| Game exits about 15 s in, `_wassert vkCreateGraphicsPipelines` | A driver shader-compile failure turned into an abort. | Fix 3 on [wine.md](wine.md), and the Turnip patch on [graphics.md](graphics.md). |
| Crash at address 0, over and over, right after start | The anti-tamper's copy of `ntdll` calling a zero dispatcher slot. | Fix 2 on [wine.md](wine.md). |
| "Your 3D accelerator card is not supported" | GameNative overwrote the ARM64 DLLs and the DLL script didn't put them back. | Rooted setup: check the Magisk boot script is running ([launcher.md](launcher.md)). With the imported files: check **DXVK Version** is the imported one, because otherwise GameNative copies its own x64 DXVK in. |
| GameNative stops responding the first time you open **Edit container** on a new game | It was waiting on a Google Play check for its recommended-settings lookup, and the check never answered. | Close GameNative and open **Edit container** again. It worked the second time for me. |
| DXVK: "No adapters found" | A Turnip build with `android-strict` on, or adrenotools off. | [graphics.md](graphics.md). |
| DXVK logs `Failed to compile pipeline: -13` | A shader the driver can't compile. Something won't draw. | The Turnip patch. Count the `-13` lines over a session, 0 is healthy. |
| My driver or Wine change seems to do nothing | GameNative reverted the container file on exit. | Import the driver and Wine through GameNative's own managers and pick them in **Edit container**, then they stay picked ([quick-path.md](quick-path.md)). Or, rooted, re-pin every launch. Either way, check `ADRENOTOOLS_DRIVER_PATH` and `extraData.appliedWineVersion` in the run itself. |
| Game killed while loading into the world, no crash dump | Something took the top screen during the load, and Android's low-memory killer took the game with it. | Keep other apps from popping up. The Magisk note on [what-you-need.md](what-you-need.md). |
| Game dies at **Log In**, no crash dump, `fdsan: attempted to close file descriptor` in Android's log | Wine's crypt32 closed a file descriptor twice. | The crypt32 fix on [wine.md](wine.md). |
| `BLZ51914403` at the game's own login screen | On 24 September 2026 Blizzard's servers refused logins typed into the game's own login screen, before the password was even sent. My PC got the same error. Logins started from the Battle.net launcher worked. It worked again that evening. | Nothing on the Thor fixed it. Wait, or log in through Battle.net ([battle-net.md](battle-net.md)). |
| `BLZ51914500` at login | On my device, the Cocoon launcher's on-screen keyboard mangled the password. | Use GameNative's own on-screen keyboard. It logged in at once for me. |
| `WOW51900319` a few seconds after the character loads | A ghost session from closing the game while a new character was in the starting area. | Wait 15 to 30 minutes without logging in. Each try restarts the wait. Next time, log out to character select before closing. |
| `WOW51900319` right after logging in, with a VPN app running | Android's low-memory killer stopped my VPN app (Tailscale) while the game was loading, and every connection that went through the VPN closed with it, the game's included. | Exclude GameNative, and the fork if you use it, from the VPN in the VPN app's settings. |
| "Connecting..." for 30 s, then error 1016 | A stalled connection to the login server. A retry went through in about 6 s. I don't know the cause. | Retry. |
| Addon settings or keybinds not showing up in Classic | The `WTF/Account/` folder is named after the **game** account (for example `WOW1`), not the Battle.net id. | Point the launcher at the right folder (`WOW_ACCOUNT`). |
| A graphics setting in `Config.wtf` keeps reverting | It belongs to a graphics preset. WoW rewrites preset settings from the preset on load. | Change the preset, or set it from an addon at login. |
| The launcher says WoW is running when it isn't | GameNative's helper processes keep the game path in their arguments after exit. | Match the process name, not the arguments ([launcher.md](launcher.md)). |

## Not a bug

- **Moonfire's beam only plays some of the time.** The damage always lands. The PC client does the same thing.

## Network, on my setup

- **Downloads failed on 6 GHz Wi-Fi.** On my network the Thor's 6 GHz connection had heavy retries and packet loss, and large transfers failed. 5 GHz was clean. The Thor rejoined the 6 GHz network after every reboot, so I check which network it's on.
- **VPN apps.** If you run Tailscale or another VPN app, check where the game's traffic goes, and exclude GameNative from it (the `WOW51900319` row above). See [ban-risk.md](ban-risk.md).

## Getting better logs

- `DXVK_LOG_LEVEL=info` in the container's environment: DXVK says why it rejects a GPU, and prints the `-13` lines.
- `WINEDEBUG=+seh` for exception problems. Wine logs unwind warnings as `warn:seh`.
- `WINEDEBUG=+vulkan` shows which extensions Wine enables. On my device it also made the loader-lock hang much more likely, so turn it off before judging anything else.
- `IR3_SHADER_DEBUG=disasm` dumps shader NIR from the driver. Use a big logcat buffer (`logcat -G 64M`).
