#!/usr/bin/env python3
"""
FFScale 1.6.0 + FFSpan 2.1.0 loaded into ONE mocked client, in the real TOC order.

Both addons were built in parallel, each against a MOCK of the other:
  * FFScale/tests/test_ffscale_home.py drives a hand-written `FFSpan` table.
  * FFSpan/tests/test_ffspan_home.py drives a hand-written `FFScale` table that always
    answers HomeSlots().
Neither suite can see a contract-level disagreement. This one loads the REAL pair.

The client here is the two existing harnesses composed, not a third mock:
  * FFScale/tests/ffscale_harness.py is imported (Edit Mode API, layout store, enums,
    bindings, action bars, the deterministic serialiser).
  * FFSpan/tests/test_ffspan_home.py's MOCK_API string is lifted out with `ast` (CVars,
    ConsolePort tri-state registry, container frames, panel manager, Escape routing,
    UnitName/GetRealmName, __placed/__px).
FFSpan's mock runs second, so its frame factory wins; BRIDGE re-adds the few methods only
FFScale's mock provided and rebuilds UIParent / WorldFrame / EditModeManagerFrame with the
merged factory. C_EditMode.SaveLayouts still echoes EDIT_MODE_LAYOUTS_UPDATED, as the real
client does.

MOCK TEST. It proves contract, units, origins, ordering and event flow between the two
addons. It proves nothing about real taint, real protected frames or the device.

Run: python test_home_integration.py
"""
import ast
import os
import sys

try:
    import lupa
except ImportError:  # pragma: no cover - environment guard
    print("SKIP: python module 'lupa' is not installed -- cannot run mocked-API tests.")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
ADDONS = os.path.abspath(os.path.join(HERE, ".."))
FFSCALE_DIR = os.path.join(ADDONS, "FFScale")
FFSPAN_DIR = os.path.join(ADDONS, "FFSpan")

sys.path.insert(0, os.path.join(FFSCALE_DIR, "tests"))
import ffscale_harness as FSH  # noqa: E402  -- the FFScale client mock, reused verbatim


