--[[
    FFSpan_Micro -- gives Blizzard's micro menu back to Blizzard while the home screen is on.

    Why: ConsolePort_Bar's toolbar has a "Micro Menu" option (layout Toolbar.menu.micromenu,
    default ON, "Take ownership of, and move the micro menu buttons to the toolbar" --
    Model/Interface.lua:425). With it on, PopoutFrame:MoveMicroButtons (View/Toolbar/Toolbar.lua
    :371) re-parents every micro button into the toolbar's popout, which sits clipped and slid
    out of view at the bottom centre of the TOP screen. Two things leak out of that on the Thor:
      - HelpTips. MainMenuMicroButton_ShowAlert (Blizzard_MicroMenu/Mainline) anchors its
        HelpTip TopEdgeCenter to the micro button itself, and ConsolePort deliberately keeps the
        buttons ignoring the popout's alpha "to show help tip frames when the micro buttons are
        hidden by clipping" (Toolbar.lua:411-418). So "You have unopened items in your
        collection" pops up over the centre ConsolePort controls.
      - The top strip of the clipped buttons shows above the bottom edge of the top screen.
    Meanwhile Blizzard's own MicroMenu, which FFScale places on the home screen as part of the
    info deck (by design the real micro menu lives on the bottom screen), stays empty (1x1).

    How: every ConsolePort path that takes the buttons is gated on `popout.props.micromenu`
    (MoveMicroButtons :373, OnOverrideMicroMenuPosition :428, OnUpdateMicroButtonsParent :437).
    Claim() swaps `popout.props` for a proxy that reads `micromenu = false` and falls through to
    the real table for everything else, so ConsolePort itself stands down; the saved layout
    table (ConsolePort_BarLayout, per character) is never written. The buttons then go back into
    Blizzard's MicroMenu exactly the way ConsolePort puts them back when Blizzard overrides the
    micro menu position (Toolbar.lua:427-434: SetParent(MicroMenu) + Layout), and
    MicroMenuContainer:Layout() re-sizes the Edit Mode system around them. Native buttons,
    native layout, native HelpTips -- nothing hidden, nothing restyled here.

    ConsolePort re-applies its props from the layout whenever they change (CPToolbar:SetProps ->
    PopoutFrame:SetProps, which resets `self.props` and re-takes the buttons), so a post-hook on
    the popout's SetProps re-claims while the home screen is on.

    Release() is the exact undo: the original props table goes back and ConsolePort's own
    MoveMicroButtons takes the buttons again, re-discovering them from MicroMenu's children the
    same way it did at load (RefreshMicroButtons, Toolbar.lua:300).

    Known limit: on non-Retail clients ConsolePort re-skins the buttons the first time it takes
    them (Toolbar.lua:382-386, Retail-style atlas art). That happens at ConsolePort_Bar's own
    ADDON_LOADED, before any FFSpan code has run, so the handed-back buttons keep that skin.

    Public API (the caller owns WHEN -- FFSpan_Home claims on activate, releases on teardown):
      FFSpan.MicroMenu.Claim(reason)   -> ok, detail
      FFSpan.MicroMenu.Release(reason) -> ok, detail
      FFSpan.MicroMenu.Status()        -> { owner, buttons, claimed, detail }
      FFSpan.MicroMenuUnits()          -> { menuW, menuH, eyeW, eyeH, buttons } in UI units at
                                          scale 1 (what FFScale sizes the home slot from), or nil
--]]

local S = _G.FFSpan
if type(S) ~= 'table' then
    S = {}
    _G.FFSpan = S
end
S.MicroMenu = S.MicroMenu or {}
local M = S.MicroMenu

-- claimed: the proxy is installed and the buttons are Blizzard's; orig/proxy: the popout's own
-- props table and FFSpan's stand-in; buttons: ConsolePort's button->layoutIndex map, held while the
-- popout's copy is emptied (so its SetActive alpha pass has nothing of Blizzard's to touch).
local state = { claimed = false, orig = nil, proxy = nil, buttons = nil, hooked = nil, last = nil }
M.state = state

local function safe(fn, ...)
    local ok, a, b = pcall(fn, ...)
    if ok then return a, b end
    return nil
end

local function popout()
    local tb = _G.ConsolePortToolbar
    local c = type(tb) == 'table' and tb.PopoutContainer
    local p = type(c) == 'table' and c.PopoutFrame
    if type(p) ~= 'table' or type(p.props) ~= 'table' then return nil end
    if type(p.MoveMicroButtons) ~= 'function' then return nil end
    return p
