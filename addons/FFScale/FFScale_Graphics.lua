-- FFScale_Graphics -- conservative, all-flavor Thor graphics profile.
--
-- Independent of FFScale's Edit Mode layout pass: separate file, separate SavedVariables
-- (FFScaleGraphicsDB -- never FFScaleLog, which a layout run resets), separate event
-- (PLAYER_LOGIN, not PLAYER_ENTERING_WORLD/OnUpdate). Loaded AFTER FFScale.lua (FFScale.toc
-- order) and attaches onto the shared _G.FFScale table as FFScale.Graphics.
--
-- Every advanced-graphics option here is an ORDINARY CVar -- confirmed against a downloaded
-- Blizzard Options_Graphics source (the advanced panel builds these through
-- CreateCVarAccessorClosures, not a special graphics API) and the live beta menu (dropdown
-- raw 0 = Low, view/environment raw 2 = UI "3", ground clutter raw 1 = UI "2"). So this reads
-- and writes them as plain CVars: C_CVar.GetCVar/SetCVar when present, else the global
-- GetCVar/SetCVar -- always called as ordinary functions (C_CVar is a table of static
-- functions, not an object with self methods).
--
-- Deliberately OUT OF SCOPE, never read or written here: graphicsQuality (the master preset),
-- spell/particle density, texture quality, display resolution, UI scale, VSync, MSAA, drivers.

local FFScale = _G.FFScale
if type(FFScale) ~= 'table' then
    FFScale = {}
    _G.FFScale = FFScale
end
FFScale.Graphics = FFScale.Graphics or {}
local Graphics = FFScale.Graphics

-- ---------------------------------------------------------------------------------------------
-- The profile. ORDER MATTERS (applied top to bottom) -- do not resort. UI-panel-equivalent is
-- noted only in a comment; the value actually written is always the raw CVar value.
-- ---------------------------------------------------------------------------------------------
local PROFILE = {
    { cvar = 'graphicsShadowQuality',     value = '0' },
    { cvar = 'graphicsLiquidDetail',      value = '0' },
    { cvar = 'graphicsPBRLiquidDetail',   value = '0' },
    { cvar = 'graphicsSSAO',              value = '0' },
    { cvar = 'graphicsSunshafts',         value = '0' },
    { cvar = 'graphicsDepthEffects',      value = '0' },
    { cvar = 'graphicsComputeEffects',    value = '0' },
    { cvar = 'graphicsLightMode',         value = '0' },
    { cvar = 'graphicsBloomUserMult',     value = '0' },
    { cvar = 'graphicsViewDistance',      value = '2' },  -- UI "3"
    { cvar = 'graphicsEnvironmentDetail', value = '2' },  -- UI "3"
    { cvar = 'graphicsGroundClutter',     value = '1' },  -- UI "2"
    { cvar = 'graphicsProjectedTextures', value = '1' },
    { cvar = 'projectedTextures',         value = '1' },
    { cvar = 'RAIDsettingsEnabled',       value = '0' },  -- same budget applies in raids
    { cvar = 'RenderScale',               value = '0.75' },
    { cvar = 'maxFPS',                    value = '60' },
}

-- ---------------------------------------------------------------------------------------------
-- CVar access -- resolved fresh on every call (never cached), same defensive style as FFScale's
-- own FFSpan bridge: a missing/older C_CVar just falls back to the global, nothing throws.
-- ---------------------------------------------------------------------------------------------
local function cvarGetFn()
    local C = _G.C_CVar
    if type(C) == 'table' and type(C.GetCVar) == 'function' then return C.GetCVar end
    return _G.GetCVar
end

local function cvarSetFn()
    local C = _G.C_CVar
    if type(C) == 'table' and type(C.SetCVar) == 'function' then return C.SetCVar end
    return _G.SetCVar
end

local function readCVar(name)
    local fn = cvarGetFn()
    if type(fn) ~= 'function' then return nil end
    local ok, v = pcall(fn, name)
    if not ok then return nil end
    return v
end

local function writeCVar(name, value)
    local fn = cvarSetFn()
    if type(fn) ~= 'function' then return false, 'no-setter' end
    local ok, err = pcall(fn, name, value)
    if not ok then return false, tostring(err) end
    return true
end

local function isUnsupported(v)
    return v == nil or v == ''
end

-- Numeric-aware compare so a re-formatted readback ("0.750000" vs "0.75") never counts as a
-- mismatch and never triggers a needless re-write.
local function cvarValuesMatch(a, b)
    local na, nb = tonumber(a), tonumber(b)
    if na ~= nil and nb ~= nil then
        return math.abs(na - nb) < 0.0001
    end
    return tostring(a) == tostring(b)
end

-- ---------------------------------------------------------------------------------------------
-- SavedVariables (FFScaleGraphicsDB -- declared in FFScale.toc, never FFScaleLog).
-- ---------------------------------------------------------------------------------------------
local function ensureDB()
    FFScaleGraphicsDB = FFScaleGraphicsDB or {}
    local db = FFScaleGraphicsDB
    db.originals = db.originals or {}
    if db.enabled == nil then db.enabled = true end
    return db
end

-- ---------------------------------------------------------------------------------------------
-- Public API.
-- ---------------------------------------------------------------------------------------------

