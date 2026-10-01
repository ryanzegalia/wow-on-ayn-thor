#!/usr/bin/env python3
"""
Shared lupa harness for FFScale tests: a mocked WoW client (Edit Mode API, frames, timers,
bindings, action bars) plus a deterministic serialiser so a whole login can be recorded as
golden text.

Used by:
  test_ffscale_layouts.py  -- characterization (golden) tests: the recorded login must not change
  test_ffscale_home.py     -- the new 4400 home-layout behaviour

The mock is deliberately close to the real client where FFScale reads it:
  * C_EditMode.GetLayouts() returns ONLY custom layouts, and the active index counts the
    presets first (Enum.EditModePresetLayoutsMeta.NumValues).
  * Edit Mode settings are RAW SLIDER INDICES (display = raw * step + minValue).
  * Boss/Arena are UnitFrame system indices 6/7.
Enum numbers were verified against EditModeManagerConstantsDocumentation.
"""
import os
import sys

try:
    import lupa
except ImportError:  # pragma: no cover - environment guard
    print("SKIP: python module 'lupa' is not installed -- cannot run mocked-API tests.")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.abspath(os.path.join(HERE, ".."))
GOLDEN_DIR = os.path.join(HERE, "golden")
FFSCALE_LUA = os.path.join(ADDON, "FFScale.lua")

