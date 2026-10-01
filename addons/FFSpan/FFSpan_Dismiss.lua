--[[ FFSpan_Dismiss -- tap the empty home screen to close the newest menu window.

    2026-09-25: I wanted a click outside a window, anywhere on the black space, to close the most
    recently opened one, like closing a pop-up. Same for professions.

    WHAT. While the home screen is on AND a menu window is open, an invisible, mouse-enabled frame
    (the catcher) covers the home rect at BACKGROUND strata, frame level 0 -- under every HUD element
    (minimap, chat, bags, micro bar sit at LOW/MEDIUM in the 09-25 frame dumps) and under every
    window, so they all keep their own taps. A tap that reaches the catcher landed on black space,
    and closes the NEWEST open menu window: one tap, one window. With no menu window open the
    catcher is hidden and the home screen behaves exactly as before.

    WHICH WINDOWS. FFSpan's own menu-window list (S.MenuWindowsOpen / S.MenuWindowNames in
    FFSpan_Home.lua) -- the same list FFBinds' `-` button closes, so tap-outside and `-` agree on
    what a menu window is. The resident bags and NPC windows (merchant, bank, mail ...) are not menu
    windows and are never closed here. NEWEST = the last one whose OnShow FFSpan saw (its own sequence;
    one hook per name, re-scanned on ADDON_LOADED because most of them load on demand). A window
    already open before its hook existed counts as the oldest.

    HOW IT CLOSES. FFBinds' closeWindow rules (FFBinds.lua, v1.2-v1.4): GameMenuFrame, UIPanelWindows
    entries and protected frames through HideUIPanel -- a bare Hide() would leave the panel manager's
    slot allocated -- and anything else Hide(). HideUIPanel is protected: in combat the tap does
    NOTHING (no call, so no red "Interface action blocked"), the FFBinds v1.4 rule. A FORBIDDEN frame
    cannot be touched by an addon at all; the tap then does nothing and the log says why.

    THE SHOP (2.8.1: it was really hard to close). It is forbidden, opens on the TOP screen,
    ConsolePort's cursor cannot reach its X, and FFBinds' menu button skips Blizzard's Escape chain
    where its only keyboard close lives (Blizzard_Shared_StoreUIToggle.lua registers
    StoreEscapePressed as a game-menu Escape handler). Retail has two shops: the legacy StoreFrame
    and, when C_CatalogShop.IsShop2Enabled(), the catalog shop behind CatalogShopInboundInterface.
    ToggleStoreUI() is Blizzard's public toggle for whichever is active (the micro button calls it),
    so while a shop is open a tap on the home screen calls it -- only then, so it can only close.
    The shop cannot be hooked, so its state is read: after ToggleStoreUI / SetStoreUIShown, and
    every POLL seconds while it is open (catches its own X). S.ShopShown / S.CloseShop /
    S.OnShopChanged let FFBinds' `-` and menu button close it the same way.

    A DRAG IS NOT A TAP. The press has to start on the catcher (OnMouseUp only reaches the frame
    that took OnMouseDown) and end within DRAG_PX physical px of where it started, so a finger drag
    -- a future drag-to-scroll -- never closes anything.

    CONSOLEPORT. Its interface cursor only scans the frames in its Stack
    (ConsolePort_Cursor/View/Cursor.lua:160-164 -> Stack:GetVisibleCursorFrames), and the Stack only
    picks up registered frames and Blizzard's frame managers -- UIPanelWindows, UISpecialFrames ...
    (Controller/Stack.lua:246-275). The catcher is parented to UIParent and is in none of them, so
    the gamepad cursor never lands on it.

    /ffspan dismiss on|off|status   (default on; FFSpanDB.dismiss.enabled, account-wide)
    Last taps: FFSpanDB.dismiss.log (read after a clean Game Menu exit).
--]]

local S = _G.FFSpan
if type(S) ~= 'table' then
    S = {}
    _G.FFSpan = S
end
S.Dismiss = S.Dismiss or {}
local D = S.Dismiss

local DRAG_PX = 24     -- physical px a press may wander and still be a tap
local MAX_LOG = 20

local state = { seq = 0, shownAt = {}, hooked = {}, frame = nil, downX = nil, downY = nil }
D.state = state

local function safe(fn, ...)
    local ok, a, b = pcall(fn, ...)
    if ok then return a, b end
    return nil
end
local function call(obj, method, ...)
    if type(obj) ~= 'table' or type(obj[method]) ~= 'function' then return nil end
    return safe(obj[method], obj, ...)
end
local function inCombat()
    return type(InCombatLockdown) == 'function' and InCombatLockdown() and true or false
end

local function db()
    if type(FFSpanDB) ~= 'table' then return nil end
    if type(FFSpanDB.dismiss) ~= 'table' then FFSpanDB.dismiss = { enabled = true } end
    return FFSpanDB.dismiss
end
function D.Enabled()
    local d = db()
    return not d or d.enabled ~= false
end

