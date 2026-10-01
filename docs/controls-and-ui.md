# Controls and UI

What I wanted: the Thor's built-in controller working in the game, the face buttons matching the labels printed on the Thor, and one button layout shared by Retail and Classic.

## The controller path

- No remapping layer in between. The Thor's built-in pad ("Odin Controller", USB id `2020:0111`) is bound straight to GameNative's controller slot 0.
- No GameNative controller profile. I tried fixing the buttons with a GameNative profile first, and that turned out to be the thing breaking them.
- The button fix is on the WoW side. [GamePadConfig_Thor.json](../launcher/config/GamePadConfig_Thor.json), copied into the game's `WTF` folder, swaps raw buttons 0 and 1, and 2 and 3, for the two device ids WoW sees (`8224:273` and `1118:654`). `Config.wtf` sets `GamePadSingleActiveID "1"`. ConsolePort's active device is set to "Nintendo Switch Pro" so the on-screen glyphs match the Thor's labels.

[tools/wow_controls.py](../tools/wow_controls.py) applies and checks those settings. WoW must be closed when you apply, because it rewrites `Config.wtf` on exit.

## FFBinds: one layout for every flavor

[addons/FFBinds/](../addons/FFBinds/) is my addon. The rule I used: anything that isn't specific to a class is the same in every game. Buttons are bound to action bar *slots*, targeting, menus and chat, never to spells. So the button grid is shared, and each character keeps its own spells in its own slots.

The grid (Nintendo labels). ZL, ZR and R3 are the three modifier buttons: ZL is Shift, ZR is Ctrl and R3 is Alt, so they have no bindings of their own. L and R are ordinary buttons. "Action n" is WoW's `ACTIONBUTTONn` (the main bar), "BL n" is `MULTIACTIONBAR1BUTTONn` (the bottom-left bar) and "BR n" is `MULTIACTIONBAR2BUTTONn` (the bottom-right bar). The exact binding names are in `LAYOUT` in [FFBinds.lua](../addons/FFBinds/FFBinds.lua).

| Button | Plain | Shift (ZL) | Ctrl (ZR) | Shift+Ctrl | Alt (R3) |
|---|---|---|---|---|---|
| B / A / Y / X | Action 1 / 3 / 5 / 7 | Action 2 / 4 / 6 / 8 | BL 1 / 3 / 5 / 7 | BL 2 / 4 / 6 / 8 | |
| R / L | Action 9 / 11 | Action 10 / 12 | BL 9 / 11 | BL 10 / 12 | Camera zoom in / out |
| D-pad Up | Interact | Nearest friend | BR 7 | BR 1 | |
| D-pad Down | Previous enemy | Previous friend | BR 8 | BR 2 | |
| D-pad Left | Target focus | Focus target | BR 9 | BR 3 | |
| D-pad Right | Nearest enemy | Assist | BR 10 | BR 4 | |
| Back (`-`) | ConsolePort menu ring | | | | |
| Forward (`+`) | | All bags | Character pane | | |
| L3 / Capture | Jump / Open chat | | | | |
| R3 | Double tap: open chat | | | | |

Up to 1.7 the modifiers were ZL (Shift) and L (Ctrl). 1.8 moved them to the triggers and R3, the same split as ConsolePort's own "Triggers" modifier preset, so L could take bindings, including R3 + L. On the first login with 1.8 a layout saved under the old modifiers is converted, edits included, so each press keeps what it did: ZL + a button is unchanged, ZR + a button does what L + that button did, and L takes ZR's old slots 11 and 12. R3 + L and R3 + R are WoW's own camera zoom commands, so they work in combat and can be held. Two taps of R3 less than 0.4 s apart open chat ([FFBinds_Camera.lua](../addons/FFBinds/FFBinds_Camera.lua)).

What it does:

