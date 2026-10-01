#!/usr/bin/env python3
"""
Mocked-WoW-API tests for FFSpan_Micro.lua: hands the micro buttons ConsolePort_Bar's toolbar took
back to Blizzard's MicroMenu while the home screen is on, and gives them back to ConsolePort on
release. Same lupa approach as the other FFSpan suites: a hand-written mock of the small slice of
the WoW API and of ConsolePort's toolbar popout this file touches, the real addon source loaded
and run unmodified through it, PASS/FAIL checks collected into `results`.

The popout mock is written from ConsolePort_Bar's documented BEHAVIOUR (View/Toolbar/Toolbar.lua):
every path that takes the buttons checks `self.props.micromenu` first; SetProps stores the table
it is given and re-takes the buttons; takes set IgnoreParentAlpha(true). No ConsolePort code is
copied here.
Run: python test_ffspan_micro.py
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

MOCK = r"""
__layouts = 0
__hooks = {}

local Frame = {}
Frame.__index = Frame
function __frame(name, parent, w, h)
    local f = setmetatable({ name = name, parent = parent, w = w or 1, h = h or 1, shown = true,
                             ignoreParentAlpha = false, points = {} }, Frame)
    if name then _G[name] = f end
    return f
end
function Frame:GetParent() return self.parent end
function Frame:SetParent(p) self.parent = p end
function Frame:SetIgnoreParentAlpha(v) self.ignoreParentAlpha = v end
function Frame:ClearAllPoints() self.points = {} end
function Frame:SetPoint(...) self.points[#self.points + 1] = { ... } end
function Frame:GetPoint(i) local p = self.points[i or 1]; if p then return unpack(p) end end
function Frame:GetWidth() return self.w end
function Frame:GetHeight() return self.h end
function Frame:IsShown() return self.shown end
function Frame:GetChildren()
    local out = {}
    for _, b in ipairs(__buttons) do if b.parent == self then out[#out + 1] = b end end
    for _, b in ipairs(__cpOwn or {}) do if b.parent == self then out[#out + 1] = b end end
    return unpack(out)
end

function hooksecurefunc(t, key, fn)
    local orig = t[key]
    t[key] = function(...)
        local a, b, c = orig(...)
        fn(...)
        return a, b, c
    end
end

function __setup(opts)
    opts = opts or {}
    __layouts = 0
    MicroMenuContainer = __frame('MicroMenuContainer', nil, 1, 1)
    MicroMenu = __frame('MicroMenu', MicroMenuContainer, 1, 1)
    QueueStatusButton = __frame('QueueStatusButton', MicroMenuContainer, 45, 45)
    QueueStatusButton:SetPoint('BOTTOMLEFT', MicroMenu, 'BOTTOMRIGHT', 15, 0)
    __buttons = {}
    local names = { 'CharacterMicroButton', 'ProfessionMicroButton', 'CollectionsMicroButton',
                    'MainMenuMicroButton' }
    for i, n in ipairs(names) do
        local b = __frame(n, MicroMenu, 32, 40)
        b.layoutIndex = i
        __buttons[#__buttons + 1] = b
    end
    -- a button a game rule kept out: Blizzard lists it but never AddButton'ed it (no layoutIndex)
    __ruledOut = __frame('StoreMicroButton', MicroMenu, 32, 40)
    if not opts.noGenerate then
        function MicroMenu:GenerateButtonInfos()
            local infos = {}
            for _, b in ipairs(__buttons) do infos[#infos + 1] = { button = b } end
            infos[#infos + 1] = { button = __ruledOut, gameRule = 1 }
            return infos
        end
    end
    -- Blizzard's container: lays the shown buttons in a row (-5 padding) and sizes around them
    function MicroMenu:Layout()
        local n = 0
        for _, b in ipairs(__buttons) do if b.parent == self and b.shown then n = n + 1 end end
        self.w = n > 0 and (n * 32 - (n - 1) * 5) or 1
        self.h = n > 0 and 40 or 1
    end
    function MicroMenuContainer:Layout()
        __layouts = __layouts + 1
        MicroMenu:Layout()
    end

    if opts.noToolbar then ConsolePortToolbar = nil; return end
    local layoutMenu = { eye = true, micromenu = opts.micromenu ~= false }
    __layoutMenu = layoutMenu              -- stands in for the SAVED per-character layout table
    local popout = __frame(nil, nil, 300, 60)
    popout.MicroButtons = {}
    -- ConsolePort's OWN toolbar buttons live in the same popout and are laid out the same way
    popout.Eye = __frame(nil, popout, 32, 40)
    popout.Eye.layoutIndex = 1
    __cpOwn = { popout.Eye }
    popout.Divider1 = { shown = true, SetShown = function(d, v) d.shown = v end }
    popout.layouts = 0
    function popout:RefreshMicroButtons()
        local map = {}
        for _, b in ipairs({ MicroMenu:GetChildren() }) do
            if b.layoutIndex then map[b] = b.layoutIndex end
        end
        self.MicroButtons = map
    end
    function popout:MoveMicroButtons()
        self.Divider1:SetShown(self.props.micromenu)
        if not self.props.micromenu then return end
        self:RefreshMicroButtons()
        for b in pairs(self.MicroButtons) do
            b:SetParent(self); b:ClearAllPoints(); b:SetIgnoreParentAlpha(true)
        end
        self:Layout()
    end
    function popout:Layout() self.layouts = self.layouts + 1 end
    function popout:SetProps(props) self.props = props; self:MoveMicroButtons(); self:Layout() end
    function popout:SetActive(active)
        for b in pairs(self.MicroButtons or {}) do b:SetIgnoreParentAlpha(not active) end
    end
    function popout:OnUpdateMicroButtonsParent()
        if not self.props.micromenu then return end
        self:MoveMicroButtons()
    end
    ConsolePortToolbar = { PopoutContainer = { PopoutFrame = popout } }
    __popout = popout
    popout:SetProps(layoutMenu)            -- ConsolePort_Bar's ADDON_LOADED: takes them first
    if opts.quirk then
        -- what the device showed (09-25 09:43): any later MoveMicroButtons rebuilds the map from
        -- MicroMenu's children, finds none (they are in the popout) and leaves it EMPTY
        popout:MoveMicroButtons()
    end
end

function __parentName(b)
    local p = b:GetParent()
    if p == MicroMenu then return 'MicroMenu' end
    if p == __popout then return 'popout' end
    return tostring(p and p.name)
end
function __allIn(where)
    for _, b in ipairs(__buttons) do if __parentName(b) ~= where then return false end end
    return true
end
function __anyIgnoresAlpha()
    for _, b in ipairs(__buttons) do if b.ignoreParentAlpha then return true end end
    return false
end
function __propsIsLayout() return __popout.props == __layoutMenu end
function __layoutKeys()
    local n = 0
    for _ in pairs(__layoutMenu) do n = n + 1 end
    return n
end
"""

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not cond else ""))


def env(opts=None):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("unpack = unpack or table.unpack")
    lua.execute(MOCK)
    g = lua.globals()
    g.FFSpan = lua.table()
    src = open(os.path.join(ADDON, "FFSpan_Micro.lua"), encoding="utf-8").read()
    lua.execute(src)
    g.__setup(lua.table_from(opts or {}))
    return lua, g


# --- baseline: ConsolePort owns them, exactly as on the device ----------------------------------
lua, g = env()
check("baseline: ConsolePort's toolbar took every micro button at load", g.__allIn("popout"))
st = g.FFSpan.MicroMenu.Status()
check("baseline: Status says consoleport", st.owner == "consoleport" and st.buttons == 4, str(st.owner))
check("baseline: MicroMenuUnits is nil while the menu is an empty 1x1", g.FFSpan.MicroMenuUnits() is None)

# --- claim ----------------------------------------------------------------------------------------
ok, detail = g.FFSpan.MicroMenu.Claim("home-on")
check("claim: succeeds", ok is True, str(detail))
check("claim: every button is back in Blizzard's MicroMenu", g.__allIn("MicroMenu"))
check("claim: no button still ignores its parent's alpha", not g.__anyIgnoresAlpha())
check("claim: ConsolePort now reads micromenu = false", g.__popout.props.micromenu is False)
check("claim: ...and still sees every other option through the proxy", g.__popout.props.eye is True)
check("claim: the SAVED layout table is never written",
      g.__layoutMenu.micromenu is True and g.__layoutKeys() == 2, str(g.__layoutKeys()))
check("claim: ConsolePort's divider hidden by its own path", g.__popout.Divider1.shown is False)
check("claim: Blizzard's container re-laid out around the buttons", g.__layouts >= 1)
check("claim: the popout's own button list is emptied", len(list(g.__popout.MicroButtons.keys())) == 0)
st = g.FFSpan.MicroMenu.Status()
check("claim: Status says blizzard", st.owner == "blizzard" and st.inMenu == 4 and st.claimed is True,
      f"{st.owner} {st.inMenu} {st.claimed}")
units = g.FFSpan.MicroMenuUnits()
check("claim: MicroMenuUnits measures the real row (4 x 32 - 3 x 5 = 113) and the eye (45 + 15)",
      units is not None and units.menuW == 113 and units.menuH == 40 and units.eyeW == 60,
      str(units and (units.menuW, units.menuH, units.eyeW)))

# --- ConsolePort's own paths while claimed ------------------------------------------------------------
g.__popout.OnUpdateMicroButtonsParent(g.__popout)
check("claimed: Blizzard's UpdateMicroButtons hook no longer re-takes them", g.__allIn("MicroMenu"))
g.__popout.SetActive(g.__popout, False)
check("claimed: the popout sliding in/out no longer touches Blizzard's buttons", not g.__anyIgnoresAlpha())
g.__popout.SetProps(g.__popout, g.__layoutMenu)   # a ConsolePort props refresh with the REAL table
check("claimed: a ConsolePort SetProps refresh is re-claimed at once", g.__allIn("MicroMenu"))
check("claimed: ...and ConsolePort is back on the proxy", g.__popout.props.micromenu is False)
check("claimed: the saved table is still untouched after the refresh", g.__layoutMenu.micromenu is True)
ok2, _ = g.FFSpan.MicroMenu.Claim("again")
check("claim twice: idempotent", ok2 is True and g.__allIn("MicroMenu"))

# --- release --------------------------------------------------------------------------------------------
ok, detail = g.FFSpan.MicroMenu.Release("home-off")
check("release: succeeds", ok is True, str(detail))
check("release: ConsolePort has its own props table back (identity)", g.__propsIsLayout() is True)
check("release: ConsolePort took every button back its own way", g.__allIn("popout"))
check("release: Status says consoleport again", g.FFSpan.MicroMenu.Status().owner == "consoleport")
g.__popout.SetProps(g.__popout, g.__layoutMenu)
check("release: a later ConsolePort refresh is left alone (hook is dormant)", g.__allIn("popout"))
ok, detail = g.FFSpan.MicroMenu.Release("again")
check("release twice: harmless", ok is True and g.__allIn("popout"), str(detail))

# --- the device state: ConsolePort's own map is empty while it still holds the buttons ------------
for label, opts in (("GenerateButtonInfos", {"quirk": True}),
                    ("popout-children fallback", {"quirk": True, "noGenerate": True})):
    luaq, gq = env(opts)
    check(f"quirk ({label}): ConsolePort's map is empty but it still holds every button",
          len(list(gq.__popout.MicroButtons.keys())) == 0 and gq.__allIn("popout"))
    ok, detail = gq.FFSpan.MicroMenu.Claim("home-on")
    check(f"quirk ({label}): claim still finds and moves all 4", ok is True and gq.__allIn("MicroMenu")
          and "4 buttons" in str(detail), str(detail))
    check(f"quirk ({label}): ConsolePort's own eye button stays in its popout",
          luaq.eval("__popout.Eye:GetParent() == __popout"))
    check(f"quirk ({label}): a button a game rule kept out is left alone",
          luaq.eval("__ruledOut:GetParent() == MicroMenu and __ruledOut.layoutIndex == nil"))
    ok, _ = gq.FFSpan.MicroMenu.Release("home-off")
    check(f"quirk ({label}): release gives all 4 back to ConsolePort", ok is True and gq.__allIn("popout"))

# --- ConsolePort's option already off -----------------------------------------------------------------
lua2, g2 = env({"micromenu": False})
check("option off: ConsolePort left the buttons with Blizzard", g2.__allIn("MicroMenu"))
ok, detail = g2.FFSpan.MicroMenu.Claim("home-on")
check("option off: claim is a no-op that says why",
      ok is True and "does not own" in str(detail) and g2.FFSpan.MicroMenu.state.claimed is False,
      str(detail))
check("option off: props untouched", g2.__propsIsLayout() is True)
ok, _ = g2.FFSpan.MicroMenu.Release("home-off")
check("option off: release has nothing to do", ok is True and g2.__allIn("MicroMenu"))

# --- no ConsolePort toolbar at all -----------------------------------------------------------------------
lua3, g3 = env({"noToolbar": True})
ok, detail = g3.FFSpan.MicroMenu.Claim("home-on")
check("no toolbar: claim fails soft, no error", ok is False and "no ConsolePort" in str(detail), str(detail))
check("no toolbar: Status still answers", g3.FFSpan.MicroMenu.Status().owner == "blizzard")

print()
print(f"{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
