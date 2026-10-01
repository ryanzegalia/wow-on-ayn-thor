-- FFBinds -- one controller layout for every WoW flavor on the Thor (retail, MoP Classic,
-- Forever beta). Design goal (2026-09-22): everything that is not specific to one class is the default
-- in all three games, so switching flavors feels like the same game on the same buttons.
--
-- What it owns (all class-agnostic: action SLOTS, targeting, menus, chat -- never spells):
--   1. LAYOUT: every gamepad button x modifier layer -> binding command. Seeded from retail's
--      live layout (ConsolePort's automatic binding backup of my character, 2026-09-22 21:22).
--      '' means unbound, so a stray binding in another flavor is cleared too.
--   2. ConsolePort's keyboardEnable -- the radial keyboard that opens with chat (double-tap R3,
--      FFBinds_Camera.lua; the capture button's OPENCHAT).
--   3. The GamePad*/SoftTarget* cvars (mouse-click emulation, camera and stick feel), seeded from
--      retail; and since v1.8 the three MODIFIER buttons (ZL = Shift, ZR = Ctrl, R3 = Alt), set
--      through ConsolePort's own setter so its bar and binding config follow (applyModifiers).
--   (1.8.0-1.8.2 also switched ConsolePort's bar to "Crossbar: Triple"; I kept the new
--   buttons but dropped the crossbar look in 1.8.3, so FFBinds_Crossbar.lua is no longer in the TOC.)
--
-- How parity holds: at login the layout is applied to whatever flavor is running (a no-op on
-- retail). For SETTLE seconds after that, a binding change is the client's own late load
-- (server binding sync) and is overridden; after it, a change is an edit by the player and is written
-- back into FFBindsDB. wowlaunch.sh mirrors FFBinds.lua newest-wins across flavors
-- (mirror/shared-sv.list), so an edit made in any flavor reaches the others on their next launch.
-- A command a flavor does not have (SetBinding refuses it) is logged and never captured.
--
-- Last run: FFBindsDB.log (read the SavedVariables after a clean Game Menu exit).

local ADDON = ...

-- Bump to push a new LAYOUT over edits already saved in FFBindsDB.
local SEED = 'retail-seed-2026-09-23-ringscope'
local SETTLE = 15

-- Every layer three modifiers make, in the order WoW spells a chord (ALT-CTRL-SHIFT-PAD1).
local MODS = { '', 'SHIFT-', 'CTRL-', 'CTRL-SHIFT-', 'ALT-', 'ALT-SHIFT-', 'ALT-CTRL-', 'ALT-CTRL-SHIFT-' }

-- ============================ v1.8: THE TRIGGERS ARE THE MODIFIERS ============================
-- 2026-09-25 11:05: I wanted both triggers and R3 to be the modifiers, with the buttons moved to
-- work like regular hotkeys that can be modified, the way Final Fantasy XIV does it. Why the bumpers had to stop being modifiers: WoW's gamepad emulation turns a
-- GamePadEmulate* button into the modifier KEY before any binding is looked up, so a modifier
-- button never dispatches a binding of its own under another modifier (only a quick tap inside
-- GamePadEmulateTapWindowMs gets through), and ConsolePort deletes such chords whenever a modifier
-- changes (ConsolePort/Model/Gamepad/Gamepad.lua:255-265 wipes Index.Modifier.Blocked, built at
-- :393-403). So R3 + L could never be a binding while L was a modifier (it was Ctrl).
--
-- The scheme is ConsolePort's own "Triggers" modifier preset (Gamepad.lua:696-697, "beneficial if
-- you are transitioning from FFXIV", Locale/enUS.lua:360-363) plus R3 as the third:
--   ZL = Shift (M1)   ZR = Ctrl (M2)   R3 = Alt (M3)   -- L and R are ordinary buttons on all 8 layers
--
-- My pick (11:08): HYBRID, keep the four bare face-button casts, and move every chord so each
-- PHYSICAL press does what it did before wherever the hardware allows. What the modifiers WERE is
-- measured, not assumed: the 1.8.0 device log (11:32) read the client defaults as Shift = ZL
-- (PADLTRIGGER) and Ctrl = L (PADLSHOULDER) -- the opposite of what this file's comments said
-- since 09-22 (I had it as "not read yet"). So:
--   ZL + x    = what ZL + x did   (ZL stays Shift: SHIFT- layer untouched)
--   ZR + x    = what L + x did    (Ctrl moves from L to ZR: CTRL- layer untouched)
--   ZL+ZR + x = what ZL+L + x did (CTRL-SHIFT- untouched)
--   L         = ZR's old job (bar slots 11/12 and their layers); R unchanged
--   R3 + L / R = camera zoom out / in -- plain native bindings now, remappable like any other
-- The bar stays ConsolePort's Default cluster bar (1.8.3: I dropped the crossbar look).
-- A layout saved under the old scheme is converted by migrateToTriggers() below, edits included.
-- 1.8.0 assumed Shift = L and swapped SHIFT-/CTRL- on conversion, which flipped the ZL and ZR sets
-- on the Thor at 11:32; a file carrying that version's flag is swapped back once (MOD_SCHEME_180).
local MOD_SCHEME = 'triggers-2026-09-25b'
local MOD_SCHEME_180 = 'triggers-2026-09-25'
local MODIFIERS = { Shift = 'PADLTRIGGER', Ctrl = 'PADRTRIGGER', Alt = 'PADRSTICK' }
-- Ctrl first: the client default is Ctrl = L and Shift = ZL; Ctrl has to reach ZR before anything
-- else moves, so no button ever carries two modifiers even for a moment.
local MODIFIER_ORDER = { 'Ctrl', 'Shift', 'Alt' }

-- Nintendo glyph positions (GamePadConfig_Thor.json): PAD1 = B (bottom), PAD2 = A (right),
-- PAD3 = Y (left), PAD4 = X (top). PADFORWARD = +, PADBACK = -, PADSOCIAL = capture.
-- ZL, ZR and R3 (PADLTRIGGER / PADRTRIGGER / PADRSTICK) carry no bindings of their own: they are
-- the Shift / Ctrl / Alt modifiers. Layers not written here are '' (filled in below), so every one
-- of the 8 layers of every button is in the shared layout and an edit to any of them is captured.
local LAYOUT = {
    PAD1 = { [''] = 'ACTIONBUTTON1', ['SHIFT-'] = 'ACTIONBUTTON2', ['CTRL-'] = 'MULTIACTIONBAR1BUTTON1', ['CTRL-SHIFT-'] = 'MULTIACTIONBAR1BUTTON2' },
    PAD2 = { [''] = 'ACTIONBUTTON3', ['SHIFT-'] = 'ACTIONBUTTON4', ['CTRL-'] = 'MULTIACTIONBAR1BUTTON3', ['CTRL-SHIFT-'] = 'MULTIACTIONBAR1BUTTON4' },
    PAD3 = { [''] = 'ACTIONBUTTON5', ['SHIFT-'] = 'ACTIONBUTTON6', ['CTRL-'] = 'MULTIACTIONBAR1BUTTON5', ['CTRL-SHIFT-'] = 'MULTIACTIONBAR1BUTTON6' },
    PAD4 = { [''] = 'ACTIONBUTTON7', ['SHIFT-'] = 'ACTIONBUTTON8', ['CTRL-'] = 'MULTIACTIONBAR1BUTTON7', ['CTRL-SHIFT-'] = 'MULTIACTIONBAR1BUTTON8' },
    PAD5 = {},
    PAD6 = {},
    PADDUP = { [''] = 'INTERACTTARGET', ['SHIFT-'] = 'TARGETNEARESTFRIEND', ['CTRL-'] = 'MULTIACTIONBAR2BUTTON7', ['CTRL-SHIFT-'] = 'MULTIACTIONBAR2BUTTON1' },
    PADDDOWN = { [''] = 'TARGETPREVIOUSENEMY', ['SHIFT-'] = 'TARGETPREVIOUSFRIEND', ['CTRL-'] = 'MULTIACTIONBAR2BUTTON8', ['CTRL-SHIFT-'] = 'MULTIACTIONBAR2BUTTON2' },
    PADDLEFT = { [''] = 'TARGETFOCUS', ['SHIFT-'] = 'FOCUSTARGET', ['CTRL-'] = 'MULTIACTIONBAR2BUTTON9', ['CTRL-SHIFT-'] = 'MULTIACTIONBAR2BUTTON3' },
    PADDRIGHT = { [''] = 'TARGETNEARESTENEMY', ['SHIFT-'] = 'ASSISTTARGET', ['CTRL-'] = 'MULTIACTIONBAR2BUTTON10', ['CTRL-SHIFT-'] = 'MULTIACTIONBAR2BUTTON4' },
    -- R3 + L / R3 + R: the camera, all the way out / all the way into first person, held for
    -- continuous zoom (the client's own behaviour for these two commands), secure, works in combat.
    PADLSHOULDER = { [''] = 'ACTIONBUTTON11', ['SHIFT-'] = 'ACTIONBUTTON12', ['CTRL-'] = 'MULTIACTIONBAR1BUTTON11', ['CTRL-SHIFT-'] = 'MULTIACTIONBAR1BUTTON12',
                     ['ALT-'] = 'CAMERAZOOMOUT' },
    PADRSHOULDER = { [''] = 'ACTIONBUTTON9', ['SHIFT-'] = 'ACTIONBUTTON10', ['CTRL-'] = 'MULTIACTIONBAR1BUTTON9', ['CTRL-SHIFT-'] = 'MULTIACTIONBAR1BUTTON10',
                     ['ALT-'] = 'CAMERAZOOMIN' },
    PADLTRIGGER = {},
    PADRTRIGGER = {},
    PADLSTICK = { [''] = 'JUMP' },
    -- R3 is the Alt modifier (v1.7). Chat is a double tap of it (FFBinds_Camera.lua); the capture
    -- button (PADSOCIAL) still opens chat on one press.
    PADRSTICK = {},
    PADFORWARD = { [''] = '', ['SHIFT-'] = 'OPENALLBAGS', ['CTRL-'] = 'TOGGLECHARACTER0', ['CTRL-SHIFT-'] = '' },
    -- v1.1 (decided 2026-09-23): `-` opens/closes ConsolePort's menu RING instead of the game
    -- menu. ConsolePortMenuTrigger is a SecureHandlerBaseTemplate button parented to GameMenuFrame
    -- (ConsolePort_Menu/View/Menu.xml:70) with registerForClicks="AnyUp", so the click lands on the
    -- UP event. Ring.lua:80-98 OnTrigger shows the ring, or closes it when it is already visible;
    -- while the ring is up Ring.lua:228-242 binds LB/RB to TOGGLEGAMEMENU, so RB from the ring is
    -- the game menu. Keyboard Escape is untouched, and single screen gets the same binding.
    PADBACK = { [''] = 'CLICK ConsolePortMenuTrigger:LeftButton', ['SHIFT-'] = '', ['CTRL-'] = '', ['CTRL-SHIFT-'] = '' },
    PADSYSTEM = { [''] = '', ['SHIFT-'] = '', ['CTRL-'] = '', ['CTRL-SHIFT-'] = '' },
    PADSOCIAL = { [''] = 'OPENCHAT', ['SHIFT-'] = '', ['CTRL-'] = '', ['CTRL-SHIFT-'] = '' },
    PADPADDLE1 = { [''] = '', ['SHIFT-'] = '', ['CTRL-'] = '', ['CTRL-SHIFT-'] = '' },
    PADPADDLE2 = { [''] = '', ['SHIFT-'] = '', ['CTRL-'] = '', ['CTRL-SHIFT-'] = '' },
    PADPADDLE3 = { [''] = '', ['SHIFT-'] = '', ['CTRL-'] = '', ['CTRL-SHIFT-'] = '' },
    PADPADDLE4 = { [''] = '', ['SHIFT-'] = '', ['CTRL-'] = '', ['CTRL-SHIFT-'] = '' },
    PADLSTICKUP = { [''] = '', ['SHIFT-'] = '', ['CTRL-'] = '', ['CTRL-SHIFT-'] = '' },
    PADLSTICKDOWN = { [''] = '', ['SHIFT-'] = '', ['CTRL-'] = '', ['CTRL-SHIFT-'] = '' },
    PADLSTICKLEFT = { [''] = '', ['SHIFT-'] = '', ['CTRL-'] = '', ['CTRL-SHIFT-'] = '' },
    PADLSTICKRIGHT = { [''] = '', ['SHIFT-'] = '', ['CTRL-'] = '', ['CTRL-SHIFT-'] = '' },
    PADRSTICKUP = { [''] = '', ['SHIFT-'] = '', ['CTRL-'] = '', ['CTRL-SHIFT-'] = '' },
    PADRSTICKDOWN = { [''] = '', ['SHIFT-'] = '', ['CTRL-'] = '', ['CTRL-SHIFT-'] = '' },
    PADRSTICKLEFT = { [''] = '', ['SHIFT-'] = '', ['CTRL-'] = '', ['CTRL-SHIFT-'] = '' },
    PADRSTICKRIGHT = { [''] = '', ['SHIFT-'] = '', ['CTRL-'] = '', ['CTRL-SHIFT-'] = '' },
}
for _, layers in pairs(LAYOUT) do
    for _, mod in ipairs(MODS) do
        if layers[mod] == nil then layers[mod] = '' end
    end
end

-- v1.8: a layout saved under the old modifiers (Shift = ZL, Ctrl = L), converted so every physical
-- press keeps its meaning (see the scheme above). Shift stays on ZL and Ctrl only changes finger
-- (L -> ZR), so the SHIFT- and CTRL- layers keep their chords; the one move is ZR's own slots
-- going to L, which is free now. Pure: returns a new table, the input untouched. my own edits
-- ride along, because they are moved by the same rule as the defaults.
local function copyLayers(old)
    local out = {}
    for button, layers in pairs(old) do
        local c = {}
        for mod, command in pairs(layers) do c[mod] = command end
        out[button] = c
    end
    return out
end

local function migrateToTriggers(old)
    local out = copyLayers(old)
    -- L takes ZR's old job; the two triggers are modifiers now and carry nothing of their own.
    out.PADLSHOULDER = out.PADRTRIGGER or {}
    out.PADLTRIGGER, out.PADRTRIGGER = {}, {}
    for _, b in ipairs({ 'PADLTRIGGER', 'PADRTRIGGER' }) do
        for _, mod in ipairs(MODS) do out[b][mod] = '' end
    end
    -- v1.7's second zoom-in chord (ALT-SHIFT-PADRSHOULDER, "with L held too") was written for an
    -- L that was never Shift; it has no job now that R3 + R is the zoom on its own.
    local r = out.PADRSHOULDER
    if r and r['ALT-SHIFT-'] == 'CAMERAZOOMIN' then r['ALT-SHIFT-'] = '' end
    return out
end
FFBinds_MigrateToTriggers = migrateToTriggers

-- 1.8.0 swapped SHIFT-/CTRL- on conversion (wrong premise, see the scheme). The swap is its own
-- inverse, so a 1.8.0-converted layout gets it once more -- edits made since ride along too.
local SWAP = { ['SHIFT-'] = 'CTRL-', ['CTRL-'] = 'SHIFT-', ['ALT-SHIFT-'] = 'ALT-CTRL-', ['ALT-CTRL-'] = 'ALT-SHIFT-' }
local function undo180Swap(layout)
    local out = {}
    for button, layers in pairs(layout) do
        local moved = {}
        for mod, command in pairs(layers) do moved[SWAP[mod] or mod] = command end
        out[button] = moved
    end
    return out
end
FFBinds_Undo180Swap = undo180Swap

-- Cvars with another owner: the launcher's Config.wtf overlay pins these, and ConsolePort flips
-- GamePadStickAxisButtons / SoftTargetInteract at runtime to match its own bindings. v1.8: the
-- three modifier cvars are FFBindsDB.modifiers' (applyModifiers), never the generic cvar sync.
local CVAR_SKIP = {
    GamePadEnable = true, GamePadSingleActiveID = true, GamePadStickAxisButtons = true,
    GamePadCursorAutoEnable = true, GamePadCursorCenteredEmulation = true,
    GamePadCursorForTargeting = true, GamePadFaceMovement = true, SoftTargetInteract = true,
    GamePadEmulateShift = true, GamePadEmulateCtrl = true, GamePadEmulateAlt = true,
}

local IS_RETAIL = WOW_PROJECT_ID == WOW_PROJECT_MAINLINE
local ACCOUNT_SET = Enum.BindingSet and Enum.BindingSet.Account or 1
local CHARACTER_SET = Enum.BindingSet and Enum.BindingSet.Character or 2

local refused = {}        -- chord -> command this client does not accept
local appliedAt           -- GetTime() of the first successful layout pass this session
local applying = false
local pendingCombat = false
local cvarBase = {}       -- tracked cvar values right after enforcement; logout diffs against it

local function log(line)
    local L = FFBindsDB.log.results
    L[#L + 1] = line
end

local function bindingSet()
    local set = GetCurrentBindingSet and GetCurrentBindingSet()
    if set == ACCOUNT_SET or set == CHARACTER_SET then return set end
end

local migratedScheme      -- set when this login converted a saved layout (logged once the log exists)
local corrected180        -- set when this login swapped a 1.8.0 conversion back

local function initDB()
    FFBindsDB = FFBindsDB or {}
    if FFBindsDB.seed ~= SEED or type(FFBindsDB.layout) ~= 'table' then
        FFBindsDB.layout = CopyTable(LAYOUT)
        FFBindsDB.seed = SEED
        FFBindsDB.modScheme = MOD_SCHEME          -- LAYOUT is already written in it
    elseif FFBindsDB.modScheme == MOD_SCHEME_180 then
        FFBindsDB.layout = undo180Swap(FFBindsDB.layout)
        FFBindsDB.modScheme = MOD_SCHEME
        corrected180 = true
    elseif FFBindsDB.modScheme ~= MOD_SCHEME then
        -- v1.8, once per install (the flag travels with the mirrored SavedVariables, so a flavor
        -- that receives an already-converted file does not convert it twice).
        FFBindsDB.layout = migrateToTriggers(FFBindsDB.layout)
        FFBindsDB.modScheme = MOD_SCHEME
        migratedScheme = true
    end
    -- The modifier buttons. Reset to the scheme's on conversion; after that a change I make in
    -- ConsolePort's own config is captured at logout (captureModifiers) and is his.
    if type(FFBindsDB.modifiers) ~= 'table' or migratedScheme then
        FFBindsDB.modifiers = CopyTable(MODIFIERS)
    end
    if type(FFBindsDB.cvars) == 'table' then
        for name in pairs(CVAR_SKIP) do FFBindsDB.cvars[name] = nil end
    end
    -- Buttons or layers added to LAYOUT under the same seed.
    for button, layers in pairs(LAYOUT) do
        local mine = FFBindsDB.layout[button] or {}
        FFBindsDB.layout[button] = mine
        for mod, command in pairs(layers) do
            if mine[mod] == nil then mine[mod] = command end
        end
    end
    -- v1.7: R3 becomes the Alt modifier WITHOUT a seed bump (a bump would throw away every edit
    -- I have saved). Its old defaults -- chat (1.5) and the 1.6 click layer -- are cleared; an R3
    -- he bound to something else himself stays his. Once per install; the flag travels with the
    -- mirrored SavedVariables. (The Alt cvar itself is FFBindsDB.modifiers' since v1.8.)
    if not FFBindsDB.r3Alt then
        local r3 = FFBindsDB.layout.PADRSTICK
        if r3 and (r3[''] == 'OPENCHAT' or r3[''] == 'CLICK FFBindsCamLayer:LeftButton') then
            r3[''] = LAYOUT.PADRSTICK['']
        end
        FFBindsDB.r3Alt = true
    end
    FFBindsDB.log = {
        stamp = date('%Y-%m-%d %H:%M:%S'),
        client = ('%s (project %s)'):format(tostring((GetBuildInfo())), tostring(WOW_PROJECT_ID)),
        results = {},
    }
    if migratedScheme then
        log('scheme: saved layout converted to ' .. MOD_SCHEME .. ' (ZL = Shift, ZR = Ctrl, R3 = Alt; L takes ZR\'s old slots)')
    end
    if corrected180 then
        log('scheme: 1.8.0 conversion swapped back (ZL keeps its old Shift set, ZR takes L\'s old Ctrl set)')
    end
end

-- v1.8: the modifier buttons go through ConsolePort's OWN cvar setter when it is there
-- (ConsolePort/Utils/Database.lua:16-28: db:SetCVar sets the cvar and fires the db event of the same
-- name). That event is what makes R3 a real ConsolePort modifier instead of a bare cvar: its
-- callback (Gamepad.lua:255-265) re-indexes the modifiers, wipes the chords a modifier makes
-- impossible and raises OnModifierChanged, which is how the bar and the binding config learn the
-- new layer. v1.7 set GamePadEmulateAlt with a raw SetCVar after ConsolePort had indexed its
-- modifiers, so none of that ran and the ALT layer never appeared (10:56: the bar graphics
-- had to change and the modifier had to be mappable). Out of combat only; runs BEFORE applyLayout, so the
-- wipe of transiently-impossible chords happens first and the layout lands on top of it.
local modifiersApplied

local function applyModifiers(reason)
    local want = FFBindsDB.modifiers
    if type(want) ~= 'table' then return end
    if InCombatLockdown() then pendingCombat = true return end
    local cp = ConsolePort and ConsolePort.GetData and ConsolePort:GetData()
    local viaCP = type(cp) == 'table' and type(cp.SetCVar) == 'function'
    local set = {}
    for _, mod in ipairs(MODIFIER_ORDER) do
        local cvar, value = 'GamePadEmulate' .. mod, want[mod]
        local current = GetCVar(cvar)
        if value and current ~= nil and current ~= value then
            local ok
            if viaCP then ok = pcall(cp.SetCVar, cp, cvar, value) else ok = pcall(SetCVar, cvar, value) end
            set[#set + 1] = ('%s %s->%s%s'):format(mod, tostring(current), value, ok and '' or ' FAILED')
        end
    end
    modifiersApplied = true
    if #set > 0 or not reason or reason == 'login' then
        log(('modifiers: %s%s (%s)'):format(#set > 0 and table.concat(set, ', ') or 'already set',
            viaCP and ' via ConsolePort' or ' via SetCVar (no ConsolePort)', tostring(reason)))
    end
end
FFBinds_ApplyModifiers = applyModifiers

-- A modifier I move in ConsolePort's config becomes the shared one (mirrored to every flavor).
local function captureModifiers()
    local mine = FFBindsDB.modifiers
    if type(mine) ~= 'table' or not modifiersApplied then return end
    for _, mod in ipairs(MODIFIER_ORDER) do
        local now = GetCVar('GamePadEmulate' .. mod)
        if now and now ~= mine[mod] then
            log(('modifiers: captured %s %s->%s'):format(mod, tostring(mine[mod]), now))
            mine[mod] = now
        end
    end
end

local function applyLayout()
    if InCombatLockdown() then pendingCombat = true return end -- SetBinding is blocked in combat
    local set = bindingSet()
    if not set then return end -- bindings not loaded yet; the next UPDATE_BINDINGS retries
    local changed, fails = 0, {}
    applying = true
    for button, layers in pairs(FFBindsDB.layout) do
        for mod, command in pairs(layers) do
            local chord = mod .. button
            if not refused[chord] and (GetBindingAction(chord) or '') ~= command then
                local ok
                -- A click binding has to go through SetBindingClick; GetBindingAction reads it
                -- back in this same 'CLICK <frame>:<button>' form, so the compare above and
                -- captureEdits() below both round-trip without a special case.
                local clickFrame, clickButton = command:match('^CLICK ([^:]+):(.+)$')
                if command == '' then
                    ok = SetBinding(chord)
                elseif clickFrame then
                    -- Both halves are conditional on purpose: Classic/Forever may not have
                    -- SetBindingClick at all, and the target frame only exists when the addon
                    -- that owns it (ConsolePort) is loaded. Either way the chord is REFUSED and
                    -- logged rather than bound to something that is not there.
                    ok = type(SetBindingClick) == 'function' and _G[clickFrame] ~= nil
                         and SetBindingClick(chord, clickFrame, clickButton) or false
                else
                    ok = SetBinding(chord, command)
                end
                if ok then
                    changed = changed + 1
                else
                    refused[chord] = command
                    fails[#fails + 1] = chord .. '=' .. command
                end
            end
        end
    end
    if changed > 0 then SaveBindings(set) end
    applying = false
    if changed > 0 or #fails > 0 or not appliedAt then
        log(('layout: %d chord(s) changed, set %d%s'):format(changed, set,
            #fails > 0 and (', REFUSED ' .. table.concat(fails, ' ')) or ''))
    end
    if not appliedAt then
        appliedAt = GetTime()
        if changed > 0 then
            print(('|cff69ccf0FFBinds:|r controller layout applied (%d binding(s) changed).'):format(changed))
        end
    end
end

-- A binding change after the settle window is the player's: take it into the shared layout.
local function captureEdits()
    if not bindingSet() then return end
    local edits = {}
    for button, layers in pairs(FFBindsDB.layout) do
        for mod, command in pairs(layers) do
            local chord = mod .. button
            local current = GetBindingAction(chord) or ''
            if not refused[chord] and current ~= command then
                layers[mod] = current
                edits[#edits + 1] = chord .. '=' .. current
            end
        end
    end
    if #edits > 0 then
        FFBindsDB.edited = date('%Y-%m-%d %H:%M:%S') .. ' project ' .. tostring(WOW_PROJECT_ID)
        log('captured edit: ' .. table.concat(edits, ' '))
    end
end

local function trackedCvars()
    local out = {}
    local all = C_Console and C_Console.GetAllCommands and C_Console.GetAllCommands()
    local cvarType = Enum.ConsoleCommandType and Enum.ConsoleCommandType.Cvar
    for _, info in ipairs(all or {}) do
        local name = info.command
        if name and (cvarType == nil or info.commandType == cvarType) and not CVAR_SKIP[name]
                and (name:find('^GamePad') or name:find('^SoftTarget')) and GetCVar(name) ~= nil then
            out[#out + 1] = name
        end
    end
    return out
end

local function syncCvars()
    local names = trackedCvars()
    if not FFBindsDB.cvars and IS_RETAIL then
        FFBindsDB.cvars = {}
        for _, name in ipairs(names) do FFBindsDB.cvars[name] = GetCVar(name) end
        FFBindsDB.cvarsFrom = FFBindsDB.log.client .. ' ' .. FFBindsDB.log.stamp
        log(('cvars: seeded %d from retail'):format(#names))
    elseif FFBindsDB.cvars then
        local set = {}
        for name, value in pairs(FFBindsDB.cvars) do
            local current = GetCVar(name)
            if current ~= nil and current ~= value and pcall(SetCVar, name, value) then
                set[#set + 1] = name .. '=' .. value
            end
        end
        log(('cvars: %d set%s'):format(#set, #set > 0 and (' ' .. table.concat(set, ' ')) or ''))
    else
        log('cvars: no retail seed yet (log in on retail once)')
    end
    for _, name in ipairs(names) do cvarBase[name] = GetCVar(name) end
end

-- Cvars the player changed this session (e.g. in ConsolePort's config) join the shared set.
local function captureCvars()
    if not FFBindsDB.cvars then return end
    for name, base in pairs(cvarBase) do
        local current = GetCVar(name)
        if current ~= nil and current ~= base then FFBindsDB.cvars[name] = current end
    end
end

local function consolePortKeyboard()
    local cp = ConsolePort and ConsolePort.GetData and ConsolePort:GetData()
    if not cp then log('keyboard: ConsolePort absent') return end
    local ok, on = pcall(cp, 'keyboardEnable')
    if ok and on then log('keyboard: already on') return end
    local ok2, err = pcall(cp, 'Settings/keyboardEnable', true)
    log(ok2 and 'keyboard: keyboardEnable -> true' or ('keyboard: FAILED ' .. tostring(err)))
end


-- ======================================== v1.2: `-` IS ONE STEP BACK ===========================
-- Design goal: it must not feel janky. Start from what actually gets pressed in real gameplay.
--
-- What I hit: the Thor's pad is Nintendo-labelled, so the button that says A is PAD2, and PAD2 is
-- ConsolePort's PLURAL, the pick that DELIBERATELY keeps the ring open
-- (ConsolePort_Menu/View/Ring.lua:129 `if ( button == PLURAL ) then return`). So the natural
-- "A = confirm" press opened the window AND left the ring sitting on top of it, holding the stick
-- and the face buttons and obstructing ConsolePort's cursor (Ring.lua:251-252). On the device the
-- log showed Professions, Collections, Map, Achievements, Calendar, Housing and Friends, each
-- closing within a second of the next opening.
--
-- And `-` had no way back. Since v1.1 it is the ring trigger, so with the game menu open
-- Ring.lua:80-82 sees `isMenuOpen`, hides an already-hidden ring, and nothing happens -- a dead
-- button. Nothing on the pad could close a window except cursoring to its X.
--
-- The contract, from the player's side:
--   a. ring open            -> close the ring, change nothing else
--   b. else any MENU window -> close them all, in ONE press, with no ring flash
--   c. else                 -> open the ring
--
-- FFSpan owns what a MENU window is (S.IsMenuWindow / S.MenuWindowsOpen) -- one list, not a copy
-- that drifts from the one deciding layout. Bags, the home HUD and NPC windows are not menu
-- windows: at a vendor `-` opens the ring so Character can be added BESIDE the vendor, which is
-- the whole point of the companion lane.
--
-- Rule (b) fires before rule (c), and after 1.2 every ring pick closes the ring. So out of combat
-- `-` never opens the ring over an open menu window. This does not make RB from the ring reach the
-- game menu in one press: WoW still closes the bags and clears the target on that press before it
-- opens the menu. FFBinds adds no binding of its own for RB.
local RING_TRIGGER = 'ConsolePortMenuTrigger'
local BACK_CHORD   = 'PADBACK'
local backButton, backOwner, overrideOn, pendingClose

local function inCombat()
    return InCombatLockdown and InCombatLockdown() or false
end

local function spanMenuWindows()
    local S = _G.FFSpan
    if not S or type(S.MenuWindowsOpen) ~= 'function' then return {} end
    local ok, list = pcall(S.MenuWindowsOpen)
    return (ok and type(list) == 'table') and list or {}
end

-- v1.8.4 (the Shop was really hard to close). The Shop's only gamepad close is its
-- Escape handler, which lives in the Escape chain the menu button skips, and ConsolePort's cursor
-- cannot reach a forbidden frame. FFSpan owns the check and the close (S.ShopShown / S.CloseShop,
-- FFSpan_Dismiss.lua): the shop's state is read, and ToggleStoreUI is called only while one is
-- open, so these can never open it.
local function shopShown()
    local S = _G.FFSpan
    if not S or type(S.ShopShown) ~= 'function' then return false end
    local ok, open = pcall(S.ShopShown)
    return ok and open and true or false
end

local function closeShop(reason)
    local S = _G.FFSpan
    if not S or type(S.CloseShop) ~= 'function' then return false end
    local ok, closed = pcall(S.CloseShop, reason)
    if ok and closed then log(('shop: closed (%s)'):format(tostring(reason))) end
    return ok and closed and true or false
end

local function ringVisible()
    local ring = _G.ConsolePortMenuRing
    return ring and ring.IsVisible and ring:IsVisible() and true or false
end

-- v1.4: the one gate every protected call in this file goes through. ShowUIPanel, HideUIPanel,
-- ToggleUIPanel, ToggleGameMenu and GameMenuFrame_Show are all protected: from an addon's tainted
-- handler in combat they refuse AND put a red "Interface action blocked" message on the screen.
-- There is no clever way round it -- securecallfunction does not launder an addon's taint -- so
-- FFBinds does not call them, and WoW's own secure bindings carry the pad through the fight.
local combatDriver, combatSwapActive, combatNoted, ringRefSet

local function protectedAllowed()
    return not inCombat()
end

-- One line per fight, not one per press: a player mashing `-` mid-pull should not fill the log
-- with the same sentence, and the count is what shows it happened more than once.
local function noteCombat(what)
    if combatNoted == what then return end
    combatNoted = what
    log('combat: ' .. what .. ' -- deferred to the end of the fight (no protected call made)')
end

-- Close one menu window the way the client expects it to be closed. HideUIPanel is the right call
-- for anything the panel manager owns -- a bare Hide() leaves its slot allocated and the next
-- window opens in the wrong place -- and Hide() is the fallback for frames it does not own.
local function closeWindow(name)
    local f = _G[name]
    if not f or not (f.IsVisible and f:IsVisible()) then return false end
    -- v1.4: HideUIPanel is protected. 1.2 only deferred IsProtected() frames, so an ordinary
    -- panel took this path in combat and the player got a red blocked message instead of a close.
    if not protectedAllowed() then return false end
    if name == 'GameMenuFrame' and type(_G.HideUIPanel) == 'function' then
        _G.HideUIPanel(f); return true
    end
    if _G.UIPanelWindows and _G.UIPanelWindows[name] and type(_G.HideUIPanel) == 'function' then
        _G.HideUIPanel(f); return true
    end
    if type(_G.HideUIPanel) == 'function' and f.IsProtected and f:IsProtected() then
        _G.HideUIPanel(f); return true
    end
    if f.Hide then f:Hide(); return true end
    return false
end

-- Returns what `-` should do right now, without doing it. The decision is one function so the
-- binding, the tests and the documentation cannot disagree about it.
local function backDecision()
    if ringVisible() then return 'ring', nil end
    local open = spanMenuWindows()
    if #open > 0 or shopShown() then return 'close', open end
    return 'ring', nil
end
FFBinds_BackDecision = backDecision

local function closeMenuWindows(reason)
    local _, open = backDecision()
    if not open then return 0 end
    local closed, deferred = 0, {}
    -- the Shop is not protected-gated: ToggleStoreUI is Blizzard's public toggle, fine in combat
    if shopShown() and closeShop(reason) then closed = closed + 1 end
    for _, name in ipairs(open) do
        -- v1.4: in combat NOTHING is closed. 1.2 deferred only IsProtected() frames and let
        -- every other panel through to HideUIPanel, which is itself protected -- the frame's own
        -- protection was never the thing that mattered.
        if not protectedAllowed() then
            deferred[#deferred + 1] = name
        elseif closeWindow(name) then
            closed = closed + 1
        end
    end
    if #deferred > 0 then
        -- the standing design rule: in combat the thing waits, it never fails silently
        pendingClose = true
        noteCombat(('%d menu window(s) to close'):format(#deferred))
    end
    if closed > 0 then
        log(('back: closed %d menu window(s) in one press (%s)'):format(closed, tostring(reason)))
    end
    return closed
end
FFBinds_CloseMenuWindows = closeMenuWindows

-- The override is what makes `-` mean "close" instead of "ring". Override bindings can only be
-- changed out of combat, so the binding is re-evaluated on every show/hide FFBinds can see and again
-- at PLAYER_REGEN_ENABLED. In combat the binding that was live when the fight started stays: if a
-- menu window opens mid-fight `-` opens the ring instead of closing it -- one extra press, never
-- a dead button and never a stuck ring -- and the moment combat ends it means "close" again.
local function refreshBackBinding(reason)
    if not backButton then return end
    if inCombat() then return end
    local want = (backDecision() == 'close')
    if want == overrideOn then return end
    overrideOn = want
    if want then
        if type(_G.SetOverrideBindingClick) == 'function' then
            _G.SetOverrideBindingClick(backOwner, true, BACK_CHORD, backButton:GetName(), 'LeftButton')
        end
    elseif type(_G.ClearOverrideBindings) == 'function' then
        _G.ClearOverrideBindings(backOwner)
    end
    log(('back: `-` now %s (%s)'):format(want and 'closes menu windows' or 'opens/closes the ring',
        tostring(reason)))
end
FFBinds_RefreshBack = refreshBackBinding

local watched = {}

-- Watch what FFBinds can see. Every one of these is an ordinary insecure hook; nothing here touches
-- ConsolePort's files, its saved variables or its secure environment. Re-run on ADDON_LOADED,
-- because most of these frames are created by an addon that loads on demand.
local function offerRingRef()
    if ringRefSet or not combatDriver or inCombat() then return end
    if combatDriver.SetFrameRef and _G.ConsolePortMenuRing then
        pcall(combatDriver.SetFrameRef, combatDriver, 'ring', _G.ConsolePortMenuRing)
        ringRefSet = true
        log('combat: the driver now holds a ref to the ring')
    end
end
FFBinds_OfferRingRef = offerRingRef

local function rescanWatches()
    offerRingRef()
    local names = {'ConsolePortMenuRing'}
    local S = _G.FFSpan
    if S and type(S.MenuWindowNames) == 'function' then
        local ok, list = pcall(S.MenuWindowNames)
        if ok and type(list) == 'table' then
            for _, n in ipairs(list) do names[#names + 1] = n end
        end
    end
    for _, name in ipairs(names) do
        if not watched[name] then
            local f = _G[name]
            if f and f.HookScript then
                watched[name] = true
                f:HookScript('OnShow', function() refreshBackBinding(name .. ' shown') end)
                f:HookScript('OnHide', function() refreshBackBinding(name .. ' hidden') end)
            end
        end
    end
end
FFBinds_RescanWatches = rescanWatches

local function setupBackButton()
    if backButton then rescanWatches() return end
    if type(CreateFrame) ~= 'function' then return end
    backOwner = CreateFrame('Frame', 'FFBindsBackOwner', UIParent)
    backButton = CreateFrame('Button', 'FFBindsBack', UIParent)
    -- AnyUp so the press lands on the release, matching ConsolePortMenuTrigger's own
    -- registerForClicks (ConsolePort_Menu/View/Menu.xml:70) -- otherwise `-` would fire on the
    -- down edge here and the up edge there, and a quick tap would feel like two different buttons.
    if backButton.RegisterForClicks then pcall(backButton.RegisterForClicks, backButton, 'AnyUp') end
    backButton:SetScript('OnClick', function()
        closeMenuWindows('`-` pressed')
        refreshBackBinding('after close')
    end)
    rescanWatches()
    -- the Shop cannot be hooked; FFSpan reads its state and tells FFBinds when it opens or closes
    local S = _G.FFSpan
    if S and type(S.OnShopChanged) == 'function' then
        pcall(S.OnShopChanged, function(what) refreshBackBinding(what) end)
    end
    if type(hooksecurefunc) == 'function' then
        -- every other menu window goes through the panel manager
        pcall(hooksecurefunc, 'ShowUIPanel', function() refreshBackBinding('panel shown') end)
        pcall(hooksecurefunc, 'HideUIPanel', function() refreshBackBinding('panel hidden') end)
    end
    refreshBackBinding('setup')
end

-- ---------------------------------------- the ring: A and B both pick-and-close ----------------
-- ConsolePort builds the ring's bindings into its own secure environment: Ring.lua:230-232 sets
-- `COMMANDS[ACCEPT] = 'LeftButton'` and `COMMANDS[PLURAL] = PLURAL`, and OnTrigger binds each with
-- SetBindingClick (:93). PreClick (:116-135) then compares the clicked `button` against PLURAL and
-- returns early -- that early return is the keep-open behaviour.
--
-- So the fix is one line of ITS OWN env, not a patch: make PLURAL's binding send 'LeftButton' too.
-- PreClick then sees button == 'LeftButton', which is never equal to PLURAL ('PAD2'), and falls
-- through to ClearAndHide(false) exactly as ACCEPT does. Both face buttons pick and close, the
-- stick-centred branch still just closes the ring, and because both are still bound through the
-- ring's own SetBindingClick neither can fall through to its action bar while the ring is up.
--
-- FFBinds does not edit ConsolePort or write its SavedVariables. OnControlsChanged wipes COMMANDS
-- (Ring.lua:205-208), so this is re-applied after it, out of combat only.
local ringSeeded = false

local function seedRingAccept(reason)
    local ring = _G.ConsolePortMenuRing
    if not ring or type(ring.Run) ~= 'function' then return false end
    if inCombat() then return false end
    local ok, err = pcall(ring.Run, ring, [[ COMMANDS[PLURAL] = 'LeftButton'; ]])
    ringSeeded = ok and true or false
    log(ok and ('ring: A and B both pick-and-close (' .. tostring(reason) .. ')')
           or ('ring: FAILED to seed accept -- ' .. tostring(err)))
    return ok
end
FFBinds_SeedRing = seedRingAccept


-- ==================== v1.3: RB FROM THE RING IS THE GAME MENU, IN ONE PRESS ====================
-- 1.2 shipped with a claim of mine that was wrong. I wrote that because the ring can never be
-- open with a menu window behind it, TOGGLEGAMEMENU has nothing to close first and RB reaches the
-- game menu in one press. The first half is true. The second does not follow, because menu windows
-- are not the only thing Escape closes first.
--
-- Retail `ToggleGameMenu()` runs a PRIORITY CHAIN and shows the menu only if nothing else claims
-- the press. `RegisterGameMenuEscHandler(GameMenuEscPriority.AddOnPost, CloseAllWindows)`
-- (Blizzard_UIParentPanelManager/Shared/UIParentPanelManager.lua:1106) comes first, and
-- CloseAllWindows opens with `local bagsVisible = CloseAllBags();`. The resident bags are ALWAYS
-- visible on the home screen -- that is what "resident" means -- so the first RB closes the
-- player's bags and no menu appears. Then GameMenuEscPriority.World's ClearTarget() takes the next
-- press if anything is targeted. Only after that does GameMenuFrame_Show() run. And FFSpan
-- deliberately never re-opens bags after an Escape-path close (FFSpan_Home.lua, by design),
-- so the bags stay gone until the menu closes.
--
-- Press, bags vanish. Press, target clears. Press, menu. Bags come back later. That is exactly the
-- jank 1.2 existed to remove, and it predates 1.2 -- the ring's TRIGGERS have always been
-- TOGGLEGAMEMENU (Ring.lua:8, :236-242).
--
-- The fix is the same shape as 1.2's COMMANDS[PLURAL]: re-seed ConsolePort's OWN env so every
-- TRIGGERS entry points at a button FFBinds owns instead of the binding that runs the chain. OnTrigger
-- binds them with `selector:SetBinding(true, binding, action)` (:86-88), and a binding ACTION may
-- be "CLICK <frame>:<button>", so nothing about ConsolePort's own path changes -- only where the
-- press lands.
local GAMEMENU_BUTTON = 'FFBindsGameMenu'
local gameMenuButton, ringTriggersSeeded

local function gameMenuShown()
    local f = _G.GameMenuFrame
    return f and f.IsShown and f:IsShown() and true or false
end

-- Item 2: it has to TOGGLE. OnGameMenuShow (Ring.lua:65-70) re-binds the SAME TRIGGERS while the
-- menu is up, so a show-only action would make RB-with-the-menu-open a dead press -- the precise
-- class of bug this function exists to remove. Today TOGGLEGAMEMENU closes it through
-- GameMenuFrame_EscapePressed at Framework priority. FFBinds does it directly.
local function toggleGameMenu()
    local f = _G.GameMenuFrame
    -- v1.8.4: this button skips the Escape chain, and with it the Shop's own Escape handler
    -- (StoreEscapePressed), so an open Shop is closed here instead of a menu shown over it.
    if shopShown() then
        return closeShop('menu button') and 'shop closed' or 'shop kept'
    end
    if not protectedAllowed() then
        -- v1.4: an earlier version called _G.ToggleGameMenu() here. securecallfunction does not launder
        -- the addon's taint, so the Escape chain ran tainted: the bags closed and then ShowUIPanel refused
        -- with a blocked message. FFBinds does NOTHING instead -- in a fight the secure state driver has
        -- already given LB/RB back to the native binding, so this handler should not even be
        -- reachable, and if it is, silence beats a red error.
        noteCombat('game menu')
        return 'combat-noop'
    end
    if gameMenuShown() then
        if type(_G.HideUIPanel) == 'function' then _G.HideUIPanel(f) elseif f then f:Hide() end
        return 'closed'
    end
    -- GameMenuFrame_Show (Blizzard_GameMenu/Shared/GameMenuFrame.lua) is PlaySound +
    -- ShowUIPanel(GameMenuFrame): the menu, and nothing else. No bags closed, no target cleared.
    if type(_G.GameMenuFrame_Show) == 'function' then
        _G.GameMenuFrame_Show()
    elseif type(_G.ShowUIPanel) == 'function' and f then
        _G.ShowUIPanel(f)
    elseif f then
        f:Show()
    end
    return 'shown'
end
FFBinds_ToggleGameMenu = toggleGameMenu

local function setupGameMenuButton()
    if gameMenuButton then return end
    if type(CreateFrame) ~= 'function' then return end
    gameMenuButton = CreateFrame('Button', GAMEMENU_BUTTON, UIParent)
    if gameMenuButton.RegisterForClicks then
        pcall(gameMenuButton.RegisterForClicks, gameMenuButton, 'AnyUp')
    end
    gameMenuButton:SetScript('OnClick', function() toggleGameMenu() end)
end

-- Re-point every TRIGGERS entry that still carries the old binding. It rewrites by VALUE rather
-- than by key: the keys are built per active modifier (Ring.lua:236-242), so which ones exist
-- depends on the player's modifier set, and matching on the value is the only way to catch all of
-- them without reimplementing that loop.
local function seedRingGameMenu(reason)
    local ring = _G.ConsolePortMenuRing
    if not ring or type(ring.Run) ~= 'function' then return false end
    if inCombat() then return false end
    setupGameMenuButton()
    local action = 'CLICK ' .. GAMEMENU_BUTTON .. ':LeftButton'
    local body = "for k, v in pairs(TRIGGERS) do if v == 'TOGGLEGAMEMENU' then TRIGGERS[k] = '"
              .. action .. "' end end"
    local ok, err = pcall(ring.Run, ring, body)
    ringTriggersSeeded = ok and true or false
    log(ok and ('ring: LB/RB open the game menu directly (' .. tostring(reason) .. ')')
           or ('ring: FAILED to seed the game-menu trigger -- ' .. tostring(err)))
    return ok
end
FFBinds_SeedRingGameMenu = seedRingGameMenu

local function hookRingControls()
    local ring = _G.ConsolePortMenuRing
    if not ring or type(ring.OnControlsChanged) ~= 'function' then return end
    if type(hooksecurefunc) ~= 'function' then return end
    pcall(hooksecurefunc, ring, 'OnControlsChanged', function()
        if inCombat() then pendingClose = true return end
        seedRingAccept('controls changed')
        seedRingGameMenu('controls changed')
    end)
end

-- ---------------------------------------- the ring's Inventory entry ---------------------------
-- Buttons.lua:78-99 references MainMenuBarBackpackButton, so the entry TOGGLES the bags -- and on
-- the home screen the bags are resident furniture, so "toggle" means the player's own inventory
-- disappears off their home screen. It must only ever open them.
local function keepBagsResident(reason)
    local S = _G.FFSpan
    if not S or type(S.HomeEnabled) ~= 'function' or not S.HomeEnabled() then return false end
    if type(S.OpenResidentBags) ~= 'function' then return false end
    local ok = pcall(S.OpenResidentBags, reason)
    return ok and true or false
end
FFBinds_KeepBagsResident = keepBagsResident



-- ================== v1.4: NOT ONE PROTECTED CALL IN COMBAT, EVER ===============================
-- 1.3 made combat WORSE and I did not check the one thing that mattered. I wrote
-- `_G.ToggleGameMenu()` into an insecure OnClick as the "never dead" fallback without reading what
-- happens when an ADDON calls it in a fight. `ShowUIPanel` and `HideUIPanel`
-- (Blizzard_UIParentPanelManager/Shared/UIParentPanelManager.lua:825 / :850) both open with
-- `CheckProtectedFunctionsAllowed()` (:808-815):
--
--     if ( InCombatLockdown() and not issecure() ) then
--         DisplayInterfaceActionBlockedMessage(); return false
--     end
--
-- From an addon's tainted click the Escape chain still runs -- so the bags close -- and then the menu
-- never opens, with a red "Interface action blocked" across the screen. Before 1.3 the ring's
-- TRIGGERS were the NATIVE TOGGLEGAMEMENU binding, which is secure and simply works. I replaced a
-- working secure path with a tainted one and called it a fallback. 1.2 has the smaller version
-- of the same mistake: `closeWindow` called HideUIPanel for any panel that was not IsProtected().
--
-- The rule now: NOTHING here calls a protected panel function while InCombatLockdown(). In combat
-- the pad runs on WoW's own secure bindings, and FFBinds' insecure handlers do nothing at all.
--
-- Can the addon just swap the bindings when the fight starts? No -- not from an insecure handler.
-- `InCombatLockdown()` is already true inside PLAYER_REGEN_DISABLED, and ConsolePort itself treats
-- it that way: `ConsolePort/Controller/Input.lua:23` asserts `not InCombatLockdown()` before it
-- will even create an input widget, and it does its own combat switching through
-- `RegisterStateDriver(InputAPI, 'combat', '[combat] true; nil')` with an `_onstate-combat`
-- snippet (:18-20), not through a regen handler. A state driver is evaluated INSIDE the secure
-- environment, so it may change bindings mid-fight; FFBinds does the same thing for the same reason.
--
-- Three layers, because any one of them failing must still leave the pad clean:
--   1. a secure state driver hands PADBACK and LB/RB back to their native bindings for the fight;
--   2. a best-effort insecure swap at PLAYER_REGEN_DISABLED, in case the driver is unavailable;
--   3. and regardless of both, every insecure handler is a SILENT no-op in combat.
-- Layer 3 alone satisfies the rule. The other two are what keep the buttons useful.

-- The secure snippet. In combat it binds PADBACK to ConsolePort's ring trigger (the same secure
-- toggle `-` has out of combat when nothing is open) and LB/RB to the native TOGGLEGAMEMENU, which
-- is what the ring carried before 1.3 and what works in a fight. Out of combat it clears them
-- and FFBinds' own seeds take over again. Both calls are made from inside the restricted environment,
-- where they are allowed mid-combat -- that is the whole point of a state driver.
-- v1.5. 1.4's snippet did this:
--
--     self:SetBinding(true, 'PADRSHOULDER', 'TOGGLEGAMEMENU')
--     self:SetBinding(true, 'PADLSHOULDER', 'TOGGLEGAMEMENU')
--
-- on FFBinds' OWN frame, which makes them GLOBAL override bindings for the whole fight. In this addon's own
-- LAYOUT plain PADRSHOULDER is ACTIONBUTTON9 -- RB is an ABILITY -- and PADLSHOULDER is the Shift
-- modifier. So from the first second of every pull RB stopped casting and became Escape. I was so
-- set on not producing a red error that I took a key the player fights with and pointed it at the
-- game menu, and no check noticed because nothing asserted that the rest of the layout survives a
-- fight. One does now.
--
-- The ring never does that. It binds LB/RB only while it (or the game menu) is SHOWN, on its own
-- owner -- `selector:SetBinding(true, binding, action)` at Ring.lua:69 and :86-88 -- and drops them
-- in ClearAndHide with `self:ClearBindings()` (Ring.lua:113). The switch has to happen inside that
-- scope, which means reaching the RING's environment rather than binding anything on FFBinds' frame.
--
-- The way to reach it is the pattern ConsolePort itself uses: hand the handle across with
-- SetFrameRef out of combat, pick it up with GetFrameRef inside the snippet
-- (ConsolePort/Controller/Pager.lua:200-203, Radial.lua:563-568), and call Run on THAT handle --
-- `header:Run(snippet, newstate)` at Pager.lua:75 is the same cross-handle call in production.
-- `HANDLE:Run(body)` runs the body in the managed environment of the frame the handle belongs to,
-- with `self` being that handle; `RunFor` would keep the CALLER's environment, the wrong one.
-- (Run/RunFor: Blizzard_RestrictedAddOnEnvironment/RestrictedFrames.lua:705-722 / :725-740 --
-- checked in a code review; I have not read that part of Blizzard's source myself.)
--
-- So inside the ring's own body: rewrite its TRIGGERS, and if the ring or the game menu is showing
-- at that moment, re-apply the bindings the same way OnTrigger does (Ring.lua:86-88) so a ring
-- that was already open when the pull started is safe too. Outside it, the driver touches exactly
-- one key -- PADBACK -- and nothing else in the layout moves.
local RING_TO_NATIVE = [[
    for k, v in pairs(TRIGGERS) do
        if v ~= 'TOGGLEGAMEMENU' then TRIGGERS[k] = 'TOGGLEGAMEMENU' end
    end
    if self:IsVisible() or isMenuOpen then
        for binding, action in pairs(TRIGGERS) do
            self:SetBinding(true, binding, action)
        end
    end
]]

local RING_TO_DIRECT = [[
    for k, v in pairs(TRIGGERS) do
        if v == 'TOGGLEGAMEMENU' then TRIGGERS[k] = 'CLICK FFBindsGameMenu:LeftButton' end
    end
    if self:IsVisible() or isMenuOpen then
        for binding, action in pairs(TRIGGERS) do
            self:SetBinding(true, binding, action)
        end
    end
]]

-- PADBACK is the ONE key this driver binds, and its combat value is the same
-- `CLICK ConsolePortMenuTrigger:LeftButton` that the LAYOUT already carries, so even if FFBinds'
-- insecure override outranks it the worst case is `-` routing to FFBindsBack -- whose handler is a
-- hard no-op in combat since v1.4. Either way: no protected call, no blocked message, nothing
-- dead-but-erroring. Which of the two owners wins is the one thing here I cannot cite, so it stays
-- an open question rather than a claim.
local COMBAT_SNIPPET = ([==[
    local ring = self:GetFrameRef('ring')
    if newstate == 'combat' then
        self:SetBindingClick(true, 'PADBACK', 'ConsolePortMenuTrigger', 'LeftButton')
        if ring then ring:Run([[%s]]) end
    else
        self:ClearBindings()
        if ring then ring:Run([[%s]]) end
    end
]==]):format(RING_TO_NATIVE, RING_TO_DIRECT)

local function setupCombatDriver()
    if combatDriver then return end
    if type(CreateFrame) ~= 'function' then return end
    local ok, frame = pcall(CreateFrame, 'Frame', 'FFBindsCombat', UIParent,
                            'SecureHandlerStateTemplate')
    if not ok or not frame then return end
    combatDriver = frame
    if frame.SetAttribute then frame:SetAttribute('_onstate-combat', COMBAT_SNIPPET) end
    -- the handle has to cross out of combat; inside the snippet it is self:GetFrameRef('ring')
    -- (ConsolePort/Controller/Pager.lua:200-203 is the same wiring)
    if frame.SetFrameRef and _G.ConsolePortMenuRing then
        pcall(frame.SetFrameRef, frame, 'ring', _G.ConsolePortMenuRing)
        ringRefSet = true
    end
    if type(_G.RegisterStateDriver) == 'function' then
        pcall(_G.RegisterStateDriver, frame, 'combat', '[combat] combat; nocombat')
        log('combat: secure state driver registered -- the pad falls back to native bindings in a fight')
    end
end
FFBinds_SetupCombatDriver = setupCombatDriver

-- Layer 2. Best effort only: if lockdown is already on -- and it is, inside this event -- every one
-- of these refuses, which is exactly why layer 1 exists. It is pcall'd and its failure is normal.
local function swapToNative(reason)
    combatSwapActive = true
    local ring = _G.ConsolePortMenuRing
    if ring and type(ring.Run) == 'function' then
        pcall(ring.Run, ring,
              "for k, v in pairs(TRIGGERS) do if v ~= 'TOGGLEGAMEMENU' then TRIGGERS[k] = 'TOGGLEGAMEMENU' end end")
    end
    if overrideOn and type(_G.ClearOverrideBindings) == 'function' then
        pcall(_G.ClearOverrideBindings, backOwner)
        overrideOn = false
    end
    log('combat: swapped to native bindings for the fight (' .. tostring(reason) .. ')')
end
FFBinds_SwapToNative = swapToNative

local function swapBack(reason)
    combatSwapActive = false
    combatNoted = nil
    seedRingGameMenu(reason)
    refreshBackBinding(reason)
end
FFBinds_SwapBack = swapBack

-- ---------------------------------------- /ffbinds back ---------------------------------------
-- A diagnostic. The two things a mock genuinely cannot
-- prove are whether `ConsolePortMenuRing:Run` reached a live secure environment and whether FFBinds'
-- override binding actually won against the ring's own. Both are invisible on the device unless
-- something prints them, and "it still feels janky" is not a diagnosis. This is.
local function backReport()
    local out = {}
    local decision, open = backDecision()
    out[#out + 1] = '|cff69ccf0FFBinds|r `-` would: |cffffd100' .. decision .. '|r'
    if open and #open > 0 then
        out[#out + 1] = '   closing: ' .. table.concat(open, ', ')
    end
    out[#out + 1] = '   override on PADBACK: ' .. (overrideOn and '|cff40ff40yes|r' or 'no')
        .. '   (binding: ' .. tostring(GetBindingAction and GetBindingAction('PADBACK') or '?') .. ')'
    out[#out + 1] = '   ring seed -- A and B both accept: '
        .. (ringSeeded and '|cff40ff40in effect|r' or '|cffff4040NOT in effect|r')
    out[#out + 1] = '   ring seed -- LB/RB open the game menu: '
        .. (ringTriggersSeeded and '|cff40ff40in effect|r' or '|cffff4040NOT in effect|r')
    out[#out + 1] = '   ring visible: ' .. tostring(ringVisible())
        .. '   game menu shown: ' .. tostring(gameMenuShown())
        .. '   combat: ' .. tostring(inCombat())
    out[#out + 1] = '   combat swap: ' .. (combatSwapActive and '|cffffd100ACTIVE (native bindings)|r'
        or 'off') .. '   secure driver: ' .. (combatDriver and 'registered' or '|cffff4040missing|r')
        .. '   ring ref: ' .. (ringRefSet and '|cff40ff40held|r' or '|cffff4040MISSING|r')
    local lines = FFBindsDB and FFBindsDB.log and FFBindsDB.log.results
    local last = type(lines) == 'table' and lines[#lines]
    out[#out + 1] = '   last log: ' .. (last and tostring(last) or '(none)')
    for _, line in ipairs(out) do print(line) end
    return out
end
FFBinds_BackReport = backReport

SLASH_FFBINDS1 = '/ffbinds'
SlashCmdList = SlashCmdList or {}
SlashCmdList.FFBINDS = function(msg)
    msg = tostring(msg or ''):lower():gsub('^%s+', ''):gsub('%s+$', '')
    if msg == 'back' or msg == '' then
        backReport()
    elseif msg == 'crossbar' and FFBinds_Crossbar then
        FFBinds_Crossbar.Ensure('slash', true)
    else
        print('|cff69ccf0FFBinds|r: /ffbinds back -- what `-` and the ring would do right now')
        if FFBinds_Crossbar then
            print('|cff69ccf0FFBinds|r: /ffbinds crossbar -- put ConsolePort\'s Crossbar: Triple bar back on this character')
        end
    end
end

local f = CreateFrame('Frame')
f:RegisterEvent('ADDON_LOADED')
f:RegisterEvent('PLAYER_ENTERING_WORLD')
f:RegisterEvent('UPDATE_BINDINGS')
f:RegisterEvent('PLAYER_REGEN_ENABLED')
f:RegisterEvent('PLAYER_REGEN_DISABLED')
f:RegisterEvent('PLAYER_LOGOUT')
f:SetScript('OnEvent', function(_, event, arg1, arg2)
    if event == 'ADDON_LOADED' then
        if arg1 == ADDON then initDB() end
        pcall(rescanWatches)   -- a late addon just created one of the menu windows
    elseif not FFBindsDB or not FFBindsDB.log then
        return
    elseif event == 'PLAYER_ENTERING_WORLD' then
        if arg1 or arg2 or not appliedAt then -- initial login or /reload, not every loading screen
            pcall(applyModifiers, 'login')     -- first: see applyModifiers for why the order matters
            applyLayout()
            if FFBinds_Crossbar and FFBinds_Crossbar.Ensure then pcall(FFBinds_Crossbar.Ensure, 'login') end
            pcall(syncCvars)
            pcall(consolePortKeyboard)
            pcall(setupCombatDriver)
            pcall(setupBackButton)
            pcall(hookRingControls)
            pcall(seedRingAccept, 'login')
            pcall(seedRingGameMenu, 'login')
        end
    elseif event == 'UPDATE_BINDINGS' then
        if applying then return end
        if not appliedAt or GetTime() - appliedAt < SETTLE then applyLayout() else captureEdits() end
    elseif event == 'PLAYER_REGEN_DISABLED' then
        pcall(swapToNative, 'combat started')
    elseif event == 'PLAYER_REGEN_ENABLED' then
        if pendingCombat then
            pendingCombat = false
            pcall(applyModifiers, 'combat ended')
            applyLayout()
            if FFBinds_Crossbar and FFBinds_Crossbar.Ensure then pcall(FFBinds_Crossbar.Ensure, 'combat ended') end
        end
        -- whatever could not be done in combat happens now: the binding, the queued closes and
        -- the ring seed. Nothing is left in a state the player would have to press twice.
        pcall(swapBack, 'combat ended')
        if pendingClose then
            pendingClose = false
            pcall(seedRingAccept, 'combat ended')
            pcall(seedRingGameMenu, 'combat ended')
        end
    elseif event == 'PLAYER_LOGOUT' then
        pcall(captureCvars)
        pcall(captureModifiers)
    end
end)
