# Fixes to two third-party addons

These are small fixes my launcher makes to ConsolePort and Glassy on my device, for Lua errors I hit. They are not the addons. You install ConsolePort and Glassy yourself from their own pages ([CREDITS.md](../../CREDITS.md)). Paths in the diffs are relative to the game's `Interface/AddOns` folder. Line endings in the diffs are LF. Glassy ships its files with CRLF.

| File | Addon, version I tested | Flavor | What it fixes |
|---|---|---|---|
| `consoleport-menu-housing-guard.diff` | ConsolePort 3.2.5 (the ConsolePort_Menu module), Artistic-2.0 | Forever | Forever has the housing micro button but not `HousingFramesUtil`, so ConsolePort's housing menu entry threw a Lua error. The entry is only created when `HousingFramesUtil.ToggleHousingDashboard` exists. |
| `consoleport-libactionbutton-flyout-guard.diff` | LibActionButton-1.0 as embedded in ConsolePort 3.2.5, BSD 3-clause | Forever | `GetFlyoutInfo` can succeed without returning a slot count, and the loop over the slots then threw a Lua error. Both call sites now also check that the count is a number. |
| `glassy-chatdock-retail-anchor.diff` | Glassy 1.9.4, MIT | Retail and Forever | A chat dock anchor-cycle Lua error at startup, which I saw on Forever. The two edits only skip Glassy's cosmetic re-anchor where Glassy treats the client as retail, which includes Forever. Classic behaves as before. |

You don't need to apply these by hand if you use the picker's backend. [launcher/scripts/wowgo.sh](../../launcher/scripts/wowgo.sh) makes the same edits on launch, only when the file still has the exact original lines, and keeps a copy of each original file in `/data/adb/wow/backups/compat/` first. The ConsolePort fixes run for Forever only. To apply one by hand, from the `Interface/AddOns` folder: `patch -p1 < <the diff>` (add `--binary` for Glassy if your `patch` complains about line endings).

My launcher also changes one line in Syndicator for Forever. Syndicator is All Rights Reserved, so that change isn't here. [docs/dual-screen.md](../../docs/dual-screen.md#third-party-addons) says what it is.
