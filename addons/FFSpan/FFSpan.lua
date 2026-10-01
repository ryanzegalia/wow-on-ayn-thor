--[[
    FFSpan -- my own tiny addon. Gates the third-party addon Offhand (source:
    https://github.com/N4UX-GIT/Offhand-DualMonitor, all rights reserved / personal use
    only) on or off depending on whether this WoW client was launched "spanned"
    (AYN Thor "span" GameNative build, one Wine virtual monitor at 3160x1080) or normal
    (1920x1080). FFSpan does NOT depend on Offhand, does NOT modify any Offhand file, and
    is a no-op if Offhand is not installed.

    Design:
      - Offhand's SavedVariables are OffhandDB.profiles[<name>] (account-wide) and
        OffhandCharDB.activeProfile (per-character, picks which profile name to use).
        Offhand.Core.Config.lua:InitializeConfig() resolves the active profile table and
        assigns it to Offhand.db; Offhand.Core.Viewport.lua's Apply/Reset/ApplyGlobalScale
        (the only place viewport/HUD-scale is actually changed) all gate on
        Offhand.db.enabled being truthy.
      - Offhand.Core.Config.lua's CopyDefaults() only fills a key that is MISSING
        (`elseif dst[k] == nil`) -- it never overwrites an existing key, but its
        defaultSettings.enabled = true. So if FFSpan does not explicitly set `enabled`
        before Offhand's own InitializeConfig() runs, Offhand defaults itself back ON.
      - Both addons listen for ADDON_LOADED. WoW loads addons without dependencies in
        alphabetical folder order, and "FFSpan" < "Offhand", so FFSpan's Lua executes (and
        registers its own ADDON_LOADED listener) before Offhand's Init.lua executes (and
        registers Offhand's own eventFrame). When Offhand's own ADDON_LOADED(arg1="Offhand")
        event later fires, frames are notified in registration order, so FFSpan's handler
        runs first and writes OffhandDB.profiles[<active>].enabled BEFORE Offhand's own
        ADDON_LOADED handler calls InitializeConfig() and reads it. This is the whole trick
        -- no timers, no polling, no hooking Offhand's functions.
      - At that point OffhandDB (the raw SavedVariables table) is already loaded as a
        global -- SavedVariables load before ADDON_LOADED fires for the owning addon -- so
        it's safe to read/create it directly.
--]]

local ADDON_NAME = ...
local OFFHAND_NAME = "Offhand"
local SPAN_ASPECT_THRESHOLD = 2.4 -- 3160/1080 = 2.93 (spanned) vs 1920/1080 = 1.78 (normal)

local FFSpan = CreateFrame("Frame", "FFSpanEventFrame")
_G.FFSpan = FFSpan

local function Print(msg)
    local frame = DEFAULT_CHAT_FRAME or (ChatFrame1 and ChatFrame1:IsShown() and ChatFrame1)
    if frame then
        frame:AddMessage("|cff00e5ff[FFSpan]|r " .. tostring(msg))
    end
end

-- Physical screen size, with a fallback for clients/situations where
-- GetPhysicalScreenSize is unavailable or errors.
local function GetPhysicalSize()
    if GetPhysicalScreenSize then
        local ok, w, h = pcall(GetPhysicalScreenSize)
        if ok and w and h and w > 0 and h > 0 then
            return w, h
        end
    end
    local scale = (UIParent and UIParent.GetEffectiveScale and UIParent:GetEffectiveScale()) or 1
    local w = GetScreenWidth and (GetScreenWidth() * scale) or 1920
    local h = GetScreenHeight and (GetScreenHeight() * scale) or 1080
    return w, h
end

local function IsSpanned()
    local w, h = GetPhysicalSize()
    if not w or not h or h == 0 then return false end
    return (w / h) >= SPAN_ASPECT_THRESHOLD
end
FFSpan.IsSpanned = IsSpanned
FFSpan.GetPhysicalSize = GetPhysicalSize

local function IsOffhandLoaded()
    if C_AddOns and C_AddOns.IsAddOnLoaded then
        return C_AddOns.IsAddOnLoaded(OFFHAND_NAME) and true or false
    end
    if IsAddOnLoaded then
        return IsAddOnLoaded(OFFHAND_NAME) and true or false
    end
    return _G.Offhand ~= nil
end

local function GetActiveProfileName()
    if type(OffhandCharDB) == "table" and OffhandCharDB.activeProfile then
        return OffhandCharDB.activeProfile
    end
    return "Default" -- mirrors Offhand's own Config.lua:82 fallback
end

-- Writes ONLY the `enabled` key into the active OffhandDB profile. Creates the
-- profiles table / the named profile table if missing (so a completely fresh
-- Offhand install still gets gated correctly on first login), but never touches
-- or deletes any other key -- Offhand's own CopyDefaults() fills the rest.
local function SetOffhandEnabledFlag(want)
    -- 2026-09-23: span mode is centre-game now (FFSpan_Layout.lua centres WorldFrame; the fork shows
    -- canvas x 620..2540 on the top screen). Offhand's left-game/right-deck layout no longer fits, and
    -- it is parked out of AddOns. If it is ever reinstalled, keep it OFF in both launches.
    want = false
    if type(OffhandDB) ~= "table" then OffhandDB = {} end
    if type(OffhandDB.profiles) ~= "table" then OffhandDB.profiles = {} end
    local name = GetActiveProfileName()
    if type(OffhandDB.profiles[name]) ~= "table" then OffhandDB.profiles[name] = {} end
    OffhandDB.profiles[name].enabled = want

    -- Rare-timing safety net: if Offhand already finished InitializeConfig (its live
    -- Offhand.db is the very same table just written), keep the in-memory copy in sync too.
    if _G.Offhand and _G.Offhand.db and _G.Offhand.db == OffhandDB.profiles[name] then
        _G.Offhand.db.enabled = want
    end
    return want