MOCK_API = r"""
unpack = unpack or table.unpack   -- WoW is Lua 5.1; lupa may be 5.4

__timers        = {}      -- {delay=, fn=} in schedule order
__timerLog      = {}      -- delays only, for the golden
__listeners     = {}
__combat        = false
__bindCalls     = {}
__saveBindings  = 0
__bindings      = {}      -- key -> action, the client's current binding set
__saveCalls     = {}      -- deep copies of every C_EditMode.SaveLayouts payload
__setActiveCalls= {}
__printed       = {}
__hookedGlobals = {}

-- ---------------------------------------------------------------- deterministic serialiser
function __deepcopy(v, seen)
    if type(v) ~= "table" then return v end
    seen = seen or {}
    if seen[v] then return seen[v] end
    local out = {}
    seen[v] = out
    for k, val in pairs(v) do out[__deepcopy(k, seen)] = __deepcopy(val, seen) end
    return out
end
CopyTable = function(t) return __deepcopy(t) end

function __ser(v)
    local t = type(v)
    if t == "nil" then return "nil" end
    if t == "boolean" then return v and "true" or "false" end
    if t == "number" then
        -- normalise Lua 5.4 floats (raw() divisions) to the 5.1 integers WoW would carry
        if v == math.floor(v) and math.abs(v) < 1e15 then return string.format("%d", v) end
        return string.format("%.6f", v)
    end
    if t == "string" then return string.format("%q", v) end
    if t ~= "table" then return "<" .. t .. ">" end
    local keys = {}
    for k in pairs(v) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b)
        local ta = type(a) == "number" and 0 or 1
        local tb = type(b) == "number" and 0 or 1
        if ta ~= tb then return ta < tb end
        if ta == 0 then return a < b end
        return tostring(a) < tostring(b)
    end)
    local parts = {}
    for _, k in ipairs(keys) do parts[#parts + 1] = __ser(k) .. "=" .. __ser(v[k]) end
    return "{" .. table.concat(parts, ",") .. "}"
end

function __serList(t)
    local out = {}
    for i, v in ipairs(t or {}) do out[#out + 1] = string.format("[%d] %s", i, __ser(v)) end
    return table.concat(out, "\n")
end

-- ---------------------------------------------------------------- frames
local function newFrame(name, parent)
    local f = { name = name, parent = parent, points = {}, shown = true, scale = 1,
                rect = {0, 0, 10, 10}, children = {}, events = {}, hooks = {},
                w = 10, h = 10 }
    function f:GetName() return self.name end
    function f:GetDebugName() return self.name or "<anon>" end
    function f:RegisterEvent(ev) self.events[ev] = true; __listeners[#__listeners + 1] = self end
    function f:UnregisterEvent(ev) self.events[ev] = nil end
    function f:SetScript(kind, fn) self["script_" .. kind] = fn end
    function f:HookScript(kind, fn)
        local prev = self['hs_' .. kind]
        self['hs_' .. kind] = function(...) if prev then prev(...) end; fn(...) end
    end
    function f:SetFrameStrata(s) self.strata = s end
    function f:SetFrameLevel(l) self.level = l end
    function f:SetScale(s) self.scale = s end
    function f:GetScale() return self.scale end
    function f:GetEffectiveScale() return self.scale end
    function f:SetSize(w, h) self.w, self.h = w, h end
    function f:SetHeight(h) self.h = h; if self.hooks.SetHeight then self.hooks.SetHeight(self) end end
    function f:SetWidth(w) self.w = w end
    function f:GetHeight() return self.h end
    function f:GetWidth() return self.w end
    function f:SetMovable(v) self.movable = v end
    function f:EnableMouse(v) self.mouse = v end
    function f:IsMouseEnabled() return self.mouse == true end
    function f:SetUserPlaced(v) self.userPlaced = v end
    function f:Show() self.shown = true end
    function f:Hide() self.shown = false end
    function f:IsShown() return self.shown end
    function f:IsVisible() return self.shown end
    function f:GetParent() return self.parent end
    function f:GetOwner() return self.owner end
    function f:GetRect() return unpack(self.rect) end
    function f:GetChildren() return unpack(self.children) end
    function f:GetObjectType() return self.objectType or 'Frame' end
    function f:IsForbidden() return self.forbidden == true end
    function f:GetNumPoints() return #self.points end
    function f:GetPoint(i) local p = self.points[i]; if p then return p[1], p[2], p[3], p[4], p[5] end end
    function f:ClearAllPoints() self.points = {} end
    function f:SetPoint(p, r, rp, x, y)
        self.points[#self.points + 1] = {p, r, rp, x or 0, y or 0}
        if self.hooks.SetPoint then self.hooks.SetPoint(self) end
    end
    function f:SetAllPoints(r) self.points = {{"TOPLEFT", r, "TOPLEFT", 0, 0}} end
    function f:CreateTexture()
        local t = {}
        function t:SetAllPoints() end
        function t:SetColorTexture() end
        return t
    end
    if name then _G[name] = f end
    return f
end
__newFrame = newFrame
function CreateFrame(kind, name, parent) return newFrame(name, parent) end

function hooksecurefunc(a, b, c)
    if type(a) == "string" then          -- hooksecurefunc("GlobalFn", fn)
        __hookedGlobals[a] = (__hookedGlobals[a] or 0) + 1
        local orig = _G[a]
        _G[a] = function(...) if orig then orig(...) end; b(...) end
        return
    end
    local prev = a.hooks[b]
    a.hooks[b] = function(...) if prev then prev(...) end; c(...) end
end

-- ---------------------------------------------------------------- timers / events
C_Timer = {}
function C_Timer.After(delay, fn)
    __timerLog[#__timerLog + 1] = delay
    __timers[#__timers + 1] = fn
end
function __flush()
    local n = 0
    while #__timers > 0 and n < 200 do local fn = table.remove(__timers, 1); fn(); n = n + 1 end
    return n
end
function __fire(ev, ...)
    for _, f in ipairs(__listeners) do
        if f.events[ev] and f.script_OnEvent then f.script_OnEvent(f, ev, ...) end
    end
end
function InCombatLockdown() return __combat end

-- ---------------------------------------------------------------- misc client API
function GetPhysicalScreenSize() return __W, __H end
function GetScreenHeight() return 768 end
function GetScreenWidth() return __W * 768 / __H end
function GetBuildInfo() return __BUILD, "60000", "Sep 22 2026", 120100 end
function date(fmt)
    if fmt == "%Y-%m-%d %H:%M:%S" then return "2026-09-23 08:30:00" end
    return "08:30:00"
end
function print(msg) __printed[#__printed + 1] = tostring(msg) end

function GetBindingAction(key) return __bindings[key] or "" end
function SetBinding(key, action)
    __bindCalls[#__bindCalls + 1] = { key = key, action = action }
    __bindings[key] = action
    return true
end
function SaveBindings(which) __saveBindings = __saveBindings + 1 end
function GetCurrentBindingSet() return 2 end

__actions = {}
function GetActionInfo(slot)
    local a = __actions[slot]
    if not a then return nil end
    return a[1], a[2]
end
C_Spell = { GetSpellName = function(id) return "Spell" .. tostring(id) end }
C_Item  = { GetItemNameByID = function(id) return "Item" .. tostring(id) end }
function GetMacroInfo(id) return "Macro" .. tostring(id) end

SlashCmdList = {}

-- ---------------------------------------------------------------- Edit Mode enums
Enum = {}
Enum.EditModeSystem = {
    ActionBar = 0, CastBar = 1, Minimap = 2, UnitFrame = 3, EncounterBar = 4,
    ExtraAbilities = 5, AuraFrame = 6, TalkingHeadFrame = 7, ChatFrame = 8,
    VehicleLeaveButton = 9, LootFrame = 10, HudTooltip = 11, ObjectiveTracker = 12,
    MicroMenu = 13, Bags = 14, StatusTrackingBar = 15, DurabilityFrame = 16,
    TimerBars = 17, VehicleSeatIndicator = 18, ArchaeologyBar = 19, CooldownViewer = 20,
    PersonalResourceDisplay = 21, EncounterEvents = 22, DamageMeter = 23,
    RaidWarning = 24, TotemActionBar = 25, LossOfControl = 26,
}
Enum.EditModeUnitFrameSystemIndices = { Player = 1, Target = 2, Focus = 3, Party = 4,
                                        Raid = 5, Boss = 6, Arena = 7, Pet = 8 }
Enum.EditModeActionBarSystemIndices = { MainBar = 1, Bar2 = 2, Bar3 = 3, RightBar1 = 4,
                                        RightBar2 = 5, ExtraBar1 = 6, ExtraBar2 = 7, ExtraBar3 = 8,
                                        StanceBar = 11, PetActionBar = 12, PossessActionBar = 13 }
Enum.EditModeLayoutType = { Preset = 0, Account = 1, Character = 2 }
Enum.EditModePresetLayoutsMeta = { NumValues = 2 }
Enum.EditModeObjectiveTrackerSetting = { Height = 0, Opacity = 1, TextSize = 2 }
Enum.EditModeUnitFrameSetting = { CastBarUnderneath = 0, BuffsOnTop = 1, UseLargerFrame = 2,
                                  FrameSize = 10 }
Enum.EditModeMinimapSetting = { HeaderUnderneath = 0, RotateMinimap = 1, Size = 2 }
Enum.EditModeAuraFrameSetting = { Orientation = 0, IconWrap = 1, IconDirection = 2,
                                  IconLimit = 3, IconSize = 4, IconPadding = 5 }
Enum.AuraFrameIconDirection = { Down = 0, Up = 1, Left = 2, Right = 3 }
Enum.EditModeCooldownViewerSetting = { Orientation = 0, IconLimit = 1, IconDirection = 2,
                                       IconSize = 3, IconPadding = 4, VisibleSetting = 5,
                                       BarContent = 6, Opacity = 7 }
Enum.CooldownViewerVisibleSetting = { Always = 0, Hidden = 1, ShowWhenActive = 2 }
Enum.EditModeChatFrameSetting = { WidthHundreds = 0, WidthTensAndOnes = 1,
                                  HeightHundreds = 2, HeightTensAndOnes = 3 }
Enum.EditModeMicroMenuSetting = { Orientation = 0, Order = 1, Size = 2, EyeSize = 3 }

-- ---------------------------------------------------------------- Edit Mode layout store
-- A system entry the way SaveLayouts round-trips it.
function __sys(system, systemIndex, point, relativeTo, relativePoint, x, y, settings)
    return {
        system = system, systemIndex = systemIndex,
        isInDefaultPosition = true,
        anchorInfo = { point = point, relativeTo = relativeTo or "UIParent",
                       relativePoint = relativePoint or point, offsetX = x, offsetY = y },
        settings = settings or {},
    }
end

__layoutStore = nil       -- { activeLayout = <combined index>, layouts = { custom... } }
__activeLayout = nil      -- the layout table EditModeManagerFrame:GetActiveLayoutInfo() returns

EditModeManagerFrame = newFrame("EditModeManagerFrame")
EditModeManagerFrame.registeredSystemFrames = {}
function EditModeManagerFrame:GetActiveLayoutInfo() return __activeLayout end

C_EditMode = {}
__saveDepth = 0
function C_EditMode.GetLayouts() return __deepcopy(__layoutStore) end
function C_EditMode.SaveLayouts(info)
    __saveCalls[#__saveCalls + 1] = __deepcopy(info)
    __layoutStore = __deepcopy(info)
    -- the real client echoes the save back as EDIT_MODE_LAYOUTS_UPDATED; a listener that does
    -- not suppress its own echo re-enters here. The depth cap turns that into extra recorded
    -- saves (a visible test failure) instead of a hung run.
    if __saveDepth < 5 then
        __saveDepth = __saveDepth + 1
        __fire("EDIT_MODE_LAYOUTS_UPDATED", __deepcopy(__layoutStore), false)
        __saveDepth = __saveDepth - 1
    end
end
function C_EditMode.SetActiveLayout(index)
    __setActiveCalls[#__setActiveCalls + 1] = index
    __layoutStore.activeLayout = index
    local numPresets = Enum.EditModePresetLayoutsMeta.NumValues
    __activeLayout = __layoutStore.layouts[index - numPresets] or __activeLayout
end
function C_EditMode.ConvertLayoutInfoToString(info)
    return "EXPORT:" .. tostring(info and info.layoutName)
end
function C_EditMode.IsValidLayoutName(name) return type(name) == "string" and #name > 0 end

GameTooltip = newFrame("GameTooltip")
function GameTooltip_SetDefaultAnchor(tt, owner) tt.owner = owner end
UIParent = newFrame("UIParent")
UIParent.rect = {0, 0, 1365.33, 768}
"""

