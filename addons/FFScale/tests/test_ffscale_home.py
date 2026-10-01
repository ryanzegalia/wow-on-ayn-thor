#!/usr/bin/env python3
"""
FFScale 1.6.0 home-layout tests: the 4400x1080 ThorSpanHome path and the FFSpan <-> FFScale
contract. The single-screen behaviour is covered by the golden tests in
test_ffscale_layouts.py -- these only exercise what v1.6.0 adds.

Run: python test_ffscale_home.py
"""
import sys

from ffscale_harness import login, new_env

W, H = 4400, 1080
UISCALE = H / 768.0          # PHYSICAL PX PER UI UNIT at uiScale 1 on a 1080p panel
HOME_X = (0, 1240)           # bottom panel
GAME_X = (1240, 3160)        # top panel
UNSHOWN_X = 3160             # drawn nowhere

# Enum.EditModeSystem numbers, as the harness defines them.
SYS = {"CastBar": 1, "Minimap": 2, "UnitFrame": 3, "EncounterBar": 4, "ExtraAbilities": 5,
       "AuraFrame": 6, "TalkingHeadFrame": 7, "ChatFrame": 8, "VehicleLeaveButton": 9,
       "LootFrame": 10, "HudTooltip": 11, "ObjectiveTracker": 12, "MicroMenu": 13, "Bags": 14,
       "StatusTrackingBar": 15, "DurabilityFrame": 16, "TimerBars": 17,
       "VehicleSeatIndicator": 18, "ArchaeologyBar": 19, "CooldownViewer": 20,
       "EncounterEvents": 22, "RaidWarning": 24, "LossOfControl": 26}
NAME = {v: k for k, v in SYS.items()}
# Everything the home layout puts on the bottom screen; everything else is game-side.
HOME_SYSTEMS = {SYS["Minimap"], SYS["ObjectiveTracker"], SYS["ChatFrame"], SYS["MicroMenu"],
                SYS["Bags"], SYS["StatusTrackingBar"], SYS["DurabilityFrame"]}

# A mocked FFSpan that answers exactly the FFSpan <-> FFScale contract.
FFSPAN = r"""
UIParent.scale = 1                  -- uiScale 1; px/unit is scale * __H/768 = 1.40625, not the scale
__homeEnabled = true
__homeListeners = {}
FFSpan = {
    GetPhysicalSize = function() return __W, __H end,
    IsSpanned       = function() return (__W / __H) >= 2.4 end,
    HomeEligible    = function() return __W == 4400 and __H == 1080 end,
    HomeEnabled     = function() return FFSpan.HomeEligible() and __homeEnabled == true end,
    HomeRect        = function()
        if not FFSpan.HomeEligible() then return nil end
        return { x = 0, y = 0, w = 1240, h = 1080 }
    end,
    GameRect        = function()
        if not FFSpan.IsSpanned() then return nil end
        local g = __H * 16 / 9
        return { x = (__W - g) / 2, y = 0, w = g, h = __H }
    end,
    RegisterHomeListener = function(fn) __homeListeners[#__homeListeners + 1] = fn end,
}
function __homeFire(enabled, reason)
    __homeEnabled = enabled
    for _, fn in ipairs(__homeListeners) do pcall(fn, enabled, reason) end
end
-- Thor6in already exists, so the home layout must clone THAT identified base, not the active one.
table.insert(__layoutStore.layouts, {
    layoutName = "Thor6in", layoutType = Enum.EditModeLayoutType.Account,
    systems = __deepcopy(__activeLayout.systems) })
"""

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not cond else ""))


def layouts(g):
    return {l.layoutName: l for l in g.__layoutStore.layouts.values()}


def systems_of(layout):
    """[(system, systemIndex, anchorInfo dict, {setting: value})]"""
    out = []
    for s in layout.systems.values():
        a = s.anchorInfo
        anchor = None if a is None else {"point": a.point, "relativeTo": a.relativeTo,
                                         "relativePoint": a.relativePoint,
                                         "x": a.offsetX, "y": a.offsetY}
        settings = {int(e.setting): e.value for e in (s.settings.values() if s.settings else [])}
        out.append((s.system, s.systemIndex, anchor, settings))
    return out


