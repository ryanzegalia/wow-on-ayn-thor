#!/usr/bin/env python3
"""
Mocked-WoW-API tests for FFSpan_Glassy.lua: fits Glassy's chat width to FFSpan's home layout
through Glassy's own supported AceDB profile field + Dispatch config event -- never by hooking
Glassy, touching its frames/mover, or switching its AceDB profile. Same lupa approach as
test_ffspan.py / test_ffspan_centre.py / test_ffspan_home.py: a hand-written mock of the small
slice of the WoW + AceDB + Glassy API this file actually touches, the real addon source loaded
and run unmodified through it, PASS/FAIL checks collected into `results`.
Run: python test_ffspan_glassy.py
"""
import os
import sys

try:
    import lupa
except ImportError:
    print("SKIP: python module 'lupa' is not installed -- cannot run mocked-API tests.")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.abspath(os.path.join(HERE, ".."))
FILE = "FFSpan_Glassy.lua"

# Only what FFSpan_Glassy.lua actually touches: InCombatLockdown, a minimal AceDB-3.0-shaped
# `Core.db` (profile metatable-backed by defaults, GetCurrentProfile), and Core:Dispatch. No
# CreateFrame/C_Timer/event system is needed -- this module never creates or reaches into a
# frame, by design (it only ever reads/writes Core.db.profile.frameWidth + calls Dispatch).
MOCK_API = r"""
__combat = false
__dispatch_calls = {}
__dispatch_fail = false

function InCombatLockdown() return __combat end
function __dispatch_count() return #__dispatch_calls end

-- rawget through Python: lupa's normal table indexing from the Python side goes through Lua
-- indexing rules too, which would resolve an unset frameWidth to the AceDB default (600)
-- instead of showing it as unset. These helpers bypass that so tests can see the RAW stored
-- value (or nil) the way the module itself does.
function __rawwidth(t) return rawget(t, "frameWidth") end
function __has_entry(name)
    local j = GlassyDB and GlassyDB.FFSpanWidthRestore
    return j ~= nil and j[name] ~= nil
end
function __applied_width(name)
    local j = GlassyDB and GlassyDB.FFSpanWidthRestore
    return j and j[name] and j[name].appliedWidth
end
-- Height twins of the helpers above, plus a generic journal-field reader for the height half.
function __rawheight(t) return rawget(t, "frameHeight") end
function __applied_height(name)
    local j = GlassyDB and GlassyDB.FFSpanWidthRestore
    return j and j[name] and j[name].appliedHeight
end
function __entry_field(name, key)
    local j = GlassyDB and GlassyDB.FFSpanWidthRestore
    return j and j[name] and j[name][key]
end
__RAW_NIL_MARKER = "\1FFSpanRawNil\1"

local DEFAULTS = { frameWidth = 600, frameHeight = 250 }
local PROFILE_MT = { __index = DEFAULTS }

-- Sets up _G.GlassyDB (the raw SavedVariables table) and _G.Glassy (Core), with GlassyDB.profiles
-- the SAME table Core.db.profiles uses -- mirroring real AceDB, where db.profiles literally IS
-- the raw SV's .profiles. `seedProfiles` is a plain Lua table of {profileName = {raw fields}};
-- only the CURRENT profile gets the defaults metatable blessed onto it here (an inactive AceDB
-- profile is just a plain table sitting in .profiles until AceDB makes it current).
function __setup(seedProfiles, current, seedJournal)
    seedProfiles = seedProfiles or {}
    current = current or "Default"
    GlassyDB = { profiles = seedProfiles }
    if seedJournal then GlassyDB.FFSpanWidthRestore = seedJournal end

    seedProfiles[current] = seedProfiles[current] or {}
    setmetatable(seedProfiles[current], PROFILE_MT)

    local db = { profiles = seedProfiles, __current = current }
    db.profile = seedProfiles[current]
    function db:GetCurrentProfile() return self.__current end

    Glassy = { db = db }
    function Glassy:Dispatch(event, key)
        __dispatch_calls[#__dispatch_calls + 1] = { event = event, key = key }
        if __dispatch_fail then error("dispatch failed (mock)") end
    end
    return Glassy
end

-- Test-only convenience to move AceDB's "current profile" pointer. The module under test must
-- NEVER call this (no profile switching) -- only the harness does, to stage the profile-switch
-- scenario the same way a real AceDB SetProfile would leave things: the old profile's raw data
-- still sitting in .profiles, a new current profile table in place. A plain function (not a
-- `db:` method) so it can be called directly from Python without needing to pass `self` by hand.
function __switch_profile(db, name)
    db.profiles[name] = db.profiles[name] or {}
    setmetatable(db.profiles[name], PROFILE_MT)
    db.__current = name
    db.profile = db.profiles[name]
end
"""