end

local function blizzardMenu()
    local menu = _G.MicroMenu
    if type(menu) ~= 'table' or type(menu.GetChildren) ~= 'function' then return nil end
    return menu
end

local function relayout()
    local container = _G.MicroMenuContainer
    if type(container) == 'table' and type(container.Layout) == 'function' then
        safe(container.Layout, container)   -- runs MicroMenu:Layout() and re-sizes the system
        return
    end
    local menu = blizzardMenu()
    if menu and type(menu.Layout) == 'function' then safe(menu.Layout, menu) end
end

-- WHICH buttons are Blizzard's micro buttons. Not ConsolePort's `p.MicroButtons`: that map is
-- rebuilt from MicroMenu's children on EVERY MoveMicroButtons (Toolbar.lua:300-322, :374), and
-- once the buttons have left MicroMenu the rebuild finds none -- on Retail, which has no
-- MICRO_BUTTONS global to fall back on, it comes back EMPTY while the buttons are still parented
-- to the popout (the device, 09-25 09:43: claim ran, "0 buttons"). So the source of truth is
-- Blizzard's own list: MicroMenu:GenerateButtonInfos() is the table InitializeButtons walks
-- (Shared/MicroMenuContainer.lua), and AddButton stamps layoutIndex on each button it actually
-- added, which is what separates them from any a game rule left out.
local function buttonMap(p)
    local map = {}
    if type(state.buttons) == 'table' then
        for button, index in pairs(state.buttons) do map[button] = index end
    end
    local menu = blizzardMenu()
    if next(map) == nil and menu and type(menu.GenerateButtonInfos) == 'function' then
        local infos = safe(menu.GenerateButtonInfos, menu)
        for _, info in ipairs(type(infos) == 'table' and infos or {}) do
            local b = type(info) == 'table' and info.button
            if type(b) == 'table' and b.layoutIndex then map[b] = b.layoutIndex end
        end
    end
    -- ConsolePort's map is right whenever it is not empty (straight after its first take)
    if next(map) == nil and p and type(p.MicroButtons) == 'table' then
        for button, index in pairs(p.MicroButtons) do map[button] = index end
    end
    -- older clients: whatever sits in MicroMenu or the popout with a layoutIndex, minus the
    -- popout's own buttons (its eye / config / exit-vehicle are laid out the same way)
    if next(map) == nil then
        local own = p and { [p.Eye or 0] = true, [p.Config or 0] = true, [p.ExitVehicle or 0] = true,
                            [p.Divider1 or 0] = true } or {}
        for _, parent in ipairs({ menu or false, p or false }) do
            local kids = parent and safe(function() return { parent:GetChildren() } end)
            for _, child in ipairs(kids or {}) do
                if type(child) == 'table' and child.layoutIndex and not own[child] then
                    map[child] = child.layoutIndex
                end
            end
        end
    end
    if next(map) == nil and type(_G.MICRO_BUTTONS) == 'table' then
        for i, name in ipairs(_G.MICRO_BUTTONS) do
            local b = _G[name]
            if type(b) == 'table' then map[b] = b.layoutIndex or i end
        end
    end
    return map
end

local function giveBack(p)
    local menu = blizzardMenu()
    if not menu then return false, 'no Blizzard MicroMenu' end
    local map = buttonMap(p)
    local total, moved = 0, 0
    for button, index in pairs(map) do
        total = total + 1
        if safe(button.GetParent, button) ~= menu then
            safe(button.SetParent, button, menu)
            moved = moved + 1
        end
        safe(button.SetIgnoreParentAlpha, button, false)
        if button.layoutIndex == nil and type(index) == 'number' then button.layoutIndex = index end
        safe(button.ClearAllPoints, button)
    end
    state.buttons = next(map) and map or nil
    if p then
        p.MicroButtons = {}
        -- ConsolePort's own path, now a no-op apart from hiding its divider, then its own
        -- Layout so the popout shrinks to what is left in it (eye, config, exit vehicle)
        safe(p.MoveMicroButtons, p)
        if type(p.Layout) == 'function' then safe(p.Layout, p) end
    end
    relayout()
    -- finding nothing is a failure to report, not a success: the proxy stays (ConsolePort stays
    -- stood down) and Release still undoes it, but the caller sees why nothing moved
    return total > 0, ('%d buttons to MicroMenu (%d moved)'):format(total, moved)
end