# The base (preset) layout every scenario clones from, as Lua source appended to the mock.
RETAIL_BASE = r"""
__activeLayout = {
    layoutName = "Modern",
    layoutType = Enum.EditModeLayoutType.Preset,
    systems = {
        __sys(12, nil, "TOPRIGHT", "UIParent", "TOPRIGHT", -85, -260,
              { { setting = Enum.EditModeObjectiveTrackerSetting.Height, value = 40 },
                { setting = Enum.EditModeObjectiveTrackerSetting.TextSize, value = 0 } }),
        __sys(3, 1, "BOTTOMRIGHT", "UIParent", "BOTTOM", -300, 250,
              { { setting = Enum.EditModeUnitFrameSetting.FrameSize, value = 0 } }),
        __sys(3, 2, "BOTTOMLEFT", "UIParent", "BOTTOM", 300, 250,
              { { setting = Enum.EditModeUnitFrameSetting.FrameSize, value = 0 } }),
        __sys(3, 3, "TOPLEFT", "UIParent", "TOPLEFT", 20, -300, {}),
        __sys(3, 4, "TOPLEFT", "UIParent", "TOPLEFT", 10, -200, {}),
        __sys(3, 5, "TOPLEFT", "UIParent", "TOPLEFT", 10, -200, {}),
        __sys(3, 6, "TOPRIGHT", "UIParent", "TOPRIGHT", -100, -200, {}),
        __sys(3, 7, "TOPRIGHT", "UIParent", "TOPRIGHT", -100, -200, {}),
        __sys(3, 8, "BOTTOMRIGHT", "UIParent", "BOTTOM", -380, 300, {}),
        __sys(14, nil, "TOPRIGHT", "MicroButtonAndBagsBar", "TOPRIGHT", 0, 0, {}),
        __sys(13, nil, "BOTTOMRIGHT", "UIParent", "BOTTOMRIGHT", -10, 10, {}),
        __sys(2, nil, "TOPRIGHT", "UIParent", "TOPRIGHT", 0, 0,
              { { setting = Enum.EditModeMinimapSetting.Size, value = 5 } }),
        __sys(1, nil, "BOTTOM", "UIParent", "BOTTOM", 0, 180, {}),
        __sys(20, 1, "BOTTOM", "UIParent", "BOTTOM", 0, 200, {}),
        __sys(20, 2, "BOTTOM", "UIParent", "BOTTOM", 0, 230, {}),
        __sys(20, 3, "BOTTOM", "UIParent", "BOTTOM", 0, 260, {}),
        __sys(20, 4, "BOTTOM", "UIParent", "BOTTOM", 0, 290, {}),
        __sys(26, nil, "CENTER", "UIParent", "CENTER", 0, 0, {}),
        __sys(5, nil, "BOTTOM", "UIParent", "BOTTOM", 0, 160, {}),
        __sys(9, nil, "BOTTOM", "UIParent", "BOTTOM", 0, 220, {}),
        __sys(16, nil, "TOPRIGHT", "UIParent", "TOPRIGHT", -180, -20, {}),
        __sys(18, nil, "TOPRIGHT", "UIParent", "TOPRIGHT", -180, -20, {}),
        __sys(11, nil, "BOTTOMRIGHT", "UIParent", "BOTTOMRIGHT", -9, 85, {}),
        __sys(6, 1, "TOPRIGHT", "UIParent", "TOPRIGHT", -205, -13,
              { { setting = Enum.EditModeAuraFrameSetting.IconDirection, value = 2 } }),
        __sys(6, 2, "TOPRIGHT", "UIParent", "TOPRIGHT", -205, -100,
              { { setting = Enum.EditModeAuraFrameSetting.IconDirection, value = 2 } }),
        __sys(6, 3, "TOP", "UIParent", "TOP", 0, -30, {}),
        __sys(22, 1, "TOP", "UIParent", "TOP", 0, -260, {}),
        __sys(22, 2, "TOP", "UIParent", "TOP", 0, -40, {}),
        __sys(22, 3, "TOP", "UIParent", "TOP", 0, -75, {}),
        __sys(22, 4, "TOP", "UIParent", "TOP", 0, -110, {}),
        __sys(17, nil, "TOP", "UIParent", "TOP", 0, -145, {}),
        __sys(4, nil, "TOP", "UIParent", "TOP", 0, -220, {}),
        __sys(19, nil, "TOP", "UIParent", "TOP", 0, -220, {}),
        __sys(7, nil, "TOP", "UIParent", "TOP", 0, -20, {}),
        __sys(10, nil, "CENTER", "UIParent", "CENTER", 250, 20, {}),
        __sys(8, nil, "BOTTOMLEFT", "UIParent", "BOTTOMLEFT", 35, 110,
              { { setting = Enum.EditModeChatFrameSetting.HeightHundreds, value = 1 },
                { setting = Enum.EditModeChatFrameSetting.HeightTensAndOnes, value = 20 } }),
        __sys(15, nil, "BOTTOM", "UIParent", "BOTTOM", 0, 6, {}),
        -- the class bars at Blizzard's default, beside the main action bar
        __sys(0, 11, "BOTTOMLEFT", "UIParent", "BOTTOM", -300, 110, {}),
        __sys(0, 12, "BOTTOMLEFT", "UIParent", "BOTTOM", -300, 150, {}),
        __sys(0, 13, "BOTTOMLEFT", "UIParent", "BOTTOM", -300, 110, {}),
    },
}
-- one foreign custom layout that FFScale must never disturb
__layoutStore = { activeLayout = 1, layouts = {
    { layoutName = "SomeoneElse", layoutType = Enum.EditModeLayoutType.Account,
      customField = "keep me",
      systems = { __sys(2, nil, "TOPLEFT", "UIParent", "TOPLEFT", 5, -5, {}) } },
} }
"""

