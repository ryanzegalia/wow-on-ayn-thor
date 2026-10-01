#!/usr/bin/env python3
"""
Mocked-WoW-API tests for FFSpan_Dismiss.lua: a tap on the empty home screen closes the NEWEST open
menu window (2026-09-25, like closing a pop-up). Same lupa approach as the other FFSpan
suites: a hand-written mock of the slice of the WoW API the file touches, FFSpan's own menu-window
API stubbed as FFSpan_Home publishes it, the real addon file loaded unmodified.

MOCK TEST: it proves the catcher's life cycle, the newest-first order, the close rules, the combat
/ drag / forbidden guards and the slash toggle. It proves nothing about real strata hit-testing or
ConsolePort's cursor on the device -- that is a device check.
Run: python test_ffspan_dismiss.py
"""
import os
import sys

try:
    import lupa
except ImportError:
    print("SKIP: python module 'lupa' is not installed -- cannot run mocked-API tests.")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.abspath(os.path.join(HERE, ".."))

MOCK = r"""
unpack = unpack or table.unpack
__combat, __cursor = false, {500, 500}
__hideCalls, __printed, __cpAdded = {}, {}, {}
__listeners = {}

local Frame = {}
Frame.__index = Frame
function __frame(name, parent)
    local f = setmetatable({ name = name, parent = parent, shown = false, points = {}, scripts = {},
                             hooks = {}, mouse = false, strata = 'MEDIUM', level = 1 }, Frame)
    if name then _G[name] = f end
    return f
end
function Frame:GetName() return self.name end
function Frame:GetParent() return self.parent end
function Frame:SetFrameStrata(s) self.strata = s end
function Frame:SetFrameLevel(l) self.level = l end
function Frame:EnableMouse(v) self.mouse = v end
function Frame:ClearAllPoints() self.points = {} end
function Frame:SetPoint(...) self.points[#self.points + 1] = { ... } end
function Frame:SetSize(w, h) self.w, self.h = w, h end
function Frame:SetScript(k, fn) self.scripts[k] = fn end
function Frame:HookScript(k, fn) self.hooks[k] = self.hooks[k] or {}; table.insert(self.hooks[k], fn) end
function Frame:IsShown() return self.shown end
function Frame:IsVisible() return self.shown end
function Frame:IsForbidden() return self.forbidden or false end
function Frame:IsProtected() return self.protected or false end
function Frame:GetEffectiveScale() return self.scale or 1 end
function Frame:RegisterEvent(ev) __listeners[#__listeners + 1] = { f = self, ev = ev } end
local function run(f, k) for _, fn in ipairs(f.hooks[k] or {}) do fn(f) end end
function Frame:Show() if not self.shown then self.shown = true; run(self, 'OnShow') end end
function Frame:Hide() if self.shown then self.shown = false; run(self, 'OnHide') end end

function CreateFrame(kind, name, parent) return __frame(name, parent) end
function InCombatLockdown() return __combat end
function GetCursorPosition() return __cursor[1], __cursor[2] end
function date() return '11:50:00' end
function print(m) __printed[#__printed + 1] = tostring(m) end
local hooked = {}
function hooksecurefunc(key, fn) hooked[key] = fn end
function HideUIPanel(f) __hideCalls[#__hideCalls + 1] = f.name; f:Hide() end
function ShowUIPanel(f) f:Show(); if hooked.ShowUIPanel then hooked.ShowUIPanel(f) end end

UIParent = __frame('UIParent'); UIParent.shown = true
UIPanelWindows = { ProfessionsFrame = {}, CollectionsJournal = {}, StoreFrame = {} }
UISpecialFrames = { 'SomethingElse' }
ConsolePort = { AddInterfaceCursorFrame = function(_, f) __cpAdded[#__cpAdded + 1] = f end }

-- the windows FFSpan calls menu windows, and one it does not (the resident bags)
for _, n in ipairs({ 'ProfessionsFrame', 'CollectionsJournal', 'StoreFrame', 'CharacterFrame' }) do
    __frame(n, UIParent)
end
__frame('ContainerFrameCombinedBags', UIParent)

-- FFSpan_Home's published API (stubbed): home rect is the 1240 x 1080 bottom panel, px, top-left
FFSpan = {}
__home = true
function FFSpan.HomeEnabled() return __home end
function FFSpan.HomeRect() return { x = 0, y = 0, w = 1240, h = 1080 } end
function FFSpan.GetPhysicalSize() return 4400, 1080 end
local MENU = { ProfessionsFrame = true, CollectionsJournal = true, StoreFrame = true, CharacterFrame = true }
function FFSpan.MenuWindowNames()
    local out = {}
    for n in pairs(MENU) do out[#out + 1] = n end
    table.sort(out)
    return out
end
function FFSpan.MenuWindowsOpen()
    local out = {}
    for n in pairs(MENU) do if _G[n].shown then out[#out + 1] = n end end
    table.sort(out)
    return out
end
FFSpanDB = {}
SLASH_FFSPAN1 = '/ffspan'
SlashCmdList = { FFSPAN = function(msg) __priorGot = msg end }

function __fire(ev) for _, l in ipairs(__listeners) do if l.ev == ev then l.f.scripts.OnEvent(l.f, ev) end end end
function __tap(x0, y0, x1, y1, button)
    local c = FFSpanDismissCatcher
    __cursor = { x0 or 500, y0 or 500 }
    c.scripts.OnMouseDown(c, button or 'LeftButton')
    __cursor = { x1 or x0 or 500, y1 or y0 or 500 }
    c.scripts.OnMouseUp(c, button or 'LeftButton')
end
"""

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not cond else ""))