# canvas corner (px, origin top-left, y downward) for each relativePoint
CORNER = {"TOPLEFT": (0, 0), "TOP": (W / 2, 0), "TOPRIGHT": (W, 0),
          "LEFT": (0, H / 2), "CENTER": (W / 2, H / 2), "RIGHT": (W, H / 2),
          "BOTTOMLEFT": (0, H), "BOTTOM": (W / 2, H), "BOTTOMRIGHT": (W, H)}


def envelope(anchor, scale, w, h):
    """Physical-px rect (x0, y0, x1, y1) a frame of w x h ends up with, y downward."""
    bx, by = CORNER[anchor["relativePoint"]]
    ax = bx + anchor["x"] * scale
    ay = by - anchor["y"] * scale          # SetPoint y is positive upward
    p = anchor["point"]
    if "LEFT" in p:
        x0 = ax
    elif "RIGHT" in p:
        x0 = ax - w
    else:
        x0 = ax - w / 2
    if "TOP" in p:
        y0 = ay
    elif "BOTTOM" in p:
        y0 = ay - h
    else:
        y0 = ay - h / 2
    return x0, y0, x0 + w, y0 + h


# --- home login -------------------------------------------------------------------------------
lua, g = new_env(W, H, preamble=FFSPAN)
login(g)

home = layouts(g).get("ThorSpanHome")
check("home: ThorSpanHome created", home is not None)
check("home: CHARACTER scope", home is not None and home.layoutType == 2, str(home and home.layoutType))
check("home: cloned from the identified Thor6in, not the active preset",
      any("cloned base \"Thor6in\"" in r for r in g.FFScaleLog.results.values()),
      str(list(g.FFScaleLog.results.values())[-40:]))
check("home: Thor6in kept untouched alongside it",
      layouts(g).get("Thor6in") is not None and layouts(g)["Thor6in"].layoutType == 1)
check("home: foreign layout preserved with its unknown field",
      layouts(g)["SomeoneElse"].customField == "keep me")
check("home: index resolved past 2 presets + 2 earlier customs -> SetActiveLayout(5)",
      list(g.__setActiveCalls.values())[-1] == 5, str(list(g.__setActiveCalls.values())))
check("home: live layout verified, not just pcall success",
      g.FFScaleLog.verify.match is True and g.FFScaleLog.verify.liveName == "ThorSpanHome")
check("home: ActiveLayoutName() reports the live layout",
      g.FFScale.ActiveLayoutName() == "ThorSpanHome")
check("home: exactly one SaveLayouts despite the client echoing EDIT_MODE_LAYOUTS_UPDATED back",
      len(list(g.__saveCalls.values())) == 1, str(len(list(g.__saveCalls.values()))))
check("home: bindings still written on the home path",
      len(list(g.__bindCalls.values())) >= 6 and g.__saveBindings >= 1)
check("home: action slots still dumped on the home path",
      any(r.startswith("slot 1:") for r in g.FFScaleLog.results.values()))

# --- HomeSlots contract -----------------------------------------------------------------------
slots = g.FFScale.HomeSlots()
check("slots: HomeSlots() published", slots is not None)
if slots is not None:
    check("slots: y origin stated explicitly", slots.yOrigin == "canvas-top-down", str(slots.yOrigin))
    check("slots: column inside the home region and clear of the gutter",
          0 < slots.x < slots.right <= 1240 - 16 + 0.001,
          f"x={slots.x} right={slots.right}")
    check("slots: minimapBottom above bottomBarTop with room for the bags",
          slots.minimapBottom < slots.bottomBarTop and slots.bagsHeight >= 420,
          f"minimapBottom={slots.minimapBottom} bottomBarTop={slots.bottomBarTop} bagsH={slots.bagsHeight}")
    check("slots: minimap size is a legal Edit Mode step (50..200 by 10)",
          50 <= slots.minimapPct <= 200 and slots.minimapPct % 10 == 0, str(slots.minimapPct))
    check("slots: HomeSlots() hands out a copy, not the live table",
          g.FFScale.HomeSlots() is not slots)

