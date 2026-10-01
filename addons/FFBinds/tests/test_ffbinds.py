#!/usr/bin/env python3
"""
Mocked-WoW-API tests for FFBinds 1.1 -- the controller layout.

New in 1.1 (decided 2026-09-23): PADBACK opens ConsolePort's menu RING
instead of the game menu. That needs a CLICK binding, which goes through SetBindingClick rather
than SetBinding, so this suite exists mainly to prove the click path works and that it is the ONLY
entry that changed.

MOCK TEST. It proves the binding table and the apply/capture logic. It proves nothing about the
real client's binding sets, ConsolePort's ring behaviour, or what the controller actually does.

Run: python -B test_ffbinds.py
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

# The 1.0 PADBACK entry, so the change can be asserted as a change.
V10_PADBACK = "TOGGLEGAMEMENU"
RING_BINDING = "CLICK ConsolePortMenuTrigger:LeftButton"

MOCK_API = r"""
unpack = unpack or table.unpack
__listeners, __timers, __combat = {}, {}, false
__bindings   = {}      -- chord -> action, the client's binding set
__bindCalls  = {}      -- every SetBinding / SetBindingClick call, in order
__saveBindings = 0
__cvars = {}
__printed = {}
__time = 0

local function newFrame(name, parent)
    local f = {name=name, parent=parent, events={}, points={}}
    function f:GetName() return self.name end
    function f:RegisterEvent(ev) self.events[ev]=true; __listeners[#__listeners+1]=self end
    function f:UnregisterEvent(ev) self.events[ev]=nil end
    function f:SetScript(kind, fn) self["script_"..kind]=fn end
    function f:SetPoint() end
    if name then _G[name]=f end
    return f
end
__newFrame = newFrame
function CreateFrame(kind, name, parent) return newFrame(name, parent) end

function __fire(ev, ...)
    for _,f in ipairs(__listeners) do
        if f.events[ev] and f.script_OnEvent then f.script_OnEvent(f, ev, ...) end
    end
end
function InCombatLockdown() return __combat end
function GetTime() return __time end
function print(m) __printed[#__printed+1]=tostring(m) end
function date() return "2026-09-23 14:45:00" end
function CopyTable(t)
    local out = {}
    for k,v in pairs(t) do
        if type(v)=="table" then out[k]=CopyTable(v) else out[k]=v end
    end
    return out
end
function GetBuildInfo() return "12.1.0", "60000", "Sep 23 2026", 120100 end
WOW_PROJECT_MAINLINE = 1
WOW_PROJECT_ID = 1
Enum = {BindingSet = {Account = 1, Character = 2}, ConsoleCommandType = {Cvar = 0}}
function GetCurrentBindingSet() return 1 end

function GetBindingAction(chord) return __bindings[chord] or "" end
function SetBinding(chord, command)
    __bindCalls[#__bindCalls+1] = {kind="SetBinding", chord=chord, command=command or ""}
    if __refuse and __refuse[chord] then return false end
    __bindings[chord] = command or ""
    return true
end
-- the real signature: SetBindingClick(key, buttonName, mouseButton)
function SetBindingClick(chord, frameName, mouseButton)
    __bindCalls[#__bindCalls+1] = {kind="SetBindingClick", chord=chord,
                                   frame=frameName, button=mouseButton}
    if __refuse and __refuse[chord] then return false end
    __bindings[chord] = "CLICK " .. tostring(frameName) .. ":" .. tostring(mouseButton)
    return true
end
function SaveBindings(which) __saveBindings = __saveBindings + 1 end

function GetCVar(n) return __cvars[n] end
function SetCVar(n,v) __cvars[n] = tostring(v) return true end
C_Console = {GetAllCommands = function()
    local out = {}
    for _, n in ipairs({"GamePadEnable","GamePadCameraPitchSpeed","SoftTargetEnemy"}) do
        out[#out+1] = {command = n, commandType = 0}
    end
    return out
end}
__cvars.GamePadCameraPitchSpeed = "1"
__cvars.SoftTargetEnemy = "3"
__cvars.GamePadEnable = "1"
-- the client defaults for the three modifier buttons
__cvars.GamePadEmulateShift = "PADLSHOULDER"
__cvars.GamePadEmulateCtrl = "PADLTRIGGER"
__cvars.GamePadEmulateAlt = "none"

-- ConsolePort's menu trigger, as the installed 3.2.5 declares it:
-- a SecureHandlerBaseTemplate button parented to GameMenuFrame, registerForClicks="AnyUp".
function __makeConsolePortMenu()
    GameMenuFrame = __newFrame("GameMenuFrame", UIParent)
    local trig = __newFrame("ConsolePortMenuTrigger", GameMenuFrame)
    trig.registerForClicks = "AnyUp"
    trig.template = "SecureHandlerBaseTemplate"
    ConsolePort = {}
    function ConsolePort:GetData() return function(...) return nil end end
    return trig
end
UIParent = newFrame("UIParent")
"""


def new_env(preamble=""):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    lua.execute(MOCK_API)
    if preamble:
        lua.execute(preamble)
    for name in ("FFBinds.lua", "FFBinds_Camera.lua", "FFBinds_Crossbar.lua"):   # Crossbar is not in the TOC, loaded here for its tests
        with open(os.path.join(ADDON, name), encoding="utf-8") as f:
            lua.eval("load")(f.read(), name)("FFBinds")
    return lua, g


def login(g):
    g.__fire("ADDON_LOADED", "FFBinds")
    g.__fire("PLAYER_ENTERING_WORLD", True, False)


results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not cond else ""))


def layout(g):
    """The layout table as the addon seeded it: {chord: command}."""
    out = {}
    db = g.FFBindsDB.layout
    for button in db.keys():
        for mod in db[button].keys():
            out[str(mod) + str(button)] = str(db[button][mod])
    return out


print("=" * 78)
print("FFBinds 1.1 -- controller layout")
print("=" * 78)

# --------------------------------------------------------------- the ring binding (1.1)
lua, g = new_env("__makeConsolePortMenu()")
login(g)

table_now = layout(g)
check("ring: PADBACK is the ConsolePort menu trigger, not TOGGLEGAMEMENU",
      table_now.get("PADBACK") == RING_BINDING, table_now.get("PADBACK"))
check("ring: TOGGLEGAMEMENU is no longer bound to any chord",
      V10_PADBACK not in table_now.values(),
      [c for c, v in table_now.items() if v == V10_PADBACK])

calls = [c for c in g.__bindCalls.values() if str(c.chord) == "PADBACK"]
check("ring: PADBACK went through SetBindingClick, not SetBinding",
      len(calls) == 1 and str(calls[0].kind) == "SetBindingClick",
      str([dict(c) for c in calls]))
check("ring: ...targeting ConsolePortMenuTrigger's LeftButton",
      len(calls) == 1 and str(calls[0].frame) == "ConsolePortMenuTrigger"
      and str(calls[0].button) == "LeftButton",
      str([dict(c) for c in calls]))
check("ring: the client reads the binding back in the same CLICK form",
      str(g.GetBindingAction("PADBACK")) == RING_BINDING,
      str(g.GetBindingAction("PADBACK")))
trig = g.ConsolePortMenuTrigger
check("ring: the trigger registers clicks on ANY UP, so the click fires on release",
      trig is not None and str(trig.registerForClicks) == "AnyUp",
      str(trig and trig.registerForClicks))
check("ring: the trigger is a secure handler parented to GameMenuFrame",
      trig is not None and str(trig.template) == "SecureHandlerBaseTemplate"
      and trig.parent is not None and str(trig.parent.name) == "GameMenuFrame")

# --------------------------------------------------------- the v1.8 table (triggers are the modifiers)
BASE_1_8 = {
    # bare face buttons keep their four casts (my pick 11:08, "hybrid")
    "PAD1": "ACTIONBUTTON1", "PAD2": "ACTIONBUTTON3", "PAD3": "ACTIONBUTTON5", "PAD4": "ACTIONBUTTON7",
    # measured 11:32: the old modifiers were Shift = ZL, Ctrl = L. ZL stays Shift (SHIFT- untouched),
    # Ctrl moves from L to ZR (CTRL- untouched), so every one of these chords keeps its command
    "SHIFT-PAD1": "ACTIONBUTTON2", "CTRL-PAD1": "MULTIACTIONBAR1BUTTON1", "CTRL-SHIFT-PAD1": "MULTIACTIONBAR1BUTTON2",
    "SHIFT-PADDUP": "TARGETNEARESTFRIEND", "CTRL-PADDUP": "MULTIACTIONBAR2BUTTON7",
    "PADDUP": "INTERACTTARGET", "PADDDOWN": "TARGETPREVIOUSENEMY",
    "PADDLEFT": "TARGETFOCUS", "PADDRIGHT": "TARGETNEARESTENEMY",
    # L took ZR's old job; R unchanged in physical terms
    "PADLSHOULDER": "ACTIONBUTTON11", "SHIFT-PADLSHOULDER": "ACTIONBUTTON12",
    "CTRL-PADLSHOULDER": "MULTIACTIONBAR1BUTTON11", "CTRL-SHIFT-PADLSHOULDER": "MULTIACTIONBAR1BUTTON12",
    "PADRSHOULDER": "ACTIONBUTTON9", "SHIFT-PADRSHOULDER": "ACTIONBUTTON10",
    "CTRL-PADRSHOULDER": "MULTIACTIONBAR1BUTTON9", "CTRL-SHIFT-PADRSHOULDER": "MULTIACTIONBAR1BUTTON10",
    # the modifiers carry nothing
    "PADLTRIGGER": "", "PADRTRIGGER": "", "PADRSTICK": "", "SHIFT-PADLTRIGGER": "", "CTRL-PADRTRIGGER": "",
    "PADLSTICK": "JUMP", "PADSOCIAL": "OPENCHAT", "PADSYSTEM": "",
    "SHIFT-PADFORWARD": "OPENALLBAGS", "CTRL-PADFORWARD": "TOGGLECHARACTER0", "PADFORWARD": "",
    "SHIFT-PADBACK": "", "CTRL-PADBACK": "", "CTRL-SHIFT-PADBACK": "",
    # the camera: plain native bindings on the bumpers under R3
    "ALT-PADLSHOULDER": "CAMERAZOOMOUT", "ALT-PADRSHOULDER": "CAMERAZOOMIN",
    "ALT-SHIFT-PADRSHOULDER": "", "ALT-CTRL-PADRSHOULDER": "", "ALT-PAD1": "",
}
drifted = {c: (want, table_now.get(c)) for c, want in BASE_1_8.items()
           if table_now.get(c) != want}
check("table: the v1.8 scheme, entry by entry", not drifted, str(drifted))
check("table: the layout covers all 32 buttons x all 8 layers (every Alt layer mappable)",
      len(table_now) == 32 * 8, str(len(table_now)))
check("table: no chord a modifier makes impossible carries a command",
      all(table_now.get(m + b, "") == "" for b in ("PADLTRIGGER", "PADRTRIGGER", "PADRSTICK")
          for m in ("", "SHIFT-", "CTRL-", "CTRL-SHIFT-", "ALT-", "ALT-SHIFT-", "ALT-CTRL-", "ALT-CTRL-SHIFT-")))

# ---------------------------------------------------------------- the click path is required
lua2, g2 = new_env("__makeConsolePortMenu()")
lua2.execute("SetBindingClick = nil")     # a client/flavour without the click API
login(g2)
check("ring: without SetBindingClick the chord is refused, not mis-bound with SetBinding",
      str(g2.GetBindingAction("PADBACK")) != V10_PADBACK,
      str(g2.GetBindingAction("PADBACK")))

# ConsolePort absent -> the trigger frame does not exist -> refuse rather than bind a dead click
lua3, g3 = new_env()                       # no ConsolePort at all
login(g3)
check("ring: with no ConsolePort the chord is left unbound, never bound to a missing frame",
      str(g3.GetBindingAction("PADBACK")) == "",
      str(g3.GetBindingAction("PADBACK")))
check("ring: ...and the rest of the layout still applied",
      str(g3.GetBindingAction("PAD1")) == "ACTIONBUTTON1" and g3.__saveBindings >= 1)

# ------------------------------------------------------------------- apply / capture round trip
lua4, g4 = new_env("__makeConsolePortMenu()")
login(g4)
saves = int(g4.__saveBindings)
g4.__fire("UPDATE_BINDINGS")
check("apply: a second pass with nothing changed writes no new bindings",
      int(g4.__saveBindings) == saves, f"{g4.__saveBindings} vs {saves}")
# after the settle window an edit by the player is captured into the shared layout
g4.__time = 999
lua4.execute('__bindings["PAD1"] = "ACTIONBUTTON6"')
g4.__fire("UPDATE_BINDINGS")
check("capture: an edit after the settle window is taken into the layout",
      layout(g4).get("PAD1") == "ACTIONBUTTON6", layout(g4).get("PAD1"))
check("capture: ...and the ring binding is not mistaken for an edit",
      layout(g4).get("PADBACK") == RING_BINDING, layout(g4).get("PADBACK"))

# ------------------------------------------------------------------------------ combat gate
lua5, g5 = new_env("__makeConsolePortMenu()")
g5.__combat = True
login(g5)
check("combat: SetBinding is not called in combat", len(list(g5.__bindCalls.values())) == 0)
g5.__combat = False
g5.__fire("PLAYER_REGEN_ENABLED")
check("combat: the layout is applied once combat ends",
      str(g5.GetBindingAction("PADBACK")) == RING_BINDING
      and str(g5.GetBindingAction("PAD1")) == "ACTIONBUTTON1")

# --------------------------------------------------------------------------- seed enforcement
# A saved 1.0 layout must be replaced, or the device keeps TOGGLEGAMEMENU forever.
OLD_DB = ('FFBindsDB = {seed = "retail-seed-2026-09-22", layout = '
          '{PADBACK = {[""] = "TOGGLEGAMEMENU", ["SHIFT-"] = "", ["CTRL-"] = "", ["CTRL-SHIFT-"] = ""}}}')
lua6, g6 = new_env("__makeConsolePortMenu() " + OLD_DB)
login(g6)
check("seed: a saved 1.0 layout is replaced by the 1.1 table",
      layout(g6).get("PADBACK") == RING_BINDING, layout(g6).get("PADBACK"))
check("seed: the stored seed is bumped so this happens exactly once",
      str(g6.FFBindsDB.seed) == "retail-seed-2026-09-23-ringscope", str(g6.FFBindsDB.seed))

# --------------------------------------------------------------- v1.7: R3 is the Alt modifier
# The seed is NOT bumped (that would discard every saved edit): R3's old defaults are cleared and
# the client's GamePadEmulateAlt becomes R3, carried in FFBindsDB.cvars like the other modifiers.
SAVED_R3 = ('FFBindsDB = {seed = "retail-seed-2026-09-23-ringscope", cvars = {GamePadEmulateShift = "PADLSHOULDER"}, layout = '
            '{PADRSTICK = {[""] = "%s", ["SHIFT-"] = "", ["CTRL-"] = "", ["CTRL-SHIFT-"] = ""},'
            ' PAD1 = {[""] = "ACTIONBUTTON7", ["SHIFT-"] = "", ["CTRL-"] = "", ["CTRL-SHIFT-"] = ""}}}')
for old_default in ("OPENCHAT", "CLICK FFBindsCamLayer:LeftButton"):
    lua7, g7 = new_env(SAVED_R3 % old_default)
    login(g7)
    check(f"r3: a saved R3 = {old_default} (an old default) is cleared -- R3 is a modifier now",
          str(g7.FFBindsDB.layout.PADRSTICK[""]) == "", str(g7.FFBindsDB.layout.PADRSTICK[""]))
check("r3: the client's Alt emulation is R3 (v1.8: FFBindsDB.modifiers owns it)",
      str(g7.GetCVar("GamePadEmulateAlt")) == "PADRSTICK", str(g7.GetCVar("GamePadEmulateAlt")))
check("r3: ...and the modifier cvars left the generic cvar sync (one owner)",
      g7.FFBindsDB.cvars.GamePadEmulateShift is None and g7.FFBindsDB.cvars.GamePadEmulateAlt is None)
check("r3: every other saved edit survives (no seed bump)",
      str(g7.FFBindsDB.layout.PAD1[""]) == "ACTIONBUTTON7", str(g7.FFBindsDB.layout.PAD1[""]))
check("r3: the ALT- camera chords reach a saved layout without a seed bump",
      str(g7.GetBindingAction("ALT-PADRSHOULDER")) == "CAMERAZOOMIN", str(g7.GetBindingAction("ALT-PADRSHOULDER")))
check("r3: the move is recorded so it happens once", g7.FFBindsDB.r3Alt is True)
lua8, g8 = new_env(SAVED_R3 % "TOGGLEAUTORUN")
login(g8)
check("r3: an R3 I bound to something else myself is left alone",
      str(g8.FFBindsDB.layout.PADRSTICK[""]) == "TOGGLEAUTORUN", str(g8.FFBindsDB.layout.PADRSTICK[""]))
lua9, g9 = new_env('FFBindsDB = {seed = "retail-seed-2026-09-23-ringscope", r3Alt = true, layout = '
                   '{PADRSTICK = {[""] = "OPENCHAT", ["SHIFT-"] = "", ["CTRL-"] = "", ["CTRL-SHIFT-"] = ""}}}')
login(g9)
check("r3: after the one-time move, putting chat back on R3 by hand sticks",
      str(g9.FFBindsDB.layout.PADRSTICK[""]) == "OPENCHAT", str(g9.FFBindsDB.layout.PADRSTICK[""]))
check("r3: ...and v1.8 still converts the layout once (modScheme)",
      str(g9.FFBindsDB.modScheme) == "triggers-2026-09-25b", str(g9.FFBindsDB.modScheme))


# ======================================================= v1.8: the triggers are the modifiers
# The conversion is checked as a PROPERTY over the real saved layout from the Thor: decode each old
# chord into the physical buttons pressed -- with the modifiers the device REALLY had (1.8.0's log,
# 11:32: Shift = ZL, Ctrl = L; 1.8.0 itself assumed the reverse and swapped the layers) -- apply the
# my two designed moves (what L held did goes to ZR held; what ZR pressed did goes to L
# pressed), encode it in the new scheme, and the command must be the same. Only v1.7's second
# zoom-in chord is dropped on purpose.
FIXTURE = os.path.join(HERE, "fixtures", "retail-2026-09-25-1038-FFBinds.lua")
with open(FIXTURE, encoding="utf-8") as f:
    OLD_SV = f.read()

OLD_MODS = {"SHIFT": "ZL", "CTRL": "L", "ALT": "R3"}                 # <= 1.7, measured 11:32
NEW_MODS = {"ZL": "SHIFT", "ZR": "CTRL", "R3": "ALT"}                # triggers scheme (1.8)
OLD_MOD_BUTTONS = {"PADLSHOULDER", "PADLTRIGGER", "PADRSTICK"}


def decode_old(chord):
    parts = chord.split("-")
    button, mods = parts[-1], parts[:-1]
    return {OLD_MODS[m] for m in mods}, button


def encode_new(held, button):
    mods = [NEW_MODS[b] for b in ("R3", "ZR", "ZL") if b in held]   # ALT-CTRL-SHIFT- order
    return "".join(m + "-" for m in mods) + button


def expected_new(old_chord):
    held, button = decode_old(old_chord)
    held = {"ZR" if b == "L" else b for b in held}
    if button == "PADRTRIGGER":
        button = "PADLSHOULDER"
    return encode_new(held, button)


lua10, g10 = new_env("__makeConsolePortMenu() " + OLD_SV)
old_flat = {}
for button in g10.FFBindsDB.layout.keys():
    for mod in g10.FFBindsDB.layout[button].keys():
        old_flat[str(mod) + str(button)] = str(g10.FFBindsDB.layout[button][mod])
login(g10)
new_flat = layout(g10)
moved_wrong = {}
for chord, command in old_flat.items():
    held, button = decode_old(chord)
    if button in OLD_MOD_BUTTONS or chord == "ALT-SHIFT-PADRSHOULDER":
        continue                                    # a modifier's own chords carried nothing usable
    want = expected_new(chord)
    if new_flat.get(want) != command:
        moved_wrong[chord] = (want, command, new_flat.get(want))
check("v1.8 convert: every physical press on the real Thor layout keeps its command",
      not moved_wrong and len(old_flat) > 100, str(moved_wrong)[:600])
check("v1.8 convert: ...and lands exactly on the v1.8 LAYOUT (the Thor had no hand edits)",
      all(new_flat.get(c) == w for c, w in BASE_1_8.items()),
      str({c: (w, new_flat.get(c)) for c, w in BASE_1_8.items() if new_flat.get(c) != w}))
check("v1.8 convert: ...all 32 x 8 chords present after the fill",
      len(new_flat) == 32 * 8, str(len(new_flat)))
check("v1.8 convert: the 1.6 R3 click layer is gone, R3 is a modifier",
      new_flat.get("PADRSTICK") == "", new_flat.get("PADRSTICK"))
check("v1.8 convert: v1.7's second zoom-in chord (ALT-SHIFT-PADRSHOULDER) is dropped",
      new_flat.get("ALT-SHIFT-PADRSHOULDER") == "" and new_flat.get("ALT-CTRL-PADRSHOULDER") == "",
      f"{new_flat.get('ALT-SHIFT-PADRSHOULDER')} {new_flat.get('ALT-CTRL-PADRSHOULDER')}")
check("v1.8 convert: recorded once (modScheme) and logged",
      str(g10.FFBindsDB.modScheme) == "triggers-2026-09-25b"
      and any("converted" in str(l) for l in g10.FFBindsDB.log.results.values()))

# A hand edit in the old scheme moves with its physical press: L + B was CTRL-PAD1 and ZR + B is
# CTRL-PAD1 now; ZR itself (then plain) moves to L.
lua11, g11 = new_env("__makeConsolePortMenu() " + OLD_SV.replace(
    '["CTRL-"] = "MULTIACTIONBAR1BUTTON1"', '["CTRL-"] = "SPELLBOOKMINE"', 1).replace(
    '[""] = "ACTIONBUTTON11"', '[""] = "TOGGLEAUTORUN"', 1))
login(g11)
check("v1.8 convert: an old hand edit on L + B (CTRL-PAD1) is on ZR + B (CTRL-PAD1)",
      layout(g11).get("CTRL-PAD1") == "SPELLBOOKMINE", layout(g11).get("CTRL-PAD1"))
check("v1.8 convert: an old hand edit on bare ZR moves with ZR's slots to bare L",
      layout(g11).get("PADLSHOULDER") == "TOGGLEAUTORUN" and layout(g11).get("PADRTRIGGER") == "",
      f"{layout(g11).get('PADLSHOULDER')} {layout(g11).get('PADRTRIGGER')}")

# Converted exactly once: a file that already carries the flag (mirrored from another flavor) is
# not converted again, or the SHIFT/CTRL swap would undo itself.
lua12, g12 = new_env("__makeConsolePortMenu()")
login(g12)
fresh = layout(g12)
check("v1.8 fresh install: LAYOUT is taken as-is, flagged, not converted",
      str(g12.FFBindsDB.modScheme) == "triggers-2026-09-25b" and fresh.get("SHIFT-PAD1") == "ACTIONBUTTON2",
      fresh.get("SHIFT-PAD1"))
lua12b, g12b = new_env("__makeConsolePortMenu() "
                       'FFBindsDB = {seed = "retail-seed-2026-09-23-ringscope", modScheme = "triggers-2026-09-25b", r3Alt = true, layout = '
                       '{PAD1 = {[""] = "ACTIONBUTTON1", ["SHIFT-"] = "ACTIONBUTTON2", ["CTRL-"] = "MULTIACTIONBAR1BUTTON1"}}}')
login(g12b)
check("v1.8 convert: a layout already in the new scheme is never converted twice",
      layout(g12b).get("SHIFT-PAD1") == "ACTIONBUTTON2" and layout(g12b).get("CTRL-PAD1") == "MULTIACTIONBAR1BUTTON1",
      f"{layout(g12b).get('SHIFT-PAD1')} {layout(g12b).get('CTRL-PAD1')}")

# 1.8.0 on the device: the file it wrote at 11:32 is swapped; 1.8.2 swaps it back exactly once.
with open(os.path.join(HERE, "fixtures", "retail-2026-09-25-1132-FFBinds-180.lua"), encoding="utf-8") as f:
    SV_180 = f.read()
lua19, g19 = new_env("__makeConsolePortMenu() " + SV_180)
check("1.8.0 fixture: it really is the swapped file (ZL + B = bar 1 slot 1, ZR + B = slot 2)",
      str(g19.FFBindsDB.layout.PAD1["SHIFT-"]) == "MULTIACTIONBAR1BUTTON1"
      and str(g19.FFBindsDB.modScheme) == "triggers-2026-09-25")
login(g19)
fixed = layout(g19)
check("1.8.0 correction: the Thor's layout is back on the v1.8 table, entry by entry",
      all(fixed.get(c) == w for c, w in BASE_1_8.items()),
      str({c: (w, fixed.get(c)) for c, w in BASE_1_8.items() if fixed.get(c) != w}))
check("1.8.0 correction: ...and on the pre-1.8 meaning of every physical press (property)",
      all(fixed.get(expected_new(c)) == v for c, v in old_flat.items()
          if decode_old(c)[1] not in OLD_MOD_BUTTONS and c != "ALT-SHIFT-PADRSHOULDER"))
check("1.8.0 correction: flagged b and logged, so it happens once",
      str(g19.FFBindsDB.modScheme) == "triggers-2026-09-25b"
      and any("swapped back" in str(l) for l in g19.FFBindsDB.log.results.values()))
check("1.8.0 correction: the R3 zoom chords survive it (ALT- is not swapped)",
      fixed.get("ALT-PADLSHOULDER") == "CAMERAZOOMOUT" and fixed.get("ALT-PADRSHOULDER") == "CAMERAZOOMIN")

# --------------------------------------------------- the modifiers go through ConsolePort's setter
CP_DB = r"""
__makeConsolePortMenu()
__cpSet, __slash = {}, {}
local db = setmetatable({}, {__call = function(self, key) return true end})
function db:SetCVar(cvar, value)
    __cpSet[#__cpSet+1] = {cvar = cvar, value = value, bindsBefore = #__bindCalls, slashBefore = #__slash}
    __cvars[cvar] = value
    return true
end
function ConsolePort:GetData() return db end
setmetatable(ConsolePort, {__call = function(self, msg) __slash[#__slash+1] = msg end})
-- ConsolePort_Bar's env as RelaTable registers it (LibStub registry keyed by addon name). The
-- preset keeps a driver as a CLOSURE, exactly like env.RunTimeFilter, so a path that skips
-- BuildLayout (rev 1's `/cp layout`) is visible as an unbuilt layout.
__barEvents = {}
local barEnv = setmetatable({
    Presets = { CrossbarTriple = { name = 'Crossbar: Triple', children = {
        Left   = { type = 'Group', modifier = function() return '[mod:M3M1] M3M1; [] M1' end },
        Center = { type = 'Group', modifier = function() return '[mod:M0] M0' end, width = 300 },
    } } },
}, {__call = function(self, k, v) if v == nil then return self.__layout end; self.__layout = v end})
function barEnv:ReleaseAll() __barEvents[#__barEvents+1] = 'release' end
function barEnv.BuildLayout(l)
    for _, c in pairs(l.children or {}) do
        for k, v in pairs(c) do if type(v) == 'function' then c[k] = v(k) end end
    end
    return l
end
function barEnv:RunSafe(f, ...) if InCombatLockdown() then return end return f(...) end
function barEnv:TriggerEvent(ev) __barEvents[#__barEvents+1] = ev end
barEnv.db = function() end
__barEnv = barEnv
__relatable = { ConsolePort_Bar = barEnv }
-- LibStub as WoW has it: a TABLE with GetLibrary and a __call metamethod (1.8.2 assumed a function)
LibStub = setmetatable({ GetLibrary = function(self, name, silent) if name == 'RelaTable' then return __relatable end end },
                       { __call = function(self, name, silent) return self:GetLibrary(name, silent) end })
function UnitName() return 'Alt' end
function GetRealmName() return 'Realm' end
"""
lua13, g13 = new_env(CP_DB + OLD_SV)
login(g13)
sets = [(str(c.cvar), str(c.value), int(c.bindsBefore)) for c in g13.__cpSet.values()]
check("modifiers: ZL = Shift, ZR = Ctrl, R3 = Alt, all through ConsolePort's db:SetCVar",
      [(c, v) for c, v, _ in sets] == [("GamePadEmulateCtrl", "PADRTRIGGER"),
                                        ("GamePadEmulateShift", "PADLTRIGGER"),
                                        ("GamePadEmulateAlt", "PADRSTICK")], str(sets))
check("modifiers: Ctrl leaves ZL before Shift takes it (never two modifiers on one button)",
      [c for c, _, _ in sets][:2] == ["GamePadEmulateCtrl", "GamePadEmulateShift"])
check("modifiers: set BEFORE the layout is applied (ConsolePort's wipe lands first)",
      all(n == 0 for _, _, n in sets) and len(list(g13.__bindCalls.values())) > 0, str(sets))
check("modifiers: logged as going via ConsolePort",
      any("via ConsolePort" in str(l) for l in g13.FFBindsDB.log.results.values()))
g13.__fire("PLAYER_ENTERING_WORLD", False, True)       # a /reload: already set, no second write
check("modifiers: a second login with everything set writes nothing", len(list(g13.__cpSet.values())) == 3)
# I move Alt somewhere else in ConsolePort's config: captured as his at logout
lua13.execute('__cvars.GamePadEmulateAlt = "PADLSTICK"')
g13.__fire("PLAYER_LOGOUT")
check("modifiers: a modifier moved in ConsolePort's config is captured at logout",
      str(g13.FFBindsDB.modifiers.Alt) == "PADLSTICK", str(g13.FFBindsDB.modifiers.Alt))

lua14, g14 = new_env("__makeConsolePortMenu() " + OLD_SV)   # ConsolePort's db is not a table here
login(g14)
check("modifiers: without ConsolePort's setter they still land via SetCVar",
      str(g14.GetCVar("GamePadEmulateShift")) == "PADLTRIGGER" and str(g14.GetCVar("GamePadEmulateCtrl")) == "PADRTRIGGER"
      and str(g14.GetCVar("GamePadEmulateAlt")) == "PADRSTICK")

lua15, g15 = new_env(CP_DB + OLD_SV)
g15.__combat = True
login(g15)
check("modifiers: never in combat", len(list(g15.__cpSet.values())) == 0)
check("crossbar: never switched in combat", len(list(g15.__barEvents.values())) == 0)
g15.__combat = False
g15.__fire("PLAYER_REGEN_ENABLED")
check("modifiers: ...applied when the fight ends", len(list(g15.__cpSet.values())) == 3)
check("crossbar: ...and switched when the fight ends",
      [str(e) for e in g15.__barEvents.values()] == ["release", "OnLayoutChanged"])

# ------------------------------------------------------------ the crossbar, once per character
events = [str(e) for e in g13.__barEvents.values()]
check("crossbar: loaded the way ConsolePort's config loads a preset (release, store, OnLayoutChanged)",
      events == ["release", "OnLayoutChanged"], str(events))
bar = g13.__barEnv.__layout
check("crossbar: the bar now holds Crossbar: Triple", bar is not None and str(bar.name) == "Crossbar: Triple")
check("crossbar: ...BUILT: every driver is a condition string, no closure left (rev 1 drew nothing)",
      bar is not None and lua13.eval("type(__barEnv.__layout.children.Left.modifier)") == "string"
      and str(bar.children.Left.modifier) == "[mod:M3M1] M3M1; [] M1", str(bar and bar.children.Left.modifier))
check("crossbar: ConsolePort's own preset table is not mutated (deep copy first, like the config)",
      lua13.eval("type(__barEnv.Presets.CrossbarTriple.children.Left.modifier)") == "function")
check("crossbar: the `/cp layout` slash path is never used (it skips BuildLayout)",
      len(list(g13.__slash.values())) == 0, str(list(g13.__slash.values())))
check("crossbar: it runs AFTER the modifiers (the preset reads M3 when it is built)",
      len(list(g13.__cpSet.values())) == 3 and events)
key = "1:Realm-Alt"
entry = g13.FFBindsDB.crossbar[key]
check("crossbar: remembered per character with rev 2 and the verified result",
      entry is not None and int(entry.rev) == 2 and entry.built is True and str(entry.layout) == "Crossbar: Triple",
      str(entry and dict(entry)))
check("crossbar: a second Ensure on the same character is a no-op", str(g13.FFBinds_Crossbar.Ensure("again")) == "done-before")

# The Thor's own case: a rev-1 entry (the slash that drew nothing) is re-applied.
lua16, g16 = new_env(CP_DB + 'FFBindsDB = {seed = "retail-seed-2026-09-23-ringscope", modScheme = "triggers-2026-09-25b", '
                     'r3Alt = true, crossbar = {["1:Realm-Alt"] = "2026-09-25 11:32:10 login"}}')
login(g16)
check("crossbar: a character left on rev 1 is loaded again at the next login",
      [str(e) for e in g16.__barEvents.values()] == ["release", "OnLayoutChanged"]
      and int(g16.FFBindsDB.crossbar[key].rev) == 2)
lua18, g18 = new_env(CP_DB + 'FFBindsDB = {seed = "retail-seed-2026-09-23-ringscope", modScheme = "triggers-2026-09-25b", '
                     'r3Alt = true, crossbar = {["1:Realm-Alt"] = {rev = 2}}}')
login(g18)
check("crossbar: a character already on rev 2 is never switched again (a bar I pick later stays)",
      len(list(g18.__barEvents.values())) == 0)
g18.SlashCmdList.FFBINDS("crossbar")
check("crossbar: /ffbinds crossbar puts it back on demand",
      [str(e) for e in g18.__barEvents.values()] == ["release", "OnLayoutChanged"])
lua17, g17 = new_env(CP_DB + '__relatable = {}')
login(g17)
check("crossbar: no ConsolePort_Bar -> nothing released, not remembered",
      len(list(g17.__barEvents.values())) == 0
      and (g17.FFBindsDB.crossbar is None or g17.FFBindsDB.crossbar[key] is None))

# 1.8.3: the crossbar look was withdrawn (1.8.3); the file stays, the TOC does not load it.
with open(os.path.join(ADDON, "FFBinds.toc"), encoding="utf-8") as f:
    TOC = f.read()
check("1.8.3: FFBinds_Crossbar.lua is not in the TOC (cluster bar stays)", "FFBinds_Crossbar.lua" not in TOC)
lua21, g21 = new_env("__makeConsolePortMenu()")
lua21.execute("FFBinds_Crossbar = nil")
login(g21)
check("1.8.3: without the crossbar file the login still applies modifiers and layout",
      str(g21.GetBindingAction("PADLSHOULDER")) == "ACTIONBUTTON11" and str(g21.GetCVar("GamePadEmulateShift")) == "PADLTRIGGER")

# 1.8.4: the Shop (it was really hard to close). FFSpan owns the check and the close; here
# FFSpan is stubbed the way FFSpan_Dismiss publishes it.
SHOP_STUB = r"""
__makeConsolePortMenu()
__shopOpen, __shopCloses, __overrides, __menuShown = true, 0, {}, 0
function SetOverrideBindingClick(owner, prio, chord, button) __overrides[chord] = button end
function ClearOverrideBindings(owner) __overrides = {} end
function GameMenuFrame_Show() __menuShown = __menuShown + 1 end
function HideUIPanel(f) if f.Hide then f:Hide() end end
FFSpan = {
    MenuWindowsOpen = function() return {} end,
    MenuWindowNames = function() return {} end,
    ShopShown = function() return __shopOpen end,
    CloseShop = function(reason)
        if not __shopOpen then return false, 'no shop open' end
        __shopOpen = false; __shopCloses = __shopCloses + 1; __lastReason = reason
        return true, 'ToggleStoreUI'
    end,
    OnShopChanged = function(fn) __shopListener = fn end,
}
"""
lua22, g22 = new_env(SHOP_STUB)


def decision(g):
    v = g.FFBinds_BackDecision()
    return str(v[0] if isinstance(v, tuple) else v)


login(g22)
check("1.8.4: FFBinds listens for the Shop opening/closing", g22.__shopListener is not None)
check("1.8.4: with the Shop open, `-` means close", decision(g22) == "close")
check("1.8.4: ...and its override binding is on", str(g22.__overrides["PADBACK"] or "") == "FFBindsBack",
      str(g22.__overrides["PADBACK"]))
lua22.execute("FFBinds_CloseMenuWindows('`-` pressed')")
check("1.8.4: `-` closes the Shop", not g22.__shopOpen and g22.__shopCloses == 1)
lua22.execute("__shopListener('shop closed')")
check("1.8.4: Shop closed -> `-` is the ring again (override cleared)",
      decision(g22) == "ring" and g22.__overrides["PADBACK"] is None)
g22.__shopOpen = True
check("1.8.4: the menu button closes an open Shop instead of showing the menu",
      str(g22.FFBinds_ToggleGameMenu()) == "shop closed" and not g22.__shopOpen and g22.__menuShown == 0)
check("1.8.4: with no Shop the menu button still shows the menu",
      str(g22.FFBinds_ToggleGameMenu()) == "shown" and g22.__menuShown == 1 and g22.__shopCloses == 2)
g22.__shopOpen = True
g22.__combat = True
check("1.8.4: in combat the menu button still closes the Shop (ToggleStoreUI is not protected-gated)",
      str(g22.FFBinds_ToggleGameMenu()) == "shop closed" and not g22.__shopOpen)
g22.__combat = False
lua23, g23 = new_env("__makeConsolePortMenu()")
login(g23)
check("1.8.4: without FFSpan's shop API nothing changes (`-` = ring)", decision(g23) == "ring")

print("\n" + "=" * 78)
passed = sum(1 for r in results if r)
print(f"{passed}/{len(results)} checks passed")
print("=" * 78)
sys.exit(0 if passed == len(results) else 1)