- **At login** it applies the grid to whichever flavor is running, saves the bindings once, and turns on ConsolePort's radial keyboard.
- **For 15 seconds after that** it treats binding changes as the client's own late loading and overrides them. **After that,** a change is treated as your edit and saved into `FFBindsDB`. My launcher copies that saved file to every flavor, so an edit in one game shows up in the others on their next launch.
- **If a game doesn't have a command,** the binding is logged as `REFUSED` and not saved, so it can't wipe the shared grid. On MoP Classic 5.5.4 I got 40 chords applied and no refusals.
- **Gamepad cvars** (which buttons are the modifiers, stick feel, soft targeting) are copied from the first retail login and applied to the other flavors.
- **Log:** `FFBindsDB.log` inside `WTF/Account/<account>/SavedVariables/FFBinds.lua`. It's updated on `PLAYER_LOGOUT`, so after a clean logout or quit. A crash or force-stop doesn't save it.

### The `-` button (FFBinds 1.8.4<!-- VERSION -->)

Up to version 1.0 the `-` button opened the game menu. From 1.1 it clicks ConsolePort's menu button (`CLICK ConsolePortMenuTrigger:LeftButton`), which opens ConsolePort's menu ring. Since 1.2 each press goes back one step:

1. If the ring is open, `-` closes it.
2. Otherwise, if a menu window is open, `-` closes all of them in one press. A menu window is one you open from the ring or the micro menu: the game menu, settings, the character pane, talents and spellbook, the map, collections and so on.
3. Otherwise, `-` opens the ring.

Bags and NPC windows (vendor, bank, mail, trade, auction house) never count as menu windows. So at a vendor, `-` opens the ring, and the character pane opens next to the vendor window.

**The Shop.** Since 1.8.4, while the Shop is open, `-` closes it, and the ring's game-menu entry closes it instead of opening the menu, in combat too. The Shop's only controller close is its own Escape handler, which the menu button skips, and ConsolePort's cursor can't reach it. FFBinds only closes it while it's open, so these presses can't open it. On my device `-` closed the Shop on Retail. On Forever the Shop is disabled.

In the ring, A and B both pick an entry and close the ring. ConsolePort's default makes one of them (on the Thor's Nintendo layout, A) pick an entry and keep the ring open. FFBinds changes that one entry in the ring's own bindings at runtime, after ConsolePort sets them up. It doesn't change ConsolePort's files or its saved settings.

In the ring, L and R open the game menu in one press, and a second press closes it. ConsolePort binds the ring's shoulder buttons to WoW's own game-menu binding, and that binding closes the bags and clears the target before it opens the menu. Since 1.3 FFBinds points those ring entries at its own button instead, which only shows or hides the game menu. The bags stay open and the target stays targeted.

Combat works differently since 1.5. WoW doesn't let an addon's own code show or hide these windows in a fight, and trying it puts a red "Interface action blocked" message on screen. So in combat FFBinds' own `-` and game-menu handlers do nothing, apart from one log line per fight. A secure state driver takes over for the fight instead, the same mechanism ConsolePort uses for its own combat switch. It binds `-` to ConsolePort's menu button, so `-` opens and closes the ring. It changes no other button, so R is still Action 9 in a fight. Inside the ring, L and R go back to WoW's own game-menu binding for the fight. That binding works in combat, but it closes the bags and clears the target first, like it did before 1.3. When the fight ends, the driver lets go of `-`, the ring's L and R point at FFBinds' button again, and the next `-` closes any menu window that was waiting.

If a menu window was open when the fight started, FFBinds' close binding for `-` may still be there during the fight. I don't know yet which of the two bindings WoW uses then. With the driver's, `-` opens the ring. With the close binding, `-` does nothing until the fight ends. `/ffbinds back` shows which one is on.

**Known issue, seen with 1.2:** if a menu window is already open when a fight starts, pressing `-` during the fight can make WoW show "Interface action blocked". An addon isn't allowed to close those windows in combat. Since 1.5 FFBinds doesn't call any protected function in combat. I haven't confirmed on my device that the message is gone.

`/ffbinds back` prints what `-` would do right now, whether the close binding is on, whether both ring changes took effect, whether the ring or the game menu is showing, whether you're in combat, whether the combat driver is registered and holds the ring, and the last log line.