end
FFSpan.SetOffhandEnabledFlag = SetOffhandEnabledFlag

-- In-world marker for the span fork's glue-mode probe (the fork, patches/gamenative/ in this repo,
-- SpanDisplayController.GlueProbe). The fork samples the canvas's bottom-right corner every few
-- frames: a magenta square there = the in-world UI exists, so the screens stay split (world on
-- top, deck below); no square = login / character select / loading screen, so the fork shows the
-- centred menu box on the top screen only and blanks the bottom one. Addons never run on glue
-- screens, so the square's absence is exact. Parentless (Alt-Z hides UIParent, not this) and at
-- TOOLTIP strata so nothing covers it. Hidden during loading screens and pre-rendered movies so
-- those also go top-only. 6 physical pixels, only when spanned.
local MARKER_PX = 6
local marker
local loadingScreen, moviePlaying = false, false

local function UpdateMarker()
    local want = IsSpanned() and not loadingScreen and not moviePlaying
    if not want then
        if marker then marker:Hide() end
        return
    end
    if not marker then
        marker = CreateFrame("Frame", "FFSpanMarker")
        marker:SetFrameStrata("TOOLTIP")
        marker:SetFrameLevel(9999)
        local tex = marker:CreateTexture(nil, "OVERLAY")
        tex:SetAllPoints()
        tex:SetColorTexture(1, 0, 1, 1)
    end
    -- A parentless frame at scale 1 lives in the 768-unit-tall base coordinate space.
    local _, ph = GetPhysicalSize()
    local size = MARKER_PX * 768 / ph
    marker:SetScale(1)
    marker:SetSize(size, size)
    marker:ClearAllPoints()
    marker:SetPoint("BOTTOMRIGHT")
    marker:Show()
end
FFSpan.UpdateMarker = UpdateMarker

FFSpan:RegisterEvent("ADDON_LOADED")
FFSpan:RegisterEvent("DISPLAY_SIZE_CHANGED")
FFSpan:RegisterEvent("PLAYER_LOGIN")
FFSpan:RegisterEvent("LOADING_SCREEN_ENABLED")
FFSpan:RegisterEvent("LOADING_SCREEN_DISABLED")
FFSpan:RegisterEvent("PLAY_MOVIE")

FFSpan:SetScript("OnEvent", function(self, event, arg1)
    if event == "ADDON_LOADED" then
        if arg1 == OFFHAND_NAME then
            SetOffhandEnabledFlag(IsSpanned())
        end
    elseif event == "LOADING_SCREEN_ENABLED" or event == "LOADING_SCREEN_DISABLED" then
        loadingScreen = event == "LOADING_SCREEN_ENABLED"
        UpdateMarker()
    elseif event == "PLAY_MOVIE" then
        if not MovieFrame then return end
        moviePlaying = true
        UpdateMarker()
        if not self.movieHooked then
            self.movieHooked = true
            MovieFrame:HookScript("OnHide", function()
                moviePlaying = false
                UpdateMarker()
            end)
        end
        -- Never leave the marker hidden in-world: a movie that never showed un-hides it.
        if C_Timer then
            C_Timer.After(1, function()
                if moviePlaying and not MovieFrame:IsShown() then
                    moviePlaying = false
                    UpdateMarker()
                end
            end)
        end
    elseif event == "PLAYER_LOGIN" then
        -- Belt-and-suspenders: re-assert right before Offhand's own PLAYER_LOGIN handler
        -- (which calls ApplyFullLayout) runs, in case anything touched OffhandDB between
        -- ADDON_LOADED and now. Cheap table write, no frame positioning here.
        if IsOffhandLoaded() then
            SetOffhandEnabledFlag(IsSpanned())
        end
        UpdateMarker()
    elseif event == "DISPLAY_SIZE_CHANGED" then
        UpdateMarker()
        if not IsOffhandLoaded() then return end
        local spanned = IsSpanned()
        SetOffhandEnabledFlag(spanned)
        if _G.Offhand and _G.Offhand.ApplyFullLayout then
            if InCombatLockdown and InCombatLockdown() then
                Print("Screen size changed -- /reload to let Offhand pick it up (in combat).")
            else
                _G.Offhand:ApplyFullLayout()
            end
        else
            Print("Screen size changed -- /reload to let Offhand pick it up.")
        end
    end
end)

SLASH_FFSPAN1 = "/ffspan"
SlashCmdList["FFSPAN"] = function()
    local w, h = GetPhysicalSize()
    local spanned = IsSpanned()
    local offhandLoaded = IsOffhandLoaded()
    local offhandEnabled = false
    if offhandLoaded then
        if _G.Offhand and _G.Offhand.db then
            offhandEnabled = _G.Offhand.db.enabled and true or false
        elseif type(OffhandDB) == "table" and type(OffhandDB.profiles) == "table" then
            local prof = OffhandDB.profiles[GetActiveProfileName()]
            offhandEnabled = prof and prof.enabled and true or false
        end
    end
    Print(string.format("physical %dx%d, spanned=%s, Offhand loaded=%s, Offhand enabled=%s",
        w or 0, h or 0,
        spanned and "yes" or "no",
        offhandLoaded and "yes" or "no",
        offhandEnabled and "yes" or "no"))
end
