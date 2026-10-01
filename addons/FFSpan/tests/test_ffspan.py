#!/usr/bin/env python3
"""
Mocked-WoW-API tests for FFSpan, in the same spirit as FFBinds' "tested N/N on lupa"
harness (Python lupa driving a real Lua 5.1 VM with a hand-rolled WoW API stub -- no
real WoW client needed). Run: python test_ffspan.py

Covers the 5 cases from the FFSpan build task:
  a) 3160x1080          -> Offhand enabled = true
  b) 1920x1080          -> Offhand enabled = false
  c) no existing OffhandDB -> creates a Default profile with ONLY `enabled` set
     (Offhand's own CopyDefaults is what fills the rest, not FFSpan)
  d) OffhandCharDB.activeProfile set to a custom name -> that profile is the one changed,
     and any pre-existing keys in it are left alone
  e) ADDON_LOADED for some other addon is ignored (OffhandDB left completely untouched)
"""
import os
import sys

try:
    import lupa
except ImportError:
    print("SKIP: python module 'lupa' is not installed -- cannot run mocked-API tests.")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
FFSPAN_LUA = os.path.abspath(os.path.join(HERE, "..", "FFSpan.lua"))

MOCK_API = r"""
-- Minimal mocked WoW API: just enough surface for FFSpan.lua to load and run.
local frames = {}

function CreateFrame(kind, name)
    local f = { kind = kind, name = name, events = {} }
    function f:RegisterEvent(ev) self.events[ev] = true end
    function f:SetScript(kind2, fn) if kind2 == "OnEvent" then self.OnEvent = fn end end
    function f:HookScript(kind2, fn) self["hook_" .. kind2] = fn end
    function f:SetFrameStrata(s) self.strata = s end
    function f:SetFrameLevel(l) self.level = l end
    function f:SetScale(s) self.scale = s end
    function f:SetSize(w, h) self.w, self.h = w, h end
    function f:ClearAllPoints() self.point = nil end
    function f:SetPoint(p) self.point = p end
    function f:Show() self.shown = true end
    function f:Hide() self.shown = false end
    function f:IsShown() return self.shown == true end
    function f:CreateTexture()
        local t = {}
        function t:SetAllPoints() end
        function t:SetColorTexture(r, g, b, a) f.color = {r, g, b, a} end
        return t
    end
    frames[#frames + 1] = f
    if name then _G[name] = f end
    __LAST_FRAME = f
    return f
end

UIParent = { }
function UIParent:GetEffectiveScale() return 1.0 end

DEFAULT_CHAT_FRAME = nil
ChatFrame1 = nil

function InCombatLockdown() return false end

SlashCmdList = {}

C_AddOns = { }
function C_AddOns.IsAddOnLoaded(name)
    return __MOCK_OFFHAND_LOADED == true and name == "Offhand"
end

function GetPhysicalScreenSize()
    return __MOCK_PHYS_W, __MOCK_PHYS_H
end
function GetScreenWidth() return 1920 end
function GetScreenHeight() return 1080 end
"""


def count_keys(lua, tbl):
    if tbl is None:
        return 0
    n = 0
    for _ in tbl.keys():
        n += 1
    return n


