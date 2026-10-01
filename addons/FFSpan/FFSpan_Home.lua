--[[
    FFSpan_Home.lua -- the bottom screen as a home screen on the 4400x1080 span canvas.

    Owns: the home on/off state machine, the snapshot/restore
    transaction for everything it changes, ConsolePort cursor exclusions, resident bags, window
    placement, and the combat rules. It does NOT own Edit Mode layouts -- FFScale is the single
    owner of those and is driven from here through S.RegisterHomeListener.

    Coordinates: physical pixels, canvas TOP-LEFT origin, y growing DOWNWARD. That is the same
    convention as FFSpan_Dump's rows and as the layout contract's `y = minimapBottom + 12 .. bottomBarTop - 8`,
    and it is the convention FFScale.HomeSlots() is read in.
    Pixels <-> frame units: a frame f with effective scale e sits in a space of q = e * physH/768
    pixels per unit, so a SetPoint offset against UIParent's BOTTOMLEFT is (px/q, (physH-py)/q).
    Each frame converts with ITS OWN effective scale; there is no universal conversion.

    Everything here is idempotent, pcall-wrapped, combat-gated for protected frames, and logs into
    FFSpanDB.home[<realm-character>]. Complete no-op at 1920 and 3160 apart from cleaning up a home
    session that a previous 4400 launch left behind -- that cleanup deliberately does NOT sit behind
    HomeEligible.
--]]

local S = _G.FFSpan
if not S then return end
local H = CreateFrame('Frame', 'FFSpanHomeEvents')
S.Home = H
local unpack = unpack or table.unpack

local MARGIN        = 16    -- px between a placed window and the edge of its region
local BAG_GAP_TOP   = 12    -- px below the minimap before the resident bags start
local BAG_GAP_BOT   = 8     -- px above the bottom bar
local MIN_BAG_SCALE = 0.60  -- below this the slots stop being a usable touch target
local BAG_COLUMN_MAX = 0.55 -- the resident bags may claim at most this share of the home width
local BAG_SCALE_MIN = 0.70  -- how far the bags narrow to widen a companion
local MAX_LOG       = 60
local MAX_NOTES     = 30   -- the durable ring for rare/diagnostic categories
local RETRY_DELAYS  = {0, 1, 2, 4, 8, 16, 30, 60} -- bounded ConsolePort/late-frame retry ladder

-- ================================================================================ helpers ======
-- NOTE: six return values, because GetPoint returns five and GetRect four -- a narrower capture
-- silently drops a frame's anchor offset and makes "exact restore" quietly inexact.
local function safe(fn, ...)
    if type(fn) ~= 'function' then return nil end
    local ok, a, b, c, d, e, f = pcall(fn, ...)
    if ok then return a, b, c, d, e, f end
end
local function call(f, key, ...)
    if not f then return nil end
    local fn = safe(function() return f[key] end)
    if type(fn) ~= 'function' then return nil end
    return safe(fn, f, ...)
end
local function combat()
    return InCombatLockdown and safe(InCombatLockdown) and true or false
end
local function physical()
    local w, h = S.GetPhysicalSize()
    return w or 0, h or 0
end
local function clamp(v, lo, hi)
    if v < lo then return lo end
    if v > hi then return hi end
    return v
end

-- `place` lines are routine and they flood. The talents event needed as
-- evidence had already been pushed out of the 60-entry ring by logout, leaving only place lines,
-- and the "not usable" line went the same way inside a single test. So the RARE
-- categories -- the ones that are only ever written when something is wrong or unusual -- also go
-- into a second, smaller ring that routine traffic cannot reach. Bounded: 30 entries, same shape.
local ROUTINE = {place = true}

