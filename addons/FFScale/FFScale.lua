-- FFScale -- Edit Mode scaling + placement pass for the 6" AYN Thor panel.
--
-- v1.6: FFScale is now the SINGLE owner of the Edit Mode layout for EVERY screen geometry
-- (decided 2026-09-23). One function picks the layout:
--     * every non-home case (1920 stock, 3160 centre-game, no FFSpan, Classic) -> 'Thor6in',
--       byte-for-byte what v1.5.1 did. Frozen by the golden tests in tests/golden/.
--     * FFSpan.HomeEnabled() (4400x1080 dual-screen home mode) -> 'ThorSpanHome', CHARACTER
--       scope, cloned from the identified Thor6in, with the home/game regions derived from
--       FFSpan.HomeRect()/GameRect() -- never hard-coded.
-- FFSpan is looked up AT CALL TIME (FFScale loads first, alphabetically, with no dependencies)
-- and every call into it is pcall-wrapped, so a missing or broken FFSpan degrades to v1.5.1.
-- Public contract: FFScale.ApplyLayout(reason), FFScale.ActiveLayoutName(),
-- FFScale.HomeSlots().
--
-- v1.5: Classic parity with retail (Option B): tracker TOPLEFT 28,-100 at 16pt, chat, tooltip, totem bar.
-- v1.4: per-flavor (Classic branch), MEASURE rect dump + pop-up rects, quiet minimap tooltips.
-- v1.2: full zone layout (ZONES table below). v1.1: do NOT use EditModeManagerFrame:MakeNewLayout(). That mixin indexes
-- self.highestLayoutIndexByType, which Blizzard only populates once the Edit Mode UI has
-- initialised -- so from a headless addon it throws:
--     EditModeManager.lua:1481: attempt to index field 'highestLayoutIndexByType' (a nil value)
-- FFScale goes straight to C_EditMode.SaveLayouts / SetActiveLayout instead.
--
-- IMPORTANT: C_EditMode.GetLayouts() returns ONLY custom layouts. Presets are client-side
-- static data spliced in by EditModeManagerFrame, and activeLayout indexes the COMBINED
-- (presets-then-customs) list. So a custom layout's active index is numPresets + itsRawIndex.
--
-- Setting values are RAW SLIDER INDICES: display = raw * step + minValue.
-- Reversible: preset layouts are never modified. Switch layout in Edit Mode to revert.

local LAYOUT_NAME = 'Thor6in'
local HOME_LAYOUT_NAME = 'ThorSpanHome'

local FFScale = {}
_G.FFScale = FFScale

-- ---------------------------------------------------------------------------------------------
-- FFSpan bridge. FFScale loads BEFORE FFSpan (alphabetical folder order, no dependencies), so
-- FFSpan is never cached at file scope -- every call resolves _G.FFSpan fresh and swallows a
-- broken implementation. No FFSpan, an older FFSpan, or an erroring one all mean "not home".
-- ---------------------------------------------------------------------------------------------
local function span()
    local S = _G.FFSpan
    return type(S) == 'table' and S or nil
end

-- forward: measured with the envelope helpers far below, but READ by the home spec above them
local trackerOverhangPx
-- the chat slot the home spec was LAST built with, so homeSlots publishes the same geometry
local homeChatH, homeChatM, homeChatBottomM
local homeOverflowPx = 0   -- px the tracker's Edit Mode floor runs past the chat slot
local function spanCall(fn, ...)
    local S = span()
    if not (S and type(S[fn]) == 'function') then return nil end
    local ok, v = pcall(S[fn], ...)
    if not ok then return nil end
    return v
end

local function homeEnabled()
    return spanCall('HomeEnabled') == true
end

local function isRect(r)
    return type(r) == 'table' and type(r.x) == 'number' and type(r.y) == 'number'
        and type(r.w) == 'number' and type(r.h) == 'number' and r.w > 0 and r.h > 0
end

-- ---------------------------------------------------------------------------------------------
-- Pixel -> UI unit conversion. Edit Mode replays anchorInfo with frame:SetPoint(...), and
-- SetPoint offsets live in the RECEIVING frame's own scaled space -- so UIParent's effective
-- scale is only right for a system that sits at scale 1 under UIParent (code review finding).
-- `ref` is either the scale multiplier the system is about to be set to (minimap Size 150 ->
-- 1.5) or the global name of the frame to measure; nil means "same scale as UIParent".
-- ---------------------------------------------------------------------------------------------
-- v1.6 integration fix: a frame's EFFECTIVE SCALE is not px-per-unit. WoW's absolute UI space is
-- a fixed 768 units tall whatever the panel is, so px = units * effectiveScale * physicalHeight/768
-- (PixelUtil's pixel->UI-unit factor is 768/physH, and UIParent's scale is the uiScale cvar, which
-- the client clamps at 1.0 -- it can never be the 1.40625 px/unit of a 1080p panel). FFSpan reads
-- FFScale.HomeSlots() as physical px using exactly this q, and FFSpan_Layout's device-verified
-- centre-game core uses the same q = effectiveScale * physH / 768. Both sides must convert alike.
local function pxPerUnit(effScale)
    local ph = 768
    if type(GetPhysicalScreenSize) == 'function' then
        local ok, _, h = pcall(GetPhysicalScreenSize)
        if ok and type(h) == 'number' and h > 0 then ph = h end
    end
    return effScale * ph / 768
end

local function uiScale()
    local s = UIParent and UIParent.GetEffectiveScale and UIParent:GetEffectiveScale()
    if type(s) ~= 'number' or s <= 0 then s = 1 end
    return pxPerUnit(s)
end

local function scaleOf(ref)
    local base = uiScale()
    if type(ref) == 'number' and ref > 0 then return base * ref end
    if type(ref) == 'string' then
        local fr = _G[ref]
        if fr and fr.GetEffectiveScale then
            local ok, v = pcall(fr.GetEffectiveScale, fr)
            if ok and type(v) == 'number' and v > 0 then return pxPerUnit(v) end
        end
    end
    return base
end

local function u(px, ref) return px / scaleOf(ref) end

-- v1.4: one addon, per-flavor behaviour. MoP Classic (project 19, 5.5.4) ships Edit Mode with a
-- smaller system set: FFScaleLog 2026-09-22 22:07 logged "system absent" for ObjectiveTracker,
-- Boss/Arena, HudTooltip, LootFrame, TalkingHead, CooldownViewer and every encounter system, and
-- its bag bar hangs off MainMenuBarArtFrame (there is no MicroButtonAndBagsBar to restore to).
local IS_RETAIL = WOW_PROJECT_ID == WOW_PROJECT_MAINLINE

local function raw(display, minValue, step)
    return (display - minValue) / step
end

-- Screen is 1365.33 x 768 UI units (1920x1080 physical, 1.40625x upscale).
-- Preset put Player at BOTTOMRIGHT/UIParent BOTTOM x=-300 y=250 (measured) -- dead space.
-- Bottom-centre is the gap between the ZL/L and R/ZR glyph clusters.
-- v1.10.0 (09-25 11:30) fitted these around ConsolePort's Crossbar: Triple; at 12:08 I preferred the
-- other one and put it back -- v1.10.1 is the 1.9.0 layout again, with the cluster bar.
local TARGETS = {
    {
        label   = 'ObjectiveTracker TextSize 16, LEFT column under party (Option B, 09-22)',
        system  = Enum.EditModeSystem.ObjectiveTracker,
        index   = nil,
        setting = Enum.EditModeObjectiveTrackerSetting and Enum.EditModeObjectiveTrackerSetting.TextSize,
        value   = raw(16, 12, 1),
        -- Height MUST drop to the minimum: at raw 40 (= 800 units) the frame is taller than the
        -- 768-unit screen, so clamp-to-screen pinned it to y=0 whatever the offset (seen twice 09-22).
        anchor  = { point = 'TOPLEFT', relativeTo = 'UIParent', relativePoint = 'TOPLEFT', offsetX = 28, offsetY = -100 },
        named   = { { settingEnum = 'EditModeObjectiveTrackerSetting', key = 'Height', fallback = 0 } },
    },
    {
        label   = 'UnitFrame(Player) 120% + bottom-centre',
        system  = Enum.EditModeSystem.UnitFrame,
        index   = Enum.EditModeUnitFrameSystemIndices and Enum.EditModeUnitFrameSystemIndices.Player,
        setting = Enum.EditModeUnitFrameSetting and Enum.EditModeUnitFrameSetting.FrameSize,
        value   = raw(120, 100, 5),
        anchor  = { point = 'BOTTOM', relativeTo = 'UIParent', relativePoint = 'BOTTOM', offsetX = 0, offsetY = 48 },
    },
    {
        -- v1.8.9 (device 09-25 09:48, /target player): the target's aura row hung BELOW the frame
        -- and sat on the player portrait, and Blizzard always hangs the target cast bar under the
        -- frame too (TargetSpellBar AdjustPosition: TOPLEFT -> frame BOTTOMLEFT 43,-8), into a
        -- ~20-unit gap it does not fit. Edit Mode's own "Buffs on Top" sends the auras up into the
        -- free space under the cast bar, and 14 more units give the target cast bar its room.
        label   = 'UnitFrame(Target) 120% + stacked above player, buffs on top',
        system  = Enum.EditModeSystem.UnitFrame,
        index   = Enum.EditModeUnitFrameSystemIndices and Enum.EditModeUnitFrameSystemIndices.Target,
        setting = Enum.EditModeUnitFrameSetting and Enum.EditModeUnitFrameSetting.FrameSize,
        value   = raw(120, 100, 5),
        anchor  = { point = 'BOTTOM', relativeTo = 'UIParent', relativePoint = 'BOTTOM', offsetX = 0, offsetY = 136 },
        named   = { { settingEnum = 'EditModeUnitFrameSetting', key = 'BuffsOnTop', fallback = 1 } },
    },
    {
        label   = 'Bags -> RESTORE original anchor (retail: MicroButtonAndBagsBar; Classic: its preset)',
        system  = Enum.EditModeSystem.Bags,
        index   = nil,
        setting = nil,
        anchor  = IS_RETAIL
            and { point = 'TOPRIGHT', relativeTo = 'MicroButtonAndBagsBar', relativePoint = 'TOPRIGHT', offsetX = 0, offsetY = 10 }
            or  { point = 'BOTTOMRIGHT', relativeTo = 'MainMenuBarArtFrame', relativePoint = 'BOTTOMRIGHT', offsetX = -4, offsetY = 2 },
    },
    {
        label   = 'Minimap Size 100 -> 80 pct',
        system  = Enum.EditModeSystem.Minimap,
        index   = nil,
        setting = Enum.EditModeMinimapSetting and Enum.EditModeMinimapSetting.Size,
        value   = raw(80, 50, 10),
        -- off the bezel: zone bar, calendar and tracking icons were flush against the right edge
        anchor  = { point = 'TOPRIGHT', relativeTo = 'UIParent', relativePoint = 'TOPRIGHT', offsetX = -14, offsetY = -10 },
    },
}

-- v1.2 ZONE LAYOUT (Option B, picked 2026-09-22: tracker in the LEFT column, boss top-right). Designed on a layout
-- mockup I drew first. Offsets are UI units; unit-frame offsets are design intent and
-- still need re-measuring on device for their own invisible padding.
-- systemIndex values come from the FFScale dump, not guessed:
--   UnitFrame 1 Player 2 Target 3 Focus 4 Party 5 Raid 6 Boss 7 Arena 8 Pet
--   AuraFrame 1 Buffs 2 Debuffs 3 External defensives; CooldownViewer 1 Essential 2 Utility 3 BuffIcon 4 BuffBar
local function A(point, rel, relPoint, x, y)
    return { point = point, relativeTo = rel or 'UIParent', relativePoint = relPoint or point, offsetX = x, offsetY = y }