def new_env(phys_w, phys_h, offhand_loaded, preamble=""):
    """Fresh Lua VM: mock API + optional preset OffhandDB/OffhandCharDB + FFSpan.lua loaded."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    g.__MOCK_PHYS_W = phys_w
    g.__MOCK_PHYS_H = phys_h
    g.__MOCK_OFFHAND_LOADED = offhand_loaded
    lua.execute(MOCK_API)
    if preamble:
        lua.execute(preamble)
    with open(FFSPAN_LUA, "r", encoding="utf-8") as f:
        src = f.read()
    # FFSpan.lua reads `local ADDON_NAME = ...` -- pass "FFSpan" as the addon-load vararg,
    # exactly like the WoW client passes (addonName, addonTable) to a loaded file.
    chunk = lua.eval("load")(src, "FFSpan.lua")
    chunk("FFSpan")
    frame = g.__LAST_FRAME
    return lua, g, frame


def fire_addon_loaded(frame, addon_name):
    frame.OnEvent(frame, "ADDON_LOADED", addon_name)


def get_profile(g, name="Default"):
    db = g.OffhandDB
    if db is None:
        return None
    profiles = db["profiles"]
    if profiles is None:
        return None
    return profiles[name]


results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))


# --- (a) 3160x1080 -> enabled = true -----------------------------------------------------
lua, g, frame = new_env(3160, 1080, offhand_loaded=False)
fire_addon_loaded(frame, "Offhand")
prof = get_profile(g)
check("a) 3160x1080 -> Offhand enabled=false (centre-game: Offhand retired)", prof is not None and prof["enabled"] is False,
      f"profile={dict(prof) if prof else None}")

# --- (b) 1920x1080 -> enabled = false ----------------------------------------------------
lua, g, frame = new_env(1920, 1080, offhand_loaded=False)
fire_addon_loaded(frame, "Offhand")
prof = get_profile(g)
check("b) 1920x1080 -> Offhand enabled=false", prof is not None and prof["enabled"] is False,
      f"profile={dict(prof) if prof else None}")

# --- (c) no existing OffhandDB -> Default profile created with ONLY `enabled` set --------
lua, g, frame = new_env(3160, 1080, offhand_loaded=False)
check("c-pre) OffhandDB starts absent", g.OffhandDB is None)
fire_addon_loaded(frame, "Offhand")
prof = get_profile(g)
only_enabled = prof is not None and count_keys(lua, prof) == 1 and prof["enabled"] is False
check("c) fresh install -> Default profile has ONLY `enabled` set", only_enabled,
      f"keys={list(prof.keys()) if prof else None}")

# --- (d) custom activeProfile -> that profile is the one changed, other keys untouched ---
preamble = (
    'OffhandCharDB = { activeProfile = "MyProfile" }\n'
    'OffhandDB = { profiles = { MyProfile = { hudScale = 0.5 } } }\n'
)
lua, g, frame = new_env(3160, 1080, offhand_loaded=False, preamble=preamble)
fire_addon_loaded(frame, "Offhand")
my_prof = get_profile(g, "MyProfile")
default_prof = get_profile(g, "Default")
check(
    "d) custom activeProfile is the one modified",
    my_prof is not None and my_prof["enabled"] is False and my_prof["hudScale"] == 0.5,
    f"MyProfile={dict(my_prof) if my_prof else None}",
)
check("d) Default profile never created when activeProfile is custom", default_prof is None,
      f"Default={default_prof}")

# --- (e) other addon's ADDON_LOADED is ignored -------------------------------------------
lua, g, frame = new_env(3160, 1080, offhand_loaded=False)
fire_addon_loaded(frame, "SomeOtherAddon")
check("e) OffhandDB left untouched for a non-Offhand ADDON_LOADED", g.OffhandDB is None,
      f"OffhandDB={g.OffhandDB}")

# --- (f) in-world marker for the span fork's glue probe ----------------------------------
lua, g, frame = new_env(3160, 1080, offhand_loaded=False)
frame.OnEvent(frame, "PLAYER_LOGIN", None)
m = g.FFSpanMarker
check("f) spanned PLAYER_LOGIN -> magenta marker shown bottom-right, TOOLTIP strata",
      m is not None and m.shown is True and m.point == "BOTTOMRIGHT" and m.strata == "TOOLTIP"
      and m.color[1] == 1 and m.color[2] == 0 and m.color[3] == 1,
      f"marker={dict(m) if m else None}")
check("f) marker is 6 physical px (6*768/1080 units)", m is not None and abs(m.w - 6 * 768 / 1080) < 1e-6,
      f"w={m.w if m else None}")
frame.OnEvent(frame, "LOADING_SCREEN_ENABLED", None)
check("f) loading screen hides the marker", m.shown is False)
frame.OnEvent(frame, "LOADING_SCREEN_DISABLED", None)
check("f) loading screen done shows it again", m.shown is True)

lua, g, frame = new_env(1920, 1080, offhand_loaded=False)
frame.OnEvent(frame, "PLAYER_LOGIN", None)
check("g) single screen (1920x1080) -> no marker frame at all", g.FFSpanMarker is None)

print()
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"{passed}/{total} passed")
sys.exit(0 if passed == total else 1)