def env(pre=""):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(MOCK)
    if pre:
        lua.execute(pre)
    with open(os.path.join(ADDON, "FFSpan_Dismiss.lua"), encoding="utf-8") as f:
        lua.eval("load")(f.read(), "FFSpan_Dismiss.lua")("FFSpan")
    lua.execute("__fire('PLAYER_ENTERING_WORLD')")
    return lua, lua.globals()


def shown(g):
    c = g.FFSpanDismissCatcher
    return c is not None and bool(c.shown)


print("=" * 78)
print("FFSpan_Dismiss -- tap the empty home screen to close the newest menu window")
print("=" * 78)

lua, g = env()
check("idle: no menu window open -> no catcher on the home screen", not shown(g))

g.ProfessionsFrame.Show(g.ProfessionsFrame)
c = g.FFSpanDismissCatcher
check("open: Professions shows -> the catcher comes up", shown(g))
check("catcher: BACKGROUND strata, level 0 (under every HUD element and every window)",
      c is not None and str(c.strata) == "BACKGROUND" and int(c.level) == 0)
check("catcher: takes mouse input", c is not None and c.mouse is True)
pt = c.points[1]
check("catcher: covers exactly the home rect (TOPLEFT of UIParent, 1240 x 1080 px in UI units)",
      str(pt[1]) == "TOPLEFT" and lua.eval("FFSpanDismissCatcher.points[1][2] == UIParent") and str(pt[3]) == "TOPLEFT"
      and abs(pt[4]) < 1e-9 and abs(pt[5]) < 1e-9
      and abs(c.w - 1240 / (1080 / 768)) < 1e-6 and abs(c.h - 768) < 1e-6,
      f"{[str(v) for v in pt.values()]} {c.w} {c.h}")

g.CollectionsJournal.Show(g.CollectionsJournal)
check("newest: Collections opened after Professions is the newest", str(g.FFSpan.Dismiss.Newest()) == "CollectionsJournal")
g.__tap()
check("tap: closes the NEWEST window only",
      not g.CollectionsJournal.shown and g.ProfessionsFrame.shown, f"{g.CollectionsJournal.shown} {g.ProfessionsFrame.shown}")
check("tap: a panel-manager window goes through HideUIPanel",
      [str(v) for v in g.__hideCalls.values()] == ["CollectionsJournal"])
check("tap: the catcher stays while a window is still open", shown(g))
g.__tap()
check("second tap: closes the next one", not g.ProfessionsFrame.shown)
check("...and the catcher goes away with the last window", not shown(g))

# a window that is not a panel-manager window and not protected: plain Hide()
g.CharacterFrame.Show(g.CharacterFrame)
g.__tap()
check("tap: a non-panel window is closed with Hide(), not HideUIPanel",
      not g.CharacterFrame.shown and "CharacterFrame" not in [str(v) for v in g.__hideCalls.values()])

# the resident bags are not a menu window: nothing to close, catcher down
g.ContainerFrameCombinedBags.Show(g.ContainerFrameCombinedBags)
lua.execute("FFSpan.Dismiss.Refresh('bags')")
check("bags: the resident bags alone never bring the catcher up", not shown(g))