end
local function sys(name) return Enum.EditModeSystem and Enum.EditModeSystem[name] end
-- An action bar's systemIndex BY NAME; nil (-> 'SKIP (system absent)') where the enum lacks it.
local function ABI(name)
    local e = Enum.EditModeActionBarSystemIndices
    return e and e[name] or nil
end
-- A setting resolved BY NAME at run time, so a renamed enum is logged as a skip instead of
-- silently writing the wrong index (raw slider indices have caused this bug before).
local function named(settingEnum, key, valueEnum, valueKey, fallback)
    return { settingEnum = settingEnum, key = key, valueEnum = valueEnum, valueKey = valueKey, fallback = fallback }
end
local GROW_RIGHT = named('EditModeAuraFrameSetting', 'IconDirection', 'AuraFrameIconDirection', 'Right', 1)
local CD_HIDDEN  = named('EditModeCooldownViewerSetting', 'VisibleSetting', 'CooldownViewerVisibleSetting', 'Hidden', nil)

local ZONES = {
    -- Zone A: combat centre
    { label = 'CastBar above target',          system = sys('CastBar'),  anchor = A('BOTTOM', nil, nil, 0, 270) },
    { label = 'Essential cooldowns above cast', system = sys('CooldownViewer'), index = 1, anchor = A('BOTTOM', nil, nil, 0, 296) },
    { label = 'Utility cooldowns hidden',      system = sys('CooldownViewer'), index = 2, named = { CD_HIDDEN } },
    { label = 'BuffIcon viewer hidden',        system = sys('CooldownViewer'), index = 3, named = { CD_HIDDEN } },
    { label = 'BuffBar viewer hidden',         system = sys('CooldownViewer'), index = 4, named = { CD_HIDDEN } },
    { label = 'Pet left of target',            system = sys('UnitFrame'), index = 8, anchor = A('BOTTOM', nil, nil, -194, 202) },
    { label = 'Focus left of target',          system = sys('UnitFrame'), index = 3, anchor = A('BOTTOM', nil, nil, -206, 254) },
    { label = 'LossOfControl alone at centre', system = sys('LossOfControl'), anchor = A('CENTER', nil, nil, 0, 21) },
    { label = 'ExtraAbilities right of target', system = sys('ExtraAbilities'), anchor = A('BOTTOM', nil, nil, 167, 199) },
    -- v1.8.8: the class bars sat at Blizzard's default, BETWEEN ConsolePort's D-pad and L/ZL
    -- clusters (09-25 dump: StanceBar x565-697 against PADDRIGHT's modifier buttons 529-621, ZL
    -- 601-682 and L's 636-709), so the druid forms collided with every ring that fanned out.
    -- They go ABOVE the left cluster group instead -- clear of the highest modifier button
    -- (PADDUP's, top edge y771 px) at any count of buttons -- stance/possess on top of the
    -- group, pet just above them. ActionBar indices by NAME: a flavor without one SKIPs it.
    { label = 'StanceBar above the left clusters', system = sys('ActionBar'), index = ABI('StanceBar'),
      anchor = A('BOTTOMLEFT', nil, 'BOTTOM', -478, 231) },
    { label = 'PossessBar shares the stance slot', system = sys('ActionBar'), index = ABI('PossessActionBar'),
      anchor = A('BOTTOMLEFT', nil, 'BOTTOM', -478, 231) },
    { label = 'PetActionBar above the stance slot', system = sys('ActionBar'), index = ABI('PetActionBar'),
      anchor = A('BOTTOMLEFT', nil, 'BOTTOM', -478, 263) },
    { label = 'VehicleLeave above extra',      system = sys('VehicleLeaveButton'), anchor = A('BOTTOM', nil, nil, 160, 277) },
    -- Zone C: group column (party/raid already anchor to CompactRaidFrameManager on the left; tracker sits under them)
    { label = 'Boss frames under minimap',     system = sys('UnitFrame'), index = 6, anchor = A('TOPRIGHT', nil, nil, -10, -206) },
    { label = 'Arena frames share boss slot',  system = sys('UnitFrame'), index = 7, anchor = A('TOPRIGHT', nil, nil, -10, -206) },
    -- Zone D: navigation / inventory
    { label = 'Durability left of minimap',    system = sys('DurabilityFrame'), anchor = A('TOPRIGHT', nil, nil, -178, -21) },
    { label = 'VehicleSeats left of minimap',  system = sys('VehicleSeatIndicator'), anchor = A('TOPRIGHT', nil, nil, -178, -21) },
    { label = 'Tooltip above right glyphs',    system = sys('HudTooltip'), anchor = A('BOTTOMRIGHT', nil, nil, -9, 206) },
    -- Zone E: status (top-left) + encounter lane (top centre)
    { label = 'Buffs top-left, grow right',    system = sys('AuraFrame'), index = 1, anchor = A('TOPLEFT', nil, nil, 24, -12), named = { GROW_RIGHT } },
    { label = 'Debuffs under buffs, grow right', system = sys('AuraFrame'), index = 2, anchor = A('TOPLEFT', nil, nil, 24, -52), named = { GROW_RIGHT } },
    { label = 'External defensives top',       system = sys('AuraFrame'), index = 3, anchor = A('TOP', nil, nil, 0, -10) },
    { label = 'Boss warning line 1',           system = sys('EncounterEvents'), index = 2, anchor = A('TOP', nil, nil, 0, -47) },
    { label = 'Boss warning line 2',           system = sys('EncounterEvents'), index = 3, anchor = A('TOP', nil, nil, 0, -81) },
    { label = 'Boss warning line 3',           system = sys('EncounterEvents'), index = 4, anchor = A('TOP', nil, nil, 0, -115) },
    { label = 'TimerBars under warnings',      system = sys('TimerBars'), anchor = A('TOP', nil, nil, 0, -152) },
    { label = 'EncounterBar top lane',         system = sys('EncounterBar'), anchor = A('TOP', nil, nil, 0, -235) },
    { label = 'Archaeology shares encounter slot', system = sys('ArchaeologyBar'), anchor = A('TOP', nil, nil, 0, -235) },
    { label = 'Boss timeline bottom of lane',  system = sys('EncounterEvents'), index = 1, anchor = A('TOP', nil, nil, 0, -279) },
    { label = 'TalkingHead top centre',        system = sys('TalkingHeadFrame'), anchor = A('TOP', nil, nil, 0, -10) },
    { label = 'Loot right of character',       system = sys('LootFrame'), anchor = A('CENTER', nil, nil, 256, 24) },
}
for _, t in ipairs(ZONES) do table.insert(TARGETS, t) end

-- v1.5 CLASSIC PARITY (decided 2026-09-22): Option B on Classic too, near-identical to retail.
-- Classic lacks the retail systems for several of these, so each gets the nearest Classic
-- equivalent at the retail coordinates. Retail numbers come from retail's Thor6in + FFDiag.
local CLASSIC_TARGETS = {
    -- retail's essential-cooldown row sits there; the totem bar (shaman totems, druid Wild
    -- Mushroom) is Classic's only bar of that kind, and its preset spot is behind the player frame
    { label = 'Totem bar where retail keeps essential cooldowns', system = sys('TotemActionBar'),
      anchor = A('BOTTOM', nil, nil, 0, 296) },
    -- retail chat measured BOTTOMLEFT +35,+50, 430x170 (FFDiag 09-22); Classic preset is y=110, 430x120
    { label = 'Chat at the retail spot and size (BOTTOMLEFT 35,50, 430x170)', system = sys('ChatFrame'),
      anchor = A('BOTTOMLEFT', nil, nil, 35, 50),
      named = { named('EditModeChatFrameSetting', 'HeightHundreds', nil, nil, 1),
                named('EditModeChatFrameSetting', 'HeightTensAndOnes', nil, nil, 70) } },
}
if not IS_RETAIL then for _, t in ipairs(CLASSIC_TARGETS) do table.insert(TARGETS, t) end end

-- ---------------------------------------------------------------------------------------------
-- v1.6 ThorSpanHome -- the 4400x1080 dual-screen home layout.
--
-- The canvas is 4400x1080: x 0..1240 is the BOTTOM panel (home), x 1240..3160 is the TOP panel
-- (game), x 3160..4400 is shown nowhere. UIParent stays centred on the canvas, and the canvas
-- centre (2200 px) is also the GAME rect's centre -- which is the whole point of 4400.
-- So every Thor6in target that hangs off UIParent BOTTOM / TOP / CENTER is already
-- correct at 4400 and is deliberately left alone: cast bar, cooldown viewers, player/target/
-- pet/focus, loss of control, vehicle leave, encounter events/bar, archaeology, totem bar.
--
-- ONLY the targets anchored to a UIParent LEFT or RIGHT edge move, because those edges are now
-- the far side of the bottom panel and the unshown strip. The home list is therefore
-- TARGETS .. HOME OVERRIDES: applyTarget walks it in order and the later entry wins, so a system
-- with no override keeps its Thor6in placement and nothing is silently dropped.
local HOME = {
    margin          = 16,    -- px, home-region gutter
    gap             = 12,    -- px, minimap -> bags and column -> column
    minimapPct      = 150,   -- display %, stepped down by 10 until the resident bags still fit
    -- v1.8 (decided 15:30): with Baganator owning the bags the minimap gives
    -- up ~15% so the bag box grows. Edit Mode's Size setting steps by 10, and 130 is the legal
    -- step nearest 150 x 0.85 = 127.5.
    minimapPctBags  = 130,
    -- With a bag addon the right column is the bag box, and it has to be wide enough that a full
    -- 202-slot set still fits above the 0.72-equivalent icon floor. 0.70 of the home width is the
    -- narrowest that does at minimapPctBags (see the capacity table in the progress file); the
    -- left column keeps the rest for the tracker and chat.
    bagsColumnPct   = 0.70,
    minimapMinPct   = 80,
    minimapU100     = { w = 198, h = 220 },  -- MinimapCluster envelope in UI units at Size 100.
                                             -- SEED VALUE: re-measure on device -- the live
                                             -- cluster is logged into FFScaleLog.home.measured.
    bagsMinPx       = { w = 380, h = 420 },  -- what the resident bags need; FFSpan owns them
    bottomBarU      = 40,    -- micro menu + bag bar strip height, UI units
    microPct        = 160,   -- v1.9: the micro bar's Edit Mode Size (decided 09-25 10:10)
    chatHPx         = 300,   -- chat height in px; its width fills the left column
    -- v1.7.1: a chat SKIN draws below ChatFrame's own bottom edge. On the device the Glassy
    -- skin's envelope ran to y1164 while ChatFrame1 itself ended at the correct y1064 -- 100 px
    -- off the bottom of the canvas. The chat is lifted by this much so the skin lands inside the
    -- gutter; with no skin installed it simply sits that much higher. Measured, not guessed:
    -- device dump `base`, GlassyFrame envelope y691 h473 vs ChatFrame1 root y764 h300.
    chatSkinPadPx   = 0,     -- v1.8.2: was 100 for Glassy, which never followed ChatFrame1
    trackerTextSize = 16,
}

local homeSlots  -- last published FFScale.HomeSlots(), physical px

-- Anchor relative to UIParent, offsets given in PHYSICAL PX and converted for the receiving frame.
local function HA(point, relPoint, xpx, ypx, ref)
    return { point = point, relativeTo = 'UIParent', relativePoint = relPoint,
             offsetX = u(xpx, ref), offsetY = u(ypx, ref) }
end

-- A setting written by name with an explicit value (resolveNamed uses `fallback` as the value
-- when there is no value enum -- same convention as the ObjectiveTracker Height entry above).
local function nv(settingEnum, key, value) return named(settingEnum, key, nil, nil, value) end

local function floorStep(v, minValue, step, maxValue)
    if v < minValue then v = minValue end
    if maxValue and v > maxValue then v = maxValue end
    return minValue + math.floor((v - minValue) / step) * step
end

-- Returns targets, slots, err. Pure computation: no client mutation, safe to call any time.
local function buildHomeTargets()
    local hr, gr = spanCall('HomeRect'), spanCall('GameRect')
    if not (isRect(hr) and isRect(gr)) then
        return nil, nil, 'FFSpan HomeRect()/GameRect() unavailable or malformed'
    end

    local s  = uiScale()                 -- px per UI unit
    local TU = function(units) return units * s end   -- Thor6in's device-tuned units -> px
    local M, GAP = HOME.margin, HOME.gap
    local HW, HH = hr.w, hr.h
    local GL, GR = gr.x, gr.x + gr.w
    local GCX    = gr.x + gr.w / 2
    local homeCX = hr.x + hr.w / 2

    -- v1.9 (decided 09-25 10:10, "wide, ~160%"): the micro menu is a BAR across the bottom
    -- of the home screen, centred, at Edit Mode Size HOME.microPct -- or smaller if a wider menu
    -- would not fit the width. It is the touch target for every menu, so it gets the size; its
    -- height comes out of BOTH columns (the bags stop above it, the chat sits on top of it).
    -- Measured off the live menu once FFSpan has handed the buttons back from ConsolePort's
    -- toolbar (FFSpan_Micro.lua); seeded from bottomBarU before that.
    local micro = spanCall('MicroMenuUnits')
    local microPct, microHU = HOME.microPct, HOME.bottomBarU * HOME.microPct / 100
    if type(micro) == 'table' and type(micro.menuW) == 'number' and micro.menuW > 0 then
        local eyeW = tonumber(micro.eyeW) or 0
        local fit = 100 * ((HW - 2 * M) / s - eyeW) / micro.menuW
        microPct = floorStep(math.min(HOME.microPct, fit), 70, 5, 200)
        if fit < 70 then
            local why = ('MICRO MENU OVERFLOWS the %.0f px home width: even Size 70 needs %.0f px')
                :format(HW - 2 * M, (micro.menuW * 0.7 + eyeW) * s)
            if R then R[#R + 1] = why end
            FFScaleLog = FFScaleLog or {}
            FFScaleLog.microOverflow = why
        end
        microHU = math.max((tonumber(micro.menuH) or HOME.bottomBarU) * microPct / 100,
                           tonumber(micro.eyeH) or 0)
    end
    -- Minimap size is capped by the space the resident bags need underneath it, not by Edit
    -- Mode's legal maximum (code review finding).
    local bottomBarPx  = microHU * s
    local bottomBarTop = HH - M - bottomBarPx
    -- v1.8: Baganator fits its own grid to whatever box FFSpan measures, so the minimap can
    -- start smaller and hand the difference to the bags.
    local bagAddon = spanCall('BagAddonPresent') == true
    local startPct = bagAddon and HOME.minimapPctBags or HOME.minimapPct
    local pct, clusterW, clusterH, minimapBottom, bagsH = startPct
    while true do
        clusterW      = HOME.minimapU100.w * s * pct / 100
        clusterH      = HOME.minimapU100.h * s * pct / 100
        minimapBottom = M + clusterH
        bagsH         = (bottomBarTop - 8) - (minimapBottom + GAP)
        if bagsH >= HOME.bagsMinPx.h or pct <= HOME.minimapMinPct then break end
        pct = pct - 10
    end

    local colW  = math.max(clusterW, HOME.bagsMinPx.w)   -- right column: minimap + bags
    if bagAddon then
        -- v1.8.1 (decided 2026-09-23): the column is only as wide as THIS
        -- character's bags need at native icon size, floored at the minimap cluster so the right
        -- column stays a clean column under it, and capped at bagsColumnPct. Everything left over
        -- goes to the tracker and chat -- a 30-slot character does not pay for a 202-slot one.
        local boxH = (bottomBarTop - 8) - (minimapBottom + GAP)
        local want = spanCall('BagColumnRequestPx', boxH)
        if type(want) == 'number' and want > 0 then
            colW = math.max(clusterW, math.min(want, HW * HOME.bagsColumnPct))
        else
            colW = math.max(colW, HW * HOME.bagsColumnPct)   -- unknown capacity: assume the worst
        end
    end
    -- measured off the LIVE tracker every time the spec is built, so it tracks a UI change
    local trackerOver = (trackerOverhangPx and trackerOverhangPx('ObjectiveTrackerFrame')) or 0
    local leftW = HW - M - colW - GAP - M                -- left column: tracker over chat
    -- v1.8.2: with Glassy loaded the chat slot is sized to the envelope Glassy
    -- actually draws, measured, rather than to a fixed constant -- its frame is 495 px on the
    -- device against the 300 px reserved before, so nothing could have fitted at any position.
    -- And chatSkinPadPx goes with it: that 100 px was added in v1.7.1 purely to leave room for
    -- Glassy's skin, on the belief that Glassy followed ChatFrame1. It never did. Now that the
    -- envelope is measured and placed directly, the pad has nothing left to do -- for Glassy or
    -- for Blizzard's chat, which never needed it -- so the tracker gets those 100 px back.
    local glassyH = spanCall('GlassyChatHeightPx')
    local glassyM = spanCall('GlassyChatMarginPx')
    local chatPad = HOME.chatSkinPadPx
    -- Glassy's own edge snap sets the smallest margin its chat can keep; FFScale's is 16 px
    local chatM = (type(glassyM) == 'number' and glassyM > M) and glassyM or M
    homeChatM = chatM
    -- v1.9: the chat sits on top of the micro bar, GAP above it. (v1.8.3 had it FLUSH on the panel
    -- edge for Glassy, whose mover snaps to an edge inside 20 units -- MoverFrame.lua:56-65; the
    -- bar keeps it well clear of that snap now, so both chats use the same rule.)
    local chatBottomM = M + bottomBarPx + GAP
    homeChatBottomM = chatBottomM
    -- ...which takes the bar's height out of the chat, not the tracker: the tracker's Edit Mode
    -- Height floors at 400 units (floorStep below), so the chat gets what is left under that
    -- floor. FFSpan fits Glassy's own height setting to this slot the way it fits its width.
    local chatMaxH = HH - M - 400 * s - GAP - chatBottomM - chatPad
    local chatH = (type(glassyH) == 'number' and glassyH > 0) and glassyH or HOME.chatHPx
    chatH = math.max(60 * s, math.min(chatH, chatMaxH))
    homeChatH = chatH
    local chatWU = math.max(120, math.floor(leftW / s))  -- chat width/height settings are in units
    local chatHU = math.max(60, math.floor(chatH / s))
    -- tracker fills the left column from the top gutter down to the chat
    local trackerHPx = (HH - M - chatPad - chatH) - GAP - chatBottomM
    local trackerHU  = floorStep(trackerHPx / s, 400, 10, 1000)
    -- v1.8.3: THE INVARIANT NOBODY WAS CHECKING. floorStep's floor is 400 units, so the
    -- tracker cannot be shorter than 400 * s px however little room is left -- ask for less and it
    -- silently takes more, straight over the top of the chat. v1.8.2 shipped with a full quest
    -- tracker covering the chat's tabs by 22 px and no test noticed, because everything measured
    -- the tracker's CURRENT content instead of the height Edit Mode will give it. Measure the
    -- floor, not the request, and say so out loud when it does not fit: the design rule is that
    -- nothing overlaps, and a silent overlap is how this bug shipped.
    local trackerMaxBottom = M + trackerHU * s   -- floorStep already clamps it at 400
    local chatTop = HH - chatBottomM - chatPad - chatH
    homeOverflowPx = math.max(0, (trackerMaxBottom + GAP) - chatTop)
    if homeOverflowPx > 0 then
        local why = ('LEFT COLUMN OVERFLOWS by %.0f px: a full tracker (%.0f px, the 400-unit Edit '
                  .. 'Mode floor) reaches %.0f and the chat starts at %.0f')
            :format(homeOverflowPx, math.max(trackerHU, 400) * s, trackerMaxBottom, chatTop)
        if R then R[#R + 1] = why end
        FFScaleLog = FFScaleLog or {}
        FFScaleLog.leftColumnOverflow = why
    end

    local T = {}
    local function add(t) T[#T + 1] = t end
    for _, t in ipairs(TARGETS) do add(t) end

    -- ---- HOME region (bottom panel, canvas x 0..1240) ----------------------------------------
    -- v1.7 (review B1): the Size setting does NOT scale the MinimapCluster ROOT --
    -- MinimapClusterMixin:SetEditModeScale scales self.MinimapContainer and the header children
    -- (Blizzard_Minimap/Mainline/Minimap.lua). Edit Mode replays this anchorInfo on the ROOT, so
    -- the offsets convert with the ROOT's own scale, measured, not with pct/100. The pct factor
    -- stays where it belongs: in the cluster SIZE estimate above.
    add{ label = ('HOME Minimap Size %d%%, top-right of the home region'):format(pct),
         system = sys('Minimap'),
         setting = Enum.EditModeMinimapSetting and Enum.EditModeMinimapSetting.Size,
         value = raw(pct, 50, 10),
         anchor = HA('TOPRIGHT', 'TOPLEFT', hr.x + HW - M, -M, 'MinimapCluster') }
    add{ label = ('HOME ObjectiveTracker top-left, Height %d units'):format(trackerHU),
         system = sys('ObjectiveTracker'),
         setting = Enum.EditModeObjectiveTrackerSetting and Enum.EditModeObjectiveTrackerSetting.TextSize,
         value = raw(HOME.trackerTextSize, 12, 1),
         -- + the overhang, so it is the VISIBLE edge that sits on the margin (v1.8.2)
         anchor = HA('TOPLEFT', 'TOPLEFT', hr.x + M + trackerOver, -M),
         named = { nv('EditModeObjectiveTrackerSetting', 'Height', raw(trackerHU, 400, 10)) } }
    -- v1.8.5: Classic has no ObjectiveTracker system (the entry above SKIPs), so placeTracker puts
    -- WatchFrame on this same slot directly. UIParent units, like TRACKER; used on a HOME run only.
    if not IS_RETAIL then
        local slot = HA('TOPLEFT', 'TOPLEFT', hr.x + M + trackerOver, -M)
        HOME.watchTarget = { x = slot.offsetX, y = slot.offsetY, heightUnits = trackerHU }
    end
    add{ label = ('HOME ChatFrame bottom-left, %dx%d units'):format(chatWU, chatHU),
         system = sys('ChatFrame'),
         anchor = HA('BOTTOMLEFT', 'BOTTOMLEFT', hr.x + chatM, chatBottomM + chatPad),
         named = { nv('EditModeChatFrameSetting', 'WidthHundreds', math.floor(chatWU / 100)),
                   nv('EditModeChatFrameSetting', 'WidthTensAndOnes', chatWU % 100),
                   nv('EditModeChatFrameSetting', 'HeightHundreds', math.floor(chatHU / 100)),
                   nv('EditModeChatFrameSetting', 'HeightTensAndOnes', chatHU % 100) } }
    -- v1.9: the micro menu is the bar across the bottom (Size worked out at the top of this
    -- function). v1.8.9 put it under the bags at ~90 %; I wanted it bigger and full width
    -- (09-25 10:10). Centred, so the queue eye beside it stays on the panel too.
    add{ label = ('HOME MicroMenu bar across the bottom, Size %d'):format(microPct),
         system = sys('MicroMenu'),
         anchor = HA('BOTTOM', 'BOTTOMLEFT', homeCX, M),
         named = { nv('EditModeMicroMenuSetting', 'Size', raw(microPct, 70, 5)) } }
    -- v1.8: Baganator draws its own bag-slot buttons, so Blizzard's bag bar is
    -- redundant on the home screen and I wanted the space back. Edit Mode has no
    -- "hidden" flag for the Bags system, so the supported way to get it off the
    -- panel is an Edit Mode ANCHOR into the strip right of the game rect, which is drawn on no
    -- panel at 4400. That is the same mechanism every other system here uses -- no Hide() hooks,
    -- nothing fighting Blizzard. Without Baganator the bar stays where it was: Blizzard's bags
    -- need it.
    if bagAddon then
        add{ label = 'HOME Bags bar parked off-panel (Baganator draws its own bag slots)',
             system = sys('Bags'),
             anchor = HA('BOTTOMLEFT', 'BOTTOMLEFT', GR + M, M), parked = true }
    else
        add{ label = 'HOME Bags bar bottom-right (overrides the Thor6in restore-to-MicroButtonAndBagsBar)',
             system = sys('Bags'),
             anchor = HA('BOTTOMRIGHT', 'BOTTOMLEFT', hr.x + HW - M, M) }
    end
    add{ label = 'HOME StatusTrackingBar above the bottom bar',
         system = sys('StatusTrackingBar'),
         anchor = HA('BOTTOM', 'BOTTOMLEFT', homeCX, M + bottomBarPx + 4) }
    add{ label = 'HOME DurabilityFrame left of the minimap column',
         system = sys('DurabilityFrame'),
         anchor = HA('TOPRIGHT', 'TOPLEFT', hr.x + HW - M - colW - GAP, -M) }

    -- ---- GAME region (top panel, canvas x 1240..3160) ----------------------------------------
    -- Thor6in's own vertical offsets are kept (they were measured on device); only the
    -- horizontal edge anchors are re-derived from the game rect.
    add{ label = 'GAME HudTooltip bottom-right of the game rect',
         system = sys('HudTooltip'),
         anchor = HA('BOTTOMRIGHT', 'BOTTOMLEFT', GR - TU(9), TU(206)) }
    add{ label = 'GAME Buffs top-left of the game rect, grow right',
         system = sys('AuraFrame'), index = 1,
         anchor = HA('TOPLEFT', 'TOPLEFT', GL + TU(24), -TU(12)), named = { GROW_RIGHT } }
    add{ label = 'GAME Debuffs under buffs, grow right',
         system = sys('AuraFrame'), index = 2,
         anchor = HA('TOPLEFT', 'TOPLEFT', GL + TU(24), -TU(52)), named = { GROW_RIGHT } }
    add{ label = 'GAME External defensives top of the game rect',
         system = sys('AuraFrame'), index = 3,
         anchor = HA('TOP', 'TOPLEFT', GCX, -TU(10)) }
    add{ label = 'GAME Boss frames top-right of the game rect',
         system = sys('UnitFrame'), index = 6,
         anchor = HA('TOPRIGHT', 'TOPLEFT', GR - TU(10), -TU(206)) }
    add{ label = 'GAME Arena frames share the boss slot',
         system = sys('UnitFrame'), index = 7,
         anchor = HA('TOPRIGHT', 'TOPLEFT', GR - TU(10), -TU(206)) }
    add{ label = 'GAME Party frames top-left of the game rect',
         system = sys('UnitFrame'), index = 4,
         anchor = HA('TOPLEFT', 'TOPLEFT', GL + TU(10), -TU(140)) }
    add{ label = 'GAME Raid frames share the party slot',
         system = sys('UnitFrame'), index = 5,
         anchor = HA('TOPLEFT', 'TOPLEFT', GL + TU(10), -TU(140)) }
    add{ label = 'GAME VehicleSeatIndicator top-right of the game rect',
         system = sys('VehicleSeatIndicator'),
         anchor = HA('TOPRIGHT', 'TOPLEFT', GR - TU(10), -TU(21)) }
    add{ label = 'GAME ExtraAbilities right of target',
         system = sys('ExtraAbilities'),
         anchor = HA('BOTTOM', 'BOTTOMLEFT', GCX + TU(167), TU(199)) }
    add{ label = 'GAME Loot right of centre',
         system = sys('LootFrame'),
         anchor = HA('CENTER', 'BOTTOMLEFT', GCX + TU(256), TU(384 + 24)) }
    add{ label = 'GAME TalkingHead top-centre of the game rect',
         system = sys('TalkingHeadFrame'),
         anchor = HA('TOP', 'TOPLEFT', GCX, -TU(10)) }
    add{ label = 'GAME TimerBars under the boss warnings',
         system = sys('TimerBars'),
         anchor = HA('TOP', 'TOPLEFT', GCX, -TU(152)) }
    add{ label = 'GAME EncounterBar top lane of the game rect',
         system = sys('EncounterBar'),
         anchor = HA('TOP', 'TOPLEFT', GCX, -TU(235)) }
    add{ label = 'GAME RaidWarning top-centre of the game rect',
         system = sys('RaidWarning'),
         anchor = HA('TOP', 'TOPLEFT', GCX, -TU(200)) }

    -- Published for FFSpan's resident bags. y is PHYSICAL PX measured DOWNWARD from the canvas
    -- TOP edge; x is physical px from the canvas LEFT edge. Bags live in
    -- x .. right, from minimapBottom + gap down to bottomBarTop - 8.
    local slots = {
        minimapBottom = minimapBottom,
        bottomBarTop  = bottomBarTop,
        yOrigin       = 'canvas-top-down',
        x             = hr.x + HW - M - colW,
        right         = hr.x + HW - M,
        width         = colW,
        bagsHeight    = bagsH,
        minimapPct    = pct,
        margin        = M,
        gap           = GAP,
    }
    return T, slots
end

-- Classic's quest tracker is NOT an Edit Mode system (22:07 log: ObjectiveTracker "system
-- absent"), so it is placed directly: retail's TOPLEFT x=28 y=-100, text scaled from Classic's
-- 12 pt to retail's 16 pt. SetPoint offsets are in the frame's own scaled space, hence / scale.
-- Height keeps it clear of the chat top (y=220 units): 300 x 1.33 = 400 units -> bottom at 268.
local TRACKER = { x = 28, y = -100, scale = 16 / 12, height = 300 }
local trackerBusy, trackerHooked = false, false
-- v1.8.5 (Classic 5.5.4 run 2026-09-24 19:33-19:48, clean /quit). The fresh FFScaleLog showed:
--   * "tracker owner: parent=UIParentRightManagedFrameContainer ... container.RemoveManagedFrame=
--     function", and the /run probe: WatchFrame TOPLEFT -> that container's TOPLEFT 0,-0.75. On
--     5.5.4 the right managed container OWNS the tracker, and it does not honour SetUserPlaced.
--   * trackerReasserts "204304 (last 19:48:09)" since 19:33:54: ~240 re-asserts a second (~4 a
--     frame at 59.6 fps) for 14 minutes -- a per-frame fight that still lost (+3 s measure:
--     WatchFrame L=2852 W=272 = the container's rect, the undrawn strip right of the game rect).
--   * FFScaleLog.pq: 0 quest-log entries, 0 watches -- an EMPTY tracker was expected, not a bug.
-- So: leave the container ONCE, out of combat, through the container's own RemoveManagedFrame;
-- take the HOME top-left slot on a HOME run (HOME.watchTarget: the slot retail's ObjectiveTracker
-- gets) and the Thor6in constants otherwise; and never fight again -- adopted back, or moved by
-- something else more than 5 times in 10 s, and it stops and says why in FFScaleLog.trackerState.
-- No flag is written onto Blizzard's frames (no ignoreFramePositionManager for its own code to
-- read back tainted); the one container call runs out of combat.
local trk = { released = false, stopped = false, t0 = 0, n = 0 }

local function placeTracker(R)
    if IS_RETAIL then return end
    local tr = _G.WatchFrame or _G.ObjectiveTrackerFrame
    if not tr then if R then R[#R + 1] = 'tracker: no WatchFrame / ObjectiveTrackerFrame' end return end
    if InCombatLockdown() then return end  -- it parents secure quest-item buttons
    if trk.stopped then return end
    FFScaleLog = FFScaleLog or {}
    local parent = tr:GetParent()
    if parent and parent ~= UIParent and type(parent.RemoveManagedFrame) == 'function' then
        local pname = tostring(parent.GetName and parent:GetName())
        if trk.released then
            trk.stopped = true
            FFScaleLog.trackerState = ('%s re-adopted by %s after release; left to Blizzard'):format(
                date('%H:%M:%S'), pname)
            if R then R[#R + 1] = 'tracker: ' .. FFScaleLog.trackerState end
            return
        end
        trk.released = true
        local okR, errR = pcall(parent.RemoveManagedFrame, parent, tr)
        local okP = pcall(tr.SetParent, tr, UIParent)
        FFScaleLog.trackerState = ('%s released from %s (RemoveManagedFrame %s, SetParent %s)'):format(
            date('%H:%M:%S'), pname, okR and 'ok' or tostring(errR), okP and 'ok' or 'failed')
        if R then R[#R + 1] = 'tracker: ' .. FFScaleLog.trackerState end
    end
    -- FFScaleLog is rebuilt by every run and only a HOME run sets .home, so a HOME target left
    -- over from an earlier run can never apply to a Thor6in one.
    local ht = FFScaleLog.home and HOME.watchTarget
    local s = TRACKER.scale
    local x, y, h = TRACKER.x, TRACKER.y, TRACKER.height
    if ht then x, y, h = ht.x, ht.y, ht.heightUnits / s end
    trackerBusy = true
    pcall(tr.SetMovable, tr, true)
    pcall(tr.SetUserPlaced, tr, true)  -- harmless; 5.5.4's container ignores it (see above)
    tr:SetScale(s)
    tr:ClearAllPoints()
    tr:SetPoint('TOPLEFT', UIParent, 'TOPLEFT', x / s, y / s)
    tr:SetHeight(h)
    trackerBusy = false
    -- v1.10.2 (Classic 5.5.4 device, 2026-09-25): on the home screen the tracker is stretched over
    -- the whole left column, and WatchFrame takes the mouse over ALL of it, so a tap on the empty
    -- column never reached FFSpan's tap-outside catcher (the Shop stayed open at bottom 150,150).
    -- Its quest lines, header and item buttons are BUTTON children with their own mouse, so only
    -- the body and its full-height plain-Frame containers (the lines holder: /fstack showed one
    -- under the header spanning the column) stop eating touches. Home runs only: stock
    -- single-screen WoW is left as is.
    if ht then
        local off = {}
        local function quiet(f)
            if type(f.IsMouseEnabled) == 'function' and f:IsMouseEnabled() then
                if pcall(f.EnableMouse, f, false) then off[#off + 1] = tostring(f.GetName and f:GetName()) end
            end
        end
        quiet(tr)
        local half = (tr.GetHeight and tr:GetHeight() or 0) / 2
        for _, c in ipairs({ tr:GetChildren() }) do
            if c.GetObjectType and c:GetObjectType() == 'Frame' and (c.GetHeight and c:GetHeight() or 0) > half then
                quiet(c)
            end
        end
        if #off > 0 then
            FFScaleLog.trackerMouseOff = table.concat(off, ', ')
            if R then R[#R + 1] = 'tracker: mouse off on the home screen for ' .. FFScaleLog.trackerMouseOff end
        end
    end
    if R and ht then
        R[#R + 1] = ('tracker %s -> HOME slot TOPLEFT %.1f,%.1f scale %.2f height %.1f units'):format(
            tr:GetName() or '?', x, y, s, ht.heightUnits)
    elseif R then
        R[#R + 1] = ('tracker %s -> TOPLEFT %d,%d scale %.2f height %d'):format(
            tr:GetName() or '?', TRACKER.x, TRACKER.y, s, TRACKER.height)
    end
    -- v1.8.4, DIAGNOSTIC ONLY (Classic 5.5.4 HOME run 2026-09-24): the line above logged
    -- "TOPLEFT 28,-100 scale 1.33 height 300", yet the +3 s measure found WatchFrame at L=2852
    -- W=272 H=457 -- the rect of UIParentRightManagedFrameContainer (L=2852 W=272), which on the
    -- 4400 canvas is the undrawn strip right of the game rect. Something on this client re-lays
    -- it out. Record who owns it and whether FFScale's SetPoint/SetHeight re-assert ever fires, so the
    -- next pass can pick a supported fix instead of guessing at the container API. Reads only.
    if R then
        local okD, line = pcall(function()
            local p, lp = tr:GetParent(), tr.layoutParent
            local c = _G.UIParentRightManagedFrameContainer
            return ('tracker owner: parent=%s layoutParent=%s isRightManagedFrame=%s ignoreFramePositionManager=%s userPlaced=%s container.RemoveManagedFrame=%s'):format(
                tostring(p and p:GetName()), tostring(lp and lp.GetName and lp:GetName()),
                tostring(tr.isRightManagedFrame), tostring(tr.ignoreFramePositionManager),
                tostring(tr.IsUserPlaced and tr:IsUserPlaced()),
                c and type(c.RemoveManagedFrame) or 'no container')
        end)
        R[#R + 1] = okD and line or ('tracker owner: ' .. tostring(line))
    end
    if not trackerHooked and hooksecurefunc then
        trackerHooked = true
        FFScaleLog = FFScaleLog or {}
        FFScaleLog.trackerReasserts = '0 (hooked ' .. date('%H:%M:%S') .. ')'  -- v1.8.4 diagnostic
        -- if Blizzard re-anchors or resizes it later, put it back on the next frame
        local pending, reasserts = false, 0
        local function reassert()
            if trackerBusy or trk.stopped then return end
            -- v1.8.4 diagnostic: how often something else moves it (stays 0 = not via these two)
            reasserts = reasserts + 1
            FFScaleLog = FFScaleLog or {}
            FFScaleLog.trackerReasserts = ('%d (last %s)'):format(reasserts, date('%H:%M:%S'))
            if pending or trk.stopped then return end
            -- v1.8.5: answer another mover a bounded number of times, never every frame
            local now = (GetTime and GetTime()) or 0
            if now - trk.t0 > 10 then trk.t0, trk.n = now, 0 end
            trk.n = trk.n + 1
            if trk.n > 5 then
                trk.stopped = true
                FFScaleLog.trackerState = ('%s stopped: moved %d times in 10 s by something else'):format(
                    date('%H:%M:%S'), trk.n)
                return
            end
            pending = true
            C_Timer.After(0, function() pending = false; pcall(placeTracker) end)
        end
        hooksecurefunc(tr, 'SetPoint', reassert)
        hooksecurefunc(tr, 'SetHeight', reassert)
    end
end

-- Classic has no HudTooltip system: lift the default tooltip to retail's Thor6in spot, clear of
-- the A/B/X/Y glyph cluster (Blizzard's default drops it onto them).
if not IS_RETAIL and hooksecurefunc and GameTooltip_SetDefaultAnchor then
    hooksecurefunc('GameTooltip_SetDefaultAnchor', function(tt)
        tt:ClearAllPoints()
        tt:SetPoint('BOTTOMRIGHT', UIParent, 'BOTTOMRIGHT', -9, 206)
    end)
end

local function enumNames(t)
    local out = {}
    if type(t) == 'table' then for k, v in pairs(t) do out[v] = k end end
    return out
end

local function describeAnchor(a)
    if not a then return 'nil' end
    return string.format('%s -> %s %s x=%s y=%s', tostring(a.point), tostring(a.relativeTo),
        tostring(a.relativePoint), tostring(a.offsetX), tostring(a.offsetY))
end

local function dumpLayout(l)
    if not l then return { error = 'nil layout' } end
    local names, out = enumNames(Enum.EditModeSystem),
        { layoutName = l.layoutName, layoutType = l.layoutType, systems = {} }
    for _, sys in ipairs(l.systems or {}) do
        local row = {
            system = names[sys.system] or tostring(sys.system),
            systemIndex = sys.systemIndex,
            anchor = describeAnchor(sys.anchorInfo),
            settings = {},
        }
        for _, s in ipairs(sys.settings or {}) do
            table.insert(row.settings, string.format('%s=%s', tostring(s.setting), tostring(s.value)))
        end
        table.insert(out.systems, row)
    end
    return out
end

local function resolveNamed(n)
    local se, ve = Enum[n.settingEnum], n.valueEnum and Enum[n.valueEnum]
    local setting = se and se[n.key]
    local value = (ve and ve[n.valueKey]) or n.fallback
    return setting, value
end

local function applyTarget(systems, t)
    if not t.system then return 'SKIP (system enum missing)' end
    if not t.setting and not t.anchor and not t.named then return 'SKIP (nothing to do)' end
    for _, sys in ipairs(systems) do
        if sys.system == t.system and sys.systemIndex == t.index then
            local notes = {}
            sys.settings = sys.settings or {}
            local found = not t.setting  -- anchor-only target: skip the settings pass
            for _, s in ipairs(sys.settings) do
                if s.setting == t.setting then
                    table.insert(notes, ('size %s->%s'):format(tostring(s.value), tostring(t.value)))
                    s.value, found = t.value, true
                    break
                end
            end
            if not found then
                table.insert(sys.settings, { setting = t.setting, value = t.value })
                table.insert(notes, ('size inserted %s'):format(tostring(t.value)))
            end
            for _, n in ipairs(t.named or {}) do
                local setting, value = resolveNamed(n)
                if setting == nil or value == nil then
                    table.insert(notes, ('SKIP %s.%s (enum not found)'):format(n.settingEnum, n.key))
                else
                    local hit = false
                    for _, s in ipairs(sys.settings) do
                        if s.setting == setting then
                            table.insert(notes, ('%s %s->%s'):format(n.key, tostring(s.value), tostring(value)))
                            s.value, hit = value, true
                            break
                        end
                    end
                    if not hit then
                        table.insert(sys.settings, { setting = setting, value = value })
                        table.insert(notes, ('%s inserted %s'):format(n.key, tostring(value)))
                    end
                end
            end
            if t.anchor then
                table.insert(notes, 'anchor was [' .. describeAnchor(sys.anchorInfo) .. ']')
                sys.anchorInfo = {
                    point = t.anchor.point, relativeTo = t.anchor.relativeTo,
                    relativePoint = t.anchor.relativePoint,
                    offsetX = t.anchor.offsetX, offsetY = t.anchor.offsetY,
                }
                sys.anchorInfo2 = nil
                sys.isInDefaultPosition = false
            end
            return 'OK: ' .. table.concat(notes, '; ')
        end
    end
    return 'SKIP (system absent)'
end

-- Gamepad bindings FFScale owns. 2026-09-22: the unmodified face buttons were found EMPTY in the
-- per-character ConsolePort Bindings block (B just highlighted, did nothing) while every
-- modified layer followed ConsolePort's odd/even pattern (SHIFT-PAD1..4 = ACTIONBUTTON2/4/6/8,
-- R/ZR = 9/11). So the plain face buttons take the odd slots 1/3/5/7. Jump moves to L3,
-- which was unbound. PADSOCIAL is HOME on this hardware and is never used.
-- Nintendo glyph positions: PAD1 = B (bottom), PAD2 = A (right), PAD3 = Y (left), PAD4 = X (top).
local BINDINGS = {
    { key = 'PADRSTICK', action = 'OPENCHAT' },
    { key = 'PAD1',      action = 'ACTIONBUTTON1' },
    { key = 'PAD2',      action = 'ACTIONBUTTON3' },  -- A; SHIFT-A is ACTIONBUTTON4
    { key = 'PAD3',      action = 'ACTIONBUTTON5' },  -- Y; SHIFT-Y is ACTIONBUTTON6
    { key = 'PAD4',      action = 'ACTIONBUTTON7' },
    { key = 'PADLSTICK', action = 'JUMP' },
}

local function fixBindings(R)
    if not (SetBinding and GetBindingAction) then R[#R + 1] = 'bindings: API missing' return end
    local changed = false
    for _, b in ipairs(BINDINGS) do
        local before = GetBindingAction(b.key)
        if before ~= b.action then
            local ok = SetBinding(b.key, b.action)
            changed = changed or ok
            R[#R + 1] = ('bind %s: %q -> %s (%s)'):format(b.key, tostring(before), b.action, tostring(ok))
        else
            R[#R + 1] = ('bind %s: already %s'):format(b.key, b.action)
        end
    end
    if changed and SaveBindings then
        pcall(SaveBindings, GetCurrentBindingSet and GetCurrentBindingSet() or 1)
    end
end

-- What is actually sitting in action slots 1-12, so button assignments can be explained
-- and filled without guessing.
local function dumpActions(R)
    if not GetActionInfo then return end
    for slot = 1, 12 do
        local kind, id = GetActionInfo(slot)
        local name = ''
        if kind == 'spell' and C_Spell and C_Spell.GetSpellName then name = C_Spell.GetSpellName(id) or ''
        elseif kind == 'item' and C_Item and C_Item.GetItemNameByID then name = C_Item.GetItemNameByID(id) or ''
        elseif kind == 'macro' and GetMacroInfo then name = GetMacroInfo(id) or '' end
        R[#R + 1] = ('slot %d: %s %s %s'):format(slot, tostring(kind or 'empty'), tostring(id or ''), name)
    end
end

-- v1.4 MEASURE (FFDiag folded in): real on-screen rects for the layout mockup, so boxes are
-- measured instead of estimated from screenshots. Rects are in UIParent units, origin
-- BOTTOM-LEFT (screen is GetScreenWidth x GetScreenHeight = 1365.33 x 768 on the Thor;
-- px = units x 1.40625, top_px = (768 - B - H) x 1.40625).
local function rectOf(fr)
    if not (fr and fr.GetRect) then return nil end
    local ok, l, b, w, h = pcall(fr.GetRect, fr)
    if not ok or not l then return nil end
    local s = fr:GetEffectiveScale() / UIParent:GetEffectiveScale()
    return l * s, b * s, w * s, h * s
end

local function measureRow(label, fr)
    local vis = fr.IsVisible and fr:IsVisible()
    local l, b, w, h = rectOf(fr)
    if not l then return ('%s | vis=%s | no rect'):format(label, tostring(vis)) end
    return ('%s | vis=%s | L=%.0f B=%.0f W=%.0f H=%.0f'):format(label, tostring(vis), l, b, w, h)
end

local function frameLabel(fr)
    local okN, name = pcall(function() return fr:GetName() end)
    if okN and name then return name end
    local ok, dbg = pcall(fr.GetDebugName, fr)
    return ok and dbg or '<anon>'
end

-- Frames that are not Edit Mode systems (or not on every flavor) but own screen space on the Thor.
local MEASURE_NAMED = {
    'ConsolePortBarManager', 'ConsolePortToolbar', 'MinimapCluster', 'Minimap', 'MiniMapTracking',
    'MiniMapTrackingButton', 'MinimapZoneTextButton', 'GameTimeFrame', 'TimeManagerClockButton',
    'WatchFrame', 'ObjectiveTrackerFrame', 'QuestWatchFrame', 'ChatFrame1', 'ChatFrame1EditBox',
    'GeneralDockManager', 'BuffFrame', 'DebuffFrame', 'TemporaryEnchantFrame', 'PlayerFrame',
    'TargetFrame', 'TargetFrameToT', 'FocusFrame', 'PetFrame', 'PartyFrame', 'PartyMemberFrame1',
    'CompactRaidFrameManager', 'CompactPartyFrame', 'Boss1TargetFrame', 'ArenaEnemyFrames',
    'CastingBarFrame', 'PlayerCastingBarFrame', 'MainMenuBar', 'MainMenuBarArtFrame',
    'MicroButtonAndBagsBar', 'MainMenuBarBackpackButton', 'CharacterMicroButton',
    'StatusTrackingBarManager', 'MainStatusTrackingBarContainer', 'MainMenuExpBar',
    'ReputationWatchBar', 'DurabilityFrame', 'VehicleSeatIndicator', 'ExtraActionBarFrame',
    'ZoneAbilityFrame', 'TalkingHeadFrame', 'LootFrame', 'GroupLootContainer', 'GameTooltip',
    'UIErrorsFrame', 'RaidWarningFrame', 'RaidBossEmoteFrame', 'LossOfControlFrame',
    'PlayerPowerBarAlt', 'QueueStatusButton', 'MiniMapLFGFrame', 'MiniMapMailFrame',
    'ZoneTextFrame', 'ImmersionFrame',
}

local function measure()
    local M = { stamp = date('%H:%M:%S'),
                screen = ('%.2f x %.2f'):format(GetScreenWidth(), GetScreenHeight()),
                systems = {}, named = {}, cpbar = {}, uiparent = {} }
    -- v1.5.1: saved up front and every row guarded. On Classic 22:46 one UIParent child
    -- refused GetName ("bad self": a forbidden frame) and the error threw away the whole dump.
    FFScaleLog = FFScaleLog or {}
    FFScaleLog.measure = M
    local rawRow = measureRow
    local function measureRow(label, fr)
        local ok, row = pcall(rawRow, label, fr)
        return ok and row or (tostring(label) .. ' | ERR ' .. tostring(row))
    end
    local sysNames = enumNames(Enum.EditModeSystem)
    local reg = EditModeManagerFrame and EditModeManagerFrame.registeredSystemFrames
    for _, fr in ipairs(reg or {}) do
        local okL, label = pcall(function()
            return ('%s%s %s'):format(tostring(sysNames[fr.system] or fr.system),
                fr.systemIndex and ('#' .. tostring(fr.systemIndex)) or '', frameLabel(fr))
        end)
        M.systems[#M.systems + 1] = measureRow(okL and label or '<unlabelled system>', fr)
    end
    for _, name in ipairs(MEASURE_NAMED) do
        local fr = _G[name]
        M.named[#M.named + 1] = fr and measureRow(name, fr) or (name .. ' | absent')
    end
    -- ConsolePort draws the glyph clusters: two levels below its manager, visible only
    local function shown(fr) local ok, v = pcall(function() return fr:IsVisible() end); return ok and v end
    local function kids(fr) local ok, t = pcall(function() return { fr:GetChildren() } end); return ok and t or {} end
    local mgr = _G.ConsolePortBarManager
    if mgr then
        for _, c in ipairs(kids(mgr)) do
            if shown(c) then
                M.cpbar[#M.cpbar + 1] = measureRow(frameLabel(c), c)
                for _, g in ipairs(kids(c)) do
                    if shown(g) then M.cpbar[#M.cpbar + 1] = '  ' .. measureRow(frameLabel(g), g) end
                end
            end
        end
    end
    -- anything else on screen that has a name: catches frames nobody thought to list
    for _, c in ipairs(kids(UIParent)) do
        local okN, name = pcall(function() return c:GetName() end)
        if okN and name and shown(c) then M.uiparent[#M.uiparent + 1] = measureRow(name, c) end
    end
    table.sort(M.uiparent)
end

-- Pop-up windows only exist on screen sometimes: record each one's rect the first time it shows.
local POPUPS = { 'ContainerFrame1', 'ContainerFrameCombinedBags', 'LootFrame', 'QuestLogFrame',
                 'QuestFrame', 'GossipFrame', 'SpellBookFrame', 'CharacterFrame', 'WorldMapFrame',
                 'ImmersionFrame', 'GameMenuFrame', 'StaticPopup1', 'GroupLootFrame1', 'MerchantFrame' }
local function hookPopups()
    for _, name in ipairs(POPUPS) do
        local fr = _G[name]
        if fr and fr.HookScript then
            fr:HookScript('OnShow', function(self)
                C_Timer.After(0.3, function()
                    FFScaleLog = FFScaleLog or {}
                    FFScaleLog.popups = FFScaleLog.popups or {}
                    FFScaleLog.popups[name] = date('%H:%M:%S ') .. measureRow(name, self)
                end)
            end)
        end
    end
end

-- Order-independent signature of a layout table, so home mode can save only REAL changes.
local function sig(v, out)
    out = out or {}
    if type(v) ~= 'table' then out[#out + 1] = tostring(v) return out end
    local keys = {}
    for k in pairs(v) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b)
        local ta, tb = type(a) == 'number' and 0 or 1, type(b) == 'number' and 0 or 1
        if ta ~= tb then return ta < tb end
        return tostring(a) < tostring(b)
    end)
    for _, k in ipairs(keys) do
        out[#out + 1] = tostring(k); out[#out + 1] = '='
        sig(v[k], out)
        out[#out + 1] = ';'
    end
    return out
end
local function signature(v) return table.concat(sig(v)) end

-- Blizzard caps custom layouts PER TYPE (EditModeManager.lua AreLayoutsOfTypeMaxed). If the
-- constant is not on this client FFScale does NOT invent a cap -- a failing SaveLayouts is logged anyway.
local function layoutLimit()
    local C = _G.Constants
    local n = C and C.EditModeConsts and C.EditModeConsts.EditModeMaxLayoutsPerType
    if type(n) == 'number' and n > 0 then return n end
    return nil
end

-- THE geometry-aware picker. Every entry point (the 12 s pass, /ffscale, ApplyLayout, the FFSpan
-- home listener, Edit Mode readiness) goes through this, so there is exactly one layout owner.
local function layoutSpec()
    if homeEnabled() then
        local targets, slots, err = buildHomeTargets()
        if targets then
            local lt = Enum.EditModeLayoutType
                and (Enum.EditModeLayoutType.Character or Enum.EditModeLayoutType.Account)
            -- v1.7 (review M6): `slots` here is an ESTIMATE from seeded constants. It is carried on
            -- the spec but NOT published -- homeSlots is only written after the layout is live and
            -- the real edges have been measured, so FFSpan can never place bags from a provisional
            -- column or from a layout that never became active.
            return { name = HOME_LAYOUT_NAME, layoutType = lt, targets = targets,
                     base = LAYOUT_NAME, home = true, estimate = slots }
        end
        -- home wanted but FFSpan cannot describe the geometry: fall back to Thor6in and say why
        FFScaleLog = FFScaleLog or {}
        FFScaleLog.homeError = tostring(err)
    end
    homeSlots = nil   -- never hand FFSpan a stale home column once the client is off the home layout
    return { name = LAYOUT_NAME, layoutType = Enum.EditModeLayoutType and Enum.EditModeLayoutType.Account,
             targets = TARGETS, home = false }
end

-- ---------------------------------------------------------------------------------------------
-- v1.7 review B1/M6: the column FFSpan fits the resident bags into is MEASURED off the live UI
-- after the layout is confirmed, never inferred from HOME's seeded constants. The measurement
-- uses FFSpan's own envelope helper when it is there, so both addons read one conversion
-- (px = units * effectiveScale * physH / 768); the local fallback has the same shape.
-- ---------------------------------------------------------------------------------------------
local MINIMAP_NAMES  = { 'MinimapCluster', 'Minimap' }
local BOTTOMBAR_NAMES = { 'MicroMenuContainer', 'MicroButtonAndBagsBar', 'BagsBar', 'MicroMenu',
                          'StatusTrackingBarManager', 'MainMenuBar' }

local function physH()
    if type(GetPhysicalScreenSize) == 'function' then
        local ok, _, h = pcall(GetPhysicalScreenSize)
        if ok and type(h) == 'number' and h > 0 then return h end
    end
    return 768
end

-- physical rect of a frame, canvas TOP-LEFT origin, y down -- the same shape as FFSpan's rectPx
local function localRectPx(fr)
    if not (fr and fr.GetRect) then return nil end
    local ok, l, b, w, h = pcall(fr.GetRect, fr)
    if not ok or not l or not b or not w or not h or w <= 0 or h <= 0 then return nil end
    local okE, e = pcall(fr.GetEffectiveScale, fr)
    if not okE or type(e) ~= 'number' or e <= 0 then return nil end
    local ph = physH()
    local q = e * ph / 768
    return { x = l * q, y = ph - (b + h) * q, w = w * q, h = h * q }
end

local function envelopePx(name)
    local viaSpan = spanCall('EnvelopePx', name)
    if type(viaSpan) == 'table' and type(viaSpan.y) == 'number' and type(viaSpan.h) == 'number' then
        return viaSpan
    end
    return localRectPx(_G[name])
end

-- v1.8.2: the objective tracker's VISIBLE envelope starts left of its frame.
-- On the device the frame sat at x16, the 16 px margin FFScale asked for, while a visible child reached
-- x-26 -- so the left flourish of the "All Objectives" header was cut off the panel edge. Edit
-- Mode anchors the FRAME, so the anchor has to carry the overhang. Measured off the live UI, never
-- assumed: a frame with no overhang gets exactly the layout it has today.
trackerOverhangPx = function(name)
    local f = _G[name]
    if not f then return 0 end
    local root, env = localRectPx(f), envelopePx(name)
    if not (root and env) then return 0 end
    local over = root.x - env.x
    -- sanity: a real flourish is tens of px. Anything wilder is a measurement not to trust,
    -- and shoving the tracker halfway across the panel is worse than the clipped flourish.
    if not (over > 0.5) or over > 200 then return 0 end
    return over
end

-- Returns minimapBottom, bottomBarTop (physical px, canvas top-down) or nil for either.
local function measureHomeEdges(hr)
    local minimapBottom, bottomBarTop
    for _, name in ipairs(MINIMAP_NAMES) do
        local r = envelopePx(name)
        -- only trust a frame that actually sits in the home region
        if r and r.x < hr.w and r.h > 0 then
            local edge = r.y + r.h
            if not minimapBottom or edge > minimapBottom then minimapBottom = edge end
        end
    end
    for _, name in ipairs(BOTTOMBAR_NAMES) do
        local r = envelopePx(name)
        if r and r.x < hr.w and r.h > 0 then
            if not bottomBarTop or r.y < bottomBarTop then bottomBarTop = r.y end
        end
    end
    return minimapBottom, bottomBarTop
end

-- Publishes homeSlots from the live UI. Returns the slots table, or nil + reason.
local function publishHomeSlots(spec)
    local hr = spanCall('HomeRect')
    if not isRect(hr) then return nil, 'no HomeRect' end
    local est = spec.estimate or {}
    local mb, bt = measureHomeEdges(hr)
    local source = 'measured'
    if not mb then mb, source = est.minimapBottom, 'estimated-minimap' end
    if not bt then bt = est.bottomBarTop; source = (source == 'measured') and 'estimated-bar' or 'estimated' end
    if type(mb) ~= 'number' or type(bt) ~= 'number' then return nil, 'no edges' end
    -- a measurement that comes back inverted is not usable: say so instead of publishing it
    if bt - mb < 60 then return nil, ('edges too close (%.0f..%.0f)'):format(mb, bt) end
    local M = est.margin or HOME.margin
    local colW = est.width or HOME.bagsMinPx.w
    homeSlots = {
        minimapBottom = mb,
        bottomBarTop  = bt,
        yOrigin       = 'canvas-top-down',
        x             = hr.x + hr.w - M - colW,
        right         = hr.x + hr.w - M,
        width         = colW,
        bagsHeight    = bt - mb,
        minimapPct    = est.minimapPct,
        margin        = M,
        gap           = est.gap or HOME.gap,
        source        = source,
        layout        = spec.name,
        leftColumnOverflowPx = homeOverflowPx,
        -- v1.8.2: the CHAT slot, in the same canvas px as the rest of this
        -- table. Glassy's chat frame is not an Edit Mode system -- it follows GlassyMoverFrame,
        -- not ChatFrame1 -- so FFSpan has to place it at runtime, and it needs to know where the
        -- slot actually is rather than re-deriving it from HOME's constants.
        chat          = (function()
                            -- the SAME height the spec was built with: Glassy's measured
                            -- envelope when it is loaded, HOME's constant otherwise
                            local ch, cm = homeChatH or HOME.chatHPx, homeChatM or M
                            local bm = homeChatBottomM or M
                            return { x = hr.x + cm,
                                     y = hr.y + hr.h - bm - ch,
                                     w = hr.w - cm - (est.gap or HOME.gap) - colW - M,
                                     h = ch }
                         end)(),
    }
    return homeSlots
end

-- v1.7 (review M6): listeners are told AFTER a layout is verified live and (for home) after the
-- column has been published, so FFSpan's first bag placement can never see a provisional column.
local layoutListeners = {}
local function notifyLayoutListeners(name, slots)
    for _, fn in ipairs(layoutListeners) do pcall(fn, name, slots) end
end

-- v1.7 (review M7): the HOME path only runs once Edit Mode is genuinely ready. The latch is a
-- probe, not a timer: the client answers with a layout list AND a live active layout.
local editModeReady = false
local function editModeIsReady()
    if editModeReady then return true end
    if not (C_EditMode and C_EditMode.GetLayouts) then return false end
    local ok, info = pcall(C_EditMode.GetLayouts)
    if not ok or type(info) ~= 'table' then return false end
    local live = EditModeManagerFrame and EditModeManagerFrame.GetActiveLayoutInfo
        and EditModeManagerFrame:GetActiveLayoutInfo()
    if type(live) ~= 'table' or not live.layoutName then return false end
    editModeReady = true
    return true
end

-- v1.7: a source for Thor6in that is never ThorSpanHome. Normally that is simply the
-- active layout, exactly what the v1.5.1 single-screen path clones. Only when the active layout
-- IS the home layout (a SavedVariables state left by an older build) does it have to reach for the
-- preset a stock 1920 login would have cloned; presets are client-side and are NOT in
-- C_EditMode.GetLayouts(), so they are probed off EditModeManagerFrame and the call fails closed.
local function baseSource(rawInfo, active)
    if active and active.layoutName and active.layoutName ~= HOME_LAYOUT_NAME then
        return active, 'active'
    end
    local emf = EditModeManagerFrame
    if emf then
        local okL, combined = pcall(function() return emf.GetLayouts and emf:GetLayouts() end)
        local list = okL and type(combined) == 'table' and (combined.layouts or combined) or nil
        local presetType = Enum.EditModeLayoutType and Enum.EditModeLayoutType.Preset
        if type(list) == 'table' and presetType ~= nil then
            for _, l in ipairs(list) do
                if type(l) == 'table' and l.layoutName and l.layoutType == presetType then
                    return l, 'preset'
                end
            end
        end
        for _, key in ipairs({'presetLayouts', 'presets'}) do
            local okP, p = pcall(function() return emf[key] end)
            if okP and type(p) == 'table' and type(p[1]) == 'table' and p[1].layoutName then
                return p[1], 'preset'
            end
        end
    end
    return nil, 'none'
end

local applying = false   -- suppresses FFScale's own EDIT_MODE_LAYOUTS_UPDATED echo
local lastApplied        -- name of the last layout FFScale activated

local function run(specIn, manual)
    local popups = FFScaleLog and FFScaleLog.popups
    FFScaleLog = { stamp = date('%Y-%m-%d %H:%M:%S'), results = {}, popups = popups }
    local R = FFScaleLog.results

    if InCombatLockdown() then R[1] = 'ABORT: in combat' return false, 'in combat' end
    R[#R + 1] = ('client %s (project %s)'):format(tostring((GetBuildInfo())), tostring(WOW_PROJECT_ID))

    -- Bindings first: they matter on every flavor, Edit Mode may not exist on all of them
    -- (v1.3: Classic/Forever share this addon through the wow_mirror launcher).
    pcall(fixBindings, R)
    pcall(dumpActions, R)

    if not (C_EditMode and C_EditMode.GetLayouts and C_EditMode.SaveLayouts) then
        R[#R + 1] = 'STOP: C_EditMode unavailable on this client (bindings applied)'
        return false, 'no C_EditMode'
    end

    local spec = specIn or layoutSpec()
    if spec.home then
        -- v1.7 (review M7): fail closed. The home path does not touch Edit Mode until the client
        -- can actually answer for it; the caller keeps its retry eligibility.
        if not editModeIsReady() then
            R[#R + 1] = 'HOME: Edit Mode is not ready yet -- deferred, will retry'
            return false, 'edit mode not ready'
        end
        -- home detail stays OUT of R: the non-home result lines are frozen by the golden tests
        FFScaleLog.home = { layout = spec.name, estimate = spec.estimate }
        -- the live minimap envelope, so HOME.minimapU100 can be corrected after the first
        -- device run instead of staying a seeded estimate
        local mc = _G.MinimapCluster
        if mc and mc.GetWidth and mc.GetHeight then
            local okW, w = pcall(mc.GetWidth, mc)
            local okH, h = pcall(mc.GetHeight, mc)
            local okS, sc = pcall(mc.GetEffectiveScale, mc)
            FFScaleLog.home.measuredCluster = {
                w = okW and w or nil, h = okH and h or nil, effScale = okS and sc or nil }
        end
    end

    local active = EditModeManagerFrame and EditModeManagerFrame:GetActiveLayoutInfo()
    FFScaleLog.before = dumpLayout(active)

    -- Fresh read + deep copy of the WHOLE custom list, so foreign layouts and any field FFScale does
    -- not understand travel back to SaveLayouts untouched (code review finding).
    local rawInfo = C_EditMode.GetLayouts()
    if not rawInfo then R[#R + 1] = 'ABORT: GetLayouts nil' return false, 'GetLayouts nil' end
    rawInfo = CopyTable(rawInfo)
    rawInfo.layouts = rawInfo.layouts or {}

    local numPresets = (Enum.EditModePresetLayoutsMeta and Enum.EditModePresetLayoutsMeta.NumValues) or 2
    R[#R + 1] = ('numPresets=%d  customLayouts=%d'):format(numPresets, #rawInfo.layouts)

    -- Find FFScale's layout among the CUSTOM layouts, or clone the base (never "whatever is active").
    -- v1.7 (review M7): on the HOME path identity is name + layoutType, and an ambiguous identity
    -- is refused rather than resolved by luck. The non-home path keeps v1.5.1's name-only match.
    local baseType = Enum.EditModeLayoutType and Enum.EditModeLayoutType.Account
    local mine, myRawIndex, base, sameType = nil, nil, nil, 0
    local mineCount, baseCount, baseSameType = 0, 0, 0
    for i, l in ipairs(rawInfo.layouts) do
        R[#R + 1] = ('custom[%d] = %s (type %s)'):format(i, tostring(l.layoutName), tostring(l.layoutType))
        if l.layoutName == spec.name and (not spec.home or l.layoutType == spec.layoutType) then
            mine, myRawIndex, mineCount = l, i, mineCount + 1
        end
        if spec.base and l.layoutName == spec.base
            and (not spec.home or l.layoutType == baseType) then
            base, baseCount = l, baseCount + 1
        end
        if l.layoutType == spec.layoutType then sameType = sameType + 1 end
        if l.layoutType == baseType then baseSameType = baseSameType + 1 end
    end
    if spec.home and (mineCount > 1 or baseCount > 1) then
        R[#R + 1] = ('ABORT: ambiguous layout identity (%d x "%s", %d x "%s")')
            :format(mineCount, tostring(spec.name), baseCount, tostring(spec.base))
        return false, 'ambiguous layout identity'
    end

    local dirty = false
    -- v1.7: Thor6in is ALWAYS built by the single-screen
    -- path from the player's own base and is NEVER cloned from ThorSpanHome. When the home path
    -- needs it and it is missing, seed it here -- in the SAME payload, so ThorSpanHome below
    -- really does clone the identified Thor6in.
    if spec.home and spec.base and not base then
        local src, how = baseSource(rawInfo, active)
        if not src then
            R[#R + 1] = ('ABORT: HOME needs base "%s" and no non-home source is available'
                .. ' -- log in once at a single screen to build it'):format(tostring(spec.base))
            return false, 'no base for ' .. tostring(spec.base)
        end
        local limit = layoutLimit()
        if limit and baseSameType >= limit then
            R[#R + 1] = ('ABORT: cannot seed base "%s", layout limit reached for its type (%d/%d)')
                :format(tostring(spec.base), baseSameType, limit)
            return false, 'layout limit (base)'
        end
        base = CopyTable(src)
        base.layoutName = spec.base
        base.layoutType = baseType
        for _, t in ipairs(TARGETS) do applyTarget(base.systems, t) end
        table.insert(rawInfo.layouts, base)
        dirty = true
        R[#R + 1] = ('HOME: seeded base "%s" from %s "%s"')
            :format(tostring(spec.base), how, tostring(src.layoutName))
        if spec.layoutType == baseType then sameType = sameType + 1 end
    end

    if not mine then
        -- the home path may only ever clone its identified base
        local src = base or (not spec.home and active) or nil
        if not src then R[#R + 1] = 'ABORT: no active layout to clone' return false, 'nothing to clone' end
        local limit = layoutLimit()
        if limit and sameType >= limit then
            R[#R + 1] = ('ABORT: layout limit reached for this type (%d/%d) -- delete one in Edit Mode')
                :format(sameType, limit)
            return false, 'layout limit'
        end
        mine = CopyTable(src)
        mine.layoutName = spec.name
        mine.layoutType = spec.layoutType
        table.insert(rawInfo.layouts, mine)
        myRawIndex = #rawInfo.layouts
        dirty = true
        if base and src == base then
            R[#R + 1] = ('cloned base "%s" -> new custom index %d'):format(tostring(src.layoutName), myRawIndex)
        else
            R[#R + 1] = ('cloned active "%s" -> new custom index %d'):format(tostring(src.layoutName), myRawIndex)
        end
    else
        R[#R + 1] = ('reusing existing "%s" at custom index %d'):format(spec.name, myRawIndex)
    end

    local wasSig = (not dirty) and signature(mine) or nil
    for _, t in ipairs(spec.targets) do R[#R + 1] = t.label .. ' -> ' .. applyTarget(mine.systems, t) end
    if wasSig and signature(mine) ~= wasSig then dirty = true end

    local activeIndex = numPresets + myRawIndex
    rawInfo.activeLayout = activeIndex

    -- Save only real changes. HOME PATH ONLY: on the single-screen path v1.5.1 always wrote, and
    -- that behaviour is frozen by the golden tests, so it only changes on purpose.
    if spec.home and not dirty and (active and active.layoutName) == spec.name
        and active.layoutType == spec.layoutType then
        R[#R + 1] = 'no change needed (layout already current)'
        FFScaleLog.after = dumpLayout(active)
        local slots, why = publishHomeSlots(spec)
        if not slots then
            homeSlots = nil
            R[#R + 1] = 'HOME: could not publish the column (' .. tostring(why) .. ')'
            return false, 'no column: ' .. tostring(why)
        end
        lastApplied = spec.name
        FFScaleLog.home.slots = slots
        print('|cff69ccf0FFScale:|r ' .. spec.name .. ' already current.')
        notifyLayoutListeners(spec.name, slots)
        return true, spec.name .. ' (unchanged)'
    end

    applying = true
    local ok, err = pcall(C_EditMode.SaveLayouts, rawInfo)
    R[#R + 1] = ok and 'C_EditMode.SaveLayouts OK' or ('SaveLayouts FAILED: ' .. tostring(err))

    local activated = false
    if ok and C_EditMode.SetActiveLayout then
        -- Re-read and resolve the NAME to its current index: the save may have been reconciled
        -- and a stale index would activate somebody else's layout (code review finding).
        -- v1.7 (review M7): the HOME path requires EXACTLY ONE fresh match and never activates a
        -- stale index; the single-screen path keeps v1.5.1's first-match-or-keep behaviour.
        local fresh = C_EditMode.GetLayouts()
        local matches, foundIndex = 0, nil
        for i, l in ipairs((fresh and fresh.layouts) or {}) do
            if l.layoutName == spec.name and l.layoutType == spec.layoutType then
                matches = matches + 1
                if not foundIndex then foundIndex = numPresets + i end
            end
        end
        if spec.home and matches ~= 1 then
            applying = false
            R[#R + 1] = ('ABORT: expected exactly one "%s" after the save, found %d')
                :format(spec.name, matches)
            FFScaleLog.after = dumpLayout(EditModeManagerFrame and EditModeManagerFrame:GetActiveLayoutInfo())
            homeSlots = nil
            return false, 'save did not resolve'
        end
        if foundIndex then activeIndex = foundIndex end
        local ok2, err2 = pcall(C_EditMode.SetActiveLayout, activeIndex)
        R[#R + 1] = ok2 and ('SetActiveLayout(%d) OK'):format(activeIndex)
                        or ('SetActiveLayout FAILED: ' .. tostring(err2))
        activated = ok2 and true or false
    end
    applying = false

    local live = EditModeManagerFrame and EditModeManagerFrame:GetActiveLayoutInfo()
    FFScaleLog.after = dumpLayout(live)
    -- Verify the LIVE result, not just pcall success. Kept out of R for the same reason as above.
    local liveOK = (live and live.layoutName == spec.name
                    and (not spec.home or live.layoutType == spec.layoutType)) or false
    FFScaleLog.verify = { wanted = spec.name, home = spec.home == true,
                          liveName = live and live.layoutName,
                          liveType = live and live.layoutType,
                          index = activeIndex,
                          match = liveOK }

    -- v1.7 (review M6/M7) -- the acknowledged sequence, HOME path only:
    --   verified live name+type -> measure the live edges -> publish the column -> tell FFSpan.
    -- Success is only ever reported after all four, and a failure keeps retry eligibility.
    if spec.home then
        if not (ok and activated and liveOK) then
            homeSlots = nil
            R[#R + 1] = 'HOME: the layout did not verify live -- nothing published, will retry'
            return false, 'not verified'
        end
        local slots, why = publishHomeSlots(spec)
        if not slots then
            homeSlots = nil
            R[#R + 1] = 'HOME: could not publish the column (' .. tostring(why) .. ')'
            return false, 'no column: ' .. tostring(why)
        end
        lastApplied = spec.name
        FFScaleLog.home.slots = slots
        -- 2026-09-25: quiet on autoapply (login/edit-mode-ready/ffspan-triggered); manual
        -- /ffscale still reports so the player knows to exit via Game Menu after typing it.
        if manual then print('|cff69ccf0FFScale:|r applied. Exit via Game Menu so SavedVariables flush.') end
        notifyLayoutListeners(spec.name, slots)
        return true, spec.name
    end

    lastApplied = spec.name
    -- 2026-09-25: quiet on autoapply (login/edit-mode-ready/ffspan-triggered); manual
    -- /ffscale still reports so the player knows to exit via Game Menu after typing it.
    if manual then print('|cff69ccf0FFScale:|r applied. Exit via Game Menu so SavedVariables flush.') end
    notifyLayoutListeners(spec.name, nil)
    return ok and true or false, spec.name
end

-- 2026-09-22: on the gamepad the (hidden) mouse cursor rests over the player frame, so its
-- "Level 4 Troll ... <Right click for Frame Settings>" tooltip sat on screen permanently.
-- Right-click frame settings are useless on a pad, so unit-frame tooltips are suppressed.
-- NPC / item / spell tooltips are untouched. Tooltips are not protected, so hiding one from
-- an OnShow hook does not taint the secure unit buttons.
-- v1.4: on Classic the parked cursor sits on the minimap's tracking button instead, leaving a
-- permanent "Tracking - Click to enable and disable tracking types" box top-right (shot 22:08).
-- Nothing in the minimap cluster needs a hover tooltip on a pad, so the whole cluster is quiet.
local QUIET_OWNERS = { PlayerFrame = true, TargetFrame = true, FocusFrame = true, PetFrame = true,
                       MinimapCluster = true, Minimap = true, MinimapBackdrop = true }
local function isQuietOwner(frame)
    for _ = 1, 6 do  -- the owner can be a child of the unit frame / minimap cluster
        if not frame then return false end
        local name = frame.GetName and frame:GetName()
        if name and QUIET_OWNERS[name] then return true end
        frame = frame.GetParent and frame:GetParent()
    end
    return false
end
if GameTooltip then
    GameTooltip:HookScript('OnShow', function(tt)
        if isQuietOwner(tt:GetOwner()) then tt:Hide() end
    end)
end

local f = CreateFrame('Frame')

local function safeRun()
    -- 2026-09-22: v1.2's first run logged only 'ABORT: in combat' (I was fighting 12 s after
    -- load) and never retried. If the player is in combat, wait for PLAYER_REGEN_ENABLED instead.
    if InCombatLockdown() then
        FFScaleLog = FFScaleLog or {}
        FFScaleLog.deferred = date('%H:%M:%S') .. ' in combat, waiting for combat to end'
        f:RegisterEvent('PLAYER_REGEN_ENABLED')
        return
    end
    local ok, err = pcall(run)
    if not ok then
        applying = false   -- never leave the echo guard latched on an error
        FFScaleLog = FFScaleLog or {}
        FFScaleLog.fatal = tostring(err)
        print('|cffff5555FFScale error:|r ' .. tostring(err))
    end
    FFScaleLog = FFScaleLog or {}
    FFScaleLog.results = FFScaleLog.results or {}
    local okT, errT = pcall(placeTracker, FFScaleLog.results)
    if not okT then FFScaleLog.trackerError = tostring(errT) end
    -- measure AFTER the layout is applied, so the rects are the layout the player actually sees
    C_Timer.After(3, function()
        local okM, errM = pcall(measure)
        if not okM then FFScaleLog = FFScaleLog or {}; FFScaleLog.measureError = tostring(errM) end
    end)
end

f:RegisterEvent('PLAYER_ENTERING_WORLD')
f:SetScript('OnEvent', function(self, event)
    self:UnregisterEvent(event)
    if event == 'PLAYER_REGEN_ENABLED' then
        C_Timer.After(1, safeRun)
    else
        pcall(hookPopups)
        C_Timer.After(12, safeRun)
    end
end)

-- ---------------------------------------------------------------------------------------------
-- v1.6 public contract. A SECOND frame owns the new events so the v1.5.1
-- frame `f` above -- whose handler unregisters whatever fired it -- is untouched.
-- ---------------------------------------------------------------------------------------------
local hf = CreateFrame('Frame')
local pendingApply, homeRegistered, homeApplied = nil, false, false

-- Out of combat: pick the layout by geometry and apply it. In combat: ONE coalesced retry on
-- PLAYER_REGEN_ENABLED (a later call while queued replaces the reason, never adds a second run).
function FFScale.ApplyLayout(reason)
    reason = tostring(reason or 'manual')
    if InCombatLockdown and InCombatLockdown() then
        pendingApply = reason
        hf:RegisterEvent('PLAYER_REGEN_ENABLED')
        FFScaleLog = FFScaleLog or {}
        FFScaleLog.pending = date('%H:%M:%S') .. ' ' .. reason .. ' deferred (in combat)'
        return false, 'in combat -- one retry queued'
    end
    local ok, a, b = pcall(run)
    if not ok then
        applying = false   -- never leave the echo guard latched on an error
        FFScaleLog = FFScaleLog or {}
        FFScaleLog.fatal = tostring(a)
        return false, tostring(a)
    end
    return a == true, b
end

-- The layout the client is actually on right now (falls back to what FFScale last activated).
function FFScale.ActiveLayoutName()
    local live = EditModeManagerFrame and EditModeManagerFrame.GetActiveLayoutInfo
        and EditModeManagerFrame:GetActiveLayoutInfo()
    if live and live.layoutName then return live.layoutName end
    return lastApplied
end

-- Where the home column is, in physical px, so FFSpan can fit the resident bags under the
-- minimap: x .. right horizontally, minimapBottom + gap .. bottomBarTop - 8 vertically, with y
-- measured DOWNWARD from the canvas top edge (slots.yOrigin says so explicitly). nil off home.
-- v1.8.3: 0 when the left column holds, else how many px the tracker's floor runs past the chat.
function FFScale.LeftColumnOverflowPx() return homeOverflowPx end

function FFScale.HomeSlots()
    if not homeSlots then return nil end
    return CopyTable(homeSlots)
end

-- v1.7 (code review): the acknowledgement back to FFSpan.
-- `fn(layoutName, slots)` runs only after the layout is verified LIVE, and for the home layout
-- only after the column has been measured and published -- so a listener can place windows
-- knowing the geometry it is reading is the geometry on screen. `slots` is nil off the home
-- layout. Listeners are pcall-wrapped and de-duplicated by function identity.
function FFScale.RegisterLayoutListener(fn)
    if type(fn) ~= 'function' then return false end
    for _, f2 in ipairs(layoutListeners) do if f2 == fn then return true end end
    layoutListeners[#layoutListeners + 1] = fn
    return true
end
function FFScale.LayoutListenerCount() return #layoutListeners end

-- True once Edit Mode has answered for itself; the home path refuses to run before that.
function FFScale.EditModeReady() return editModeIsReady() end

local function registerHomeListener()
    if homeRegistered then return end
    local S = span()
    if not (S and type(S.RegisterHomeListener) == 'function') then return end
    local ok = pcall(S.RegisterHomeListener, function(enabled, reason)
        homeApplied = false
        FFScale.ApplyLayout('ffspan:' .. tostring(reason or (enabled and 'on' or 'off')))
    end)
    homeRegistered = ok and true or false
end

hf:RegisterEvent('PLAYER_ENTERING_WORLD')
hf:RegisterEvent('EDIT_MODE_LAYOUTS_UPDATED')
hf:SetScript('OnEvent', function(self, event)
    if event == 'PLAYER_REGEN_ENABLED' then
        self:UnregisterEvent(event)
        local reason = pendingApply
        pendingApply = nil
        if reason then FFScale.ApplyLayout(reason) end
        return
    end
    if event == 'PLAYER_ENTERING_WORLD' then
        registerHomeListener()   -- FFSpan has loaded by now; FFScale loads first
        return
    end
    -- EDIT_MODE_LAYOUTS_UPDATED: Edit Mode is ready. In home mode apply straight away instead of
    -- waiting out the 12 s pass; `applying` swallows the echo of FFScale's own SaveLayouts.
    editModeReady = true   -- v1.7: the readiness latch the HOME path waits on
    registerHomeListener()
    if applying or homeApplied then return end
    if not homeEnabled() then return end
    -- v1.7 (review M7): `homeApplied` latches only on SUCCESS, so a refused or unverified apply
    -- stays eligible for the next readiness/regen/12 s trigger instead of being swallowed.
    local okApply = FFScale.ApplyLayout('edit-mode-ready')
    homeApplied = okApply and true or false
end)

SLASH_FFSCALE1 = '/ffscale'
-- run() is the geometry-aware path as of v1.6, so /ffscale picks ThorSpanHome in home mode and
-- Thor6in everywhere else -- with v1.5.1's exact in-combat behaviour on the single-screen path.
SlashCmdList['FFSCALE'] = function() pcall(run, nil, true) end