local function note(what)
    local d = db()
    if not d then return end
    if type(d.log) ~= 'table' then d.log = {} end
    d.log[#d.log + 1] = (safe(date, '%H:%M:%S') or '?') .. ' ' .. what
    while #d.log > MAX_LOG do table.remove(d.log, 1) end
end

-- ------------------------------------------------------------------------ which window is newest
local function openWindows()
    if type(S.MenuWindowsOpen) ~= 'function' then return {} end
    local list = safe(S.MenuWindowsOpen)
    return type(list) == 'table' and list or {}
end

function D.Newest()
    local best, bestSeq
    for _, name in ipairs(openWindows()) do
        local seq = state.shownAt[name] or 0
        -- ties (two never-seen windows) break by name so the choice is stable
        if not best or seq > bestSeq or (seq == bestSeq and name < best) then
            best, bestSeq = name, seq
        end
    end
    return best
end

-- FFBinds' closeWindow rules, for ONE window.
function D.Close(name)
    local f = _G[name]
    if not f or not call(f, 'IsVisible') then return false, 'not visible' end
    if inCombat() then return false, 'combat' end
    if call(f, 'IsForbidden') then return false, 'forbidden' end
    local hide = _G.HideUIPanel
    local panel = name == 'GameMenuFrame'
        or (type(_G.UIPanelWindows) == 'table' and _G.UIPanelWindows[name] ~= nil)
        or call(f, 'IsProtected')
    if panel and type(hide) == 'function' then
        local ok = pcall(hide, f)
        return ok, ok and 'HideUIPanel' or 'HideUIPanel failed'
    end
    local ok = pcall(f.Hide, f)
    return ok, ok and 'Hide' or 'Hide failed'
end

-- ------------------------------------------------------------------------------------ the shop
local POLL = 0.5
local shopListeners = {}

function D.ShopShown()
    local cs = _G.C_CatalogShop
    if type(cs) == 'table' and type(cs.IsShop2Enabled) == 'function' and safe(cs.IsShop2Enabled) then
        local inbound = _G.CatalogShopInboundInterface
        return type(inbound) == 'table' and type(inbound.IsShown) == 'function' and safe(inbound.IsShown) and true or false
    end
    return type(_G.StoreFrame_IsShown) == 'function' and safe(_G.StoreFrame_IsShown) and true or false
end

function D.CloseShop()
    if not D.ShopShown() then return false, 'no shop open' end
    if type(_G.ToggleStoreUI) ~= 'function' then return false, 'no ToggleStoreUI' end
    if not pcall(_G.ToggleStoreUI) then return false, 'ToggleStoreUI failed' end
    return true, D.ShopShown() and 'ToggleStoreUI (still shown)' or 'ToggleStoreUI'
end

-- Re-read the shop's state; on a change, move the catcher and tell the listeners (FFBinds' `-`).
function D.ShopCheck(reason)
    local now = D.ShopShown()
    if now ~= (state.shop or false) then
        state.shop = now
        local what = 'shop ' .. (now and 'open' or 'closed')
        note(('%s (%s)'):format(what, tostring(reason)))
        D.Refresh(what)
        for _, fn in ipairs(shopListeners) do pcall(fn, what) end
    end
    if now and not state.polling and type(C_Timer) == 'table' and type(C_Timer.After) == 'function' then
        state.polling = true
        C_Timer.After(POLL, function()
            state.polling = false
            D.ShopCheck('poll')
        end)
    end
    return now
end