# MoP Classic: Edit Mode exists but with a smaller system set (FFScaleLog 09-22 22:07).
CLASSIC_BASE = r"""
__activeLayout = {
    layoutName = "Classic",
    layoutType = Enum.EditModeLayoutType.Preset,
    systems = {
        __sys(3, 1, "BOTTOMRIGHT", "UIParent", "BOTTOM", -300, 250,
              { { setting = Enum.EditModeUnitFrameSetting.FrameSize, value = 0 } }),
        __sys(3, 2, "BOTTOMLEFT", "UIParent", "BOTTOM", 300, 250,
              { { setting = Enum.EditModeUnitFrameSetting.FrameSize, value = 0 } }),
        __sys(3, 3, "TOPLEFT", "UIParent", "TOPLEFT", 20, -300, {}),
        __sys(3, 8, "BOTTOMRIGHT", "UIParent", "BOTTOM", -380, 300, {}),
        __sys(14, nil, "BOTTOMRIGHT", "MainMenuBarArtFrame", "BOTTOMRIGHT", 0, 0, {}),
        __sys(13, nil, "BOTTOMRIGHT", "UIParent", "BOTTOMRIGHT", -10, 10, {}),
        __sys(2, nil, "TOPRIGHT", "UIParent", "TOPRIGHT", 0, 0,
              { { setting = Enum.EditModeMinimapSetting.Size, value = 5 } }),
        __sys(1, nil, "BOTTOM", "UIParent", "BOTTOM", 0, 180, {}),
        __sys(5, nil, "BOTTOM", "UIParent", "BOTTOM", 0, 160, {}),
        __sys(9, nil, "BOTTOM", "UIParent", "BOTTOM", 0, 220, {}),
        __sys(16, nil, "TOPRIGHT", "UIParent", "TOPRIGHT", -180, -20, {}),
        __sys(18, nil, "TOPRIGHT", "UIParent", "TOPRIGHT", -180, -20, {}),
        __sys(25, nil, "BOTTOMLEFT", "UIParent", "BOTTOM", -260, 120, {}),
        __sys(8, nil, "BOTTOMLEFT", "UIParent", "BOTTOMLEFT", 35, 110,
              { { setting = Enum.EditModeChatFrameSetting.HeightHundreds, value = 1 },
                { setting = Enum.EditModeChatFrameSetting.HeightTensAndOnes, value = 20 } }),
        __sys(15, nil, "BOTTOM", "UIParent", "BOTTOM", 0, 6, {}),
    },
}
__layoutStore = { activeLayout = 1, layouts = {
    { layoutName = "SomeoneElse", layoutType = Enum.EditModeLayoutType.Account,
      customField = "keep me",
      systems = { __sys(2, nil, "TOPLEFT", "UIParent", "TOPLEFT", 5, -5, {}) } },
} }
WatchFrame = __newFrame("WatchFrame", UIParent)
WatchFrame.mouse = true   -- Classic 5.5.4: the tracker body takes the mouse (device 09-25)
-- its children: the full-height lines holder (takes the mouse too) and a clickable button
WatchFrameLines = __newFrame("WatchFrameLines", WatchFrame); WatchFrameLines.mouse = true; WatchFrameLines.h = 900
WatchFrameCollapseExpandButton = __newFrame("WatchFrameCollapseExpandButton", WatchFrame)
WatchFrameCollapseExpandButton.mouse = true; WatchFrameCollapseExpandButton.objectType = "Button"
WatchFrame.children = { WatchFrameLines, WatchFrameCollapseExpandButton }
"""

