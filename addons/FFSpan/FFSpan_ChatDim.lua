--[[ FFSpan_ChatDim -- the home-screen chat dims when idle instead of vanishing (2.9.0).

    2026-09-25: I wanted the chat to fade, not vanish. It now sits on the bottom screen and I still
    want to see it.

    Glassy's own `chatAlwaysVisible` keeps the messages up (FFSpan_Glassy ApplyAlwaysVisible,
    journaled and restored at logout like the width). This file only sets the alpha of Glassy's
    main container, `GlassyFrame` -- a plain frame Glassy never fades itself (its fades run on the
    dock, the messages and the edit box, all children, so the two multiply and never fight).

    FULL (1.0) for HOLD seconds after a message lands in any chat window but the combat log, while
    an edit box has keyboard focus (typing), and while the pointer is over the chat (a tap on it);
    otherwise DIM. Moves at most one full dim/brighten per FADE seconds, so it eases both ways.
    Only while the home screen is on; with it off the container goes back to 1.0 once and is left
    alone.

    /ffspan chatdim on|off|<alpha 0.1-1>|status   (default on, 0.45; FFSpanDB.chatDim, account-wide)
--]]

local S = _G.FFSpan
if type(S) ~= 'table' then
    S = {}
    _G.FFSpan = S
end
S.ChatDim = S.ChatDim or {}
local C = S.ChatDim

local DIM_DEFAULT = 0.45
local HOLD = 10      -- s at full after the last message: Glassy's own default chatHoldTime
local FADE = 0.6     -- s for a full dim or brighten
local TICK = 0.1

local state = { last = nil, owned = false, hooked = {}, ticker = nil }
C.state = state

local function safe(fn, ...)
    local ok, a = pcall(fn, ...)
    if ok then return a end
    return nil
end

local function db()
    if type(FFSpanDB) ~= 'table' then return nil end
    if type(FFSpanDB.chatDim) ~= 'table' then FFSpanDB.chatDim = { enabled = true, alpha = DIM_DEFAULT } end
    return FFSpanDB.chatDim
end

function C.Enabled()
    local d = db()
    return not d or d.enabled ~= false
end

function C.DimAlpha()
    local d = db()
    local a = d and tonumber(d.alpha)
    if not a or a < 0.1 or a > 1 then return DIM_DEFAULT end
    return a
end

local function now()
    return type(GetTime) == 'function' and GetTime() or 0
end

local function homeActive()
    return type(S.HomeEnabled) == 'function' and safe(S.HomeEnabled) and true or false
end

-- What the container should be at right now; nil = not FFSpan's to touch.
function C.Wanted()
    local frame = _G.GlassyFrame
    if not frame or not C.Enabled() or not homeActive() then return nil end
    if type(GetCurrentKeyBoardFocus) == 'function' and GetCurrentKeyBoardFocus() then return 1 end
    if type(MouseIsOver) == 'function' and safe(MouseIsOver, frame) then return 1 end
    if state.last and now() - state.last < HOLD then return 1 end
    return C.DimAlpha()
end

function C.Tick()
    local frame = _G.GlassyFrame
    if not frame or type(frame.SetAlpha) ~= 'function' then return end
    local want = C.Wanted()
    if want == nil then
        -- hand it back exactly once, then leave the player's (or Glassy's) alpha alone
        if state.owned then
            state.owned = false
            frame:SetAlpha(1)
        end
        return
    end
    state.owned = true
    local cur = tonumber(safe(frame.GetAlpha, frame)) or 1
    if cur == want then return end
    local step = (TICK / FADE) * (1 - C.DimAlpha())
    if math.abs(want - cur) <= step then
        frame:SetAlpha(want)
    else
        frame:SetAlpha(cur + (want > cur and step or -step))
    end
end

function C.Activity()
    state.last = now()
end

-- Every chat window but the combat log (ChatFrame2): combat spam must not keep it lit.
function C.Hook()
    if type(hooksecurefunc) ~= 'function' then return end
    local n = tonumber(_G.NUM_CHAT_WINDOWS) or 10
    for i = 1, n do
        local f = _G['ChatFrame' .. i]
        if i ~= 2 and f and not state.hooked[i] and type(f.AddMessage) == 'function' then
            if pcall(hooksecurefunc, f, 'AddMessage', C.Activity) then state.hooked[i] = true end
        end
    end
end

function C.Start()
    C.Hook()
    if state.ticker or type(C_Timer) ~= 'table' or type(C_Timer.NewTicker) ~= 'function' then return end
    state.ticker = C_Timer.NewTicker(TICK, C.Tick)
end

local ev = type(CreateFrame) == 'function' and CreateFrame('Frame') or nil
if ev then
    ev:RegisterEvent('PLAYER_ENTERING_WORLD')
    ev:RegisterEvent('UPDATE_CHAT_WINDOWS')
    ev:SetScript('OnEvent', function() C.Start() end)
end

-- ----------------------------------------------------------------------------- /ffspan chatdim
local prior = SlashCmdList and SlashCmdList['FFSPAN']
if SlashCmdList then
    SlashCmdList['FFSPAN'] = function(message)
        local arg = type(message) == 'string' and message:match('^%s*chatdim%s*(.-)%s*$')
        if not arg then
            if prior then prior(message) end
            return
        end
        arg = arg:lower()
        local d = db()
        local a = tonumber(arg)
        if d and (arg == 'on' or arg == 'off') then d.enabled = (arg == 'on') end
        if d and a and a >= 0.1 and a <= 1 then d.alpha = a end
        C.Tick()
        print(('|cff00e5ffFFSpan|r chat dim: %s, idle alpha %.2f, full for %ds after a message'):format(
            C.Enabled() and 'ON' or 'OFF', C.DimAlpha(), HOLD))
    end
end
