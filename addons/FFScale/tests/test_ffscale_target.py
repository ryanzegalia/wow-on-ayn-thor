#!/usr/bin/env python3
"""
Mocked-WoW-API tests for FFScale_Target.lua: target-of-target moves beside the target frame on the
home layout (off the player frame), only out of combat, and goes back to Blizzard's anchor off it.

MOCK TEST: it proves the anchor, the layout gating, the combat queue, the restore and the bounded
re-apply. Where it lands on the Thor's screen is a device check (FFSpan dump rect of TargetFrameToT).
Run: python test_ffscale_target.py
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
__combat, __now, __timers, __listeners, __layoutFns = false, 100, {}, {}, {}
function InCombatLockdown() return __combat end
function GetTime() return __now end
function date() return "14:50:00" end
C_Timer = { After = function(t, fn) __timers[#__timers + 1] = fn end }
function __flush() local t = __timers; __timers = {}; for _, fn in ipairs(t) do fn() end end
function hooksecurefunc(t, key, fn)
    local orig = t[key]
    t[key] = function(...) local r = orig(...) fn(...) return r end
end
local function frame(name)
    local f = { name = name, points = {}, events = {} }
    function f:ClearAllPoints() self.points = {} end
    function f:SetPoint(...) self.points[#self.points + 1] = { ... } end
    function f:GetNumPoints() return #self.points end
    function f:GetPoint(i) return unpack(self.points[i]) end
    function f:RegisterEvent(ev) __listeners[#__listeners + 1] = { f = self, ev = ev } end
    function f:SetScript(k, fn) self[k] = fn end
    if name then _G[name] = f end
    return f
end
function CreateFrame() return frame() end
TargetFrame = frame("TargetFrame")
TargetFrameToT = frame("TargetFrameToT")
TargetFrameToT:SetPoint("TOPRIGHT", TargetFrame, "BOTTOMRIGHT", 12, 10)   -- Blizzard's anchor
FFScale = { RegisterLayoutListener = function(fn) __layoutFns[#__layoutFns + 1] = fn return true end }
function __layout(name) for _, fn in ipairs(__layoutFns) do fn(name) end end
function __fire(ev) for _, l in ipairs(__listeners) do if l.ev == ev then l.f.OnEvent(l.f, ev) end end end
function __pt(i)
    local p = TargetFrameToT.points[i or 1]
    return p[1], p[2] == TargetFrame, p[3], p[4], p[5]
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
    with open(os.path.join(ADDON, "FFScale_Target.lua"), encoding="utf-8") as f:
        lua.eval("load")(f.read(), "FFScale_Target.lua")("FFScale")
    return lua, lua.globals()


def point(lua):
    return tuple(lua.eval("{__pt()}").values())


print("=" * 78)
print("FFScale_Target -- target-of-target beside the target on the home layout")
print("=" * 78)

lua, g = env()
check("registers one layout listener with FFScale", len(list(g.__layoutFns.values())) == 1)
check("before any layout: Blizzard's anchor untouched", point(lua) == ("TOPRIGHT", True, "BOTTOMRIGHT", 12, 10))
g.__layout("ThorSpanHome")
check("home layout: ToT TOPLEFT -> TargetFrame TOPRIGHT -8,18 (beside the target, off the player)",
      point(lua) == ("TOPLEFT", True, "TOPRIGHT", -8, 18) and g.TargetFrameToT.GetNumPoints(g.TargetFrameToT) == 1,
      str(point(lua)))
check("home layout: logged for the device read-back", "beside the target" in str(g.FFScaleLog.targetOfTarget))
g.__layout("Thor6in")
check("any other layout: Blizzard's own anchor comes back", point(lua) == ("TOPRIGHT", True, "BOTTOMRIGHT", 12, 10), str(point(lua)))
g.__layout("SomeoneElse")
check("a second non-home layout: still Blizzard's anchor (no double restore)", point(lua) == ("TOPRIGHT", True, "BOTTOMRIGHT", 12, 10))

# combat: queued, applied when the fight ends
lua, g = env()
g.__combat = True
g.__layout("ThorSpanHome")
check("combat: nothing moves (secure unit button)", point(lua) == ("TOPRIGHT", True, "BOTTOMRIGHT", 12, 10))
g.__combat = False
g.__fire("PLAYER_REGEN_ENABLED")
check("combat ended: the queued move happens", point(lua) == ("TOPLEFT", True, "TOPRIGHT", -8, 18), str(point(lua)))

# something else re-anchors it: put back next frame, a bounded number of times
lua, g = env()
g.__layout("ThorSpanHome")
lua.execute('TargetFrameToT:ClearAllPoints() TargetFrameToT:SetPoint("TOPRIGHT", TargetFrame, "BOTTOMRIGHT", 12, 10)')
g.__flush()
check("moved by something else: re-applied on the next frame", point(lua) == ("TOPLEFT", True, "TOPRIGHT", -8, 18), str(point(lua)))
for _ in range(8):
    lua.execute('TargetFrameToT:ClearAllPoints() TargetFrameToT:SetPoint("TOPRIGHT", TargetFrame, "BOTTOMRIGHT", 12, 10)')
    g.__flush()
check("a fight with another mover stops after 5 re-applies in 10 s (never every frame)",
      g.FFScaleTarget.stopped is True and "stopped" in str(g.FFScaleLog.targetOfTarget))

# no ToT frame (flavor without it): silent
lua, g = env("TargetFrameToT = nil")
ok = True
try:
    g.__layout("ThorSpanHome")
except Exception:
    ok = False
check("no TargetFrameToT: a silent no-op", ok)

print("\n" + "=" * 78)
passed = sum(1 for r in results if r)
print(f"{passed}/{len(results)} checks passed")
print("=" * 78)
sys.exit(0 if passed == len(results) else 1)