local function log(event, detail)
    local rec = S.HomeRecord(true)
    if not rec then return end
    local entry = {t = safe(date, '%Y-%m-%d %H:%M:%S'), e = event, d = detail}
    if type(rec.log) ~= 'table' then rec.log = {} end
    rec.log[#rec.log + 1] = entry
    while #rec.log > MAX_LOG do table.remove(rec.log, 1) end
    if not ROUTINE[event] then
        if type(rec.notes) ~= 'table' then rec.notes = {} end
        -- Repeats COLLAPSE. `bags` residency lines are diagnostic but they also recur on every
        -- loading screen, and a run of identical ones would evict the rare line this ring is
        -- actually kept for -- which is how the first version of it lost the "not usable" line inside a
        -- single test. Counting a repeat instead of appending it keeps distinct evidence.
        local last
        for i = #rec.notes, 1, -1 do
            local n = rec.notes[i]
            if n.e == event and n.d == detail then last = n; break end
        end
        if last then
            last.n = (last.n or 1) + 1
            last.t = entry.t
        else
            rec.notes[#rec.notes + 1] = entry
            while #rec.notes > MAX_NOTES do table.remove(rec.notes, 1) end
        end
    end
end

local function Print(msg)
    local frame = DEFAULT_CHAT_FRAME
    if frame then safe(function() frame:AddMessage('|cff00e5ff[FFSpan]|r ' .. tostring(msg)) end) end
end

-- ================================================================================= state =======
local applied     = false  -- home mutations are installed right now
local generation  = 0      -- bumped on every enable/disable; queued callbacks compare against it
local placing     = false  -- recursion guard around FFSpan's own placement pass
local anchoring   = false  -- recursion guard around FFSpan's own bag anchoring
local hooksDone   = false
local deferred    = {}     -- [frameName] = true, waiting for PLAYER_REGEN_ENABLED
local shownSeq, shownAt = 0, {} -- ordering for "the older companion gives way"
local pendingRestore       -- frames a combat-time `home off` could not put back yet
local cpStep      = 0
local cpScheduled = false
local layoutConfirmed = false -- FFScale has a VERIFIED live home layout and a published column
local layoutRegistered = false
local layoutSource            -- where the confirmed column's edges came from
local layoutDegraded  = false -- the column is estimated, not measured (degraded mode)
local degradedLogged  = false
local residencyOpened = false -- this session's FIRST confirmation has opened the resident bags
local residencyBlocked = false -- combat stopped the login-time residency; retry once at regen
local confirmStep = 0         -- bounded retry ladder for an unconfirmed layout
local confirmWarned = false   -- the "not confirmed" chat line is printed once per session
local lastLayoutDetail        -- the layout owner's reason for refusing, for that chat line
local panelHook   = 'not installed'
local placedNames = {}     -- [frameName] = true, FFSpan has placed it this session
local scaleRefused = {}    -- [frameName] = the scale it kept, when a readback still disagrees
local scaleOwners  = {}    -- [frameName] = who most likely pinned it (diagnostic)
local positionOwners = {}  -- [frameName] = another addon that owns its POSITION (Leatrix Maps)
local glassyFits           -- did Glassy's envelope land inside the chat slot
local closingResident      -- set while FFSpan closes the bags on purpose, so the keep-resident
                           -- hook does not fight FFSpan's own teardown
local scaleHook   = 'not installed'
local bagScaleTarget   = 1 -- the bag scale the companion lane negotiated
local bagsNaturalWidth = 0 -- the resident bags' width at scale 1, measured by anchorBags
local anchorBags           -- forward: placeAll settles the bag width before measuring the lane
local baganatorPresent, baganatorBank, baganatorBackpack  -- forward: the bridge is defined later
local baganatorUsable                   -- forward: PRESENT is not USABLE -- see the gate below
local origToggleAllBags = _G.ToggleAllBags   -- captured at FFSpan's file load, before Baganator's init
local totalBagSlots, minBagWidthUnits   -- forward: used by the companion negotiation
local layoutOwner, applyLayoutVia       -- forward: the capacity watcher asks the owner to re-apply

-- Baganator grid constants and state. These live UP HERE, not in the bridge below, because the
-- companion negotiation and the column maths both read them and both run earlier in the file.
local BAG_PADDING   = 4     -- Baganator's icon padding at default spacing
local BAG_ICON_MAX  = 37    -- Baganator's native icon. An earlier build capped at 44, which
                            -- upscales a 37 px texture, so the cap is 37.
local BAG_ICON_BASE = 37    -- Blizzard's slot size; icon/37 is the "equivalent scale" FFSpan reports
local BAG_ICON_MIN  = 26    -- the 0.7-equivalent floor, used when the bags are alone
local BAG_ICON_FLOOR = 8    -- the absolute limit the balanced companion search may reach

local bagChromeW, bagChromeH = 26, 60   -- measured off the live frame after the first layout
local bagChromeMeasured = false
local bagHeaderMinW = 300           -- UI units: keep the native toolbar/search usable. Raised to
                                    -- Baganator's own minimum width once measured (v2.6)
local bagLayoutPending = false
local bagSizeHooked = {}
local bagGrid                            -- the last grid FFSpan asked Baganator for

-- Baganator's bank view is a companion too, but its global name carries a frame-group
-- suffix that is only known at run time -- so it is resolved per pass instead of listed
-- statically in MANAGED, and these two have to exist before classOf() reads them.
local BAGANATOR_BANK_CLASS = {class = 'COMPANION', group = 'bank'}
local baganatorBankName    -- the live bank view's global name, when it is showing
local bagWidthCap          -- px: how wide the bag column may be while a companion is open
local lastColumnRequest    -- px: the column width last requested from the layout owner
local capacityPending      -- a capacity re-apply is debounced or waiting for combat to end
local deferredCapacity     -- ...specifically waiting for PLAYER_REGEN_ENABLED

-- v2.2.1: ONE readiness predicate. Every path that moves, anchors or opens anything
-- goes through it -- the OnShow hook, the panel post-hook, the bag-anchor hook, the regen pass and
-- residency, not just the two callers that happened to check before. `applied` alone is not
-- enough: it only means the session is open, not that the home geometry on screen is the one
-- things are about to be fitted into.
local function ready()
    return applied and layoutConfirmed
end

local function session(create)
    local rec = S.HomeRecord(create)
    if not rec then return nil end
    if type(rec.session) ~= 'table' then
        if not create then return nil end
        local w, h = physical()
        rec.session = {startedAt = safe(date, '%Y-%m-%d %H:%M:%S'),
                       geometry = string.format('%dx%d', w, h)}
    end
    return rec.session
end

-- ============================================== shared (ACCOUNT-WIDE) restore transaction ======
-- v2.2: CVars and ConsolePort's registry are GLOBAL, not per-character -- ConsolePort
-- saves its registry as the account-wide `ConsolePortUIStack`, and SetCVar is a client setting.
-- Keeping their originals in FFSpanDB.home[<realm-character>] meant a stock login on a DIFFERENT
-- character inherited the changes and saw no session to clean up. They live in
-- FFSpanDB.homeShared instead (FFSpanDB is account-wide, FFSpan.toc:6), as a JOURNAL: each
-- component is cleared only once its restore has been confirmed, and whatever is left is retried
-- on the next login, ADDON_LOADED or PLAYER_REGEN_ENABLED, from any character.
local function sharedRecord(create)
    if type(FFSpanDB) ~= 'table' then
        if not create then return nil end
        FFSpanDB = {}
    end
    local rec = FFSpanDB.homeShared
    if type(rec) ~= 'table' then
        if not create then return nil end
        rec = {}
        FFSpanDB.homeShared = rec
    end
    return rec
end

local WANT_CVARS = {mapFade = '0', combinedBags = '1'}

-- Never overwrite an original that is already journalled: an interrupted session's snapshot is
-- the only copy of the player's real values, so a second activation must reuse it.
local function snapshotCVars(shared)
    if type(shared.cvars) ~= 'table' then shared.cvars = {} end
    for name in pairs(WANT_CVARS) do
        if shared.cvars[name] == nil then
            local v = safe(GetCVar, name)
            shared.cvars[name] = (v ~= nil) and tostring(v) or false -- false = was unreadable
        end
    end
end
local function applyCVars()
    for name, want in pairs(WANT_CVARS) do safe(SetCVar, name, want) end
end
-- Returns true only when every journalled CVar reads back as its original.
local function restoreCVars(shared)
    local ok = true
    for name, prior in pairs(shared.cvars or {}) do
        if prior and prior ~= false then
            safe(SetCVar, name, prior)
            local now = safe(GetCVar, name)
            -- v2.2.1: a readback that cannot be performed is UNCONFIRMED, not success --
            -- `nil` used to count as "fine" and let the journal row be deleted unverified.
            -- (A CVar that was unreadable at SNAPSHOT time is stored as `false` and skipped above.)
            if now == nil or tostring(now) ~= tostring(prior) then ok = false end
        end
    end
    return ok
end

-- ====================================================================== ConsolePort cursor =====
-- ConsolePort:RemoveInterfaceCursorFrame(name) resolves _G[name] FIRST and does nothing when the
-- frame does not exist yet (API.lua:157-164), which is why late frames need the retry ladder.
-- Exact restore needs the tri-state (unset / false / true) per owner, and the DEFAULT owner key is
-- private to ConsolePort -- so FFSpan snapshots the whole per-frame registry row before and diffs it back
-- afterwards through Stack:SetFrame, which is what ConsolePort's own `/cp frame reset` does.
local cpNames
local function cpFrameNames()
    if cpNames then return cpNames end
    local t = {'ContainerFrameCombinedBags', 'WorldMapFrame'}
    local n = tonumber(_G.NUM_CONTAINER_FRAMES) or 13
    n = clamp(math.floor(n), 1, 20)
    for i = 1, n do t[#t + 1] = 'ContainerFrame' .. i end
    cpNames = t
    return t
end
local function cpStack()
    local cp = _G.ConsolePort
    if not cp then return nil end
    local db = call(cp, 'GetData')
    if type(db) ~= 'table' then return nil end
    local stack = safe(function() return db.Stack end)
    if type(stack) ~= 'table' then return nil end
    return stack
end
-- v2.2: ConsolePort_Cursor owns the Stack. API.lua:157-164 returns true after merely
-- SCHEDULING the exclusion through EventUtil.ContinueOnAddOnLoaded when the cursor addon is not
-- loaded yet -- and that queued callback cannot be cancelled, so it can land after teardown. FFSpan
-- therefore never ASKS until the Stack is actually reachable; until then the retry ladder waits.
-- v2.2.1: readiness is the USABLE STACK, nothing weaker. "ConsolePort_Cursor is
-- loaded" was accepted before, but every snapshot and every exact restore goes through the Stack
-- -- without it there is no way to record the prior owner set or put it back, so asking is pointless
-- and acknowledging would be a lie.
local function cpReady()
    return cpStack() ~= nil
end

-- v2.2: the RUNTIME tracking state, as far as this build can read it.
-- Stack:GetVisibleCursorFrames() is the only public read and it reports VISIBLE tracked frames,
-- so it can only say "false" about a frame that is currently shown. nil means "not knowable".
local function cpTracked(fname)
    local stack = cpStack()
    if not stack then return nil end
    if type(safe(function() return stack.GetVisibleCursorFrames end)) ~= 'function' then return nil end
    local list = safe(function() return {stack:GetVisibleCursorFrames()} end)
    if type(list) ~= 'table' then return nil end
    local obj = _G[fname]
    if not obj then return nil end
    for _, w in ipairs(list) do if w == obj then return true end end
    if call(obj, 'IsVisible') then return false end
    return nil
end

-- {owners = {[owner] = true|false}, read = 'live'|'saved'|'none'}
local function cpSnapshot(fname)
    local stack = cpStack()
    local reg, src = stack and safe(function() return stack.Registry end), 'live'
    if type(reg) ~= 'table' then reg, src = _G.ConsolePortUIStack, 'saved' end
    if type(reg) ~= 'table' then return {owners = {}, read = 'none'} end
    local owners = {}
    safe(function()
        for owner, set in pairs(reg) do
            if type(set) == 'table' and set[fname] ~= nil then
                owners[owner] = set[fname] and true or false
            end
        end
    end)
    return {owners = owners, read = src}
end
-- returns true when the exclusion registered; otherwise nil + a reason
local function cpRemove(fname)
    local cp = _G.ConsolePort
    if not cp or type(safe(function() return cp.RemoveInterfaceCursorFrame end)) ~= 'function' then
        return nil, 'noapi'
    end
    if not _G[fname] then return nil, 'noframe' end
    local ret = call(cp, 'RemoveInterfaceCursorFrame', fname)
    if ret then return true end
    return nil, 'rejected'
end
-- v2.2: `st` = {before = {[owner] = true|false}, tracked = bool|nil}.
-- Stack:SetFrame(frame, state, owner) writes Registry[owner][name] AND drives the runtime
-- tracking off THAT call's `state` alone -- trackWidget/untrackWidget, last call wins, whatever
-- the other owners hold (Stack.lua:141-158). A diff-based restore that skips an owner whose value
-- did not change therefore leaves a previously tracked frame UNTRACKED while the registry reads
-- correct; a code review reproduced exactly that. So: replay the FULL prior owner set, finish on
-- the effective prior state, then VERIFY both the registry and the runtime tracking.
-- Returns true only when the restore is confirmed -- the caller's journal retries otherwise.
local function cpRestoreOne(fname, st)
    st = (type(st) == 'table') and st or {}
    local before = st.before or {}
    local stack, obj = cpStack(), _G[fname]
    if not (stack and obj and type(safe(function() return stack.SetFrame end)) == 'function') then
        -- v2.2.1: ALWAYS unconfirmed. This branch used to call the public
        -- AddInterfaceCursorFrame and report its return as success, and restoreShared then deleted
        -- the journal row -- but a request the API accepted is not a restore: the prior owner set
        -- was never replayed and nothing was verified. Stay journalled until the Stack is back.
        return false
    end
    local function set(state, owner) return safe(function() stack:SetFrame(obj, state, owner) end) end
    local after = cpSnapshot(fname).owners
    -- 1. drop every owner that was NOT there before (FFSpan's, or a late queued exclusion)
    for owner in pairs(after) do
        if before[owner] == nil then set(nil, owner) end
    end
    -- 2. replay the whole prior set, the `true` owners LAST so tracking ends on the prior state
    local trues = {}
    for owner, state in pairs(before) do
        if state == true then trues[#trues + 1] = owner else set(false, owner) end
    end
    for _, owner in ipairs(trues) do set(true, owner) end
    -- 3. the registry has to actually match again, in both directions
    local now = cpSnapshot(fname).owners
    for owner, state in pairs(before) do if now[owner] ~= state then return false end end
    for owner in pairs(now) do if before[owner] == nil then return false end end
    -- 4. ...and so does the runtime tracking, where this build can read it
    local want = st.tracked
    if want ~= nil then
        local isTracked = cpTracked(fname)
        if isTracked ~= nil and isTracked ~= want then
            local fixedBy
            for owner, state in pairs(before) do
                if state == want then fixedBy = owner; break end
            end
            if not fixedBy then return false end   -- cannot correct without changing the registry
            set(want, fixedBy)
            local check = cpTracked(fname)
            if check ~= nil and check ~= want then return false end
        end
    end
    return true
end

local function cpPass()
    cpScheduled = false
    if not applied then return end
    local shared = sharedRecord(true)
    if not shared then return end
    if type(shared.consolePort) ~= 'table' then shared.consolePort = {} end
    local remaining, noapi = false, false
    -- v2.2: do not ask before the Stack exists, or ConsolePort silently QUEUES the
    -- exclusion through ContinueOnAddOnLoaded and it can fire after FFSpan has already torn down.
    if not cpReady() then
        remaining = true
        noapi = _G.ConsolePort == nil
    else
        for _, fname in ipairs(cpFrameNames()) do
            local st = shared.consolePort[fname]
            if not (type(st) == 'table' and st.done) then
                local before = cpSnapshot(fname)
                local tracked = cpTracked(fname)
                local ok, why = cpRemove(fname)
                if ok then
                    shared.consolePort[fname] = {done = true, before = before.owners,
                                                 read = before.read, tracked = tracked}
                else
                    remaining = true
                    if why == 'noapi' then noapi = true end
                end
            end
        end
    end
    if not remaining then
        log('consolePort', 'all exclusions registered')
        return
    end
    cpStep = cpStep + 1
    if cpStep >= #RETRY_DELAYS then
        log('consolePort', noapi and 'ConsolePort API not present; gave up'
                                 or 'some frames never appeared; gave up')
        return
    end
    if not cpScheduled and C_Timer then
        cpScheduled = true
        local gen = generation
        safe(C_Timer.After, RETRY_DELAYS[cpStep + 1], function()
            cpScheduled = false
            if gen == generation then cpPass() end
        end)
    end
end
local function cpKick()
    if not applied or cpScheduled then return end
    cpPass()
end

-- v2.2 migration: v2.1 kept these originals in the PER-CHARACTER session. On an upgrade that
-- happens mid-session they are the only copy of the player's real values, so move them into the
-- shared journal rather than starting a fresh (and by then wrong) snapshot.
local function adoptLegacySession(sess)
    if type(sess) ~= 'table' then return end
    if type(sess.cvars) ~= 'table' and type(sess.consolePort) ~= 'table' then return end
    local shared = sharedRecord(true)
    if not shared then return end
    if type(sess.cvars) == 'table' and type(shared.cvars) ~= 'table' then
        shared.cvars = sess.cvars
        sess.cvars = nil
    end
    if type(sess.consolePort) == 'table' and type(shared.consolePort) ~= 'table' then
        -- v2.1 rows are {done, before, read}; `tracked` was never recorded, so it stays nil and
        -- cpRestoreOne simply skips the runtime-tracking verification for them.
        shared.consolePort = sess.consolePort
        sess.consolePort = nil
    end
end

-- v2.2: work the ACCOUNT-WIDE journal. Each component is cleared only once its
-- restore is CONFIRMED; anything left keeps the journal alive for the next retry, from any
-- character, at any geometry. Returns true when the shared transaction is fully closed.
local function restoreShared()
    local shared = sharedRecord(false)
    if not shared then return true end
    local done = true
    if type(shared.cvars) == 'table' then
        if restoreCVars(shared) then shared.cvars = nil else done = false end
    end
    if type(shared.consolePort) == 'table' then
        local left = false
        for fname, st in pairs(shared.consolePort) do
            if type(st) ~= 'table' or not st.done then
                shared.consolePort[fname] = nil
            elseif cpRestoreOne(fname, st) then
                shared.consolePort[fname] = nil
            else
                left = true
            end
        end
        if left then done = false else shared.consolePort = nil end
    end
    if done then
        if type(FFSpanDB) == 'table' then FFSpanDB.homeShared = nil end
        return true
    end
    shared.pending = true
    return false
end

-- v2.6: Glassy's chat WIDTH. placeGlassy narrows it to the chat slot through Glassy's own setting
-- (FFSpan_Glassy.lua), which journals the player's original inside GlassyDB -- Glassy.lua is shared
-- across flavors and FFSpan.lua is not, so the record travels with the value it describes. It goes
-- back whenever home is not live (home off, geometry left home, a stock login) and, as data only,
-- at every logout, so a narrowed width is never the one that gets saved.
-- NOTE: this file's main chunk sits at Lua's 200-local limit -- new helpers go in a table.
local chatWidth = {}
function chatWidth.restore(reason, dispatch)
    local fit = S.GlassyFit
    if type(fit) ~= 'table' or type(fit.Restore) ~= 'function' then return true end
    local ok, changed = safe(fit.Restore, dispatch ~= false)
    if changed then log('glassy', 'chat width restored (' .. tostring(reason) .. ')') end
    chatWidth.alwaysOn = nil
    return ok and true or false
end

-- ================================================================ measuring / conversions =====
-- physical rect of a frame, canvas top-left origin
local function rectPx(f)
    if not f then return nil end
    local l, b, w, h = call(f, 'GetRect')
    if not l or not b or not w or not h or w <= 0 or h <= 0 then return nil end
    local e = call(f, 'GetEffectiveScale') or 1
    if e <= 0 then return nil end
    local _, ph = physical()
    local q = e * ph / 768
    return {x = l * q, y = ph - (b + h) * q, w = w * q, h = h * q, scale = e, q = q}
end

-- union of the frame and its shown children/regions, so hanging tabs and portraits are included
local function envelopePx(f)
    local root = rectPx(f)
    if not root then return nil end
    local x1, y1, x2, y2 = root.x, root.y, root.x + root.w, root.y + root.h
    local budget = 60
    local function eat(child)
        if budget <= 0 or not child then return end
        budget = budget - 1
        if call(child, 'IsForbidden') then return end
        if not call(child, 'IsVisible') then return end
        local r = rectPx(child)
        if not r or r.w <= 0 or r.h <= 0 then return end
        -- ignore absurd children (full-screen overlays) so one stray child cannot blow the envelope
        local pw, ph = physical()
        if r.w >= pw * 0.9 or r.h >= ph * 0.98 then return end
        if r.x < x1 then x1 = r.x end
        if r.y < y1 then y1 = r.y end
        if r.x + r.w > x2 then x2 = r.x + r.w end
        if r.y + r.h > y2 then y2 = r.y + r.h end
    end
    local kids = safe(function() return {f:GetChildren()} end)
    for _, c in ipairs(kids or {}) do eat(c) end
    local regions = safe(function() return {f:GetRegions()} end)
    for _, c in ipairs(regions or {}) do eat(c) end
    return {x = x1, y = y1, w = x2 - x1, h = y2 - y1, root = root}
end

-- ==================================================================== home column geometry =====
-- FFScale publishes the minimap's bottom and the bottom bar's top; without it FFSpan measures the same
-- two things itself. Both are physical px from the canvas top.
local MINIMAP_CANDIDATES = {'MinimapCluster', 'Minimap'}
local BOTTOMBAR_CANDIDATES = {'MicroMenuContainer', 'MicroButtonAndBagsBar', 'BagsBar',
                              'MicroMenu', 'MainMenuBar', 'StatusTrackingBarManager'}

local function measureHomeSlots()
    local home = S.HomeRect()
    if not home then return nil end
    local _, ph = physical()
    local top, bottom
    local width, chat
    local fs = _G.FFScale
    if fs then
        local slots = call(fs, 'HomeSlots')
        if type(slots) == 'table' then
            top = tonumber(safe(function() return slots.minimapBottom end))
            bottom = tonumber(safe(function() return slots.bottomBarTop end))
            width = tonumber(safe(function() return slots.width end))
            -- the chat slot travels with the rest, for Glassy
            local c = safe(function() return slots.chat end)
            if type(c) == 'table' then chat = c end
        end
    end
    if not top then
        for _, name in ipairs(MINIMAP_CANDIDATES) do
            local r = _G[name] and call(_G[name], 'IsVisible') and rectPx(_G[name])
            -- only trust it when it actually sits in the home region
            if r and r.x < home.w then top = math.max(top or 0, r.y + r.h) end
        end
    end
    if not bottom then
        for _, name in ipairs(BOTTOMBAR_CANDIDATES) do
            local r = _G[name] and call(_G[name], 'IsVisible') and rectPx(_G[name])
            if r and r.x < home.w then bottom = math.min(bottom or ph, r.y) end
        end
    end
    -- Clamp the TOP first, leaving room for the column: clamping only the bottom could push it
    -- past the canvas and hand bagColumn() a negative height (see the scale guard in anchorBags).
    top = clamp(tonumber(top) or home.h * 0.30, 0, math.max(0, home.h - 60))
    bottom = clamp(tonumber(bottom) or home.h * 0.88, top + 60, home.h)
    return {minimapBottom = top, bottomBarTop = bottom, width = width, chat = chat}
end

-- the resident-bag column: right-hand side of the home region, under the minimap
local function bagColumn()
    local home = S.HomeRect()
    local slots = measureHomeSlots()
    if not home or not slots then return nil end
    -- with a BAG ADDON the layout owner sizes the column, because it is the one
    -- that decided how much of the home screen the tracker and chat get. Blizzard's own bags keep
    -- the original 55% cap exactly, so nothing about that path moves.
    local publishedW = baganatorUsable() and tonumber(safe(function() return slots.width end)) or nil
    local top = slots.minimapBottom + BAG_GAP_TOP
    local bottom = slots.bottomBarTop - BAG_GAP_BOT
    if bottom - top < 80 then bottom = math.min(home.h - MARGIN, top + 80) end
    -- Cap the column so unusually wide bags can never swallow the companion lane; the height
    -- between the minimap and the bottom bar is the constraint that normally binds anyway.
    local w = publishedW and math.min(publishedW, home.w - MARGIN * 2)
              or math.min(home.w - MARGIN * 2, home.w * BAG_COLUMN_MAX)
    -- with a companion open the column itself narrows, and Baganator reflows into
    -- FEWER COLUMNS rather than shrinking (decided 2026-09-23). The Blizzard path still uses
    -- bagScaleTarget; this cap is what the two have in common.
    if bagWidthCap and bagWidthCap > 0 then w = math.min(w, bagWidthCap) end
    return {x = home.w - MARGIN - w, y = top, w = w, h = bottom - top,
            right = home.w - MARGIN, bottom = bottom}
end

-- Companions share the full-height lane, so they must clear BOTH right-hand residents.
local function minimapLeft()
    local home, left = S.HomeRect()
    if not home then return nil end
    for _, name in ipairs(MINIMAP_CANDIDATES) do
        local f = _G[name]
        local r = f and call(f, 'IsVisible') and envelopePx(f)
        if r and r.x >= MARGIN and r.x < home.w and r.x + r.w <= home.w + 1 then
            left = math.min(left or home.w, r.x)
        end
    end
    return left
end

-- the companion lane, left of whatever the bags actually occupy
local bagsOccupiedWidth = 0
local function companionLane()
    local home = S.HomeRect()
    if not home then return nil end
    local bagsW = bagsOccupiedWidth
    if bagsW <= 0 then
        local col = bagColumn()
        bagsW = col and col.w or 380
    end
    local right = home.w - MARGIN - bagsW - MARGIN
    local mapLeft = minimapLeft()
    if mapLeft then right = math.min(right, mapLeft - MARGIN) end
    local w = math.max(1, right - MARGIN)
    return {x = MARGIN, y = MARGIN, w = w, h = home.h - MARGIN * 2, right = right}
end

local function homeArea()
    local home = S.HomeRect()
    if not home then return nil end
    return {x = MARGIN, y = MARGIN, w = home.w - MARGIN * 2, h = home.h - MARGIN * 2}
end
local function gameArea()
    local game = S.GameRect()
    if not game then return nil end
    return {x = game.x + MARGIN, y = MARGIN, w = game.w - MARGIN * 2, h = game.h - MARGIN * 2}
end

-- ========================================================================== window placement ===
-- v2.3: THE size-class table: one data row per window, so the
-- policy can be changed here without touching any placement code.
--
--   TOP       -- the game rect, centred. Urgent / full-attention things the player looks up at.
--   PAGE      -- the WHOLE home screen, one page at a time, over the home HUD.
--   COMPANION -- the lane beside the resident bags; the bags narrow to make room.
--
-- Dual-screen convention: top = game + urgent popups, bottom = ONE page
-- at a time at full size, or a split beside inventory.
local CLASS = {
    TOP       = {area = 'game', max = 1.25},
    PAGE      = {area = 'home', max = 1.50},
    COMPANION = {area = 'lane', max = 1.25},
}
-- group: windows in the same group never evict each other (mail's inbox + open letter).
local MANAGED = {
    -- ---- TOP ---------------------------------------------------------------------------------
    GameMenuFrame        = {class = 'TOP'},   -- ConsolePortMenu follows it (Menu.lua:80-106)
    SettingsPanel        = {class = 'TOP'},
    StoreFrame           = {class = 'TOP'},
    -- ---- PAGE --------------------------------------------------------------------------------
    PlayerSpellsFrame    = {class = 'PAGE', page = true, spells = true}, -- talents -> TOP
    CollectionsJournal   = {class = 'PAGE', page = true},
    AchievementFrame     = {class = 'PAGE', page = true},
    ProfessionsBookFrame = {class = 'PAGE', page = true},
    ProfessionsFrame     = {class = 'PAGE', page = true},
    WorldMapFrame        = {class = 'PAGE', page = true, align = 'top', map = true}, -- maximized -> TOP
    EncounterJournal     = {class = 'PAGE', page = true},
    PVEFrame             = {class = 'PAGE', page = true},
    CommunitiesFrame     = {class = 'PAGE', page = true},
    CalendarFrame        = {class = 'PAGE', page = true},
    FriendsFrame         = {class = 'PAGE', page = true},
    WardrobeFrame        = {class = 'PAGE', page = true},
    -- LoD Blizzard_HousingDashboard; RegisterUIPanel(HousingDashboardFrame,
    -- { area = 'left', pushable = 0, extraWidthFunc = ... }) -- a full home page
    HousingDashboardFrame = {class = 'PAGE', page = true},
    -- ---- COMPANION ---------------------------------------------------------------------------
    CharacterFrame       = {class = 'COMPANION', group = 'char'},
    MerchantFrame        = {class = 'COMPANION', group = 'merchant'},
    MailFrame            = {class = 'COMPANION', group = 'mail'},
    OpenMailFrame        = {class = 'COMPANION', group = 'mail'},
    BankFrame            = {class = 'COMPANION', group = 'bank'},
    AccountBankPanel     = {class = 'COMPANION', group = 'bank'},
    GuildBankFrame       = {class = 'COMPANION', group = 'guildbank'},
    TradeFrame           = {class = 'COMPANION', group = 'trade'},
    AuctionHouseFrame    = {class = 'COMPANION', group = 'auction'},
    ItemSocketingFrame   = {class = 'COMPANION', group = 'socket'},
    ItemUpgradeFrame     = {class = 'COMPANION', group = 'upgrade'},
    -- with Baganator loaded its bank view is the companion, and the resident bags
    -- stay beside it. The name carries a frame-group suffix, so it is resolved at run time by
    -- S.BaganatorBank() and injected into the visible set rather than listed statically here.

}

-- PlayerSpellsFrame:GetTab() against PlayerSpellsUtil.FrameTabs (Blizzard_PlayerSpellsFrame.lua);
-- falls back to whichever child frame is shown. Unknown -> treat as spellbook, which keeps the
-- window on the home screen where it is guaranteed to be visible.
local function spellsMode()
    local f = _G.PlayerSpellsFrame
    if not f then return 'centre' end
    local tabs = _G.PlayerSpellsUtil and safe(function() return _G.PlayerSpellsUtil.FrameTabs end)
    -- Blizzard_PlayerSpellsFrame.lua:164-169 exposes IsFrameTabActive(frameTab), which
    -- resolves the LOGICAL tab through frameTabsToTabID. Prefer it over comparing raw tab ids.
    local isActive = safe(function() return f.IsFrameTabActive end)
    if type(isActive) == 'function' and type(tabs) == 'table' then
        if safe(isActive, f, safe(function() return tabs.SpellBook end)) then return 'centre' end
        if safe(isActive, f, safe(function() return tabs.ClassTalents end))
            or safe(isActive, f, safe(function() return tabs.ClassSpecializations end)) then
            return 'top'
        end
    end
    local tab = call(f, 'GetTab')
    if type(tabs) == 'table' and tab ~= nil then
        if tab == safe(function() return tabs.SpellBook end) then return 'centre' end
        if tab == safe(function() return tabs.ClassTalents end)
            or tab == safe(function() return tabs.ClassSpecializations end) then return 'top' end
    end
    local talents = safe(function() return f.TalentsFrame end)
    if talents and call(talents, 'IsShown') then return 'top' end
    return 'centre'
end

-- The class a window is in RIGHT NOW. Only PlayerSpellsFrame moves between classes: the talents
-- tab is a TOP takeover, the spellbook is a home PAGE.
-- ============================================ MENU WINDOWS =====================================
-- The `-` button's one-step-back contract needs to know what counts as "a menu window". FFSpan
-- owns the window classes, so it owns this too and FFBinds reads it -- one list, not two copies
-- that drift.
--
-- A MENU window is something the ring or the micro menu opened: the player chose it from a menu,
-- so `-` takes it away again. Every TOP and PAGE class window qualifies, plus the few frames that
-- are not in the size table because FFSpan does not place them.
--
-- What is deliberately NOT a menu window:
--   * the resident bags (Blizzard or Baganator) -- they are home furniture, always up. Escape
--     still closes them natively; `-` must never make the home screen empty.
--   * the home HUD.
--   * NPC-interaction companions -- merchant, bank, guild bank, mail, trade, auction house,
--     crafting orders. You did not open them from a menu, you walked up to someone, and they
--     close when you walk away. Keeping them out is what makes `-` at a vendor OPEN THE RING, so
--     Character can be added beside the vendor instead of the vendor vanishing.
-- CharacterFrame is the exception that proves the rule: it is a COMPANION for layout (it shares
-- the lane beside the bags) but you opened it from a menu, so `-` closes it.
local MENU_EXTRA = {
    GameMenuFrame        = true,   -- rule 1b: this is the dead-button fix
    SettingsPanel        = true,
    PlayerSpellsFrame    = true,
    CharacterFrame       = true,
    ConsolePortConfig    = true,   -- ConsolePort's own config window
}
local function isMenuWindow(name)
    if type(name) ~= 'string' then return false end
    if name == baganatorBankName then return false end          -- Baganator's bank view is a bank
    local spec = MANAGED[name]
    if spec then
        -- A COMPANION is a menu window only if MENU_EXTRA names it. That one rule covers every
        -- NPC window -- merchant, bank, guild bank, mail, trade, auction house, crafting orders --
        -- without listing them: none of them is in MENU_EXTRA, because you did not pick any of
        -- them from a menu. CharacterFrame is, because you did.
        if spec.class == 'COMPANION' then return MENU_EXTRA[name] == true end
        if spec.class == 'TOP' or spec.class == 'PAGE' then return true end
        return false
    end
    return MENU_EXTRA[name] == true
end
S.IsMenuWindow = isMenuWindow

-- The menu windows that are VISIBLE right now, in the order `-` should close them (all at once,
-- but the order decides which one's close is reported first).
local function menuWindowsOpen()
    local out = {}
    for name in pairs(MANAGED) do
        if isMenuWindow(name) then
            local f = _G[name]
            if f and call(f, 'IsVisible') then out[#out + 1] = name end
        end
    end
    for name in pairs(MENU_EXTRA) do
        if not MANAGED[name] then
            local f = _G[name]
            if f and call(f, 'IsVisible') then out[#out + 1] = name end
        end
    end
    table.sort(out)
    return out
end
S.MenuWindowsOpen = menuWindowsOpen

-- Every name that COULD be a menu window, visible or not, so FFBinds can hook their show/hide
-- rather than guessing which ones go through the panel manager.
function S.MenuWindowNames()
    local out = {}
    for name in pairs(MANAGED) do if isMenuWindow(name) then out[#out + 1] = name end end
    for name in pairs(MENU_EXTRA) do if not MANAGED[name] then out[#out + 1] = name end end
    table.sort(out)
    return out
end

-- v2.6: the world map's MAXIMIZE button. Blizzard maximizes to a fixed 1024x768 map at FULLSCREEN
-- strata over a BlackoutFrame whose two anchors are UIParent's corners (Blizzard_WorldMap
-- Cata/Blizzard_WorldMap.lua SynchronizeDisplayState :3-67 and Cata/Blizzard_WorldMap.xml :40-57,
-- the files Blizzard_WorldMap_Mists.toc loads). UIParent is the whole 4400 canvas, so on the device
-- the maximized map sat on the top screen with BOTH screens blacked out, bags and minimap included
-- (Classic 02:18-02:20). Maximize now means what it says on a dual screen: the big map on the big
-- screen -- a TOP window, like talents -- while the ordinary map stays a home page. The blackout
-- is pinned to the world view, so the home screen stays visible and touchable underneath.
-- (One table, not five locals: this file's main chunk is at Lua's 200-local limit.)
local mapMax = {}
function mapMax.maximized()
    local map = _G.WorldMapFrame
    local fn = map and safe(function() return map.IsMaximized end)
    if type(fn) ~= 'function' then return false end
    return safe(fn, map) and true or false
end

local function classOf(name)
    local spec = MANAGED[name]
    if not spec and name ~= nil and name == baganatorBankName then spec = BAGANATOR_BANK_CLASS end
    if not spec then return nil end
    if spec.spells then return (spellsMode() == 'top') and 'TOP' or 'PAGE' end
    if spec.map then return mapMax.maximized() and 'TOP' or 'PAGE' end
    return spec.class
end

-- mapMax.points: the BlackoutFrame's own anchors, kept the first time FFSpan moves it so home-off puts
-- them back exactly. Blizzard only ever Show()s and Hide()s it (never re-anchors), so one pin holds.
function mapMax.blackout()
    local map = _G.WorldMapFrame
    local bf = map and safe(function() return map.BlackoutFrame end)
    return type(bf) == 'table' and bf or nil
end
function mapMax.confine()
    local bf, world = mapMax.blackout(), _G.WorldFrame
    if not bf or not world or combat() then return end
    if mapMax.points == nil then
        local pts = {}
        for i = 1, math.min(call(bf, 'GetNumPoints') or 0, 8) do
            local p, rel, rp, x, y = call(bf, 'GetPoint', i)
            if p then pts[#pts + 1] = {p, rel, rp, x or 0, y or 0} end
        end
        mapMax.points = pts
    end
    -- WorldFrame IS the game rect (the centre-game core put it at x 1240..3160), so this is
    -- exactly the top screen at whatever scale the map is drawn
    safe(function()
        bf:ClearAllPoints()
        bf:SetAllPoints(world)
    end)
end
function mapMax.release()
    local bf, pts = mapMax.blackout(), mapMax.points
    if not bf or type(pts) ~= 'table' then return true end
    if combat() then return false end
    local ok = safe(function()
        bf:ClearAllPoints()
        for _, p in ipairs(pts) do bf:SetPoint(p[1], p[2], p[3], p[4], p[5]) end
        return true
    end)
    if ok then mapMax.points = nil end
    return ok and true or false
end
-- v2.6.4 (Classic A/B on the device, 09-25 08:29-08:41): the pass changes the map's SCALE from
-- inside Blizzard's own display-state chain -- the UpdateUIPanelPositions post-hook fires within
-- MoveUIPanel (UIParentPanelManager.lua:467-486), and the envelope, so the fit, moves whenever the
-- quest panel shows or hides. The engine then leaves the map's rects unresolved, and the very next
-- Blizzard line (Cata/Blizzard_WorldMap.lua :66 -> MapCanvas_ScrollContainerMixin.lua
-- CreateZoomLevels :427-429) reads ScrollContainer:GetWidth() == 0: zoom scale 0, "Scale must be
-- > 0", blank parchment, a quest panel stuck open. Exact 2.6.2 failed on the first maximized
-- open; home off was clean; 2.6.3, whose read-only probe happened to query these rects right
-- before :66, was clean. So resolve them ourselves: after every map placement, and after
-- MaximizeUIPanel / RestoreUIPanelArea, the last calls before :66 in either branch.
function mapMax.resolve()
    local map = _G.WorldMapFrame
    if not map then return end
    local sc = safe(function() return map.ScrollContainer end)
    local child = sc and safe(function() return sc.Child end)
    for _, f in ipairs({map, sc or false, child or false}) do
        if f then call(f, 'GetRect'); call(f, 'GetSize') end
    end
end
S.MapMax = mapMax
local function isPage(name)
    local spec = MANAGED[name]
    return spec ~= nil and spec.page == true and classOf(name) == 'PAGE'
end
-- kept for the dump's intended-screen policy: TOP -> the game rect, everything else -> home
local function modeOf(name)
    local class = classOf(name)
    if not class then return nil end
    return (class == 'TOP') and 'top' or 'centre'
end

-- v2.2: ONE managed-window policy table. The dump derives its intended screen from
-- the SAME source placement uses -- including the live spellbook/talents mode -- instead of a
-- second, hand-maintained list that drifts out of step with this one.
function S.ManagedIntent()
    local out = {}
    for name in pairs(MANAGED) do
        out[name] = (modeOf(name) == 'top') and 'top' or 'home'
    end
    return out
end

local function mutable(f)
    if not f then return false end
    if call(f, 'IsForbidden') then return false end
    if combat() and call(f, 'IsProtected') then return false end
    return true
end

-- v2.2: the anchor a frame was really on can be an ANONYMOUS region, which has no
-- name to serialise. Substituting UIParent for it silently moves the frame on restore, so the
-- real objects are kept here, in-session only, and used whenever the restore happens in the same
-- session. Across a reload the serialised name (or UIParent) is all that is left, by definition.
local anchorRefs = {}

-- snapshot a frame's anchors + scale exactly once per home session, by name so it survives a reload
local function snapshotFrame(name, f)
    local sess = session(true)
    if not sess then return end
    if type(sess.frames) ~= 'table' then sess.frames = {} end
    if sess.frames[name] then return end
    local pts, refs = {}, {}
    local n = call(f, 'GetNumPoints') or 0
    local anonymous = false
    for i = 1, math.min(n, 8) do
        local p, rel, rp, x, y = call(f, 'GetPoint', i)
        local relName = rel and call(rel, 'GetName')
        if rel and not relName then anonymous = true end
        pts[#pts + 1] = {p, relName or 'UIParent', rp, x or 0, y or 0}
        refs[i] = rel
    end
    anchorRefs[name] = refs
    sess.frames[name] = {points = pts, scale = call(f, 'GetScale') or 1, anonymous = anonymous or nil}
end
local function baseScaleOf(name, f)
    local sess = session(false)
    local saved = sess and sess.frames and sess.frames[name]
    return (saved and tonumber(saved.scale)) or call(f, 'GetScale') or 1
end
-- Returns the frames it could NOT restore (protected while in combat). `/ffspan home off` during a
-- fight must not silently leave a window where FFSpan put it -- the caller retries at regen.
-- v2.2: a frame that is not there YET, or whose restore THREW, is a restore that has
-- not happened -- it has to stay in `left` so the journal retries it, not vanish because the
-- pcall swallowed it.
local function restoreFrames(sess)
    local left
    local function keep(name, saved)
        left = left or {frames = {}}
        left.frames[name] = saved
    end
    for name, saved in pairs((sess and sess.frames) or {}) do
        local f = _G[name]
        if type(saved) ~= 'table' then
            -- nothing usable to put back; drop it
        elseif not f then
            keep(name, saved)          -- frame not loaded yet: retry at the next readiness event
        elseif not mutable(f) then
            keep(name, saved)          -- protected while in combat: retry at regen
        else
            local refs = anchorRefs[name]
            local ok = safe(function()
                if saved.scale then f:SetScale(saved.scale) end
                f:ClearAllPoints()
                for i, p in ipairs(saved.points or {}) do
                    local rel = (refs and refs[i]) or _G[p[2]] or UIParent
                    f:SetPoint(p[1], rel, p[3], p[4], p[5])
                end
                return true
            end)
            if ok then anchorRefs[name] = nil else keep(name, saved) end
        end
    end
    return left
end

-- v2.2: finish whatever the journal still owes -- shared (account-wide) first, then
-- this character's frames. Safe at any geometry, on any character, any number of times.
local function reconcileRestore()
    -- A LIVE session OWNS the journal -- its entries are the originals it still has to put back
    -- LATER, not work outstanding now. Replaying them here would hand the player's own values
    -- back while home is still on, and then clear the only copy of them.
    if applied then return false end
    chatWidth.restore('journal')
    mapMax.release()   -- a combat-time home off could not put it back; this is the retry
    local sharedDone = restoreShared()
    local rec = S.HomeRecord(false)
    local sess = rec and rec.session
    local framesDone = true
    if type(sess) == 'table' and sess.restoring then
        local leftOver = restoreFrames(sess)
        pendingRestore = leftOver
        if leftOver then framesDone = false else rec.session = nil end
    end
    return sharedDone and framesDone
end

-- place one frame so its VISIBLE ENVELOPE sits inside `area`; align = 'centre' | 'left'
-- v2.3: `maxScale` is the class cap. The target scale is ABSOLUTE -- fit is measured on the
-- envelope normalised to scale 1, so repeated passes can never compound -- and the frame may be
-- ENLARGED up to the cap, as big as it can be within reason.
--
-- Root cause: `SetScale` does NOT take on Blizzard's PROTECTED panels. On the device
-- PlayerSpellsFrame (IsProtected true) kept scale 1 after SetScale(0.531) -- proven by the anchor
-- it was given: x 11.377779 * q means q was computed at scale 1, i.e. GetEffectiveScale() still
-- read 1 on the very next line. The old code trusted the call, so it anchored a 2277x1284 frame
-- at the position computed for a 1208x681 one and left it SPLIT across both screens. Every
-- unprotected frame in the same dumps (CharacterFrame 0.755, WorldMapFrame 0.830) scaled fine.
-- So: set the scale, READ IT BACK, and redo the geometry with whatever the frame actually has.
-- DIAGNOSTIC ONLY. When a frame refuses FFSpan's scale, say who most likely
-- pinned it, so nobody has to re-derive the answer from dumps.
--
-- The talents/spellbook frame is the live case. TalentTreeTweaks v1.14.0 module ScaleTalentFrame
-- SecureHooks PlayerSpellsFrame's OWN SetScale and puts its saved scale straight back
-- (`modules/scaleTalentFrame.lua:81-83`, "Reset the scale if someone else tries to set it.", and
-- the same OnShow at :86); `SharedUtil.lua:262-268` names PlayerSpellsFrame as the container.
-- That also defeats Blizzard's own checkFit. TTT stands the module down by itself when BlizzMove
-- is enabled (:16, :46), which is why BlizzMove is part of the test below.
--
-- FFSpan does NOT fight it, spoof BlizzMoveAPI or write TalentTreeTweaks' settings -- whether that
-- module goes off is the player's call. FFSpan only reads its SV to name it.
-- The map. Leatrix Maps 12.1.06 ships with UnlockMap and ScaleWorldMap OFF (:2112,
-- :2115), and with them off it neither moves nor scales WorldMapFrame -- its SetPoint block
-- (:638-686) and SetScale block (:119-150) only run when the option is On. So by default FFSpan places
-- the map and Leatrix does not mind. If the player ever turns either one ON there would be two
-- owners fighting over the same frame every time it is shown, which is precisely the jank this
-- code exists to remove. Leatrix wins: the player turned it on deliberately, and it is their map
-- addon. FFSpan stands down for the session, names the owner in the log and the dump, and places nothing.
local function leatrixMapOwner()
    local db = _G.LeaMapsDB
    if type(db) ~= 'table' then return nil end
    for _, key in ipairs({'UnlockMap', 'ScaleWorldMap'}) do
        local v = safe(function() return db[key] end)
        if v == 'On' or v == true or v == 1 then return 'LeatrixMaps:' .. key end
    end
    return nil
end
S.LeatrixMapOwner = leatrixMapOwner

local function scaleOwnerOf(name)
    if name == 'WorldMapFrame' then
        local who = leatrixMapOwner()
        if who then return who end
    end
    if name == 'PlayerSpellsFrame' then
        local loaded = (_G.C_AddOns and _G.C_AddOns.IsAddOnLoaded) or _G.IsAddOnLoaded
        local hasTTT = type(loaded) == 'function' and safe(loaded, 'TalentTreeTweaks') and true
        if hasTTT then
            local db = _G.TalentTreeTweaksDB
            local mod = type(db) == 'table' and safe(function() return db.modules end)
            local off = type(mod) == 'table' and mod.ScaleTalentFrame == false
            local blizzMove = type(loaded) == 'function' and safe(loaded, 'BlizzMove') and true
            if not off and not blizzMove then return 'TalentTreeTweaks:ScaleTalentFrame' end
        end
    end
    return 'unknown'
end

local function placeIn(name, f, area, align, maxScale)
    if not area or not mutable(f) then return false, 'blocked' end
    local env = envelopePx(f)
    if not env or env.w <= 0 or env.h <= 0 then return false, 'nomeasure' end
    if area.w <= 0 or area.h <= 0 then return false, 'noarea' end
    snapshotFrame(name, f)
    local cur = call(f, 'GetScale') or 1
    if cur <= 0 then return false, 'noscale' end
    maxScale = maxScale or 1
    -- envelope size at scale 1, so repeated passes never compound a previous fit
    local envW1, envH1 = env.w / cur, env.h / cur
    local fit = math.min(area.w / envW1, area.h / envH1)
    local want = math.min(maxScale, fit)
    if want <= 0 then return false, 'noscale' end
    local _, ph = physical()

    local got = want
    local okScale = safe(function()
        f:SetScale(want)
        return call(f, 'GetScale') or want
    end)
    if type(okScale) == 'number' and okScale > 0 then got = okScale end
    -- v2.4: a readback that disagrees is a DIAGNOSTIC, not a
    -- verdict. Blizzard's checkFit pass resets the scale a moment later and the
    -- UIPanelUpdateScaleForFit hook below puts FFSpan's back, so "it refused" is almost always just
    -- "it was read too early". Only a frame that still disagrees after that re-apply is genuinely
    -- stuck; it is recorded and still placed, never abandoned.
    if math.abs(got - want) > 0.001 then
        if scaleRefused[name] == nil then
            log('scale', ('%s kept %.3f after SetScale(%.3f) -- owner: %s')
                :format(name, got, want, scaleOwnerOf(name)))
        end
        scaleRefused[name] = got
        scaleOwners[name] = scaleOwnerOf(name)
    else
        scaleRefused[name] = nil
        scaleOwners[name] = nil
    end

    local final = got
    local envW, envH = envW1 * final, envH1 * final
    -- offset of the root inside the envelope, at the final scale
    local dx = (env.root.x - env.x) / cur * final
    local dy = (env.root.y - env.y) / cur * final
    local ex = (align == 'left') and area.x or (area.x + (area.w - envW) / 2)
    -- The map should move up and stretch down. A TOP-aligned page starts at
    -- the top of its area and grows downward, so the extra height a hidden quest panel frees up
    -- becomes map instead of becoming equal margins above and below it.
    local ey = (align == 'top') and area.y or (area.y + (area.h - envH) / 2)
    ex = clamp(ex, area.x, math.max(area.x, area.x + area.w - envW))
    ey = clamp(ey, area.y, math.max(area.y, area.y + area.h - envH))
    local rootX, rootY = ex + dx, ey + dy
    local ok = safe(function()
        local e = call(f, 'GetEffectiveScale') or final
        local q = e * ph / 768
        if not q or q <= 0 then error('scale') end
        f:ClearAllPoints()
        f:SetPoint('TOPLEFT', UIParent, 'BOTTOMLEFT', rootX / q, (ph - rootY) / q)
        return true
    end)
    if not ok then return false, 'seterror' end
    return true, {x = ex, y = ey, w = envW, h = envH, scale = final, wanted = want}
end

local function visibleManaged()
    local out = {}
    for name in pairs(MANAGED) do
        local f = _G[name]
        if f and call(f, 'IsVisible') then out[#out + 1] = name end
    end
    -- Baganator's bank view is a companion too; its global name is only known at run time.
    baganatorBankName = nil
    if baganatorUsable() then
        local bank = baganatorBank()
        local bankName = bank and call(bank, 'GetName')
        if bank and bankName and call(bank, 'IsVisible') then
            baganatorBankName = bankName
            out[#out + 1] = bankName
        end
    end
    table.sort(out, function(a, b) return (shownAt[a] or 0) < (shownAt[b] or 0) end)
    return out
end

-- If every visible companion fits side by side in the lane at its native size,
-- they all stay and each gets its OWN slot (never stacked on the same anchor, which would be the
-- janky case). Otherwise, OUT OF COMBAT, the newest wins and the older one is closed the native
-- way.
--
-- IN COMBAT the order reverses (decided 2026-09-23). An addon may not hide a
-- UI panel in combat (UIParentPanelManager.lua:807-811), so there is no way to make room: the
-- OLDER window KEEPS the lane slot it already occupies and the NEWER one is simply NOT PLACED by
-- FFSpan -- it stays wherever WoW's own panel manager put it, and is recorded as deferred. That
-- is one rule for movable and protected losers alike, and it is why this pass walks oldest-first
-- in combat: whoever is already in the lane keeps it. At PLAYER_REGEN_ENABLED the ordinary
-- out-of-combat decision runs again and the newer window replaces the older one for real.
-- (v2.2.1 replaces v2.2's off-panel parking, which I removed.)
local laneSlots = {}
local function layoutLane(names)
    laneSlots = {}
    local lane = companionLane()
    if not lane or #names == 0 then return end
    local inCombat = combat()
    local seq = {}
    if inCombat then
        for i = 1, #names do seq[#seq + 1] = i end        -- oldest first: it keeps its slot
    else
        for i = #names, 1, -1 do seq[#seq + 1] = i end    -- newest first: the newcomer wins
    end
    local keep, groups, order = {}, {}, {}
    local total = 0
    for _, i in ipairs(seq) do
        local name = names[i]
        local key = (MANAGED[name] or (name == baganatorBankName and BAGANATOR_BANK_CLASS) or {}).group or name
        if groups[key] then
            keep[#keep + 1] = name -- same group (mail inbox + open letter): shares one slot
        else
            local f = _G[name]
            local env = envelopePx(f)
            local cur = call(f, 'GetScale') or 1
            -- The fit rule is unchanged by v2.3: whether both companions FIT is judged at
            -- NATIVE size. Growing them to the class cap happens afterwards, inside the slot each
            -- one is given -- otherwise two windows that used to sit side by side would start
            -- evicting each other just because they are now allowed to be bigger.
            local w = (env and cur > 0 and env.w > 0) and (env.w / cur) or lane.w
            w = math.min(w, lane.w)
            local need = (total == 0) and w or (total + MARGIN + w)
            if need <= lane.w then
                groups[key] = {w = w, age = i}
                order[#order + 1] = key
                total = need
                keep[#keep + 1] = name
            elseif not inCombat and type(HideUIPanel) == 'function' then
                safe(HideUIPanel, _G[name])
                log('evict', name)
            else
                -- the newer window waits: no slot, so placeOne leaves it exactly where it is
                log('lane', name .. ' deferred: no room beside the window already in the lane')
            end
        end
    end
    -- oldest companion leftmost in BOTH orders, so an existing window never shuffles sideways
    table.sort(order, function(a, b) return groups[a].age < groups[b].age end)
    -- v2.3: hand out the WHOLE lane, not just each window's native width -- a single companion
    -- then gets the full lane and can grow to its class cap, as big as it can be, and two
    -- companions each get their native width plus a proportional share of what
    -- is left over. Nothing overlaps either way.
    local natural = 0
    for _, key in ipairs(order) do natural = natural + groups[key].w end
    local spare = lane.w - natural - MARGIN * math.max(0, #order - 1)
    if spare > 0 and natural > 0 then
        for _, key in ipairs(order) do
            groups[key].w = groups[key].w + spare * (groups[key].w / natural)
        end
    end
    local x = lane.x
    for _, key in ipairs(order) do
        groups[key].x = x
        x = x + groups[key].w + MARGIN
    end
    for _, name in ipairs(keep) do
        local slot = groups[(MANAGED[name] or (name == baganatorBankName and BAGANATOR_BANK_CLASS) or {}).group or name]
        if slot and slot.x then
            laneSlots[name] = {x = slot.x, y = lane.y, w = slot.w, h = lane.h}
        end
    end
end

local function placeOne(name)
    local f = _G[name]
    if not f or not call(f, 'IsVisible') then return end
    -- Leatrix Maps wins the map when the player has turned its own position or scale
    -- option on. Two owners re-placing one frame on every show is the jank, not the fix.
    if name == 'WorldMapFrame' then
        local who = leatrixMapOwner()
        if who then
            if scaleOwners[name] ~= who then
                log('scale', 'WorldMapFrame: standing down, ' .. who .. ' owns it this session')
            end
            scaleOwners[name] = who
            positionOwners[name] = who
            return
        end
        mapMax.confine()
    end
    local class = classOf(name)
    if not class then return end
    local spec = CLASS[class]
    local area
    if class == 'TOP' then
        area = gameArea()
    elseif class == 'PAGE' then
        area = homeArea()
    else
        area = laneSlots[name]
        if not area then
            -- v2.2.1: no slot means the lane is already occupied by a window FFSpan
            -- may not hide. FFSpan places NOTHING here -- falling back to the whole lane, as it
            -- used to, is what put the winner on top of the kept window. Leave it where WoW put
            -- it and re-decide at PLAYER_REGEN_ENABLED.
            deferred[name] = true
            return false
        end
    end
    -- the alignment is a property of the WINDOW (the map wants the top), not of its size class
    local align = (MANAGED[name] or {}).align
        or ((class == 'COMPANION') and 'left' or 'centre')
    local ok, why = placeIn(name, f, area, align, spec.max)
    if name == 'WorldMapFrame' then mapMax.resolve() end
    if not ok then
        if why == 'blocked' then deferred[name] = true end
        return false
    end
    placedNames[name] = true
    deferred[name] = nil
    return true
end

-- v2.3: the bags give room back to a companion. The bag column shrinks (floor
-- BAG_SCALE_MIN) only while a companion is open, and only by as much as the companion can
-- actually use -- so the bags stay as big as they can while the companion gets its best scale.
local function negotiateBagScale(companions)
    if #companions == 0 then bagWidthCap = nil; return 1 end
    local home = S.HomeRect()
    local natural = bagsNaturalWidth
    if not home or natural <= 0 then return 1 end
    local laneH = home.h - MARGIN * 2
    -- what the visible companions would need to ALL sit at their class cap; one group per slot
    local needW, seen, groups = 0, {}, 0
    for _, name in ipairs(companions) do
        local key = (MANAGED[name] or (name == baganatorBankName and BAGANATOR_BANK_CLASS) or {}).group or name
        if not seen[key] then
            seen[key] = true
            local f = _G[name]
            local env = envelopePx(f)
            local cur = call(f, 'GetScale') or 1
            if env and cur > 0 and env.h > 0 then
                local w1, h1 = env.w / cur, env.h / cur
                local cap = math.min(CLASS.COMPANION.max, laneH / h1)
                groups = groups + 1
                needW = needW + w1 * cap
            end
        end
    end
    needW = needW + MARGIN * math.max(0, groups - 1)
    if needW <= 0 then return 1 end
    -- home.w = MARGIN + lane + MARGIN + bags + MARGIN  (left gutter, gap, right gutter)
    local allowedBags = home.w - MARGIN * 3 - needW
    if baganatorUsable() then
        -- v2.5.1: a BALANCED split. An earlier build gave the bags their
        -- minimum first and left the companion 0.47 at 202 slots; the first build gave the companion its
        -- full 1.25 and left the bags a box no grid fits in. Neither is what the screen wants.
        -- Instead, pick the split that makes the WORSE of the two sides as good as it can be:
        -- maximise min(bag icon / 37, companion scale). The search walks the icon size down --
        -- each icon implies the narrowest bag column that still shows every slot, which implies
        -- the lane, which implies the companion's scale -- so it is 28 bounded steps, no solving.
        local col = bagColumn()
        local _, ph2 = physical()
        local q2 = ph2 / 768
        local slots = totalBagSlots() or 0
        if not (col and q2 > 0 and slots > 0) then bagWidthCap = nil; return 1 end
        local boxHUnits = col.h / q2
        local compW1, compH1 = needW / math.max(1, groups), 0
        -- the widest single companion decides the lane; re-measure it at scale 1
        compW1 = 0
        for _, name in ipairs(companions) do
            local f = _G[name]
            local env = envelopePx(f)
            local cur = call(f, 'GetScale') or 1
            if env and cur > 0 and env.w / cur > compW1 then
                compW1, compH1 = env.w / cur, env.h / cur
            end
        end
        if compW1 <= 0 then bagWidthCap = nil; return 1 end
        local bestW, bestScore, bestIcon, bestComp
        local mapLeft = minimapLeft()
        for icon = BAG_ICON_MAX, BAG_ICON_FLOOR, -1 do
            local pitch = icon + BAG_PADDING
            local maxRows = math.floor((boxHUnits - bagChromeH) / pitch)
            if maxRows >= 1 then
                -- v2.6.5: Baganator's minimum is a floor on its WINDOW, not a width the grid must
                -- reach -- see solveBagGrid. The column this offers is the window it will draw.
                local cols = math.ceil(slots / maxRows)
                local wPx = math.max(cols * pitch - BAG_PADDING + bagChromeW, bagHeaderMinW) * q2
                local laneW = home.w - MARGIN * 3 - wPx
                if mapLeft then laneW = math.min(laneW, mapLeft - MARGIN * 2) end
                if laneW > 0 then
                    local comp = math.min(CLASS.COMPANION.max, laneW / compW1,
                                          (compH1 > 0) and (laneH / compH1) or CLASS.COMPANION.max)
                    local score = math.min(icon / BAG_ICON_MAX, comp)
                    if not bestScore or score > bestScore then
                        bestScore, bestW, bestIcon, bestComp = score, wPx, icon, comp
                    end
                end
            end
        end
        if not bestW then bagWidthCap = nil; return 1 end
        bagWidthCap = bestW
        log('bags', ('balanced split: icon %d (%.2f) vs companion %.2f -- worse side %.2f')
            :format(bestIcon, bestIcon / BAG_ICON_MAX, bestComp, bestScore))
        return 1
    end
    return clamp(allowedBags / natural, BAG_SCALE_MIN, 1)
end

-- v2.3: ONE page at a time on the home screen. Out of combat the newest PAGE
-- wins and the older one closes the native way; in combat nothing may be hidden, so the OLDER one
-- keeps the screen and the newer one waits -- the same rule as the companion lane.
-- Returns the set of names this pass must NOT place.
local function arbitratePages(visible)
    local skip = {}
    local pages = {}
    for _, n in ipairs(visible) do
        if isPage(n) then pages[#pages + 1] = n end   -- visibleManaged() is oldest-first
    end
    if #pages < 2 then return skip end
    local inCombat = combat()
    local keep = inCombat and pages[1] or pages[#pages]
    for _, n in ipairs(pages) do
        if n ~= keep then
            if not inCombat and type(HideUIPanel) == 'function' then
                safe(HideUIPanel, _G[n])
                log('page', n .. ' closed: one page at a time')
            else
                skip[n] = true
                deferred[n] = true
                log('page', n .. ' deferred: a page is already open and combat forbids closing it')
            end
        end
    end
    return skip
end

-- Opening any managed window closes the game menu first. Out of combat only --
-- in combat an addon may not hide a UI panel, so it is left alone.
local function closeGameMenuFor(visible)
    local menu = _G.GameMenuFrame
    if not (menu and call(menu, 'IsVisible')) then return end
    if combat() or type(HideUIPanel) ~= 'function' then return end
    for _, n in ipairs(visible) do
        if n ~= 'GameMenuFrame' then
            safe(HideUIPanel, menu)
            log('menu', 'game menu closed: ' .. n .. ' opened')
            return
        end
    end
end

-- ============================================== GLASSY CHAT ====================================
-- An earlier build added `chatSkinPadPx = 100` on the assumption that Glassy's frame follows ChatFrame1
-- and just needed room under it. It does not follow it at all. `GlassyFrame` is anchored
-- TOPLEFT -> GlassyMoverFrame TOPLEFT (Modules/UIManager.lua:256-258), so it goes wherever the
-- MOVER is and Edit Mode's chat slot means nothing to it. On the device that left it at y691 with
-- a visible envelope 473 px tall -- bottom edge at 1164 on a 1080 screen, cut off, `split` in
-- every dump.
--
-- Glassy's supported way to move it is the mover's own mixin, `SetDragPosition(left, bottom)`
-- (Components/MoverFrame.lua:40), which is exactly what its drag handler calls (:92). It takes UI
-- units, re-anchors the mover to the nearest corner of its parent, and persists NOTHING -- there
-- is no profile write anywhere in that path, and the account SV has no saved position. So calling
-- it is a pure runtime placement through Glassy's own API: nothing patched, nothing vendored,
-- and Glassy still owns its own frame.
--
-- Two things the mover already does: its height already includes the edit box
-- (`UpdateLayoutBounds`, :146 `SetHeight(frameHeight + attachedExtent)`), so positioning the mover
-- positions the WHOLE visible envelope; and `AddBoundsRegion(container)` (:258) keeps its bounds
-- in step. FFSpan still verifies against the measured envelope rather than trusting either.
local GLASSY_SNAP = 20   -- Components/MoverFrame.lua:20, EDGE_SNAP_DISTANCE, in UI units

local function glassyMover()
    local m = _G.GlassyMoverFrame
    if type(m) ~= 'table' then return nil end
    if type(safe(function() return m.SetDragPosition end)) ~= 'function' then return nil end
    return m
end

local function glassyPresent() return glassyMover() ~= nil and _G.GlassyFrame ~= nil end
S.GlassyPresent = glassyPresent

-- v2.6: position alone could never fit Glassy. Its saved 600-unit width is 844 px on the device,
-- against a chat slot of ~690 px beside the resident bags, so every pass logged STILL OVERFLOWS.
-- The WIDTH goes through Glassy's own setting and event -- the exact path its options slider uses
-- (Modules/ConfigChatPages.lua:192-194) -- via FFSpan_Glassy.lua, which keeps the player's
-- original, honours a width they set by hand, and never goes below Glassy's 300-unit soft minimum.
-- Whole units, like the slider, so repeated passes land on the same value and never re-dispatch.
function chatWidth.fit(frame, chat)
    local fit = S.GlassyFit
    if type(fit) ~= 'table' or type(fit.Apply) ~= 'function' or combat() then return end
    -- 2.9.0: the home chat stays up and FFSpan_ChatDim dims it when idle, instead of Glassy
    -- fading it out completely (Glassy's own chatAlwaysVisible, journaled, restored at logout)
    if not chatWidth.alwaysOn and type(fit.ApplyAlwaysVisible) == 'function' then
        local okA, changedA = safe(fit.ApplyAlwaysVisible)
        chatWidth.alwaysOn = okA and true or nil
        if changedA then log('glassy', 'chat kept visible (chatAlwaysVisible on until logout)') end
    end
    local core = _G.Glassy
    local profile = type(core) == 'table' and safe(function() return core.db.profile end)
    local cur = type(profile) == 'table' and tonumber(safe(function() return profile.frameWidth end))
    local es = call(frame, 'GetEffectiveScale')
    local _, ph = physical()
    if not (cur and cur > 0 and es and es > 0 and ph > 0) then return end
    local unitPx = es * ph / 768
    -- The width is taken from the SLOT alone. Glassy's envelope equals frameWidth exactly
    -- (844 px = 600 units on the device), and subtracting a measured "overhang" read a
    -- half-re-laid envelope as one: 09-25 06:44 stepped 541 -> 482 -> 423 -> 364 -> 305 units
    -- in two seconds before it settled. placeGlassy's own verify still reports any overflow.
    local want = math.floor(chat.w / unitPx)
    local ok, changed = safe(fit.Apply, want)
    local now = tonumber(safe(function() return profile.frameWidth end))
    local note
    if changed then
        note = ('chat width %d -> %s units for the %.0f px slot'):format(cur, tostring(now), chat.w)
    elseif not ok then
        note = ('chat width NOT fitted: wanted %d units for the %.0f px slot'):format(want, chat.w)
    end
    if note and note ~= chatWidth.last then log('glassy', note) end
    chatWidth.last = note or chatWidth.last
    -- v2.7 (FFScale 1.9, decided 2026-09-25): the micro menu is a bar across the bottom,
    -- so the chat slot got SHORTER than Glassy's 495 px envelope. Its HEIGHT goes through the same
    -- supported path as the width (FFSpan_Glassy ApplyHeight: frameHeight + Glassy's own dispatch).
    -- Glassy draws its tabs and edit box beyond frameHeight, so the target is the slot minus that
    -- overhead, measured -- and never in the pass straight after a change, while Glassy re-lays.
    if type(fit.ApplyHeight) ~= 'function' then return end
    if chatWidth.hPending then chatWidth.hPending = nil return end
    local curH = tonumber(safe(function() return profile.frameHeight end))
    local env = envelopePx(frame)
    if not (curH and curH > 0 and env and env.h > 0) then return end
    local overhead = env.h - curH * unitPx
    if overhead < 0 or overhead > 400 then return end   -- a half-laid envelope, not a measurement
    local wantH = math.floor((chat.h - overhead) / unitPx)
    local okH, changedH = safe(fit.ApplyHeight, wantH)
    if changedH then
        chatWidth.hPending = true
        log('glassy', ('chat height %d -> %d units for the %.0f px slot'):format(curH, wantH, chat.h))
    elseif not okH and chatWidth.hLast ~= wantH then
        log('glassy', ('chat height NOT fitted: wanted %d units for the %.0f px slot'):format(wantH, chat.h))
    end
    chatWidth.hLast = wantH
end

-- Put Glassy's whole visible envelope inside FFScale's published chat slot.
local function placeGlassy(slots)
    local mover = glassyMover()
    local chat = slots and slots.chat
    if not mover or type(chat) ~= 'table' or not (chat.w > 0 and chat.h > 0) then return nil end
    local frame = _G.GlassyFrame
    if not frame then return nil end
    local _, ph = physical()
    local q = ph / 768
    if q <= 0 then return nil end
    -- size first, then position: the mover takes Glassy's new width inside the same dispatch
    chatWidth.fit(frame, chat)

    -- The mover's own left/bottom must clear Glassy's edge snap, or SetDragPosition pulls it flat
    -- against UIParent and the requested margin disappears. The home screen's left edge IS
    -- UIParent's left, so a 16 px margin (11.4 units) is inside the 20-unit snap. FFSpan asks for the
    -- first margin outside it instead -- still inside the slot, still clear of the edge.
    -- FLUSH inside the slot: FFScale already sized and positioned the slot to Glassy's envelope
    -- and to the margin its snap demands, so there is nothing left to inset here.
    local wantX = chat.x
    local wantBottomY = chat.y + chat.h                     -- canvas top-down px

    -- Where is the envelope relative to the mover right now? Everything below is applied as a
    -- DELTA off that, so a skin that draws outside the frame is accounted for rather than assumed.
    local env = envelopePx(frame)
    local mv = rectPx(mover)
    if not env or not mv then return nil end
    local dx = env.x - mv.x                                  -- px the envelope sits left of the mover
    local dy = (env.y + env.h) - (mv.y + mv.h)               -- ...and below it

    local moverX = wantX - dx
    local moverBottomY = wantBottomY - dy

    -- SetDragPosition speaks UI units, bottom-up, relative to UIParent.
    local _, screenH = physical()
    local left = moverX / q
    local bottom = (screenH - moverBottomY) / q
    safe(function() mover:SetDragPosition(left, bottom) end)

    -- ...then VERIFY, because the snap may still have moved it and because Glassy re-lays its own
    -- bounds on a timer. A refusal is a diagnostic, exactly like a refused scale.
    local after = envelopePx(frame)
    local fits = after and after.x >= chat.x - 1 and after.y >= chat.y - 1
        and after.x + after.w <= chat.x + chat.w + 1
        and after.y + after.h <= chat.y + chat.h + 1
    glassyFits = fits and true or false
    log('glassy', ('chat envelope %s the chat slot (%.0f,%.0f %.0fx%.0f -> slot %.0f,%.0f %.0fx%.0f)')
        :format(fits and 'is inside' or 'STILL OVERFLOWS', after and after.x or -1,
                after and after.y or -1, after and after.w or -1, after and after.h or -1,
                chat.x, chat.y, chat.w, chat.h))
    return fits
end
-- FFScale sizes the chat slot from this. Glassy's envelope is 495 px on the device -- taller
-- than the 300 px chat slot the layout used to reserve -- so without it Glassy could never fit
-- however it was positioned. The slot's HEIGHT follows Glassy; its WIDTH is whatever is left
-- beside the bags, and chatWidth.fit brings Glassy's own width setting down to that (v2.6).
-- Glassy's mover snaps to its parent's edge within EDGE_SNAP_DISTANCE = 20 UI units
-- (Components/MoverFrame.lua:20, :56-65). The home screen's left and bottom edges ARE UIParent's,
-- so the usual 16 px margin (11.4 units) sits inside the snap and SetDragPosition would pull the
-- chat flat against the panel. The chat slot therefore uses the first margin OUTSIDE the snap --
-- still a margin, just Glassy's minimum one -- and the envelope is then placed flush inside it.
function S.GlassyChatMarginPx()
    if not glassyPresent() then return nil end
    local _, ph = physical()
    local q = ph / 768
    if q <= 0 then return nil end
    return math.max(MARGIN, (GLASSY_SNAP + 0.5) * q)
end

function S.GlassyChatHeightPx()
    if not glassyPresent() then return nil end
    local env = envelopePx(_G.GlassyFrame)
    if not env or not (env.h > 0) then return nil end
    return env.h
end
S.PlaceGlassy = placeGlassy
function S.GlassyFits() return glassyFits end

local function placeAll(reason)
    if placing or not ready() then return end
    if not S.HomeEligible() then return end
    placing = true
    safe(function()
        -- Glassy's chat is resident furniture, placed once per pass with the
        -- slots FFScale published -- home screen only (placeAll already refuses off it).
        if glassyPresent() then safe(placeGlassy, measureHomeSlots()) end
        local visible = visibleManaged()
        closeGameMenuFor(visible)
        local skipPages = arbitratePages(visible)
        local kept = {}
        for _, n in ipairs(visible) do
            if not skipPages[n] and _G[n] and call(_G[n], 'IsVisible') then kept[#kept + 1] = n end
        end
        visible = kept
        local lane = {}
        for _, n in ipairs(visible) do
            if classOf(n) == 'COMPANION' then lane[#lane + 1] = n end
        end
        -- the bag width is settled BEFORE the lane is measured off it
        local beforeCap = bagWidthCap
        local wantBagScale = negotiateBagScale(lane)
        if math.abs(wantBagScale - bagScaleTarget) > 0.001 or beforeCap ~= bagWidthCap then
            bagScaleTarget = wantBagScale
            anchoring = true; safe(anchorBags); anchoring = false
        end
        layoutLane(lane)
        for _, n in ipairs(visible) do placeOne(n) end
    end)
    placing = false
    if reason then log('place', reason) end
end
-- v2.6.3: the Dump's map probe records whether a Blizzard map hook fired inside FFSpan's own pass
function S.HomePlacing() return placing end
-- =============================================== checkFit rescale ==============================
-- CORRECTION of an earlier conclusion. The first build assumed "SetScale does not take on protected
-- Blizzard panels"; that was inferred from ONE frame and it is wrong -- BlizzMove scales exactly
-- these panels out of combat every day. What actually happens is that BLIZZARD re-applies its own
-- fit scale after FFSpan has placed the frame:
--   * PlayerSpellsFrame is registered checkFit = 1, checkFitExtraWidth = 200
--     (Blizzard_PlayerSpells/Blizzard_PlayerSpellsRegistration.lua).
--   * UIParentPanelManager.lua calls FramePositionDelegate:UpdateScaleForFit from FOUR places --
--     ShowUIPanel :532, the "update frame's scaling early" step of UpdateUIPanelPositions :705,
--     EvaluateAutoMinimize :1018 and UpdateScaleForFitForOpenPanels :1001 -- and all four funnel
--     through the GLOBAL UIPanelUpdateScaleForFit :1062. Three of them are NOT inside the global
--     UpdateUIPanelPositions FFSpan already post-hooks, so they land after its placement.
--   * That fit is measured against UIParent, i.e. the whole 4400 canvas, so a frame that is only
--     too TALL comes back at scale 1 and FFSpan's fit is undone.
-- The remedy is BlizzMove's (Kiatra/BlizzMove, BlizzMove.lua, 2026-09-19): post-hook the global
-- and re-apply. In combat on a protected frame, queue it for PLAYER_REGEN_ENABLED exactly as
-- BlizzMove does -- which here just means it becomes a deferred window under the existing rules.
--
-- The hook is frame-AGNOSTIC on purpose: it fires with the frame as its first argument, so it
-- covers every checkFit panel in the class table without anyone having to enumerate them.
local rescaling = false
local function onScaleForFit(frame)
    if rescaling or placing or not ready() then return end
    local name = frame and safe(function() return frame.GetName and frame:GetName() end)
    if not name or not MANAGED[name] or not placedNames[name] then return end
    if combat() then
        deferred[name] = true   -- protected in combat: put it back at regen, like BlizzMove
        return
    end
    rescaling = true
    safe(placeOne, name)
    rescaling = false
end

-- ============================================= panel-edge awareness ============================
-- WoW sees ONE 4400x1080 screen, so any code that picks a side from the SCREEN HALF, or from the
-- distance to the SCREEN EDGE, is wrong at the inner panel edges. I hit the bag case:
-- ContainerFrameItemButton_CalculateItemTooltipAnchors uses
-- `anchorFromLeft = self:GetRight() < GetScreenWidth()/2` -> ANCHOR_RIGHT, and EVERYTHING on the
-- home screen is in the canvas's left half with ~3000 px of "room" to its right, so the tooltip
-- opens rightwards across x = 1240 and off the bottom screen. The same rule is in EquipmentFlyout,
-- WorldMapBountyBoard, the raid UI and TooltipComparisonManager; ConsolePort's cursor tooltips
-- use GameTooltip with a hard ANCHOR_RIGHT, so the GameTooltip rule covers those too.
--
-- ONE relocator, applied AFTER whoever owns the frame has positioned it. It never replaces a
-- Blizzard function and never touches GetScreenWidth. Centred frames are untouched by construction
-- (the canvas centre x2200 IS the top panel's centre).
local TRANSIENT = {
    'GameTooltip', 'ShoppingTooltip1', 'ShoppingTooltip2', 'ShoppingTooltip3',
    'ItemRefTooltip', 'ItemRefShoppingTooltip1', 'ItemRefShoppingTooltip2',
    'EmbeddedItemTooltip', 'EquipmentFlyoutFrame', 'SpellFlyout',
    'DropDownList1', 'DropDownList2', 'DropDownList3',
}
local FOLLOWERS = {GameTooltip = {'ShoppingTooltip1', 'ShoppingTooltip2', 'ShoppingTooltip3'}}
local relocating = false

-- the panel that contains canvas x: HOME 0..1240, TOP 1240..3160. x >= 3160 is drawn nowhere.
local function panelFor(x)
    local home, game = S.HomeRect(), S.GameRect()
    if home and x >= home.x and x < home.x + home.w then
        return {x0 = home.x, x1 = home.x + home.w}
    end
    if game and x >= game.x and x < game.x + game.w then
        return {x0 = game.x, x1 = game.x + game.w}
    end
    return nil
end

-- v2.6: OWNER-anchored tooltips (09-25 06:45: the tooltip popped off to the right, off the
-- screen). Bag items, spells and ConsolePort nodes use SetOwner(owner, 'ANCHOR_RIGHT'), and WoW
-- itself re-applies that anchor every time the owner refreshes its tooltip -- a bag item does it
-- several times a second -- firing neither OnShow nor OnSizeChanged, so a tooltip moved by the
-- relocator below went straight back across the seam (dump 06:52: GameTooltip x1091 w353,
-- 'split'). Pick the side the way Blizzard means to -- towards the middle of the SCREEN the owner
-- is on, not of the 4400 canvas -- and do it with the anchor type itself, which WoW then keeps
-- through every refresh. The relocator still clamps anything too wide for either side.
local tipSide = {
    mirror = {ANCHOR_RIGHT = 'ANCHOR_LEFT', ANCHOR_TOPRIGHT = 'ANCHOR_TOPLEFT',
              ANCHOR_BOTTOMRIGHT = 'ANCHOR_BOTTOMLEFT', ANCHOR_LEFT = 'ANCHOR_RIGHT',
              ANCHOR_TOPLEFT = 'ANCHOR_TOPRIGHT', ANCHOR_BOTTOMLEFT = 'ANCHOR_BOTTOMRIGHT'},
    rightward = {ANCHOR_RIGHT = true, ANCHOR_TOPRIGHT = true, ANCHOR_BOTTOMRIGHT = true},
}
function tipSide.apply(tt, owner)
    if relocating or not S.HomeEligible() then return end
    local kind = call(tt, 'GetAnchorType')
    local mirror = kind and tipSide.mirror[kind]
    if not mirror or type(safe(function() return tt.SetAnchorType end)) ~= 'function' then return end
    owner = owner or call(tt, 'GetOwner')
    local o = owner and envelopePx(owner)
    if not o then return end
    local cx = o.x + o.w / 2
    local panel = panelFor(cx)
    if not panel then return end
    -- right half of its own screen and opening right (or left half, opening left): flip it
    if (cx > (panel.x0 + panel.x1) / 2) == (tipSide.rightward[kind] == true) then
        relocating = true
        safe(function() tt:SetAnchorType(mirror) end)
        relocating = false
    end
end

local relocateTransient
relocateTransient = function(f, owner)
    if relocating or not S.HomeEligible() then return end
    if type(f) == 'string' then f = _G[f] end
    if not f or not call(f, 'IsVisible') or call(f, 'IsForbidden') then return end
    if combat() and call(f, 'IsProtected') then
        log('edge', tostring(call(f, 'GetName')) .. ' protected in combat: left where it is')
        return
    end
    tipSide.apply(f, owner)
    local env = envelopePx(f)
    if not env or env.w <= 0 or env.h <= 0 then return end
    owner = owner or safe(function() return f.GetOwner and f:GetOwner() end)
    local ownerEnv = owner and envelopePx(owner)
    -- the panel is the OWNER's, not the tooltip's: the tooltip may already have escaped it
    local panel = panelFor(ownerEnv and (ownerEnv.x + ownerEnv.w / 2) or (env.x + env.w / 2))
                  or panelFor(env.x)
    if not panel then return end
    local x = env.x
    if env.x + env.w > panel.x1 + 0.5 then
        x = ownerEnv and (ownerEnv.x - env.w) or (panel.x1 - env.w)   -- mirror to the LEFT
    elseif env.x < panel.x0 - 0.5 then
        x = ownerEnv and (ownerEnv.x + ownerEnv.w) or panel.x0        -- mirror to the RIGHT
    end
    -- still no fit -> clamp inside the panel; never split, never into the unshown strip
    x = clamp(x, panel.x0, math.max(panel.x0, panel.x1 - env.w))
    local _, ph = physical()
    local y = clamp(env.y, 0, math.max(0, ph - env.h))
    if math.abs(x - env.x) >= 0.5 or math.abs(y - env.y) >= 0.5 then
        local rootX, rootY = env.root.x + (x - env.x), env.root.y + (y - env.y)
        relocating = true
        safe(function()
            local q = (call(f, 'GetEffectiveScale') or 1) * ph / 768
            if not q or q <= 0 then error('scale') end
            -- an owner anchor would be re-applied by WoW over FFSpan's point; take it off first
            if tipSide.mirror[call(f, 'GetAnchorType') or ''] then f:SetAnchorType('ANCHOR_NONE') end
            f:ClearAllPoints()
            f:SetPoint('TOPLEFT', UIParent, 'BOTTOMLEFT', rootX / q, (ph - rootY) / q)
        end)
        relocating = false
    end
    -- The followers are checked whether or not the main tooltip itself had to move: they were
    -- positioned by the comparison manager against the SCREEN, so they can straddle an edge even
    -- when the tooltip they hang off does not.
    local name = call(f, 'GetName')
    -- the comparison tooltips were positioned against the MAIN tooltip's old spot
    for _, follower in ipairs(FOLLOWERS[name] or {}) do
        local g = _G[follower]
        if g and call(g, 'IsVisible') then relocateTransient(g, f) end
    end
end
S.RelocateTransient = relocateTransient

local hookedTransient = {}
local function hookTransients()
    for _, name in ipairs(TRANSIENT) do
        local f = _G[name]
        if f and not hookedTransient[name] and not call(f, 'IsForbidden') then
            if safe(function()
                f:HookScript('OnShow', function() relocateTransient(f) end)
                f:HookScript('OnSizeChanged', function() relocateTransient(f) end)
                return true
            end) then hookedTransient[name] = true end
        end
        -- v2.6.2: every SetOwner / SetPoint is an owner (re)anchoring the frame -- including the
        -- refreshes that fire neither script above. A bag slot re-runs Blizzard's
        -- CalculateItemTooltipAnchors (SetOwner ANCHOR_NONE + SetPoint) several times a second, so
        -- 2.6.1's next-frame correction left one frame on the wrong side at EVERY refresh: the
        -- tooltip visibly flashed right-left (07:22). Correct it synchronously, inside the
        -- owner's own call, so the frame is only ever drawn where it ends up. A two-point anchor is
        -- left to OnSizeChanged: re-pointing between an owner's first and second SetPoint would
        -- stretch it.
        if f and not hookedTransient[name .. ':owner'] and not call(f, 'IsForbidden') then
            if safe(function()
                if type(f.SetOwner) == 'function' then
                    hooksecurefunc(f, 'SetOwner', function(tt, owner)
                        tipSide.apply(tt, owner)
                        relocateTransient(tt, owner)
                    end)
                end
                hooksecurefunc(f, 'SetPoint', function(tt)
                    if not relocating and (call(tt, 'GetNumPoints') or 0) <= 1 then
                        relocateTransient(tt)
                    end
                end)
                return true
            end) then hookedTransient[name .. ':owner'] = true end
        end
    end
    -- retail's Menu system builds ANONYMOUS context menus, reachable only through the manager
    -- proxy (Blizzard_Menu/Menu.lua: Menu.GetManager(), MenuManagerProxyMixin:OpenContextMenu,
    -- :GetOpenMenu). Hook the open and relocate on the next frame, once it has been laid out.
    local mgr = _G.Menu and safe(function() return _G.Menu.GetManager and _G.Menu.GetManager() end)
    if mgr and not hookedTransient['@menu'] then
        if safe(function()
            hooksecurefunc(mgr, 'OpenContextMenu', function(_, region)
                if not C_Timer then return end
                safe(C_Timer.After, 0, function()
                    local open = safe(function() return mgr:GetOpenMenu() end)
                    if open then relocateTransient(open, region) end
                end)
            end)
            return true
        end) then hookedTransient['@menu'] = true end
    end
end

-- what the dump asks: is every visible transient frame fully on one panel right now?
function S.TransientOffPanel()
    local out = {}
    if not S.HomeEligible() then return out end
    for _, name in ipairs(TRANSIENT) do
        local f = _G[name]
        if f and call(f, 'IsVisible') then
            local env = envelopePx(f)
            if env and env.w > 0 then
                local panel = panelFor(env.x + env.w / 2)
                if not panel or env.x < panel.x0 - 0.5 or env.x + env.w > panel.x1 + 0.5 then
                    out[#out + 1] = {name = name, x = env.x, width = env.w,
                                     panel = panel and panel.x0 or nil}
                end
            end
        end
    end
    return out
end

H.PlaceAll = placeAll -- mock-test entry, same gates
-- v2.2: ONE physical-px conversion for both addons. FFScale reads the live minimap / bottom-bar
-- edges through this before it publishes FFScale.HomeSlots(), so the column it publishes and the
-- column FFSpan fits the bags into are measured the same way.
function S.EnvelopePx(nameOrFrame)
    local f = (type(nameOrFrame) == 'string') and _G[nameOrFrame] or nameOrFrame
    if not f then return nil end
    return envelopePx(f)
end
function S.RectPx(nameOrFrame)
    local f = (type(nameOrFrame) == 'string') and _G[nameOrFrame] or nameOrFrame
    if not f then return nil end
    return rectPx(f)
end
-- what the panel-manager hook actually bound to, for the dump and the logs
function H.PanelHook() return panelHook end
function H.LayoutConfirmed() return layoutConfirmed end
-- v2.2.1: where the confirmed column's edges came from, and whether that is the approved
-- DEGRADED mode (estimated rather than measured). Reported in the dump so a capture can never be
-- read as measured home geometry when it is not.
-- v2.4: windows whose scale readback STILL disagreed after Blizzard's checkFit
-- pass and FFSpan's re-apply. A diagnostic, not a placement decision -- they are placed anyway.
function H.ScaleRefused()
    local out = {}
    for name in pairs(scaleRefused) do out[#out + 1] = name end
    table.sort(out)
    return out
end
S.ScaleRefused = H.ScaleRefused

-- ...and WHO. `{PlayerSpellsFrame = 'TalentTreeTweaks:ScaleTalentFrame'}` in the dump beats
-- inferring it all over again from rects.
function H.ScaleOwners()
    local out = {}
    for name, who in pairs(scaleOwners) do out[name] = who end
    return out
end
function H.PositionOwners()
    local out = {}
    for name, who in pairs(positionOwners) do out[name] = who end
    return out
end
S.PositionOwners = H.PositionOwners
S.ScaleOwners = H.ScaleOwners
function H.ScaleHook() return scaleHook end
function H.BagScale() return bagScaleTarget end
function H.LayoutSource() return layoutSource end
function H.LayoutDegraded() return layoutDegraded end

-- ============================================================================ resident bags ====
-- Two Escape presses for now, by design: native Escape is untouched -- FFSpan never hooks Escape or
-- CloseAllBags and never re-opens from an OnHide. Residency resumes only on: login, loading-screen
-- end, the game menu closing, and the player's own bag key (which opens them natively anyway).
-- 2.9.0: for BAGANATOR's bags (every flavor on the Thor) I reversed this -- they are open
-- all the time; see "always-open bags" below. Blizzard's own bags still follow the two-press rule.
local function isBankContainer(f)
    local id = call(f, 'GetID')
    if id == nil then return false end
    if type(_G.ContainerFrame_IsCharacterBankTab) == 'function'
        and safe(_G.ContainerFrame_IsCharacterBankTab, id) then return true end
    if type(_G.ContainerFrame_IsAccountBankTab) == 'function'
        and safe(_G.ContainerFrame_IsAccountBankTab, id) then return true end
    if call(f, 'IsBankBag') then return true end
    return false
end

local function bagsShown()
    local mgr = _G.ContainerFrameSettingsManager
    local list = mgr and call(mgr, 'GetBagsShown')
    if type(list) ~= 'table' then
        list = {}
        for i = 1, 13 do
            local f = _G['ContainerFrame' .. i]
            if f and call(f, 'IsShown') then list[#list + 1] = f end
        end
        local combined = _G.ContainerFrameCombinedBags
        if combined and call(combined, 'IsShown') then table.insert(list, 1, combined) end
    end
    local player, bank = {}, {}
    for _, f in ipairs(list) do
        if f and call(f, 'IsShown') then
            if isBankContainer(f) then bank[#bank + 1] = f else player[#player + 1] = f end
        end
    end
    return player, bank
end

-- Anchors the player's bags into the home column (Blizzard puts them at the canvas BOTTOMRIGHT,
-- which is the UNSHOWN region at 4400) and fits their SCALE to the column, because Blizzard's own
-- fit uses the whole canvas width (ContainerFrame.lua:1163,1223).
-- ================================================= Baganator bridge ===========================
-- Decided 2026-09-23: bags stay ALWAYS OPEN and NOTHING overlaps, so the
-- resident bag view has to FIT the box rather than be scaled down into it. Baganator's grid does
-- that if it is told how many COLUMNS and what ICON SIZE to use.
--
-- LICENCE: Baganator is All Rights Reserved (plusmouse). Nothing here is copied from it. FFSpan
-- only reads its SavedVariable, writes the documented option keys, calls its ONE public refresh
-- function, and anchors its frame -- all runtime configuration, which is what a user could do by
-- hand in its own options panel. The grid arithmetic below is FFSpan's own.
--
-- The pitch and the two option keys come from reading its source:
-- container width = cols * (icon + padding) - padding, height =
-- rows * (icon + padding), padding 4 at default spacing. Everything else about the frame is
-- chrome, which FFSpan MEASURES rather than assumes.
baganatorPresent = function()
    local b = _G.Baganator
    return type(b) == 'table' and type(safe(function() return b.API end)) == 'table'
end

-- ---- PRESENT IS NOT USABLE (the device blocker) ----------------------------------------------
-- v2.5.1 shipped to the Thor with Baganator 829 installed and Syndicator NOT installed, and the
-- player got a bottom screen with no bags on it at all. The reason is that `baganatorPresent()`
-- above answers the wrong question. Baganator creates its global in
-- `Core/Objects.lua:3` -- `Baganator = {API = {Constants = {}}}` -- at FILE LOAD, unconditionally.
-- Its real initialisation happens later, in its own ADDON_LOADED handler, and
-- `Core/Initialize.lua:32-50` starts that handler by calling `error()` when Syndicator is missing.
-- So `ItemViewCommon.Initialize` / `ViewManagement.Initialize` never run, not one frame is built,
-- `ToggleAllBags` is never replaced (`ViewManagement/Initialize.lua:126`) and nothing lands in
-- UISpecialFrames (`:165`) -- while the global being tested sits there looking healthy.
-- v2.5.1 stood the Blizzard bags down on the strength of it.
--
-- `baganatorUsable()` is the predicate for every decision that changes what the PLAYER sees.
-- `baganatorPresent()` survives only for the things that are merely about the global existing.
local usableDecided, usableValue, usableWhy

local function addonIsLoaded(name)
    local f = (_G.C_AddOns and _G.C_AddOns.IsAddOnLoaded) or _G.IsAddOnLoaded
    if type(f) ~= 'function' then return nil end          -- cannot tell; do not hold it against it
    return safe(f, name) and true or false
end

-- ---- "NOT YET" IS NOT "NO" (v2.5.4; Classic 5.5.4 device run 2026-09-24) ---------------------
-- FFSpanDB: "loaded but not usable (loaded but never initialised (no bag view)) -> Blizzard bags"
-- at 17:19:44, latched for the rest of the session. FFScaleLog's measure at 17:19:58 then listed
-- Baganator_SingleViewBackpackViewFrameblizzard and Baganator_CategoryViewBackpackViewFrameblizzard
-- as SHOWN children of UIParent, both anchored to Baganator_WelcomeFrame (its first-run chooser),
-- while FFSpan's Blizzard-bag residency had nothing to hold (ContainerFrame1/2 recorded with no points).
-- So the prefixes below are right and the verdict was early. Whether the views were late or only
-- missing from UISpecialFrames the dump cannot say, so on Classic both are covered: the backpack
-- lookup falls back to UIParent's children, and the two "not yet" verdicts get a bounded ONE-WAY
-- re-check (soft.schedule, below openResidentBags) that can only ever turn them into "usable".
-- Retail (soft.enabled false) skips both of those; this table is one long chunk rather than ten
-- locals because Lua caps a function at 200 locals.
--
-- ---- v2.5.5 (fresh Retail account, live device run 2026-09-24): the WELCOME CHOOSER ITSELF is
-- not Classic-specific -- Baganator shows Baganator_WelcomeFrame on ANY flavor's first login. With
-- the onboarding branch below gated to soft.enabled, a fresh Retail account hitting computeUsable()
-- while the chooser was still open fell straight through to the generic NOT_INIT verdict, and that
-- LATCHED (usableDecided only re-arms on ADDON_LOADED of Baganator/Syndicator, which had already
-- fired). Picking Single/Category bag view then closed the chooser but nothing was listening, so
-- resident bags never recovered. The onboarding wait + one-shot recheck (soft.schedule's OnHide
-- hook) costs nothing on an already-configured Retail account -- Baganator_WelcomeFrame only
-- exists and shows during first-run -- so it now runs on every flavor.
--
-- ---- v2.5.6: Retail also needs bounded late discovery. The 09-24 session latched NOT_INIT,
-- then its logout dump found a shown backpack in the unshown strip. That does NOT establish when
-- it was created: Baganator 829 normally creates both views at PLAYER_LOGIN, before any toggle.
-- The retry ladder and UIParent fallback now cover every flavor; an explicit bag press can also
-- recheck a soft failure after the ladder ends. No synthetic toggle is needed to create a view.
local soft = {
    NOT_INIT   = 'loaded but never initialised (no bag view)',
    ONBOARDING = 'first-run welcome open (onboarding)',
    delays = { 2, 5, 15, 45 }, step = 0, pending = false, welcomeHooked = false,
}

-- Baganator's first-run chooser previews BOTH views anchored to itself; taking one over while it
-- is up would tear the preview out of the player's choice, so the verdict waits for it to close.
-- Not gated on soft.enabled (v2.5.5): the chooser itself is not a Classic-only phenomenon.
function soft.onboarding()
    local w = _G.Baganator_WelcomeFrame
    return w ~= nil and safe(function() return w:IsShown() end) == true
end

local function computeUsable()
    if not baganatorPresent() then return false, 'not loaded' end
    -- the exact condition Baganator itself errors out on (Core/Initialize.lua:33)
    if addonIsLoaded('Syndicator') == false then return false, 'Syndicator not loaded' end
    -- Baganator builds its frames on PLAYER_LOGIN (Skins/Initialize.lua:46-49) and FFSpan's own login
    -- pass may well run first, so "no frame yet" only means something once FFSpan is READY -- which
    -- is gated on the layout owner's acknowledgement, long after every PLAYER_LOGIN handler.
    -- (Every check below also answered true before READY, so that answer is unchanged.)
    if not ready() then return true end
    -- v2.5.5: all flavors wait for the player's own first-run choice, not just Classic (see above).
    if soft.onboarding() then
        if soft.schedule then soft.schedule() end
        return false, soft.ONBOARDING
    end
    -- Its toggle is replaced BEFORE its frames are created. Only a real backpack proves that
    -- the view exists; a changed function (including another addon's wrapper) does not.
    if baganatorBackpack() then return true end
    -- NOT_INIT is soft on every flavor. Timed discovery never creates or selects an addon view.
    if soft.schedule then soft.schedule() end
    return false, soft.NOT_INIT
end

-- Decided ONCE per session at the readiness point and latched, so nothing flip-flops mid-session.
-- Re-armed only by ADDON_LOADED of Baganator or Syndicator.
baganatorUsable = function()
    if usableDecided then return usableValue end
    local v, why = computeUsable()
    if not ready() then return v end          -- provisional: not latched, not logged
    usableDecided, usableValue, usableWhy = true, v, why
    if not v and baganatorPresent() then
        log('baganator', 'loaded but not usable (' .. tostring(why) .. ') -> Blizzard bags')
    end
    local rec = S.HomeRecord(true)
    if rec then rec.baganator = v and 'usable' or ('unusable: ' .. tostring(why or 'absent')) end
    return v
end

-- ADDON_LOADED of either addon re-arms the decision (and only that).
local function rearmUsable(addon)
    if addon == 'Baganator' or addon == 'Syndicator' then
        usableDecided, usableValue, usableWhy = nil, nil, nil
    end
end

S.BaganatorUsable  = function() return baganatorUsable() end
S.BaganatorWhyNot  = function() return usableWhy end
S.BaganatorPresent = function() return baganatorPresent() end   -- diagnostic: loaded, not working

-- Its live settings table. Newer builds keep profiles; older ones put the keys at the top level.
local function baganatorConfig()
    local cfg = _G.BAGANATOR_CONFIG
    if type(cfg) ~= 'table' then return nil end
    local profiles = safe(function() return cfg.Profiles end)
    local current = _G.BAGANATOR_CURRENT_PROFILE
    if type(profiles) == 'table' and current ~= nil and type(profiles[current]) == 'table' then
        return profiles[current]
    end
    return cfg
end

-- 829 registers BOTH views in UISpecialFrames, in pairs() order (ViewManagement/Initialize.lua
-- 138-165). First match is not the selected view. Prefer the live shown view, then the configured
-- single/category choice and skin; the hidden selected view is valid before its first opening.
local function bagViewScore(f, name, prefixes, view)
    if not f or type(name) ~= 'string' or call(f, 'IsForbidden') then return nil end
    local cfg = baganatorConfig() or {}
    local selected = cfg[view .. '_view_type']
    local skin = cfg.current_skin
    for i, prefix in ipairs(prefixes) do
        if name:sub(1, #prefix) == prefix then
            local score = call(f, 'IsShown') and 4 or 0
            if (selected == 'single' and i == 1) or (selected == 'category' and i == 2) then
                score = score + 2
            end
            if type(skin) == 'string' and name:sub(#prefix + 1) == skin then score = score + 1 end
            return score
        end
    end
end

-- 2.9.0 always-open bags (filled in with openResidentBags): the resident backpack views it takes
-- off UISpecialFrames are still Baganator's views, so discovery reads its list too.
local keepOpen = { names = {}, hooked = {}, pending = false }

local function findByPrefix(prefixes, view)
    if soft.onboarding() then return nil end
    local best, bestName, bestScore
    for _, list in ipairs({_G.UISpecialFrames, keepOpen.names}) do
        if type(list) == 'table' then
            for _, name in ipairs(list) do
                if type(name) == 'string' then
                    local f = _G[name]
                    local score = bagViewScore(f, name, prefixes, view)
                    if score and (not bestScore or score > bestScore) then
                        best, bestName, bestScore = f, name, score
                    end
                end
            end
        end
    end
    return best, bestName
end

local BACKPACK_PREFIXES = {'Baganator_SingleViewBackpackViewFrame',
                           'Baganator_CategoryViewBackpackViewFrame'}
local BANKVIEW_PREFIXES = {'Baganator_SingleViewBankViewFrame',
                           'Baganator_CategoryViewBankViewFrame'}

baganatorBackpack = function() return (findByPrefix(BACKPACK_PREFIXES, 'bag')) end
baganatorBank = function() return (findByPrefix(BANKVIEW_PREFIXES, 'bank')) end
S.BaganatorBackpack = baganatorBackpack
S.BaganatorBank = baganatorBank

-- Writing the SavedVariable does not refresh anything by itself; this is the public call that
-- queues exactly the Layout refresh those two keys declare.
local function baganatorRefresh()
    local api = safe(function() return _G.Baganator.API end)
    local req = api and safe(function() return api.RequestLayoutUpdate end)
    if type(req) == 'function' then safe(req) end
end

-- Returns true when something changed. `cols`/`icon` are optional.
local function configureBaganator(cols, icon)
    local cfg = baganatorConfig()
    if not cfg then return false end
    local changed = false
    local function put(key, value)
        if cfg[key] ~= value then cfg[key] = value; changed = true end
    end
    -- By design: the plain single grid and the Blizzard skin (native look, no custom chrome).
    -- Both are already Baganator's defaults; setting them makes a pre-existing profile agree.
    put('bag_view_type', 'single')
    put('current_skin', 'blizzard')
    -- Locking is what stops a stray drag rewriting its saved anchor, which is the only thing that
    -- would re-position the frame behind FFSpan's back.
    put('lock_frames', true)
    if cols then put('bag_view_width', cols) end
    if icon then put('bag_icon_size', icon) end
    if changed then baganatorRefresh() end
    return changed
end

-- How many bag slots the character actually has, so the grid can be solved for them.
totalBagSlots = function()
    local get = _G.C_Container and safe(function() return _G.C_Container.GetContainerNumSlots end)
    if type(get) ~= 'function' then return nil end
    local last = tonumber(_G.NUM_TOTAL_EQUIPPED_BAG_SLOTS) or tonumber(_G.NUM_BAG_SLOTS) or 4
    last = clamp(math.floor(last), 1, 8)
    local total = 0
    for i = 0, last do total = total + (tonumber(safe(get, i)) or 0) end
    return total
end
S.TotalBagSlots = totalBagSlots

-- THE grid solve, in UI units. Maximise the icon size subject to rows x cols >= slots and the
-- whole thing fitting the box. Walking the icon size down from the cap and taking the first fit
-- gives the largest icon by construction -- no cleverness, and bounded at 19 steps.
-- `minIcon` defaults to the original floor. With a companion open the BALANCED search
-- is the authority on how small the icon may get -- it has already weighed the icon
-- against the companion's scale -- so that floor is deliberately lifted and the numbers are
-- reported instead. Keeping it would have refused the balanced answer outright: at 202 slots the
-- search picks icon 24 with both sides at 0.65, and a hard 26 would have forced 0.73 / 0.44.
--
-- v2.6.5: bagHeaderMinW is the smallest WINDOW Baganator draws (its header: search box and
-- buttons), and a narrower grid simply sits inside that window. It used to be a width the GRID
-- had to reach, which made the answer depend on how whole columns happened to round: on the
-- device (09-25 08:5x, 60 slots, a 395-unit column, minimum 387.x) every pitch from icon 37 down
-- to 30 left the grid a few units short, so the Character frame opening dropped the bags from
-- icon 33 to 29 (0.78) for nothing. The only width test that matters is that the window fits.
local function solveBagGrid(boxWUnits, boxHUnits, slots, minIcon)
    if not (boxWUnits > 0 and boxHUnits > 0 and slots and slots > 0) then return nil end
    for icon = BAG_ICON_MAX, (minIcon or BAG_ICON_MIN), -1 do
        local pitch = icon + BAG_PADDING
        local cols = math.floor((boxWUnits - bagChromeW + BAG_PADDING) / pitch)
        if cols >= 1 then
            local rows = math.ceil(slots / cols)
            local h = rows * pitch + bagChromeH
            local w = math.max(cols * pitch - BAG_PADDING + bagChromeW, bagHeaderMinW)
            if h <= boxHUnits and w <= boxWUnits + 0.5 then   -- 0.5: float slack, not layout
                return {icon = icon, cols = cols, rows = rows, w = w, h = h,
                        scale = icon / BAG_ICON_BASE, slots = slots}
            end
        end
    end
    return nil
end
S.SolveBagGrid = solveBagGrid

-- The narrowest the bag box may get and still show every slot at the icon floor. This is the
-- bags' hard minimum: a companion may have whatever is left over, but not this.
minBagWidthUnits = function(boxHUnits, slots)
    if not (boxHUnits and boxHUnits > 0 and slots and slots > 0) then return 0 end
    local pitch = BAG_ICON_MIN + BAG_PADDING
    local maxRows = math.floor((boxHUnits - bagChromeH) / pitch)
    if maxRows < 1 then return 0 end
    local cols = math.ceil(slots / maxRows)
    return math.max(cols * pitch - BAG_PADDING + bagChromeW, bagHeaderMinW)   -- v2.6.5: window floor
end
S.MinBagWidthUnits = minBagWidthUnits

-- v2.5.1: the width this character's bags need AT NATIVE
-- icon size. FFScale sizes the home layout's right column from this, so a 30-slot character no
-- longer pays for a 202-slot one. Returns px, or nil when it cannot be worked out.
local function bagColumnRequestPx(boxHPx)
    if not baganatorUsable() then return nil end
    local slots = totalBagSlots()
    if not slots or slots <= 0 then return nil end
    local _, ph = physical()
    local q = ph / 768
    if q <= 0 or not boxHPx or boxHPx <= 0 then return nil end
    local pitch = BAG_ICON_MAX + BAG_PADDING
    local maxRows = math.floor((boxHPx / q - bagChromeH) / pitch)
    if maxRows < 1 then return nil end
    local cols = math.ceil(slots / maxRows)
    -- v2.6.5: the column is the WINDOW Baganator draws, which never goes below its minimum
    return math.max(cols * pitch - BAG_PADDING + bagChromeW, bagHeaderMinW) * q, slots
end
S.BagColumnRequestPx = bagColumnRequestPx

-- Chrome is whatever the live frame has beyond the grid it was asked for. Measured once, then reused,
-- so the first solve can be slightly out and every later one is exact.
-- v2.6: the resident bags sit BELOW page windows. Baganator's view is a topLevel MEDIUM frame
-- (ItemViewCommon/BackpackView.xml:2), so every show or tap raised it over a MEDIUM page: on
-- 09-25 06:54 the bags covered a column of the spellbook, while the HIGH world map covered the
-- bags. A page is one window at a time OVER the home HUD (CLASS.PAGE), so the bags take the LOW
-- strata while home is on -- still above the world and still raised within LOW when touched --
-- and get their own strata back on home off.
local bagLayer = {orig = {}}
function bagLayer.lower(f)
    if not f or (combat() and call(f, 'IsProtected')) then return end
    if bagLayer.orig[f] == nil then bagLayer.orig[f] = call(f, 'GetFrameStrata') or 'MEDIUM' end
    if call(f, 'GetFrameStrata') ~= 'LOW' then safe(function() f:SetFrameStrata('LOW') end) end
end
function bagLayer.restore()
    for f, strata in pairs(bagLayer.orig) do
        if not (combat() and call(f, 'IsProtected')) then
            safe(function() f:SetFrameStrata(strata) end)
            bagLayer.orig[f] = nil
        end
    end
end

local function measureBagChrome(frame, grid)
    if not (frame and grid) then return end
    local env = envelopePx(frame)
    if not env or env.w <= 0 or env.h <= 0 then return end
    local _, ph = physical()
    local q = (call(frame, 'GetEffectiveScale') or 1) * ph / 768
    if q <= 0 then return end
    local pitch = grid.icon + BAG_PADDING
    local fw, fh = env.w / q, env.h / q
    local w = fw - (grid.cols * pitch - BAG_PADDING)
    local h = fh - (grid.rows * pitch)
    if not (w >= 0 and w < 200 and h >= 0 and h < 300) then return end
    -- v2.6: Baganator never draws its window smaller than its header needs (search box + buttons),
    -- ~387 x 362 units on the device. Past that, "frame minus grid" is NOT chrome: on 09-25 06:53
    -- it read 58 -> 85 -> 103 units while the balanced split shrank icons 33 -> 30 -> 28 for a
    -- companion, each smaller icon making the "chrome" look bigger and the next icon smaller, for
    -- no width gained. The real chrome is ~30 x 81 units, so a reading beyond 40 / 100 is the
    -- window's minimum instead -- the width one becomes the solvers' floor.
    local wIsChrome, hIsChrome = w <= 40, h <= 100
    if (wIsChrome and (not bagChromeMeasured or math.abs(w - bagChromeW) > 1))
        or (hIsChrome and (not bagChromeMeasured or math.abs(h - bagChromeH) > 1)) then
        if wIsChrome then bagChromeW = w end
        if hIsChrome then bagChromeH = h end
        bagChromeMeasured = true
        log('bags', ('Baganator chrome measured: %.0f x %.0f units'):format(bagChromeW, bagChromeH))
    end
    -- v2.6.5: remembered across sessions (FFSpanDB.bagWindowMinW, seeded in activate), so the
    -- first column of a session is sized to the real window instead of the 300-unit guess. A window
    -- drawn NARROWER than the remembered minimum (wIsChrome: it is exactly grid + chrome) proves
    -- the minimum went down -- a Baganator setting changed -- so the floor follows it down too.
    local learned
    if not wIsChrome and fw > bagHeaderMinW + 1 then
        learned = fw
    elseif wIsChrome and fw < bagHeaderMinW - 1 then
        learned = fw
    end
    if learned then
        bagHeaderMinW = learned
        if type(FFSpanDB) == 'table' then FFSpanDB.bagWindowMinW = learned end
        log('bags', ('Baganator minimum width measured: %.0f units'):format(learned))
    end
end

-- Residency, Baganator style. Its ToggleAllBags IS its own toggle (it replaces the global), and
-- OpenAllBags is deliberately NOT hooked by it -- so calling OpenAllBags here would open
-- Blizzard's bags behind its view. The IsShown guard is what stops the toggle closing it.
local openingBaganator = false
local function openBaganator()
    local frame = baganatorBackpack()
    if not frame or openingBaganator then return false end
    if call(frame, 'IsShown') then return true end
    local toggle = _G.ToggleAllBags
    if type(toggle) == 'function' then
        -- Its toggle may do nothing while Syndicator has no current character. FFSpan's own post-hook
        -- must not recursively retry that same no-op until Lua's stack is exhausted.
        openingBaganator = true
        safe(toggle)
        openingBaganator = false
    end
    frame = baganatorBackpack()
    return frame ~= nil and call(frame, 'IsShown') == true
end

-- RequestLayoutUpdate queues its work for the next frame (Baganator API/Main.lua). Never infer
-- chrome from the old rectangle and the NEW grid: that feedback made a real 16-slot bag collapse
-- to two columns, and left Retail's later-grown frame crossing the screen seam.
local function settleBagLayout()
    if bagLayoutPending or type(C_Timer) ~= 'table' then return end
    bagLayoutPending = true
    local gen = generation
    C_Timer.After(0, function()
        if gen ~= generation then return end
        bagLayoutPending = false
        if not ready() or combat() then return end
        local frame = baganatorBackpack()
        if not frame or not call(frame, 'IsShown') then return end
        measureBagChrome(frame, bagGrid)
        anchoring = true; safe(anchorBags); anchoring = false
        placeAll('bags:layout settled')
    end)
end

-- Fit Baganator's grid to the bag box and anchor it there. Returns the grid, or nil.
local function anchorBaganator(col)
    local frame = baganatorBackpack()
    if not (frame and col and col.w > 0 and col.h > 0) then return nil end
    if not mutable(frame) then return nil end
    if bagLayoutPending then return bagGrid end
    if not bagSizeHooked[frame] then
        bagSizeHooked[frame] = true
        safe(function()
            frame:HookScript('OnSizeChanged', function()
                if ready() and not anchoring and not placing then settleBagLayout() end
            end)
        end)
    end
    local slots = totalBagSlots()
    if not slots or slots <= 0 then return nil end
    local _, ph = physical()
    local q = (call(frame, 'GetEffectiveScale') or 1) * ph / 768
    if q <= 0 then return nil end
    -- a companion is open exactly when the balanced search has capped the column
    local grid = solveBagGrid(col.w / q, col.h / q, slots, bagWidthCap and BAG_ICON_FLOOR or nil)
    if not grid then
        -- Keep the current grid rather than reflowing into something that does not fit.
        -- The companion beside it gets whatever is left, which may be very little.
        log('bags', ('%d slots do not fit a %.0f px box even at the %d px icon floor; keeping the '
            .. 'current grid'):format(slots, col.w, BAG_ICON_MIN))
        -- v2.6.5: the companion lane is planned from bagsOccupiedWidth, so it must be what is
        -- actually DRAWN -- here that is Baganator's own minimum window, wider than this box and
        -- growing left from its right-hand anchor. A stale width let a companion sit on the bags.
        local drawn = envelopePx(frame)
        if drawn and drawn.w > 0 then bagsOccupiedWidth = drawn.w end
        return bagGrid
    end
    local changed = false
    if not bagGrid or bagGrid.cols ~= grid.cols or bagGrid.icon ~= grid.icon
        or bagGrid.slots ~= grid.slots then
        changed = configureBaganator(grid.cols, grid.icon)
        log('bags', ('Baganator grid: %d slots, %d cols x %d rows, icon %d (%.2f of Blizzard)')
            :format(grid.slots, grid.cols, grid.rows, grid.icon, grid.scale))
    end
    bagGrid = grid
    if changed then settleBagLayout() end
    snapshotFrame(call(frame, 'GetName') or 'Baganator', frame)
    -- anchored to the BOTTOM-RIGHT of the column, like the Blizzard bags it replaces
    local env = envelopePx(frame)
    local w = env and env.w or (grid.w * q)
    local h = env and env.h or (grid.h * q)
    local top = clamp(col.bottom - h, col.y, math.max(col.y, col.bottom - h))
    local overRight = env and (env.x + env.w - env.root.x - env.root.w) or 0
    local dy = (env and (env.root.y - env.y)) or 0
    safe(function()
        frame:ClearAllPoints()
        -- A later width change grows LEFT, never across the physical screen seam.
        frame:SetPoint('TOPRIGHT', UIParent, 'BOTTOMLEFT',
                       (col.right - overRight) / q, (ph - (top + dy)) / q)
    end)
    bagLayer.lower(frame)
    if not changed then measureBagChrome(frame, grid) end
    bagsOccupiedWidth = w
    bagsNaturalWidth = w
    return grid
end

-- v2.5.1: the ONLY thing that asks the layout owner to re-apply
-- ThorSpanHome. An Edit Mode save goes to Blizzard's servers, so it happens when the column
-- width this character's bags need actually CHANGES -- a bag equipped, removed or upgraded --
-- and never for looting, moving items, opening or closing bags, or zoning. Debounced so a
-- multi-bag swap is one save, deferred out of combat, and logged every time.
local function checkBagCapacity(reason)
    if not ready() or not baganatorUsable() then return end
    local col = bagColumn()
    if not col then return end
    local want = bagColumnRequestPx(col.h)
    if type(want) ~= 'number' then return end
    if lastColumnRequest and math.abs(want - lastColumnRequest) <= 1 then return end
    if capacityPending then return end
    capacityPending = true
    local gen = generation
    local function apply()
        capacityPending = false
        if gen ~= generation or not ready() then return end
        local now = bagColumnRequestPx(bagColumn() and bagColumn().h or 0)
        if type(now) ~= 'number' then return end
        if lastColumnRequest and math.abs(now - lastColumnRequest) <= 1 then return end
        if combat() then
            capacityPending = true
            deferredCapacity = true   -- picked up at PLAYER_REGEN_ENABLED
            return
        end
        lastColumnRequest = now
        log('bags', ('bag capacity changed (%s): column now wants %.0f px, re-applying the layout')
            :format(tostring(reason), now))
        local fs = layoutOwner()
        if fs then applyLayoutVia(fs, 'ffspan:bag-capacity') end
    end
    if C_Timer then safe(C_Timer.After, 0.5, apply) else apply() end
end
H.CheckBagCapacity = checkBagCapacity

function H.BagGrid() return bagGrid end
function H.BaganatorPresent() return baganatorPresent() end
-- The contract FFScale reads (it must not need to know which bag addon it is): true when
-- something other than Blizzard owns the bags, so the layout can reclaim the bag bar.
function S.BagAddonPresent() return baganatorUsable() end

anchorBags = function()
    local col = bagColumn()
    -- With Baganator loaded the resident bag view is ITS frame, fitted by columns
    -- and icon size rather than scaled down. Without it, everything below is exactly as before.
    if baganatorUsable() then
        if not col or col.w <= 0 or col.h <= 0 then return end
        anchorBaganator(col)
        -- Return either way. Falling through to the Blizzard path would find no container frames,
        -- reset bagsOccupiedWidth to 0, and the companion lane would then size itself as if the
        -- whole home screen were free -- straight over the bags.
        return
    end
    -- A degenerate column (slots that disagree, or a canvas change mid-pass) must not reach the
    -- scale maths below: a non-positive fit becomes a non-positive SetScale, and a frame left at
    -- scale <= 0 is skipped by `cur > 0` on every later pass -- i.e. it is never placed again.
    if not col or col.w <= 0 or col.h <= 0 then return end
    local player, bank = bagsShown()
    if #player == 0 and #bank == 0 then bagsOccupiedWidth = 0; return end
    local _, ph = physical()
    -- flagMin only REPORTS an unusably small result; it never clamps the scale back up. When the
    -- fit is what forced the scale down, a larger scale cannot fit by definition, so clamping would
    -- only push the bags across the home/game boundary -- which the "never janky" rule forbids.
    local function stack(frames, rightEdge, flagMin)
        local x, used, tooSmall = rightEdge, 0, false
        local natural = 0
        for _, f in ipairs(frames) do
            if mutable(f) then
                local name = call(f, 'GetName') or tostring(f)
                snapshotFrame(name, f)
                local env = envelopePx(f)
                local cur = call(f, 'GetScale') or 1
                if env and cur > 0 then
                    local w1, h1 = env.w / cur, env.h / cur
                    natural = natural + w1 + MARGIN
                    -- v2.3: the bags may be narrowed to widen a companion. The
                    -- target is an ABSOLUTE scale, capped by what the column can hold.
                    local fit = math.min(col.w / w1, col.h / h1)
                    local final = math.min(bagScaleTarget, fit)
                    if flagMin and final < MIN_BAG_SCALE then tooSmall = true end
                    local w, h = w1 * final, h1 * final
                    local left = clamp(x - w, MARGIN, math.max(MARGIN, col.right - w))
                    local top = clamp(col.bottom - h, col.y, math.max(col.y, col.bottom - h))
                    local dx = (env.root.x - env.x) / cur * final
                    local dy = (env.root.y - env.y) / cur * final
                    safe(function()
                        f:SetScale(final)
                        local q = (call(f, 'GetEffectiveScale') or final) * ph / 768
                        if not q or q <= 0 then error('scale') end
                        f:ClearAllPoints()
                        f:SetPoint('TOPLEFT', UIParent, 'BOTTOMLEFT',
                                   (left + dx) / q, (ph - (top + dy)) / q)
                    end)
                    bagLayer.lower(f)
                    x = left - MARGIN
                    used = used + w + MARGIN
                end
            end
        end
        return used, tooSmall, math.max(0, natural - MARGIN)
    end
    local previousWidth = bagsOccupiedWidth
    local used, tooSmall, natural = stack(player, col.right, true)
    bagsOccupiedWidth = math.max(0, used - MARGIN)
    bagsNaturalWidth = natural
    -- Bank containers never take the resident slot: they stack leftward from the player column.
    if #bank > 0 then stack(bank, col.right - bagsOccupiedWidth - MARGIN, false) end
    if tooSmall then log('bags', 'column forces scale below ' .. MIN_BAG_SCALE .. ' (usability fail)') end
    -- the companion lane is measured from the bags' ACTUAL width, so a bag-size change
    -- (combined <-> separate, bank opening) has to re-place the companions or they overlap.
    if math.abs(bagsOccupiedWidth - previousWidth) > 1 and not placing then
        placeAll('bag width changed')
    end
end

-- `atLogin` marks the residency attempts that belong to entering the world. By design,
-- if combat blocked THAT one, retry it exactly once at the next
-- PLAYER_REGEN_ENABLED. No other new residency trigger -- the residency list is otherwise
-- exhaustive, and re-opening from anywhere else is the Escape trap.
-- Exported so the ring's Inventory entry can OPEN the resident bags instead of toggling
-- them away (ConsolePort_Menu/Model/Buttons.lua:78-99 references MainMenuBarBackpackButton, which
-- is a toggle -- on the home screen that means the player's own inventory vanishes).
local openResidentBags
function S.OpenResidentBags(reason) return openResidentBags(reason or 'ring inventory entry') end

openResidentBags = function(reason, atLogin)
    if not ready() then return end
    if combat() then
        if atLogin then residencyBlocked = true end
        return
    end
    if baganatorUsable() then
        keepOpen.arm()
        openBaganator()
    elseif type(_G.OpenAllBags) == 'function' then
        safe(_G.OpenAllBags)
    end
    log('bags', 'residency resumed: ' .. tostring(reason))
end

-- ================================================ always-open bags (2.9.0) ====================
-- 2026-09-25: I wanted the bags open all the time, which is why they are sized the way they are.
-- This supersedes the earlier two-press rule ("two presses for now") for Baganator's
-- bags, which every flavor on the Thor runs (829). Blizzard's own bags keep the two-press rule.
--
-- 1. Escape skips them. Baganator puts every backpack view in UISpecialFrames
--    (ViewManagement/Initialize.lua:165), so CloseSpecialWindows hid the bags on Escape AND
--    counted that as "something closed", which ate the press (UIParentPanelManager.lua
--    CloseWindows -> CloseSpecialWindows). The same path put them away when the Shop ran
--    CloseAllWindows, and made a menu press in combat -- FFBinds hands the native TOGGLEGAMEMENU
--    back for the fight -- close the bags instead of opening the menu. While home is on the
--    backpack views are off that list; teardown puts them back.
-- 2. Anything else that hides them (the view's own X, a toggle, a view-type switch) is undone
--    on the next frame -- in combat, when it ends (Baganator's item buttons are protected).
function keepOpen.isView(name)
    return type(name) == 'string' and name:match('^Baganator_%a+ViewBackpackViewFrame') ~= nil
end

function keepOpen.onHide()
    if not ready() or not S.HomeEnabled() or anchoring or closingResident then return end
    if not baganatorUsable() then return end
    if combat() then keepOpen.pending = true return end
    if type(C_Timer) ~= 'table' then return end
    local gen = generation
    C_Timer.After(0, function()
        if gen ~= generation or not ready() or not S.HomeEnabled() then return end
        if combat() then keepOpen.pending = true return end
        safe(openResidentBags, 'kept open (the bags were hidden)')
    end)
end

function keepOpen.arm()
    local list = _G.UISpecialFrames
    if type(list) ~= 'table' then return end
    for i = #list, 1, -1 do
        local name = list[i]
        if keepOpen.isView(name) then
            table.remove(list, i)
            table.insert(keepOpen.names, 1, name)
            local f = _G[name]
            if f and not keepOpen.hooked[name] and type(f.HookScript) == 'function' then
                keepOpen.hooked[name] = true
                safe(function() f:HookScript('OnHide', keepOpen.onHide) end)
            end
        end
    end
end

function keepOpen.disarm()
    local list = _G.UISpecialFrames
    if type(list) == 'table' then
        for _, name in ipairs(keepOpen.names) do list[#list + 1] = name end
    end
    keepOpen.names = {}
    keepOpen.pending = false
end

function keepOpen.regen()
    if not keepOpen.pending or not ready() then return end
    keepOpen.pending = false
    safe(openResidentBags, 'combat ended (bags kept open)')
end
H.KeepOpen = keepOpen

-- v2.5.6: discover late frames on every flavor, including hidden cold-start views. The welcome
-- chooser owns its previews until it closes. UISpecialFrames and UIParent both contain multiple
-- view types/skins, so use the same selection rule for both rather than arbitrary child order.
local uiSpecialOnly = baganatorBackpack
baganatorBackpack = function()
    if soft.onboarding() then return nil end
    local best = uiSpecialOnly()
    local bestScore = best and bagViewScore(best, call(best, 'GetName'), BACKPACK_PREFIXES, 'bag')
    local kids = safe(function() return { UIParent:GetChildren() } end)
    if type(kids) == 'table' then
        for _, kid in ipairs(kids) do
            local name = call(kid, 'GetName')
            if type(name) == 'string' and _G[name] == kid then
                local score = bagViewScore(kid, name, BACKPACK_PREFIXES, 'bag')
                if score and (not bestScore or score > bestScore) then best, bestScore = kid, score end
            end
        end
    end
    return best
end
S.BaganatorBackpack = baganatorBackpack

function soft.recheck(reason)
    soft.pending = false
    if not usableDecided or usableValue then return end            -- re-armed, or already usable
    if usableWhy ~= soft.NOT_INIT and usableWhy ~= soft.ONBOARDING then return end   -- a hard "no"
    if not ready() or not S.HomeEnabled() then return end
    if combat() then                                                -- one event retry, not polling
        soft.pending, soft.waitingCombat = true, true
        return
    end
    local v, why = computeUsable()                                  -- a "not yet" re-schedules
    local rec = S.HomeRecord(true)
    if not v then
        usableWhy = why or usableWhy
        if rec then rec.baganator = 'unusable: ' .. tostring(usableWhy) end
        return
    end
    usableValue, usableWhy = true, nil
    log('baganator', 'usable after all (' .. tostring(reason) .. ') -> Baganator bags')
    if rec then rec.baganator = 'usable (late: ' .. tostring(reason) .. ')' end
    -- The first layout may have used Blizzard bags while discovery was pending. Re-negotiate its
    -- measured column once, including reclaiming the now-redundant native bag bar.
    checkBagCapacity('baganator became usable')
    safe(openResidentBags, 'baganator became usable')
    anchoring = true; safe(anchorBags); anchoring = false
    placeAll('baganator became usable')
end

function soft.schedule()
    if soft.pending or type(C_Timer) ~= 'table' then return end
    if soft.onboarding() then
        -- the player's own first-run choice: wait for the chooser to close, however long it takes
        local w = _G.Baganator_WelcomeFrame
        if w and not soft.welcomeHooked then
            soft.welcomeHooked = true
            safe(function()
                w:HookScript('OnHide', function()
                    C_Timer.After(1, function() safe(soft.recheck, 'first-run welcome closed') end)
                end)
            end)
        end
        return
    end
    soft.step = soft.step + 1
    local delay, step = soft.delays[soft.step], soft.step
    if not delay then return end                                    -- tries spent: the "no" stands
    soft.pending = true
    C_Timer.After(delay, function() safe(soft.recheck, 're-check ' .. step) end)
end

-- ================================================================================== hooks ======
local hookedShow = {}
-- The ring's Inventory entry TOGGLES the bags. ConsolePort's model row references
-- MainMenuBarBackpackButton (ConsolePort_Menu/Model/Buttons.lua:78-99), and a toggle is exactly
-- wrong for a home screen where the bags are furniture: picking "Inventory" from the ring made the
-- player's own inventory disappear off the screen it lives on. It must only ever OPEN them.
--
-- FFSpan cannot stop the toggle -- that button is protected and not FFSpan's -- so it lets it happen
-- and puts them straight back in the same frame. `openResidentBags` is a no-op when they are
-- already up, so choosing Inventory with the bags open costs nothing and there is no flicker: the
-- hook runs inside the same click, before the next frame is drawn.
local bagToggleHooked = {}

local function hookBagToggles()
    if type(hooksecurefunc) ~= 'function' then return end
    -- NOT CloseAllBags. Escape reaches the bags through CloseAllWindows -> CloseAllBags, and
    -- re-opening from there is the Escape trap the design rules out by name: the player
    -- would have no way to put the bags down at all. Only the TOGGLES are hooked, which is what
    -- the ring's Inventory entry actually calls.
    for _, fn in ipairs({'ToggleAllBags', 'ToggleBackpack'}) do
        if not bagToggleHooked[fn] and type(_G[fn]) == 'function' then
            bagToggleHooked[fn] = true
            pcall(hooksecurefunc, fn, function()
                if not ready() or not S.HomeEnabled() then return end
                if anchoring or closingResident then return end
                safe(openResidentBags, 'kept resident through ' .. fn)
                -- An explicit bag press permits one late discovery after timed retries are spent.
                -- Coalesce with pending work; never promote a hard dependency failure or steal
                -- onboarding previews. The toggle itself is not proof that a view was created.
                if usableDecided and not usableValue and not soft.pending
                    and (usableWhy == soft.NOT_INIT or usableWhy == soft.ONBOARDING)
                    and type(C_Timer) == 'table' then
                    soft.pending = true
                    C_Timer.After(0, function() safe(soft.recheck, 'explicit ' .. fn) end)
                end
            end)
            -- hooksecurefunc REPLACES the global with its wrapper, and the usable gate
            -- reads "ToggleAllBags is no longer the captured one" as "Baganator initialised".
            -- Re-baseline off FFSpan's wrapper so its own hook is never mistaken for Baganator's.
            if fn == 'ToggleAllBags' then origToggleAllBags = _G.ToggleAllBags end
        end
    end
end
H.HookBagToggles = hookBagToggles

local function hookShows()
    for name in pairs(MANAGED) do
        local f = _G[name]
        if f and not hookedShow[name] and not call(f, 'IsForbidden') then
            if safe(function()
                f:HookScript('OnShow', function()
                    shownSeq = shownSeq + 1
                    shownAt[name] = shownSeq
                    if not ready() then return end
                    placeAll('onshow:' .. name)
                    -- Root cause (GameMenuFrame): a skin can reshape the window on the NEXT
                    -- frame -- ConsolePort's menu does exactly that from RunNextFrame
                    -- (ConsolePort_Menu/View/Menu.lua:28-44) -- and the device dump caught the
                    -- game menu still sitting at the placement made before the skin ran. One
                    -- silent follow-up pass (no log line) re-fits it once the size has settled.
                    if C_Timer then
                        local gen = generation
                        safe(C_Timer.After, 0, function()
                            if gen == generation and ready() then placeAll(nil) end
                        end)
                    end
                end)
                -- when one of two companions closes, the survivor has to be re-placed
                -- -- Blizzard's own pass will have moved it back to a canvas-relative spot.
                f:HookScript('OnHide', function()
                    shownAt[name] = nil
                    if ready() then placeAll('onhide:' .. name) end
                end)
                return true
            end) then hookedShow[name] = true end
        end
    end
    -- Blizzard_PlayerSpellsFrame.lua:143-158 -- SetTab fires
    -- EventRegistry:TriggerEvent("PlayerSpellsFrame.TabSet", PlayerSpellsFrame, tabID), and its
    -- ordinary branch only calls SetTabMinimized. An ALREADY-MAXIMIZED spellbook <-> talents
    -- switch therefore never hides or re-shows the window, so nothing else would re-place it.
    local reg = _G.EventRegistry
    if reg and not hookedShow['@spellstab'] then
        if safe(function()
            reg:RegisterCallback('PlayerSpellsFrame.TabSet', function()
                if not ready() then return end
                -- The native tab switch can close bags without re-showing the containing window.
                -- Restore furniture for this explicit menu action, not from Hide/CloseAllBags (Escape).
                local gen = generation
                local function afterTab()
                    local f = _G.PlayerSpellsFrame
                    if gen ~= generation or not ready() or not call(f, 'IsShown') then return end
                    openResidentBags('spellbook/talents tab')
                    anchoring = true; safe(anchorBags); anchoring = false
                    placeAll('spells:tab')
                end
                if C_Timer then safe(C_Timer.After, 0, afterTab) else afterTab() end
            end, H)
            return true
        end) then hookedShow['@spellstab'] = true end
    end
    local menu = _G.GameMenuFrame
    if menu and not hookedShow['@gamemenu'] then
        if safe(function()
            menu:HookScript('OnHide', function() openResidentBags('game menu closed') end)
            return true
        end) then hookedShow['@gamemenu'] = true end
    end
    local map = _G.WorldMapFrame
    if map and not hookedShow['@map'] then
        if safe(function()
            for _, key in ipairs({'Maximize', 'Minimize'}) do
                if type(map[key]) == 'function' then
                    hooksecurefunc(map, key, function()
                        if not ready() then return end
                        placeAll('map:' .. key)
                        -- v2.6: the panel manager re-anchors the map AFTER this returns. On the
                        -- device the pass ran (log: map:Maximize) and the dump a minute later
                        -- still read TOP -> UIParent TOP, Blizzard's maximize anchor. Place once
                        -- more on the next frame, when that has happened.
                        local gen = generation
                        if C_Timer then
                            safe(C_Timer.After, 0, function()
                                if gen == generation and ready() then placeAll('map:' .. key .. ' settled') end
                            end)
                        end
                    end)
                end
            end
            map:HookScript('OnSizeChanged', function()
                if ready() and not placing then placeAll('map:size') end
            end)
            -- v2.6.4: read-only, see mapMax.resolve
            for _, fn in ipairs({'MaximizeUIPanel', 'RestoreUIPanelArea'}) do
                if type(_G[fn]) == 'function' then
                    hooksecurefunc(fn, function(frame) if frame == map then mapMax.resolve() end end)
                end
            end
            return true
        end) then hookedShow['@map'] = true end
    end
end

local function installHooks()
    if hooksDone then return end
    hooksDone = true
    -- Blizzard's panel manager. `FramePositionDelegate` is a LOCAL frame that Blizzard
    -- immediately marks forbidden (UIParentPanelManager.lua:247-249) -- `_G.FramePositionDelegate`
    -- is nil on a real client, so the old hook on it NEVER installed, and touching a forbidden
    -- frame would not be safe anyway. The supported dispatch is the GLOBAL function
    -- `UpdateUIPanelPositions(currentFrame)` (:1108-1111); it sets `panel-frame`/`panel-update` on
    -- the delegate, whose OnAttributeChanged (:206-230) calls the delegate's own
    -- UpdateUIPanelPositions (:527-632) SYNCHRONOUSLY inside that SetAttribute. So a secure
    -- post-hook here runs after ClearAllPoints/SetPoint (:690-691) and sees FINAL native
    -- positions -- verified against the live Blizzard source, not assumed.
    if type(_G.UpdateUIPanelPositions) == 'function' then
        local ok = safe(function()
            hooksecurefunc('UpdateUIPanelPositions', function()
                if ready() and not placing then placeAll('panelmanager') end
            end)
            return true
        end)
        panelHook = ok and 'global:UpdateUIPanelPositions' or 'hook failed'
    else
        panelHook = 'UpdateUIPanelPositions absent'
    end
    log('hooks', 'panel manager: ' .. panelHook)
    -- v2.4: the checkFit re-apply. Every Blizzard path funnels through this ONE global
    -- (UIParentPanelManager.lua:1062), so hooking it covers ShowUIPanel, the early scaling step,
    -- EvaluateAutoMinimize and UpdateScaleForFitForOpenPanels at once.
    local scaleFit = (type(_G.UIPanelUpdateScaleForFit) == 'function' and 'UIPanelUpdateScaleForFit')
        or (type(_G.UpdateScaleForFit) == 'function' and 'UpdateScaleForFit') or nil
    if scaleFit then
        local ok = safe(function() hooksecurefunc(scaleFit, onScaleForFit) return true end)
        scaleHook = ok and ('global:' .. scaleFit) or 'hook failed'
    else
        scaleHook = 'UIPanelUpdateScaleForFit absent'
    end
    log('hooks', 'checkFit rescale: ' .. scaleHook)
    if type(_G.UpdateContainerFrameAnchors) == 'function' then
        safe(hooksecurefunc, 'UpdateContainerFrameAnchors', function()
            if ready() and not anchoring then
                anchoring = true
                safe(anchorBags)
                anchoring = false
            end
        end)
    end
    hookShows()
    hookTransients()
    hookBagToggles()
end

-- ============================================================================ state machine ====
-- v2.2: nothing visible moves until the layout owner says its layout is LIVE.
-- This is the only place that flips `layoutConfirmed` to true, and the only place that starts the
-- first bag/window pass.
--
-- v2.2.1: residency is opened on the FIRST confirmation of a session only.
-- A ROUTINE re-confirmation -- FFScale re-acknowledging an unchanged layout -- must never reopen
-- bags the player closed, because that silently undoes the first Escape press and the
-- residency triggers are an exhaustive list (login, loading-screen end, game-menu close, bag key).
-- Later confirmations only re-fit bags that are already shown.
--
-- `slots` (when the layout owner acknowledged with a column) carries `source`. An estimated
-- source is an approved DEGRADED mode: accepted, but recorded and logged once, and reported in
-- the dump -- never passed off as measured home geometry.
local function onLayoutConfirmed(reason, slots)
    if not applied then return end
    layoutConfirmed = true
    layoutSource = (type(slots) == 'table' and slots.source) or 'ffspan-measured'
    local nowDegraded = (layoutSource ~= 'measured' and layoutSource ~= 'ffspan-measured')
    if nowDegraded ~= layoutDegraded then
        layoutDegraded = nowDegraded
        degradedLogged = false
    end
    if layoutDegraded and not degradedLogged then
        degradedLogged = true
        log('home', 'DEGRADED column: edges are estimated, not measured (source='
            .. tostring(layoutSource) .. ')')
    end
    if not residencyOpened then
        residencyOpened = true
        openResidentBags(reason, true)
    end
    if baganatorUsable() and lastColumnRequest == nil then
        -- the baseline: whatever the just-confirmed layout was built for. Without this the
        -- first bag event after login would look like a change and cause a needless save.
        local col0 = bagColumn()
        local want0 = col0 and bagColumnRequestPx(col0.h)
        if type(want0) == 'number' then lastColumnRequest = want0 end
    end
    anchoring = true; safe(anchorBags); anchoring = false
    placeAll(reason)
end

layoutOwner = function()
    local fs = _G.FFScale
    if type(fs) ~= 'table' then return nil end
    if type(safe(function() return fs.ApplyLayout end)) ~= 'function' then return nil end
    return fs
end

applyLayoutVia = function(fs, reason)
    local fn = safe(function() return fs.ApplyLayout end)
    -- FFScale's contract functions are plain (dot) functions, so they must NOT be passed `fs`
    if type(fn) ~= 'function' then return nil end
    local ok, detail = safe(fn, reason)
    -- the owner's own words for why it refused, so the chat line can say something useful
    if not ok and detail ~= nil then lastLayoutDetail = tostring(detail) end
    return ok, detail
end

-- FFScale.RegisterLayoutListener: the acknowledgement
-- that the home layout is verified live AND its column published.
local function registerLayoutListener()
    if layoutRegistered then return end
    local fs = _G.FFScale
    local reg = fs and safe(function() return fs.RegisterLayoutListener end)
    if type(reg) ~= 'function' then return end
    local ok = safe(reg, function(name, slots)
        if not applied then return end
        if slots then
            onLayoutConfirmed('layout confirmed: ' .. tostring(name), slots)
        else
            layoutConfirmed = false   -- off the home layout; place nothing from it
        end
    end)
    layoutRegistered = (ok ~= nil) or true
end

-- v2.2.1: the watchdog no longer FORGES confirmation. An owner that
-- refused an ambiguous layout, could not save, or could not measure is not an absent legacy
-- owner, and sixty seconds does not make any of those safe -- the old version called
-- onLayoutConfirmed() and left `layoutConfirmed = true` with no layout and no slots, which also
-- poisoned the dump. Now: confirmation stays FALSE, nothing is placed, the player gets ONE plain
-- chat line, and the layout owner is asked again on a BOUNDED ladder. If a retry confirms, the
-- listener does the placing exactly as it would have.
local confirmRetry, startConfirmWatchdog
confirmRetry = function(gen)
    if gen ~= generation or not applied or layoutConfirmed then return end
    confirmStep = confirmStep + 1
    if not confirmWarned then
        confirmWarned = true
        Print('home layout not confirmed (' .. tostring(lastLayoutDetail or 'no answer from the layout owner')
            .. '); bags and windows left where WoW put them.')
    end
    log('home', ('layout unconfirmed, retry %d/%d'):format(confirmStep, #RETRY_DELAYS))
    local fs = layoutOwner()
    if fs then applyLayoutVia(fs, 'ffspan:confirm-retry-' .. confirmStep) end
    if layoutConfirmed then
        log('home', 'layout confirmed on retry ' .. confirmStep)
        return
    end
    if confirmStep >= #RETRY_DELAYS then
        log('home', 'layout still unconfirmed after ' .. confirmStep .. ' retries; giving up')
        return
    end
    if C_Timer then
        safe(C_Timer.After, RETRY_DELAYS[confirmStep + 1], function() confirmRetry(gen) end)
    end
end

startConfirmWatchdog = function(gen)
    if not C_Timer then return end
    safe(C_Timer.After, RETRY_DELAYS[#RETRY_DELAYS], function() confirmRetry(gen) end)
end

local function activate(reason)
    if applied then return true end
    if not S.HomeEligible() then return false end
    local rec = S.HomeRecord(true)
    if not rec then return false end -- character not known yet; PLAYER_LOGIN retries
    if rec.enabled == false then return false end
    -- finish (or at least try to finish) an older pending restore BEFORE a new
    -- activation, so this session's snapshot is of the player's values, not of FFSpan's own.
    reconcileRestore()
    local sess = session(true) -- an interrupted prior session is REUSED, never overwritten
    if not sess then return false end
    local shared = sharedRecord(true)
    if not shared then return false end
    adoptLegacySession(sess)
    -- v2.2.1: make the ownership EXPLICIT. reconcileRestore() above may have been
    -- unable to finish an old frame restore (protected frames in combat, a frame not loaded yet).
    -- The new session now TAKES OVER that cleanup: it is reusing the very same session record, so
    -- it still holds the ORIGINAL snapshots and loses nothing -- and dropping `pendingRestore` /
    -- `restoring` here is what stops the old restore being replayed through a live session at the
    -- next PLAYER_REGEN_ENABLED, which is the off -> on -> regen hole a code review reproduced.
    if pendingRestore or sess.restoring then
        log('home', 'took over a pending frame restore from the previous session')
    end
    pendingRestore = nil
    sess.restoring = nil
    applied = true
    layoutConfirmed = false
    residencyBlocked = false
    residencyOpened = false
    layoutSource, layoutDegraded, degradedLogged = nil, false, false
    confirmStep, confirmWarned, lastLayoutDetail = 0, false, nil
    generation = generation + 1
    bagLayoutPending = false
    cpStep = 0
    -- v2.6.5: Baganator's minimum window width as an earlier session measured it (measureBagChrome)
    local learnedMinW = type(FFSpanDB) == 'table' and tonumber(FFSpanDB.bagWindowMinW)
    if learnedMinW and learnedMinW > 100 and learnedMinW < 1000 then bagHeaderMinW = learnedMinW end
    shared.owner = shared.owner or S.CharacterKey()
    shared.pending = nil
    snapshotCVars(shared)
    applyCVars()
    installHooks()
    hookShows()
    cpKick()
    -- v2.6.5: the real micro menu goes back into Blizzard's MicroMenu (FFSpan_Micro.lua) BEFORE
    -- the layout owner measures the bottom bar, so FFScale sizes the home slot to real buttons
    -- instead of the empty 1x1 ConsolePort's toolbar leaves behind.
    if S.MicroMenu then log('micro', tostring(select(2, safe(S.MicroMenu.Claim, reason)))) end
    -- The layout owner runs FIRST and answers back. FFScale only publishes FFScale.HomeSlots()
    -- after its layout is verified live and the real edges are measured, so waiting for that
    -- callback is what stops the bags being fitted to a provisional column.
    registerLayoutListener()
    S.NotifyHomeListeners(true, reason)
    local fs = layoutOwner()
    if S.HomeListenerCount() == 0 and fs then applyLayoutVia(fs, reason or 'home-on') end
    if not layoutRegistered then
        -- No layout owner, or one too old to acknowledge (no RegisterLayoutListener). There is
        -- nothing to wait for, so measure what is actually on screen and place now.
        onLayoutConfirmed(fs and 'layout owner does not acknowledge' or 'no layout owner')
    elseif C_Timer then
        startConfirmWatchdog(generation)
    end
    log('home', 'enabled (' .. tostring(reason) .. ')')
    return true
end

-- v2.2: the geometry moved under a LIVE session. Drop the confirmation, ask the
-- layout owner again, and only re-place once it answers.
local function invalidate(reason)
    if not applied then return end
    layoutConfirmed = false
    bagsOccupiedWidth = 0
    bagScaleTarget, bagsNaturalWidth = 1, 0
    bagWidthCap = nil
    lastColumnRequest, capacityPending, deferredCapacity = nil, false, nil
    local fs = layoutOwner()
    if fs then applyLayoutVia(fs, 'ffspan:' .. tostring(reason))
    else onLayoutConfirmed('re-measured (' .. tostring(reason) .. ')') end
end

-- Undoes the whole session. Safe to call at ANY geometry: this is also the stock-1920 cleanup path.
local function teardown(reason, sess)
    generation = generation + 1 -- invalidates every queued callback
    bagLayoutPending = false
    applied = false
    layoutConfirmed = false
    layoutSource, layoutDegraded, degradedLogged = nil, false, false
    residencyOpened = false
    residencyBlocked = false
    confirmStep, confirmWarned = 0, false
    deferred = {}
    placedNames, scaleRefused, scaleOwners, positionOwners = {}, {}, {}, {}
    bagsOccupiedWidth = 0
    bagScaleTarget, bagsNaturalWidth = 1, 0
    bagWidthCap = nil
    lastColumnRequest, capacityPending, deferredCapacity = nil, false, nil
    local framesDone = true
    if sess then
        adoptLegacySession(sess)
        sess.restoring = true      -- journal it BEFORE trying, so a crash mid-restore still retries
        pendingRestore = restoreFrames(sess)
        if pendingRestore then
            framesDone = false
            log('home', 'restore deferred (protected or not loaded) until combat ends / next login')
        end
    end
    local shared = sharedRecord(false)
    if shared then shared.pending = true end
    local sharedDone = restoreShared()
    -- combat refuses the dispatching restore; reconcileRestore retries it at PLAYER_REGEN_ENABLED
    chatWidth.restore(reason)
    mapMax.release()
    bagLayer.restore()
    keepOpen.disarm()   -- 2.9.0: Escape closes the bags again with home off
    -- ConsolePort's own props go back and it re-takes the buttons itself (FFSpan_Micro.lua);
    -- a no-op when nothing was claimed, so the stock-1920 cleanup path is unaffected
    if S.MicroMenu and S.MicroMenu.state and (S.MicroMenu.state.claimed or S.MicroMenu.state.orig) then
        log('micro', tostring(select(2, safe(S.MicroMenu.Release, reason))))
    end
    local rec = S.HomeRecord(false)
    -- the session record is the ONLY copy of the originals, so it is cleared only once
    -- the restore is CONFIRMED complete -- never unconditionally.
    if rec and framesDone then rec.session = nil end
    if not (framesDone and sharedDone) then
        log('home', 'restore journal kept open (frames=' .. tostring(framesDone)
            .. ', shared=' .. tostring(sharedDone) .. ')')
    end
    log('home', 'disabled (' .. tostring(reason) .. ')')
    S.NotifyHomeListeners(false, reason)
    local fs = layoutOwner()
    if S.HomeListenerCount() == 0 and fs then applyLayoutVia(fs, 'home-off') end
end

local function deactivate(reason)
    local sess = session(false)
    teardown(reason, sess)
end
H.Activate, H.Deactivate = activate, deactivate

-- Runs at EVERY geometry. A home session left behind by a 4400 launch is undone on the next login
-- at 1920 or 3160 -- it must not sit behind HomeEligible.
local function cleanupStaleSession()
    if S.HomeEligible() then return false end
    local sess = session(false)
    if not sess then
        -- v2.2: the shared journal is ACCOUNT-wide, so a stock login on a DIFFERENT
        -- character has no session of its own and must still finish the outstanding restore.
        local shared = sharedRecord(false)
        if shared then
            restoreShared()
            log('home', 'finished an account-wide restore left by another character/session')
            return true
        end
        return false
    end
    teardown('stale session at ' .. string.format('%dx%d', physical()), sess)
    return true
end

local function resolve(reason)
    if cleanupStaleSession() then return end
    if not S.HomeEligible() then
        if applied then deactivate('geometry left home') end
        return
    end
    local rec = S.HomeRecord(true)
    if rec and rec.enabled == false then
        if applied then deactivate('user off') else S.NotifyHomeListeners(false, reason) end
        return
    end
    activate(reason)
end
H.Resolve = resolve

-- ================================================================================= events ======
for _, ev in ipairs({'PLAYER_LOGIN', 'PLAYER_ENTERING_WORLD', 'ADDON_LOADED',
                     'LOADING_SCREEN_DISABLED', 'DISPLAY_SIZE_CHANGED', 'UI_SCALE_CHANGED',
                     'PLAYER_REGEN_ENABLED', 'EDIT_MODE_LAYOUTS_UPDATED',
                     'BAG_CONTAINER_UPDATE', 'PLAYER_LOGOUT'}) do
    H:RegisterEvent(ev)
end
H:SetScript('OnEvent', function(_, event, arg1)
    if event == 'PLAYER_LOGOUT' then
        -- v2.6: data only (no dispatch, no layout, safe in combat). Glassy.lua is saved right
        -- after this, and single-screen play must never inherit the dual-screen chat width.
        chatWidth.restore('logout', false)
    elseif event == 'PLAYER_LOGIN' then
        reconcileRestore()   -- any character, any geometry, finishes the journal
        resolve('login')
    elseif event == 'PLAYER_ENTERING_WORLD' then
        resolve('entering world')
        if ready() then openResidentBags('entering world', true) end
    elseif event == 'LOADING_SCREEN_DISABLED' then
        if ready() then openResidentBags('loading screen ended') end
    elseif event == 'BAG_CONTAINER_UPDATE' then
        -- the ONE event that means a bag was equipped, removed or upgraded
        checkBagCapacity('BAG_CONTAINER_UPDATE')
    elseif event == 'EDIT_MODE_LAYOUTS_UPDATED' then
        -- The Edit Mode layout just changed, so the minimap and the bottom bar -- i.e. the whole
        -- home column -- moved. With a layout owner that acknowledges (FFScale 1.7+) the callback
        -- is the authority and this is only a safety net; with an older or absent owner this IS
        -- the confirmation, and it is also what covers a layout deferred to PLAYER_REGEN_ENABLED,
        -- since the two addons' regen handlers fire in an order neither of them owns.
        if applied and not combat() then
            if layoutRegistered then
                if ready() then
                    anchoring = true; safe(anchorBags); anchoring = false
                    placeAll('edit mode layout changed')
                end
            else
                onLayoutConfirmed('edit mode layout changed')  -- no acknowledging owner: this IS it
            end
        end
    elseif event == 'ADDON_LOADED' then
        -- the ONLY thing that re-opens the usable question: Baganator or Syndicator
        -- arriving late. It re-arms the decision; it never applies a layout by itself.
        rearmUsable(arg1)
        registerLayoutListener()
        reconcileRestore()   -- a late ConsolePort/frame can finish an outstanding restore
        if applied then
            hookShows(); hookTransients(); hookBagToggles(); cpKick()
            -- a claim that found no ConsolePort toolbar yet gets another chance here
            if S.MicroMenu and S.MicroMenu.state and not S.MicroMenu.state.claimed then
                safe(S.MicroMenu.Claim, 'addon loaded')
            end
            if ready() then placeAll('addon loaded') end
        end
    elseif event == 'DISPLAY_SIZE_CHANGED' or event == 'UI_SCALE_CHANGED' then
        -- review M6: a live session must be INVALIDATED and redone, not silently kept -- resolve()
        -- returns early while `applied`, so on its own it never re-fits anything.
        if applied and S.HomeEligible() then invalidate(event) end
        resolve(event)
    elseif event == 'PLAYER_REGEN_ENABLED' then
        if soft.waitingCombat then
            soft.waitingCombat, soft.pending = nil, false
            safe(soft.recheck, 'combat ended')   -- recheck itself rejects off-home/unready state
        end
        -- v2.2.1 (re-check M4): the frame restore and the session record belong to a session that
        -- is OVER. While `applied` this pass must touch neither -- the live session took them over
        -- in activate(). Previously this ran before any applied check and could replay an old
        -- restore, and clear rec.session, straight through a live session.
        if not applied then
            if pendingRestore then
                local left = restoreFrames(pendingRestore)
                pendingRestore = left
                if not left then
                    log('home', 'deferred restore completed')
                    local rec = S.HomeRecord(false)
                    if rec and rec.session and rec.session.restoring then rec.session = nil end
                end
            end
            reconcileRestore()   -- the journal retries here too
            return
        end
        if deferredCapacity then
            deferredCapacity, capacityPending = nil, false
            checkBagCapacity('combat ended')
        end
        if residencyBlocked and ready() then
            -- by design: exactly one retry of the residency
            -- that combat blocked at login. The flag is cleared first, so it is never a loop.
            residencyBlocked = false
            openResidentBags('combat ended (login residency retry)')
        end
        keepOpen.regen()
        -- v2.2.1 (re-check M6): the rest of this pass MOVES things, so it waits for confirmation
        -- like every other placement path. An unconfirmed session just leaves the UI alone.
        if not ready() then return end
        -- the coexistence decision is re-made afresh by the
        -- placement pass below, out of combat, where the genuine loser can be hidden the native
        -- way. Nothing is carried over from combat -- which is what cancels a displacement whose
        -- newer window has since closed, and what lets the newer one finally take the lane.
        local pending = deferred
        deferred = {}
        for name in pairs(pending) do
            local f = _G[name]
            if f and call(f, 'IsVisible') then placeOne(name) end -- never re-open a closed window
        end
        anchoring = true; safe(anchorBags); anchoring = false
        placeAll('combat ended')
    end
end)

-- ================================================================================== slash ======
local function statusLine()
    local w, h = physical()
    local rec = S.HomeRecord(false)
    local sess = rec and rec.session
    local cp = 0
    for _, st in pairs((sess and sess.consolePort) or {}) do
        if type(st) == 'table' and st.done then cp = cp + 1 end
    end
    local micro = S.MicroMenu and safe(S.MicroMenu.Status)
    return string.format(
        'home: canvas %dx%d, eligible=%s, enabled=%s, applied=%s, session=%s, cursor exclusions=%d, micro menu=%s',
        w, h,
        S.HomeEligible() and 'yes' or 'no',
        S.HomeEnabled() and 'yes' or 'no',
        applied and 'yes' or 'no',
        sess and 'open' or 'none', cp,
        type(micro) == 'table' and tostring(micro.owner) or 'n/a')
end
H.StatusLine = statusLine

local prior = SlashCmdList['FFSPAN']
SlashCmdList['FFSPAN'] = function(message)
    local arg = safe(function()
        if type(message) ~= 'string' then return nil end
        return message:match('^%s*home%s*(.-)%s*$')
    end)
    if not arg then
        if prior then prior(message) end
        return
    end
    arg = arg:lower()
    if arg == 'on' then
        local rec = S.HomeRecord(true)
        if rec then rec.enabled = true end
        if not S.HomeEligible() then
            Print('home enabled for this character, but this canvas is not 4400x1080.')
        elseif activate('slash on') then
            Print('home ON. ' .. statusLine())
        else
            Print('home could not be enabled. ' .. statusLine())
        end
    elseif arg == 'off' then
        local rec = S.HomeRecord(true)
        if rec then rec.enabled = false end
        deactivate('slash off')
        Print('home OFF, previous state restored. ' .. statusLine())
    elseif arg == '' or arg == 'status' then
        Print(statusLine())
    else
        Print('usage: /ffspan home [on|off|status]')
    end
end