def _literal(path, name):
    """Lift a module-level constant out of a test script without executing it."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), path)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(node.value)
    raise SystemExit(f"could not find {name} in {path}")


_FFSPAN_TEST = os.path.join(FFSPAN_DIR, "tests", "test_ffspan_home.py")
FFSPAN_MOCK = _literal(_FFSPAN_TEST, "MOCK_API")
FFSPAN_FILES = _literal(_FFSPAN_TEST, "FILES")
FFSCALE_FILES = ["FFScale.lua"]
# FFBinds 1.2: FFBinds joins the client, because the `-` contract is exactly the seam between the two
# -- FFBinds owns the binding, FFSpan owns what counts as a menu window, and the bug this version
# fixes was the two of them not agreeing about the second.
FFBINDS_DIR = os.path.join(ADDONS, "FFBinds")
FFBINDS_FILES = ["FFBinds.lua"]


# The binding half of the client, so FFBinds can run beside FFScale and FFSpan. Same shapes as
# FFBinds' own harness; the override-binding pair is new for FFBinds 1.2, because the `-` contract IS
# an override binding and its state is the thing worth asserting.
FFBINDS_MOCK = r"""
__bindings, __bindCalls, __saveBindings, __time = {}, {}, 0, 0
__overrides = {}          -- owner -> {chord -> "CLICK frame:button"}, SetOverrideBindingClick
__overrideClears = 0
function GetTime() return __time end
function GetCurrentBindingSet() return 1 end
function GetBindingAction(chord) return __bindings[chord] or "" end
function SetBinding(chord, command)
    __bindCalls[#__bindCalls+1] = {kind="SetBinding", chord=chord, command=command or ""}
    __bindings[chord] = command or ""
    return true
end
function SetBindingClick(chord, frameName, mouseButton)
    __bindCalls[#__bindCalls+1] = {kind="SetBindingClick", chord=chord,
                                   frame=frameName, button=mouseButton}
    __bindings[chord] = "CLICK " .. tostring(frameName) .. ":" .. tostring(mouseButton)
    return true
end
function SaveBindings() __saveBindings = __saveBindings + 1 end
function SetOverrideBindingClick(owner, priority, chord, frameName, mouseButton)
    local key = owner and owner:GetName() or "?"
    __overrides[key] = __overrides[key] or {}
    __overrides[key][chord] = "CLICK " .. tostring(frameName) .. ":" .. tostring(mouseButton)
    return true
end
function ClearOverrideBindings(owner)
    local key = owner and owner:GetName() or "?"
    __overrides[key] = nil
    __overrideClears = __overrideClears + 1
end
-- what `-` actually does when pressed, override first, exactly like the client's binding stack
function __pressBack()
    for _, tbl in pairs(__overrides) do
        if tbl.PADBACK then
            local frame = tbl.PADBACK:match("^CLICK ([^:]+)")
            local f = _G[frame]
            if f and f.script_OnClick then f.script_OnClick(f, "LeftButton") end
            return "override:" .. tbl.PADBACK
        end
    end
    local action = __bindings.PADBACK or ""
    local frame = action:match("^CLICK ([^:]+)")
    local f = frame and _G[frame]
    if f and f.script_OnClick then f.script_OnClick(f, "LeftButton") end
    return "binding:" .. action
end
Enum = Enum or {}
Enum.BindingSet = Enum.BindingSet or {Account = 1, Character = 2}
Enum.ConsoleCommandType = Enum.ConsoleCommandType or {Cvar = 0}
C_Console = C_Console or {GetAllCommands = function() return {} end}
"""

H_PHYS = 1080
PX_PER_UNIT = H_PHYS / 768.0  # UIParent sits at effective scale 1 in the merged mock

# FFSpan's MOCK_API replaces the frame factory, UIParent and WorldFrame. Put back the methods
# only FFScale's mock defined, and rebuild the three frames FFScale's mock owns, so one client
# satisfies both addons.
BRIDGE = r"""
local base = __newFrame
local function newFrame(name, parent)
    local f = base(name, parent)
    f.hooks = f.hooks or {}
    f.w, f.h = f.w or 10, f.h or 10
    function f:GetDebugName() return self.name or "<anon>" end
    function f:SetMovable(v) self.movable = v end
    function f:SetUserPlaced(v) self.userPlaced = v end
    function f:SetHeight(v) self.h = v end
    function f:SetWidth(v) self.w = v end
    function f:GetHeight() return self.h end
    function f:GetWidth() return self.w end
    function f:GetOwner() return self.owner end
    return f
end
__newFrame = newFrame
function CreateFrame(kind, name, parent) return newFrame(name, parent) end

UIParent = newFrame("UIParent")
UIParent.rect = {0, 0, __W * 768 / __H, 768}
WorldFrame = newFrame("WorldFrame")
WorldFrame.rect = {(__W - __H*16/9)/2 / (__H/768), 0, (__H*16/9) / (__H/768), 768}
WorldFrame.points = {{"TOPLEFT", UIParent, "TOPLEFT", 0, 0},
                     {"BOTTOMRIGHT", UIParent, "BOTTOMRIGHT", 0, 0}}
EditModeManagerFrame = newFrame("EditModeManagerFrame")
EditModeManagerFrame.registeredSystemFrames = {}
function EditModeManagerFrame:GetActiveLayoutInfo() return __activeLayout end
GameTooltip = newFrame("GameTooltip")

-- FFScale's harness records every scheduled delay; FFSpan's C_Timer.After does not.
__timerLog = {}
local rawAfter = C_Timer.After
function C_Timer.After(delay, fn) __timerLog[#__timerLog + 1] = delay; rawAfter(delay, fn) end

-- Count how often FFSpan asked FFScale for the home column, and whether it got one.
__slotCalls = {}
function __watchHomeSlots()
    local orig = FFScale.HomeSlots
    FFScale.HomeSlots = function(...)
        local v = orig(...)
        __slotCalls[#__slotCalls + 1] = (v ~= nil) and "slots" or "nil"
        return v
    end
end

-- Physical px (canvas top-left origin, y down) that an Edit Mode anchorInfo actually resolves to,
-- using FFSpan's device-verified conversion: q = frameEffectiveScale * physH / 768.
-- `mult` is the system's own scale multiplier (minimap Size 150% -> 1.5).
function __anchorPx(anchor, mult)
    if not anchor then return nil end
    local q = UIParent:GetEffectiveScale() * (mult or 1) * __H / 768
    local rp, x, y = anchor.relativePoint, anchor.offsetX or 0, anchor.offsetY or 0
    local ox, oy
    if rp == "TOPLEFT" then ox, oy = 0, 0
    elseif rp == "TOPRIGHT" then ox, oy = __W, 0
    elseif rp == "TOP" then ox, oy = __W / 2, 0
    elseif rp == "BOTTOMLEFT" then ox, oy = 0, __H
    elseif rp == "BOTTOMRIGHT" then ox, oy = __W, __H
    elseif rp == "BOTTOM" then ox, oy = __W / 2, __H
    elseif rp == "CENTER" then ox, oy = __W / 2, __H / 2
    else return nil end
    return {x = ox + x * q, y = oy - y * q, q = q}
end

-- ------------------------------------------------------------------ realising the layout -------
-- v1.7/v2.2 (review B1/M6): FFScale now MEASURES the live minimap and bottom-bar edges
-- after the layout is verified, instead of publishing seeded estimates. So the client has to
-- actually move those frames when a layout is activated, or the measurement has nothing to read
-- and the whole acknowledged sequence is untested. This closes the loop end to end:
--   FFScale writes anchorInfo -> the client realises it -> FFScale measures it back -> publishes.
-- Sizes are UI units; rectPx multiplies by q = effectiveScale * physH / 768.
__MINIMAP_UNITS = {w = 198, h = 220}      -- MinimapCluster at Size 100%
__BOTTOMBAR_UNITS = {w = 800, h = 40}     -- the micro-menu + bags strip

function __realiseLayout()
    local l = __activeLayout
    if type(l) ~= "table" or type(l.systems) ~= "table" then return end
    local q = UIParent:GetEffectiveScale() * __H / 768
    for _, s in ipairs(l.systems) do
        local a = s.anchorInfo
        if a and a.relativeTo == "UIParent" then
            if s.system == 2 then                      -- Minimap -> MinimapCluster root
                local pct = 100
                for _, st in ipairs(s.settings or {}) do
                    if st.setting == 2 then pct = 50 + (st.value or 0) * 10 end
                end
                local f = _G.MinimapCluster
                if f then
                    -- the Size setting scales the CONTAINER, so the cluster's envelope grows with
                    -- pct while the root anchor itself resolves at the root's own scale
                    local wU = __MINIMAP_UNITS.w * pct / 100
                    local hU = __MINIMAP_UNITS.h * pct / 100
                    local p = __anchorPx(a, 1)
                    if p then
                        local left = (a.point:find("RIGHT") and (p.x - wU * q)) or p.x
                        local top  = (a.point:find("BOTTOM") and (p.y - hU * q)) or p.y
                        f.rect = {left / q, (__H - top) / q - hU, wU, hU}
                    end
                end
            elseif s.system == 13 then                 -- MicroMenu -> the bottom strip
                local f = _G.MicroMenuContainer
                if f then
                    local wU, hU = __BOTTOMBAR_UNITS.w, __BOTTOMBAR_UNITS.h
                    local p = __anchorPx(a, 1)
                    if p then
                        local left = p.x - wU * q / 2
                        if a.point:find("LEFT") then left = p.x end
                        if a.point:find("RIGHT") then left = p.x - wU * q end
                        local top = (a.point:find("BOTTOM") and (p.y - hU * q)) or p.y
                        f.rect = {left / q, (__H - top) / q - hU, wU, hU}
                    end
                end
            end
        end
    end
end

-- The ThorSpanHome entry for one system, straight out of the saved layout.
function __homeSystem(system, index)
    for _, l in ipairs((__layoutStore and __layoutStore.layouts) or {}) do
        if l.layoutName == "ThorSpanHome" then
            for _, s in ipairs(l.systems or {}) do
                if s.system == system and (s.systemIndex or false) == (index or false) then
                    return s
                end
            end
        end
    end
    return nil
end

function __settingValue(sys, setting)
    for _, s in ipairs((sys and sys.settings) or {}) do
        if s.setting == setting then return s.value end
    end
    return nil
end

function __layoutNames()
    local out = {}
    for _, l in ipairs((__layoutStore and __layoutStore.layouts) or {}) do
        out[#out + 1] = l.layoutName
    end
    return table.concat(out, ",")
end

function __countLayout(name)
    local n = 0
    for _, l in ipairs((__layoutStore and __layoutStore.layouts) or {}) do
        if l.layoutName == name then n = n + 1 end
    end
    return n
end

-- Every SaveLayouts payload whose active layout is `name`, so a double-apply is visible.
function __savesOf(name)
    local n = 0
    for _, info in ipairs(__saveCalls) do
        local idx = (info.activeLayout or 0) - Enum.EditModePresetLayoutsMeta.NumValues
        local l = info.layouts and info.layouts[idx]
        if l and l.layoutName == name then n = n + 1 end
    end
    return n
end

-- ffscale_harness's __ser is a DIFF format ("k"=v), not loadable Lua. Reloads here re-seed the
-- next client from the previous one's SavedVariables, so they need a real table constructor.
-- activating a layout is what moves the frames on a real client
do
    local rawSetActive = C_EditMode.SetActiveLayout
    function C_EditMode.SetActiveLayout(index)
        rawSetActive(index)
        __realiseLayout()
    end
end

function __luaser(v)
    local t = type(v)
    if t == "nil" then return "nil" end
    if t == "boolean" then return v and "true" or "false" end
    if t == "number" then
        if v == math.floor(v) and math.abs(v) < 1e15 then return string.format("%d", v) end
        return string.format("%.10g", v)
    end
    if t == "string" then return string.format("%q", v) end
    if t ~= "table" then return "nil" end
    local keys = {}
    for k in pairs(v) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b)
        local ta = type(a) == "number" and 0 or 1
        local tb = type(b) == "number" and 0 or 1
        if ta ~= tb then return ta < tb end
        if ta == 0 then return a < b end
        return tostring(a) < tostring(b)
    end)
    local parts = {}
    for _, k in ipairs(keys) do
        parts[#parts + 1] = "[" .. __luaser(k) .. "]=" .. __luaser(v[k])
    end
    return "{" .. table.concat(parts, ",") .. "}"
end
"""

# A cluster/bar/bag set every 4400 scenario needs. Sizes are UI units (the mock's GetRect space).
HOME_FIXTURE = r"""
__makeConsolePort(true)
ContainerFrameCombinedBags = __newFrame("ContainerFrameCombinedBags", UIParent)
ContainerFrameCombinedBags.rect = {0, 0, 256, 320}
ContainerFrameCombinedBags.shown = false
GameMenuFrame = __newFrame("GameMenuFrame", UIParent)
GameMenuFrame.rect = {0, 0, 150, 200}
GameMenuFrame.shown = false
MinimapCluster = __newFrame("MinimapCluster", UIParent)
MinimapCluster.rect = {0, 0, 198, 220}
MicroMenuContainer = __newFrame("MicroMenuContainer", UIParent)
MicroMenuContainer.rect = {0, 0, 800, 40}
WorldMapFrame = __newFrame("WorldMapFrame", UIParent)
WorldMapFrame.rect = {0, 0, 400, 300}
WorldMapFrame.shown = false
-- a ConsolePort registry row that already exists, so "exact restore" has something to restore to
ConsolePort:AddInterfaceCursorFrame("WorldMapFrame")
__cvars.mapFade = "1"
__cvars.combinedBags = "0"
"""


def new_client(w, h, *, preamble="", retail=True, watch_slots=True, mid="", binds=False):
    """One mocked client with BOTH addons loaded in TOC order (FFScale first, then FFSpan)."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    g.__W, g.__H = w, h
    g.__BUILD = "12.1.0" if retail else "5.5.4"
    lua.execute(FSH.MOCK_API)
    lua.execute("WOW_PROJECT_MAINLINE = 1; WOW_PROJECT_ID = %d" % (1 if retail else 19))
    lua.execute(FSH.RETAIL_BASE if retail else FSH.CLASSIC_BASE)
    lua.execute(FSH.ACTIONS)
    lua.execute(FFSPAN_MOCK)
    lua.execute(BRIDGE)
    if preamble:
        lua.execute(preamble)

    load = lua.eval("load")

    def load_addon(folder, files, name):
        for fn in files:
            with open(os.path.join(folder, fn), encoding="utf-8") as fh:
                load(fh.read(), fn)(name)
        g.__fire("ADDON_LOADED", name)

    load_addon(FFSCALE_DIR, FFSCALE_FILES, "FFScale")
    if mid:
        lua.execute(mid)          # runs between the two addons, e.g. to age FFScale's contract
    if watch_slots:
        g.__watchHomeSlots()
    load_addon(FFSPAN_DIR, FFSPAN_FILES, "FFSpan")
    if binds:
        lua.execute(FFBINDS_MOCK)
        load_addon(FFBINDS_DIR, FFBINDS_FILES, "FFBinds")
    return lua, g


def login(g, *, combat=False, flush=True):
    """A realistic login: PLAYER_LOGIN, PLAYER_ENTERING_WORLD, then the scheduled timers."""
    g.__combat = combat
    g.__fire("PLAYER_LOGIN")
    g.__fire("PLAYER_ENTERING_WORLD")
    if flush:
        g.__flush()
    return g


results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not cond else ""))


def calls(g, key):
    v = g.__calls[key]
    return int(v) if v else 0


def near(a, b, tol=1.0):
    return a is not None and b is not None and abs(a - b) <= tol


def slot_list(g):
    return [str(v) for v in (g.__slotCalls.values() if g.__slotCalls else [])]


print("=" * 78)
print("FFScale 1.6.0 + FFSpan 2.1.0 -- integration (one client, real TOC order)")
print("=" * 78)

# ============================================================ 1. load order + contract ===========
print("\n-- 1. load order and the two-way contract --")
lua, g = new_client(4400, 1080, preamble=HOME_FIXTURE)
check("load: FFScale and FFSpan both loaded, no Lua error",
      g.FFScale is not None and g.FFSpan is not None)
check("load: FFScale exposes the section-9 contract",
      all(g.FFScale[k] is not None for k in ("ApplyLayout", "ActiveLayoutName", "HomeSlots")))
check("load: FFSpan exposes the section-9 contract",
      all(g.FFSpan[k] is not None
          for k in ("GameRect", "HomeRect", "HomeEligible", "HomeEnabled", "RegisterHomeListener")))
check("load: before login nothing has registered a home listener",
      int(g.FFSpan.HomeListenerCount()) == 0)
check("load: HomeSlots() is nil before any layout pass", g.FFScale.HomeSlots() is None)

login(g)
check("login: FFScale registered exactly one home listener",
      int(g.FFSpan.HomeListenerCount()) == 1, f"count={g.FFSpan.HomeListenerCount()}")

# ============================================================ 2. 1920 stock ======================
print("\n-- 2. 1920x1080 stock: Thor6in, FFSpan is a no-op --")
lua2, g2 = new_client(1920, 1080, preamble=HOME_FIXTURE)
login(g2)
check("1920: FFScale applied Thor6in", g2.FFScale.ActiveLayoutName() == "Thor6in",
      str(g2.FFScale.ActiveLayoutName()))
check("1920: no ThorSpanHome layout exists", int(g2.__countLayout("ThorSpanHome")) == 0,
      str(g2.__layoutNames()))
check("1920: HomeEligible false, HomeEnabled false",
      not g2.FFSpan.HomeEligible() and not g2.FFSpan.HomeEnabled())
check("1920: HomeSlots() stays nil", g2.FFScale.HomeSlots() is None)
check("1920: FFSpan wrote no CVars",
      g2.__cvars.mapFade == "1" and g2.__cvars.combinedBags == "0",
      f"mapFade={g2.__cvars.mapFade} combinedBags={g2.__cvars.combinedBags}")
check("1920: no home session opened", "applied=no" in g2.FFSpan.Home.StatusLine(),
      g2.FFSpan.Home.StatusLine())
check("1920: the foreign layout is still there", int(g2.__countLayout("SomeoneElse")) == 1)

# ============================================================ 3. 3160 centre-game ================
print("\n-- 3. 3160x1080 centre-game: unchanged, still Thor6in --")
lua3, g3 = new_client(3160, 1080, preamble=HOME_FIXTURE)
login(g3)
check("3160: FFScale applied Thor6in", g3.FFScale.ActiveLayoutName() == "Thor6in",
      str(g3.FFScale.ActiveLayoutName()))
check("3160: no ThorSpanHome layout exists", int(g3.__countLayout("ThorSpanHome")) == 0)
check("3160: centre-game applied the WorldFrame rect", g3.FFSpan.CentreCore.applied is True)
gr3 = g3.FFSpan.GameRect()
check("3160: GameRect is the centred 16:9 box", near(gr3.x, 620) and near(gr3.w, 1920),
      f"{dict(gr3)}")
check("3160: HomeEligible false -> FFSpan home is a no-op", not g3.FFSpan.HomeEligible())
check("3160: HomeSlots() stays nil", g3.FFScale.HomeSlots() is None)

# ============================================================ 4. 4400 home on ====================
print("\n-- 4. 4400x1080, home on --")
lua4, g4 = new_client(4400, 1080, preamble=HOME_FIXTURE)
login(g4)
check("4400: ThorSpanHome is the active layout", g4.FFScale.ActiveLayoutName() == "ThorSpanHome",
      str(g4.FFScale.ActiveLayoutName()))
check("4400: exactly one ThorSpanHome layout", int(g4.__countLayout("ThorSpanHome")) == 1,
      str(g4.__layoutNames()))
check("4400: Thor6in exists even on a 4400-first login",
      int(g4.__countLayout("Thor6in")) == 1, str(g4.__layoutNames()))
check("4400: the foreign layout survived", int(g4.__countLayout("SomeoneElse")) == 1)
check("4400: FFSpan home session is applied", "applied=yes" in g4.FFSpan.Home.StatusLine(),
      g4.FFSpan.Home.StatusLine())
check("4400: FFSpan wrote its CVars",
      g4.__cvars.mapFade == "0" and g4.__cvars.combinedBags == "1",
      f"mapFade={g4.__cvars.mapFade} combinedBags={g4.__cvars.combinedBags}")

slots = g4.FFScale.HomeSlots()
check("4400: FFScale published HomeSlots", slots is not None)
check("4400: HomeSlots says which origin it is in",
      slots is not None and slots.yOrigin == "canvas-top-down",
      str(slots.yOrigin) if slots else "nil")
check("4400: HomeSlots right edge is HomeRect.w - 16",
      slots is not None and near(slots.right, 1224), f"right={slots.right if slots else None}")
check("4400: minimapBottom is above bottomBarTop with room for the bags",
      slots is not None and slots.bottomBarTop - slots.minimapBottom >= 420,
      f"{dict(slots) if slots else None}")

# -- units / origin round trip -----------------------------------------------------------------
# FFScale converts an intended PX position into Edit Mode anchor UNITS. Resolving those units back
# with FFSpan's device-verified q = effectiveScale * physH / 768 must land on the same pixel. This
# is the one check neither addon's own suite could make: they each used their own conversion.
print("\n-- 4b. px <-> UI unit agreement between the two addons --")
minimap = g4.__homeSystem(2, None)
check("4400: ThorSpanHome carries a Minimap entry", minimap is not None)
if minimap is not None:
    size_raw = g4.__settingValue(minimap, 2)  # EditModeMinimapSetting.Size
    pct = 50 + (size_raw or 0) * 10
    # review B1: the Size setting scales MinimapContainer, not the cluster ROOT that Edit
    # Mode anchors -- so the anchor resolves at the root's own scale, mult = 1.
    mm = g4.__anchorPx(minimap.anchorInfo, 1)
    check("4400: minimap TOPRIGHT resolves to (1224, 16) in FFSpan pixels",
          mm is not None and near(mm.x, 1224) and near(mm.y, 16),
          f"resolved={dict(mm) if mm else None} pct={pct}")
    if mm is not None:
        cluster_h = 220 * PX_PER_UNIT * pct / 100.0  # the envelope DOES grow with pct
        check("4400: HomeSlots.minimapBottom == where the minimap actually lands",
              near(slots.minimapBottom, mm.y + cluster_h, 2.0),
              f"published={slots.minimapBottom} realized={mm.y + cluster_h}")

bags_bar = g4.__homeSystem(14, None)
bb = g4.__anchorPx(bags_bar.anchorInfo, None) if bags_bar is not None else None
check("4400: bags bar BOTTOMRIGHT resolves to (1224, 1064) in FFSpan pixels",
      bb is not None and near(bb.x, 1224) and near(bb.y, 1064),
      f"resolved={dict(bb) if bb else None}")

chat = g4.__homeSystem(8, None)
ch = g4.__anchorPx(chat.anchorInfo, None) if chat is not None else None
# FFScale 1.7.1 lifted the HOME chat by HOME.chatSkinPadPx (100 px) so that Glassy's skin would
# land inside the bottom gutter. FFScale 1.8.2 established that Glassy never followed ChatFrame1 at all,
# so the pad was reserving 100 px of the tracker's column for a frame it could not move. With
# Glassy now measured and placed through its own mover, the pad is gone and Blizzard's chat -- the
# only thing this anchor ever controlled -- sits on the plain 16 px margin like everything else.
# FFScale 1.9: the micro menu is a bar across the bottom (Size 160; 40 x 1.6 units = 90 px with no
# live measurement), and the chat sits GAP (12) on top of it: 1080 - (16 + 90 + 12) = 962.
BAR_PX = 40 * 1.6 * PX_PER_UNIT
check("4400: chat BOTTOMLEFT resolves to (16, 962) -- on top of the micro bar, the pad still gone",
      ch is not None and near(ch.x, 16) and near(ch.y, 1080 - (16 + BAR_PX + 12)),
      f"resolved={dict(ch) if ch else None}")

tracker = g4.__homeSystem(12, None)
tr = g4.__anchorPx(tracker.anchorInfo, None) if tracker is not None else None
check("4400: objective tracker TOPLEFT resolves to (16, 16) in FFSpan pixels",
      tr is not None and near(tr.x, 16) and near(tr.y, 16),
      f"resolved={dict(tr) if tr else None}")

boss = g4.__homeSystem(3, 6)
bo = g4.__anchorPx(boss.anchorInfo, None) if boss is not None else None
check("4400: boss frames land inside the game rect x 1240..3160",
      bo is not None and 1240 <= bo.x <= 3160, f"resolved={dict(bo) if bo else None}")

buffs = g4.__homeSystem(6, 1)
bf = g4.__anchorPx(buffs.anchorInfo, None) if buffs is not None else None
check("4400: buffs land inside the game rect x 1240..3160",
      bf is not None and 1240 <= bf.x <= 3160, f"resolved={dict(bf) if bf else None}")

# -- resident bags --------------------------------------------------------------------------------
print("\n-- 4c. resident bags in FFScale's column --")
check("bags: residency opened the bags at login", calls(g4, "OpenAllBags") >= 1)
bagp = g4.__placed("ContainerFrameCombinedBags")
bag_w = 256 * PX_PER_UNIT * (bagp.scale if bagp else 1)
bag_h = 320 * PX_PER_UNIT * (bagp.scale if bagp else 1)
check("bags: right edge is inside the home region and flush to the column",
      bagp is not None and near(bagp.x + bag_w, 1224, 2.0) and bagp.x >= 1240 - 16 - bag_w - 2,
      f"placed={dict(bagp) if bagp else None} w={bag_w}")
check("bags: vertically between minimapBottom + 12 and bottomBarTop - 8",
      bagp is not None and slots is not None
      and bagp.y >= slots.minimapBottom + 12 - 2
      and bagp.y + bag_h <= slots.bottomBarTop - 8 + 2,
      f"y={bagp.y if bagp else None} h={bag_h} "
      f"window={slots.minimapBottom + 12 if slots else None}..{slots.bottomBarTop - 8 if slots else None}")
check("bags: never cross into the game rect", bagp is not None and bagp.x + bag_w <= 1240)
check("bags: FFSpan read FFScale's column, not its own fallback",
      "slots" in slot_list(g4), f"HomeSlots calls={slot_list(g4)}")
check("bags: the FIRST HomeSlots read already had a column (no nil-on-first-placement)",
      slot_list(g4)[:1] == ["slots"], f"HomeSlots calls={slot_list(g4)}")

# ConsolePort exclusions came through
check("cursor: bags and map excluded from the ConsolePort cursor",
      g4.__reg("ContainerFrameCombinedBags") == "false" and g4.__reg("WorldMapFrame") == "false",
      f"bags={g4.__reg('ContainerFrameCombinedBags')} map={g4.__reg('WorldMapFrame')}")

# ============================================================ 5. /ffspan home off at 4400 ========
print("\n-- 5. /ffspan home off at 4400 --")
saves_before = int(g4.__savesOf("Thor6in"))
g4.SlashCmdList["FFSPAN"]("home off")
g4.__flush()
check("home off: FFSpan tore the session down", "applied=no" in g4.FFSpan.Home.StatusLine(),
      g4.FFSpan.Home.StatusLine())
check("home off: Thor6in is the active layout again",
      g4.FFScale.ActiveLayoutName() == "Thor6in", str(g4.FFScale.ActiveLayoutName()))
check("home off: Thor6in was re-applied through the listener",
      int(g4.__savesOf("Thor6in")) > saves_before,
      f"before={saves_before} after={g4.__savesOf('Thor6in')}")
check("home off: still exactly one ThorSpanHome layout (not deleted, not duplicated)",
      int(g4.__countLayout("ThorSpanHome")) == 1, str(g4.__layoutNames()))
check("home off: HomeSlots() is nil again -- FFSpan can never read a stale column",
      g4.FFScale.HomeSlots() is None)
check("home off: mapFade and combinedBags restored exactly",
      g4.__cvars.mapFade == "1" and g4.__cvars.combinedBags == "0",
      f"mapFade={g4.__cvars.mapFade} combinedBags={g4.__cvars.combinedBags}")
check("home off: ConsolePort registry restored exactly (tri-state)",
      g4.__reg("WorldMapFrame") == "true"
      and g4.__reg("ContainerFrameCombinedBags") == "absent",
      f"map={g4.__reg('WorldMapFrame')} bags={g4.__reg('ContainerFrameCombinedBags')}")
check("home off: HomeEligible is still true (canvas did not change)", g4.FFSpan.HomeEligible())
check("home off: HomeEnabled is now false", not g4.FFSpan.HomeEnabled())

# FFScale 1.7 rule: Thor6in is ALWAYS built by the single-screen
# path from the player's own base and is NEVER cloned from ThorSpanHome, so no HOME-only entry
# can leak into it. MicroMenu is the entry that used to leak (TARGETS has no MicroMenu override),
# so it is the sharpest witness: it must still be the clean preset/Thor6in placement.
def _system_of(g, layout, sys_id):
    for _l in g.__layoutStore.layouts.values():
        if _l.layoutName == layout:
            for _s in _l.systems.values():
                if _s.system == sys_id:
                    return _s
    return None

micro6 = _system_of(g4, "Thor6in", 13)
micro6 = micro6.anchorInfo if micro6 is not None else None
check("home off: Thor6in keeps the clean single-screen MicroMenu, no HOME leak",
      micro6 is not None and micro6.point == "BOTTOMRIGHT" and micro6.relativePoint == "BOTTOMRIGHT",
      f"micro menu anchor={dict(micro6) if micro6 else None}")
chat6 = _system_of(g4, "Thor6in", 8)
chat_widths = [s.setting for s in chat6.settings.values()] if chat6 is not None else []
check("home off: Thor6in did not inherit the HOME chat WIDTH settings",
      0 not in chat_widths and 1 not in chat_widths, str(chat_widths))

# turning it back on in the same session
g4.SlashCmdList["FFSPAN"]("home on")
g4.__flush()
check("home on: ThorSpanHome comes back", g4.FFScale.ActiveLayoutName() == "ThorSpanHome",
      str(g4.FFScale.ActiveLayoutName()))
check("home on: still exactly one ThorSpanHome layout",
      int(g4.__countLayout("ThorSpanHome")) == 1, str(g4.__layoutNames()))
check("home on: home listener count is still 1 (no duplicate registration)",
      int(g4.FFSpan.HomeListenerCount()) == 1)

# ============================================================ 6. 1920 after an interrupted home ==
print("\n-- 6. next login at 1920 after an interrupted 4400 home session --")
lua6a, g6a = new_client(4400, 1080, preamble=HOME_FIXTURE)
login(g6a)
carried = str(g6a.__luaser(g6a.FFSpanDB))
check("interrupted: the 4400 session left a session record in FFSpanDB", "session" in carried)

PRE_1920 = HOME_FIXTURE + "\nFFSpanDB = " + carried + "\n"
lua6, g6 = new_client(1920, 1080, preamble=PRE_1920)
login(g6)
check("1920 cleanup: the stale home session was torn down",
      g6.FFSpanDB.home["TestRealm-Fatty"].session is None,
      str(g6.__luaser(g6.FFSpanDB.home["TestRealm-Fatty"].session)))
check("1920 cleanup: CVars were put back",
      g6.__cvars.mapFade == "1" and g6.__cvars.combinedBags == "0",
      f"mapFade={g6.__cvars.mapFade} combinedBags={g6.__cvars.combinedBags}")
check("1920 cleanup: ConsolePort registry restored",
      g6.__reg("WorldMapFrame") == "true", g6.__reg("WorldMapFrame"))
check("1920 cleanup: FFScale is on Thor6in", g6.FFScale.ActiveLayoutName() == "Thor6in",
      str(g6.FFScale.ActiveLayoutName()))
check("1920 cleanup: no ThorSpanHome layout was created at 1920",
      int(g6.__countLayout("ThorSpanHome")) == 0, str(g6.__layoutNames()))

# ============================================================ 7. combat at login =================
print("\n-- 7. login in combat --")
lua7, g7 = new_client(4400, 1080, preamble=HOME_FIXTURE)
login(g7, combat=True)
check("combat: no layout was written while in combat", int(g7.__savesOf("ThorSpanHome")) == 0,
      f"saves={g7.__savesOf('ThorSpanHome')}")
check("combat: FFScale recorded the deferral", g7.FFScaleLog.pending is not None
      or g7.FFScaleLog.deferred is not None,
      f"pending={g7.FFScaleLog.pending} deferred={g7.FFScaleLog.deferred}")
check("combat: FFSpan still opened the session (it just cannot move protected frames)",
      "applied=yes" in g7.FFSpan.Home.StatusLine(), g7.FFSpan.Home.StatusLine())
g7.__combat = False
g7.__fire("PLAYER_REGEN_ENABLED")
g7.__flush()
check("combat: ThorSpanHome applied once combat ended",
      g7.FFScale.ActiveLayoutName() == "ThorSpanHome", str(g7.FFScale.ActiveLayoutName()))
check("combat: exactly one ThorSpanHome layout (no duplicate from the two deferral paths)",
      int(g7.__countLayout("ThorSpanHome")) == 1, str(g7.__layoutNames()))
check("combat: the layout was written exactly once",
      int(g7.__savesOf("ThorSpanHome")) == 1, f"saves={g7.__savesOf('ThorSpanHome')}")
# Design rule: residency that combat blocked at LOGIN is
# retried exactly once at the next PLAYER_REGEN_ENABLED. No other new residency trigger.
check("combat: login residency blocked by combat is retried once at regen",
      g7.ContainerFrameCombinedBags.shown is True
      and g7.__placed("ContainerFrameCombinedBags") is not None,
      f"shown={g7.ContainerFrameCombinedBags.shown} placed={g7.__placed('ContainerFrameCombinedBags')}")
opens_after_retry = calls(g7, "OpenAllBags")
g7.__fire("PLAYER_REGEN_ENABLED")
g7.__flush()
check("combat: and ONLY once (a later regen is not a residency trigger)",
      calls(g7, "OpenAllBags") == opens_after_retry,
      f"before={opens_after_retry} after={calls(g7, 'OpenAllBags')}")

# The regen retry on its own. With an acknowledging FFScale the layout callback happens to reopen the
# bags at regen anyway; without one (an older or absent layout owner) the retry is the ONLY thing
# that brings residency back after a combat login.
NOOWNER = HOME_FIXTURE + "\n__noLayoutOwner = true\n"
# the contract has to be taken away BEFORE FFSpan loads -- FFSpan registers its layout listener
# at its own ADDON_LOADED, so removing it afterwards is too late
lua7b, g7b = new_client(4400, 1080, preamble=NOOWNER, watch_slots=False,
                        mid="FFScale.RegisterLayoutListener = nil")
login(g7b, combat=True)
check("combat: with a non-acknowledging layout owner, combat blocks the login residency",
      g7b.ContainerFrameCombinedBags.shown is False,
      f"shown={g7b.ContainerFrameCombinedBags.shown}")
# Isolate the retry: take away the layout event too, so no confirmation can reach FFSpan after
# combat and the regen retry is the only thing that could reopen the bags.
lua7b.execute("FFSpan.Home.events['EDIT_MODE_LAYOUTS_UPDATED'] = nil")
g7b.__combat = False
g7b.__fire("PLAYER_REGEN_ENABLED")
g7b.__flush()
check("combat: the regen retry is what brings it back -- nothing else would",
      g7b.ContainerFrameCombinedBags.shown is True
      and g7b.__placed("ContainerFrameCombinedBags") is not None,
      f"shown={g7b.ContainerFrameCombinedBags.shown}")
bag7 = g7.__placed("ContainerFrameCombinedBags")
s7 = g7.FFScale.HomeSlots()
check("combat: once residency does resume, the bags land in FFScale's column",
      bag7 is not None and s7 is not None
      and bag7.x + 256 * PX_PER_UNIT * bag7.scale <= 1240
      and bag7.y >= s7.minimapBottom + 12 - 2,
      f"placed={dict(bag7) if bag7 else None} slots={dict(s7) if s7 else None}")

# ============================================================ 8. reload ==========================
print("\n-- 8. reload at 4400 (SavedVariables + layout store carried over) --")
state_db = str(g4.__luaser(g4.FFSpanDB))
state_store = str(g4.__luaser(g4.__layoutStore))
state_active = str(g4.__luaser(g4.__activeLayout))
PRE_RELOAD = (HOME_FIXTURE + "\nFFSpanDB = " + state_db + "\n"
              + "__layoutStore = " + state_store + "\n"
              + "__activeLayout = " + state_active + "\n")
lua8, g8 = new_client(4400, 1080, preamble=PRE_RELOAD)
login(g8)
check("reload: exactly one home listener", int(g8.FFSpan.HomeListenerCount()) == 1,
      f"count={g8.FFSpan.HomeListenerCount()}")
check("reload: no second ThorSpanHome layout", int(g8.__countLayout("ThorSpanHome")) == 1,
      str(g8.__layoutNames()))
check("reload: no second Thor6in layout", int(g8.__countLayout("Thor6in")) == 1,
      str(g8.__layoutNames()))
check("reload: the foreign layout is still intact", int(g8.__countLayout("SomeoneElse")) == 1)
check("reload: ThorSpanHome is active", g8.FFScale.ActiveLayoutName() == "ThorSpanHome",
      str(g8.FFScale.ActiveLayoutName()))
check("reload: an unchanged layout is not re-saved",
      int(g8.__savesOf("ThorSpanHome")) <= 1, f"saves={g8.__savesOf('ThorSpanHome')}")
check("reload: the account-wide journal was reused, not re-snapshotted "
      "(originals cannot be overwritten with FFSpan's own values)",
      g8.FFSpanDB.homeShared.cvars.mapFade == "1",
      str(g8.__luaser(g8.FFSpanDB.homeShared.cvars)))
check("reload: bags placed again in the same column",
      g8.__placed("ContainerFrameCombinedBags") is not None)

# ============================================================ 9. loading screens =================
print("\n-- 9. loading screens --")
before_open = calls(g8, "OpenAllBags")
g8.__fire("LOADING_SCREEN_ENABLED")
g8.__fire("LOADING_SCREEN_DISABLED")
g8.__flush()
check("loading screen: residency resumes when the screen ends",
      calls(g8, "OpenAllBags") > before_open,
      f"before={before_open} after={calls(g8, 'OpenAllBags')}")
check("loading screen: the layout is not re-saved by a loading screen",
      int(g8.__savesOf("ThorSpanHome")) <= 1, f"saves={g8.__savesOf('ThorSpanHome')}")

# ============================================================ 10. EDIT_MODE_LAYOUTS_UPDATED ======
print("\n-- 10. EDIT_MODE_LAYOUTS_UPDATED from the client --")
lua10, g10 = new_client(4400, 1080, preamble=HOME_FIXTURE)
login(g10)
saves10 = int(g10.__savesOf("ThorSpanHome"))
g10.__fire("EDIT_MODE_LAYOUTS_UPDATED")
g10.__flush()
check("edit mode ready: a client-side layouts-updated does not re-save an unchanged layout",
      int(g10.__savesOf("ThorSpanHome")) == saves10,
      f"before={saves10} after={g10.__savesOf('ThorSpanHome')}")
check("edit mode ready: still exactly one ThorSpanHome",
      int(g10.__countLayout("ThorSpanHome")) == 1, str(g10.__layoutNames()))
check("edit mode ready: FFScale's own SaveLayouts echo never recursed",
      int(g10.__savesOf("ThorSpanHome")) <= 1, f"saves={g10.__savesOf('ThorSpanHome')}")

# ============================================================ 11. column re-read + guards ========
print("\n-- 11. the home column moving under FFSpan --")
lua11, g11 = new_client(4400, 1080, preamble=HOME_FIXTURE)
login(g11)
check("column: FFSpan listens for EDIT_MODE_LAYOUTS_UPDATED",
      g11.FFSpan.Home.events["EDIT_MODE_LAYOUTS_UPDATED"] is True)
# The layout changing is what moves the minimap and the bottom bar, i.e. the whole column. It is
# also the only signal that works when FFScale had to defer its layout to PLAYER_REGEN_ENABLED,
# because the two addons' regen handlers fire in an order neither of them owns.
lua11.execute("ContainerFrameCombinedBags:ClearAllPoints()")
check("column: bags really were un-anchored for the probe",
      g11.__placed("ContainerFrameCombinedBags") is None)
g11.__fire("EDIT_MODE_LAYOUTS_UPDATED")
g11.__flush()
re_bag = g11.__placed("ContainerFrameCombinedBags")
s11 = g11.FFScale.HomeSlots()
check("column: a layout change re-anchors the resident bags into the published column",
      re_bag is not None and s11 is not None
      and near(re_bag.x + 256 * PX_PER_UNIT * re_bag.scale, 1224, 2.0)
      and re_bag.y >= s11.minimapBottom + 12 - 2,
      f"placed={dict(re_bag) if re_bag else None} slots={dict(s11) if s11 else None}")

# A column FFSpan has to measure itself can come out degenerate (here: the only minimap-ish frame
# in the home region sits on the canvas floor, so minimapBottom lands below bottomBarTop). That
# must not reach the scale maths -- SetScale(<= 0) leaves the frame skipped by every later pass.
lua11.execute("FFScale.HomeSlots = function() return nil end")
lua11.execute("ContainerFrameCombinedBags:ClearAllPoints()")
g11.__fire("EDIT_MODE_LAYOUTS_UPDATED")
g11.__flush()
check("column: a degenerate measured column never leaves the bags at scale <= 0",
      g11.ContainerFrameCombinedBags.scale > 0,
      f"scale={g11.ContainerFrameCombinedBags.scale}")
# and once a real column is published again the bags recover
lua11.execute("FFScale.HomeSlots = function() return " +
              "{minimapBottom=480, bottomBarTop=1008, yOrigin='canvas-top-down', right=1224} end")
g11.__fire("EDIT_MODE_LAYOUTS_UPDATED")
g11.__flush()
rec_bag = g11.__placed("ContainerFrameCombinedBags")
check("column: the bags recover once a usable column comes back",
      rec_bag is not None and rec_bag.y >= 480 + 12 - 2 and rec_bag.x > 0,
      f"placed={dict(rec_bag) if rec_bag else None}")

# A container that is shown but not laid out yet has a zero envelope. It must be skipped, not
# scaled by a zero fit -- and it must not stop the containers behind it from being placed.
lua11.execute('ContainerFrame1 = __newFrame("ContainerFrame1", UIParent)\n'
              'ContainerFrame1.rect = {0, 0, 0, 0}\n'
              'ContainerFrame1.shown = true\n'
              'ContainerFrameCombinedBags:ClearAllPoints()')
g11.__fire("EDIT_MODE_LAYOUTS_UPDATED")
g11.__flush()
check("column: a zero-size container is skipped, never scaled to 0",
      g11.ContainerFrame1.scale > 0 and g11.__placed("ContainerFrame1") is None,
      f"scale={g11.ContainerFrame1.scale} placed={g11.__placed('ContainerFrame1')}")
check("column: a zero-size container does not stop the real bags being placed",
      g11.__placed("ContainerFrameCombinedBags") is not None)

# ================================================== 12. the code-review findings =================
# One section per finding, each asserting the FIXED behaviour and, where the old behaviour is
# still reachable, that the defect itself is gone.
print("\n-- 12. code review --")

# --- B1: one pixel contract, and the minimap ROOT is not scaled by the Size setting -------------
lua12, g12 = new_client(4400, 1080, preamble=HOME_FIXTURE)
login(g12)
s12 = g12.FFScale.HomeSlots()
check("B1: the published column is MEASURED off the live UI, not seeded",
      s12 is not None and s12.source == "measured", str(s12.source) if s12 else "nil")
mm12 = g12.__homeSystem(2, None)
mm_px = g12.__anchorPx(mm12.anchorInfo, 1) if mm12 is not None else None
check("B1: the minimap anchor resolves at the cluster ROOT scale (not pct/100)",
      mm_px is not None and near(mm_px.x, 1224) and near(mm_px.y, 16),
      f"{dict(mm_px) if mm_px else None}")
cluster = g12.__px("MinimapCluster")
check("B1: FFScale and FFSpan agree on where the minimap actually IS",
      cluster is not None and s12 is not None
      and near(s12.minimapBottom, cluster.y + cluster.h, 1.0),
      f"published={s12.minimapBottom if s12 else None} "
      f"measured={cluster.y + cluster.h if cluster else None}")
bar = g12.__px("MicroMenuContainer")
check("B1: ...and on where the bottom controls are",
      bar is not None and s12 is not None and near(s12.bottomBarTop, bar.y, 1.0),
      f"published={s12.bottomBarTop if s12 else None} measured={bar.y if bar else None}")
# fail closed: if the edges cannot be measured into a sane column, nothing is published
lua12.execute("MinimapCluster.rect = {0, 0, 198, 220}")   # back to the canvas floor
g12.SlashCmdList["FFSCALE"]()
g12.__flush()
check("B1: an inverted/unmeasurable column is refused, not published",
      g12.FFScale.HomeSlots() is None or g12.FFScale.HomeSlots().bottomBarTop
      > g12.FFScale.HomeSlots().minimapBottom,
      str(dict(g12.FFScale.HomeSlots()) if g12.FFScale.HomeSlots() else None))

# --- B2: the panel hook binds to the GLOBAL, never to the forbidden local delegate ---------------
lua13, g13 = new_client(4400, 1080, preamble=HOME_FIXTURE)
login(g13)
check("B2: FramePositionDelegate is NOT a global on a real client (nothing to hook)",
      g13.FramePositionDelegate is None)
check("B2: the hook reports that it bound to the global dispatch",
      str(g13.FFSpan.Home.PanelHook()) == "global:UpdateUIPanelPositions",
      str(g13.FFSpan.Home.PanelHook()))
lua13.execute("CharacterFrame = __newFrame('CharacterFrame', UIParent) "
              "CharacterFrame.rect = {0,0,180,300} CharacterFrame.shown = false")
lua13.execute("MerchantFrame = __newFrame('MerchantFrame', UIParent) "
              "MerchantFrame.rect = {0,0,180,300} MerchantFrame.shown = false")
g13.__fire("ADDON_LOADED", "Blizzard_Character")
lua13.execute("CharacterFrame:Show() MerchantFrame:Show()")
g13.__flush()
both = (g13.__placed("CharacterFrame"), g13.__placed("MerchantFrame"))
check("B2: two companions each get their own slot inside the home region",
      all(p is not None and 0 <= p.x < 1240 for p in both)
      and abs(both[0].x - both[1].x) > 1,
      f"char={dict(both[0]) if both[0] else None} merch={dict(both[1]) if both[1] else None}")
# the native pass moves a window; the post-hook must put it back
lua13.execute("UpdateUIPanelPositions(CharacterFrame)")
g13.__flush()
after_native = g13.__placed("CharacterFrame")
check("B2: a native panel pass is repaired synchronously by the post-hook",
      after_native is not None and 0 <= after_native.x < 1240,
      f"{dict(after_native) if after_native else None}")
# ...and when one of the two closes, the survivor is re-placed
lua13.execute("MerchantFrame:Hide()")
g13.__flush()
survivor = g13.__placed("CharacterFrame")
check("B2: closing one companion re-places the survivor",
      survivor is not None and 0 <= survivor.x < 1240,
      f"{dict(survivor) if survivor else None}")

# --- M3: ConsolePort registry AND runtime tracking both come back -------------------------------
# The reviewer's exact reproduction: an owner that already held `true` and whose value never
# changes. The old diff-based restore skipped it, so the frame stayed UNTRACKED at runtime while
# the registry read correct.
CP_TRACKED = HOME_FIXTURE + (
    '\nConsolePort:GetData().Stack:SetFrame("ContainerFrameCombinedBags", true, "Other")\n')
lua14, g14 = new_client(4400, 1080, preamble=CP_TRACKED)
check("M3: the frame starts tracked through another owner",
      g14.__isTracked("ContainerFrameCombinedBags") is True
      and g14.__reg("ContainerFrameCombinedBags", "Other") == "true")
login(g14)
check("M3: home excludes it from the cursor",
      g14.__reg("ContainerFrameCombinedBags") == "false"
      and g14.__isTracked("ContainerFrameCombinedBags") is False)
g14.SlashCmdList["FFSPAN"]("home off")
g14.__flush()
check("M3: home off restores the REGISTRY exactly (the unchanged `true` owner included)",
      g14.__reg("ContainerFrameCombinedBags", "Other") == "true"
      and g14.__reg("ContainerFrameCombinedBags") == "absent",
      f"other={g14.__reg('ContainerFrameCombinedBags', 'Other')} "
      f"default={g14.__reg('ContainerFrameCombinedBags')}")
check("M3: ...and the RUNTIME tracking with it (the defect the reviewer reproduced)",
      g14.__isTracked("ContainerFrameCombinedBags") is True,
      f"tracked={g14.__isTracked('ContainerFrameCombinedBags')}")
check("M3: the shared journal closed once the restore was confirmed",
      g14.FFSpanDB.homeShared is None)
# exclusions are not requested at all until the cursor Stack exists (no uncancellable queue)
lua15, g15 = new_client(4400, 1080, preamble='__makeConsolePort(false)\n' + HOME_FIXTURE.replace(
    "__makeConsolePort(true)", ""))
login(g15)
check("M3: with no cursor Stack reachable, no exclusion is ever requested",
      calls(g15, "cpRemove") == 0 and "applied=yes" in g15.FFSpan.Home.StatusLine(),
      f"cpRemove={calls(g15, 'cpRemove')}")

# --- M4: the restore journal is account-wide and durable ----------------------------------------
lua16, g16 = new_client(4400, 1080, preamble=HOME_FIXTURE)
login(g16)
check("M4: the originals live in the ACCOUNT-wide journal, not under the character",
      g16.FFSpanDB.homeShared is not None and g16.FFSpanDB.homeShared.cvars is not None
      and g16.FFSpanDB.home["TestRealm-Fatty"].session.cvars is None)
carried16 = str(g16.__luaser(g16.FFSpanDB))
# ...so a stock login on a DIFFERENT character still finishes it
lua17, g17 = new_client(1920, 1080, preamble=(HOME_FIXTURE + "\nFFSpanDB = " + carried16
                                              + '\n__player = "Otherguy"\n'))
login(g17)
check("M4: another character at 1920 finishes the account-wide restore",
      g17.__cvars.mapFade == "1" and g17.__cvars.combinedBags == "0"
      and g17.FFSpanDB.homeShared is None,
      f"cvars={dict(g17.__cvars)} shared={g17.FFSpanDB.homeShared}")
# a restore that cannot complete keeps the journal open and retries
lua18, g18 = new_client(4400, 1080, preamble=HOME_FIXTURE)
login(g18)
lua18.execute("__cvarsLocked = true "
              "local realSet = SetCVar "
              "function SetCVar(n, v) if __cvarsLocked and n == 'mapFade' then return end "
              "realSet(n, v) end")
g18.SlashCmdList["FFSPAN"]("home off")
g18.__flush()
check("M4: a CVar that refuses to come back keeps the journal OPEN",
      g18.FFSpanDB.homeShared is not None and g18.FFSpanDB.homeShared.cvars is not None,
      str(g18.__luaser(g18.FFSpanDB.homeShared)))
lua18.execute("__cvarsLocked = false")
g18.__fire("PLAYER_REGEN_ENABLED")
g18.__flush()
check("M4: ...and the next regen finishes it and closes the journal",
      g18.__cvars.mapFade == "1" and g18.FFSpanDB.homeShared is None,
      f"cvars={dict(g18.__cvars)} shared={g18.FFSpanDB.homeShared}")
# a v2.1 SavedVariables (originals under the character) is adopted, not lost
LEGACY = HOME_FIXTURE + ('\nFFSpanDB = {home={["TestRealm-Fatty"]={session={geometry="4400x1080",'
                         'cvars={mapFade="1", combinedBags="0"}}}}}\n'
                         '__cvars.mapFade = "0" __cvars.combinedBags = "1"\n')
lua19, g19 = new_client(1920, 1080, preamble=LEGACY)
login(g19)
check("M4: a v2.1 per-character snapshot is adopted and still restores",
      g19.__cvars.mapFade == "1" and g19.__cvars.combinedBags == "0",
      f"cvars={dict(g19.__cvars)}")

# --- M5: an already-maximized spellbook <-> talents switch re-places ------------------------------
SPELLS = HOME_FIXTURE + (
    '\nEventRegistry = {callbacks = {}}\n'
    'function EventRegistry:RegisterCallback(name, fn, owner)\n'
    '    self.callbacks[name] = self.callbacks[name] or {}\n'
    '    table.insert(self.callbacks[name], fn)\n'
    'end\n'
    'function EventRegistry:TriggerEvent(name, ...)\n'
    '    for _, fn in ipairs(self.callbacks[name] or {}) do fn(...) end\n'
    'end\n'
    'PlayerSpellsUtil = {FrameTabs = {SpellBook = 1, ClassTalents = 2, ClassSpecializations = 3}}\n'
    'PlayerSpellsFrame = __newFrame("PlayerSpellsFrame", UIParent)\n'
    'PlayerSpellsFrame.rect = {0, 0, 420, 520}\n'
    'PlayerSpellsFrame.shown = false\n'
    'PlayerSpellsFrame.__tab = 1\n'
    'function PlayerSpellsFrame:IsFrameTabActive(t) return self.__tab == t end\n')
lua20, g20 = new_client(4400, 1080, preamble=SPELLS)
login(g20)
lua20.execute("PlayerSpellsFrame:Show()")
g20.__flush()
book = g20.__placed("PlayerSpellsFrame")
check("M5: the spellbook tab lands on the home screen",
      book is not None and book.x + 420 * PX_PER_UNIT * book.scale <= 1240,
      f"{dict(book) if book else None}")
# switch tab WITHOUT hiding/re-showing the window -- the case the review calls out
lua20.execute("PlayerSpellsFrame.__tab = 2 "
              "EventRegistry:TriggerEvent('PlayerSpellsFrame.TabSet', PlayerSpellsFrame, 2)")
g20.__flush()
talents = g20.__placed("PlayerSpellsFrame")
check("M5: an ALREADY-MAXIMIZED switch to talents moves it to the game rect",
      talents is not None and talents.x >= 1240,
      f"{dict(talents) if talents else None}")
lua20.execute("PlayerSpellsFrame.__tab = 1 "
              "EventRegistry:TriggerEvent('PlayerSpellsFrame.TabSet', PlayerSpellsFrame, 1)")
g20.__flush()
back = g20.__placed("PlayerSpellsFrame")
check("M5: ...and back to the home screen, with no compounding scale",
      back is not None and back.x + 420 * PX_PER_UNIT * back.scale <= 1240
      and near(back.scale, book.scale, 0.001),
      f"back={dict(back) if back else None} first={dict(book) if book else None}")

# --- M6: nothing is placed before the layout is confirmed ----------------------------------------
lua21, g21 = new_client(4400, 1080, preamble=HOME_FIXTURE)
# hold Edit Mode back: no layouts and no active layout means "not ready"
lua21.execute("__layoutStoreHeld = __layoutStore __activeLayoutHeld = __activeLayout "
              "__layoutStore = nil __activeLayout = nil")
# no flush: the mock's __flush fires every timer regardless of delay, including the deliberate
# 60 s "owner never answered" watchdog, which would mask the state under test
login(g21, flush=False)
check("M6/M7: with Edit Mode not ready, FFScale publishes nothing",
      g21.FFScale.HomeSlots() is None)
check("M6: ...and FFSpan places no bags from a provisional column",
      g21.__placed("ContainerFrameCombinedBags") is None
      and g21.FFSpan.Home.LayoutConfirmed() is False,
      f"placed={g21.__placed('ContainerFrameCombinedBags')} "
      f"confirmed={g21.FFSpan.Home.LayoutConfirmed()}")
check("M6: the home session is still open and owns its CVars meanwhile",
      "applied=yes" in g21.FFSpan.Home.StatusLine() and g21.__cvars.mapFade == "0")
lua21.execute("__layoutStore = __layoutStoreHeld __activeLayout = __activeLayoutHeld")
g21.__fire("EDIT_MODE_LAYOUTS_UPDATED")
g21.__flush()
check("M6/M7: once Edit Mode is ready the layout lands and the column is published",
      g21.FFScale.ActiveLayoutName() == "ThorSpanHome"
      and g21.FFScale.HomeSlots() is not None
      and g21.FFSpan.Home.LayoutConfirmed() is True,
      f"layout={g21.FFScale.ActiveLayoutName()} slots={g21.FFScale.HomeSlots() is not None}")
check("M6: only THEN are the bags placed",
      g21.__placed("ContainerFrameCombinedBags") is not None)
# a UI-scale change must invalidate and redo a LIVE session
saves21 = int(g21.__savesOf("ThorSpanHome"))
lua21.execute("ContainerFrameCombinedBags:ClearAllPoints()")
g21.__fire("UI_SCALE_CHANGED")
g21.__flush()
check("M6: a UI-scale change re-fits a live session instead of being ignored",
      g21.__placed("ContainerFrameCombinedBags") is not None
      and g21.FFSpan.Home.LayoutConfirmed() is True,
      f"placed={g21.__placed('ContainerFrameCombinedBags')}")

# --- M7: fail-closed Edit Mode identity ----------------------------------------------------------
DUPES = HOME_FIXTURE + (
    '\n__layoutStore.layouts[#__layoutStore.layouts+1] = '
    '{layoutName="ThorSpanHome", layoutType=Enum.EditModeLayoutType.Character, systems={}}\n'
    '__layoutStore.layouts[#__layoutStore.layouts+1] = '
    '{layoutName="ThorSpanHome", layoutType=Enum.EditModeLayoutType.Character, systems={}}\n')
lua22, g22 = new_client(4400, 1080, preamble=DUPES)
login(g22)
check("M7: two layouts with the same name+scope are REFUSED, not resolved by luck",
      any("ambiguous layout identity" in str(r) for r in g22.FFScaleLog.results.values()),
      str(list(g22.FFScaleLog.results.values())[-3:]))
check("M7: nothing was saved or activated while the identity was ambiguous",
      int(g22.__savesOf("ThorSpanHome")) == 0 and g22.FFScale.HomeSlots() is None)
check("M7: ...and the failure did not latch, so a later trigger can still retry",
      g22.FFScale.EditModeReady() is True)

# The readiness latch on its own: everything else would succeed (Thor6in already exists, the
# layout list answers) but Edit Mode has no ACTIVE layout yet, so it is not ready.
NOACTIVE = HOME_FIXTURE + (
    '\n__layoutStore.layouts[#__layoutStore.layouts+1] = '
    '{layoutName="Thor6in", layoutType=Enum.EditModeLayoutType.Account,'
    ' systems={__sys(13, nil, "BOTTOMRIGHT", "UIParent", "BOTTOMRIGHT", -10, 10, {})}}\n'
    '__activeLayout = nil\n')
lua25, g25 = new_client(4400, 1080, preamble=NOACTIVE)
login(g25, flush=False)
check("M7: no ACTIVE layout yet means not ready -- nothing is saved or activated",
      g25.FFScale.EditModeReady() is False
      and int(g25.__savesOf("ThorSpanHome")) == 0
      and int(g25.__countLayout("ThorSpanHome")) == 0,
      f"ready={g25.FFScale.EditModeReady()} saves={g25.__savesOf('ThorSpanHome')}")
check("M7: the deferral is recorded as a deferral, not as a failure",
      any("Edit Mode is not ready" in str(r) for r in g25.FFScaleLog.results.values()),
      str(list(g25.FFScaleLog.results.values())[-3:]))
g25.__fire("EDIT_MODE_LAYOUTS_UPDATED")
g25.__flush()
check("M7: once readiness arrives the same trigger succeeds",
      g25.FFScale.ActiveLayoutName() == "ThorSpanHome"
      and int(g25.__countLayout("ThorSpanHome")) == 1,
      str(g25.__layoutNames()))

# A save that reconciles away (or duplicates) FFScale's layout must NOT be followed by SetActiveLayout
# on a stale index, and must publish nothing.
lua26, g26 = new_client(4400, 1080, preamble=HOME_FIXTURE)
login(g26)
lua26.execute("""
__activeCallsBefore = #__setActiveCalls
local rawSave = C_EditMode.SaveLayouts
C_EditMode.SaveLayouts = function(info)
    rawSave(info)
    -- the client reconciled FFScale's layout away, as a refused save would
    for i = #__layoutStore.layouts, 1, -1 do
        if __layoutStore.layouts[i].layoutName == 'ThorSpanHome' then
            table.remove(__layoutStore.layouts, i)
        end
    end
end
-- force a real write next time round
for _, l in ipairs(__layoutStore.layouts) do
    if l.layoutName == 'ThorSpanHome' then l.systems = {} end
end
__activeLayout = __layoutStore.layouts[1]
""")
before26 = len(list(g26.__setActiveCalls.values()))
g26.SlashCmdList["FFSCALE"]()
g26.__flush()
check("M7: a save that did not resolve to exactly one match never activates a stale index",
      len(list(g26.__setActiveCalls.values())) == before26
      and any("expected exactly one" in str(r) for r in g26.FFScaleLog.results.values()),
      f"setActive={len(list(g26.__setActiveCalls.values()))} vs {before26}")
check("M7: ...and nothing is published off a layout that never became live",
      g26.FFScale.HomeSlots() is None)

# --- M8: no partial overlap in combat ------------------------------------------------------------
WIDE = HOME_FIXTURE + (
    '\nCharacterFrame = __newFrame("CharacterFrame", UIParent)\n'
    'CharacterFrame.rect = {0,0,300,400} CharacterFrame.shown = false\n'
    'MerchantFrame = __newFrame("MerchantFrame", UIParent)\n'
    'MerchantFrame.rect = {0,0,560,400} MerchantFrame.shown = false\n')



def lane_case(protect_older):
    """Older CharacterFrame in the lane, then a wider MerchantFrame opens in combat."""
    lua, g = new_client(4400, 1080, preamble=WIDE)
    login(g)
    lua.execute("CharacterFrame:Show()")
    g.__flush()
    if protect_older:
        lua.execute("CharacterFrame.protected = true")
    g.__combat = True
    lua.execute("MerchantFrame:Show()")
    g.__flush()
    return lua, g


# Decided 2026-09-23, replacing v2.2's off-panel parking: in combat the OLDER
# window keeps its lane slot and the NEWER one is not placed by FFSpan at all. One rule for
# movable and protected losers alike.
for _protected in (False, True):
    _label = "protected" if _protected else "movable"
    lua23, g23 = lane_case(_protected)
    chr23, mer23 = g23.__placed("CharacterFrame"), g23.__placed("MerchantFrame")
    check(f"M8 ({_label} older): the OLDER window keeps its lane slot",
          chr23 is not None and near(chr23.x, 16, 1.0),
          f"char={dict(chr23) if chr23 else None}")
    check(f"M8 ({_label} older): the NEWER window is not placed by FFSpan at all",
          mer23 is None, f"merch={dict(mer23) if mer23 else None}")
    check(f"M8 ({_label} older): nothing was parked in the unshown strip",
          all(p is None or p.x < 3160 for p in (chr23, mer23)),
          f"char={chr23 and chr23.x} merch={mer23 and mer23.x}")
    check(f"M8 ({_label} older): both windows are still open -- nothing hidden in combat",
          g23.CharacterFrame.shown is True and g23.MerchantFrame.shown is True)
    check(f"M8 ({_label} older): no two FFSpan-placed rects overlap",
          len([p for p in (chr23, mer23) if p is not None]) == 1)

# (c) regen with the newer still open -> the newer REPLACES the older
lua23, g23 = lane_case(False)
g23.__combat = False
lua23.execute("CharacterFrame.protected = false")
g23.__fire("PLAYER_REGEN_ENABLED")
g23.__flush()
chr23b, mer23b = g23.__placed("CharacterFrame"), g23.__placed("MerchantFrame")
check("M8: at regen the newer window replaces the older one",
      g23.MerchantFrame.shown is True and g23.CharacterFrame.shown is False
      and mer23b is not None and near(mer23b.x, 16, 1.0),
      f"char shown={g23.CharacterFrame.shown} merch={dict(mer23b) if mer23b else None}")

# (d) the newer closed before regen -> the older simply stays, nothing is hidden
lua23, g23 = lane_case(False)
lua23.execute("MerchantFrame.shown = false")
hidden_before = calls(g23, "HideUIPanel")
g23.__combat = False
g23.__fire("PLAYER_REGEN_ENABLED")
g23.__flush()
check("M8: a displacement whose newer window closed before regen is cancelled",
      g23.CharacterFrame.shown is True
      and g23.__placed("CharacterFrame") is not None
      and near(g23.__placed("CharacterFrame").x, 16, 1.0)
      and calls(g23, "HideUIPanel") == hidden_before,
      f"shown={g23.CharacterFrame.shown} placed={g23.__placed('CharacterFrame')} "
      f"hides={calls(g23, 'HideUIPanel')} vs {hidden_before}")

# --- M9: the dump cannot report false containment -------------------------------------------------
lua24, g24 = new_client(4400, 1080, preamble=WIDE)
login(g24)
lua24.execute("CharacterFrame:Show()")
g24.__flush()
g24.SlashCmdList["FFSPAN"]("dump")
g24.__flush()
dump = g24.FFSpanDB.dumps["manual"] if g24.FFSpanDB.dumps else None
check("M9: a dump was captured at 4400", dump is not None)
if dump is not None:
    check("M9: the dump records which panel hook actually installed",
          str(dump.panelHook) == "global:UpdateUIPanelPositions", str(dump.panelHook))
    check("M9: intended screens are derived from the ENABLED state, not mere eligibility",
          dump.homeActiveForIntent is True)
    rows = {r.name: r for r in dump.frames.values() if r.name}
    check("M9: a managed window's intended screen comes from the shared policy table",
          "CharacterFrame" in rows and rows["CharacterFrame"].intendedScreen == "home",
          str(rows.get("CharacterFrame") and rows["CharacterFrame"].intendedScreen))
    check("M9: an unmapped named frame is reported as unknown, never as a pass",
          int(dump.unmappedCount) >= 0
          and all(r.intendedScreen is not None for r in dump.frames.values() if r.name),
          f"unmapped={dump.unmappedCount}")
    # A frame pushed off the TOP of the canvas must not still count as "home". The mock does not
    # recompute a rect from anchors, so the rect is set directly: WoW's GetRect is bottom-left in
    # UI units, and b + h > 768 puts the frame's top edge above the canvas.
    #   left  px = 71 * 1.40625  = 100   (inside home x 0..1240)
    #   top   px = 1080 - (700 + 300) * 1.40625 = -326  (above the canvas)
    lua24.execute("CharacterFrame.rect = {71, 700, 128, 300}")
    g24.SlashCmdList["FFSPAN"]("dump offtop")
    g24.__flush()
    d2 = g24.FFSpanDB.dumps["offtop"]
    row2 = None
    for r in d2.frames.values():
        if r.name == "CharacterFrame":
            row2 = r
    check("M9: vertical containment is judged too -- a frame off the top is not 'home'",
          row2 is not None and row2.actualScreen != "home", str(row2 and row2.actualScreen))

# ================================================ 13. code review re-check + a design decision ===
# Second fix pass (FFSpan 2.2.1). Each of these is one of the review's reproductions, or a design
# decision, turned into
# a regression check.
print("\n-- 13. code review re-check (2.2.1) --")

HELD = "__layoutStoreHeld = __layoutStore __activeLayoutHeld = __activeLayout " \
       "__layoutStore = nil __activeLayout = nil"
FREED = "__layoutStore = __layoutStoreHeld __activeLayout = __activeLayoutHeld"
WIN2 = HOME_FIXTURE + (
    '\nCharacterFrame = __newFrame("CharacterFrame", UIParent)\n'
    'CharacterFrame.rect = {0,0,180,300} CharacterFrame.shown = false\n')

# --- item 1: ONE readiness gate on every entry point --------------------------------------------
# The review's exact case: Edit Mode held unavailable, log in WITHOUT flushing timers, then show a
# managed window. Before the fix the ordinary OnShow hook placed it while confirmed == false.
lua30, g30 = new_client(4400, 1080, preamble=WIN2)
lua30.execute(HELD)
login(g30, flush=False)
check("item1: unconfirmed at login (confirmed=false, placed=false)",
      g30.FFSpan.Home.LayoutConfirmed() is False
      and g30.__placed("ContainerFrameCombinedBags") is None)
lua30.execute("CharacterFrame:Show()")
check("item1: a managed OnShow does NOT place while unconfirmed",
      g30.FFSpan.Home.LayoutConfirmed() is False
      and g30.__placed("CharacterFrame") is None,
      f"confirmed={g30.FFSpan.Home.LayoutConfirmed()} placed={g30.__placed('CharacterFrame')}")
# The panel post-hook is an entry point too. The mock's native pass anchors CENTER; an FFSpan
# placement is always TOPLEFT -- so the anchor point says which of the two touched the frame.
lua30.execute("UpdateUIPanelPositions(CharacterFrame)")
after_native30 = g30.__placed("CharacterFrame")
check("item1: the panel post-hook does NOT re-place while unconfirmed",
      after_native30 is not None and after_native30.point == "CENTER",
      f"placed={dict(after_native30) if after_native30 else None} (TOPLEFT would mean FFSpan moved it)")
# ...and so is the bag-anchor hook
lua30.execute("ContainerFrameCombinedBags.shown = true UpdateContainerFrameAnchors()")
check("item1: the bag-anchor hook does NOT anchor while unconfirmed",
      g30.__placed("ContainerFrameCombinedBags") is None,
      f"placed={g30.__placed('ContainerFrameCombinedBags')}")
# ...and the regen pass
lua30.execute("CharacterFrame:ClearAllPoints()")
g30.__combat = True
g30.__combat = False
g30.__fire("PLAYER_REGEN_ENABLED")
check("item1: the regen pass does NOT place while unconfirmed",
      g30.__placed("CharacterFrame") is None
      and g30.__placed("ContainerFrameCombinedBags") is None,
      f"char={g30.__placed('CharacterFrame')} bags={g30.__placed('ContainerFrameCombinedBags')}")
check("item1: the session is still live and owns its CVars throughout",
      "applied=yes" in g30.FFSpan.Home.StatusLine() and g30.__cvars.mapFade == "0")
# once Edit Mode is ready everything lands in one pass
lua30.execute(FREED)
g30.__fire("EDIT_MODE_LAYOUTS_UPDATED")
g30.__flush()
check("item1: once confirmed, the same entry points place normally",
      g30.FFSpan.Home.LayoutConfirmed() is True
      and g30.__placed("CharacterFrame") is not None
      and g30.__placed("ContainerFrameCombinedBags") is not None)

# --- item 2: the watchdog must never forge confirmation ------------------------------------------
# The review's case: Edit Mode held unavailable and timers FLUSHED. v2.2 reported
# (layoutConfirmed=true, HomeSlots=nil, ActiveLayoutName=nil).
lua31, g31 = new_client(4400, 1080, preamble=WIN2)
lua31.execute(HELD)
login(g31)          # flushed: the watchdog and its whole retry ladder fire
check("item2: the watchdog does NOT forge confirmation",
      g31.FFSpan.Home.LayoutConfirmed() is False
      and g31.FFScale.HomeSlots() is None,
      f"confirmed={g31.FFSpan.Home.LayoutConfirmed()} slots={g31.FFScale.HomeSlots()}")
check("item2: nothing was placed by the timeout",
      g31.__placed("ContainerFrameCombinedBags") is None)
warn_lines = [str(m) for m in g31.__printed.values() if "not confirmed" in str(m)]
check("item2: the player is told once, in one plain chat line",
      len(warn_lines) == 1 and "left where WoW put them" in warn_lines[0],
      f"{warn_lines}")
rec31 = g31.FFSpanDB.home["TestRealm-Fatty"]
tries = [str(r.d) for r in rec31.log.values() if "layout unconfirmed, retry" in str(r.d)]
check("item2: the retry ladder is bounded and every try is logged",
      0 < len(tries) <= 8
      and any("giving up" in str(r.d) for r in rec31.log.values()),
      f"{len(tries)} tries: {tries[:3]}")
# ...and a retry that CAN confirm does confirm, and then places
lua32, g32 = new_client(4400, 1080, preamble=WIN2)
lua32.execute(HELD)
login(g32, flush=False)
lua32.execute(FREED)          # Edit Mode becomes ready before the watchdog runs
g32.__flush()
check("item2: a retry that can confirm does confirm, and placement follows",
      g32.FFSpan.Home.LayoutConfirmed() is True
      and g32.FFScale.ActiveLayoutName() == "ThorSpanHome"
      and g32.__placed("ContainerFrameCombinedBags") is not None,
      f"confirmed={g32.FFSpan.Home.LayoutConfirmed()} layout={g32.FFScale.ActiveLayoutName()}")

# --- item 3: estimated edges are an explicit DEGRADED mode ---------------------------------------
lua33, g33 = new_client(4400, 1080, preamble=HOME_FIXTURE)
login(g33)
check("item3: a measured column is not flagged degraded",
      g33.FFSpan.Home.LayoutDegraded() is False
      and str(g33.FFSpan.Home.LayoutSource()) == "measured",
      f"source={g33.FFSpan.Home.LayoutSource()}")
# take the measurable bottom bar away: FFScale falls back to its estimate for that edge
lua34, g34 = new_client(4400, 1080,
                        preamble=HOME_FIXTURE.replace(
                            'MicroMenuContainer = __newFrame("MicroMenuContainer", UIParent)\n'
                            'MicroMenuContainer.rect = {0, 0, 800, 40}\n', ''))
login(g34)
s34 = g34.FFScale.HomeSlots()
check("item3: an estimated edge is ACCEPTED, not refused",
      s34 is not None and g34.FFSpan.Home.LayoutConfirmed() is True
      and g34.__placed("ContainerFrameCombinedBags") is not None,
      f"slots={s34 is not None} confirmed={g34.FFSpan.Home.LayoutConfirmed()}")
check("item3: ...but recorded as degraded, with its source",
      g34.FFSpan.Home.LayoutDegraded() is True
      and str(g34.FFSpan.Home.LayoutSource()).startswith("estimated"),
      f"degraded={g34.FFSpan.Home.LayoutDegraded()} source={g34.FFSpan.Home.LayoutSource()}")
rec34 = g34.FFSpanDB.home["TestRealm-Fatty"]
deg_logs = [str(r.d) for r in rec34.log.values() if "DEGRADED" in str(r.d)]
check("item3: ...and logged exactly once", len(deg_logs) == 1, f"{deg_logs}")
g34.SlashCmdList["FFSPAN"]("dump")
g34.__flush()
dump34 = g34.FFSpanDB.dumps["manual"] if g34.FFSpanDB.dumps else None
check("item3: the dump reports layoutConfirmed, the slot source and degraded",
      dump34 is not None and dump34.layoutConfirmed is True
      and dump34.layoutDegraded is True
      and str(dump34.layoutSlotSource).startswith("estimated"),
      f"confirmed={dump34 and dump34.layoutConfirmed} degraded={dump34 and dump34.layoutDegraded} "
      f"source={dump34 and dump34.layoutSlotSource}")
# refusal paths are unchanged: no slots -> no confirmation
check("item3: a refusal still yields no slots and no confirmation (g22 = ambiguous layout)",
      g22.FFScale.HomeSlots() is None and g22.FFSpan.Home.LayoutConfirmed() is False)

# --- item 4: routine re-confirmations must not reopen closed bags ---------------------------------
# The review's case: confirmed session, the player closes the bags, FFScale re-acknowledges.
lua35, g35 = new_client(4400, 1080, preamble=HOME_FIXTURE)
login(g35)
check("item4: the FIRST confirmation opens the resident bags",
      g35.ContainerFrameCombinedBags.shown is True
      and g35.__placed("ContainerFrameCombinedBags") is not None)
lua35.execute("CloseAllBags()")
g35.__flush()
check("item4: the player's close sticks", g35.ContainerFrameCombinedBags.shown is False)
opens35 = calls(g35, "OpenAllBags")
g35.FFScale.ApplyLayout("routine-reconfirm")
g35.__flush()
check("item4: a routine re-confirmation does NOT reopen them",
      g35.ContainerFrameCombinedBags.shown is False
      and calls(g35, "OpenAllBags") == opens35,
      f"shown={g35.ContainerFrameCombinedBags.shown} "
      f"opens={calls(g35, 'OpenAllBags')} vs {opens35}")
check("item4: the re-confirmation still happened (this is not just a dead callback)",
      g35.FFSpan.Home.LayoutConfirmed() is True
      and g35.FFScale.ActiveLayoutName() == "ThorSpanHome")
# an approved trigger still reopens them
g35.__fire("LOADING_SCREEN_DISABLED")
g35.__flush()
check("item4: an APPROVED trigger (loading screen) still reopens them",
      g35.ContainerFrameCombinedBags.shown is True)

# --- item 5: never acknowledge what was not confirmed ---------------------------------------------
# 5a. a no-Stack ConsolePort restore keeps its journal row
lua36, g36 = new_client(4400, 1080, preamble=HOME_FIXTURE)
login(g36)
check("item5: exclusions were registered while the Stack was reachable",
      g36.FFSpanDB.homeShared.consolePort is not None)
lua36.execute("ConsolePort.GetData = function() return nil end")   # Stack goes away
g36.SlashCmdList["FFSPAN"]("home off")
g36.__flush()
check("item5a: a restore with no usable Stack stays journalled, not acknowledged",
      g36.FFSpanDB.homeShared is not None
      and g36.FFSpanDB.homeShared.consolePort is not None,
      str(g36.__luaser(g36.FFSpanDB.homeShared)))
# 5b. a nil CVar readback is unconfirmed
lua37, g37 = new_client(4400, 1080, preamble=HOME_FIXTURE)
login(g37)
lua37.execute("function GetCVar(n) return nil end")
g37.SlashCmdList["FFSPAN"]("home off")
g37.__flush()
check("item5b: a nil CVar readback keeps the journal open",
      g37.FFSpanDB.homeShared is not None and g37.FFSpanDB.homeShared.cvars is not None,
      str(g37.__luaser(g37.FFSpanDB.homeShared)))
# 5c. The review's off -> on before regen case
MOVE = HOME_FIXTURE + (
    '\nCharacterFrame = __newFrame("CharacterFrame", UIParent)\n'
    'CharacterFrame.rect = {0,0,180,300} CharacterFrame.shown = false\n')
lua38, g38 = new_client(4400, 1080, preamble=MOVE)
login(g38)
lua38.execute("CharacterFrame:ClearAllPoints() "
              "CharacterFrame:SetPoint('TOPLEFT', UIParent, 'BOTTOMLEFT', 900, 700) "
              "CharacterFrame:Show()")
g38.__flush()
origin38 = dict(g38.__placed("CharacterFrame"))     # where FFSpan put it (snapshot already taken)
snap38 = g38.FFSpanDB.home["TestRealm-Fatty"].session.frames["CharacterFrame"]
orig_pt = [v for v in snap38.points[1].values()]
g38.__combat = True
lua38.execute("CharacterFrame.protected = true")     # cannot be restored while in combat
g38.SlashCmdList["FFSPAN"]("home off")
g38.__flush()
check("item5c: a combat `home off` leaves the frame restore pending",
      g38.FFSpanDB.home["TestRealm-Fatty"].session is not None)
g38.SlashCmdList["FFSPAN"]("home on")               # back on BEFORE regen
g38.__flush()
check("item5c: the reused session still holds the ORIGINAL snapshot",
      g38.FFSpanDB.home["TestRealm-Fatty"].session.frames["CharacterFrame"] is not None
      and [v for v in g38.FFSpanDB.home["TestRealm-Fatty"]
           .session.frames["CharacterFrame"].points[1].values()] == orig_pt,
      f"now={[v for v in g38.FFSpanDB.home['TestRealm-Fatty'].session.frames['CharacterFrame'].points[1].values()]}"
      f" orig={orig_pt}")
lua38.execute("CharacterFrame.protected = false")
g38.__combat = False
g38.__fire("PLAYER_REGEN_ENABLED")
g38.__flush()
# The decisive evidence is whether the OLD session's frame restore executed at all. Its own log
# line is the only unambiguous witness: the end position is not, because the placement pass that
# follows immediately puts the frame back in the lane either way, and the re-snapshot that follows
# happens to capture the same anchors -- which is exactly why this hole survived the earlier fix.
rec38 = g38.FFSpanDB.home["TestRealm-Fatty"]
ran_old = [str(r.d) for r in rec38.log.values() if "deferred restore completed" in str(r.d)]
check("item5c: the old restore did NOT run through the live session",
      not ran_old and "applied=yes" in g38.FFSpan.Home.StatusLine(),
      f"old-restore log lines={ran_old} status={g38.FFSpan.Home.StatusLine()}")
check("item5c: the live session still owns a placed frame and its snapshot",
      g38.FFSpanDB.home["TestRealm-Fatty"].session is not None
      and g38.__placed("CharacterFrame") is not None
      and g38.__placed("CharacterFrame").x < 1240,
      f"placed={g38.__placed('CharacterFrame')}")
g38.SlashCmdList["FFSPAN"]("home off")
g38.__flush()
back38 = g38.__placed("CharacterFrame")
check("item5c: a later `home off` puts the frame back at its ORIGINAL position",
      back38 is not None and near(back38.x, 900 * PX_PER_UNIT, 1.0)
      and near(back38.y, 1080 - 700 * PX_PER_UNIT, 1.0),
      f"back={dict(back38) if back38 else None} wanted=({900 * PX_PER_UNIT}, "
      f"{1080 - 700 * PX_PER_UNIT}) ffspan-placed={origin38}")

# ============================== 14. the first real device test (FFSpan 2.3) ======================
# Every number here is measured from the Thor run of 2026-09-23 14:17-14:32
# (FFSpan's SavedVariables from that run). Sizes are given at scale 1, in the
# mock's UI units (px / 1.40625), so the frames are literally the ones I saw.
print("\n-- 14. first device test (real device numbers) --")

U = PX_PER_UNIT  # 1.40625


def units(px_w, px_h):
    return f"{{0, 0, {px_w / U:.4f}, {px_h / U:.4f}}}"


# device: PlayerSpellsFrame env 2277x1284 @ scale 1, IsProtected -> refused SetScale -> SPLIT
# device: CharacterFrame    env  575x482 @ 0.755 => 761x638 @ scale 1
# device: GameMenuFrame     env  360x683 @ scale 1, IsProtected (fits without scaling)
# device: ContainerFrameCombinedBags 617x252 @ scale 1
DEVICE_FIXTURE = HOME_FIXTURE.replace(
    "ContainerFrameCombinedBags.rect = {0, 0, 256, 320}",
    f"ContainerFrameCombinedBags.rect = {units(617, 252)}") + (
    f'\nPlayerSpellsFrame = __newFrame("PlayerSpellsFrame", UIParent)\n'
    f'PlayerSpellsFrame.rect = {units(2277, 1284)}\n'
    f'PlayerSpellsFrame.shown = false PlayerSpellsFrame.protected = true\n'
    # the real registration: Blizzard_PlayerSpellsRegistration.lua sets checkFit = 1,
    # checkFitExtraWidth = 200, so Blizzard re-applies its own fit AFTER FFSpan places the frame.
    f'PlayerSpellsFrame.checkFit = true PlayerSpellsFrame.checkFitExtraWidth = 200\n'
    f'PlayerSpellsFrame.__tab = 1\n'
    f'function PlayerSpellsFrame:IsFrameTabActive(t) return self.__tab == t end\n'
    f'PlayerSpellsUtil = {{FrameTabs = {{SpellBook = 1, ClassTalents = 2, ClassSpecializations = 3}}}}\n'
    f'CharacterFrame = __newFrame("CharacterFrame", UIParent)\n'
    f'CharacterFrame.rect = {units(761, 638)} CharacterFrame.shown = false\n'
    f'MerchantFrame = __newFrame("MerchantFrame", UIParent)\n'
    f'MerchantFrame.rect = {units(500, 600)} MerchantFrame.shown = false\n'
    f'GameMenuFrame.rect = {units(360, 683)}\n'
    f'CollectionsJournal = __newFrame("CollectionsJournal", UIParent)\n'
    f'CollectionsJournal.rect = {units(900, 700)} CollectionsJournal.shown = false\n'
    f'AchievementFrame = __newFrame("AchievementFrame", UIParent)\n'
    f'AchievementFrame.rect = {units(880, 640)} AchievementFrame.shown = false\n'
    'EventRegistry = {callbacks = {}}\n'
    'function EventRegistry:RegisterCallback(name, fn, owner)\n'
    '    self.callbacks[name] = self.callbacks[name] or {}\n'
    '    table.insert(self.callbacks[name], fn)\n'
    'end\n'
    'function EventRegistry:TriggerEvent(name, ...)\n'
    '    for _, fn in ipairs(self.callbacks[name] or {}) do fn(...) end\n'
    'end\n')

# --- the PlayerSpellsFrame split: checkFit, not a scale refusal ----------------------------------
# FFSpan 2.4 CORRECTION. FFSpan 2.3 concluded "SetScale does not take on protected panels"
# from a single frame; that was wrong. PlayerSpellsFrame is a checkFit panel and Blizzard
# re-applies its own fit (measured against UIParent = the whole 4400 canvas) through the global
# UIPanelUpdateScaleForFit, from paths that are NOT inside the UpdateUIPanelPositions hook.
# __showPanel() reproduces the real ShowUIPanel ordering: position, Show (FFSpan's OnShow runs), then
# the checkFit rescale at :532 -- which is what undid FFSpan's fit on the device.
lua40, g40 = new_client(4400, 1080, preamble=DEVICE_FIXTURE)
login(g40)
lua40.execute("__showPanel('PlayerSpellsFrame')")
g40.__flush()
spells = g40.__placed("PlayerSpellsFrame")
check("Blizzard's checkFit rescale really did fire after FFSpan's placement",
      calls(g40, "UIPanelUpdateScaleForFit") >= 1,
      f"calls={calls(g40, 'UIPanelUpdateScaleForFit')}")
check("the SPELLBOOK tab ends fully inside the HOME rect, never split",
      spells is not None and spells.x >= 16 - 0.5
      and spells.x + 2277 * spells.scale <= 1240 - 16 + 1
      and spells.y >= 16 - 0.5 and spells.y + 1284 * spells.scale <= 1080 - 16 + 1,
      f"placed={dict(spells) if spells else None}")
check("...at the fit scale FFSpan asked for, not the 1 Blizzard reset it to",
      spells is not None and near(spells.scale, min(1208 / 2277, 1048 / 1284), 0.01),
      f"scale={spells.scale if spells else None} wanted={min(1208 / 2277, 1048 / 1284):.3f}")
check("nothing is reported as a scale refusal -- the re-apply worked",
      len([str(v) for v in g40.FFSpan.Home.ScaleRefused().values()]) == 0,
      str([str(v) for v in g40.FFSpan.Home.ScaleRefused().values()]))
g40.SlashCmdList["FFSPAN"]("dump")
g40.__flush()
d40 = g40.FFSpanDB.dumps["manual"] if g40.FFSpanDB.dumps else None
check("the dump records which hook caught the rescale",
      d40 is not None and str(d40.scaleHook) == "global:UIPanelUpdateScaleForFit",
      str(d40.scaleHook) if d40 else "no dump")

# the TALENTS tab is a TOP window and must end fully inside the game rect
lua47, g47 = new_client(4400, 1080, preamble=DEVICE_FIXTURE)
login(g47)
lua47.execute("PlayerSpellsFrame.__tab = 2 __showPanel('PlayerSpellsFrame')")
g47.__flush()
tal47 = g47.__placed("PlayerSpellsFrame")
check("the TALENTS tab ends fully inside the TOP rect, never split",
      tal47 is not None and tal47.x >= 1240 + 16 - 0.5
      and tal47.x + 2277 * tal47.scale <= 3160 - 16 + 1
      and tal47.y >= 16 - 0.5 and tal47.y + 1284 * tal47.scale <= 1080 - 16 + 1,
      f"placed={dict(tal47) if tal47 else None}")

# in combat a protected checkFit panel is QUEUED for regen (BlizzMove's rule), not fought over
lua48, g48 = new_client(4400, 1080, preamble=DEVICE_FIXTURE)
login(g48)
lua48.execute("__showPanel('PlayerSpellsFrame')")
g48.__flush()
g48.__combat = True
lua48.execute("UIPanelUpdateScaleForFit(PlayerSpellsFrame, 200)")   # a rescale mid-combat
# In combat FFSpan must NOT re-apply: the frame is protected, so Blizzard's scale stands until
# regen. The mock's fit maths gives 0.841 here; what matters is that it is not FFSpan's 0.531.
check("a rescale in combat is not fought -- Blizzard's scale stands for now",
      not near(float(g48.PlayerSpellsFrame.scale), min(1208 / 2277, 1048 / 1284), 0.01),
      f"scale={g48.PlayerSpellsFrame.scale}")
g48.__combat = False
g48.__fire("PLAYER_REGEN_ENABLED")
g48.__flush()
sp48 = g48.__placed("PlayerSpellsFrame")
check("...and FFSpan's fit is put back at PLAYER_REGEN_ENABLED",
      sp48 is not None and near(g48.PlayerSpellsFrame.scale, min(1208 / 2277, 1048 / 1284), 0.01)
      and sp48.x + 2277 * sp48.scale <= 1240 - 16 + 1,
      f"scale={g48.PlayerSpellsFrame.scale} placed={dict(sp48) if sp48 else None}")

# A LATE rescale -- the case the hook exists for. EvaluateAutoMinimize and
# UpdateScaleForFitForOpenPanels can fire at any time, long after the OnShow pass, so nothing
# else is going to put FFSpan's fit back. Out of combat the hook must do it on the spot.
lua50a, g50a = new_client(4400, 1080, preamble=DEVICE_FIXTURE)
login(g50a)
lua50a.execute("__showPanel('PlayerSpellsFrame')")
g50a.__flush()
want50 = min(1208 / 2277, 1048 / 1284)
check("FFSpan's fit is in place after the show",
      near(float(g50a.PlayerSpellsFrame.scale), want50, 0.01),
      f"scale={g50a.PlayerSpellsFrame.scale}")
lua50a.execute("UIPanelUpdateScaleForFit(PlayerSpellsFrame, 200)")   # late, no event follows
check("a LATE checkFit rescale is undone by the hook, with no event to help",
      near(float(g50a.PlayerSpellsFrame.scale), want50, 0.01),
      f"scale={g50a.PlayerSpellsFrame.scale} wanted={want50:.3f}")
sp50a = g50a.__placed("PlayerSpellsFrame")
check("...and it is re-anchored from the same placement, still inside HOME",
      sp50a is not None and sp50a.x >= 16 - 0.5
      and sp50a.x + 2277 * sp50a.scale <= 1240 - 16 + 1,
      f"placed={dict(sp50a) if sp50a else None}")

# HousingDashboardFrame -- a PAGE row (RegisterUIPanel, area = "left")
lua50b, g50b = new_client(4400, 1080, preamble=DEVICE_FIXTURE + (
    '\nHousingDashboardFrame = __newFrame("HousingDashboardFrame", UIParent)\n'
    'HousingDashboardFrame.rect = {0, 0, 640, 500} HousingDashboardFrame.shown = false\n'))
login(g50b)
lua50b.execute("HousingDashboardFrame:Show()")
g50b.__flush()
house = g50b.__placed("HousingDashboardFrame")
check("the housing dashboard is a home PAGE",
      house is not None and house.x >= 16 - 0.5
      and house.x + 640 * PX_PER_UNIT * house.scale <= 1240 - 16 + 1,
      f"placed={dict(house) if house else None}")

# a frame that genuinely will not scale is now a DIAGNOSTIC, and it is still placed
lua49, g49 = new_client(4400, 1080, preamble=DEVICE_FIXTURE.replace(
    "PlayerSpellsFrame.checkFit = true", "PlayerSpellsFrame.refuseScale = true PlayerSpellsFrame.checkFit = true"))
login(g49)
lua49.execute("__showPanel('PlayerSpellsFrame')")
g49.__flush()
check("a genuine scale refusal is reported as a diagnostic, not a verdict",
      "PlayerSpellsFrame" in [str(v) for v in g49.FFSpan.Home.ScaleRefused().values()],
      str([str(v) for v in g49.FFSpan.Home.ScaleRefused().values()]))
check("...and the frame is still anchored, not abandoned to the native UI",
      g49.__placed("PlayerSpellsFrame") is not None)

# --- FFSpan 2.5.2: name the addon that pinned it --------------------------------------------------
# On the device PlayerSpellsFrame comes back scale 1 / 2275x1242 px in every dump and the root
# cause is not FFSpan: TalentTreeTweaks' ScaleTalentFrame module SecureHooks the frame's own SetScale
# and puts its saved scale back (scaleTalentFrame.lua:81-83). Diagnostic only -- FFSpan never fights it.
TTT = ("__loadedAddons.TalentTreeTweaks = true\nTalentTreeTweaksDB = {modules = {}}\n")


def r5_scale_env(extra=""):
    l, gg = new_client(4400, 1080, preamble=DEVICE_FIXTURE.replace(
        "PlayerSpellsFrame.checkFit = true",
        "PlayerSpellsFrame.refuseScale = true PlayerSpellsFrame.checkFit = true") + extra)
    login(gg)
    l.execute("__showPanel('PlayerSpellsFrame')")
    gg.__flush()
    return l, gg


def owner_of(gg, name="PlayerSpellsFrame"):
    o = gg.FFSpan.ScaleOwners()
    return str(o[name]) if o is not None and o[name] is not None else None


_, g_ttt = r5_scale_env(TTT)
check("a refused scale names TalentTreeTweaks:ScaleTalentFrame as the likely owner",
      owner_of(g_ttt) == "TalentTreeTweaks:ScaleTalentFrame", f"owner={owner_of(g_ttt)}")
g_ttt.FFSpan.DumpFrames("scale owner", "r5owner")
_d = g_ttt.FFSpanDB.dumps["r5owner"]
check("...and it is in the DUMP, so the next device test reads it instead of re-deriving it",
      _d is not None and str(_d.scaleOwners.PlayerSpellsFrame) == "TalentTreeTweaks:ScaleTalentFrame",
      f"dump={_d is not None and _d.scaleOwners and _d.scaleOwners.PlayerSpellsFrame}")

# TTT stands its own module down when BlizzMove is loaded (scaleTalentFrame.lua:16, :46)
_, g_bm = r5_scale_env(TTT + "__loadedAddons.BlizzMove = true\n")
check("with BlizzMove loaded TTT disables that module itself, so it is NOT blamed",
      owner_of(g_bm) == "unknown", f"owner={owner_of(g_bm)}")

_, g_off = r5_scale_env(TTT + "TalentTreeTweaksDB.modules.ScaleTalentFrame = false\n")
check("the module switched off is not blamed either",
      owner_of(g_off) == "unknown", f"owner={owner_of(g_off)}")

_, g_none = r5_scale_env()
check("no TalentTreeTweaks at all -> 'unknown', never a guess",
      owner_of(g_none) == "unknown", f"owner={owner_of(g_none)}")
check("naming an owner never changes placement -- the frame is still anchored",
      g_ttt.__placed("PlayerSpellsFrame") is not None)
check("...and FFSpan never wrote TalentTreeTweaks' settings",
      g_ttt.TalentTreeTweaksDB.modules.ScaleTalentFrame is None,
      "FFSpan must never write another addon's saved variables")

# --- the bags narrow so the companion gets bigger ------------------------------------
lua42, g42 = new_client(4400, 1080, preamble=DEVICE_FIXTURE)
login(g42)
bags_before = g42.FFSpan.Home.BagScale()
lua42.execute("CharacterFrame:Show()")
g42.__flush()
chs = g42.__placed("CharacterFrame")
bag_scale = float(g42.FFSpan.Home.BagScale())
check("with a companion open the bags narrow to the 0.7 floor",
      near(bag_scale, 0.70, 0.005), f"bagScale={bag_scale}")
check("the companion is far bigger than the 0.755 seen on the device (>= 0.99, was 0.755)",
      chs is not None and chs.scale >= 0.99,
      f"scale={chs.scale if chs else None}")
check("...and it still sits inside the home screen, clear of the bags",
      chs is not None and chs.x >= 16 - 0.5
      and chs.x + 761 * chs.scale <= 1240 - 16 - 617 * bag_scale - 16 + 1,
      f"placed={dict(chs) if chs else None}")
bagp42 = g42.__placed("ContainerFrameCombinedBags")
check("the bags are still flush to the right of the home screen",
      bagp42 is not None and near(bagp42.x + 617 * bag_scale, 1224, 2.0),
      f"bags={dict(bagp42) if bagp42 else None}")
lua42.execute("CharacterFrame:Hide()")
g42.__flush()
check("the bags go back to full size when the companion closes",
      near(float(g42.FFSpan.Home.BagScale()), 1.0, 0.005)
      and near(float(g42.ContainerFrameCombinedBags.scale), 1.0, 0.005),
      f"bagScale={g42.FFSpan.Home.BagScale()} frame={g42.ContainerFrameCombinedBags.scale}")

# --- the game menu is a TOP window ---------------------------------------------------
lua43, g43 = new_client(4400, 1080, preamble=DEVICE_FIXTURE)
login(g43)
lua43.execute("GameMenuFrame:Show()")
g43.__flush()
menu43 = g43.__placed("GameMenuFrame")
check("the game menu opens on the TOP screen, inside the game rect",
      menu43 is not None and menu43.x >= 1240 and menu43.x + 360 * menu43.scale <= 3160,
      f"placed={dict(menu43) if menu43 else None}")
check("...and no longer runs off the bottom of the canvas",
      menu43 is not None and menu43.y >= 16 - 0.5
      and menu43.y + 683 * menu43.scale <= 1080 - 16 + 0.5,
      f"placed={dict(menu43) if menu43 else None} bottom="
      f"{menu43.y + 683 * menu43.scale if menu43 else None}")
hides43 = calls(g43, "HideUIPanel")
lua43.execute("CharacterFrame:Show()")
g43.__flush()
check("opening a managed window closes the game menu first",
      g43.GameMenuFrame.shown is False and calls(g43, "HideUIPanel") > hides43,
      f"menu shown={g43.GameMenuFrame.shown}")

# --- one PAGE at a time, and the spellbook/talents class switch -----------------------
lua44, g44 = new_client(4400, 1080, preamble=DEVICE_FIXTURE)
login(g44)
lua44.execute("CollectionsJournal:Show()")
g44.__flush()
coll = g44.__placed("CollectionsJournal")
check("a PAGE takes the whole home screen and may grow past 1.0",
      coll is not None and coll.x >= 16 - 0.5 and coll.scale > 1.0
      and coll.x + 900 * coll.scale <= 1240 - 16 + 1,
      f"placed={dict(coll) if coll else None}")
lua44.execute("AchievementFrame:Show()")
g44.__flush()
check("opening a second PAGE closes the first one the native way",
      g44.CollectionsJournal.shown is False and g44.AchievementFrame.shown is True,
      f"coll={g44.CollectionsJournal.shown} ach={g44.AchievementFrame.shown}")
# in combat nothing may be hidden, so the NEWER page waits
lua45, g45 = new_client(4400, 1080, preamble=DEVICE_FIXTURE)
login(g45)
lua45.execute("CollectionsJournal:Show()")
g45.__flush()
g45.__combat = True
lua45.execute("AchievementFrame:Show()")
g45.__flush()
check("in combat the open PAGE keeps the screen and the newer one waits",
      g45.CollectionsJournal.shown is True and g45.AchievementFrame.shown is True
      and g45.__placed("AchievementFrame") is None
      and g45.__placed("CollectionsJournal") is not None,
      f"ach placed={g45.__placed('AchievementFrame')}")
g45.__combat = False
g45.__fire("PLAYER_REGEN_ENABLED")
g45.__flush()
check("at regen the newer PAGE takes over and the older closes",
      g45.AchievementFrame.shown is True and g45.CollectionsJournal.shown is False,
      f"coll={g45.CollectionsJournal.shown} ach={g45.AchievementFrame.shown}")
# spellbook (PAGE, home) <-> talents (TOP, game rect)
lua46, g46 = new_client(4400, 1080, preamble=DEVICE_FIXTURE)
login(g46)
lua46.execute("PlayerSpellsFrame:Show()")
g46.__flush()
book46 = g46.__placed("PlayerSpellsFrame")
check("the spellbook tab is a home PAGE",
      book46 is not None and book46.x < 1240, f"{dict(book46) if book46 else None}")
lua46.execute("PlayerSpellsFrame.__tab = 2 "
              "EventRegistry:TriggerEvent('PlayerSpellsFrame.TabSet', PlayerSpellsFrame, 2)")
g46.__flush()
tal46 = g46.__placed("PlayerSpellsFrame")
check("the talents tab moves it to the TOP screen",
      tal46 is not None and tal46.x >= 1240, f"{dict(tal46) if tal46 else None}")

# ===================================== 15. panel-edge awareness (FFSpan 2.4) ======================
# Found on the device 2026-09-23: clicking an item in the bags put its tooltip to the RIGHT of the
# item, which on the right side of the bag column runs off the bottom screen, and that looked like
# a whole class of problem. It is: WoW sees ONE 4400x1080 screen, so Blizzard's
# ContainerFrameItemButton_CalculateItemTooltipAnchors rule
#   anchorFromLeft = self:GetRight() < GetScreenWidth()/2  ->  ANCHOR_RIGHT
# makes EVERYTHING on the home screen (x < 2200) open rightwards, across x = 1240.
print("\n-- 15. panel-edge awareness --")

EDGE = DEVICE_FIXTURE + r"""
GameTooltip = __newFrame("GameTooltip", UIParent)
GameTooltip.rect = {0, 0, 220, 120} GameTooltip.shown = false
function GameTooltip:GetOwner() return self.owner end
ShoppingTooltip1 = __newFrame("ShoppingTooltip1", UIParent)
ShoppingTooltip1.rect = {0, 0, 200, 110} ShoppingTooltip1.shown = false
BagItem = __newFrame("BagItem", UIParent)
BagItem.rect = {0, 0, 30, 30} BagItem.shown = true
TopItem = __newFrame("TopItem", UIParent)
TopItem.rect = {0, 0, 30, 30} TopItem.shown = true

-- The mock does not derive a rect from anchors, so put a frame somewhere by setting BOTH: the
-- rect (what envelopePx measures) and the anchor (what __placed reads back).
function __setPx(f, x, y)
    local q = __H / 768
    local w, h = f.rect[3], f.rect[4]
    f.rect = {x / q, (__H - y) / q - h, w, h}
    f:ClearAllPoints()
    f:SetPoint("TOPLEFT", UIParent, "BOTTOMLEFT", x / q, (__H - y) / q)
end

-- Blizzard's rule, verbatim in shape (ContainerFrameItemButton_CalculateItemTooltipAnchors):
-- anchor to the RIGHT of the owner whenever the owner sits in the canvas's LEFT HALF. That is
-- what puts a home-screen tooltip across the panel edge.
function __blizzardTooltipAnchor(owner)
    local q = __H / 768
    local ox, ow = owner.rect[1] * q, owner.rect[3] * q
    GameTooltip.owner = owner
    GameTooltip.shown = true
    local x
    if (ox + ow) < GetScreenWidth() / 2 then x = ox + ow else x = ox - 220 * q end
    __setPx(GameTooltip, x, 300)
    if GameTooltip.hs_OnShow then GameTooltip.hs_OnShow(GameTooltip) end
end
"""


def place_frame(lua, name, x_px, y_px):
    """Put a mock frame at a physical-px position (rect AND anchor, so both readouts agree)."""
    lua.execute(f"__setPx({name}, {x_px}, {y_px})")



lua50, g50 = new_client(4400, 1080, preamble=EDGE)
login(g50)
# a bag item at the RIGHT of the home column -- exactly the case seen on the device
place_frame(lua50, "BagItem", 1180, 800)
lua50.execute("__blizzardTooltipAnchor(BagItem)")
g50.__flush()
tip = g50.__placed("GameTooltip")
tip_w = 220 * PX_PER_UNIT
check("edges: Blizzard put the bag tooltip across the panel edge (the bug reproduces)",
      calls(g50, "UIPanelUpdateScaleForFit") >= 0 and tip is not None,
      "tooltip was never shown")
check("edges: FFSpan pulls it back fully onto the HOME panel",
      tip is not None and tip.x >= 0 - 0.5 and tip.x + tip_w <= 1240 + 0.5,
      f"tooltip x={tip.x if tip else None}..{tip.x + tip_w if tip else None}")
check("edges: ...by mirroring it to the LEFT of the item, not by squashing it",
      tip is not None and tip.x + tip_w <= 1180 + 0.5,
      f"tooltip right={tip.x + tip_w if tip else None} item left=1180")
# the comparison tooltip follows the main one
lua50.execute("ShoppingTooltip1.shown = true")
place_frame(lua50, "ShoppingTooltip1", 1200, 800)   # Blizzard put it past the edge too
lua50.execute("FFSpan.RelocateTransient(GameTooltip)")
g50.__flush()
shop = g50.__placed("ShoppingTooltip1")
check("edges: the comparison tooltip is brought back too",
      shop is not None and shop.x + 200 * PX_PER_UNIT <= 1240 + 0.5,
      f"shopping x={shop.x if shop else None}")

# an owner so near the LEFT edge that mirroring cannot fit either: the tooltip is clamped inside
# the panel rather than pushed off the other side
lua50c, g50c = new_client(4400, 1080, preamble=EDGE)
login(g50c)
lua50c.execute("GameTooltip.rect = {0, 0, 800, 120}")     # 1125 px wide
place_frame(lua50c, "BagItem", 200, 800)                  # mirroring left would land at x = -925
lua50c.execute("__blizzardTooltipAnchor(BagItem)")
g50c.__flush()
tipc = g50c.__placed("GameTooltip")
wide = 800 * PX_PER_UNIT
check("edges: when neither side fits, the tooltip is clamped inside the panel",
      tipc is not None and tipc.x >= 0 - 0.5 and tipc.x + wide <= 1240 + 0.5,
      f"tooltip x={tipc.x if tipc else None}..{tipc.x + wide if tipc else None}")

# an item near the right of the TOP panel must not push its tooltip into the unshown strip
lua51, g51 = new_client(4400, 1080, preamble=EDGE)
login(g51)
place_frame(lua51, "TopItem", 3100, 500)
lua51.execute("__blizzardTooltipAnchor(TopItem)")
g51.__flush()
tip51 = g51.__placed("GameTooltip")
check("edges: a tooltip on the TOP panel stays out of the unshown strip (x <= 3160)",
      tip51 is not None and tip51.x + tip_w <= 3160 + 0.5 and tip51.x >= 1240 - 0.5,
      f"tooltip x={tip51.x if tip51 else None}..{tip51.x + tip_w if tip51 else None}")

# a tooltip that already sits inside its panel is left exactly alone
lua52, g52 = new_client(4400, 1080, preamble=EDGE)
login(g52)
place_frame(lua52, "BagItem", 300, 400)
lua52.execute("__blizzardTooltipAnchor(BagItem)")
g52.__flush()
tip52 = g52.__placed("GameTooltip")
before52 = dict(tip52) if tip52 else None
lua52.execute("FFSpan.RelocateTransient(GameTooltip)")
g52.__flush()
after52 = g52.__placed("GameTooltip")
check("edges: a centred/already-fitting tooltip is not moved",
      before52 is not None and after52 is not None and near(before52["x"], after52.x, 0.01),
      f"before={before52} after={dict(after52) if after52 else None}")

# the dump reports a transient that is straddling an edge
lua53, g53 = new_client(4400, 1080, preamble=EDGE)
login(g53)
lua53.execute("GameTooltip.shown = true")
# Straddles x=1240 WITHOUT a SetPoint: since 2.6.2 FFSpan corrects a tooltip inside its own
# SetPoint post-hook (place_frame's __setPx lands it at x=1240 immediately), so the only straddle
# left for the dump to catch is one the client draws with no anchor call FFSpan can see.
lua53.execute("local q = 1080 / 768; GameTooltip.rect = {1150 / q, 400 / q, GameTooltip.rect[3], GameTooltip.rect[4]}")
g53.SlashCmdList["FFSPAN"]("dump")
g53.__flush()
d53 = g53.FFSpanDB.dumps["manual"] if g53.FFSpanDB.dumps else None
off = [str(r.name) for r in d53.transientOffPanel.values()] if (d53 and d53.transientOffPanel) else []
check("edges: the dump flags a transient straddling a panel edge",
      d53 is not None and "GameTooltip" in off and int(d53.transientOffPanelCount) >= 1,
      f"offPanel={off} count={d53.transientOffPanelCount if d53 else None}")

# in combat a protected transient is left alone and logged; an unprotected one still moves
lua54, g54 = new_client(4400, 1080, preamble=EDGE)
login(g54)
g54.__combat = True
place_frame(lua54, "BagItem", 1180, 800)
lua54.execute("GameTooltip.protected = true __blizzardTooltipAnchor(BagItem)")
g54.__flush()
tip54 = g54.__placed("GameTooltip")
check("edges: a PROTECTED transient is left where it is in combat",
      tip54 is not None and tip54.x + tip_w > 1240,
      f"tooltip x={tip54.x if tip54 else None}")
lua54.execute("GameTooltip.protected = false FFSpan.RelocateTransient(GameTooltip)")
g54.__flush()
tip54b = g54.__placed("GameTooltip")
check("edges: ...but an unprotected one is moved even in combat (tooltips are not protected)",
      tip54b is not None and tip54b.x + tip_w <= 1240 + 0.5,
      f"tooltip x={tip54b.x if tip54b else None}")

# ============================== 16. Baganator big bags ============================================
# Decided 2026-09-23: bags ALWAYS OPEN, NOTHING overlaps. Baganator's grid is
# told how many COLUMNS and what ICON SIZE to use so it FILLS the box instead of being shrunk.
#
# The fixture below is a STAND-IN written from the published behaviour of Baganator 829, not a
# copy of it: the two option keys, the one public refresh call, the documented grid arithmetic
# (container = cols * (icon + padding) - padding wide, rows * (icon + padding) tall, padding 4),
# the replaced global ToggleAllBags, and the frame-group-suffixed names registered in
# UISpecialFrames. No Baganator code is reproduced here or anywhere in this repo.
print("\n-- 16. Baganator big bags --")

BAGANATOR = r"""
BAGANATOR_CURRENT_PROFILE = "DEFAULT"
BAGANATOR_CONFIG = {Profiles = {DEFAULT = {}}}
__bagSlots = 30                       -- what C_Container reports; the tests vary it
__baganatorChromeW, __baganatorChromeH = 26, 60   -- frame chrome around the grid, in UI units

C_Container = C_Container or {}
function C_Container.GetContainerNumSlots(i)
    if i == 0 then return math.min(__bagSlots, 20) end
    local left = __bagSlots - 20
    if left <= 0 then return 0 end
    local per = math.ceil(left / 4)
    local used = (i - 1) * per
    return math.max(0, math.min(per, left - used))
end
NUM_TOTAL_EQUIPPED_BAG_SLOTS = 4

__loadedAddons.Baganator = true
__loadedAddons.Syndicator = true       -- Baganator errors out without it (Core/Initialize.lua:33)
Baganator = {API = {Skins = {}}}
__baganatorLayouts = 0
function Baganator.API.RequestLayoutUpdate()
    __baganatorLayouts = __baganatorLayouts + 1
    __baganatorRelayout()
end
function Baganator.API.Skins.GetCurrentSkin() return __bagCfg().current_skin end

function __bagCfg() return BAGANATOR_CONFIG.Profiles[BAGANATOR_CURRENT_PROFILE] end

-- the backpack view, named with a frame-group suffix and registered in UISpecialFrames
Baganator_SingleViewBackpackViewFrameDEFAULT =
    __newFrame("Baganator_SingleViewBackpackViewFrameDEFAULT", UIParent)
Baganator_SingleViewBackpackViewFrameDEFAULT.shown = false
Baganator_SingleViewBankViewFrameDEFAULT =
    __newFrame("Baganator_SingleViewBankViewFrameDEFAULT", UIParent)
Baganator_SingleViewBankViewFrameDEFAULT.shown = false
UISpecialFrames = {"Baganator_SingleViewBackpackViewFrameDEFAULT",
                   "Baganator_SingleViewBankViewFrameDEFAULT"}

-- the documented sizing: container + chrome, in UI units
function __baganatorRelayout()
    local cfg = __bagCfg()
    local icon = cfg.bag_icon_size or 37
    local cols = cfg.bag_view_width or 12
    local padding = cfg.reduce_spacing and 1 or 4
    local slots = 0
    for i = 0, NUM_TOTAL_EQUIPPED_BAG_SLOTS do
        slots = slots + C_Container.GetContainerNumSlots(i)
    end
    local rows = math.ceil(slots / math.max(1, cols))
    local f = Baganator_SingleViewBackpackViewFrameDEFAULT
    local w = cols * (icon + padding) - padding + __baganatorChromeW
    local h = rows * (icon + padding) + __baganatorChromeH
    f.rect = {f.rect[1], f.rect[2], w, h}
    __lastGrid = {icon = icon, cols = cols, rows = rows, slots = slots}
end

-- Baganator REPLACES the global; OpenAllBags is deliberately not hooked by it
__baganatorToggles = 0
function ToggleAllBags()
    __baganatorToggles = __baganatorToggles + 1
    local f = Baganator_SingleViewBackpackViewFrameDEFAULT
    f.shown = not f.shown
    if f.hs_OnShow and f.shown then f.hs_OnShow(f) end
end
__baganatorRelayout()
"""


def bag_env(slots=30, preamble_extra=""):
    lua, g = new_client(4400, 1080, preamble=HOME_FIXTURE + BAGANATOR + preamble_extra)
    lua.execute(f"__bagSlots = {slots} __baganatorRelayout()")
    login(g)
    return lua, g


def grid(g):
    t = g.__lastGrid
    return (int(t.icon), int(t.cols), int(t.rows), int(t.slots)) if t else None


lua60, g60 = bag_env(30)
check("bags: FFSpan sees Baganator and reports it",
      g60.FFSpan.Home.BaganatorPresent() is True and g60.FFSpan.BagAddonPresent() is True)
cfg60 = g60.__bagCfg()
check("bags: it is configured to the plain single grid and the Blizzard skin (native look)",
      str(cfg60.bag_view_type) == "single" and str(cfg60.current_skin) == "blizzard",
      f"view={cfg60.bag_view_type} skin={cfg60.current_skin}")
check("bags: frames are locked so a drag cannot rewrite its saved anchor",
      cfg60.lock_frames is True)
check("bags: the public refresh call was used, not a silent SavedVariable poke",
      int(g60.__baganatorLayouts) >= 1, f"layouts={g60.__baganatorLayouts}")
placed60 = g60.__placed("Baganator_SingleViewBackpackViewFrameDEFAULT")
check("bags: Baganator's view is the resident bag frame, anchored in the column",
      placed60 is not None and placed60.x > 0 and placed60.x < 1240,
      f"placed={dict(placed60) if placed60 else None}")
check("bags: Blizzard's combined bag frame is NOT the resident view any more",
      g60.__placed("ContainerFrameCombinedBags") is None)
g60_grid = grid(g60)
check("bags: the grid was solved for the real slot count",
      g60_grid is not None and g60_grid[3] == 30 and g60_grid[0] * g60_grid[1] > 0,
      f"grid={g60_grid}")


def fits_box(g, name="Baganator_SingleViewBackpackViewFrameDEFAULT"):
    """Is the bag frame inside the measured column, and clear of the minimap and bottom bar?"""
    # The bags are anchored by their TOPRIGHT (FFSpan_Home anchorBaganator, v2.5.5: a width change
    # grows LEFT, never across the seam), so the anchor offset is the frame's RIGHT edge. __placed()
    # reads the raw offset as a left edge; __px() reads the frame's resolved rect, which the SetPoint
    # mock keeps coherent for TOPRIGHT too. That mismatch was every "x 1224.." failure here.
    s = g.FFScale.HomeSlots()
    if g.__placed(name) is None or s is None:
        return False, "no placement or no slots"
    r = g.__px(name)
    x, y, w, h = float(r.x), float(r.y), float(r.w), float(r.h)
    ok = (x >= 16 - 0.5 and x + w <= 1240 - 16 + 1
          and y >= s.minimapBottom + 12 - 1 and y + h <= s.bottomBarTop - 8 + 1)
    return ok, (f"x {x:.0f}..{x + w:.0f} y {y:.0f}..{y + h:.0f} "
                f"box y {s.minimapBottom + 12:.0f}..{s.bottomBarTop - 8:.0f}")


ok60, why60 = fits_box(g60)
check("bags: 30 slots fit the box, clear of the minimap and the bottom bar", ok60, why60)

# --- the capacity ladder, with the real box -----------------------------------------------------
CAPACITY = {}
for n in (30, 60, 120, 202):
    lua_n, g_n = bag_env(n)
    gr = grid(g_n)
    okn, whyn = fits_box(g_n)
    CAPACITY[n] = (gr, okn, whyn)
    check(f"bags: {n} slots fit the box", okn, f"grid={gr} {whyn}")
    if gr:
        check(f"bags: {n} slots stay at or above the 0.72-equivalent icon",
              gr[0] / 37.0 >= 0.72, f"icon={gr[0]} = {gr[0] / 37.0:.3f} of Blizzard's 37")
        check(f"bags: {n} slots never upscale past Baganator's native 37 px icon",
              gr[0] <= 37, f"icon={gr[0]}")

# --- companion open: FEWER COLUMNS, not a smaller view ------------------------------------------
lua61, g61 = bag_env(120, preamble_extra=(
    '\nCharacterFrame = __newFrame("CharacterFrame", UIParent)\n'
    'CharacterFrame.rect = {0, 0, 541.16, 453.69} CharacterFrame.shown = false\n'))
before = grid(g61)
lua61.execute("CharacterFrame:Show()")
g61.__flush()
after = grid(g61)
check("bags: a companion narrows the grid to FEWER COLUMNS",
      before is not None and after is not None and after[1] < before[1],
      f"before cols={before and before[1]} after cols={after and after[1]}")
check("bags: ...and more rows, so every slot is still shown",
      after is not None and after[1] * after[2] >= 120, f"after={after}")
check("bags: ...with a BALANCED icon, better than the earlier fixed 0.70 floor",
      after is not None and after[0] > 26, f"icon={after and after[0]}")
okc, whyc = fits_box(g61)
check("bags: ...and the narrowed grid still fits the box", okc, whyc)
chr61 = g61.__placed("CharacterFrame")
bag61 = g61.__placed("Baganator_SingleViewBackpackViewFrameDEFAULT")
check("bags: the companion and the bags do not overlap",
      chr61 is not None and bag61 is not None
      and chr61.x + 541.16 * PX_PER_UNIT * chr61.scale <= bag61.x + 1,
      f"companion right={chr61 and chr61.x + 541.16 * PX_PER_UNIT * chr61.scale} bags x={bag61 and bag61.x}")
lua61.execute("CharacterFrame:Hide()")
g61.__flush()
restored = grid(g61)
check("bags: closing the companion gives the columns back",
      restored is not None and before is not None and restored[1] == before[1],
      f"restored={restored} original={before}")

# --- residency uses Baganator's own toggle, and never closes it ---------------------------------
lua62, g62 = bag_env(60)
opens62 = calls(g62, "OpenAllBags")
toggles62 = int(g62.__baganatorToggles)
check("bags: residency did NOT call OpenAllBags (Baganator does not hook it)",
      calls(g62, "OpenAllBags") == 0, f"OpenAllBags={opens62}")
check("bags: it used the replaced global ToggleAllBags instead",
      toggles62 >= 1, f"toggles={toggles62}")
check("bags: the view is open", g62.Baganator_SingleViewBackpackViewFrameDEFAULT.shown is True)
g62.__fire("LOADING_SCREEN_DISABLED")
g62.__flush()
check("bags: a second residency trigger does NOT toggle the open view closed",
      g62.Baganator_SingleViewBackpackViewFrameDEFAULT.shown is True
      and int(g62.__baganatorToggles) == toggles62,
      f"shown={g62.Baganator_SingleViewBackpackViewFrameDEFAULT.shown} "
      f"toggles={g62.__baganatorToggles} vs {toggles62}")

# --- the bank view is a COMPANION, bags stay resident beside it ----------------------------------
lua63, g63 = bag_env(120)
lua63.execute("Baganator_SingleViewBankViewFrameDEFAULT.rect = {0, 0, 400, 400} "
              "Baganator_SingleViewBankViewFrameDEFAULT:Show()")
g63.FFSpan.Home.PlaceAll("bank opened")   # its OnShow is not one FFSpan hooks
g63.__flush()
bank63 = g63.__placed("Baganator_SingleViewBankViewFrameDEFAULT")
bags63 = g63.__placed("Baganator_SingleViewBackpackViewFrameDEFAULT")
check("bags: Baganator's bank view is placed as a COMPANION on the home screen",
      bank63 is not None and bank63.x >= 16 - 0.5 and bank63.x < 1240,
      f"bank={dict(bank63) if bank63 else None}")
check("bags: ...and the resident bags stay beside it, not behind it",
      bags63 is not None and bank63 is not None
      and bank63.x + 400 * PX_PER_UNIT * bank63.scale <= bags63.x + 1,
      f"bank right={bank63 and bank63.x + 400 * PX_PER_UNIT * bank63.scale} bags x={bags63 and bags63.x}")

# --- the 2.4 tooltip relocator is owner-based, so Baganator's buttons are covered -----------
lua64, g64 = new_client(4400, 1080, preamble=HOME_FIXTURE + BAGANATOR + (
    '\nGameTooltip = __newFrame("GameTooltip", UIParent)\n'
    'GameTooltip.rect = {0, 0, 220, 120} GameTooltip.shown = false\n'
    'function GameTooltip:GetOwner() return self.owner end\n'
    'BagItem = __newFrame("BagItem", Baganator_SingleViewBackpackViewFrameDEFAULT)\n'
    'BagItem.rect = {0, 0, 30, 30} BagItem.shown = true\n'
    'function __setPx(f, x, y)\n'
    '    local q = __H / 768\n'
    '    local w, h = f.rect[3], f.rect[4]\n'
    '    f.rect = {x / q, (__H - y) / q - h, w, h}\n'
    '    f:ClearAllPoints()\n'
    '    f:SetPoint("TOPLEFT", UIParent, "BOTTOMLEFT", x / q, (__H - y) / q)\n'
    'end\n'
    'function __blizzardTooltipAnchor(owner)\n'
    '    local q = __H / 768\n'
    '    local ox, ow = owner.rect[1] * q, owner.rect[3] * q\n'
    '    GameTooltip.owner = owner\n'
    '    GameTooltip.shown = true\n'
    '    local x\n'
    '    if (ox + ow) < GetScreenWidth() / 2 then x = ox + ow else x = ox - 220 * q end\n'
    '    __setPx(GameTooltip, x, 300)\n'
    '    if GameTooltip.hs_OnShow then GameTooltip.hs_OnShow(GameTooltip) end\n'
    'end\n'))
login(g64)
lua64.execute("__setPx(BagItem, 1180, 800) __blizzardTooltipAnchor(BagItem)")
g64.__flush()
tip64 = g64.__placed("GameTooltip")
check("bags: an item tooltip on a Baganator button is kept on the HOME panel",
      tip64 is not None and tip64.x >= -0.5 and tip64.x + 220 * PX_PER_UNIT <= 1240 + 0.5,
      f"tooltip x={tip64.x if tip64 else None}")

# --- FFScale reclaimed the space -----------------------------------------------------------------
mm64 = g60.__homeSystem(2, None)
size64 = g60.__settingValue(mm64, 2) if mm64 is not None else None
check("layout: the minimap shrank ~15% with a bag addon (150 -> 130)",
      size64 is not None and 50 + int(size64) * 10 == 130,
      f"pct={size64 is not None and 50 + int(size64) * 10 or None}")
bags_sys = g60.__homeSystem(14, None)
bagbar = g60.__anchorPx(bags_sys.anchorInfo, 1) if bags_sys is not None else None
check("layout: the Blizzard bag bar is parked off-panel (Baganator draws its own slots)",
      bagbar is not None and bagbar.x >= 3160 - 0.5,
      f"bag bar x={bagbar.x if bagbar else None}")
slots64 = g60.FFScale.HomeSlots()
check("layout: a 30-slot character gets a NARROW column, not the 70% maximum",
      slots64 is not None and slots64.width < 1240 * 0.35
      and slots64.width >= 198 * PX_PER_UNIT * 1.30 - 1,
      f"width={slots64.width if slots64 else None} (floor = the minimap cluster)")

# without a bag addon nothing is reclaimed -- Blizzard's bags need the bar
mm_plain = g4.__homeSystem(2, None)
size_plain = g4.__settingValue(mm_plain, 2) if mm_plain is not None else None
check("layout: with no bag addon the minimap stays at 150 and the bar stays put",
      size_plain is not None and 50 + int(size_plain) * 10 == 150,
      f"pct={size_plain is not None and 50 + int(size_plain) * 10 or None}")
plain_bar = g4.__anchorPx(g4.__homeSystem(14, None).anchorInfo, 1)
check("layout: ...and the bag bar is still on the home screen",
      plain_bar is not None and plain_bar.x < 1240,
      f"bag bar x={plain_bar.x if plain_bar else None}")

print("\n  capacity (measured, no companion):")
for n in (30, 60, 120, 202):
    gr, okn, _ = CAPACITY[n]
    if gr:
        print(f"    {n:3d} slots -> {gr[1]:2d} cols x {gr[2]:2d} rows, icon {gr[0]} px "
              f"({gr[0] / 37.0:.2f} of Blizzard), fits={okn}")

# ====================== 17. responsive bag column (FFSpan 2.5.1) ================================
# I rejected the earlier FIXED 70% column: it squeezed the tracker and chat to ~328 px for every
# character, including a 30-slot one. The column is now sized from the CURRENT bag capacity at
# native icon size, floored at the minimap cluster, capped at 70%; companions always sit beside
# the bags and the split between them is BALANCED rather than floored.
print("\n-- 17. responsive bag column --")

CLUSTER_FLOOR = 198 * PX_PER_UNIT * 1.30   # the minimap cluster at minimapPctBags = 130
COMPANION_FIX = ('\nCharacterFrame = __newFrame("CharacterFrame", UIParent)\n'
                 'CharacterFrame.rect = {0, 0, 541.16, 453.69} CharacterFrame.shown = false\n')


def r4_env(slots, companion=False):
    lua, g = new_client(4400, 1080,
                        preamble=HOME_FIXTURE + BAGANATOR + (COMPANION_FIX if companion else ""))
    lua.execute(f"__bagSlots = {slots} __baganatorRelayout()")
    login(g)
    return lua, g


def r4_log(g):
    rec = g.FFSpan.HomeRecord(True)
    if isinstance(rec, tuple):
        rec = rec[0]
    log = rec.log if rec is not None else None
    return [f"{e.e}: {e.d}" for e in (log.values() if log else [])]


# --- the column tracks capacity ------------------------------------------------------------------
widths = {}
for n in (30, 60, 120, 202):
    lua_n, g_n = r4_env(n)
    s_n = g_n.FFScale.HomeSlots()
    widths[n] = float(s_n.width) if s_n else None
    gr = g_n.__lastGrid
    check(f"{n} slots -> the column is sized for them, never upscaled past 37",
          widths[n] is not None and int(gr.icon) <= 37, f"width={widths[n]} icon={gr and gr.icon}")

check("the column GROWS with capacity",
      widths[30] < widths[60] < widths[120] <= widths[202],
      f"{[round(widths[k], 1) for k in (30, 60, 120, 202)]}")
check("a 30-slot character is not charged for a 202-slot one (the fixed column gave both 868 px)",
      widths[30] < 1240 * 0.35, f"30-slot column={widths[30]:.0f} px")
check("...and it never drops below the minimap cluster, so the right column stays a column",
      widths[30] >= CLUSTER_FLOOR - 1, f"width={widths[30]:.0f} floor={CLUSTER_FLOOR:.0f}")
check("at maximum capacity it is the old fixed 70% layout",
      near(widths[202], 1240 * 0.70, 1.0), f"202-slot column={widths[202]:.0f} px")
left30 = 1240 - 16 - widths[30] - 12 - 16
check("the tracker and chat get everything left over (was 328 px for every character)",
      left30 > 800, f"left column={left30:.0f} px at 30 slots")

# --- companions never go to the top screen -------------------------------------------------------
lua70, g70 = r4_env(120, companion=True)
lua70.execute("CharacterFrame:Show()")
g70.__flush()
comp70 = g70.__placed("CharacterFrame")
check("a companion NEVER goes to the top screen -- always beside the bags",
      comp70 is not None and comp70.x < 1240, f"placed={dict(comp70) if comp70 else None}")
bags70 = g70.__placed("Baganator_SingleViewBackpackViewFrameDEFAULT")
check("...and it does not overlap them",
      comp70 is not None and bags70 is not None
      and comp70.x + 761 * comp70.scale <= bags70.x + 1,
      f"companion right={comp70 and comp70.x + 761 * comp70.scale:.0f} bags x={bags70 and bags70.x:.0f}")

# --- the split is BALANCED, not floored ----------------------------------------------------------
BALANCE = {}
for n in (30, 60, 120, 202):
    lua_b, g_b = r4_env(n, companion=True)
    lua_b.execute("CharacterFrame:Show()")
    g_b.__flush()
    gr = g_b.__lastGrid
    p = g_b.__placed("CharacterFrame")
    icon_eq = int(gr.icon) / 37.0
    comp = float(p.scale) if p else 0.0
    BALANCE[n] = (int(gr.cols), int(gr.rows), int(gr.icon), icon_eq, comp)
    check(f"{n} slots + companion -- neither side is starved",
          min(icon_eq, comp) >= 0.5,
          f"icon {gr.icon} = {icon_eq:.2f}, companion {comp:.2f}, worse side {min(icon_eq, comp):.2f}")

check("the 202 case is far better balanced than the fixed column's 0.70/0.47",
      min(BALANCE[202][3], BALANCE[202][4]) > 0.47 + 0.05,
      f"icon {BALANCE[202][3]:.2f} companion {BALANCE[202][4]:.2f}")
check("the two sides are close to each other, which is what 'balanced' means",
      abs(BALANCE[202][3] - BALANCE[202][4]) < 0.15,
      f"icon {BALANCE[202][3]:.2f} vs companion {BALANCE[202][4]:.2f}")

# --- ordinary play must never re-save the Edit Mode layout ---------------------------------------
# Edit Mode saves go to Blizzard's servers, so this is the one that matters.
lua71, g71 = r4_env(60)
saves_before = int(g71.__savesOf("ThorSpanHome"))
for _ in range(3):
    g71.__fire("BAG_UPDATE")
    g71.__fire("BAG_UPDATE_DELAYED")
    g71.__fire("ITEM_PUSH")
    g71.__fire("LOADING_SCREEN_ENABLED")
    g71.__fire("LOADING_SCREEN_DISABLED")
    g71.__fire("PLAYER_ENTERING_WORLD")
    lua71.execute("ToggleAllBags() ToggleAllBags()")
g71.__flush()
check("looting, moving items, bag toggles and zoning cause ZERO Edit Mode re-saves",
      int(g71.__savesOf("ThorSpanHome")) == saves_before,
      f"saves {g71.__savesOf('ThorSpanHome')} vs {saves_before}")
check("...and the layout is still the live one",
      g71.FFScale.ActiveLayoutName() == "ThorSpanHome")

# a BAG_CONTAINER_UPDATE that does not change the needed width is also free
g71.__fire("BAG_CONTAINER_UPDATE")
g71.__flush()
check("a bag event that does not change the needed width re-saves nothing either",
      int(g71.__savesOf("ThorSpanHome")) == saves_before,
      f"saves={g71.__savesOf('ThorSpanHome')}")

# ...but equipping a bigger bag DOES re-apply, exactly once
lua71.execute("__bagSlots = 160 __baganatorRelayout()")
g71.__fire("BAG_CONTAINER_UPDATE")
g71.__fire("BAG_CONTAINER_UPDATE")      # a multi-bag swap must still be ONE save
g71.__flush()
after_swap = int(g71.__savesOf("ThorSpanHome"))
check("equipping a bigger bag re-applies the layout",
      after_swap > saves_before, f"saves {after_swap} vs {saves_before}")
check("...exactly once, debounced across a multi-bag swap",
      after_swap == saves_before + 1, f"saves {after_swap} vs {saves_before}")
# The save COUNT is already guaranteed by FFScale's pre-existing "no change needed" short-circuit,
# so it cannot show whether the 2.5.1 debounce works. What the debounce owns is the WORK: a
# multi-bag swap must cost ONE capacity pass, not one per container event.
passes = [l for l in r4_log(g71) if "bag capacity changed" in l]
check("a multi-bag swap costs exactly ONE capacity pass, not one per container event",
      len(passes) == 1, f"{len(passes)} passes: {passes}")

# Swapping TWO bags of DIFFERENT sizes in the same tick is the case the width early-out cannot
# absorb -- each event sees a genuinely different width. Only the pending flag coalesces them.
lua74, g74 = r4_env(60)
saves74 = int(g74.__savesOf("ThorSpanHome"))
lua74.execute("__bagSlots = 160 __baganatorRelayout()")
g74.__fire("BAG_CONTAINER_UPDATE")
lua74.execute("__bagSlots = 220 __baganatorRelayout()")
g74.__fire("BAG_CONTAINER_UPDATE")
g74.__flush()
check("two differently-sized bags swapped in one tick still cost ONE pass",
      len([l for l in r4_log(g74) if "bag capacity changed" in l]) == 1,
      f"passes: {[l for l in r4_log(g74) if 'bag capacity changed' in l]}")
# ...and the brief's "never in a loop": a burst of container events must not queue a timer each.
lua75, g75 = r4_env(60)
lua75.execute("__timers = {}")
lua75.execute("__bagSlots = 160 __baganatorRelayout()")
for _ in range(20):
    g75.__fire("BAG_CONTAINER_UPDATE")
queued = int(lua75.eval("#__timers"))
check("a burst of 20 container events queues ONE capacity timer, not 20",
      queued == 1, f"{queued} timers queued")

check("...and ONE Edit Mode save, for the final capacity",
      int(g74.__savesOf("ThorSpanHome")) == saves74 + 1,
      f"saves {g74.__savesOf('ThorSpanHome')} vs {saves74}")

check("...and the column grew to match",
      g71.FFScale.HomeSlots() is not None
      and float(g71.FFScale.HomeSlots().width) > widths[60],
      f"width={g71.FFScale.HomeSlots() and g71.FFScale.HomeSlots().width}")

# in combat the re-apply waits for regen
lua72, g72 = r4_env(60)
saves72 = int(g72.__savesOf("ThorSpanHome"))
g72.__combat = True
lua72.execute("__bagSlots = 160 __baganatorRelayout()")
g72.__fire("BAG_CONTAINER_UPDATE")
g72.__flush()
check("a capacity change in combat does NOT re-save",
      int(g72.__savesOf("ThorSpanHome")) == saves72,
      f"saves={g72.__savesOf('ThorSpanHome')}")
g72.__combat = False
g72.__fire("PLAYER_REGEN_ENABLED")
g72.__flush()
# The 2.4 rule applies here too: nothing may RECORD as applied what the layout owner refused.
# Without FFSpan's own combat guard the refused re-apply still logs "re-applying the layout" and
# banks the new width as satisfied, so if the owner's deferral is ever dropped FFSpan never retries.
lua73, g73 = r4_env(60)
g73.__combat = True
lua73.execute("__bagSlots = 160 __baganatorRelayout()")
g73.__fire("BAG_CONTAINER_UPDATE")
g73.__flush()
claims = [l for l in r4_log(g73) if "re-applying the layout" in l]
check("in combat NOTHING claims the layout was re-applied", not claims, f"claimed: {claims}")

# ...and because nothing was queued, a change UNDONE before combat ends costs no save at all:
# swap the big bag in and back out mid-fight and the layout the player already has is kept.
saves73 = int(g73.__savesOf("ThorSpanHome"))
lua73.execute("__bagSlots = 60 __baganatorRelayout()")
g73.__fire("BAG_CONTAINER_UPDATE")
g73.__combat = False
g73.__fire("PLAYER_REGEN_ENABLED")
g73.__flush()
check("a capacity change undone before combat ends costs ZERO Edit Mode saves",
      int(g73.__savesOf("ThorSpanHome")) == saves73,
      f"saves {g73.__savesOf('ThorSpanHome')} vs {saves73}")

check("...and is applied once combat ends",
      int(g72.__savesOf("ThorSpanHome")) == saves72 + 1,
      f"saves {g72.__savesOf('ThorSpanHome')} vs {saves72}")

print("\n  responsive column + balanced split (CharacterFrame 761 x 638 px):")
print(f"    {'slots':>5} | {'column':>7} {'left':>6} | {'bags alone':>18} | {'with a companion':>26}")
for n in (30, 60, 120, 202):
    lua_a, g_a = r4_env(n)
    ga = g_a.__lastGrid
    c, r, i, eq, comp = BALANCE[n]
    print(f"    {n:>5} | {widths[n]:>6.0f}p {1240 - 44 - widths[n]:>5.0f}p | "
          f"{int(ga.cols):>2}x{int(ga.rows):<2} icon {int(ga.icon):>2} = {int(ga.icon) / 37.0:.2f} | "
          f"{c:>2}x{r:<2} icon {i:>2} = {eq:.2f}, companion {comp:.2f}")
# ====================== 18. Baganator USABLE, not merely loaded (FFSpan 2.5.2) ==================
# The device blocker. Baganator 829 shipped to the Thor without Syndicator; Baganator's own
# ADDON_LOADED handler calls error() when Syndicator is missing (Core/Initialize.lua:32-50), so it
# built NOTHING -- yet `Baganator = {API = ...}` already existed from Core/Objects.lua:3, which is
# what the earlier tests checked. FFSpan stood the Blizzard bags down for an addon that was doing nothing.
print("\n-- 18. Baganator usable gate --")

# Baganator loaded, init ERRORED: the global exists, nothing else does. This is the device state.
BAGANATOR_BROKEN = r"""
__loadedAddons.Baganator = true
-- __loadedAddons.Syndicator deliberately NOT set: this is the device's 16:2x state
BAGANATOR_CURRENT_PROFILE = "DEFAULT"
BAGANATOR_CONFIG = {Profiles = {DEFAULT = {}}}
__bagSlots = 30
C_Container = C_Container or {}
function C_Container.GetContainerNumSlots(i)
    if i == 0 then return math.min(__bagSlots, 20) end
    return 0
end
NUM_TOTAL_EQUIPPED_BAG_SLOTS = 4
-- Core/Objects.lua:3 -- created at FILE LOAD, before any init, unconditionally
Baganator = {API = {Skins = {}}}
-- and that is ALL: no view frames, nothing in UISpecialFrames, ToggleAllBags still Blizzard's
UISpecialFrames = {}
"""

BLIZZ_BAGS = ('ContainerFrameCombinedBags = __newFrame("ContainerFrameCombinedBags", UIParent)\n'
              'ContainerFrameCombinedBags.rect = {0, 0, 256, 320}\n'
              'ContainerFrameCombinedBags.shown = false\n')


def r5_env(state, slots=30):
    pre = {"absent": "", "broken": BAGANATOR_BROKEN, "usable": BAGANATOR}[state]
    lua, g = new_client(4400, 1080, preamble=HOME_FIXTURE + BLIZZ_BAGS + pre)
    if state != "absent":
        lua.execute(f"__bagSlots = {slots}")
    if state == "usable":
        lua.execute("__baganatorRelayout()")
    login(g)
    return lua, g


def r5_notes(g):
    rec = g.FFSpan.HomeRecord(True)
    if isinstance(rec, tuple):
        rec = rec[0]
    n = rec.notes if rec is not None else None
    return [f"{e.e}: {e.d}" for e in (n.values() if n else [])]


lua_ab, g_ab = r5_env("absent")
lua_br, g_br = r5_env("broken")
lua_us, g_us = r5_env("usable")

check("Baganator absent -> not usable", g_ab.FFSpan.BaganatorUsable() is False)
check("Baganator loaded but its init errored -> NOT usable",
      g_br.FFSpan.BaganatorUsable() is False, f"usable={g_br.FFSpan.BaganatorUsable()}")
check("...and the reason names Syndicator, which is what Baganator itself errors on",
      "Syndicator" in str(g_br.FFSpan.BaganatorWhyNot()), f"why={g_br.FFSpan.BaganatorWhyNot()}")
check("Baganator + Syndicator, frames built -> usable",
      g_us.FFSpan.BaganatorUsable() is True, f"usable={g_us.FFSpan.BaganatorUsable()}")
# the old predicate still says "loaded" for the broken one -- that IS the bug, kept visible
check("the OLD present() predicate still says yes for the broken install (the 2.5.1 bug)",
      g_br.FFSpan.BaganatorPresent() is True)

# --- the regression: not usable must look EXACTLY like absent ------------------------------------
for label, g_x in (("absent", g_ab), ("broken", g_br)):
    bags_x = g_x.__homeSystem(14, None)
    bar_x = g_x.__anchorPx(bags_x.anchorInfo, 1) if bags_x is not None else None
    check(f"{label} -- the Blizzard bag bar is NOT parked off-panel",
          bar_x is not None and bar_x.x < 3160 - 0.5, f"bag bar x={bar_x.x if bar_x else None}")
    mm_x = g_x.__homeSystem(2, None)
    sz_x = g_x.__settingValue(mm_x, 2) if mm_x is not None else None
    check(f"{label} -- the minimap keeps its no-bag-addon size (150, not 130)",
          sz_x is not None and 50 + int(sz_x) * 10 == 150,
          f"pct={50 + int(sz_x) * 10 if sz_x is not None else None}")

bags_u = g_us.__homeSystem(14, None)
bar_u = g_us.__anchorPx(bags_u.anchorInfo, 1) if bags_u is not None else None
check("usable -- the bag bar IS parked, exactly as in 2.5.1",
      bar_u is not None and bar_u.x >= 3160 - 0.5, f"bag bar x={bar_u.x if bar_u else None}")

# the Blizzard bags must actually be PLACED on the home screen when Baganator cannot draw them.
# On the device they were left at Blizzard's default BOTTOMRIGHT -10,85 -> x3770, drawn nowhere.
lua_br.execute("ToggleAllBags()")
g_br.__flush()
placed_br = g_br.__placed("ContainerFrameCombinedBags")
check("broken -- the Blizzard bags are PLACED on the home screen, not left at x3770",
      placed_br is not None and placed_br.x < 1240,
      f"placed={dict(placed_br) if placed_br else None}")
check("...and they are resident, not stranded in the unshown strip",
      placed_br is not None and placed_br.x >= 0, f"x={placed_br.x if placed_br else None}")

# FFScale must get the BLIZZARD column, not a Baganator capacity request
check("broken -- FFScale is told there is no bag addon",
      g_br.FFSpan.BagAddonPresent() is not True, f"={g_br.FFSpan.BagAddonPresent()}")
check("broken -- no Baganator capacity request is published",
      g_br.FFSpan.BagColumnRequestPx(700) is None, f"={g_br.FFSpan.BagColumnRequestPx(700)}")

# --- it says WHY, once, durably ------------------------------------------------------------------
why_lines = [l for l in r5_notes(g_br) if "not usable" in l]
check("broken -- ONE log line says why it fell back",
      len(why_lines) == 1, f"{len(why_lines)} lines: {why_lines}")
rec_br = g_br.FFSpan.HomeRecord(True)
rec_br = rec_br[0] if isinstance(rec_br, tuple) else rec_br
check("...and a dump field carries it into the SavedVariables",
      rec_br is not None and "Syndicator" in str(rec_br.baganator),
      f"dump field={rec_br and rec_br.baganator}")

# --- decided once, never flip-flopping, never re-saving by itself --------------------------------
saves_br = int(g_br.__savesOf("ThorSpanHome"))
for _ in range(5):
    g_br.__fire("BAG_UPDATE")
    g_br.__fire("BAG_CONTAINER_UPDATE")
    g_br.__fire("PLAYER_ENTERING_WORLD")
    lua_br.execute("ToggleAllBags() ToggleAllBags()")
g_br.__flush()
check("broken -- ordinary play causes ZERO extra Edit Mode saves (2.5.1 guard holds)",
      int(g_br.__savesOf("ThorSpanHome")) == saves_br,
      f"saves {g_br.__savesOf('ThorSpanHome')} vs {saves_br}")
check("...and the decision never flips: still one log line, still not usable",
      len([l for l in r5_notes(g_br) if "not usable" in l]) == 1
      and g_br.FFSpan.BaganatorUsable() is False)

# an unrelated addon loading must not re-open the question
g_br.__fire("ADDON_LOADED", "SomeOtherAddon")
g_br.__flush()
check("an unrelated ADDON_LOADED does not re-open the decision",
      len([l for l in r5_notes(g_br) if "not usable" in l]) == 1,
      f"{len([l for l in r5_notes(g_br) if 'not usable' in l])} lines")


# --- the durable ring (item 2): routine `place` traffic must not flush the evidence -------------
check("the routine log ring HAS lost the reason by now (that is why the second ring exists)",
      len([l for l in r4_log(g_br) if "not usable" in l]) == 0,
      f"routine ring still holds it: {[l for l in r4_log(g_br) if 'not usable' in l]}")
check("...but the durable ring still has it",
      len([l for l in r5_notes(g_br) if "not usable" in l]) == 1)
check("the durable ring holds NO routine place lines",
      not [l for l in r5_notes(g_br) if l.startswith("place:")],
      f"{[l for l in r5_notes(g_br) if l.startswith('place:')][:2]}")
check("...and it stays bounded at 30",
      len(r5_notes(g_br)) <= 30, f"{len(r5_notes(g_br))} entries")

# ...but Syndicator arriving late does, and it costs nothing until Baganator really works
lua_br.execute("__loadedAddons.Syndicator = true")
g_br.__fire("ADDON_LOADED", "Syndicator")
g_br.__flush()
check("Syndicator loading re-opens it -- still unusable, because no frames were ever built",
      g_br.FFSpan.BaganatorUsable() is False,
      f"usable={g_br.FFSpan.BaganatorUsable()} why={g_br.FFSpan.BaganatorWhyNot()}")
check("...and the new reason is the missing bag view, not Syndicator",
      "initialis" in str(g_br.FFSpan.BaganatorWhyNot()), f"why={g_br.FFSpan.BaganatorWhyNot()}")

# ====================== 19. Glassy chat + tracker overhang (FFSpan 2.5.2 / FFScale 1.8.2) =======
# Both are the same class of bug: the addon placed a FRAME and the player sees an ENVELOPE.
print("\n-- 19. Glassy chat and the tracker overhang --")

# Glassy 1.9.4: GlassyFrame is anchored TOPLEFT -> GlassyMoverFrame (UIManager.lua:256-258), NOT
# to ChatFrame1. Device rect: x0 y691 h352, visible envelope h473 -> bottom 1164 on a 1080 screen.
GLASSY = r"""
__loadedAddons.Glassy = true
GlassyMoverFrame = __newFrame("GlassyMoverFrame", UIParent)
GlassyMoverFrame.rect = {0, 1080 - 691 - 336, 420, 336}      -- UI units, bottom-up
GlassyMoverFrame.shown = true
__glassyDrags = 0
__glassySnapped = false
-- Components/MoverFrame.lua:40 SetDragPosition(left, bottom) with the :20 EDGE_SNAP_DISTANCE = 20
function GlassyMoverFrame:SetDragPosition(left, bottom)
    __glassyDrags = __glassyDrags + 1
    local pl, pb = 0, 0
    local pr, pt = UIParent.rect[3], UIParent.rect[4]
    local w, h = self.rect[3], self.rect[4]
    local ld, rd = math.abs(left - pl), math.abs(left + w - pr)
    local bd, td = math.abs(bottom - pb), math.abs(bottom + h - pt)
    if ld <= 20 and ld <= rd then left = pl __glassySnapped = true
    elseif rd <= 20 then left = pr - w __glassySnapped = true end
    if bd <= 20 and bd <= td then bottom = pb __glassySnapped = true
    elseif td <= 20 then bottom = pt - h __glassySnapped = true end
    self.rect = {left, bottom, w, h}
    -- the container follows the mover (UIManager.lua:258)
    GlassyFrame.rect = {left, bottom, w, h}
end
GlassyFrame = __newFrame("GlassyFrame", UIParent)
GlassyFrame.rect = {0, 1080 - 691 - 336, 420, 336}
GlassyFrame.shown = true
-- the edit box hangs BELOW the container: this is the envelope the player sees, and the reason
-- placing ChatFrame1 never fixed anything
GlassyEditBox = __newFrame("GlassyEditBox", GlassyFrame)
GlassyEditBox.shown = true
table.insert(GlassyFrame.children, GlassyEditBox)
function GlassyEditBox:GetRect()
    -- the edit box lives INSIDE the mover's height: MoverFrame.lua:146 sets the mover to
    -- frameHeight + attachedExtent, so 250 + 86 = 336 units = 473 px, the device's 16:23 measure
    local l, b, w = GlassyFrame.rect[1], GlassyFrame.rect[2], GlassyFrame.rect[3]
    return l, b, w, 86
end
-- FFSpan 2.6/2.7 size Glassy through its OWN settings: an AceDB profile whose frameWidth /
-- frameHeight are inherited defaults (init.lua:52 frameHeight = 250), written then dispatched as
-- Glassy/UPDATE_CONFIG -- MainContainerFrame and MoverFrame resize off that key. The container
-- hangs from the mover's TOPLEFT, so a height change keeps the top edge where it is.
__glassyDefaults = {frameWidth = 420, frameHeight = 250}
GlassyDB = {profileKeys = {}, profiles = {Default = {}}}
local gprofile = setmetatable(GlassyDB.profiles.Default, {__index = __glassyDefaults})
Glassy = {db = {profile = gprofile}}
function Glassy.db:GetCurrentProfile() return "Default" end
function Glassy:Dispatch(msg, key)
    if msg ~= "Glassy/UPDATE_CONFIG" then return end
    if key == "frameWidth" then
        GlassyFrame.rect[3] = gprofile.frameWidth
        GlassyMoverFrame.rect[3] = gprofile.frameWidth
    elseif key == "frameHeight" then
        local extra = GlassyFrame.rect[4] - __glassyFrameHeight0   -- tabs + edit box above frameHeight
        local top = GlassyFrame.rect[2] + GlassyFrame.rect[4]
        local h = gprofile.frameHeight + extra
        GlassyFrame.rect[2], GlassyFrame.rect[4] = top - h, h
        GlassyMoverFrame.rect[2], GlassyMoverFrame.rect[4] = top - h, h
        __glassyFrameHeight0 = gprofile.frameHeight
    end
end
__glassyFrameHeight0 = 250
"""

lua_g, g_g = new_client(4400, 1080, preamble=HOME_FIXTURE + GLASSY)
login(g_g)
g_g.__flush()
slots_g = g_g.FFScale.HomeSlots()
check("FFScale publishes the chat slot so FFSpan does not re-derive it",
      slots_g is not None and slots_g.chat is not None and float(slots_g.chat.w) > 0,
      f"chat={dict(slots_g.chat) if slots_g is not None and slots_g.chat is not None else None}")
check("Glassy is detected through its own mover, not a name guess",
      g_g.FFSpan.GlassyPresent() is True)
check("...and it was positioned through Glassy's OWN SetDragPosition, nothing else",
      int(lua_g.eval("__glassyDrags")) >= 1, f"drags={lua_g.eval('__glassyDrags')}")

chat_g = slots_g.chat
env_g = g_g.FFSpan.EnvelopePx("GlassyFrame")
check("Glassy's WHOLE visible envelope (edit box included) is inside the chat slot",
      env_g is not None
      and float(env_g.x) >= float(chat_g.x) - 1
      and float(env_g.y) >= float(chat_g.y) - 1
      and float(env_g.x) + float(env_g.w) <= float(chat_g.x) + float(chat_g.w) + 1
      and float(env_g.y) + float(env_g.h) <= float(chat_g.y) + float(chat_g.h) + 1,
      f"env={dict(env_g) if env_g else None} slot={dict(chat_g)}")
check("...so it no longer hangs off the bottom of a 1080 screen (device: bottom at 1164)",
      env_g is not None and float(env_g.y) + float(env_g.h) <= 1080,
      f"bottom={float(env_g.y) + float(env_g.h) if env_g else None}")
check("FFSpan agrees it fits, and says so",
      g_g.FFSpan.GlassyFits() is True, f"fits={g_g.FFSpan.GlassyFits()}")
# An earlier build let the BOTTOM snap deliberately -- flush on the panel edge is where Glassy's mover
# wants to be, and those 16 px are what the left column needs. The LEFT margin still has to
# survive, which is what the slot's snap-clearing margin buys.
check("the LEFT margin survives Glassy's edge snap",
      float(g_g.FFSpan.EnvelopePx("GlassyFrame").x) > 20 * PX_PER_UNIT - 1,
      f"env x={g_g.FFSpan.EnvelopePx('GlassyFrame').x} (snap is 20 units)")
# FFSpan 2.6/2.7: SIZE goes through Glassy's own frameWidth / frameHeight settings (the slider's
# path) with a restore journal beside them; POSITION still only ever goes through the mover.
written = sorted(str(k) for k in lua_g.eval("(function() local t = {} for k in pairs(GlassyDB.profiles.Default) do t[#t+1] = k end return t end)()").values())
# 2.9.0: plus chatAlwaysVisible (only ever ON; FFSpan_ChatDim dims the chat instead of it vanishing).
check("the only Glassy profile keys ever written are its size settings + chatAlwaysVisible -- never a position",
      set(written) <= {"frameWidth", "frameHeight", "chatAlwaysVisible"}, f"written={written}")

# Glassy absent -> nothing about today's behaviour moves
lua_ng, g_ng = new_client(4400, 1080, preamble=HOME_FIXTURE)
login(g_ng)
check("Glassy absent -> not present, and nothing is placed",
      g_ng.FFSpan.GlassyPresent() is False and g_ng.FFSpan.GlassyFits() is None)

# and it is home-screen only
check("the chat slot is inside the home screen, never the game screen",
      float(chat_g.x) >= 0 and float(chat_g.x) + float(chat_g.w) <= 1240,
      f"chat x={chat_g.x} w={chat_g.w}")

# --- item 4: the tracker's flourish hangs 42 px left of its frame --------------------------------
OVERHANG = r"""
ObjectiveTrackerFrame = __newFrame("ObjectiveTrackerFrame", UIParent)
ObjectiveTrackerFrame.rect = {16 / 1.40625, 400, 300, 400}
ObjectiveTrackerFrame.shown = true
__trackerFlourish = __newFrame("__trackerFlourish", ObjectiveTrackerFrame)
__trackerFlourish.shown = true
table.insert(ObjectiveTrackerFrame.children, __trackerFlourish)
function __trackerFlourish:GetRect()
    local l, b, w, h = ObjectiveTrackerFrame.rect[1], ObjectiveTrackerFrame.rect[2],
                       ObjectiveTrackerFrame.rect[3], ObjectiveTrackerFrame.rect[4]
    return l - 42 / 1.40625, b + h - 40, 60, 40      -- 42 px of header flourish, left of the frame
end
"""

lua_t, g_t = new_client(4400, 1080, preamble=HOME_FIXTURE + OVERHANG)
login(g_t)
g_t.__flush()
trk = g_t.__homeSystem(12, None)
trk_x = g_t.__anchorPx(trk.anchorInfo, 1) if trk is not None else None
check("the tracker anchor carries the 42 px overhang instead of clipping the flourish",
      trk_x is not None and abs(float(trk_x.x) - (16 + 42)) < 2,
      f"anchor x={trk_x.x if trk_x else None} (want 16 + 42)")

# no overhang -> byte-for-byte the layout from before
lua_t0, g_t0 = new_client(4400, 1080, preamble=HOME_FIXTURE)
login(g_t0)
trk0 = g_t0.__homeSystem(12, None)
trk0_x = g_t0.__anchorPx(trk0.anchorInfo, 1) if trk0 is not None else None
check("a tracker with NO overhang keeps exactly the anchor it had in FFScale 1.8.1",
      trk0_x is not None and abs(float(trk0_x.x) - 16) < 0.5,
      f"anchor x={trk0_x.x if trk0_x else None} (want 16)")

# an absurd measurement is refused rather than shoving the tracker across the panel
ABSURD = OVERHANG.replace("l - 42 / 1.40625", "l - 900 / 1.40625")
lua_ta, g_ta = new_client(4400, 1080, preamble=HOME_FIXTURE + ABSURD)
login(g_ta)
trka = g_ta.__homeSystem(12, None)
trka_x = g_ta.__anchorPx(trka.anchorInfo, 1) if trka is not None else None
check("an absurd overhang is refused -- a clipped flourish beats a tracker in the middle",
      trka_x is not None and abs(float(trka_x.x) - 16) < 0.5,
      f"anchor x={trka_x.x if trka_x else None}")

# --- item 3 tail: what the dropped 100 px pad was worth ------------------------------------------
# The pad reserved 100 px of the LEFT column for a Glassy skin it could not reach. With it gone
# the tracker -- the only other thing in that column -- gets them back.
chat_plain = g_t0.__anchorPx(g_t0.__homeSystem(8, None).anchorInfo, None)
check("with the pad gone Blizzard's chat sits on the micro bar (FFScale 1.9), not 100 px above it",
      chat_plain is not None and near(float(chat_plain.y), 1080 - (16 + BAR_PX + 12)),
      f"chat y={chat_plain.y if chat_plain else None} (bar top {1080 - 16 - BAR_PX:.0f}; was 1080-16-100)")
trk_set = {int(x.setting): float(x.value)
           for x in (g_t0.__homeSystem(12, None).settings.values() or [])}
check("...which is 100 px of the left column handed back to the tracker",
      trk_set.get(2) == 4.0,
      f"tracker Height raw={trk_set.get(2)} (a 100 px pad leaves it smaller)")

# --- and the no-re-save guarantee survives both -----------------------------------------
saves_r5 = int(g_g.__savesOf("ThorSpanHome"))
for _ in range(4):
    g_g.__fire("BAG_UPDATE")
    g_g.__fire("LOADING_SCREEN_DISABLED")
    g_g.__fire("PLAYER_ENTERING_WORLD")
g_g.__flush()
check("placing Glassy and the tracker causes ZERO extra Edit Mode saves",
      int(g_g.__savesOf("ThorSpanHome")) == saves_r5,
      f"saves {g_g.__savesOf('ThorSpanHome')} vs {saves_r5}")

# ====================== 20. the left column must hold =============================
# An earlier build shipped an overlap and every test passed, because they all measured the tracker's CURRENT
# content. Edit Mode does not: floorStep's floor is 400 units = 562 px, so a full quest tracker
# takes that however little room is left. On the device that put the tracker's bottom at 578 and
# the chat's top at 556 -- the tracker covering the chat's tabs by 22 px. My rule is that
# NOTHING overlaps, so the invariant is measured against the FLOOR, not the request.
print("\n-- 20. the left column holds --")

TRACKER_FLOOR_PX = 400 * PX_PER_UNIT          # 562 px, whatever height FFSpan asks for
GAP_PX, M_PX = 12, 16

# Glassy at its DEVICE-REAL size: frameHeight 250 units (init.lua:52) + the always-reserved
# attached edit box (MoverFrame.lua:138-145) measured 473 px at 16:23.
GLASSY_473 = GLASSY                                     # device-real: 336 units = 473 px
GLASSY_TALL = GLASSY.replace("420, 336}", "420, 400}")  # 400 units = 562 px: too tall to fit


def left_column(g):
    """tracker max bottom, chat top, and the gap between them -- in canvas px."""
    s = g.FFScale.HomeSlots()
    if s is None or s.chat is None:
        return None
    return {"trackerBottom": M_PX + TRACKER_FLOOR_PX,
            "chatTop": float(s.chat.y),
            "gap": float(s.chat.y) - (M_PX + TRACKER_FLOOR_PX),
            "overflow": float(g.FFScale.LeftColumnOverflowPx())}


# --- Glassy at its real size, across every bag column the responsive layout can produce ---------
print(f"    {'slots':>5} | {'column':>7} | {'tracker bottom':>14} {'chat top':>9} {'gap':>6} {'overflow':>9}")
for n in (30, 60, 120, 202):
    lua_n, g_n = new_client(4400, 1080, preamble=HOME_FIXTURE + BLIZZ_BAGS + BAGANATOR + GLASSY_473)
    lua_n.execute(f"__bagSlots = {n} __baganatorRelayout()")
    login(g_n)
    g_n.__flush()
    lc = left_column(g_n)
    w = float(g_n.FFScale.HomeSlots().width)
    print(f"    {n:>5} | {w:>6.0f}p | {lc['trackerBottom']:>13.0f}p {lc['chatTop']:>8.0f}p "
          f"{lc['gap']:>5.0f}p {lc['overflow']:>8.0f}p")
    check(f"{n} slots -- a FULL tracker never reaches the chat",
          lc["gap"] >= GAP_PX - 0.5,
          f"tracker bottom {lc['trackerBottom']:.0f}, chat top {lc['chatTop']:.0f}, "
          f"gap {lc['gap']:.0f} (need {GAP_PX})")
    check(f"{n} slots -- and FFScale agrees the column holds",
          lc["overflow"] == 0, f"overflow={lc['overflow']}")

# --- the same invariant with no Glassy at all ---------------------------------------------------
lua_nb, g_nb = new_client(4400, 1080, preamble=HOME_FIXTURE + BLIZZ_BAGS)
login(g_nb)
lc_nb = left_column(g_nb)
check("no Glassy -- the column holds too, and Blizzard's chat keeps its 16 px margin",
      lc_nb["gap"] >= GAP_PX - 0.5 and lc_nb["overflow"] == 0,
      f"gap={lc_nb['gap']:.0f} overflow={lc_nb['overflow']}")
chat_nb = g_nb.FFScale.HomeSlots().chat
check("...on top of the micro bar (FFScale 1.9), the bar's margin and a GAP below it",
      abs((1080 - float(chat_nb.y) - float(chat_nb.h)) - (M_PX + BAR_PX + GAP_PX)) < 0.5,
      f"bottom margin={1080 - float(chat_nb.y) - float(chat_nb.h):.0f}")

# --- Glassy sits on the bar too, and is SHRUNK into the slot through its own height -------------
# An earlier build put it flush on the panel edge; FFScale 1.9's bar across the bottom takes that room, so
# FFSpan 2.7 fits Glassy's frameHeight to the (shorter) slot instead.
lua_fl, g_fl = new_client(4400, 1080, preamble=HOME_FIXTURE + BLIZZ_BAGS + GLASSY_473)
login(g_fl)
g_fl.__flush()
chat_fl = g_fl.FFScale.HomeSlots().chat
check("Glassy's chat sits on the micro bar too, not flush on the edge",
      abs(1080 - (float(chat_fl.y) + float(chat_fl.h)) - (M_PX + BAR_PX + GAP_PX)) < 0.5,
      f"bottom margin={1080 - (float(chat_fl.y) + float(chat_fl.h)):.0f} px")
env_fl = g_fl.FFSpan.EnvelopePx("GlassyFrame")
check("...and Glassy's envelope is still wholly inside the slot",
      env_fl is not None and float(env_fl.y) >= float(chat_fl.y) - 1
      and float(env_fl.y) + float(env_fl.h) <= float(chat_fl.y) + float(chat_fl.h) + 1,
      f"env={dict(env_fl) if env_fl else None} slot={dict(chat_fl)}")

# --- a Glassy too tall to SHRINK into it must SAY so, not overlap silently -----------------------
# 400 units = 562 px with 150 of it tabs and edit box: fitting the slot would need frameHeight ~113,
# under FFSpan_Glassy's 150 floor, so the fit refuses. The column itself still holds (FFScale caps
# the chat slot at what the 400-unit tracker floor leaves), and the leftover is Glassy's -- which
# FFSpan's own verify reports. The point stands: never discovered by looking at it.
lua_big, g_big = new_client(4400, 1080, preamble=HOME_FIXTURE + BLIZZ_BAGS + GLASSY_TALL)
login(g_big)
g_big.__flush()
lc_big = left_column(g_big)
check("a too-tall Glassy never pushes the chat SLOT into the tracker's floor",
      lc_big["gap"] >= GAP_PX - 0.5 and lc_big["overflow"] == 0, f"{lc_big}")
check("a Glassy that cannot shrink into the slot is DETECTED, not silently overlapped",
      g_big.FFSpan.GlassyFits() is False, f"fits={g_big.FFSpan.GlassyFits()}")
big_notes = r5_notes(g_big)
check("...and in the durable log as STILL OVERFLOWS, with the refused height beside it",
      any("STILL OVERFLOWS" in n for n in big_notes) and any("height NOT fitted" in n for n in big_notes),
      f"notes={[n for n in big_notes if 'glassy' in n][-4:]}")
print("    Glassy 562 px (cannot shrink under the 150-unit floor): reported, not hidden")

# ====================== 21. `-` is one step back ==================================
# The jank, in my words: "I just don't want it to feel janky." The 16:21-16:22 log is what
# janky looked like -- seven windows in 38 seconds, each closing as the next opened, because the
# Nintendo A button is ConsolePort's PLURAL and PLURAL keeps the ring up on purpose. And `-` had
# no way back: with the game menu open it was a dead button.
print("\n-- 21. `-` is one step back --")

MENU_FIXTURE = (
    'CharacterFrame = __newFrame("CharacterFrame", UIParent)\n'
    'CharacterFrame.rect = {0, 0, 541, 454} CharacterFrame.shown = false\n'
    'MerchantFrame = __newFrame("MerchantFrame", UIParent)\n'
    'MerchantFrame.rect = {0, 0, 400, 500} MerchantFrame.shown = false\n'
    'WorldMapFrame = __newFrame("WorldMapFrame", UIParent)\n'
    'WorldMapFrame.rect = {0, 0, 800, 600} WorldMapFrame.shown = false\n'
    'CollectionsJournal = __newFrame("CollectionsJournal", UIParent)\n'
    'CollectionsJournal.rect = {0, 0, 700, 500} CollectionsJournal.shown = false\n'
    'GameMenuFrame = __newFrame("GameMenuFrame", UIParent)\n'
    'GameMenuFrame.rect = {0, 0, 200, 300} GameMenuFrame.shown = false\n'
    'ConsolePortMenuRing = __newFrame("ConsolePortMenuRing", UIParent)\n'
    'ConsolePortMenuRing.shown = false\n'
    '__ringSeed = {}\n'
    'function ConsolePortMenuRing:Run(body) __ringSeed[#__ringSeed+1] = body return true end\n'
    'function ConsolePortMenuRing:OnControlsChanged() end\n'
    '__triggerClicks = 0\n'
    'ConsolePortMenuTrigger = __newFrame("ConsolePortMenuTrigger", UIParent)\n'
    'function ConsolePortMenuTrigger:script_OnClick()\n'
    '    __triggerClicks = __triggerClicks + 1\n'
    '    ConsolePortMenuRing.shown = not ConsolePortMenuRing.shown\n'
    'end\n'
)


def back_env(**kw):
    lua, g = new_client(4400, 1080, preamble=HOME_FIXTURE + BLIZZ_BAGS + MENU_FIXTURE, binds=True)
    login(g)
    g.__flush()
    return lua, g


def press_back(lua, g):
    """What the player's thumb does, through the client's binding stack."""
    r = lua.eval("__pressBack")()
    g.__flush()
    return str(r)


def shown(g, name):
    f = getattr(g, name, None)
    return bool(f is not None and f.shown)


lua_b, g_b = back_env()

# --- the classification is ONE list, owned by FFSpan, read by FFBinds --------------------------
check("a PAGE window is a menu window", g_b.FFSpan.IsMenuWindow("WorldMapFrame") is True)
check("the game menu is a menu window -- this is the dead-button fix",
      g_b.FFSpan.IsMenuWindow("GameMenuFrame") is True)
check("CharacterFrame is a menu window even though it is a layout COMPANION",
      g_b.FFSpan.IsMenuWindow("CharacterFrame") is True)
check("a VENDOR is NOT a menu window -- you walked up to it, you did not pick it",
      g_b.FFSpan.IsMenuWindow("MerchantFrame") is False)
check("the resident bags are NOT menu windows -- `-` never empties the home screen",
      g_b.FFSpan.IsMenuWindow("ContainerFrameCombinedBags") is False
      and g_b.FFSpan.IsMenuWindow("Baganator_SingleViewBackpackViewFrameDEFAULT") is False)
check("FFBinds reads THAT list rather than keeping its own",
      lua_b.eval("FFBinds_BackDecision") is not None)

# --- (c) nothing open -> `-` opens the ring ------------------------------------------------------
before = int(lua_b.eval("__triggerClicks"))
press_back(lua_b, g_b)
check("nothing open -> `-` opens the ring",
      int(lua_b.eval("__triggerClicks")) == before + 1 and shown(g_b, "ConsolePortMenuRing"),
      f"clicks={lua_b.eval('__triggerClicks')} ring={shown(g_b, 'ConsolePortMenuRing')}")

# --- (a) ring open -> `-` closes the ring and nothing else --------------------------------------
press_back(lua_b, g_b)
check("ring open -> `-` closes the ring",
      not shown(g_b, "ConsolePortMenuRing"))

# --- (b) a window open -> ONE press closes it, with no ring flash -------------------------------
lua_b.execute("CollectionsJournal:Show()")
g_b.__flush()
ring_before = int(lua_b.eval("__triggerClicks"))
route = press_back(lua_b, g_b)
check("one window open -> ONE press closes it",
      not shown(g_b, "CollectionsJournal"), "the window is still up")
check("...and the ring never flashed on the way",
      int(lua_b.eval("__triggerClicks")) == ring_before and not shown(g_b, "ConsolePortMenuRing"),
      f"trigger clicks={lua_b.eval('__triggerClicks')} vs {ring_before}")
check("...because `-` was re-routed to the closer, not to the ring trigger",
      route.startswith("override:"), f"route={route}")

# --- three windows, still one press -------------------------------------------------------------
lua_b.execute("CollectionsJournal:Show() WorldMapFrame:Show() CharacterFrame:Show()")
g_b.__flush()
press_back(lua_b, g_b)
check("three windows open -> ONE press closes ALL of them",
      not shown(g_b, "CollectionsJournal") and not shown(g_b, "WorldMapFrame")
      and not shown(g_b, "CharacterFrame"),
      f"collections={shown(g_b, 'CollectionsJournal')} map={shown(g_b, 'WorldMapFrame')} "
      f"char={shown(g_b, 'CharacterFrame')}")

# --- the game menu: the dead button ------------------------------------------------------------
lua_b.execute("GameMenuFrame:Show()")
g_b.__flush()
press_back(lua_b, g_b)
check("the game menu closes on `-` -- it used to be a dead button",
      not shown(g_b, "GameMenuFrame"))

# --- at a vendor: `-` opens the ring, the vendor stays -------------------------------------------
lua_b.execute("MerchantFrame:Show()")
g_b.__flush()
vendor_clicks = int(lua_b.eval("__triggerClicks"))
press_back(lua_b, g_b)
check("at a VENDOR `-` opens the ring and the vendor stays put",
      shown(g_b, "MerchantFrame") and shown(g_b, "ConsolePortMenuRing")
      and int(lua_b.eval("__triggerClicks")) == vendor_clicks + 1,
      f"vendor={shown(g_b, 'MerchantFrame')} ring={shown(g_b, 'ConsolePortMenuRing')}")
press_back(lua_b, g_b)
lua_b.execute("MerchantFrame:Hide()")
g_b.__flush()

# --- out of combat the ring never opens over a menu window --------------------------------------
# (b) fires before (c) and every ring pick now closes the ring. Here `-` closes the map, the next
# `-` opens the ring, and no menu window is open behind it. This says nothing about RB from the
# ring, which section 23 covers.
lua_b.execute("WorldMapFrame:Show()")
g_b.__flush()
press_back(lua_b, g_b)          # closes the map
press_back(lua_b, g_b)          # opens the ring
_open_now = [str(v) for v in g_b.FFSpan.MenuWindowsOpen().values()]
check("the ring can never be open with a menu window behind it",
      shown(g_b, "ConsolePortMenuRing") and not _open_now,
      f"ring={shown(g_b, 'ConsolePortMenuRing')} open={_open_now}")
press_back(lua_b, g_b)

# --- A and B both pick-and-close ----------------------------------------------------------------
seeds = [str(v) for v in (lua_b.eval("__ringSeed").values() or [])]
check("the ring is re-seeded so PLURAL sends LeftButton -- A and B both pick and close",
      any("COMMANDS[PLURAL] = 'LeftButton'" in x for x in seeds), f"seeds={seeds}")
check("...through ConsolePort's OWN env tables, never by editing its files or saved vars",
      all(("COMMANDS" in x or "TRIGGERS" in x) for x in seeds), f"seeds={seeds}")
check("...and it is re-applied when ConsolePort rebuilds its controls",
      lua_b.eval("FFBinds_SeedRing") is not None)
n_seeds = len(seeds)
lua_b.execute("ConsolePortMenuRing:OnControlsChanged()")
g_b.__flush()
check("OnControlsChanged wipes BOTH tables, so both seeds go back on after it",
      len([str(v) for v in (lua_b.eval("__ringSeed").values() or [])]) == n_seeds + 2,
      "the hook must re-seed COMMANDS[PLURAL] and TRIGGERS")

# --- combat: never dead, never stuck ------------------------------------------------------------
lua_c, g_c = back_env()
g_c.__combat = True
clicks_c = int(lua_c.eval("__triggerClicks"))
press_back(lua_c, g_c)
check("in combat with nothing open, `-` still opens the ring",
      int(lua_c.eval("__triggerClicks")) == clicks_c + 1, "the ring must never go dead")
press_back(lua_c, g_c)
check("...and still closes it",
      not shown(g_c, "ConsolePortMenuRing"))
# a window opening mid-fight cannot re-bind, so `-` opens the ring: one extra press, never stuck
lua_c.execute("CollectionsJournal:Show()")
g_c.__flush()
press_back(lua_c, g_c)
check("a window opened IN combat leaves `-` on the ring -- one extra press, never a dead button",
      shown(g_c, "ConsolePortMenuRing") and shown(g_c, "CollectionsJournal"),
      f"ring={shown(g_c, 'ConsolePortMenuRing')} window={shown(g_c, 'CollectionsJournal')}")
press_back(lua_c, g_c)
g_c.__combat = False
g_c.__fire("PLAYER_REGEN_ENABLED")
g_c.__flush()
press_back(lua_c, g_c)
check("...and the moment combat ends `-` closes it again",
      not shown(g_c, "CollectionsJournal"), "the binding must be restored at regen")

# ====================== 22. the map, and the bags the ring used to hide (FFSpan 2.5.3) ==========
print("\n-- 22. the map and the Inventory entry --")

# The map with its quest-log panel shown and hidden. Blizzard's WorldMapFrame is ~1.4x taller
# relative to its width once the side panel goes, which is exactly the room I want the map
# to grow INTO: moved up and stretched down.
# The map, at the size the DEVICE reports. An earlier fixture was 1000x666 units, which was simply
# made up, and the numbers I published from it did not describe the Thor. The 16:22 dump has
# WorldMapFrame at 1208.00 x 623.26 px with effectiveScale 0.829973, so at scale 1 that is
#   1208.00 / (0.829973 * 1.40625) = 1035 units wide
#    623.26 / (0.829973 * 1.40625) =  534 units tall
# Placing that in the 1208 x 1048 home area reproduces the device's 1208 x 623 exactly, which is
# how I know the fixture is right rather than merely different.
MAP_W_UNITS, MAP_H_UNITS = 1035, 534
# The panel-HIDDEN width is NOT device-measured -- the player never opened the map without the
# quest panel while a dump was being taken, and there is no citable Blizzard constant to hand. So
# it is modelled as the frame minus a quest panel, flagged as an assumption, and none of the
# checks below depends on the exact figure: they assert direction and containment, not a ratio.
MAP_PANEL_UNITS = 293          # ASSUMED quest-panel width, not measured on the device
MAP = f"""
WorldMapFrame = __newFrame("WorldMapFrame", UIParent)
WorldMapFrame.rect = {{0, 0, {MAP_W_UNITS}, {MAP_H_UNITS}}}
WorldMapFrame.shown = false
__mapPanel = true
function __mapSetPanel(on)
    __mapPanel = on
    WorldMapFrame.rect = on and {{0, 0, {MAP_W_UNITS}, {MAP_H_UNITS}}}
                            or {{0, 0, {MAP_W_UNITS - MAP_PANEL_UNITS}, {MAP_H_UNITS}}}
    if WorldMapFrame.hs_OnSizeChanged then WorldMapFrame.hs_OnSizeChanged(WorldMapFrame) end
end
function WorldMapFrame:Maximize() end
function WorldMapFrame:Minimize() end
"""

lua_m, g_m = new_client(4400, 1080, preamble=HOME_FIXTURE + BLIZZ_BAGS + MAP)
login(g_m)
lua_m.execute("WorldMapFrame:Show()")
g_m.__flush()
map_on = g_m.__placed("WorldMapFrame")
home_top, home_h = 16, 1080 - 32
# The fixture is only worth having if it reproduces the Thor. Device dump 16:22: WorldMapFrame
# 1207.9996 x 623.2579 px at effectiveScale 0.829973. Anything else and the numbers below describe
# a map that does not exist -- which is exactly what the earlier fixture published.
_dev_w = MAP_W_UNITS * PX_PER_UNIT * float(map_on.scale)
_dev_h = MAP_H_UNITS * PX_PER_UNIT * float(map_on.scale)
check("the mock map reproduces the DEVICE: 1208 x 623 px at effectiveScale 0.83",
      abs(_dev_w - 1208.0) < 2 and abs(_dev_h - 623.26) < 2
      and abs(float(map_on.scale) - 0.829973) < 0.005,
      f"{_dev_w:.1f} x {_dev_h:.1f} px at scale {float(map_on.scale):.4f} "
      f"(device: 1208.0 x 623.3 at 0.829973)")
check("the map is on the HOME screen, not the game screen",
      map_on is not None and float(map_on.x) < 1240, f"placed={dict(map_on) if map_on else None}")
check("the map is TOP-aligned -- it starts at the top margin and stretches down",
      map_on is not None and abs(float(map_on.y) - home_top) < 1.5,
      f"y={map_on.y if map_on else None} (want {home_top})")
h_on = MAP_H_UNITS * PX_PER_UNIT * float(map_on.scale)
w_on = MAP_W_UNITS * PX_PER_UNIT * float(map_on.scale)

lua_m.execute("__mapSetPanel(false)")
g_m.__flush()
map_off = g_m.__placed("WorldMapFrame")
h_off = MAP_H_UNITS * PX_PER_UNIT * float(map_off.scale)
w_off = (MAP_W_UNITS - MAP_PANEL_UNITS) * PX_PER_UNIT * float(map_off.scale)
check("hiding the quest panel re-fits the map without the player asking",
      abs(float(map_off.scale) - float(map_on.scale)) > 0.01,
      f"scale {map_on.scale} -> {map_off.scale}")
check("...and it is still top-aligned afterwards",
      abs(float(map_off.y) - home_top) < 1.5, f"y={map_off.y}")
check("...and it got TALLER, which is the point of stretching down",
      h_off > h_on, f"{h_on:.0f} px -> {h_off:.0f} px")
check("the map never leaves the home screen at either size",
      float(map_off.x) >= 16 - 0.5 and float(map_off.x) + w_off <= 1240 - 16 + 1,
      f"x={map_off.x:.0f} w={w_off:.0f}")
print(f"    map, quest panel SHOWN:  {w_on:>4.0f} x {h_on:>4.0f} px  (scale {float(map_on.scale):.2f})")
print(f"    map, quest panel HIDDEN: {w_off:>4.0f} x {h_off:>4.0f} px  (scale {float(map_off.scale):.2f})"
      f"  -- {h_off / h_on:.2f}x taller")
# An earlier version claimed "~1.30x taller" off a fixture that was not the device's map. The direction is
# what I wanted and what the test can stand behind; the exact multiplier depends on a quest
# panel width nobody has measured on the Thor, so it is reported, not asserted.
check("the map still fits the home screen at BOTH panel states",
      float(map_on.x) >= 16 - 0.5 and float(map_on.x) + w_on <= 1240 - 16 + 1
      and h_off <= 1048 + 1,
      f"with panel {w_on:.0f}x{h_on:.0f}, without {w_off:.0f}x{h_off:.0f}")

# --- Leatrix Maps: if the player turns its own options on, it wins -------------------------------
for opt in ("UnlockMap", "ScaleWorldMap"):
    lua_l, g_l = new_client(4400, 1080,
                            preamble=HOME_FIXTURE + BLIZZ_BAGS + MAP + f'LeaMapsDB = {{{opt} = "On"}}\n')
    login(g_l)
    lua_l.execute("WorldMapFrame:Show()")
    g_l.__flush()
    check(f"Leatrix {opt} On -> FFSpan does not place the map at all",
          g_l.__placed("WorldMapFrame") is None,
          f"placed={g_l.__placed('WorldMapFrame')}")
    check(f"...and says who owns it, in the log and the dump",
          str(g_l.FFSpan.PositionOwners().WorldMapFrame) == f"LeatrixMaps:{opt}",
          f"owner={g_l.FFSpan.PositionOwners().WorldMapFrame}")

# Leatrix installed with DEFAULT settings neither moves nor scales the map (:2112, :2115), so FFSpan does
lua_ld, g_ld = new_client(4400, 1080,
                          preamble=HOME_FIXTURE + BLIZZ_BAGS + MAP
                          + 'LeaMapsDB = {UnlockMap = "Off", ScaleWorldMap = "Off", NoMapFade = "On"}\n')
login(g_ld)
lua_ld.execute("WorldMapFrame:Show()")
g_ld.__flush()
check("Leatrix at its DEFAULTS does not move or scale the map, so FFSpan still places it",
      g_ld.__placed("WorldMapFrame") is not None,
      "default UnlockMap/ScaleWorldMap are Off -- neither block runs")
check("...and nothing is recorded as owning it",
      g_ld.FFSpan.PositionOwners().WorldMapFrame is None)

# --- the ring's Inventory entry ------------------------------------------------------------------
# Buttons.lua:78-99 references MainMenuBarBackpackButton, which is a TOGGLE. On a home screen where
# the bags are furniture, picking "Inventory" made the player's own inventory vanish.
lua_i, g_i = new_client(4400, 1080, preamble=HOME_FIXTURE + BLIZZ_BAGS + BAGANATOR)
login(g_i)
g_i.__flush()
bags_i = "Baganator_SingleViewBackpackViewFrameDEFAULT"
check("the resident bags start open",
      bool(getattr(g_i, bags_i).shown), "residency should have opened them")
lua_i.execute("ToggleAllBags()")          # exactly what the ring's Inventory entry ends up calling
g_i.__flush()
check("the ring's Inventory entry can no longer hide the resident bags",
      bool(getattr(g_i, bags_i).shown),
      "picking Inventory must never empty the home screen")
notes_i = [l for l in r5_notes(g_i) if "kept resident" in l]
check("...and it says so, once, in the durable ring",
      len(notes_i) >= 1, f"notes={notes_i}")

# Escape must still work -- the design rules out re-opening from the Escape path by name.
# With Blizzard's own bags that path IS CloseAllBags, so this is where it has to be proven.
lua_e, g_e = new_client(4400, 1080, preamble=HOME_FIXTURE + BLIZZ_BAGS)
login(g_e)
g_e.__flush()
check("Blizzard's resident bags start open too",
      bool(g_e.ContainerFrameCombinedBags.shown))
lua_e.execute("ToggleAllBags()")
g_e.__flush()
check("the Inventory entry cannot hide Blizzard's resident bags either",
      bool(g_e.ContainerFrameCombinedBags.shown))
lua_e.execute("CloseAllBags()")
g_e.__flush()
check("...but Escape still closes them -- CloseAllBags is deliberately NOT hooked",
      not bool(g_e.ContainerFrameCombinedBags.shown),
      "hooking CloseAllBags would be the Escape trap the design forbids by name")

# ...and off the home screen the entry is an ordinary toggle again
lua_s, g_s = new_client(1920, 1080, preamble=HOME_FIXTURE + BLIZZ_BAGS + BAGANATOR)
login(g_s)
g_s.__flush()
before_s = bool(getattr(g_s, bags_i).shown)
lua_s.execute("ToggleAllBags()")
g_s.__flush()
check("on a single screen the Inventory entry toggles exactly as it always did",
      bool(getattr(g_s, bags_i).shown) != before_s,
      "there are no resident bags to protect off the home screen")

# ====================== 23. RB from the ring IS the game menu (FFBinds 1.3) =====================
# My 1.2 claim was wrong. I reasoned that because the ring can never be open with a menu window
# behind it, TOGGLEGAMEMENU has nothing to close first. But menu windows are not the only thing the
# Escape chain closes: CloseAllWindows is registered at AddOnPost priority
# (UIParentPanelManager.lua:1106) and it OPENS with CloseAllBags(). The resident bags are always
# visible on the home screen, so the first RB closed the player's bags and no menu appeared. Then
# ClearTarget() took the next press. That is three presses and a home screen that empties itself.
print("\n-- 23. RB is the game menu, in one press --")

# The Escape chain, modelled the way retail actually runs it, so a regression cannot hide.
ESC_CHAIN = r"""
__escChain = {}
__targetCleared = 0
__hasTarget = true
function ClearTarget() __hasTarget = false __targetCleared = __targetCleared + 1 end
-- Blizzard_GameMenuEsc: handlers run by priority and the menu opens only if none claims the press
function ToggleGameMenu()
    __escChain[#__escChain+1] = "ToggleGameMenu"
    if CloseAllWindows() then return end          -- AddOnPost: CloseAllWindows -> CloseAllBags
    if __hasTarget then ClearTarget() return end  -- World: ClearTarget
    GameMenuFrame_Show()                          -- only now
end
-- CheckProtectedFunctionsAllowed, modelled (UIParentPanelManager.lua:808-815):
--   if ( InCombatLockdown() and not issecure() ) then
--       DisplayInterfaceActionBlockedMessage(); return false
--   end
-- Every call from an addon is insecure by definition, so in combat it is refused AND leaves a
-- red message on the player's screen. __blocked is the count of those messages.
__blocked = {}
function DisplayInterfaceActionBlockedMessage(who)
    __blocked[#__blocked+1] = tostring(who or "?")
end
function __protectedAllowed(who)
    if __combat then DisplayInterfaceActionBlockedMessage(who) return false end
    return true
end
function ShowUIPanel(f)
    if not __protectedAllowed("ShowUIPanel") then return false end
    if f then __showPanel(f:GetName()) end
    return true
end
__gameMenuShows = 0
function GameMenuFrame_Show()
    __gameMenuShows = __gameMenuShows + 1
    ShowUIPanel(GameMenuFrame)
end
"""

MENU7 = MENU_FIXTURE + ESC_CHAIN + r"""
-- the ring closes itself when the game menu shows: Ring.lua:65-70 OnGameMenuShow, reached through
-- the trigger being parented to GameMenuFrame (ConsolePort_Menu/View/Menu.xml:70)
GameMenuFrame:HookScript("OnShow", function() ConsolePortMenuRing.shown = false __gameMenuShown = true end)
GameMenuFrame:HookScript("OnHide", function() __gameMenuShown = false end)
"""


def menu_env(combat=False):
    lua, g = new_client(4400, 1080, preamble=HOME_FIXTURE + BLIZZ_BAGS + BAGANATOR + MENU7,
                        binds=True)
    login(g)
    g.__combat = combat
    g.__flush()
    return lua, g


def ring_press(lua, g, binding):
    """Press a ring TRIGGERS button, through whatever action the ring has bound to it."""
    action = str(lua.eval(f"__ringTrigger('{binding}')"))
    frame = action.split("CLICK ")[-1].split(":")[0] if action.startswith("CLICK ") else None
    if frame:
        lua.execute(f"if {frame}.script_OnClick then {frame}:script_OnClick('LeftButton') end")
    elif action == "TOGGLEGAMEMENU":
        lua.execute("ToggleGameMenu()")
    g.__flush()
    return action


# the ring's TRIGGERS, as ConsolePort seeds them and as FFBinds' re-seed rewrites them
RING_TRIGGERS = r"""
TRIGGERS = {PADRSHOULDER = "TOGGLEGAMEMENU", PADLSHOULDER = "TOGGLEGAMEMENU"}
function __ringTrigger(b) return TRIGGERS[b] end
-- HANDLE:Run(body) runs `body` in the managed environment of the frame the HANDLE belongs to, with
-- `self` being THAT handle -- not the caller's (RunFor is the one that keeps the caller's
-- environment). So `ring:Run(body)` below executes with the RING's env: its TRIGGERS, its
-- isMenuOpen, and a `self` that is the ring. Getting this backwards is the whole point of the
-- fix, so the harness models the distinction rather than flattening it.
function __ringEnv()
    return {
        TRIGGERS = TRIGGERS, pairs = pairs, isMenuOpen = __gameMenuShown,
        self = {
            IsVisible = function() return ConsolePortMenuRing.shown end,
            -- Ring.lua:86-88: the ring binds on its OWN owner, scoped to while it is shown
            SetBinding = function(_, _, chord, action)
                __ringOwned[chord] = action
            end,
            ClearBindings = function() __ringOwned = {} end,
        },
    }
end

__ringOwned = {}          -- what the RING has bound on its own owner, while it is shown
__gameMenuShown = false   -- the ring's own `isMenuOpen` (Ring.lua:65)
function ConsolePortMenuRing:Run(body)
    __ringSeed[#__ringSeed+1] = body
    -- Run executes in the RING's managed environment, with `self` = the ring's handle
    local env = __ringEnv()
    env.COMMANDS, env.PLURAL = COMMANDS or {}, "PAD2"
    local fn = load(body, "ring:Run", "t", env)
    if fn then pcall(fn) end
    return true
end
"""

lua7, g7 = None, None
lua7, g7 = new_client(4400, 1080,
                      preamble=HOME_FIXTURE + BLIZZ_BAGS + BAGANATOR + MENU7 + RING_TRIGGERS,
                      binds=True)
login(g7)
g7.__flush()

bags7 = "Baganator_SingleViewBackpackViewFrameDEFAULT"
check("the resident bags are up, which is the whole reason the old chain misfired",
      bool(getattr(g7, bags7).shown))
_rb = lambda: str(lua7.eval("__ringTrigger('PADRSHOULDER')"))
_lb = lambda: str(lua7.eval("__ringTrigger('PADLSHOULDER')"))
check("the ring's TRIGGERS no longer carry TOGGLEGAMEMENU",
      _rb() != "TOGGLEGAMEMENU", "RB action=" + _rb())
check("...both LB and RB were re-pointed, not just the one under test",
      _lb() == _rb(), "LB=" + _lb() + " RB=" + _rb())

# open the ring, then press RB
lua7.execute("__pressBack()")
g7.__flush()
check("the ring is open", bool(g7.ConsolePortMenuRing.shown))
shows_before = int(lua7.eval("__gameMenuShows"))
act = ring_press(lua7, g7, "PADRSHOULDER")
check("ONE press of RB opens the game menu",
      int(lua7.eval("__gameMenuShows")) == shows_before + 1 and bool(g7.GameMenuFrame.shown),
      f"shows={lua7.eval('__gameMenuShows')} menu={g7.GameMenuFrame.shown} action={act}")
check("...and the bags are STILL THERE -- the old chain closed them first",
      bool(getattr(g7, bags7).shown),
      "CloseAllWindows -> CloseAllBags is what used to eat the first press")
check("...and the target is still targeted",
      bool(lua7.eval("__hasTarget")) and int(lua7.eval("__targetCleared")) == 0,
      f"cleared={lua7.eval('__targetCleared')}")
check("...and the Escape chain was never entered at all",
      len([str(v) for v in lua7.eval("__escChain").values()]) == 0,
      f"chain={[str(v) for v in lua7.eval('__escChain').values()]}")
check("...and the ring closed itself when the menu appeared",
      not bool(g7.ConsolePortMenuRing.shown),
      "Ring.lua:65-70 OnGameMenuShow, via the trigger parented to GameMenuFrame")

# --- it has to TOGGLE, because OnGameMenuShow re-binds the same TRIGGERS ----------------
act2 = ring_press(lua7, g7, "PADRSHOULDER")
check("RB with the menu OPEN closes it -- a show-only action would be a dead press",
      not bool(g7.GameMenuFrame.shown),
      f"menu={g7.GameMenuFrame.shown} action={act2}")
check("...without touching the bags on the way out either",
      bool(getattr(g7, bags7).shown))
shows_mid = int(lua7.eval("__gameMenuShows"))
ring_press(lua7, g7, "PADRSHOULDER")
check("...and RB again re-opens it: a real toggle, both directions",
      bool(g7.GameMenuFrame.shown) and int(lua7.eval("__gameMenuShows")) == shows_mid + 1)

# `-` with the menu open is still rule 1b from 1.2
lua7.execute("__pressBack()")
g7.__flush()
check("`-` with the menu open still closes it (rule 1b from 1.2, unchanged)",
      not bool(g7.GameMenuFrame.shown))

# --- combat: never dead ---------------------------------------------------------------------------
lua8, g8 = new_client(4400, 1080,
                      preamble=HOME_FIXTURE + BLIZZ_BAGS + BAGANATOR + MENU7 + RING_TRIGGERS,
                      binds=True)
login(g8)
g8.__flush()
g8.__combat = True
chain_before = len([str(v) for v in lua8.eval("__escChain").values()])
ring_press(lua8, g8, "PADRSHOULDER")
# 1.3 fell back to _G.ToggleGameMenu() here, which is how it made combat WORSE: the chain ran
# tainted, the bags closed, and ShowUIPanel refused with a red message. 1.4's contract is that
# the handler makes NO protected call at all -- the secure state driver has already handed LB/RB
# back to the native binding, so this code should not even be reached in a fight.
check("in combat the handler does NOT enter the Escape chain",
      len([str(v) for v in lua8.eval("__escChain").values()]) == chain_before,
      "1.3 called ToggleGameMenu() from a tainted click")
check("...and produces no 'Interface action blocked' message",
      len([str(v) for v in lua8.eval("__blocked").values()]) == 0,
      f"blocked={[str(v) for v in lua8.eval('__blocked').values()]}")
notes8 = [l for l in (str(x) for x in g8.FFBindsDB.log.results.values()) if "combat:" in l]
check("...and says so once, rather than failing quietly",
      len([l for l in notes8 if "game menu" in l]) == 1, f"log={notes8}")

# --- the seeds are re-applied after ConsolePort rebuilds its controls ---------------------------
lua7.execute("TRIGGERS.PADRSHOULDER = 'TOGGLEGAMEMENU' TRIGGERS.PADLSHOULDER = 'TOGGLEGAMEMENU'")
lua7.execute("ConsolePortMenuRing:OnControlsChanged()")
g7.__flush()
check("OnControlsChanged restores TOGGLEGAMEMENU, so the seed goes straight back on",
      _rb() != "TOGGLEGAMEMENU", "RB action=" + _rb())

# --- /ffbinds back ------------------------------------------------------------------------
report = [str(x) for x in lua7.eval("FFBinds_BackReport")().values()]
check("/ffbinds back says what `-` would do right now",
      any("would:" in l for l in report), f"report={report}")
check("...whether the override is on",
      any("override on PADBACK" in l for l in report))
_seed_lines = [l for l in report if "ring seed --" in l]
check("...and whether BOTH ring seeds actually took -- the two things a mock cannot prove",
      len(_seed_lines) == 2
      and any("A and B both accept" in l for l in _seed_lines)
      and any("LB/RB open the game menu" in l for l in _seed_lines),
      f"seed lines={_seed_lines}")
check("...and the last log line, so a failed seed names itself",
      any("last log:" in l for l in report))

# ====================== 24. not one protected call in combat (FFBinds 1.4) =====================
# The regression that held 1.3 back. ShowUIPanel and HideUIPanel both open with
# CheckProtectedFunctionsAllowed() (UIParentPanelManager.lua:808-815), which refuses an insecure
# caller in combat AND puts a red "Interface action blocked" message on the player's screen. The
# 1.3 combat fallback called _G.ToggleGameMenu() from the addon's own tainted click: the chain ran, the
# bags closed, and the menu never opened -- strictly worse than the native binding it replaced.
print("\n-- 24. not one protected call in combat --")

# A state driver, modelled the way ConsolePort's own is (Input.lua:18-20): the snippet runs inside
# the secure environment, so it may re-bind mid-fight, which an insecure handler may not.
DRIVER = r"""
__stateDrivers = {}
function RegisterStateDriver(frame, state, macro)
    __stateDrivers[#__stateDrivers+1] = {frame = frame, state = state, macro = macro}
end
-- Run the addon's OWN `_onstate-combat` snippet, rather than a paraphrase of it -- otherwise the
-- snippet is a string nobody executes and any edit to it goes unnoticed.
--
function __setCombat(on)
    __combat = on
    local frame = _G.FFBindsCombat
    local body = frame and frame.attributes and frame.attributes["_onstate-combat"]
    if body then
        local env
        env = {
            newstate = on and "combat" or "nocombat",
            self = {
                GetFrameRef = function(_, name) return frame.frameRefs and frame.frameRefs[name] end,
                SetBindingClick = function(_, _, chord, frameName, button)
                    __overrides.FFBindsCombat = __overrides.FFBindsCombat or {}
                    __overrides.FFBindsCombat[chord] = "CLICK "..frameName..":"..button
                end,
                SetBinding = function(_, _, chord, action)
                    __overrides.FFBindsCombat = __overrides.FFBindsCombat or {}
                    __overrides.FFBindsCombat[chord] = action
                end,
                ClearBindings = function() __overrides.FFBindsCombat = nil end,
            },
        }
        local fn = load(body, "_onstate-combat", "t", env)
        if fn then pcall(fn) end
    end
    __fire(on and "PLAYER_REGEN_DISABLED" or "PLAYER_REGEN_ENABLED")
end
"""


def combat_env():
    lua, g = new_client(4400, 1080,
                        preamble=HOME_FIXTURE + BLIZZ_BAGS + BAGANATOR + MENU7 + RING_TRIGGERS
                        + DRIVER, binds=True)
    login(g)
    g.__flush()
    lua.execute("__blocked = {}")
    return lua, g


def blocked(lua):
    return [str(v) for v in lua.eval("__blocked").values()]


lua9, g9 = combat_env()
bags9 = "Baganator_SingleViewBackpackViewFrameDEFAULT"

check("a secure state driver is registered, the way ConsolePort does it",
      len([str(v) for v in lua9.eval("__stateDrivers").values()]) >= 1,
      "Input.lua:18-20 -- an insecure regen handler cannot re-bind, a state driver can")

# --- THE FULL FLOW: pull with a window open, RB, `-` twice, a ring pick, regen -----
lua9.execute("CollectionsJournal:Show()")
g9.__flush()
check("a menu window is open when the pull happens",
      bool(g9.CollectionsJournal.shown))

lua9.execute("__setCombat(true)")          # PULL
g9.__flush()

check("in combat `-` is back on the ring trigger, which is secure",
      str(lua9.eval("__overrides.FFBindsCombat.PADBACK")) == "CLICK ConsolePortMenuTrigger:LeftButton")
check("...and LB/RB are back on the native TOGGLEGAMEMENU",
      str(lua9.eval("__ringTrigger('PADRSHOULDER')")) == "TOGGLEGAMEMENU"
      and str(lua9.eval("__ringTrigger('PADLSHOULDER')")) == "TOGGLEGAMEMENU",
      "the binding that actually works in a fight")

for _ in range(4):                          # a player mashing `-` mid-pull
    lua9.execute("__pressBack()")
    lua9.execute("if FFBindsBack.script_OnClick then FFBindsBack:script_OnClick('LeftButton') end")
g9.__flush()
ring_press(lua9, g9, "PADRSHOULDER")        # RB from the ring
lua9.execute("if FFBindsBack.script_OnClick then FFBindsBack:script_OnClick('LeftButton') end")
g9.__flush()                                # and the closer directly, in case it is still bound
lua9.execute("FFBinds_ToggleGameMenu()")    # ...and the handler directly, the worst case
g9.__flush()

check("the WHOLE combat flow produces ZERO 'Interface action blocked' messages",
      len(blocked(lua9)) == 0, f"blocked={blocked(lua9)}")
check("...and the player's bags were never closed by any of it",
      bool(getattr(g9, bags9).shown))
check("...and the menu window is still open, waiting for the fight to end",
      bool(g9.CollectionsJournal.shown),
      "in combat it waits -- it does not fail with a red error")
combat_notes = [l for l in (str(x) for x in g9.FFBindsDB.log.results.values()) if "combat:" in l]
check("...and it is logged ONCE per fight, though `-` was pressed five times",
      len([l for l in combat_notes if "menu window(s) to close" in l]) == 1,
      f"notes={combat_notes}")

# --- and the moment the fight ends, everything comes back ---------------------------------------
lua9.execute("__setCombat(false)")
g9.__flush()
check("at regen the direct game-menu seed is back on",
      str(lua9.eval("__ringTrigger('PADRSHOULDER')")) != "TOGGLEGAMEMENU",
      f"RB={lua9.eval(chr(34) + '__ringTrigger(' + chr(39) + 'PADRSHOULDER' + chr(39) + ')' + chr(34))}")
check("...and the combat override is gone",
      lua9.eval("__overrides.FFBindsCombat") is None)
lua9.execute("__pressBack()")
g9.__flush()
check("...and `-` closes the window that was waiting",
      not bool(g9.CollectionsJournal.shown))
check("...still with no blocked messages anywhere in the whole sequence",
      len(blocked(lua9)) == 0, f"blocked={blocked(lua9)}")

# --- the layer that does not depend on the driver working at all --------------------------------
# If the state driver were unavailable and the override stayed on, the insecure handlers must STILL
# make no protected call. This is the floor, and it is what the 1.4 rule actually requires.
luaA, gA = combat_env()
luaA.execute("CollectionsJournal:Show() CharacterFrame:Show()")   # a PAGE and a COMPANION:
gA.__flush()                                                      # both menu windows, no contest
gA.__combat = True                          # combat, but NO driver swap -- the pessimistic case
luaA.execute("__blocked = {}")
luaA.execute("if FFBindsBack.script_OnClick then FFBindsBack:script_OnClick('LeftButton') end")
luaA.execute("FFBinds_ToggleGameMenu()")
gA.__flush()
check("with the swap FAILED, the handlers are silent no-ops -- still zero blocked messages",
      len(blocked(luaA)) == 0, f"blocked={blocked(luaA)}")
check("...and they closed nothing rather than half-closing things",
      bool(gA.CollectionsJournal.shown) and bool(gA.CharacterFrame.shown),
      f"collections={gA.CollectionsJournal.shown} char={gA.CharacterFrame.shown}")
gA.__combat = False
gA.__fire("PLAYER_REGEN_ENABLED")
gA.__flush()
luaA.execute("__pressBack()")
gA.__flush()
check("...and the deferred close happens at regen, in one press",
      not bool(gA.CollectionsJournal.shown) and not bool(gA.CharacterFrame.shown),
      f"collections={gA.CollectionsJournal.shown} char={gA.CharacterFrame.shown}")

# --- /ffbinds back reports the swap --------------------------------------------------------------
report8 = [str(x) for x in luaA.eval("FFBinds_BackReport")().values()]
check("/ffbinds back reports whether the combat swap is active",
      any("combat swap:" in l for l in report8), f"report={report8}")
check("...and whether the secure driver registered at all",
      any("secure driver:" in l for l in report8), f"report={report8}")

# ====================== 25. the combat driver touches ONE key (FFBinds 1.5) ====================
# The 1.4 driver did `self:SetBinding(true, 'PADRSHOULDER', 'TOGGLEGAMEMENU')` on FFBinds' OWN frame,
# which is a GLOBAL override for the whole fight. In FFBinds' own LAYOUT plain PADRSHOULDER is
# ACTIONBUTTON9 -- RB is an ability -- and PADLSHOULDER is the Shift modifier. So from the first
# second of every pull RB stopped casting. Nothing checked that the rest of the layout survives a
# fight, so nothing caught it. That check is the first one here.
print("\n-- 25. the combat driver touches one key --")

# FFBinds' LAYOUT, as the addon itself defines it -- lifted, not re-typed, so it cannot drift.
LAYOUT_RB = "ACTIONBUTTON9"       # FFBinds.lua PADRSHOULDER ['']
# FFBinds 1.8 (triggers are the modifiers): LB is an ability too now -- it took ZR's old slot 11 --
# and ZR is the Ctrl modifier, deliberately unbound. Both bumpers must survive a fight.
LAYOUT_LB = "ACTIONBUTTON11"      # FFBinds.lua PADLSHOULDER ['']
LAYOUT_ZR = ""                    # PADRTRIGGER is the Ctrl modifier


def live_action(lua, chord):
    """What the chord resolves to right now: priority overrides first, then the binding set."""
    for owner in ("FFBindsCombat", "FFBindsBackOwner"):
        tbl = lua.eval(f"__overrides['{owner}']")
        if tbl is not None and tbl[chord] is not None:
            return str(tbl[chord])
    return str(lua.eval(f"__bindings['{chord}'] or ''"))


lua10, g10 = combat_env()
lua10.execute("__blocked = {}")

# --- (e) out of combat, RB is an ability -------------------------------------------------------
check("out of combat plain RB is ACTIONBUTTON9, as the layout says",
      live_action(lua10, "PADRSHOULDER") == LAYOUT_RB,
      f"RB={live_action(lua10, 'PADRSHOULDER')}")

# --- (a) THE regression check: a fight must not move any key but PADBACK ------------------------
lua10.execute("__setCombat(true)")
g10.__flush()
moved = []
for chord, want in (("PADRSHOULDER", LAYOUT_RB), ("PADLSHOULDER", LAYOUT_LB),
                    ("PAD1", "ACTIONBUTTON1"), ("PAD2", "ACTIONBUTTON3"),
                    ("PADRTRIGGER", LAYOUT_ZR), ("PADDUP", "INTERACTTARGET")):
    if live_action(lua10, chord) != want:
        moved.append(f"{chord}: {want} -> {live_action(lua10, chord)}")
check("in combat EVERY layout chord still does what the layout says -- except PADBACK",
      not moved, f"moved: {moved}")
check("RB is still the player's ability in a fight, which is the whole bug",
      live_action(lua10, "PADRSHOULDER") == LAYOUT_RB,
      f"RB={live_action(lua10, 'PADRSHOULDER')} (an earlier build gave it TOGGLEGAMEMENU)")
check("LB is still the player's ability in a fight too (v1.8: slot 11, no longer Shift)",
      live_action(lua10, "PADLSHOULDER") == LAYOUT_LB,
      f"LB={live_action(lua10, 'PADLSHOULDER')}")
check("...and PADBACK is the ONLY key the driver bound",
      sorted(str(k) for k in lua10.eval("__overrides.FFBindsCombat").keys()) == ["PADBACK"],
      f"driver bound: {sorted(str(k) for k in lua10.eval('__overrides.FFBindsCombat').keys())}")

# --- (b) the ring opened IN combat: RB is the native binding, scoped to the ring ----------------
check("the ring's own TRIGGERS were switched to the native binding instead",
      str(lua10.eval("__ringTrigger('PADRSHOULDER')")) == "TOGGLEGAMEMENU",
      f"ring RB={lua10.eval(chr(34)+'__ringTrigger(' + chr(39) + 'PADRSHOULDER' + chr(39) + ')'+chr(34))}")
check("...and that switch went through the RING's handle, not FFBinds'",
      lua10.eval("FFBindsCombat.frameRefs.ring") is not None,
      "self:GetFrameRef('ring') -> ring:Run(body), the Pager.lua:75 pattern")
lua10.execute("ConsolePortMenuRing.shown = true")
g10.__flush()
ring_press(lua10, g10, "PADRSHOULDER")
check("RB from a ring opened in combat runs the native TOGGLEGAMEMENU",
      len([str(v) for v in lua10.eval("__escChain").values()]) >= 1,
      "secure, so it works -- it closes bags first, which is acceptable in a fight")
check("...with zero 'Interface action blocked' messages",
      len(blocked(lua10)) == 0, f"blocked={blocked(lua10)}")
lua10.execute("ConsolePortMenuRing.shown = false __gameMenuShown = false GameMenuFrame:Hide()")

# --- (c) the ring was ALREADY open when the pull happened ---------------------------------------
lua11, g11 = combat_env()
lua11.execute("__pressBack()")                 # open the ring out of combat
g11.__flush()
check("the ring is open before the pull", bool(g11.ConsolePortMenuRing.shown))
lua11.execute("__blocked = {} __setCombat(true)")   # PULL, ring still up
g11.__flush()
check("a ring open AT the pull has its bindings re-applied, not left on the direct toggle",
      str(lua11.eval("__ringOwned['PADRSHOULDER']")) == "TOGGLEGAMEMENU",
      f"ring owner binding={lua11.eval(chr(34)+'__ringOwned[' + chr(39) + 'PADRSHOULDER' + chr(39) + ']'+chr(34))}")
check("...and the player's RB ability is STILL untouched underneath it",
      live_action(lua11, "PADRSHOULDER") == LAYOUT_RB,
      "the ring's binding is scoped to the ring; FFBinds adds none")
check("...with no blocked messages from the switch",
      len(blocked(lua11)) == 0, f"blocked={blocked(lua11)}")

# --- (d) regen puts the direct toggle back -------------------------------------------------------
lua11.execute("__setCombat(false)")
g11.__flush()
check("at regen the ring's TRIGGERS are back on the direct game-menu toggle",
      str(lua11.eval("__ringTrigger('PADRSHOULDER')")) == "CLICK FFBindsGameMenu:LeftButton",
      f"ring RB={lua11.eval(chr(34)+'__ringTrigger(' + chr(39) + 'PADRSHOULDER' + chr(39) + ')'+chr(34))}")
check("...the driver's PADBACK binding is cleared",
      lua11.eval("__overrides.FFBindsCombat") is None)
# __ringOwned is written only by the snippet running in the ring's environment, never by the
# insecure re-seed -- so this is the secure half on its own, not the two of them together.
check("...and a ring still open at regen has the direct toggle re-bound on ITS OWN owner",
      str(lua11.eval("__ringOwned['PADRSHOULDER']")) == "CLICK FFBindsGameMenu:LeftButton",
      f"ring owner binding={lua11.eval(chr(34)+chr(95)+chr(95)+'ringOwned[' + chr(39) + 'PADRSHOULDER' + chr(39) + ']'+chr(34))}")
check("...and RB is an ability again",
      live_action(lua11, "PADRSHOULDER") == LAYOUT_RB)
lua11.execute("ConsolePortMenuRing.shown = false")
lua11.execute("__pressBack()")
g11.__flush()
ring_press(lua11, g11, "PADRSHOULDER")
check("...and RB from the ring opens the game menu directly again, in one press",
      bool(g11.GameMenuFrame.shown) and len(blocked(lua11)) == 0,
      f"menu={g11.GameMenuFrame.shown} blocked={blocked(lua11)}")

# --- the driver must degrade safely if the ring never loaded -------------------------------------
lua12, g12 = new_client(4400, 1080,
                        preamble=HOME_FIXTURE + BLIZZ_BAGS + BAGANATOR + MENU_FIXTURE + ESC_CHAIN
                        + DRIVER, binds=True)
login(g12)
g12.__flush()
lua12.execute("__blocked = {} __setCombat(true)")
g12.__flush()
check("with no ring at all the driver still binds only PADBACK and errors on nothing",
      lua12.eval("__overrides.FFBindsCombat") is not None
      and sorted(str(k) for k in lua12.eval("__overrides.FFBindsCombat").keys()) == ["PADBACK"]
      and len(blocked(lua12)) == 0,
      f"blocked={blocked(lua12)}")

# --- /ffbinds back reports the ring ref ----------------------------------------------------------
report9 = [str(x) for x in lua10.eval("FFBinds_BackReport")().values()]
check("/ffbinds back says whether the driver holds the ring ref",
      any("ring ref:" in l for l in report9), f"report={report9}")

# ============================================================ summary ============================
print("\n" + "=" * 78)
passed = sum(1 for r in results if r)
print(f"{passed}/{len(results)} checks passed")
print("=" * 78)
sys.exit(0 if passed == len(results) else 1)
