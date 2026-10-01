--[[
    FFSpan_Glassy -- reflows the third-party addon Glassy (chat) to fit inside FFSpan's home
    screen layout by adjusting its TWO size settings through Glassy's own supported AceDB
    profile + config-event Dispatch, never by hooking Glassy's code, touching its frames/mover
    directly, or switching its AceDB profile. This file owns ONLY Glassy's `frameWidth` and
    `frameHeight` profile fields, plus (2.9.0) `chatAlwaysVisible` -- only ever switched ON, see
    ApplyAlwaysVisible; Glassy's frame *position* is handled separately by
    FFSpan_Home.lua's placeGlassy (GlassyMoverFrame:SetDragPosition), which this file never touches.

    Verified facts this module is built on: _G.Glassy is Glassy's Core; Core.db is an AceDB-3.0
    object (Core.db.profile / Core.db:GetCurrentProfile()); the width slider's own bounds are
    min 100 / soft-min 300; defaults.profile.frameWidth = 600; the height slider
    (Modules/ConfigChatPages.lua:197-213) is min MIN_FRAME_HEIGHT / soft-min 200 / soft-max 800 /
    step 1 and writes Core.db.profile.frameHeight then dispatches 'frameHeight', which
    MainContainerFrame and MoverFrame both react to; Core:Dispatch(event, ...) runs registered
    subscribers in a plain inline loop (synchronous -- an erroring subscriber errors the whole
    call, which is exactly why every call site below is pcall-wrapped); the mover re-measures its
    own bounds off that dispatch on the next C_Timer.After(0, ...) tick, so nothing here needs to
    touch the mover. Because none of that requires knowing any child frame's name, this module
    never assumes one -- it only ever reads/writes Core.db.profile.frameWidth / .frameHeight and
    calls Core:Dispatch('Glassy/UPDATE_CONFIG', <that same key>).

    Public API (integration -- wiring these calls into placeGlassy / home cleanup / logout /
    stock-login -- is owned by the caller, not here):

      FFSpan.GlassyFit.Apply(widthInUIUnits) -> success (bool), changed (bool)
        Fits Glassy's width to at most `widthInUIUnits`, never exceeding the width Glassy had
        before FFSpan ever touched it (or the width the user most recently set by hand, if that
        happened after FFSpan last applied one -- see "baseline" below). Caller passes UI units
        already converted from physical pixels and owns placement; this function only ever
        writes the single numeric `frameWidth` field, and only when the value actually changes.
        Refuses (false, false), with zero mutation and zero dispatch, when: Glassy/its AceDB
        surface isn't present, widthInUIUnits isn't a finite positive number, the caller is in
        combat, or widthInUIUnits is below Glassy's own 300-unit soft-min (fitting into less
        than that would violate the slot rather than honor it).

      FFSpan.GlassyFit.ApplyHeight(heightInUIUnits) -> success (bool), changed (bool)
        Apply's exact twin for `frameHeight`: same baseline/ceiling rule (never taller than the
        height before FFSpan first touched it, or a later hand-set one), same refusals, same
        write-only-on-change, dispatching 'frameHeight'. The floor is 150 (Glassy's hard min is 100, its slider's soft min 200 -- see HEIGHT), and
        the request is floored to whole units first (the slider's step is 1), so repeated passes
        land on the same value and never re-dispatch.

      FFSpan.GlassyFit.Restore(dispatch) -> success (bool), changed (bool)
        Restores the current AceDB profile's `frameWidth` AND `frameHeight`, each to what it was
        before FFSpan's last successful Apply/ApplyHeight for that profile, but each ONLY if the
        field still holds exactly the value FFSpan last applied -- an intervening user change (in
        Glassy's own options, e.g.) is always honored and never clobbered; in that case this just
        drops FFSpan's now-stale bookkeeping for that field. `changed` is true when either field
        was put back; with nothing put back it reports (true, false). `dispatch` defaults to
        true, and then fires once per restored key (width first), only after BOTH fields' data is
        back, so no subscriber ever sees half a restore; `success` is false only if one of those
        dispatches threw (the data is restored regardless). Pass false for the PLAYER_LOGOUT
        path: that is pure data restoration with no layout operations and no Dispatch call, so
        it is safe to run even in combat (nothing here is protected unless it dispatches). The
        same function also serves late-addon / stock-login cleanup (Home disabled this session):
        it is idempotent and safe to call any time, including with no prior Apply in this
        session at all, since it always reads its state fresh from GlassyDB rather than from any
        in-memory flag. A journal written before the height half existed (width fields only)
        restores exactly as it always did.

    Baseline / "never clobber" rule: every Apply call re-checks whether the current profile's
    field still equals the value FFSpan itself last wrote. If it does not, something else
    (the user, Glassy's own reset, etc.) changed it since -- that current value is adopted as
    the new baseline/ceiling for future fits, exactly like the profile had never been touched
    before. This is also how a profile switch is handled without ever calling
    Core.db:SetProfile(): before doing anything for the current profile, Apply/Restore sweep
    every OTHER profile this module still has an open journal entry for and restore both fields
    of each one directly through GlassyDB.profiles[<name>] (plain data, no active-profile
    switching), so a profile is never left narrowed or shortened just because play moved on.

    Journal: GlassyDB.FFSpanWidthRestore[<AceDB profile name>] = {
        rawFrameWidth  = rawget(profile, "frameWidth") at the moment FFSpan first adapted this
                         profile -- RAW_NIL_MARKER stands in for a real Lua nil (i.e. "this was
                         inherited from AceDB defaults, not explicitly set"), because
                         SavedVariables cannot round-trip a bare nil as a distinguishable stored
                         value across a reload,
        effectiveWidth = the resolved numeric width in effect at that same moment (what
                         `profile.frameWidth` returns through the AceDB defaults metatable) --
                         this is the ceiling every Apply caps against,
        appliedWidth   = the width this module actually wrote last,
        rawFrameHeight / effectiveHeight / appliedHeight = the same three, for frameHeight.
    }
    The table keeps its width-era name and width field names on purpose: saved GlassyDB files on
    the device already carry them. A field counts as journaled only while its applied* value is
    set, which only ever happens once a write of it has actually landed; either field may be
    journaled alone, and an entry is cleared only once neither field remains journaled in it.
    This lives inside GlassyDB (Glassy's own SavedVariables), never FFSpanDB: Glassy.lua's file
    content is shared across flavors but FFSpan.lua's is not, so the record of "which profile
    did FFSpan narrow, and by how much" has to travel in the same SavedVariables file as the
    value it describes, or a flavor/profile without FFSpan's own SV present could be left
    permanently narrowed with nothing left able to find the journal that would undo it.
--]]

local ADDON_NAME = ...

local FFSpan = _G.FFSpan
if type(FFSpan) ~= "table" then
    FFSpan = {}
    _G.FFSpan = FFSpan
end
FFSpan.GlassyFit = FFSpan.GlassyFit or {}
local GlassyFit = FFSpan.GlassyFit

local JOURNAL_KEY = "FFSpanWidthRestore" -- width-era name, kept: saved GlassyDB files already use it
local RAW_NIL_MARKER = "\1FFSpanRawNil\1" -- a real frameWidth/frameHeight is always a number; a string never collides

-- The two fields this module may write. Each carries its own journal keys (the width names are
-- frozen by saved data) and Glassy's own slider soft-min for it (native widget; FFSpan only ever
-- honor it). FIELDS is the order Restore puts them back and dispatches them in.
local WIDTH = {
    key = "frameWidth", raw = "rawFrameWidth", effective = "effectiveWidth", applied = "appliedWidth",
    softMin = 300,
}
local HEIGHT = {
    key = "frameHeight", raw = "rawFrameHeight", effective = "effectiveHeight", applied = "appliedHeight",
    -- 150, not the slider's 200: Glassy itself accepts anything down to MIN_FRAME_HEIGHT = 100
    -- (Modules/Config.lua:22, :226); 200 is only the slider's comfortable range
    -- (ConfigChatPages.lua:197-213). The 160 % micro bar (FFScale 1.9) leaves a ~371 px chat slot,
    -- and with ~102 units of tabs and edit box on top that is frameHeight ~161 -- ~8 lines.
    softMin = 150,
}
-- 2.9.0 (2026-09-25: I wanted the chat to fade, not vanish): Glassy's own
-- `chatAlwaysVisible` keeps the messages up; FFSpan_ChatDim dims the whole chat when idle. A
-- boolean, so it has no soft-min and its own apply (ApplyAlwaysVisible); the journal helpers
-- below compare values, not numbers, so Restore and the stale-profile sweep handle it as is.
local ALWAYS = {
    key = "chatAlwaysVisible", raw = "rawAlwaysVisible", effective = "effectiveAlwaysVisible",
    applied = "appliedAlwaysVisible",
}
local FIELDS = { WIDTH, HEIGHT, ALWAYS }

-- ---------------------------------------------------------------------------------------------
-- Small helpers. Every one of these fails closed: any unexpected shape means "do nothing," not
-- an error thrown back at the caller.
-- ---------------------------------------------------------------------------------------------

local function getCore()
    local Core = _G.Glassy
    if type(Core) ~= "table" or type(Core.Dispatch) ~= "function" then return nil end
    local db = Core.db
    if type(db) ~= "table" or type(db.profile) ~= "table" then return nil end
    if type(db.GetCurrentProfile) ~= "function" then return nil end
    return Core, db
end

local function isFiniteNumber(v)
    return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge
end

-- A field is journaled for a profile only while its applied* value is set -- i.e. only once a
-- write of it has actually landed. A width-era entry simply has no height fields at all.
local function isJournaled(entry, field)
    return type(entry) == "table" and entry[field.applied] ~= nil
end

-- Drops FFSpan's claim on ONE field of a profile's entry. The entry itself goes only once no
-- field is left journaled in it, so a live width claim survives a height restore and vice versa.
local function dropClaim(journal, name, field)
    local entry = journal[name]
    if type(entry) ~= "table" then
        journal[name] = nil
        return
    end
    entry[field.raw], entry[field.effective], entry[field.applied] = nil, nil, nil
    for _, other in ipairs(FIELDS) do
        if isJournaled(entry, other) then return end
    end
    journal[name] = nil
end

-- Restores one field of one profile directly against `target` (either the live db.profile for
-- the active profile, or a raw GlassyDB.profiles[name] table for any other profile) -- pure
-- data, no frame/mover/Dispatch involvement. Only writes if the field is journaled and still
-- equals exactly what FFSpan last applied there; an intervening change is left alone entirely
-- (never clobbered).
local function restoreOnto(target, entry, field)
    if type(target) ~= "table" or not isJournaled(entry, field) then return false end
    local current = rawget(target, field.key)
    if current ~= entry[field.applied] then
        return false -- not FFSpan's to touch any more; caller still drops the claim
    end
    if entry[field.raw] == RAW_NIL_MARKER then
        target[field.key] = nil
    else
        target[field.key] = entry[field.raw]
    end
    return true
end

-- Sweeps every journaled profile OTHER than the active one: restores both fields of each
-- directly through GlassyDB.profiles[name] (never via db:SetProfile -- no profile switching
-- here, ever) and clears its journal row either way (restored, or the user already changed it
-- and superseded FFSpan's claim -- both are a resolved state; only a failed WRITE attempt on the
-- ACTIVE profile keeps a claim alive, see applyField's rollback path below).
local function sweepStaleProfiles(GlassyDB, journal, activeProfile)
    local profiles = GlassyDB.profiles
    for name, entry in pairs(journal) do
        if name ~= activeProfile then
            local target = type(profiles) == "table" and profiles[name] or nil
            if type(target) == "table" then
                for _, field in ipairs(FIELDS) do
                    restoreOnto(target, entry, field)
                end
            end
            journal[name] = nil
        end
    end
end

local function safeDispatch(Core, key)
    return pcall(Core.Dispatch, Core, "Glassy/UPDATE_CONFIG", key)
end

-- ---------------------------------------------------------------------------------------------
-- Apply / ApplyHeight -- one body, parameterised by field
-- ---------------------------------------------------------------------------------------------

local function applyField(field, requested)
    if InCombatLockdown() then return false, false end
    if not isFiniteNumber(requested) or requested <= 0 then return false, false end

    local Core, db = getCore()
    if not Core then return false, false end

    local GlassyDB = _G.GlassyDB
    if type(GlassyDB) ~= "table" then return false, false end

    local activeProfile = db:GetCurrentProfile()
    if type(activeProfile) ~= "string" then return false, false end

    GlassyDB[JOURNAL_KEY] = GlassyDB[JOURNAL_KEY] or {}
    local journal = GlassyDB[JOURNAL_KEY]

    -- Never leave some OTHER profile sitting narrowed just because play moved on.
    sweepStaleProfiles(GlassyDB, journal, activeProfile)

    local key = field.key
    local profile = db.profile
    local rawNow = rawget(profile, key)
    local effectiveNow = profile[key]
    if not isFiniteNumber(effectiveNow) then return false, false end

    -- This field's baseline is only READ out of the stored entry here; nothing is written into
    -- it until a write has really landed, because that entry may also hold the other field's
    -- live claim.
    local stored = journal[activeProfile]
    local rawOrig, original, lastApplied
    if isJournaled(stored, field) and stored[field.applied] == effectiveNow then
        rawOrig, original, lastApplied = stored[field.raw], stored[field.effective], stored[field.applied]
    else
        -- Never journaled, or the field no longer matches what FFSpan last wrote: the user (or
        -- Glassy itself) changed it since. Honor that -- the current value becomes the new
        -- baseline/ceiling.
        rawOrig = (rawNow == nil) and RAW_NIL_MARKER or rawNow
        original = effectiveNow
    end

    if requested < field.softMin then
        -- Fitting into less than the native soft-min would violate the slot; refuse instead.
        return false, false
    end

    local target = math.min(original, requested)

    if target == effectiveNow then
        return true, false -- do not write if unchanged -- neither Glassy's field nor FFSpan's journal
    end

    profile[key] = target
    local ok = safeDispatch(Core, key)
    if not ok then
        profile[key] = rawNow        -- restore data immediately
        safeDispatch(Core, key)      -- best-effort original-value refresh; its own failure is swallowed
        if not lastApplied then
            dropClaim(journal, activeProfile, field) -- never successfully applied -- leave no trace of this field
        end
        return false, false -- honest failure; caller logs. No permanent poison either way.
    end

    local entry = journal[activeProfile]
    if type(entry) ~= "table" then entry = {} end
    entry[field.raw], entry[field.effective], entry[field.applied] = rawOrig, original, target
    journal[activeProfile] = entry
    return true, true
end

function GlassyFit.Apply(widthInUIUnits)
    return applyField(WIDTH, widthInUIUnits)
end

function GlassyFit.ApplyHeight(heightInUIUnits)
    -- Whole units, like the slider (step 1). Floored only once known finite: math.floor would
    -- throw on a non-number, and applyField refuses anything non-finite on its own.
    if isFiniteNumber(heightInUIUnits) then heightInUIUnits = math.floor(heightInUIUnits) end
    return applyField(HEIGHT, heightInUIUnits)
end

-- Turns `chatAlwaysVisible` ON, journaled like the width. It never turns it off, and an option
-- that is already on (the player's, or FFSpan's from earlier) is left alone with no new claim.
function GlassyFit.ApplyAlwaysVisible()
    if InCombatLockdown() then return false, false end
    local Core, db = getCore()
    if not Core then return false, false end
    local GlassyDB = _G.GlassyDB
    if type(GlassyDB) ~= "table" then return false, false end
    local activeProfile = db:GetCurrentProfile()
    if type(activeProfile) ~= "string" then return false, false end

    GlassyDB[JOURNAL_KEY] = GlassyDB[JOURNAL_KEY] or {}
    local journal = GlassyDB[JOURNAL_KEY]
    sweepStaleProfiles(GlassyDB, journal, activeProfile)

    local profile = db.profile
    if profile[ALWAYS.key] == true then return true, false end
    local rawNow = rawget(profile, ALWAYS.key)
    profile[ALWAYS.key] = true
    if not safeDispatch(Core, ALWAYS.key) then
        profile[ALWAYS.key] = rawNow
        safeDispatch(Core, ALWAYS.key)
        return false, false
    end
    local entry = journal[activeProfile]
    if type(entry) ~= "table" then entry = {} end
    entry[ALWAYS.raw] = (rawNow == nil) and RAW_NIL_MARKER or rawNow
    entry[ALWAYS.effective], entry[ALWAYS.applied] = false, true
    journal[activeProfile] = entry
    return true, true
end

-- ---------------------------------------------------------------------------------------------
-- Restore
-- ---------------------------------------------------------------------------------------------

function GlassyFit.Restore(dispatch)
    if dispatch == nil then dispatch = true end

    local Core, db = getCore()
    if not Core then return false, false end

    local GlassyDB = _G.GlassyDB
    if type(GlassyDB) ~= "table" then return false, false end

    local journal = GlassyDB[JOURNAL_KEY]
    if type(journal) ~= "table" then return true, false end -- nothing was ever journaled

    local activeProfile = db:GetCurrentProfile()
    if type(activeProfile) ~= "string" then return false, false end

    -- Only a dispatching restore is layout-affecting; a data-only call (logout, dispatch=false)
    -- never touches anything protected, so combat never blocks it.
    if dispatch and InCombatLockdown() then return false, false end

    sweepStaleProfiles(GlassyDB, journal, activeProfile)

    local entry = journal[activeProfile]
    if not entry then return true, false end

    -- Data first, for BOTH fields, before any dispatch -- every subscriber then sees the whole
    -- restored shape. Each field's claim is dropped either way: restored, or the user changed it
    -- since (honor that, drop the claim only).
    local profile = db.profile
    local restored = {}
    for _, field in ipairs(FIELDS) do
        if restoreOnto(profile, entry, field) then restored[#restored + 1] = field.key end
        dropClaim(journal, activeProfile, field)
    end
    if #restored == 0 then return true, false end

    local ok = true
    if dispatch then
        for _, key in ipairs(restored) do
            -- data really is restored either way; a failed dispatch is reported honestly
            if not safeDispatch(Core, key) then ok = false end
        end
    end
    return ok, true
end
