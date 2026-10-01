-- FFBinds_Camera -- R3 is the THIRD modifier. 2026-09-25 10:23: the left bumper and the left trigger were both
-- modifiers and I wanted R3 to be a third. It is the same
-- class, so ConsolePort treats it like the other two -- and while it is held the bumpers zoom the
-- camera: R in, L out, "all the way into first person or all the way zoomed out", in combat too.
-- Double-clicking R3 opens chat, and double-clicking it again with chat (or ConsolePort's keyboard
-- wheel) open closes it; a single click does nothing.
--
-- v1.8 (11:05, I wanted it to work like Final Fantasy XIV): the triggers are Shift and Ctrl now and both
-- bumpers are ordinary buttons (FFBinds.lua, THE TRIGGERS ARE THE MODIFIERS). So R3 + L and R3 + R
-- are simply the bindings ALT-PADLSHOULDER = CAMERAZOOMOUT and ALT-PADRSHOULDER = CAMERAZOOMIN in
-- FFBinds' LAYOUT: native, secure, held for continuous zoom, remappable in ConsolePort's binding
-- config like any other chord. v1.7's zoom-out loop off the Alt+Shift STATE is gone. It assumed L
-- was the Shift button; the device's modifiers were in fact Shift = ZL and Ctrl = L (1.8.0 log,
-- 11:32), so that loop zoomed out on R3 + ZL while R3 + L (Alt+Ctrl) did nothing -- which is what
-- I hit at 10:56, when the left bumper could not be used because it was also a modifier.
--
-- What stays here: the double tap. Taps are read off the Alt state, not off a binding: a modifier
-- button's own binding only fires inside GamePadEmulateTapWindowMs, and with ConsolePort's keyboard
-- up the pad's buttons belong to the keyboard. The Alt state is there either way.
--
-- What it never does: touch ConsolePort's code or saved data, or call a protected function.
-- Last run: FFBindsDB.camera (read the SavedVariables after a clean Game Menu exit).

local TAP_MAX    = 0.30   -- s: an Alt press shorter than this, with nothing else done, is a tap
local DOUBLE_GAP = 0.40   -- s: two taps closer than this (release to release) toggle chat

local Cam = { alt = false, downAt = nil, used = false, lastTapUp = nil }
FFBinds_Camera = Cam

local function now() return (type(GetTime) == 'function' and GetTime()) or 0 end
local function isDown(fn) return type(fn) == 'function' and fn() and true or false end

-- SavedVariables load after this file runs, so a note made at load waits for FFBindsDB.
local pendingNotes = {}
local function note(key, value)
    if type(FFBindsDB) ~= 'table' then pendingNotes[key] = value return end
    FFBindsDB.camera = FFBindsDB.camera or {}
    for k, v in pairs(pendingNotes) do FFBindsDB.camera[k] = v end
    pendingNotes = {}
    FFBindsDB.camera[key] = value
end

local function cameraZoom()
    if type(GetCameraZoom) ~= 'function' then return nil end
    local ok, z = pcall(GetCameraZoom)
    return ok and z or nil
end

-- The chat box that is open right now, on either client generation.
local function activeChat()
    local get = (type(ChatFrameUtil) == 'table' and ChatFrameUtil.GetActiveWindow) or _G.ChatEdit_GetActiveWindow
    local ok, box = pcall(get or function() end)
    if ok and box and box.IsVisible and box:IsVisible() then return box end
    return nil
end

-- Close it the way Escape does: the edit box's own OnEscapePressed handler. ConsolePort's keyboard
-- wheel follows the edit box's focus (ConsolePort_Keyboard/Core/Observer.lua), so it goes too.
local function closeChat(box)
    local esc = box.GetScript and box:GetScript('OnEscapePressed')
    local ok = type(esc) == 'function' and pcall(esc, box)
    if not ok and box.ClearFocus then ok = pcall(box.ClearFocus, box) end
    note('chat', ok and 'closed by double-tap' or 'chat close failed')
    return ok
end

local function openChat()
    local open = (type(ChatFrameUtil) == 'table' and ChatFrameUtil.OpenChat) or _G.ChatFrame_OpenChat
    if type(open) ~= 'function' then note('chat', 'no chat opener on this client') return false end
    local ok = pcall(open, '')
    note('chat', ok and 'opened by double-tap' or 'chat opener failed')
    return ok
end

function Cam.Toggle()
    local box = activeChat()
    if box then return closeChat(box) end
    return openChat()
end

-- One frame. Reads the Alt state and turns short presses of it into taps.
function Cam.OnUpdate(_, elapsed)
    if next(pendingNotes) and type(FFBindsDB) == 'table' then note('flushed', true) end
    local t = now()
    local alt = isDown(IsAltKeyDown)
    if alt and not Cam.alt then                    -- R3 went down
        Cam.alt, Cam.downAt, Cam.used, Cam.zoomAt = true, t, false, cameraZoom()
    elseif not alt and Cam.alt then                -- R3 came up
        Cam.alt = false
        local z = cameraZoom()
        -- the zoom is a native binding FFBinds never sees; a camera that moved means the hold was used
        if Cam.zoomAt and z and math.abs(z - Cam.zoomAt) > 0.01 then Cam.used = true end
        local held = Cam.downAt and (t - Cam.downAt) or math.huge
        Cam.downAt = nil
        if Cam.used or held > TAP_MAX then
            Cam.lastTapUp = nil
        elseif Cam.lastTapUp and (t - Cam.lastTapUp) <= DOUBLE_GAP then
            Cam.lastTapUp = nil
            Cam.Toggle()
        else
            Cam.lastTapUp = t
        end
    end
end

function Cam.Setup()
    if Cam.frame or type(CreateFrame) ~= 'function' then return Cam.frame end
    local ok, f = pcall(CreateFrame, 'Frame', 'FFBindsCamera', UIParent)
    if not ok or not f then note('setup', 'CreateFrame failed') return nil end
    Cam.frame = f
    f:SetScript('OnUpdate', Cam.OnUpdate)
    note('setup', 'R3 = Alt: R3+R zooms in, R3+L zooms out (native ALT- bindings), double-tap toggles chat')
    return f
end

Cam.Setup()