ACTIONS = r"""
__actions = { [1] = {"spell", 100}, [2] = {"spell", 200}, [3] = {"item", 300},
              [4] = {"macro", 4}, [5] = {"spell", 500} }
"""


def new_env(w, h, *, retail=True, preamble="", extra_files=None):
    """Load FFScale into a fresh mocked client. `preamble` runs after the mock, before FFScale."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    g.__W, g.__H = w, h
    g.__BUILD = "12.1.0" if retail else "5.5.4"
    lua.execute(MOCK_API)
    lua.execute("WOW_PROJECT_MAINLINE = 1; WOW_PROJECT_ID = %d" % (1 if retail else 19))
    lua.execute(RETAIL_BASE if retail else CLASSIC_BASE)
    lua.execute(ACTIONS)
    if preamble:
        lua.execute(preamble)
    load = lua.eval("load")
    for name in (extra_files or ["FFScale.lua"]):
        with open(os.path.join(ADDON, name), encoding="utf-8") as f:
            load(f.read(), name)("FFScale")
    return lua, g


def login(g, flush=True):
    """PLAYER_ENTERING_WORLD and then every timer it schedules (12 s run, 3 s measure)."""
    g.__fire("PLAYER_ENTERING_WORLD")
    return g.__flush() if flush else 0


def record(lua, g):
    """Everything FFScale did, as deterministic text."""
    return lua.eval(r"""(function()
        local L = FFScaleLog or {}
        local out = {}
        local function sec(title, body)
            out[#out + 1] = "== " .. title .. " =="
            out[#out + 1] = body
        end
        sec("results", __serList(L.results))
        sec("before", __ser(L.before))
        sec("after", __ser(L.after))
        sec("deferred/fatal/errors", __ser({ deferred = L.deferred, fatal = L.fatal,
            trackerError = L.trackerError, measureError = L.measureError }))
        sec("saveLayouts", __serList(__saveCalls))
        sec("setActiveLayout", __serList(__setActiveCalls))
        sec("layoutStore", __ser(__layoutStore))
        sec("bindings", __serList(__bindCalls) .. "\nSaveBindings=" .. tostring(__saveBindings))
        sec("timers", __serList(__timerLog))
        sec("hookedGlobals", __ser(__hookedGlobals))
        sec("printed", __serList(__printed))
        sec("measure.named", __serList(L.measure and L.measure.named))
        sec("measure.systems", __serList(L.measure and L.measure.systems))
        sec("measure.screen", __ser(L.measure and L.measure.screen))
        sec("trackerPoints", __ser((function()
            local tr = _G.WatchFrame or _G.ObjectiveTrackerFrame
            if not tr then return "no tracker frame" end
            local p = {}
            for i = 1, tr:GetNumPoints() do
                local pt, r, rp, x, y = tr:GetPoint(i)
                p[i] = { pt, r and r.name or "nil", rp, x, y }
            end
            return { points = p, scale = tr.scale, height = tr.h,
                     movable = tr.movable, userPlaced = tr.userPlaced }
        end)()))
        return table.concat(out, "\n")
    end)()""")


def golden_path(case):
    return os.path.join(GOLDEN_DIR, case + ".txt")


def compare_golden(case, actual, update):
    """Returns (ok, detail). With update=True the golden is (re)written instead."""
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    path = golden_path(case)
    if update or not os.path.exists(path):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(actual)
        return True, "golden written"
    with open(path, encoding="utf-8") as f:
        expected = f.read()
    if expected == actual:
        return True, ""
    a, b = expected.splitlines(), actual.splitlines()
    for i in range(max(len(a), len(b))):
        ea = a[i] if i < len(a) else "<missing>"
        eb = b[i] if i < len(b) else "<missing>"
        if ea != eb:
            return False, f"line {i + 1}:\n  golden: {ea[:300]}\n  actual: {eb[:300]}"
    return False, "length differs"