# ------------------------------------------------------------------------- combat
lua, g = env()
g.ProfessionsFrame.Show(g.ProfessionsFrame)
g.__combat = True
g.__tap()
check("combat: the tap closes nothing", g.ProfessionsFrame.shown)
check("combat: no protected call at all (no HideUIPanel)", len(list(g.__hideCalls.values())) == 0)
check("combat: the log says why", any("combat" in str(l) for l in g.FFSpanDB.dismiss.log.values()))
g.__combat = False
g.__tap()
check("combat over: the next tap closes it", not g.ProfessionsFrame.shown)

# ------------------------------------------------------------------------- drag / right button
lua, g = env()
g.ProfessionsFrame.Show(g.ProfessionsFrame)
g.__tap(100, 100, 300, 100)
check("drag: a 200 px finger drag is not a tap -- nothing closes", g.ProfessionsFrame.shown)
check("drag: logged as ignored", any("drag ignored" in str(l) for l in g.FFSpanDB.dismiss.log.values()))
g.__tap(100, 100, 110, 108)
check("jitter: a 13 px wobble is still a tap", not g.ProfessionsFrame.shown)
g.ProfessionsFrame.Show(g.ProfessionsFrame)
g.__tap(None, None, None, None, "RightButton")
check("right button: never closes", g.ProfessionsFrame.shown)

# ------------------------------------------------------------------------- forbidden (the Shop)
lua, g = env("StoreFrame.forbidden = true")
g.StoreFrame.shown = True          # a forbidden frame cannot be hooked; it is just open
g.ProfessionsFrame.Show(g.ProfessionsFrame)
lua.execute("__seq = FFSpan.Dismiss.state.seq; FFSpan.Dismiss.state.shownAt.StoreFrame = __seq + 1")
check("forbidden: the Shop is the newest", str(g.FFSpan.Dismiss.Newest()) == "StoreFrame")
g.__tap()
check("forbidden: the tap closes nothing (an addon cannot touch it) -- no error",
      g.StoreFrame.shown and g.ProfessionsFrame.shown and len(list(g.__hideCalls.values())) == 0)
check("forbidden: the log says why", any("forbidden" in str(l) for l in g.FFSpanDB.dismiss.log.values()))
check("forbidden: the Shop is never hooked (IsForbidden checked first)",
      g.FFSpan.Dismiss.state.hooked.StoreFrame is None)

# ------------------------------------------------------------------------- opened before the hook
lua, g = env("CollectionsJournal.shown = true")   # already open when the file loaded
g.ProfessionsFrame.Show(g.ProfessionsFrame)
check("order: a window already open before its hook counts as the oldest",
      str(g.FFSpan.Dismiss.Newest()) == "ProfessionsFrame")

# ------------------------------------------------------------------------- home off / slash
lua, g = env()
g.ProfessionsFrame.Show(g.ProfessionsFrame)
g.__home = False
lua.execute("FFSpan.Dismiss.Refresh('home off')")
check("home off: no catcher even with a window open", not shown(g))
g.__home = True
g.SlashCmdList.FFSPAN("dismiss off")
check("/ffspan dismiss off: catcher down", not shown(g) and g.FFSpanDB.dismiss.enabled is False)
g.SlashCmdList.FFSPAN("dismiss on")
check("/ffspan dismiss on: catcher back", shown(g) and g.FFSpanDB.dismiss.enabled is True)
check("/ffspan dismiss: prints its state", any("tap-outside-to-close: ON" in str(p) for p in g.__printed.values()))
g.SlashCmdList.FFSPAN("home status")
check("/ffspan <anything else>: passed on to the previous handler", str(g.__priorGot) == "home status")

# ------------------------------------------------------------------------- ConsolePort cursor
check("consoleport: the catcher is parented to UIParent", lua.eval("FFSpanDismissCatcher.parent == UIParent"))
check("consoleport: never registered with the cursor (AddInterfaceCursorFrame not called)",
      len(list(g.__cpAdded.values())) == 0)
check("consoleport: not in UIPanelWindows / UISpecialFrames, so its Stack never discovers it",
      g.UIPanelWindows.FFSpanDismissCatcher is None
      and "FFSpanDismissCatcher" not in [str(v) for v in g.UISpecialFrames.values()])

