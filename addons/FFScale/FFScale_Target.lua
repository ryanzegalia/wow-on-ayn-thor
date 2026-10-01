--[[ FFScale_Target -- target-of-target off the player frame on the home layout (FFScale 1.11.0).

    2026-09-25: the target's pieces land on the player frame. Measured on the device (Retail,
    ThorSpanHome, canvas px): PlayerFrame y844-1013, TargetFrame x2004-2396 y720-889, and Blizzard
    hangs TargetFrameToT TOPRIGHT -> TargetFrame BOTTOMRIGHT 12,10, i.e. y872-955 -- right on the
    player's health bars. It shows whenever the target has a target (a mob fighting you: always).

    WHAT. On the home layout only, TargetFrameToT is re-anchored BESIDE the target frame's top
    right (TOPLEFT -> TargetFrame TOPRIGHT, ANCHOR below; TargetFrame's own units, scale 1.2 there):
    ~x1143-1346 y690-773 on the top screen -- above the R button (~y845) and clear of the player.
    Off the home layout Blizzard's own anchor is put back.

    WHY IT IS SAFE. TargetFrameToT is a secure unit button, so it moves out of combat only (a
    fight queues it for PLAYER_REGEN_ENABLED). Blizzard never re-anchors the TARGET frame's ToT
    (TargetFrame.lua re-anchors only the focus frame's, in SetSmallSize), so one move holds; a
    SetPoint post-hook re-applies it if anything ever does.

    NOT MOVED: the target's cast bar. Blizzard re-runs TargetSpellBarMixin:AdjustPosition at every
    cast start, in combat too, and the bar is anchored into the protected TargetFrame, so moving it
    mid-fight would be blocked. It needs a layout decision instead (see the FFSpan notes).
--]]

local ANCHOR = { 'TOPLEFT', 'TOPRIGHT', -8, 18 }
local HOME = 'ThorSpanHome'

local T = { original = nil, placed = false, pending = nil, busy = false, hooked = false }
_G.FFScaleTarget = T

local function note(what)
    FFScaleLog = FFScaleLog or {}
    FFScaleLog.targetOfTarget = (type(date) == 'function' and date('%H:%M:%S') or '?') .. ' ' .. what
end

local function capture(tot)
    if T.original then return end
    local pts = {}
    for i = 1, (tot.GetNumPoints and tot:GetNumPoints() or 0) do
        pts[#pts + 1] = { tot:GetPoint(i) }
    end
    T.original = pts
end

local function setPoints(tot, pts)
    T.busy = true
    tot:ClearAllPoints()
    for _, p in ipairs(pts) do tot:SetPoint(unpack(p)) end
    T.busy = false
end

-- want = true: beside the target (home layout); false: Blizzard's own anchor back.
function T.Apply(want, reason)
    local tot, target = _G.TargetFrameToT, _G.TargetFrame
    if not tot or not target then return false end
    if InCombatLockdown() then
        T.pending = want
        return false
    end
    T.pending = nil
    if want then
        capture(tot)
        setPoints(tot, { { ANCHOR[1], target, ANCHOR[2], ANCHOR[3], ANCHOR[4] } })
        T.placed = true
        note('beside the target (' .. tostring(reason) .. ')')
    elseif T.placed and T.original then
        setPoints(tot, T.original)
        T.placed = false
        note('Blizzard anchor restored (' .. tostring(reason) .. ')')
    end
    if not T.hooked and type(hooksecurefunc) == 'function' then
        T.hooked = true
        hooksecurefunc(tot, 'SetPoint', function()
            if T.busy or not T.placed or T.stopped then return end
            -- answer another mover a bounded number of times, never every frame (FFScale tracker rule)
            local now = type(GetTime) == 'function' and GetTime() or 0
            if now - (T.t0 or -math.huge) > 10 then T.t0, T.n = now, 0 end
            T.n = (T.n or 0) + 1
            if T.n > 5 then
                T.stopped = true
                note('stopped: moved 6 times in 10 s by something else')
                return
            end
            if type(C_Timer) == 'table' then
                C_Timer.After(0, function() if T.placed and not T.busy then T.Apply(true, 'moved by something else') end end)
            end
        end)
    end
    return true
end

local F = _G.FFScale
if type(F) == 'table' and type(F.RegisterLayoutListener) == 'function' then
    F.RegisterLayoutListener(function(layoutName)
        T.Apply(layoutName == HOME, 'layout ' .. tostring(layoutName))
    end)
end

local ev = type(CreateFrame) == 'function' and CreateFrame('Frame') or nil
if ev then
    ev:RegisterEvent('PLAYER_REGEN_ENABLED')
    ev:SetScript('OnEvent', function()
        if T.pending ~= nil then T.Apply(T.pending, 'combat ended') end
    end)
end