# --- every system lands on the screen it is meant to --------------------------------------------
NOMINAL = (200, 150)          # px stand-in envelope for a system with no measurement
bad, checked, foreign, widest = [], 0, [], None
for system, index, anchor, settings in systems_of(home):
    if anchor is None:
        continue
    if anchor["relativeTo"] != "UIParent":
        foreign.append((NAME.get(system, system), anchor["relativeTo"]))
        continue
    scale, w, h = UISCALE, NOMINAL[0], NOMINAL[1]
    if system == SYS["Minimap"]:
        pct = settings.get(2, 5) * 10 + 50          # raw -> display %, Size min 50 step 10
        # v1.7 (review B1): MinimapClusterMixin:SetEditModeScale scales self.MinimapContainer
        # and the header children, NOT the cluster ROOT -- and Edit Mode replays anchorInfo on the
        # root. So the ANCHOR resolves at the root's own scale while the ENVELOPE grows with pct.
        scale = UISCALE
        w = 198 * UISCALE * pct / 100
        h = 220 * UISCALE * pct / 100
    elif system == SYS["ObjectiveTracker"]:
        h = (settings.get(0, 0) * 10 + 400) * UISCALE   # Height min 400 step 10
    elif system == SYS["ChatFrame"]:
        w = (settings.get(0, 0) * 100 + settings.get(1, 0)) * UISCALE
        h = (settings.get(2, 0) * 100 + settings.get(3, 0)) * UISCALE
    x0, y0, x1, y1 = envelope(anchor, scale, w, h)
    lo, hi = HOME_X if system in HOME_SYSTEMS else GAME_X
    checked += 1
    if widest is None or x1 > widest[1]:
        widest = (NAME.get(system, system), x1)
    if not (lo - 0.5 <= x0 and x1 <= hi + 0.5 and -0.5 <= y0 and y1 <= H + 0.5):
        bad.append(f"{NAME.get(system, system)}#{index} -> x {x0:.0f}..{x1:.0f} y {y0:.0f}..{y1:.0f} "
                   f"(wanted x {lo}..{hi})")

check(f"regions: all {checked} anchored systems land on their intended screen",
      not bad and checked >= 30, "; ".join(bad[:6]) or f"only {checked} systems checked")
check("regions: nothing reaches the unshown strip x>=3160",
      widest is not None and widest[1] < UNSHOWN_X, str(widest))
check("regions: no home/game system is still anchored to a non-UIParent frame",
      not foreign, str(foreign))

# --- repeated apply ------------------------------------------------------------------------------
saves_before = len(list(g.__saveCalls.values()))
ok, detail = g.FFScale.ApplyLayout("repeat")
check("repeat: second apply reports success", ok is True, str(detail))
check("repeat: no duplicate layout created",
      sum(1 for l in g.__layoutStore.layouts.values() if l.layoutName == "ThorSpanHome") == 1)
check("repeat: an unchanged layout is not re-saved",
      len(list(g.__saveCalls.values())) == saves_before,
      f"{saves_before} -> {len(list(g.__saveCalls.values()))}")

# --- home turned off at run time ------------------------------------------------------------------
g.__homeFire(False, "off")
check("off: /ffspan home off switches back to Thor6in",
      g.FFScale.ActiveLayoutName() == "Thor6in", str(g.FFScale.ActiveLayoutName()))
check("off: Thor6in reactivated by resolved index, not a stale one",
      list(g.__setActiveCalls.values())[-1] == 2 + 2, str(list(g.__setActiveCalls.values())))
check("off: ThorSpanHome kept for the next time home is enabled",
      layouts(g).get("ThorSpanHome") is not None)
check("off: the stale home column is withdrawn", g.FFScale.HomeSlots() is None)
g.__homeFire(True, "on")
check("on: home listener switches straight back",
      g.FFScale.ActiveLayoutName() == "ThorSpanHome")
check("auto: no dev 'Exit via Game Menu' chat spam across login/repeat/off/on (all automatic)",
      not any("Exit via Game Menu" in p for p in g.__printed.values()))

# --- FFSpan absent / not home ---------------------------------------------------------------------
lua2, g2 = new_env(W, H)      # 4400 canvas but NO FFSpan at all
login(g2)
check("no FFSpan: falls back to Thor6in", g2.FFScale.ActiveLayoutName() == "Thor6in")
check("no FFSpan: HomeSlots() is nil", g2.FFScale.HomeSlots() is None)

lua3, g3 = new_env(1920, 1080, preamble=FFSPAN)    # FFSpan present, single screen
login(g3)
check("FFSpan at 1920: HomeEnabled false -> Thor6in", g3.FFScale.ActiveLayoutName() == "Thor6in")
check("FFSpan at 1920: no ThorSpanHome layout created", layouts(g3).get("ThorSpanHome") is None)