- A click binding needs the target button to exist, so FFBinds only sets it when ConsolePort's menu button is there.
- 1.1 and 1.2 each changed the layout's seed, and 1.5 has a new one again, so the new layout replaces any binding edits saved in `FFBindsDB` once, on the first login with the new version. 1.8 converts a saved layout to the new modifiers instead (above).
- On my device, 1.1's `-` opened the ring, and the ring could stay open after picking an entry with A. On 25 September I played Retail with 1.8.4, and it converted the saved layout on the first login on Classic and Forever.
- On the dual-screen layout, the ring's Inventory entry would normally close the always-open bags. FFSpan puts them straight back.

MoP Classic's default ConsolePort setup had almost none of this: no D-pad bindings, no game-menu button, no Shift/Ctrl layers, keyboard off. That's why I wrote FFBinds instead of copying settings by hand.

## FFScale: the UI layout

[addons/FFScale/](../addons/FFScale/) is my addon for placing and scaling Blizzard's own UI on a 6-inch 1080p screen. It uses WoW's Edit Mode where the game has it, and places frames directly where it doesn't.

- **Retail:** one Edit Mode layout for 1920x1080. Player and target frames larger and lower, bigger quest tracker text, a smaller minimap, buffs top-left.
- **MoP Classic:** made to match retail. Classic's Edit Mode has fewer systems, so the ones it lacks are logged as `SKIP (system absent)`. Classic's quest tracker (`WatchFrame`) isn't in Edit Mode, so FFScale places and scales it directly, out of combat only.
- **Dual screen:** since 1.6 there's a second Edit Mode layout, `ThorSpanHome`, for the 4400 x 1080 dual-screen canvas. It lays out the bottom screen (tracker, minimap, chat, room for the always-open bags) and moves the frames that hang off the screen's left and right edges onto the game view. Frames anchored to the centre are already right and are left alone. Version 1.11.0<!-- VERSION --> is on my device. The details and the device results are in [dual-screen.md](dual-screen.md).
- **Target of target:** since 1.11.0, on the home layout only, the target-of-target frame sits beside the target frame's top right instead of on the player frame ([FFScale_Target.lua](../addons/FFScale/FFScale_Target.lua)). It's a secure frame, so it only moves out of combat. On my device it showed beside the target. The target's cast bar still hangs under the target frame, over the player frame. Blizzard repositions it at every cast start, in combat too, so I haven't moved it.
- **Graphics profile:** [FFScale_Graphics.lua](../addons/FFScale/FFScale_Graphics.lua) applies a conservative graphics profile once per login on every flavor: lower shadows and bloom, view distance and environment detail at 3, ground clutter at 2, a 75% render scale and a 60 fps cap. It doesn't touch the overall graphics preset, texture quality, spell and particle density, resolution or UI scale. It keeps the original values, and `/ffgraphics off` and `/ffgraphics restore` turn it off or put them back. Settings a flavor doesn't have are skipped. I haven't measured whether it changes the frame rate.
- **Single screen** is unchanged by the dual-screen work. The tests compare its output with saved golden files.
- It logs the measured position of every frame it touches to `FFScaleLog`, which is how I checked layouts without guessing.
- Every frame call is wrapped in `pcall`. On Classic one protected frame threw an error from `GetName`, and without the guard the whole measurement was lost.

Tests run the addon's Lua against a mocked WoW API in Python: [addons/FFScale/tests/](../addons/FFScale/tests/) with [ffscale_harness.py](../addons/FFScale/tests/ffscale_harness.py). The expected outputs are in `tests/golden/`.

## Logging in

- On the login form there's no key that moves from the email field to the password field (Tab does nothing, Enter submits). I pre-fill the email with `SET accountName "..."` in `Config.wtf` while the game is closed. The game then starts with the cursor in the password field.
- Type the password with **GameNative's** on-screen keyboard. The Cocoon launcher's keyboard mangled the text in the Wine field for me, and the server answered `BLZ51914500`.

## Quitting

**Log out to character select before closing the game.** If you close it while a new character is still in the starting area, the server keeps a ghost session, and every login for the next 15 to 30 minutes disconnects with `WOW51900319` a few seconds after the character loads. I later got the same error from a different cause, a VPN app that Android killed during the load ([battle-net.md](battle-net.md#the-vpn-trap)).