local function claimFrom(p)
    local props = p.props
    if props == state.proxy and state.proxy then
        return giveBack(p)
    end
    if not props.micromenu then
        -- the player (or the layout) turned ConsolePort's option off: nothing to take back from
        state.orig, state.proxy = nil, nil
        return true, 'ConsolePort does not own the micro menu'
    end
    state.orig = props
    state.proxy = setmetatable({ micromenu = false }, { __index = props })
    p.props = state.proxy
    return giveBack(p)
end

local function hookSetProps(p)
    if state.hooked == p or type(p.SetProps) ~= 'function' or type(hooksecurefunc) ~= 'function' then
        return
    end
    state.hooked = p
    hooksecurefunc(p, 'SetProps', function(self)
        if not state.claimed then return end
        -- ConsolePort just re-applied its layout: the real props are back and it took the
        -- buttons again. Stand it down once more against whatever table it now uses.
        if self.props ~= state.proxy then
            state.buttons = nil
            local ok, detail = claimFrom(self)
            state.claimed = (ok and state.proxy ~= nil) and true or false
            state.last = 'reclaimed after ConsolePort SetProps: ' .. tostring(detail)
        end
    end)
end

function M.Claim(reason)
    local p = popout()
    if not p then
        state.last = 'no ConsolePort toolbar popout'
        return false, state.last
    end
    hookSetProps(p)
    local ok, detail = claimFrom(p)
    state.claimed = (ok and state.proxy ~= nil) and true or false
    state.last = tostring(reason) .. ': ' .. tostring(detail)
    return ok, detail
end

function M.Release(reason)
    if not state.claimed and not state.orig then return true, 'nothing claimed' end
    local p = popout()
    local orig, held = state.orig, state.buttons
    state.claimed = false
    state.orig, state.proxy, state.buttons = nil, nil, nil
    if p and orig then
        if p.props ~= orig then p.props = orig end
        if type(held) == 'table' and (type(p.MicroButtons) ~= 'table' or next(p.MicroButtons) == nil) then
            p.MicroButtons = held
        end
        -- ConsolePort takes them back its own way (RefreshMicroButtons re-discovers them)
        if p.props.micromenu then safe(p.MoveMicroButtons, p) end
    end
    relayout()
    state.last = tostring(reason) .. ': released to ConsolePort'
    return true, state.last
end

function M.Status()
    local menu = blizzardMenu()
    local p = popout()
    local total, inMenu, inPopout = 0, 0, 0
    for button in pairs(buttonMap(p)) do
        total = total + 1
        local parent = safe(button.GetParent, button)
        if menu and parent == menu then inMenu = inMenu + 1
        elseif p and parent == p then inPopout = inPopout + 1 end
    end
    local owner = (inMenu > 0 and inPopout == 0) and 'blizzard'
        or (inPopout > 0 and inMenu == 0) and 'consoleport'
        or (total == 0) and 'none' or 'mixed'
    return { owner = owner, buttons = total, inMenu = inMenu, inPopout = inPopout,
             claimed = state.claimed, detail = state.last }
end

-- The micro menu's natural size in UI units at scale 1, measured off the live frames once the
-- buttons are Blizzard's. MicroMenu is a GridLayoutFrame, so its own width/height already are
-- the laid-out row; the queue eye sits beside it with a fixed offset (MicroMenuContainer:Layout
-- adds |offsetX|). Nil while ConsolePort still holds the buttons -- an empty 1x1 menu is not a
-- measurement.
function S.MicroMenuUnits()
    local menu = blizzardMenu()
    if not menu then return nil end
    local st = M.Status()
    if st.owner ~= 'blizzard' then return nil end
    local w = safe(menu.GetWidth, menu)
    local h = safe(menu.GetHeight, menu)
    if type(w) ~= 'number' or type(h) ~= 'number' or w <= 2 or h <= 2 then return nil end
    local eyeW, eyeH = 0, 0
    local eye = _G.QueueStatusButton
    if type(eye) == 'table' and type(eye.GetWidth) == 'function' then
        eyeW = safe(eye.GetWidth, eye) or 0
        eyeH = safe(eye.GetHeight, eye) or 0
        local ok, _, _, _, ox = pcall(eye.GetPoint, eye, 1)
        if ok and type(ox) == 'number' then eyeW = eyeW + math.abs(ox) end
    end
    return { menuW = w, menuH = h, eyeW = eyeW, eyeH = eyeH, buttons = st.inMenu }
end
