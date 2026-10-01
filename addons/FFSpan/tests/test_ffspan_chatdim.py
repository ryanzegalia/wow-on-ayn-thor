#!/usr/bin/env python3
"""
Mocked-WoW-API tests for FFSpan_ChatDim.lua: the home-screen chat dims when idle instead of
vanishing (2026-09-25). Same lupa approach as the other FFSpan suites: a small mock of
what the file touches, the real addon file loaded unmodified.

MOCK TEST: it proves the alpha rules (full after a message / while typing / under the pointer,
dim otherwise, easing both ways, combat log ignored, home off hands the alpha back once) and the
slash command. How it looks on the Thor is a device check.
Run: python test_ffspan_chatdim.py
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
__now, __focus, __over, __home, __printed = 100, nil, false, true, {}
__listeners, __tickers = {}, {}
function GetTime() return __now end
function GetCurrentKeyBoardFocus() return __focus end
function MouseIsOver(f) return __over end
function print(m) __printed[#__printed + 1] = tostring(m) end
C_Timer = { NewTicker = function(t, fn) __tickers[#__tickers + 1] = fn return {} end }
function hooksecurefunc(t, key, fn)
    local orig = t[key]
    t[key] = function(...) local r = orig(...) fn(...) return r end
end
local function frame()
    local f = { alpha = 1, events = {} }
    function f:SetAlpha(a) self.alpha = a end
    function f:GetAlpha() return self.alpha end
    function f:RegisterEvent(ev) __listeners[#__listeners + 1] = { f = self, ev = ev } end
    function f:SetScript(k, fn) self[k] = fn end
    function f:AddMessage(m) self.last = m end
    return f
end
function CreateFrame() return frame() end
GlassyFrame = frame()
NUM_CHAT_WINDOWS = 3
ChatFrame1, ChatFrame2, ChatFrame3 = frame(), frame(), frame()
FFSpan = { HomeEnabled = function() return __home end }
FFSpanDB = {}
SlashCmdList = { FFSPAN = function(msg) __priorGot = msg end }
function __fire(ev) for _, l in ipairs(__listeners) do if l.ev == ev then l.f.OnEvent(l.f, ev) end end end
function __tick(n, dt)
    for _ = 1, n or 1 do
        __now = __now + (dt or 0.1)
        for _, fn in ipairs(__tickers) do fn() end
    end
end
"""

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not cond else ""))


def env():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(MOCK)
    with open(os.path.join(ADDON, "FFSpan_ChatDim.lua"), encoding="utf-8") as f:
        lua.eval("load")(f.read(), "FFSpan_ChatDim.lua")("FFSpan")
    lua.execute("__fire('PLAYER_ENTERING_WORLD')")
    return lua, lua.globals()


def alpha(g):
    return round(float(g.GlassyFrame.alpha), 3)


print("=" * 78)
print("FFSpan_ChatDim -- the home chat dims when idle instead of vanishing")
print("=" * 78)

lua, g = env()
check("start: one ticker, no double start on a second PLAYER_ENTERING_WORLD",
      len(list(g.__tickers.values())) == 1 and (lua.execute("__fire('PLAYER_ENTERING_WORLD')") or True)
      and len(list(g.__tickers.values())) == 1)
g.__tick(20)
check("idle: the chat eases down to the dim alpha (0.45), not to 0", alpha(g) == 0.45, alpha(g))

g.ChatFrame1.AddMessage(g.ChatFrame1, "hello")
g.__tick(1)
check("message: a new message starts bringing it back up", alpha(g) > 0.45, alpha(g))
g.__tick(6)
check("message: full brightness within the fade time", alpha(g) == 1.0, alpha(g))
g.__tick(50)                        # 5 s later: still inside the 10 s hold
check("hold: stays full for the hold after the message", alpha(g) == 1.0, alpha(g))
g.__tick(60)                        # past the hold, plus the fade
check("hold over: dims again", alpha(g) == 0.45, alpha(g))
check("message: the original AddMessage still ran (post-hook only)", str(g.ChatFrame1.last) == "hello")

g.ChatFrame2.AddMessage(g.ChatFrame2, "You hit Wolf for 12")
g.__tick(3)
check("combat log: its messages never light the chat up", alpha(g) == 0.45, alpha(g))
g.ChatFrame3.AddMessage(g.ChatFrame3, "trade chat")
g.__tick(7)
check("other windows: any other chat window does", alpha(g) == 1.0, alpha(g))

lua, g = env()
g.__tick(20)
lua.execute("__focus = {}")
g.__tick(7)
check("typing: an edit box with keyboard focus keeps it full", alpha(g) == 1.0, alpha(g))
lua.execute("__focus = nil")
g.__tick(200)
check("typing done: dims again", alpha(g) == 0.45, alpha(g))
g.__over = True
g.__tick(7)
check("touch: the pointer over the chat (a tap on it) brings it up", alpha(g) == 1.0, alpha(g))
g.__over = False

g.__tick(200)
g.__home = False
g.__tick(1)
check("home off: the alpha is handed back to 1 once", alpha(g) == 1.0, alpha(g))
g.GlassyFrame.alpha = 0.7            # someone else's alpha now
g.__tick(5)
check("home off: ...and then left alone", alpha(g) == 0.7, alpha(g))
g.__home = True

lua, g = env()
g.SlashCmdList.FFSPAN("chatdim 0.6")
g.__tick(200)
check("/ffspan chatdim 0.6: idle alpha changes", alpha(g) == 0.6 and float(g.FFSpanDB.chatDim.alpha) == 0.6, alpha(g))
g.SlashCmdList.FFSPAN("chatdim 5")
check("/ffspan chatdim 5: an out-of-range alpha is ignored", float(g.FFSpanDB.chatDim.alpha) == 0.6)
g.SlashCmdList.FFSPAN("chatdim off")
g.__tick(1)
check("/ffspan chatdim off: full at once and left alone", alpha(g) == 1.0 and g.FFSpanDB.chatDim.enabled is False)
check("/ffspan chatdim: prints its state", any("chat dim: OFF" in str(p) for p in g.__printed.values()))
g.SlashCmdList.FFSPAN("home status")
check("/ffspan <anything else>: passed on to the previous handler", str(g.__priorGot) == "home status")

lua, g = env()
lua.execute("GlassyFrame = nil")
ok = True
try:
    g.__tick(5)
except Exception:
    ok = False
check("no Glassy: ticks are silent no-ops", ok)

print("\n" + "=" * 78)
passed = sum(1 for r in results if r)
print(f"{passed}/{len(results)} checks passed")
print("=" * 78)
sys.exit(0 if passed == len(results) else 1)