lua4, g4 = new_env(3160, 1080, preamble=FFSPAN)    # spanned centre-game, not home
login(g4)
check("FFSpan at 3160: centre-game is not home -> Thor6in",
      g4.FFScale.ActiveLayoutName() == "Thor6in")
check("FFSpan at 3160: no ThorSpanHome layout created", layouts(g4).get("ThorSpanHome") is None)

# --- broken FFSpan --------------------------------------------------------------------------------
BROKEN = FFSPAN + """
FFSpan.HomeRect = function() error("boom") end
"""
lua5, g5 = new_env(W, H, preamble=BROKEN)
login(g5)
check("broken FFSpan: HomeRect error degrades to Thor6in, no Lua error escapes",
      g5.FFScale.ActiveLayoutName() == "Thor6in" and g5.FFScaleLog.fatal is None)
check("broken FFSpan: the reason is logged", g5.FFScaleLog.homeError is not None,
      str(g5.FFScaleLog.homeError))

# --- combat: one coalesced retry --------------------------------------------------------------------
lua6, g6 = new_env(W, H, preamble=FFSPAN + "\n__combat = true")
ok, detail = g6.FFScale.ApplyLayout("first")
check("combat: ApplyLayout reports the deferral", ok is False and "combat" in str(detail))
g6.FFScale.ApplyLayout("second")
g6.FFScale.ApplyLayout("third")
check("combat: nothing written while in combat", len(list(g6.__saveCalls.values())) == 0)
g6.__combat = False
g6.__fire("PLAYER_REGEN_ENABLED")
check("combat: exactly ONE run after combat ends, not three",
      len(list(g6.__saveCalls.values())) == 1, str(len(list(g6.__saveCalls.values()))))
check("combat: the retry applied the home layout", g6.FFScale.ActiveLayoutName() == "ThorSpanHome")
g6.__fire("PLAYER_REGEN_ENABLED")
check("combat: a later PLAYER_REGEN_ENABLED does not re-run the queue",
      len(list(g6.__saveCalls.values())) == 1)

# --- layout limit ------------------------------------------------------------------------------------
LIMIT = FFSPAN + """
Constants = { EditModeConsts = { EditModeMaxLayoutsPerType = 2 } }
table.insert(__layoutStore.layouts, { layoutName = "CharA",
    layoutType = Enum.EditModeLayoutType.Character, systems = {} })
table.insert(__layoutStore.layouts, { layoutName = "CharB",
    layoutType = Enum.EditModeLayoutType.Character, systems = {} })
"""
lua7, g7 = new_env(W, H, preamble=LIMIT)
login(g7)
check("limit: refuses to add a third CHARACTER layout",
      layouts(g7).get("ThorSpanHome") is None and len(list(g7.__saveCalls.values())) == 0)
check("limit: says so in the log",
      any("layout limit reached" in r for r in g7.FFScaleLog.results.values()),
      str(list(g7.FFScaleLog.results.values())[-3:]))
check("limit: bindings were still applied before the abort",
      len(list(g7.__bindCalls.values())) == 6)

# --- an unknown client with no limit constant must not invent one -------------------------------------
lua8, g8 = new_env(W, H, preamble=FFSPAN + """
for i = 1, 8 do
    table.insert(__layoutStore.layouts, { layoutName = "Char" .. i,
        layoutType = Enum.EditModeLayoutType.Character, systems = {} })
end
""")
login(g8)
check("no limit constant: does not invent a cap", layouts(g8).get("ThorSpanHome") is not None)

# --- Classic at the home geometry: flavour-agnostic, no-ops where a system is missing -------------------
luac, gc = new_env(W, H, retail=False, preamble=FFSPAN)
login(gc)
check("classic home: ThorSpanHome still built, no Lua error",
      layouts(gc).get("ThorSpanHome") is not None and gc.FFScaleLog.fatal is None)
check("classic home: systems Classic does not have report SKIP instead of erroring",
      any("HOME ObjectiveTracker" in r and "SKIP (system absent)" in r
          for r in gc.FFScaleLog.results.values()),
      str([r for r in gc.FFScaleLog.results.values() if "HOME ObjectiveTracker" in r]))