# ------------------------------------------------------------------------- the Shop (2.8.1)
# Blizzard_Shared_StoreUIToggle.lua: ToggleStoreUI -> Shop2 (CatalogShopInboundInterface) when
# C_CatalogShop.IsShop2Enabled(), else the legacy StoreFrame_IsShown / StoreFrame_SetShown.
SHOP = r"""
__timers, __toggles, __shop2, __shopOpen, __legacyOpen = {}, 0, true, false, false
C_Timer = { After = function(t, fn) __timers[#__timers + 1] = fn end }
function __runTimers() local t = __timers; __timers = {}; for _, fn in ipairs(t) do fn() end end
C_CatalogShop = { IsShop2Enabled = function() return __shop2 end }
CatalogShopInboundInterface = { IsShown = function() return __shopOpen end }
function StoreFrame_IsShown() return __legacyOpen end
function ToggleStoreUI()
    __toggles = __toggles + 1
    if __shop2 then __shopOpen = not __shopOpen else __legacyOpen = not __legacyOpen end
end
function SetStoreUIShown(v) __legacyOpen = v end
__heard = {}
-- a real post-hook for the two shop toggles (the base mock's hooksecurefunc only records)
local recordOnly = hooksecurefunc
function hooksecurefunc(key, fn)
    if key == 'ToggleStoreUI' or key == 'SetStoreUIShown' then
        local orig = _G[key]
        _G[key] = function(...) orig(...); fn(...) end
        return
    end
    return recordOnly(key, fn)
end
"""

lua, g = env(SHOP)
lua.execute("FFSpan.OnShopChanged(function(what) __heard[#__heard + 1] = what end)")
check("shop: closed at login -> no catcher", not shown(g))
check("shop: ToggleStoreUI is post-hooked at load", lua.eval("FFSpan.Dismiss.state.shopHooked == true"))
# the micro button path: Blizzard's ToggleStoreUI, then FFSpan's post-hook
lua.execute("ToggleStoreUI()")
check("shop2 open: the catcher comes up with no menu window open", shown(g))
check("shop2 open: listeners hear it (FFBinds' `-`)", [str(v) for v in g.__heard.values()] == ["shop open"])
check("shop2 open: a poll is scheduled while it is open", len(list(g.__timers.values())) >= 1)
g.ProfessionsFrame.shown = True    # even with a menu window behind it, the shop goes first
g.__tap()
check("tap: closes the Shop through ToggleStoreUI", not g.__shopOpen and g.__toggles == 2)
check("tap: the menu window behind it stays", g.ProfessionsFrame.shown)
check("tap: listeners hear the close", [str(v) for v in g.__heard.values()] == ["shop open", "shop closed"])
check("tap: the log names the Shop", any("closed the Shop" in str(l) for l in g.FFSpanDB.dismiss.log.values()))
g.ProfessionsFrame.shown = False
lua.execute("FFSpan.Dismiss.Refresh('x')")
check("shop closed + nothing open: catcher down", not shown(g))

# closed by its own X: nothing calls FFSpan, the poll notices
lua, g = env(SHOP)
g.__shopOpen = True
lua.execute("FFSpan.Dismiss.ShopCheck('toggle')")
check("poll: open shop seen", shown(g))
g.__shopOpen = False               # the player used the Shop's own X
lua.execute("__runTimers()")
check("poll: the Shop's own X is noticed and the catcher goes down", not shown(g))
check("poll: no more polling once closed", len(list(g.__timers.values())) == 0)

# legacy shop (Shop2 off)
lua, g = env(SHOP + "__shop2 = false; __legacyOpen = true")
check("legacy StoreFrame open: seen at PLAYER_ENTERING_WORLD", shown(g))
g.__tap()
check("legacy: the tap closes it through ToggleStoreUI", not g.__legacyOpen and g.__toggles == 1)

# never opens it
lua, g = env(SHOP)
ok = lua.eval("FFSpan.CloseShop('test')")
check("CloseShop with no shop open: does not call ToggleStoreUI (it can only close)", g.__toggles == 0 and not g.__shopOpen)
lua, g = env(SHOP + "ToggleStoreUI = nil")
g.__shopOpen = True
lua.execute("FFSpan.Dismiss.ShopCheck('x')")
g.__tap()
check("no ToggleStoreUI: the tap is a logged no-op, no error",
      g.__shopOpen and any("no ToggleStoreUI" in str(l) for l in g.FFSpanDB.dismiss.log.values()))

print("\n" + "=" * 78)
passed = sum(1 for r in results if r)
print(f"{passed}/{len(results)} checks passed")
print("=" * 78)
sys.exit(0 if passed == len(results) else 1)