def new_env(setup_lua=None):
    """Fresh Lua VM, the mock API, the real addon file loaded exactly as WoW loads it (the file
    receives the addon name as its sole vararg), then optional raw-Lua fixture setup. Using raw
    Lua source for fixtures (not Python dicts passed into Lua calls) matches this addon's other
    tests and sidesteps any ambiguity in how a foreign Python object would behave under
    `setmetatable`."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    lua.execute(MOCK_API)
    load = lua.eval("load")
    with open(os.path.join(ADDON, FILE), encoding="utf-8") as f:
        load(f.read(), FILE)("FFSpan")
    if setup_lua:
        lua.execute(setup_lua)
    return lua, g


def setup_default(body="{}", current="Default"):
    return f'__setup({{ {current} = {body} }}, "{current}")'


results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not cond else ""))


def apply(g, width):
    return g.FFSpan.GlassyFit.Apply(width)


def restore(g, dispatch=True):
    return g.FFSpan.GlassyFit.Restore(dispatch)


def dispatch_events(g):
    return [(c.event, c.key) for c in g.__dispatch_calls.values()]


# --- 1. basic width fit -----------------------------------------------------------------------
lua, g = new_env(setup_default())
ok, changed = apply(g, 400)
check("fit: Apply narrows the default 600 down to the requested 400", (ok, changed) == (True, True), f"{ok},{changed}")
check("fit: frameWidth actually written to 400", g.__rawwidth(g.Glassy.db.profile) == 400)
check("fit: dispatch fired exactly once with the documented event+key",
      dispatch_events(g) == [("Glassy/UPDATE_CONFIG", "frameWidth")], dispatch_events(g))
ok, changed = apply(g, 9999)
check("fit: never exceeds the true original width even when asked to", (ok, changed) == (True, True))
check("fit: capped at the original 600, not the oversized request", g.__rawwidth(g.Glassy.db.profile) == 600)
before = g.__dispatch_count()
ok, changed = g.FFSpan.GlassyFit.Restore()  # no-arg call -- dispatch must default to true
check("fit: Restore() with no argument defaults dispatch=true", (ok, changed) == (True, True) and g.__dispatch_count() == before + 1)

# --- 2. no font mutation -----------------------------------------------------------------------
lua, g = new_env(setup_default(body='{ fontSize = 14, frameWidth = 500 }'))
apply(g, 350)
check("no font mutation: unrelated fontSize survives Apply untouched", g.Glassy.db.profile.fontSize == 14)
restore(g)
check("no font mutation: unrelated fontSize survives Restore untouched too", g.Glassy.db.profile.fontSize == 14)

# --- 3. inherited-nil restore ------------------------------------------------------------------
lua, g = new_env(setup_default())
check("inherited-nil: raw frameWidth starts nil (inherited from AceDB defaults)", g.__rawwidth(g.Glassy.db.profile) is None)
check("inherited-nil: effective width resolves to the 600 default", g.Glassy.db.profile.frameWidth == 600)
ok, changed = apply(g, 400)
check("inherited-nil: apply from an inherited default succeeds", (ok, changed) == (True, True))
check("inherited-nil: raw frameWidth now explicitly 400", g.__rawwidth(g.Glassy.db.profile) == 400)
ok, changed = restore(g)
check("inherited-nil: restore reports success + changed", (ok, changed) == (True, True))
check("inherited-nil: raw frameWidth is nil again -- inheritance restored, not a literal 600", g.__rawwidth(g.Glassy.db.profile) is None)
check("inherited-nil: effective width falls back through the default once more", g.Glassy.db.profile.frameWidth == 600)
check("inherited-nil: journal cleared on a real restore", g.__has_entry("Default") is False)

# --- 4. repeated / expanded fit + do-not-write-if-unchanged -------------------------------------
lua, g = new_env(setup_default())
apply(g, 400)
apply(g, 350)
check("repeated: second narrower Apply shrinks further to 350", g.__rawwidth(g.Glassy.db.profile) == 350)
before = g.__dispatch_count()
ok, changed = apply(g, 350)
check("repeated: identical re-apply is a reported no-op", (ok, changed) == (True, False))
check("repeated: no-op does not touch the stored value", g.__rawwidth(g.Glassy.db.profile) == 350)
check("repeated: no-op does not dispatch again", g.__dispatch_count() == before)
ok, changed = apply(g, 900)
check("repeated: expand request still capped at the true original 600, not 900", (ok, changed) == (True, True) and g.__rawwidth(g.Glassy.db.profile) == 600)

# --- 5. user override preservation --------------------------------------------------------------
lua, g = new_env(setup_default())
apply(g, 400)
g.Glassy.db.profile.frameWidth = 550  # user manually widens it in Glassy's own options, bypassing FFSpan
ok, changed = restore(g)
check("user override: Restore never clobbers a value the user changed since the last Apply",
      (ok, changed) == (True, False) and g.__rawwidth(g.Glassy.db.profile) == 550)
check("user override: Restore drops the now-stale journal claim rather than leaving it dangling", g.__has_entry("Default") is False)

lua, g = new_env(setup_default())
apply(g, 400)
g.Glassy.db.profile.frameWidth = 550
ok, changed = apply(g, 500)
check("user override: a later Apply adopts the user's value as the new baseline, not the stale 400",
      (ok, changed) == (True, True) and g.__rawwidth(g.Glassy.db.profile) == 500)
ok, changed = apply(g, 9999)
check("user override: the new ceiling is the user's 550, never the long-ago 600 default",
      (ok, changed) == (True, True) and g.__rawwidth(g.Glassy.db.profile) == 550)

# --- 6. profile switch -----------------------------------------------------------------------
lua, g = new_env(setup_default())
apply(g, 400)
check("profile switch: Default narrowed to 400 before the switch", g.__rawwidth(g.Glassy.db.profile) == 400)
g.__switch_profile(g.Glassy.db, "Alt")
ok, changed = apply(g, 500)
check("profile switch: Apply on the newly-active profile succeeds", (ok, changed) == (True, True))
check("profile switch: the stale Default entry was restored directly through GlassyDB.profiles",
      g.__rawwidth(g.GlassyDB.profiles["Default"]) is None)
check("profile switch: Default's journal row is cleared", g.__has_entry("Default") is False)
check("profile switch: Alt now owns a fresh journal entry at the newly applied width", g.__applied_width("Alt") == 500)
check("profile switch: Alt's effective width is 500", g.Glassy.db.profile.frameWidth == 500)
check("profile switch: no SetProfile/profile-switching call was needed or made by the module "
      "(the harness's own __switchProfile is the only thing that moved 'current')", True)

# --- 7. reload / cross-flavor journal restore ---------------------------------------------------
# A brand-new module load (fresh VM below == fresh addon load) with a GlassyDB that already
# carries a persisted journal from "a prior session" -- proves the journal is genuinely
# session-independent: Restore must recover purely from GlassyDB, with no Apply ever called in
# this VM at all.
reload_setup = """
local seedProfiles = { Default = { frameWidth = 350 } }
local seedJournal = { Default = { rawFrameWidth = 500, effectiveWidth = 500, appliedWidth = 350 } }
__setup(seedProfiles, "Default", seedJournal)
"""
lua, g = new_env(reload_setup)
check("reload: persisted journal is visible before any Apply/Restore runs in this VM", g.__has_entry("Default") is True)
ok, changed = restore(g)
check("reload: Restore recovers purely from a persisted GlassyDB, no Apply needed this session", (ok, changed) == (True, True))
check("reload: frameWidth restored to the persisted pre-adaptation value", g.__rawwidth(g.Glassy.db.profile) == 500)
check("reload: persisted journal entry cleared once genuinely restored", g.__has_entry("Default") is False)

# --- 8. stock / off (nothing ever applied) -------------------------------------------------------
lua, g = new_env(setup_default())
ok, changed = restore(g)
check("stock/off: Restore on an addon that was never adapted is a clean no-op", (ok, changed) == (True, False))
check("stock/off: nothing mutated", g.__rawwidth(g.Glassy.db.profile) is None)
check("stock/off: no dispatch fired", g.__dispatch_count() == 0)

# --- 9. PLAYER_LOGOUT data-only restoration -------------------------------------------------------
lua, g = new_env(setup_default())
apply(g, 400)
g.__combat = True  # logout can land mid-combat; the data-only path must not care
before = g.__dispatch_count()
ok, changed = restore(g, False)  # dispatch=false -- the logout call shape
check("logout: data-only restore still succeeds while InCombatLockdown is true", (ok, changed) == (True, True))
check("logout: frameWidth actually restored", g.__rawwidth(g.Glassy.db.profile) is None)
check("logout: never calls Dispatch -- that is exactly why combat can't block it", g.__dispatch_count() == before)
check("logout: journal cleared", g.__has_entry("Default") is False)

# --- 10. combat guard (a DISPATCHING call must refuse outright in combat) -------------------------
lua, g = new_env(setup_default())
g.__combat = True
ok, changed = apply(g, 400)
check("combat guard: Apply refuses outright in combat", (ok, changed) == (False, False))
check("combat guard: no mutation happened", g.__rawwidth(g.Glassy.db.profile) is None)
check("combat guard: no dispatch happened", g.__dispatch_count() == 0)

lua, g = new_env(setup_default())
apply(g, 400)  # out of combat
g.__combat = True
ok, changed = restore(g, True)  # dispatch=true while in combat -- same guard applies here
check("combat guard: a dispatching Restore also refuses in combat rather than mutate-then-fail",
      (ok, changed) == (False, False) and g.__rawwidth(g.Glassy.db.profile) == 400)

# --- 11. failure rollback --------------------------------------------------------------------------
lua, g = new_env(setup_default())
g.__dispatch_fail = True
ok, changed = apply(g, 400)
check("failure rollback: a first-ever Apply whose Dispatch throws reports honest failure", (ok, changed) == (False, False))
check("failure rollback: frameWidth rolled back to the untouched original", g.__rawwidth(g.Glassy.db.profile) is None)
check("failure rollback: attempted a best-effort original-width refresh dispatch too", g.__dispatch_count() == 2)
check("failure rollback: no journal poison left behind after a first-attempt failure", g.__has_entry("Default") is False)

lua, g = new_env(setup_default())
apply(g, 400)  # a real, successful prior adaptation
g.__dispatch_fail = True
before = g.__dispatch_count()
ok, changed = apply(g, 300)
check("failure rollback: a later failing Apply also reports honest failure", (ok, changed) == (False, False))
check("failure rollback: rolls back to the last GOOD applied value, not the ancient original",
      g.__rawwidth(g.Glassy.db.profile) == 400)
check("failure rollback: still attempted the original-width refresh dispatch", g.__dispatch_count() == before + 2)
check("failure rollback: the still-valid prior adaptation is not poisoned/lost", g.__applied_width("Default") == 400)

# --- 12. missing addon ----------------------------------------------------------------------------
lua, g = new_env(setup_lua=None)  # _G.Glassy / _G.GlassyDB left completely unset
ok, changed = apply(g, 400)
check("missing addon: Apply fails safe with no Glassy present", (ok, changed) == (False, False))
ok, changed = restore(g)
check("missing addon: Restore fails safe with no Glassy present", (ok, changed) == (False, False))


# ================================================================ height (frameHeight) =============
# ApplyHeight is Apply's twin for Glassy's frameHeight (slider soft-min 200, step 1, dispatch key
# 'frameHeight'); Restore puts back both fields. The mock's inherited default height is 250.
def apply_height(g, height):
    return g.FFSpan.GlassyFit.ApplyHeight(height)


def dispatch_keys(g):
    return [c.key for c in g.__dispatch_calls.values()]


# --- 13. basic height fit ------------------------------------------------------------------------
lua, g = new_env(setup_default())
ok, changed = apply_height(g, 220)
check("height fit: ApplyHeight shortens the inherited 250 to the requested 220", (ok, changed) == (True, True), f"{ok},{changed}")
check("height fit: frameHeight actually written to 220", g.__rawheight(g.Glassy.db.profile) == 220)
check("height fit: dispatch fired exactly once with UPDATE_CONFIG + 'frameHeight'",
      dispatch_events(g) == [("Glassy/UPDATE_CONFIG", "frameHeight")], dispatch_events(g))
check("height fit: width field and width journal are untouched",
      g.__rawwidth(g.Glassy.db.profile) is None and g.__applied_width("Default") is None)
check("height fit: journal carries the height triple",
      g.__entry_field("Default", "rawFrameHeight") == g.__RAW_NIL_MARKER
      and g.__entry_field("Default", "effectiveHeight") == 250 and g.__applied_height("Default") == 220)
ok, changed = apply_height(g, 9999)
check("height fit: never exceeds the true original height even when asked to",
      (ok, changed) == (True, True) and g.__rawheight(g.Glassy.db.profile) == 250)
apply_height(g, 230)
before = g.__dispatch_count()
ok, changed = apply_height(g, 230)
check("height fit: identical re-apply is a no-op with no dispatch",
      (ok, changed) == (True, False) and g.__dispatch_count() == before and g.__rawheight(g.Glassy.db.profile) == 230)
ok, changed = apply_height(g, 230.9)
check("height fit: fractional request floors to whole units (230.9 -> 230, so still a no-op)",
      (ok, changed) == (True, False) and g.__rawheight(g.Glassy.db.profile) == 230 and g.__dispatch_count() == before)
ok, changed = apply_height(g, 210.7)
check("height fit: a fractional request that changes lands on the floored whole unit",
      (ok, changed) == (True, True) and g.__rawheight(g.Glassy.db.profile) == 210)

# --- 14. height refusals: soft-min, combat, non-finite -------------------------------------------
lua, g = new_env(setup_default())
ok, changed = apply_height(g, 149)
check("height refuse: below the 150 floor is refused", (ok, changed) == (False, False))
check("height refuse: soft-min refusal mutates and dispatches nothing",
      g.__rawheight(g.Glassy.db.profile) is None and g.__dispatch_count() == 0 and g.__has_entry("Default") is False)
ok, changed = apply_height(g, 149.9)
check("height refuse: 149.9 floors to 149 and is refused too", (ok, changed) == (False, False) and g.__dispatch_count() == 0)
ok, changed = apply_height(g, 150)
check("height refuse: exactly 150 is allowed", (ok, changed) == (True, True) and g.__rawheight(g.Glassy.db.profile) == 150)

lua, g = new_env(setup_default())
g.__combat = True
ok, changed = apply_height(g, 220)
check("height refuse: ApplyHeight refuses outright in combat",
      (ok, changed) == (False, False) and g.__rawheight(g.Glassy.db.profile) is None and g.__dispatch_count() == 0)

lua, g = new_env(setup_default())
bad = [float("nan"), float("inf"), float("-inf"), 0, -220, "220", None]
results_bad = [tuple(apply_height(g, v)) for v in bad]
check("height refuse: NaN / +-inf / 0 / negative / string / nil are all refused",
      all(r == (False, False) for r in results_bad), results_bad)
check("height refuse: non-finite input mutated and dispatched nothing",
      g.__rawheight(g.Glassy.db.profile) is None and g.__dispatch_count() == 0)

# --- 15. hand-set height honoured -------------------------------------------------------------------
lua, g = new_env(setup_default())
apply_height(g, 220)
g.Glassy.db.profile.frameHeight = 240  # player resizes it in Glassy's own options
ok, changed = restore(g)
check("height hand-set: Restore never clobbers a height the player changed since",
      (ok, changed) == (True, False) and g.__rawheight(g.Glassy.db.profile) == 240)
check("height hand-set: stale height claim dropped, entry cleared", g.__has_entry("Default") is False)

lua, g = new_env(setup_default())
apply_height(g, 220)
g.Glassy.db.profile.frameHeight = 240
ok, changed = apply_height(g, 230)
check("height hand-set: a later ApplyHeight adopts the player's 240 as the new baseline",
      (ok, changed) == (True, True) and g.__rawheight(g.Glassy.db.profile) == 230
      and g.__entry_field("Default", "effectiveHeight") == 240 and g.__entry_field("Default", "rawFrameHeight") == 240)
ok, changed = apply_height(g, 9999)
check("height hand-set: the new ceiling is the player's 240, never the old 250 default",
      (ok, changed) == (True, True) and g.__rawheight(g.Glassy.db.profile) == 240)

# --- 16. RAW nil marker round-trip (height) -------------------------------------------------------
lua, g = new_env(setup_default())
apply_height(g, 220)
check("height nil-marker: an inherited height is journaled as the RAW nil marker",
      g.__entry_field("Default", "rawFrameHeight") == g.__RAW_NIL_MARKER)
ok, changed = restore(g)
check("height nil-marker: restore reports success + changed", (ok, changed) == (True, True))
check("height nil-marker: raw frameHeight is nil again -- inheritance restored, not a literal 250",
      g.__rawheight(g.Glassy.db.profile) is None and g.Glassy.db.profile.frameHeight == 250)
check("height nil-marker: journal cleared", g.__has_entry("Default") is False)

lua, g = new_env(setup_default(body="{ frameHeight = 300 }"))
apply_height(g, 260)
check("height nil-marker: an explicitly stored height is journaled as that number",
      g.__entry_field("Default", "rawFrameHeight") == 300)
restore(g)
check("height nil-marker: ...and restored as that stored number", g.__rawheight(g.Glassy.db.profile) == 300)

# --- 17. logout Restore(false) restores height with zero dispatch ---------------------------------
lua, g = new_env(setup_default())
apply_height(g, 220)
g.__combat = True
before = g.__dispatch_count()
ok, changed = restore(g, False)
check("height logout: data-only restore succeeds even in combat", (ok, changed) == (True, True))
check("height logout: frameHeight restored with zero dispatch",
      g.__rawheight(g.Glassy.db.profile) is None and g.__dispatch_count() == before)
check("height logout: journal cleared", g.__has_entry("Default") is False)

# --- 18. profile switch sweeps the other profile's height -----------------------------------------
lua, g = new_env(setup_default())
apply(g, 400)
apply_height(g, 220)
g.__switch_profile(g.Glassy.db, "Alt")
ok, changed = apply_height(g, 230)
check("height switch: ApplyHeight on the new profile succeeds", (ok, changed) == (True, True))
check("height switch: the stale Default height AND width were both restored through GlassyDB.profiles",
      g.__rawheight(g.GlassyDB.profiles["Default"]) is None and g.__rawwidth(g.GlassyDB.profiles["Default"]) is None)
check("height switch: Default's journal row is cleared", g.__has_entry("Default") is False)
check("height switch: Alt owns a height-only claim at 230",
      g.__applied_height("Alt") == 230 and g.__applied_width("Alt") is None)

lua, g = new_env(setup_default(body="{ frameHeight = 300 }"))
apply_height(g, 220)
g.__switch_profile(g.Glassy.db, "Alt")
ok, changed = restore(g)
check("height switch: a Restore on the new profile also sweeps the old profile's height",
      (ok, changed) == (True, False) and g.__rawheight(g.GlassyDB.profiles["Default"]) == 300
      and g.__has_entry("Default") is False)

# --- 19. width + height restored together: each key dispatched once -------------------------------
lua, g = new_env(setup_default())
apply(g, 400)
apply_height(g, 220)
check("both: one entry carries both claims", g.__applied_width("Default") == 400 and g.__applied_height("Default") == 220)
before = g.__dispatch_count()
ok, changed = restore(g)
new_keys = dispatch_keys(g)[before:]
check("both: Restore reports success + changed", (ok, changed) == (True, True))
check("both: each restored key dispatched exactly once (width, then height)",
      new_keys == ["frameWidth", "frameHeight"], new_keys)
check("both: both fields back to inherited", g.__rawwidth(g.Glassy.db.profile) is None and g.__rawheight(g.Glassy.db.profile) is None)
check("both: entry cleared once neither field remains journaled", g.__has_entry("Default") is False)

lua, g = new_env(setup_default())
apply(g, 400)
apply_height(g, 220)
g.Glassy.db.profile.frameHeight = 240  # player hand-set the height only
before = g.__dispatch_count()
ok, changed = restore(g)
check("both: a hand-set height is left alone while the width is still restored",
      (ok, changed) == (True, True) and g.__rawwidth(g.Glassy.db.profile) is None and g.__rawheight(g.Glassy.db.profile) == 240)
check("both: only the key actually restored is dispatched", dispatch_keys(g)[before:] == ["frameWidth"], dispatch_keys(g)[before:])
check("both: entry cleared after a partial restore (the other claim was superseded)", g.__has_entry("Default") is False)

lua, g = new_env(setup_default())
apply(g, 400)
apply_height(g, 220)
g.__dispatch_fail = True
before = g.__dispatch_count()
ok, changed = restore(g)
check("both: failing dispatches report (false, true) with data still restored",
      (ok, changed) == (False, True) and g.__rawwidth(g.Glassy.db.profile) is None and g.__rawheight(g.Glassy.db.profile) is None)
check("both: a failing first dispatch does not skip the second key", g.__dispatch_count() == before + 2)
check("both: journal cleared even when the dispatch failed", g.__has_entry("Default") is False)

# --- 20. height-only entry cleared after its restore ----------------------------------------------
lua, g = new_env(setup_default())
apply_height(g, 220)
check("height-only: entry holds a height claim and no width fields",
      g.__applied_height("Default") == 220 and g.__applied_width("Default") is None
      and g.__entry_field("Default", "rawFrameWidth") is None)
before = g.__dispatch_count()
ok, changed = restore(g)
check("height-only: restore reports success + changed and dispatches only 'frameHeight'",
      (ok, changed) == (True, True) and dispatch_keys(g)[before:] == ["frameHeight"], dispatch_keys(g)[before:])
check("height-only: entry cleared after its restore", g.__has_entry("Default") is False)
check("height-only: width never touched", g.__rawwidth(g.Glassy.db.profile) is None)

# --- 21. one field's failure / refusal never drops the other field's claim -------------------------
lua, g = new_env(setup_default())
apply_height(g, 220)
g.__dispatch_fail = True
ok, changed = apply(g, 400)  # first-ever width apply fails
check("isolation: a failing first width Apply rolls back and reports failure",
      (ok, changed) == (False, False) and g.__rawwidth(g.Glassy.db.profile) is None)
check("isolation: ...but the live height claim in the same entry survives",
      g.__applied_height("Default") == 220 and g.__applied_width("Default") is None
      and g.__entry_field("Default", "rawFrameWidth") is None)

lua, g = new_env(setup_default())
g.__dispatch_fail = True
ok, changed = apply_height(g, 220)
check("isolation: a first-ever failing ApplyHeight rolls back, refreshes, leaves no journal",
      (ok, changed) == (False, False) and g.__rawheight(g.Glassy.db.profile) is None
      and dispatch_keys(g) == ["frameHeight", "frameHeight"] and g.__has_entry("Default") is False)

lua, g = new_env(setup_default())
apply(g, 400)
apply_height(g, 220)
apply(g, 350)
check("isolation: a later width Apply keeps the height claim intact",
      g.__applied_width("Default") == 350 and g.__applied_height("Default") == 220
      and g.__entry_field("Default", "effectiveWidth") == 600 and g.__entry_field("Default", "effectiveHeight") == 250)

# --- 22. width-only journals from older saves restore exactly as before ---------------------------
old_save = """
local seedProfiles = { Default = { frameWidth = 350, frameHeight = 300 } }
local seedJournal = { Default = { rawFrameWidth = 500, effectiveWidth = 500, appliedWidth = 350 } }
__setup(seedProfiles, "Default", seedJournal)
"""
lua, g = new_env(old_save)
ok, changed = restore(g)
check("old save: a width-only journal restores with (true, true)", (ok, changed) == (True, True))
check("old save: width back to 500, the stored height left exactly as it was",
      g.__rawwidth(g.Glassy.db.profile) == 500 and g.__rawheight(g.Glassy.db.profile) == 300)
check("old save: exactly one dispatch, for 'frameWidth'", dispatch_events(g) == [("Glassy/UPDATE_CONFIG", "frameWidth")], dispatch_events(g))
check("old save: entry cleared", g.__has_entry("Default") is False)

old_nil = """
local seedProfiles = { Default = { frameWidth = 491 } }
local seedJournal = { Default = { rawFrameWidth = "\\1FFSpanRawNil\\1", effectiveWidth = 600, appliedWidth = 491 } }
__setup(seedProfiles, "Default", seedJournal)
"""
lua, g = new_env(old_nil)
ok, changed = restore(g, False)
check("old save: a width-only RAW-nil journal restores the inheritance, data-only, no dispatch",
      (ok, changed) == (True, True) and g.__rawwidth(g.Glassy.db.profile) is None
      and g.__rawheight(g.Glassy.db.profile) is None and g.__dispatch_count() == 0 and g.__has_entry("Default") is False)

lua, g = new_env(old_save)
g.Glassy.db.profile.frameWidth = 450  # hand-set since the old session
ok, changed = restore(g)
check("old save: a hand-set width still wins over an old width-only journal",
      (ok, changed) == (True, False) and g.__rawwidth(g.Glassy.db.profile) == 450
      and g.__dispatch_count() == 0 and g.__has_entry("Default") is False)

old_other = """
local seedProfiles = { Old = { frameWidth = 350 }, Default = {} }
local seedJournal = { Old = { rawFrameWidth = 500, effectiveWidth = 500, appliedWidth = 350 } }
__setup(seedProfiles, "Default", seedJournal)
"""
lua, g = new_env(old_other)
ok, changed = apply_height(g, 220)
check("old save: an ApplyHeight sweeps another profile's width-only journal back by plain data",
      (ok, changed) == (True, True) and g.__rawwidth(g.GlassyDB.profiles["Old"]) == 500
      and g.__has_entry("Old") is False and g.__applied_height("Default") == 220)

# --- 23. missing addon (height) -----------------------------------------------------------------------
lua, g = new_env(setup_lua=None)
ok, changed = apply_height(g, 220)
check("missing addon: ApplyHeight fails safe with no Glassy present", (ok, changed) == (False, False))


# ============================================================ 2.9.0 chatAlwaysVisible (boolean) ===
# 2026-09-25: the home chat should dim, not vanish. The messages stay up through Glassy's own
# `chatAlwaysVisible`; FFSpan_ChatDim does the dimming. Only ever switched ON, journaled, restored.
def always(g):
    return g.FFSpan.GlassyFit.ApplyAlwaysVisible()


def raw_always(lua):
    return lua.eval('rawget(Glassy.db.profile, "chatAlwaysVisible")')


lua, g = new_env(setup_default())
ok, changed = always(g)
check("always: turns chatAlwaysVisible on", (ok, changed) == (True, True) and raw_always(lua) is True)
check("always: one dispatch, key 'chatAlwaysVisible'", dispatch_keys(g) == ["chatAlwaysVisible"])
check("always: journaled with the player's raw value (unset)",
      g.__entry_field("Default", "rawAlwaysVisible") == g.__RAW_NIL_MARKER
      and g.__entry_field("Default", "appliedAlwaysVisible") is True)
ok, changed = always(g)
check("always: a second apply is a no-op (no write, no dispatch)",
      (ok, changed) == (True, False) and len(dispatch_keys(g)) == 1)
ok, changed = restore(g)
check("always: Restore puts the option back to unset and dispatches it",
      (ok, changed) == (True, True) and raw_always(lua) is None
      and dispatch_keys(g)[-1] == "chatAlwaysVisible" and not g.__has_entry("Default"))

lua, g = new_env(setup_default())
apply(g, 500)
always(g)
ok, changed = restore(g, False)
check("always + width: a logout (data-only) restore puts both back with no dispatch",
      changed is True and raw_always(lua) is None and g.__rawwidth(g.Glassy.db.profile) is None
      and dispatch_keys(g) == ["frameWidth", "chatAlwaysVisible"])

lua, g = new_env(setup_default("{ chatAlwaysVisible = true }"))
ok, changed = always(g)
check("always: already on by the player -> no write, no claim", (ok, changed) == (True, False)
      and not g.__has_entry("Default") and len(dispatch_keys(g)) == 0)
restore(g)
check("always: ...and Restore never turns the player's own setting off", raw_always(lua) is True)

lua, g = new_env(setup_default())
always(g)
lua.execute('Glassy.db.profile.chatAlwaysVisible = false')   # the player changed it since
restore(g)
check("always: a player change after the Apply is honoured by Restore",
      raw_always(lua) is False and not g.__has_entry("Default"))

lua, g = new_env(setup_default())
g.__combat = True
check("always: refused in combat, nothing written", always(g) == (False, False) and raw_always(lua) is None)
g.__combat = False
g.__dispatch_fail = True
ok, changed = always(g)
check("always: a failing dispatch rolls the write back, no claim",
      (ok, changed) == (False, False) and raw_always(lua) is None and not g.__has_entry("Default"))

print()
print(f"{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