check("classic home (1.10.2): the stretched tracker body stops eating taps (WatchFrame mouse off)",
      gc.WatchFrame.mouse is False, str(gc.WatchFrame.mouse))
check("classic home (1.10.2): ...and the full-height lines holder too",
      gc.WatchFrameLines.mouse is False, str(gc.WatchFrameLines.mouse))
check("classic home (1.10.2): buttons (collapse, quest lines, items) keep their mouse",
      gc.WatchFrameCollapseExpandButton.mouse is True)
check("classic home (1.10.2): logged for the device read-back",
      "WatchFrameLines" in str(gc.FFScaleLog.trackerMouseOff), str(gc.FFScaleLog.trackerMouseOff))
lua_cs, g_cs = new_env(1920, 1080, retail=False, preamble=FFSPAN)
login(g_cs)
check("classic stock 1920 (1.10.2): the tracker's mouse is left alone",
      g_cs.WatchFrame.mouse is True and g_cs.WatchFrameLines.mouse is True, str(g_cs.WatchFrame.mouse))
check("classic home: the systems Classic DOES have were placed",
      any("HOME Minimap" in r and r.find("OK:") > 0 for r in gc.FFScaleLog.results.values())
      and any("HOME ChatFrame" in r and r.find("OK:") > 0 for r in gc.FFScaleLog.results.values()))

# --- Edit Mode readiness: home applies without waiting out the 12 s pass --------------------------------
lua10, g10 = new_env(W, H, preamble=FFSPAN)
g10.__fire("PLAYER_ENTERING_WORLD")      # registers the home listener and schedules the 12 s pass
check("ready: nothing applied at +0 s", len(list(g10.__saveCalls.values())) == 0)
g10.__fire("EDIT_MODE_LAYOUTS_UPDATED")
check("ready: EDIT_MODE_LAYOUTS_UPDATED applies home immediately, 12 s early",
      g10.FFScale.ActiveLayoutName() == "ThorSpanHome"
      and len(list(g10.__saveCalls.values())) == 1,
      f"{g10.FFScale.ActiveLayoutName()} after {len(list(g10.__saveCalls.values()))} saves")
g10.__flush()                            # the 12 s pass still runs
check("ready: the 12 s pass afterwards neither re-saves nor duplicates the layout",
      len(list(g10.__saveCalls.values())) == 1
      and sum(1 for l in g10.__layoutStore.layouts.values() if l.layoutName == "ThorSpanHome") == 1,
      str(len(list(g10.__saveCalls.values()))))
check("ready: the 12 s pass still refreshed the bindings",
      len(list(g10.__bindCalls.values())) == 6, str(len(list(g10.__bindCalls.values()))))

# --- /ffscale routes through the geometry-aware path ---------------------------------------------------
lua9, g9 = new_env(W, H, preamble=FFSPAN)
lua9.execute("SlashCmdList['FFSCALE']()")
check("slash: /ffscale in home mode applies ThorSpanHome, not Thor6in",
      g9.FFScale.ActiveLayoutName() == "ThorSpanHome")
check("manual: /ffscale (typed) still reports 'applied. Exit via Game Menu' in chat",
      any("Exit via Game Menu" in p for p in g9.__printed.values()))

# --- v1.9: the micro menu is a bar across the bottom (decided 09-25 10:10, "wide ~160%") ------
# 13 Retail micro buttons at 32 units with Blizzard's -5 padding = 356 units; the queue eye is 45
# units plus its 15-unit offset. FFSpan 2.6.5+ publishes those as MicroMenuUnits once it has handed
# the buttons back from ConsolePort's toolbar. Glassy's measured envelope is 495 px on the device.
MICRO_UNITS = FFSPAN + """
FFSpan.BagAddonPresent = function() return true end
FFSpan.BagColumnRequestPx = function() return 557 end
FFSpan.GlassyChatHeightPx = function() return 495 end
FFSpan.MicroMenuUnits = function() return { menuW = 356, menuH = 40, eyeW = 60, eyeH = 45, buttons = 13 } end
"""


def entry(layout, sysname):
    for system, index, anchor, settings in systems_of(layout):
        if system == SYS[sysname]:
            return anchor, settings
    return None, None


