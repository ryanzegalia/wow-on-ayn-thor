#!/usr/bin/env python3
"""
Mocked-WoW-API tests for FFBinds_Camera.lua -- R3 as the third (Alt) modifier (2026-09-25
10:23). Since v1.8 (triggers are the modifiers) both zooms are native ALT- bindings in FFBinds'
LAYOUT (tested in test_ffbinds.py), so this file only owns the double-tap of R3: it opens chat, or
closes it when chat / ConsolePort's keyboard wheel is open. It must NOT zoom off modifier state any
more: with ZL as Shift, v1.7's Alt+Shift loop would have fired on R3 + ZL.

MOCK TEST: it proves the state machine and the timing. It proves nothing about the real client's
modifier emulation -- that needs a hand on the controller.

Run: python -B test_ffbinds_camera.py
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
__time, __alt, __shift, __zoom = 0, false, false, 10
__cvars = { cameraZoomSpeed = '20' }
__zoomOut, __chatOpened, __chatClosed = 0, 0, 0
__chatBox = nil

function GetTime() return __time end
function GetCVar(n) return __cvars[n] end
function IsAltKeyDown() return __alt end
function IsShiftKeyDown() return __shift end
function GetCameraZoom() return __zoom end
function CameraZoomOut(v) __zoomOut = __zoomOut + v end

-- the chat edit box: open = shown and active; its OnEscapePressed closes it (what Escape does)
local box = { shown = false }
function box:IsVisible() return self.shown end
function box:GetScript(k)
    if k == 'OnEscapePressed' then
        return function(b) b.shown = false; __chatClosed = __chatClosed + 1 end
    end
end
__box = box
ChatFrameUtil = {
    OpenChat = function(text) box.shown = true; __chatOpened = __chatOpened + 1 end,
    GetActiveWindow = function() return box.shown and box or nil end,
}

local function newFrame(name)
    local f = { name = name, scripts = {} }
    function f:SetScript(k, fn) self.scripts[k] = fn end
    if name then _G[name] = f end
    return f
end
function CreateFrame(kind, name, parent) return newFrame(name) end
UIParent = newFrame('UIParent')

function __frame(dt) __time = __time + (dt or 0.016); FFBindsCamera.scripts.OnUpdate(FFBindsCamera, dt or 0.016) end
-- a tap of R3 held for `hold` seconds
function __tap(hold) __alt = true; __frame(); __time = __time + (hold or 0.1); __alt = false; __frame() end
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
    with open(os.path.join(ADDON, "FFBinds_Camera.lua"), encoding="utf-8") as f:
        lua.eval("load")(f.read(), "FFBinds_Camera.lua")("FFBinds")
    return lua, lua.globals()


# --- v1.8: no zoom off the modifier state ----------------------------------------------------------------
lua, g = env()
check("setup: an ordinary (insecure) frame with an OnUpdate, no secure handler needed",
      g.FFBindsCamera is not None and g.FFBindsCamera.scripts.OnUpdate is not None)
g.__alt = True
g.__frame(0.1)
g.__shift = True                   # R3 + ZL (ZL is the Shift button since v1.8)
g.__frame(0.5)
check("v1.8: R3 + ZL (the Alt+Shift state) no longer zooms -- R3 + L is a native binding now",
      g.__zoomOut == 0, str(g.__zoomOut))
check("v1.8: CameraZoomOut is never called from this file", lua.eval("__zoomOut == 0"))
g.__shift = False
g.__alt = False
g.__frame(0.1)
check("v1.8: a long R3 hold is still never a tap -- no chat", g.__chatOpened == 0)

# --- double-tap: open, and close again -------------------------------------------------------------------
lua, g = env()
g.__tap(0.1)
check("tap: one short R3 press does nothing", g.__chatOpened == 0)
g.__time = g.__time + 0.15
g.__tap(0.1)
check("double-tap: opens chat", g.__chatOpened == 1 and g.__box.shown is True)
g.__time = g.__time + 1.0
g.__tap(0.1); g.__time = g.__time + 0.15; g.__tap(0.1)
check("double-tap again with chat open: closes it the way Escape does",
      g.__chatClosed == 1 and g.__box.shown is False, f"closed={g.__chatClosed}")
g.__time = g.__time + 1.0
g.__tap(0.1); g.__time = g.__time + 1.0; g.__tap(0.1)
check("two taps a second apart are two single taps", g.__chatOpened == 1)
g.__time = g.__time + 1.0
g.__tap(0.6); g.__time = g.__time + 0.1; g.__tap(0.1)
check("a hold then a tap is not a double-tap", g.__chatOpened == 1)

# --- a hold that zoomed (R3 + L / R3 + R, native ALT- bindings) is not a tap -----------------------------------------
lua, g = env()
g.__alt = True; g.__frame()
g.__zoom = 8                       # R zoomed the camera while R3 was down
g.__time = g.__time + 0.1
g.__alt = False; g.__frame()
g.__time = g.__time + 0.1
g.__tap(0.1)
check("zoom in: a short R3 press that moved the camera does not count toward a double-tap",
      g.__chatOpened == 0)

# --- Classic-style client: only the legacy chat functions ----------------------------------------------------
lua, g = env("""
ChatFrameUtil = nil
function ChatFrame_OpenChat() __box.shown = true; __chatOpened = __chatOpened + 1 end
function ChatEdit_GetActiveWindow() return __box.shown and __box or nil end
""")
g.__tap(0.1); g.__time = g.__time + 0.15; g.__tap(0.1)
check("classic: ChatFrame_OpenChat is used when ChatFrameUtil is missing", g.__chatOpened == 1)
g.__time = g.__time + 1.0
g.__tap(0.1); g.__time = g.__time + 0.15; g.__tap(0.1)
check("classic: ...and ChatEdit_GetActiveWindow finds the box to close", g.__chatClosed == 1)

# --- notes -----------------------------------------------------------------------------------------------------
lua, g = env()
check("notes: nothing is written before the SavedVariables exist", lua.eval("FFBindsDB == nil"))
lua.execute("FFBindsDB = {}")      # the SavedVariables arrive after the file has loaded
g.__frame()
check("notes: the setup line is flushed into FFBindsDB.camera once it exists",
      g.FFBindsDB.camera is not None and "native ALT- bindings" in str(g.FFBindsDB.camera.setup),
      str(g.FFBindsDB.camera and g.FFBindsDB.camera.setup))

print()
print(f"{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
