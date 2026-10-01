#!/usr/bin/env python3
"""
Mocked-WoW-API tests for FFSpan v2: the centre-game core (FFSpan_Layout.lua) and the frame dump
(FFSpan_Dump.lua), loaded in TOC order after FFSpan.lua. Same lupa approach as test_ffspan.py.
Run: python test_ffspan_centre.py
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
FILES = ["FFSpan.lua", "FFSpan_Layout.lua", "FFSpan_Dump.lua"]

MOCK_API = r"""
unpack = unpack or table.unpack -- WoW is Lua 5.1; lupa may be 5.4
__listeners = {}
__timers = {}
__combat = false
__setpoint_calls = 0

local function newFrame(name, parent)
    local f = { name = name, parent = parent, points = {}, shown = true, strata = "MEDIUM", level = 1,
                scale = 1, rect = {0, 0, 10, 10}, children = {}, events = {}, hooks = {} }
    function f:GetName() return self.name end
    function f:RegisterEvent(ev) self.events[ev] = true; __listeners[#__listeners + 1] = self end
    function f:SetScript(kind, fn) self["script_" .. kind] = fn end
    function f:HookScript(kind, fn) local prev = self['hs_' .. kind]; self['hs_' .. kind] = function(...) if prev then prev(...) end; fn(...) end end
    function f:SetFrameStrata(s) self.strata = s end
    function f:GetFrameStrata() return self.strata end
    function f:SetFrameLevel(l) self.level = l end
    function f:GetFrameLevel() return self.level end
    function f:SetScale(s) self.scale = s end
    function f:GetEffectiveScale() return self.scale end
    function f:SetSize(w, h) self.w, self.h = w, h end
    function f:Show() self.shown = true end
    function f:Hide() self.shown = false end
    function f:IsShown() return self.shown end
    function f:IsVisible() return self.shown end
    function f:GetParent() return self.parent end
    function f:GetRect() return unpack(self.rect) end
    function f:GetChildren() return unpack(self.children) end
    function f:IsForbidden() return self.forbidden == true end
    function f:GetNumPoints() return #self.points end
    function f:GetPoint(i) local p = self.points[i]; if p then return p[1], p[2], p[3], p[4], p[5] end end
    function f:ClearAllPoints() self.points = {}; if self.hooks.ClearAllPoints then self.hooks.ClearAllPoints(self) end end
    function f:SetPoint(p, r, rp, x, y)
        if self.name == "WorldFrame" then __setpoint_calls = __setpoint_calls + 1 end
        self.points[#self.points + 1] = {p, r, rp, x or 0, y or 0}
        if self.hooks.SetPoint then self.hooks.SetPoint(self) end
    end
    function f:SetAllPoints(r) self.points = {{"TOPLEFT", r, "TOPLEFT", 0, 0}, {"BOTTOMRIGHT", r, "BOTTOMRIGHT", 0, 0}}
        if self.hooks.SetAllPoints then self.hooks.SetAllPoints(self) end end
    function f:CreateTexture() local t = {}; function t:SetAllPoints() end; function t:SetColorTexture() end; return t end
    if name then _G[name] = f end
    return f
end
__newFrame = newFrame

function CreateFrame(kind, name, parent) return newFrame(name, parent) end
function hooksecurefunc(obj, key, fn)
    local prev = obj.hooks[key]
    obj.hooks[key] = function(...) if prev then prev(...) end; fn(...) end
end

UIParent = newFrame("UIParent")
UIParent.rect = {0, 0, 2247.1, 768}
WorldFrame = newFrame("WorldFrame")
WorldFrame.points = {{"TOPLEFT", UIParent, "TOPLEFT", 0, 0}, {"BOTTOMRIGHT", UIParent, "BOTTOMRIGHT", 0, 0}}

C_Timer = {}
function C_Timer.After(_, fn) __timers[#__timers + 1] = fn end
function __flush()
    local n = 0
    while #__timers > 0 and n < 100 do local fn = table.remove(__timers, 1); fn(); n = n + 1 end
    return n
end
function __fire(ev, ...)
    for _, f in ipairs(__listeners) do
        if f.events[ev] and f.script_OnEvent then f.script_OnEvent(f, ev, ...) end
    end
end
function InCombatLockdown() return __combat end
function GetPhysicalScreenSize() return __W, __H end
function GetScreenWidth() return 1920 end
function GetScreenHeight() return 1080 end
C_AddOns = {}
function C_AddOns.IsAddOnLoaded(name) return false end
SlashCmdList = {}
__printed = {}
DEFAULT_CHAT_FRAME = { AddMessage = function(_, msg) __printed[#__printed + 1] = tostring(msg) end }
function print(msg) __printed[#__printed + 1] = tostring(msg) end
function date() return "2026-09-23 08:30:00" end
__target = false
function UnitExists() return __target end
function IsInGroup() return false end
function __show(name) local f = _G[name]; f.shown = true; if f.hs_OnShow then f.hs_OnShow(f) end end
"""


def new_env(w, h, preamble=""):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    g.__W, g.__H = w, h
    lua.execute(MOCK_API)
    if preamble:
        lua.execute(preamble)
    load = lua.eval("load")
    for name in FILES:
        with open(os.path.join(ADDON, name), encoding="utf-8") as f:
            load(f.read(), name)("FFSpan")
    return lua, g


def world_points(lua):
    return lua.eval("""(function()
        local out = {}
        for i = 1, WorldFrame:GetNumPoints() do
            local p, r, rp, x, y = WorldFrame:GetPoint(i)
            out[i] = p .. "|" .. (r and r.name or "nil") .. "|" .. rp .. "|" .. string.format("%.4f|%.4f", x, y)
        end
        return table.concat(out, ";")
    end)()""")


results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not cond else ""))


def login(lua, g):
    g.__fire("PLAYER_LOGIN")
    g.__fire("PLAYER_ENTERING_WORLD")
    return g.__flush()


# --- core: spanned, WorldFrame scale 1 -> x 620..2540 in physical px ------------------------------
lua, g = new_env(3160, 1080)
login(lua, g)
q = 1080 / 768
want = f"BOTTOMLEFT|UIParent|BOTTOMLEFT|{620 / q:.4f}|0.0000;TOPRIGHT|UIParent|BOTTOMLEFT|{2540 / q:.4f}|{1080 / q:.4f}"
check("core: 3160x1080 centres WorldFrame on canvas x 620..2540", world_points(lua) == want, world_points(lua))
check("core: applied flag set", g.FFSpan.CentreCore.applied is True)

# idempotent: a second pass adds no SetPoint calls
before = g.__setpoint_calls
g.__fire("DISPLAY_SIZE_CHANGED")
g.__flush()
check("core: stable re-apply adds no WorldFrame SetPoint calls", g.__setpoint_calls == before, f"{before} -> {g.__setpoint_calls}")

# an external reset (e.g. Blizzard / another addon) is corrected once, and the queue quiesces
lua.execute("WorldFrame:SetAllPoints(UIParent)")
n = g.__flush()
check("core: external SetAllPoints reset is re-centred", world_points(lua) == want, world_points(lua))
check("core: correction queue quiesces", len(list(g.__timers.values())) == 0 and n <= 3, f"timers ran={n}")

# WorldFrame effective scale 0.7 -> offsets in WorldFrame units still land on physical 620/2540
lua, g = new_env(3160, 1080, "WorldFrame.scale = 0.7")
login(lua, g)
q7 = 0.7 * 1080 / 768
pts = world_points(lua)
check("core: WorldFrame scale 0.7 converts offsets per receiving frame",
      pts.startswith(f"BOTTOMLEFT|UIParent|BOTTOMLEFT|{620 / q7:.4f}|"), pts)

# combat: no protected writes until regen
lua, g = new_env(3160, 1080, "__combat = true")
orig = world_points(lua)
login(lua, g)
check("core: in combat nothing moves", world_points(lua) == orig, world_points(lua))
g.__combat = False
g.__fire("PLAYER_REGEN_ENABLED")
g.__flush()
check("core: PLAYER_REGEN_ENABLED applies the centre", world_points(lua) == want, world_points(lua))

# stock launch (1920x1080): WorldFrame untouched, no marker, no dump
lua, g = new_env(1920, 1080)
orig = world_points(lua)
login(lua, g)
check("stock: 1920x1080 leaves WorldFrame alone", world_points(lua) == orig and g.FFSpan.CentreCore.applied is not True)
lua.execute('SlashCmdList.FFSPAN("dump")')
check("stock: /ffspan dump refuses and writes nothing", g.FFSpanDB is None)

# Offhand still loaded -> fail closed with one warning
lua, g = new_env(3160, 1080, "Offhand = { db = { enabled = false } }")
orig = world_points(lua)
login(lua, g)
g.__fire("DISPLAY_SIZE_CHANGED")
g.__flush()
warns = [p for p in g.__printed.values() if "remove Offhand" in p]
check("core: loaded Offhand -> WorldFrame untouched + exactly one warning",
      world_points(lua) == orig and len(warns) == 1, f"points={world_points(lua)} warns={len(warns)}")

# --- dump ------------------------------------------------------------------------------------------
pre = """
EditModeManagerFrame = __newFrame("EditModeManagerFrame")
local sys = __newFrame("PlayerFrame", UIParent)
sys.system = 5; sys.systemIndex = nil; sys.scale = 0.8; sys.rect = {100, 200, 300, 400}
function sys:IsInDefaultPosition() return false end
sys.points = {{"BOTTOM", UIParent, "BOTTOM", 0, 48}}
local hidden = __newFrame("PartyFrame", UIParent); hidden.system = 7; hidden.shown = false
EditModeManagerFrame.registeredSystemFrames = { sys, hidden }
local bad = __newFrame("BrokenFrame", UIParent)
function bad:GetRect() error("secret") end
local forb = __newFrame("ForbiddenFrame", UIParent); forb.forbidden = true
local anon = __newFrame(nil, UIParent)
UIParent.children = { sys, hidden, bad, forb, anon }
"""
lua, g = new_env(3160, 1080, pre)
login(lua, g)
lua.execute('SlashCmdList.FFSPAN("dump bags")')
d = g.FFSpanDB and g.FFSpanDB.dumps and g.FFSpanDB.dumps["bags"]
check("dump: /ffspan dump bags stores dumps.bags", d is not None and d.label == "bags")
rows = {r.name: r for r in d.frames.values()} if d else {}
pf = rows.get("PlayerFrame")
r = pf.rect if pf else None
check("dump: physical rect = GetRect * effScale * 1080/768, y flipped",
      r is not None and abs(r.x - 112.5) < 1e-6 and abs(r.y - 405) < 1e-6 and abs(r.width - 337.5) < 1e-6 and abs(r.height - 450) < 1e-6,
      f"rect={dict(r) if r else None}")
check("dump: Edit Mode metadata + raw anchor kept",
      pf is not None and pf.system == 5 and pf.inDefaultPosition is False and pf.anchors[1].relativeTo == "UIParent" and pf.anchors[1].y == 48)
check("dump: hidden Edit Mode system still recorded", "PartyFrame" in rows and rows["PartyFrame"].shown is False)
check("dump: GetRect error recorded, row kept", "BrokenFrame" in rows and rows["BrokenFrame"].rect is None)
check("dump: forbidden frame skipped", "ForbiddenFrame" not in rows and d.forbiddenSkipped >= 1)
check("dump: anonymous frame not emitted", "<anonymous>" not in rows)
check("dump: FFSpanMarker/WorldFrame geometry row present", "WorldFrame" in rows)

lua.execute('SlashCmdList.FFSPAN("dump")')
g.__fire("PLAYER_LOGOUT")
order = list(g.FFSpanDB.dumpOrder.values())
check("dump: labels kept side by side (base, bags, manual, logout)", order == ["base", "bags", "manual", "logout"], f"order={order}")
for i in range(15):
    lua.execute(f'SlashCmdList.FFSPAN("dump s{i}")')
order = list(g.FFSpanDB.dumpOrder.values())
check("dump: capped at 12 labels, oldest dropped", len(order) == 12 and "bags" not in order and g.FFSpanDB.dumps["bags"] is None, f"order={order}")
lua.execute('SlashCmdList.FFSPAN("dump no/slash")')
check("dump: bad label rejected with a message", any("dump label" in p for p in g.__printed.values()))
g.__printed = lua.table()
lua.execute('SlashCmdList.FFSPAN("")')
check("slash: plain /ffspan still prints status", any("physical" in p for p in g.__printed.values()))

# --- auto-capture while playing ---------------------------------------------------------------------
lua, g = new_env(3160, 1080, 'ContainerFrameCombinedBags = __newFrame("ContainerFrameCombinedBags", UIParent)')
login(lua, g)
dumps = g.FFSpanDB and g.FFSpanDB.dumps
check("auto: base snapshot after entering the world", dumps is not None and dumps["base"] is not None)
g.__show("ContainerFrameCombinedBags")
g.__flush()
check("auto: opening bags captures 'bags'", g.FFSpanDB.dumps["bags"] is not None)
g.__show("ContainerFrameCombinedBags")
g.__flush()
check("auto: each label once per session", list(g.FFSpanDB.dumpOrder.values()).count("bags") == 1)
g.__target = True
g.__fire("PLAYER_TARGET_CHANGED")
g.__fire("PLAYER_REGEN_DISABLED")
g.__flush()
check("auto: target + combat captured", g.FFSpanDB.dumps["target"] is not None and g.FFSpanDB.dumps["combat"] is not None)
check("auto: automatic captures stay quiet in chat (no dev clutter)",
      sum(1 for p in g.__printed.values() if "captured layout" in p) == 0)
g.__printed = lua.table()
lua.execute('SlashCmdList.FFSPAN("dump")')
check("manual: /ffspan dump still reports success in chat",
      any("FFSpan dump" in p for p in g.__printed.values()))
lua, g = new_env(1920, 1080, 'ContainerFrameCombinedBags = __newFrame("ContainerFrameCombinedBags", UIParent)')
login(lua, g)
g.__show("ContainerFrameCombinedBags")
g.__flush()
check("auto: stock launch captures nothing", g.FFSpanDB is None)

print()
print(f"{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