-- Apply the profile. Never aborts on one bad setting; every outcome is recorded, nothing is
-- claimed applied unless the readback proves it. Safe to call repeatedly (no-ops once correct).
function Graphics.Apply(reason)
    local db = ensureDB()
    local snap = { reason = reason, requested = {}, applied = {}, rejected = {}, missing = {} }
    for _, entry in ipairs(PROFILE) do
        local name, want = entry.cvar, entry.value
        snap.requested[name] = want
        local before = readCVar(name)
        if isUnsupported(before) then
            snap.missing[#snap.missing + 1] = name
        else
            if db.originals[name] == nil then
                db.originals[name] = before   -- preserve ONCE, before the very first write
            end
            if cvarValuesMatch(before, want) then
                snap.applied[name] = before   -- already correct -- no write
            else
                local ok, err = writeCVar(name, want)
                if not ok then
                    snap.rejected[name] = { want = want, before = before, error = err }
                else
                    local after = readCVar(name)
                    if cvarValuesMatch(after, want) then
                        snap.applied[name] = after
                    else
                        snap.rejected[name] = { want = want, before = before, after = after,
                                                 error = 'readback-mismatch' }
                    end
                end
            end
        end
    end
    db.lastStatus = snap
    return snap
end

-- Put every preserved original back and turn autoapply off (per /ffgraphics restore contract).
function Graphics.Restore()
    local db = ensureDB()
    local snap = { reason = 'restore', requested = {}, applied = {}, rejected = {}, missing = {} }
    for _, entry in ipairs(PROFILE) do
        local name = entry.cvar
        local original = db.originals[name]
        if original == nil then
            snap.missing[#snap.missing + 1] = name
        else
            snap.requested[name] = original
            local ok, err = writeCVar(name, original)
            if not ok then
                snap.rejected[name] = { want = original, error = err }
            else
                local after = readCVar(name)
                if cvarValuesMatch(after, original) then
                    snap.applied[name] = after
                else
                    snap.rejected[name] = { want = original, after = after,
                                            error = 'readback-mismatch' }
                end
            end
        end
    end
    db.enabled = false
    db.lastStatus = snap
    return snap
end

-- requested/applied/rejected/missing from the last Apply/Restore, for real-device readback.
function Graphics.Status()
    local db = ensureDB()
    local last = db.lastStatus or {}
    return {
        enabled   = db.enabled,
        reason    = last.reason,
        requested = last.requested or {},
        applied   = last.applied or {},
        rejected  = last.rejected or {},
        missing   = last.missing or {},
        originals = db.originals,
    }
end

-- The ordered CVar list itself, for a caller that wants to read the live client independently.
function Graphics.Profile()
    local out = {}
    for i, entry in ipairs(PROFILE) do
        out[i] = { cvar = entry.cvar, value = entry.value }
    end
    return out
end

-- ---------------------------------------------------------------------------------------------
-- /ffgraphics status|apply|off|restore
-- ---------------------------------------------------------------------------------------------
local function countKeys(t)
    local n = 0
    for _ in pairs(t or {}) do n = n + 1 end
    return n
end

local function reportSnapshot(snap)
    print(string.format('FFScale.Graphics: applied=%d rejected=%d missing=%d (reason=%s)',
        countKeys(snap.applied), countKeys(snap.rejected), countKeys(snap.missing),
        tostring(snap.reason)))
    for name, info in pairs(snap.rejected or {}) do
        local errText = type(info) == 'table' and tostring(info.error) or tostring(info)
        print(string.format('  REJECTED %s: %s', name, errText))
    end
    for _, name in ipairs(snap.missing or {}) do
        print(string.format('  MISSING %s (not supported on this client)', name))
    end
end

local function slash(msg)
    msg = tostring(msg or ''):lower():match('^%s*(.-)%s*$')
    local db = ensureDB()
    if msg == 'off' then
        db.enabled = false
        print('FFScale.Graphics: autoapply OFF (current values left as-is)')
    elseif msg == 'restore' then
        print('FFScale.Graphics: restoring original values, autoapply OFF')
        reportSnapshot(Graphics.Restore())
    elseif msg == 'apply' then
        db.enabled = true
        reportSnapshot(Graphics.Apply('slash'))
    elseif msg == 'status' or msg == '' then
        local snap = Graphics.Status()
        print(string.format('FFScale.Graphics: autoapply=%s', tostring(snap.enabled)))
        reportSnapshot(snap)
    else
        print('/ffgraphics status|apply|off|restore')
    end
end

SLASH_FFGRAPHICS1 = '/ffgraphics'
SlashCmdList['FFGRAPHICS'] = function(msg) pcall(slash, msg) end

-- ---------------------------------------------------------------------------------------------
-- Apply ONCE per fresh login/reload. PLAYER_LOGIN (not PLAYER_ENTERING_WORLD) fires exactly
-- once per UI load and never again on a zone change, so this never re-applies mid-session; the
-- 2 s delay lets the client's own CVar defaults settle first. No OnUpdate, no retry loop.
-- ---------------------------------------------------------------------------------------------
local loginFrame = CreateFrame('Frame')
loginFrame:RegisterEvent('PLAYER_LOGIN')
loginFrame:SetScript('OnEvent', function()
    C_Timer.After(2, function()
        local db = ensureDB()
        if db.enabled then
            pcall(Graphics.Apply, 'login')
        end
    end)
end)
