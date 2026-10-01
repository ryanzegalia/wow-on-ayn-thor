-- FFBinds_Crossbar -- the bar that SHOWS the layout: ConsolePort's own "Crossbar: Triple".
--
-- NOT LOADED since FFBinds 1.8.3: on 2026-09-25 12:08 I saw it on the Thor and wanted the cluster
-- bar back. Kept, corrected, for a later retry; add it back to the
-- TOC to re-enable. 1.8.2 never reached ConsolePort_Bar on the device -- see Cross.BarEnv.
-- 2026-09-25 11:05: I wanted it to work like Final Fantasy XIV. At 11:08 I picked ConsolePort's
-- crossbar look with the hybrid layout (bare face buttons keep their four casts).
--
-- Why Triple and not "Crossbar: Triggers": Triggers draws only the held-trigger sets (Left = M1,
-- Right = M2, Center = M2M1; ConsolePort_Bar/Model/Presets.lua:178-278), so the four bare casts
-- I kept would have no button on screen. Triple's Center group shows the no-modifier set
-- (`mod:M0`) and swaps to ZL+ZR or R3 while they are held; Left is ZL's set, Right is ZR's
-- (Presets.lua:280-424). It is ConsolePort's own FFXIV model: "Group buttons in three layouts, with
-- modifier swapping."
--
-- HOW -- exactly what ConsolePort's own config does when you load a preset
-- (ConsolePort_Bar/View/Config/Loadout.lua:1081-1101, Loadout:OnLoadPreset): release the bar, deep-
-- copy the preset, run it through env.BuildLayout, store it as this character's 'Layout', raise
-- OnLayoutChanged. FFBinds never writes ConsolePort_BarLayout itself; ConsolePort stores it.
--
-- rev 1 (1.8.0 first device run, 11:32) used ConsolePort's `/cp layout <name>` slash command
-- instead (Model/Utils.lua:449-465). That command stores the RAW preset -- it skips BuildLayout --
-- and Triple keeps its modifier and scale drivers as env.RunTimeFilter closures (Utils.lua:376-397)
-- that only BuildLayout turns into condition strings (Model/Upgrade.lua:135-175). The bar was
-- released and nothing could be drawn: no glyphs at all on the Thor. A ConsolePort bug on that
-- path, not in the preset; the config path has no such gap.
--
-- Reaching ConsolePort_Bar's env: it is a RelaTable database (Utils.lua:2,
-- `LibStub('RelaTable')(name, env)`), and RelaTable keeps every database in its LibStub registry
-- under the addon's name (ConsolePort/Libs/External/RelaTable/RelaTable.lua:285-293, rawset(self,
-- id, db)). rawget reads it without creating anything when the bar is not loaded.
--
-- Once per character per REV (FFBindsDB.crossbar[key]), so a different bar I pick later in
-- ConsolePort's config stays his; `/ffbinds crossbar` puts the crossbar back on demand. Runs after
-- applyModifiers: the preset's M3 rows are filtered at build time on GamePadEmulateAlt being a PAD
-- button (Presets.lua:27-29).

local PRESET = 'CrossbarTriple'
local PRESET_NAME = 'Crossbar: Triple'
local REV = 2                          -- bump to re-apply on every character (rev 1 drew nothing)

local Cross = { REV = REV }
FFBinds_Crossbar = Cross

local function note(line)
    local L = type(FFBindsDB) == 'table' and FFBindsDB.log and FFBindsDB.log.results
    if type(L) == 'table' then L[#L + 1] = 'crossbar: ' .. line end
end

function Cross.Key()
    local name = type(UnitName) == 'function' and UnitName('player')
    if not name or name == '' then return nil end
    local realm = type(GetRealmName) == 'function' and GetRealmName() or '?'
    return ('%s:%s-%s'):format(tostring(WOW_PROJECT_ID), tostring(realm), name)
end

-- ConsolePort_Bar's env, or nil when the bar addon is not loaded.
function Cross.BarEnv()
    -- LibStub is a TABLE with a __call metamethod, not a function: 1.8.2 tested type(LibStub) ==
    -- 'function', so on the device this returned nil and logged "ConsolePort_Bar not loaded".
    local ls = _G.LibStub
    local lib = type(ls) == 'table' and type(ls.GetLibrary) == 'function' and ls:GetLibrary('RelaTable', true)
    if type(lib) ~= 'table' then return nil end
    local env = rawget(lib, 'ConsolePort_Bar')
    if type(env) ~= 'table' or type(env.BuildLayout) ~= 'function' or type(env.Presets) ~= 'table' then
        return nil
    end
    return env
end

-- What the bar holds right now: its preset name, and whether every group driver is a built
-- condition string (a closure left in a driver is what drew nothing in rev 1).
function Cross.Current(env)
    env = env or Cross.BarEnv()
    if not env then return nil end
    local ok, layout = pcall(env, 'Layout')
    if not ok or type(layout) ~= 'table' then return nil end
    local built = true
    for _, child in pairs(type(layout.children) == 'table' and layout.children or {}) do
        if type(child) == 'table' then
            for _, key in ipairs({ 'modifier', 'rescale', 'visibility', 'opacity' }) do
                if type(child[key]) == 'function' then built = false end
            end
        end
    end
    return layout.name, built
end

-- Loadout:OnLoadPreset, minus the config panel's own widget release (there is no panel open).
local function loadPreset(env, preset)
    env:ReleaseAll()
    preset = CopyTable(preset)
    if preset.settings then
        for path, data in pairs(preset.settings) do env(path, data) end
        preset.settings = nil
    end
    if preset.pager then
        for path, data in pairs(preset.pager) do env.db(path, data) end
        preset.pager = nil
    end
    env('Layout', env.BuildLayout(preset))
    env:TriggerEvent('OnLayoutChanged', true)
end

-- Returns what happened, for the log and the tests.
function Cross.Ensure(reason, force)
    if type(FFBindsDB) ~= 'table' then return 'no-db' end
    FFBindsDB.crossbar = type(FFBindsDB.crossbar) == 'table' and FFBindsDB.crossbar or {}
    local key = Cross.Key()
    if not key then return 'no-character' end
    local done = FFBindsDB.crossbar[key]
    if type(done) == 'table' and done.rev == REV and not force then return 'done-before' end
    if type(InCombatLockdown) == 'function' and InCombatLockdown() then
        note('deferred, in combat (' .. tostring(reason) .. ')')
        return 'combat'
    end
    local env = Cross.BarEnv()
    if not env then note('ConsolePort_Bar not loaded') return 'no-bar' end
    local preset = env.Presets[PRESET]
    if type(preset) ~= 'table' then note('preset ' .. PRESET .. ' missing') return 'no-preset' end
    local ok, err = pcall(env.RunSafe, env, loadPreset, env, preset)
    if not ok then note('FAILED: ' .. tostring(err)) return 'failed' end
    local name, built = Cross.Current(env)
    FFBindsDB.crossbar[key] = { rev = REV, at = date('%Y-%m-%d %H:%M:%S'), reason = tostring(reason),
                                layout = tostring(name), built = built and true or false }
    note(('%s loaded for %s (%s): bar now "%s", drivers %s'):format(PRESET, key, tostring(reason),
        tostring(name), built and 'built' or 'NOT BUILT'))
    return (name == PRESET_NAME and built) and 'applied' or 'unverified'
end