function D.OnShopChanged(fn)
    if type(fn) == 'function' then shopListeners[#shopListeners + 1] = fn end
end

S.ShopShown = D.ShopShown
S.OnShopChanged = D.OnShopChanged
function S.CloseShop(reason)
    local ok, how = D.CloseShop()
    note(('%s: %s the Shop (%s)'):format(tostring(reason or 'close'), ok and 'closed' or 'kept', tostring(how)))
    D.ShopCheck(reason or 'close')
    return ok, how
end

local function onShopToggle()
    D.ShopCheck('toggle')
    -- in case the shop shows a frame later than the call that asked for it
    if type(C_Timer) == 'table' and type(C_Timer.After) == 'function' then
        C_Timer.After(0.2, function() D.ShopCheck('toggle+0.2') end)
    end
end

local function hookShop()
    if state.shopHooked or type(hooksecurefunc) ~= 'function' or type(_G.ToggleStoreUI) ~= 'function' then return end
    if pcall(hooksecurefunc, 'ToggleStoreUI', onShopToggle) then
        state.shopHooked = true
        if type(_G.SetStoreUIShown) == 'function' then pcall(hooksecurefunc, 'SetStoreUIShown', onShopToggle) end
    end
end

-- ------------------------------------------------------------------------------- the catcher
local function homeActive()
    if type(S.HomeEnabled) ~= 'function' or not safe(S.HomeEnabled) then return false end
    return type(S.HomeRect) == 'function' and safe(S.HomeRect) ~= nil
end

local function place(f)
    local home = safe(S.HomeRect)
    local ui = _G.UIParent
    if not home or not ui then return false end
    local _, ph = 0, 1080
    if type(S.GetPhysicalSize) == 'function' then _, ph = S.GetPhysicalSize() end
    local q = (call(ui, 'GetEffectiveScale') or 1) * (ph or 1080) / 768   -- px per UI unit
    if not q or q <= 0 then return false end
    f:ClearAllPoints()
    f:SetPoint('TOPLEFT', ui, 'TOPLEFT', home.x / q, -home.y / q)
    f:SetSize(home.w / q, home.h / q)
    return true
end

function D.OnTap()
    -- the shop first: opening it closed every other panel (CloseAllWindows), so it is the newest
    if D.ShopShown() then
        local ok, how = S.CloseShop('tap')
        return ok and 'closed' or how
    end
    local name = D.Newest()
    if not name then note('tap: nothing open') return 'nothing' end
    local ok, how = D.Close(name)
    note(('tap: %s %s (%s)'):format(ok and 'closed' or 'kept', name, tostring(how)))
    if ok then D.Refresh('closed ' .. name) end
    return ok and 'closed' or how
end

local function cursorPx()
    if type(GetCursorPosition) ~= 'function' then return nil end
    return GetCursorPosition()
end

local function build()
    if state.frame or type(CreateFrame) ~= 'function' or not _G.UIParent then return state.frame end
    local f = safe(CreateFrame, 'Frame', 'FFSpanDismissCatcher', _G.UIParent)
    if not f then return nil end
    f:SetFrameStrata('BACKGROUND')
    f:SetFrameLevel(0)
    f:EnableMouse(true)
    f:Hide()
    f:SetScript('OnMouseDown', function(_, button)
        if button ~= 'LeftButton' then state.downX = nil return end
        state.downX, state.downY = cursorPx()
    end)
    f:SetScript('OnMouseUp', function(_, button)
        local x0, y0 = state.downX, state.downY
        state.downX, state.downY = nil, nil
        if button ~= 'LeftButton' or not x0 then return end
        local x1, y1 = cursorPx()
        if x1 and y1 and ((x1 - x0) ^ 2 + (y1 - y0) ^ 2) > DRAG_PX * DRAG_PX then
            note('drag ignored')
            return
        end
        D.OnTap()
    end)
    state.frame = f
    return f
end

-- Shown exactly while: enabled, home on, and at least one menu window or a shop open.
function D.Refresh(reason)
    local want = D.Enabled() and homeActive() and (#openWindows() > 0 or D.ShopShown())
    local f = want and build() or state.frame
    if not f then return false end
    if want then
        place(f)
        if not call(f, 'IsShown') then f:Show() end
    elseif call(f, 'IsShown') then
        f:Hide()
    end
    state.lastReason = reason
    return want
end

-- ------------------------------------------------------------------------------- the watches
function D.Rescan()
    if type(S.MenuWindowNames) ~= 'function' then return end
    local names = safe(S.MenuWindowNames) or {}
    for _, name in ipairs(names) do
        local f = _G[name]
        if f and not state.hooked[name] and type(f.HookScript) == 'function' and not call(f, 'IsForbidden') then
            if safe(function()
                f:HookScript('OnShow', function()
                    state.seq = state.seq + 1
                    state.shownAt[name] = state.seq
                    D.Refresh(name .. ' shown')
                end)
                f:HookScript('OnHide', function() D.Refresh(name .. ' hidden') end)
                return true
            end) then
                state.hooked[name] = true
            end
        end
    end
end

local ev = type(CreateFrame) == 'function' and CreateFrame('Frame') or nil
if ev then
    ev:RegisterEvent('ADDON_LOADED')
    ev:RegisterEvent('PLAYER_ENTERING_WORLD')
    ev:SetScript('OnEvent', function(_, event)
        hookShop()
        D.Rescan()
        D.Refresh(event)
        D.ShopCheck(event)
    end)
end
hookShop()
if type(hooksecurefunc) == 'function' then
    -- windows that go through the panel manager without a hook from FFSpan yet (first open of a LoD one)
    pcall(hooksecurefunc, 'ShowUIPanel', function() D.Rescan() D.Refresh('panel shown') end)
    pcall(hooksecurefunc, 'HideUIPanel', function() D.Refresh('panel hidden') end)
end

-- ------------------------------------------------------------------------------- /ffspan dismiss
local prior = SlashCmdList and SlashCmdList['FFSPAN']
if SlashCmdList then
    SlashCmdList['FFSPAN'] = function(message)
        local arg = type(message) == 'string' and message:match('^%s*dismiss%s*(.-)%s*$')
        if not arg then
            if prior then prior(message) end
            return
        end
        arg = arg:lower()
        local d = db()
        if (arg == 'on' or arg == 'off') and d then d.enabled = (arg == 'on') end
        D.Refresh('slash ' .. arg)
        local f = state.frame
        print(('|cff00e5ffFFSpan|r tap-outside-to-close: %s; catcher %s; newest open: %s; shop %s'):format(
            D.Enabled() and 'ON' or 'OFF', (f and call(f, 'IsShown')) and 'up' or 'down',
            tostring(D.Newest() or 'none'), D.ShopShown() and 'open' or 'closed'))
    end
end