lua11, g11 = new_env(W, H, preamble=MICRO_UNITS)
login(g11)
home11 = layouts(g11).get("ThorSpanHome")
anchor, settings = entry(home11, "MicroMenu") if home11 else (None, None)
check("bar: anchored BOTTOM at the centre of the home screen, on the bottom margin",
      anchor is not None and anchor["point"] == "BOTTOM" and anchor["relativePoint"] == "BOTTOMLEFT"
      and abs(anchor["x"] * UISCALE - 620) < 0.5 and abs(anchor["y"] * UISCALE - 16) < 0.5, str(anchor))
size_raw = settings.get(2) if settings else None
check("bar: Edit Mode Size 160 (raw 18), the wide option", size_raw == 18, str(settings))
if anchor is not None and size_raw is not None:
    pct = size_raw * 5 + 70
    mw = (356 * pct / 100 + 60) * UISCALE
    mh = max(40 * pct / 100, 45) * UISCALE
    mx0, my0, mx1, my1 = envelope(anchor, UISCALE, mw, mh)
    check("bar: the whole row (menu + eye) stays on the home screen, inside the margins",
          mx0 >= 16 - 0.5 and mx1 <= 1240 - 16 + 0.5 and my1 <= H - 16 + 0.5,
          f"bar x {mx0:.0f}..{mx1:.0f} y {my0:.0f}..{my1:.0f}")
    slots11 = g11.FFScale.HomeSlots()
    check("bar: the bag column stops above the bar",
          slots11 is not None and slots11.bottomBarTop <= my0 + 0.5,
          f"bottomBarTop={slots11 and slots11.bottomBarTop} bar top={my0:.0f}")
    ca, cs = entry(home11, "ChatFrame")
    cw = (cs.get(0, 0) * 100 + cs.get(1, 0)) * UISCALE
    chh = (cs.get(2, 0) * 100 + cs.get(3, 0)) * UISCALE
    cx0, cy0, cx1, cy1 = envelope(ca, UISCALE, cw, chh)
    check("bar: the chat sits on top of the bar, never on it", cy1 <= my0 + 0.5,
          f"chat bottom {cy1:.0f} bar top {my0:.0f}")
    chat = slots11.chat
    check("bar: the published chat slot (what Glassy is fitted to) also clears the bar",
          chat.y + chat.h <= my0 + 0.5 and chat.h < 495, f"slot y {chat.y:.0f} h {chat.h:.0f}")
    check("bar: the left column still fits -- no tracker-over-chat overflow",
          g11.FFScaleLog.leftColumnOverflow is None, str(g11.FFScaleLog.leftColumnOverflow))
check("bar: the label says what was applied",
      any("HOME MicroMenu bar across the bottom, Size 160" in r for r in g11.FFScaleLog.results.values()),
      str([r for r in g11.FFScaleLog.results.values() if "MicroMenu" in r]))

# no measurement yet (ConsolePort still holds the buttons, or an older FFSpan): same bar, same Size
anchor0, settings0 = entry(home, "MicroMenu") if home else (None, None)
check("bar: without MicroMenuUnits it is still the centred bar at Size 160",
      anchor0 is not None and anchor0["point"] == "BOTTOM" and (settings0 or {}).get(2) == 18,
      f"{anchor0} {settings0}")

# a menu too wide for 160 % is shrunk to fit; one that cannot fit even at 70 % says so
lua12, g12 = new_env(W, H, preamble=MICRO_UNITS.replace("menuW = 356", "menuW = 700"))
login(g12)
_, settings12 = entry(layouts(g12)["ThorSpanHome"], "MicroMenu")
check("bar: a wider menu is fitted to the width (700 units -> Size 110, raw 8)",
      settings12 is not None and settings12.get(2) == 8, str(settings12))
lua13, g13 = new_env(W, H, preamble=MICRO_UNITS.replace("menuW = 356", "menuW = 1300"))
login(g13)
_, settings13 = entry(layouts(g13)["ThorSpanHome"], "MicroMenu")
check("bar overflow: clamps to the 70 % floor", settings13 is not None and settings13.get(2) == 0,
      str(settings13))
check("bar overflow: logged out loud", g13.FFScaleLog.microOverflow is not None
      and "MICRO MENU OVERFLOWS" in str(g13.FFScaleLog.microOverflow), str(g13.FFScaleLog.microOverflow))

print()
print(f"{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
