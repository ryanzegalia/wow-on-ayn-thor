#!/usr/bin/env python3
"""
Mocked-WoW-API tests for FFSpan 2.1: the home screen (FFSpan_Home.lua) plus the geometry contract
in FFSpan_Layout.lua and the 4400-capable dump. All four files load in .toc order.

These are MOCK tests. They prove control flow, arithmetic, snapshot/restore bookkeeping and gating.
They do NOT prove anything about real protected frames, real taint, real Blizzard panel behaviour or
how the Thor's panels actually look -- that takes testing on the device.

Run: python test_ffspan_home.py
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
FILES = ["FFSpan.lua", "FFSpan_Glassy.lua", "FFSpan_Micro.lua", "FFSpan_Layout.lua", "FFSpan_Home.lua", "FFSpan_Dump.lua"]

MOCK_API = r"""
unpack = unpack or table.unpack
__listeners, __timers, __combat = {}, {}, false
__cvars = {}
__calls = {}
local function bump(k) __calls[k] = (__calls[k] or 0) + 1 end
__bump = bump

local function newFrame(name, parent)
    local f = {name=name, parent=parent, points={}, shown=true, strata="MEDIUM", level=1,
               scale=1, rect={0,0,10,10}, children={}, regions={}, events={}}
    function f:GetName() return self.name end
    function f:RegisterEvent(ev) self.events[ev]=true; __listeners[#__listeners+1]=self end
    function f:UnregisterEvent(ev) self.events[ev]=nil end
    function f:SetScript(kind, fn) self["script_"..kind]=fn end
    -- secure-handler attributes: `_onstate-combat` and friends are stored, so a test can run the
    -- addon's OWN snippet body instead of a paraphrase of it
    f.attributes = {}
    function f:SetAttribute(k, v) self.attributes[k]=v end
    function f:GetAttribute(k) return self.attributes[k] end
    -- secure frame refs: handed across out of combat, picked up inside a snippet
    -- (ConsolePort/Controller/Pager.lua:200-203)
    f.frameRefs = {}
    function f:SetFrameRef(k, other) self.frameRefs[k]=other end
    function f:GetFrameRef(k) return self.frameRefs[k] end
    function f:HookScript(kind, fn)
        local prev=self['hs_'..kind]
        self['hs_'..kind]=function(...) if prev then prev(...) end; fn(...) end
    end
    function f:SetFrameStrata(s) self.strata=s end
    function f:GetFrameStrata() return self.strata end
    function f:SetFrameLevel(l) self.level=l end
    function f:GetFrameLevel() return self.level end
    -- `refuseScale` models a frame that genuinely will not take a scale. NOTE (v2.4):
    -- this is NOT what PlayerSpellsFrame does. An earlier build concluded "protected panels refuse
    -- SetScale" from one frame and that was wrong -- it is a checkFit panel that Blizzard
    -- RE-SCALES afterwards through UIPanelUpdateScaleForFit. The real behaviour is modelled by
    -- `checkFit` below; `refuseScale` is kept only to exercise the diagnostic path.
    function f:SetScale(s) if self.refuseScale then return end self.scale=s end
    function f:GetScale() return self.scale end
    function f:GetEffectiveScale() return self.scale end
    function f:SetSize(w,h) self.w,self.h=w,h end
    function f:Show() self.shown=true; if self.hs_OnShow then self.hs_OnShow(self) end end
    function f:Hide() self.shown=false; if self.hs_OnHide then self.hs_OnHide(self) end end
    function f:IsShown() return self.shown end
    function f:IsVisible() return self.shown end
    function f:IsProtected() return self.protected == true end
    function f:IsForbidden() return self.forbidden == true end
    function f:GetParent() return self.parent end
    function f:GetID() return self.id end
    function f:GetRect() return unpack(self.rect) end
    function f:GetChildren() return unpack(self.children) end
    function f:GetRegions() return unpack(self.regions) end
    function f:GetNumPoints() return #self.points end
    function f:GetPoint(i) local p=self.points[i]; if p then return p[1],p[2],p[3],p[4],p[5] end end
    function f:ClearAllPoints() self.points={} end
    function f:SetPoint(p,r,rp,x,y)
        self.points[#self.points+1]={p,r,rp,x or 0,y or 0}
        -- Keep the rect coherent with the anchor for the ONE form FFSpan writes
        -- (TOPLEFT -> UIParent BOTTOMLEFT). Without this the mock's geometry goes stale the
        -- moment FFSpan moves a frame, and anything that measures it afterwards -- a comparison
        -- tooltip following the main one, say -- reads the old position.
        if (p=="TOPLEFT" or p=="TOPRIGHT") and rp=="BOTTOMLEFT" and r==_G.UIParent and self.rect then
            local w,h=self.rect[3],self.rect[4]
            self.rect={(x or 0) - (p=="TOPRIGHT" and w or 0),(y or 0)-h,w,h}
        end
    end
    function f:SetAllPoints(r)
        self.points={{"TOPLEFT",r,"TOPLEFT",0,0},{"BOTTOMRIGHT",r,"BOTTOMRIGHT",0,0}}
    end
    function f:CreateTexture()
        local t={}; function t:SetAllPoints() end; function t:SetColorTexture() end; return t
    end
    if name then _G[name]=f end
    return f
end
__newFrame = newFrame
function CreateFrame(kind, name, parent) return newFrame(name, parent) end

-- real wrapping hooksecurefunc: supports both (table,key,fn) and (globalName,fn)
function hooksecurefunc(a,b,c)
    local obj,key,fn
    if type(a)=="string" then obj,key,fn=_G,a,b else obj,key,fn=a,b,c end
    local orig=obj[key]
    obj[key]=function(...) if orig then orig(...) end; fn(...) end
end

UIParent = newFrame("UIParent")
WorldFrame = newFrame("WorldFrame")
-- the mock does not recompute a rect from anchors, so seed WorldFrame with the rect the centre-game
-- core is supposed to give it: the 16:9 game box, in units (x*q = physical px, q = __H/768)
WorldFrame.rect = {(__W - __H*16/9)/2 / (__H/768), 0, (__H*16/9) / (__H/768), 768}
WorldFrame.points={{"TOPLEFT",UIParent,"TOPLEFT",0,0},{"BOTTOMRIGHT",UIParent,"BOTTOMRIGHT",0,0}}

C_Timer = {}
function C_Timer.After(delay, fn) __timers[#__timers+1]={d=delay, fn=fn} end
function __flush(rounds)
    local n=0
    while #__timers>0 and n<(rounds or 200) do
        local t=table.remove(__timers,1); t.fn(); n=n+1
    end
    return n
end
function __fire(ev, ...)
    for _,f in ipairs(__listeners) do
        if f.events[ev] and f.script_OnEvent then f.script_OnEvent(f, ev, ...) end
    end
end
function InCombatLockdown() return __combat end
function GetPhysicalScreenSize() return __W, __H end
function GetScreenWidth() return __W end
function GetScreenHeight() return __H end
function GetCVar(n) return __cvars[n] end
function SetCVar(n,v) __cvars[n]=tostring(v); bump("SetCVar:"..n) end
C_AddOns = {}
__loadedAddons = {}              -- fixtures declare what the client has actually loaded
function C_AddOns.IsAddOnLoaded(name) return __loadedAddons[name] == true end
SlashCmdList = {}
__printed = {}
DEFAULT_CHAT_FRAME = {AddMessage=function(_,m) __printed[#__printed+1]=tostring(m) end}
function print(m) __printed[#__printed+1]=tostring(m) end
function date() return "2026-09-23 11:30:00" end
function time() return 1790000000 end
__player = "Fatty"
function UnitName() return __player end
function GetRealmName() return "TestRealm" end
function UnitExists() return false end
function IsInGroup() return false end

NUM_CONTAINER_FRAMES = 13
function ContainerFrame_IsCharacterBankTab(id) return type(id)=="number" and id>=100 end
function ContainerFrame_IsAccountBankTab(id) return type(id)=="number" and id>=200 end

-- panel/bag machinery
-- HideUIPanel is PROTECTED: UIParentPanelManager.lua:850 starts with
-- CheckProtectedFunctionsAllowed(), which refuses an insecure caller in combat and puts a red
-- "Interface action blocked" message on screen. The mock records that refusal so a test can see it
-- instead of quietly passing. __blocked is defined by whichever harness wants to count them.
function HideUIPanel(f)
    bump("HideUIPanel")
    if __combat then
        __blocked = __blocked or {}
        __blocked[#__blocked+1] = "HideUIPanel"
        return false
    end
    if f then f:Hide() end
    return true
end
function OpenAllBags()
    bump("OpenAllBags")
    local c=_G.ContainerFrameCombinedBags
    if c then c.shown=true end
    if _G.UpdateContainerFrameAnchors then _G.UpdateContainerFrameAnchors() end
end
-- Blizzard's own ToggleAllBags. Baganator REPLACES this global on a clean init
-- (ViewManagement/Initialize.lua:126), which is one of the two signals the usable gate reads.
function ToggleAllBags()
    bump("ToggleAllBags")
    local c=_G.ContainerFrameCombinedBags
    if c then c.shown = not c.shown end
    if _G.UpdateContainerFrameAnchors then _G.UpdateContainerFrameAnchors() end
end
function CloseAllBags()
    bump("CloseAllBags")
    local c=_G.ContainerFrameCombinedBags
    local was = c and c.shown
    if c then c.shown=false end
    return was and true or false
end
-- UIParentPanelManager.lua:1091-1098 -- bags first, and ANY close makes Escape "handled"
function CloseAllWindows()
    local bagsVisible = CloseAllBags()
    local windowsVisible = false
    for _,n in ipairs({"CharacterFrame","MerchantFrame","BankFrame","WorldMapFrame"}) do
        local f=_G[n]
        if f and f.shown then f:Hide(); windowsVisible=true end
    end
    return (bagsVisible or windowsVisible) and true or false
end
-- one Escape press, exactly as Blizzard routes it
function __escape()
    bump("escape")
    if _G.GameMenuFrame and _G.GameMenuFrame.shown then _G.GameMenuFrame:Hide(); return "closed menu" end
    if CloseAllWindows() then return "closed windows" end
    if _G.GameMenuFrame then _G.GameMenuFrame:Show() end
    return "opened menu"
end
__origCloseAllBags = nil -- set in the preamble after the addon loads, see __freezeCloseAllBags
function UpdateContainerFrameAnchors() bump("UpdateContainerFrameAnchors") end
-- Blizzard's real shape (UIParentPanelManager.lua): the delegate is a LOCAL, SetForbidden() frame
-- that addons cannot see, and the only public dispatch is this GLOBAL function, whose positioning
-- runs synchronously inside it (:1108-1111 -> OnAttributeChanged :206-230 -> :527-632).
-- It moves the panel the way the native pass does, so a post-hook has something to repair.
function UpdateUIPanelPositions(currentFrame)
    bump("UpdateUIPanelPositions")
    -- :705 "update frame's scaling early" -- this one IS inside the global FFSpan post-hooks
    if currentFrame and currentFrame.checkFit then UIPanelUpdateScaleForFit(currentFrame) end
    if currentFrame and currentFrame.ClearAllPoints then
        currentFrame:ClearAllPoints()
        currentFrame:SetPoint("CENTER", UIParent, "BOTTOMLEFT", 0, 0)  -- canvas-relative, FFSpan's is not
    end
end
-- UIParentPanelManager.lua:1062 -- the ONE global every checkFit path funnels through. It fits
-- the frame against UIParent, i.e. the whole 4400 canvas, so a frame that is merely too TALL
-- comes back at scale 1 and an addon's fit is undone.
function UIPanelUpdateScaleForFit(frame, extraWidth, extraHeight)
    bump("UIPanelUpdateScaleForFit")
    if not (frame and frame.GetRect and frame.SetScale) then return end
    local _, _, w, h = frame:GetRect()
    local horiz = (__W / (__H / 768)) / ((w or 1) + (extraWidth or 0))
    local vert  = 768 / ((h or 1) + (extraHeight or 0))
    if horiz < 1 or vert < 1 then frame:SetScale(math.min(horiz, vert)) else frame:SetScale(1) end
end
-- ShowUIPanel: the securecall to UpdateUIPanelPositions (:451), then frame:Show() (addon OnShow
-- hooks run here), then the checkFit rescale at :532 -- which lands AFTER FFSpan's placement and is
-- NOT covered by the UpdateUIPanelPositions hook. This is the real device ordering.
function __showPanel(name)
    local f = _G[name]
    if not f then return end
    UpdateUIPanelPositions(f)
    f:Show()
    if f.checkFit then UIPanelUpdateScaleForFit(f, f.checkFitExtraWidth, f.checkFitExtraHeight) end
end

ContainerFrameSettingsManager = {}
function ContainerFrameSettingsManager:GetBagsShown()
    local out={}
    local c=_G.ContainerFrameCombinedBags
    if c and c.shown then out[#out+1]=c end
    for i=1,13 do
        local f=_G['ContainerFrame'..i]
        if f and f.shown then out[#out+1]=f end
    end
    return out
end

-- ConsolePort mock: the real tri-state Registry, the RUNTIME tracking it drives, and the two
-- public API entry points. Upstream ConsolePort_Cursor/Controller/Stack.lua:141-158 --
--   Registry[owner][name] = state; if widget then (state and trackWidget or untrackWidget)(widget)
-- -- so the runtime tracking follows THAT call's `state` alone, whatever any other owner holds:
-- last call wins. Modelling only the Registry is what hid the restore defect.
function __makeConsolePort(withStack)
    local Stack = {Registry = {}}
    local tracked = {}
    Stack.__tracked = tracked
    function Stack:SetFrame(frame, state, owner)
        local fname = type(frame)=="string" and frame or (frame and frame:GetName())
        if not fname then return end
        local key = owner or "ConsolePort_Cursor"
        self.Registry[key] = self.Registry[key] or {}
        self.Registry[key][fname] = state
        local widget = _G[fname]
        if widget then
            if state then tracked[widget] = true else tracked[widget] = nil end
        end
        bump("SetFrame")
        return true
    end
    -- the only public read upstream exposes: the VISIBLE tracked frames
    function Stack:GetVisibleCursorFrames()
        local out = {}
        for w in pairs(tracked) do if w.shown then out[#out+1] = w end end
        return unpack(out)
    end
    local db = {Stack = Stack}
    local cp = {}
    function cp:GetData() if withStack then return db end return nil end
    function cp:RemoveInterfaceCursorFrame(frame)
        local obj = type(frame)=="string" and _G[frame] or frame
        if not obj then return nil end
        Stack:SetFrame(frame, false)
        bump("cpRemove")
        return true
    end
    function cp:AddInterfaceCursorFrame(frame)
        local obj = type(frame)=="string" and _G[frame] or frame
        if not obj then return nil end
        Stack:SetFrame(frame, true)
        return true
    end
    ConsolePort = cp
    ConsolePortUIStack = Stack.Registry
    return Stack
end

-- is the frame RUNTIME-tracked right now (not just present in the registry)?
function __isTracked(fname)
    local s = ConsolePort and ConsolePort:GetData()
    local t = s and s.Stack and s.Stack.__tracked
    if not t then return nil end
    return t[_G[fname]] and true or false
end

function __reg(fname, owner)
    local s = ConsolePort and ConsolePort:GetData()
    local r = (s and s.Stack.Registry) or ConsolePortUIStack or {}
    local set = r[owner or "ConsolePort_Cursor"]
    if not set then return "absent" end
    local v = set[fname]
    if v == nil then return "absent" end
    return v and "true" or "false"
end

-- returns the physical top-left rect of a frame, the same conversion FFSpan uses
function __px(name)
    local f=_G[name]
    if not f then return nil end
    local l,b,w,h = f:GetRect()
    local q = f:GetEffectiveScale()*__H/768
    return {x=l*q, y=__H-(b+h)*q, w=w*q, h=h*q}
end

-- where a frame's TOPLEFT anchor actually put it, in physical px (top-left origin)
function __placed(name)
    local f=_G[name]
    if not f or #f.points==0 then return nil end
    local p=f.points[1]
    local q=f:GetEffectiveScale()*__H/768
    return {point=p[1], x=p[4]*q, y=__H-p[5]*q, scale=f.scale}
end
"""


def new_env(w, h, preamble=""):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    g.__W, g.__H = w, h
    lua.execute(MOCK_API)
    if preamble:
        lua.execute(preamble)
    load = lua.eval("load")
    for name in FILES:
        with open(os.path.join(ADDON, name), encoding="utf-8") as f:
            load(f.read(), name)("FFSpan")
    return lua, g


def login(g):
    g.__fire("PLAYER_LOGIN")
    g.__fire("PLAYER_ENTERING_WORLD")
    return g.__flush()


results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not cond else ""))


def calls(g, key):
    v = g.__calls[key]
    return int(v) if v else 0


# =============================================================== 1. geometry contract ============
for w, h, game_x, home_w, eligible in [(1920, 1080, None, None, False),
                                       (3160, 1080, 620.0, None, False),
                                       (4400, 1080, 1240.0, 1240.0, True)]:
    lua, g = new_env(w, h)
    gr = g.FFSpan.GameRect()
    hr = g.FFSpan.HomeRect()
    if game_x is None:
        check(f"contract {w}: GameRect is nil", gr is None)
    else:
        check(f"contract {w}: GameRect x={game_x} w=1920",
              gr is not None and abs(gr.x - game_x) < 1e-9 and abs(gr.w - 1920) < 1e-9,
              f"{dict(gr) if gr else None}")
    if home_w is None:
        check(f"contract {w}: HomeRect is nil", hr is None)
    else:
        check(f"contract {w}: HomeRect 0..{home_w}",
              hr is not None and hr.x == 0 and abs(hr.w - home_w) < 1e-9, f"{dict(hr) if hr else None}")
    check(f"contract {w}: HomeEligible={eligible}", bool(g.FFSpan.HomeEligible()) == eligible)
    check(f"contract {w}: HomeEnabled={eligible}", bool(g.FFSpan.HomeEnabled()) == eligible)

# WorldFrame at 4400 -> the game sits at x 1240..3160
lua, g = new_env(4400, 1080)
login(g)
q = 1080 / 768
pts = lua.eval("(function() local p,r,rp,x,y = WorldFrame:GetPoint(1); local p2,_,_,x2,y2 = WorldFrame:GetPoint(2)"
               " return string.format('%s|%.4f|%s|%.4f|%.4f', p, x, p2, x2, y2) end)()")
check("4400: WorldFrame centred on canvas x 1240..3160",
      pts == f"BOTTOMLEFT|{1240 / q:.4f}|TOPRIGHT|{3160 / q:.4f}|{1080 / q:.4f}", pts)
check("4400: centre-game applied flag", g.FFSpan.CentreCore.applied is True)

# listener contract
lua, g = new_env(4400, 1080)
lua.execute("__hits={} FFSpan.RegisterHomeListener(function(en,why) __hits[#__hits+1]=tostring(en)..':'..tostring(why) end)")
check("contract: RegisterHomeListener rejects a non-function", g.FFSpan.RegisterHomeListener(5) is False)
login(g)
hits = list(g.__hits.values())
check("contract: listener fired true at login", len(hits) >= 1 and hits[0].startswith("true:"), f"{hits}")

# =============================================================== 2. state machine ================
PRE_CVARS = '__cvars = {mapFade="1", combinedBags="0", unrelated="7"}'

lua, g = new_env(4400, 1080, PRE_CVARS)
login(g)
check("state: home applied at login", "applied=yes" in g.FFSpan.Home.StatusLine())
check("state: mapFade off + combinedBags on", g.__cvars["mapFade"] == "0" and g.__cvars["combinedBags"] == "1")
rec = g.FFSpanDB.home["TestRealm-Fatty"]
check("state: session opened under the character key", rec is not None and rec.session is not None)
check("state: the ACCOUNT-WIDE journal holds the ORIGINAL cvars",
      g.FFSpanDB.homeShared.cvars["mapFade"] == "1"
      and g.FFSpanDB.homeShared.cvars["combinedBags"] == "0")

lua.execute('SlashCmdList.FFSPAN("home off")')
g.__flush()
check("state: /ffspan home off restores both cvars exactly",
      g.__cvars["mapFade"] == "1" and g.__cvars["combinedBags"] == "0",
      f"{dict(g.__cvars)}")
check("state: home off leaves unrelated cvars alone", g.__cvars["unrelated"] == "7")
rec = g.FFSpanDB.home["TestRealm-Fatty"]
check("state: home off clears the session and persists enabled=false",
      rec.session is None and rec.enabled is False)
check("state: home off reports not applied", "applied=no" in g.FFSpan.Home.StatusLine())

lua.execute('SlashCmdList.FFSPAN("home on")')
g.__flush()
check("state: /ffspan home on re-enables", "applied=yes" in g.FFSpan.Home.StatusLine()
      and g.FFSpanDB.home["TestRealm-Fatty"].enabled is True)

# home off does not disturb centre-game or the marker
check("state: centre-game still applied with home off", g.FFSpan.CentreCore.applied is True)

# v2.6.5: the micro menu follows home on/off (FFSpan_Micro.lua). ConsolePort_Bar's toolbar takes
# the buttons at its own ADDON_LOADED; home on hands them to Blizzard's MicroMenu, home off gives
# them back. Minimal stand-ins, behaviour as documented in FFSpan_Micro.lua's header.
MICRO_PRE = r"""
local B = {}
B.__index = B
function B:GetParent() return self.parent end
function B:SetParent(p) self.parent = p end
function B:SetIgnoreParentAlpha(v) self.ipa = v end
function B:ClearAllPoints() end
__mbuttons = {}
MicroMenuContainer = setmetatable({}, B)
MicroMenu = setmetatable({ parent = MicroMenuContainer, w = 1, h = 1 }, B)
function MicroMenu:GetChildren()
    local out = {}
    for _, b in ipairs(__mbuttons) do if b.parent == self then out[#out + 1] = b end end
    return unpack(out)
end
function MicroMenu:GetWidth() return self.w end
function MicroMenu:GetHeight() return self.h end
function MicroMenu:Layout()
    local n = 0
    for _, b in ipairs(__mbuttons) do if b.parent == self then n = n + 1 end end
    self.w, self.h = (n > 0) and (n * 27 + 5) or 1, (n > 0) and 40 or 1
end
function MicroMenuContainer:Layout() MicroMenu:Layout() end
for i = 1, 3 do __mbuttons[i] = setmetatable({ parent = MicroMenu, layoutIndex = i }, B) end
local menu = { eye = true, micromenu = true }
local p = setmetatable({ MicroButtons = {}, Divider1 = { SetShown = function() end } }, B)
function p:MoveMicroButtons()
    if not self.props.micromenu then return end
    local map = {}
    for _, b in ipairs({ MicroMenu:GetChildren() }) do map[b] = b.layoutIndex end
    self.MicroButtons = map
    for b in pairs(map) do b:SetParent(self); b:SetIgnoreParentAlpha(true) end
end
function p:Layout() end
function p:SetProps(props) self.props = props; self:MoveMicroButtons() end
p:SetProps(menu)
__cpPopout = p
ConsolePortToolbar = { PopoutContainer = { PopoutFrame = p } }
function __microWhere()
    local w = {}
    for _, b in ipairs(__mbuttons) do
        w[#w + 1] = (b.parent == MicroMenu and 'blizzard') or (b.parent == __cpPopout and 'cp') or '?'
    end
    return table.concat(w, ',')
end
"""
lua, g = new_env(4400, 1080, MICRO_PRE)
check("micro: ConsolePort holds the buttons before login", g.__microWhere() == "cp,cp,cp")
login(g)
check("micro: home on hands every micro button to Blizzard's MicroMenu",
      g.__microWhere() == "blizzard,blizzard,blizzard", g.__microWhere())
check("micro: /ffspan home status reports it", "micro menu=blizzard" in g.FFSpan.Home.StatusLine(),
      g.FFSpan.Home.StatusLine())
check("micro: FFScale gets a real measurement to size the slot from",
      g.FFSpan.MicroMenuUnits() is not None and g.FFSpan.MicroMenuUnits().menuW > 2)
lua.execute('SlashCmdList.FFSPAN("home off")')
g.__flush()
check("micro: home off gives them back to ConsolePort", g.__microWhere() == "cp,cp,cp", g.__microWhere())
check("micro: ...with ConsolePort's own props table", lua.eval("__cpPopout.props.micromenu == true "
                                                              "and rawget(__cpPopout.props, 'micromenu') == true"))
lua.execute('SlashCmdList.FFSPAN("home on")')
g.__flush()
check("micro: home on again claims them again", g.__microWhere() == "blizzard,blizzard,blizzard",
      g.__microWhere())

# a login with enabled=false stays off
lua, g = new_env(4400, 1080, 'FFSpanDB = {home={["TestRealm-Fatty"]={enabled=false}}} ' + PRE_CVARS)
login(g)
check("state: enabled=false at login -> stays off and touches no cvar",
      "applied=no" in g.FFSpan.Home.StatusLine() and g.__cvars["mapFade"] == "1")

# multiple characters are independent
lua, g = new_env(4400, 1080, 'FFSpanDB = {home={["TestRealm-Fatty"]={enabled=false}}} ' + PRE_CVARS)
g.__player = "Other"
login(g)
check("state: a second character is unaffected by the first's off state",
      "applied=yes" in g.FFSpan.Home.StatusLine()
      and g.FFSpanDB.home["TestRealm-Other"] is not None
      and g.FFSpanDB.home["TestRealm-Fatty"].enabled is False)

# interrupted prior session at the same geometry: originals survive, they are never re-snapshotted
INTERRUPTED = ('FFSpanDB = {home={["TestRealm-Fatty"]={session={geometry="4400x1080",'
               'cvars={mapFade="1", combinedBags="0"}}}}} __cvars={mapFade="0", combinedBags="1"}')
lua, g = new_env(4400, 1080, INTERRUPTED)
login(g)
rec = g.FFSpanDB.home["TestRealm-Fatty"]
check("state: an interrupted session is reused, not overwritten",
      g.FFSpanDB.homeShared.cvars["mapFade"] == "1"
      and g.FFSpanDB.homeShared.cvars["combinedBags"] == "0")
lua.execute('SlashCmdList.FFSPAN("home off")')
check("state: restore uses the ORIGINAL snapshot after an interrupted session",
      g.__cvars["mapFade"] == "1" and g.__cvars["combinedBags"] == "0", f"{dict(g.__cvars)}")

# stale-session cleanup at a non-home geometry -- must NOT sit behind HomeEligible
STALE = ('FFSpanDB = {home={["TestRealm-Fatty"]={session={geometry="4400x1080",'
         'cvars={mapFade="1", combinedBags="0"}}}}} __cvars={mapFade="0", combinedBags="1"}')
for w in (1920, 3160):
    lua, g = new_env(w, 1080, STALE)
    login(g)
    rec = g.FFSpanDB.home["TestRealm-Fatty"]
    check(f"cleanup: a stale home session is undone on a {w} login",
          rec.session is None and g.__cvars["mapFade"] == "1" and g.__cvars["combinedBags"] == "0",
          f"session={rec.session} cvars={dict(g.__cvars)}")
check("cleanup: 3160 centre-game still works after the cleanup", g.FFSpan.CentreCore.applied is True)

lua, g = new_env(1920, 1080, PRE_CVARS)
login(g)
check("stock 1920: no session, no cvar writes, nothing applied",
      (g.FFSpanDB is None or g.FFSpanDB.home is None) and g.__cvars["mapFade"] == "1")

# =============================================================== 3. ConsolePort ==================
CP = '__makeConsolePort(true) ContainerFrameCombinedBags = __newFrame("ContainerFrameCombinedBags", UIParent)'
lua, g = new_env(4400, 1080, CP + ' ContainerFrame1 = __newFrame("ContainerFrame1", UIParent)')
login(g)
check("cursor: present frames excluded at login",
      g.__reg("ContainerFrameCombinedBags") == "false" and g.__reg("ContainerFrame1") == "false")
check("cursor: an absent frame is not silently marked done", g.__reg("WorldMapFrame") == "absent")
# the map appears late -> the bounded retry ladder picks it up
lua.execute('WorldMapFrame = __newFrame("WorldMapFrame", UIParent)')
g.__fire("ADDON_LOADED")
g.__flush()
check("cursor: a late WorldMapFrame is excluded on retry", g.__reg("WorldMapFrame") == "false")

# exact restore of the tri-state
CP2 = (CP + ' ContainerFrame1 = __newFrame("ContainerFrame1", UIParent)'
          + ' WorldMapFrame = __newFrame("WorldMapFrame", UIParent)')
lua, g = new_env(4400, 1080, CP2)
lua.execute('local s=ConsolePort:GetData().Stack s.Registry["ConsolePort_Cursor"]={ContainerFrame1=true}')
login(g)
check("cursor: exclusion applied over a prior true", g.__reg("ContainerFrame1") == "false")
lua.execute('SlashCmdList.FFSPAN("home off")')
g.__flush()
check("cursor: prior true is restored exactly", g.__reg("ContainerFrame1") == "true")
check("cursor: a previously UNSET frame is cleared, not left false",
      g.__reg("WorldMapFrame") == "absent" and g.__reg("ContainerFrameCombinedBags") == "absent",
      f"map={g.__reg('WorldMapFrame')} bags={g.__reg('ContainerFrameCombinedBags')}")

# no ConsolePort at all -> home still works
lua, g = new_env(4400, 1080, 'ContainerFrameCombinedBags = __newFrame("ContainerFrameCombinedBags", UIParent)')
login(g)
g.__flush()
check("cursor: absent ConsolePort does not break home", "applied=yes" in g.FFSpan.Home.StatusLine())

# =============================================================== 4. resident bags ================
BAGS = ('ContainerFrameCombinedBags = __newFrame("ContainerFrameCombinedBags", UIParent)\n'
        'ContainerFrameCombinedBags.rect = {0, 0, 256, 320}\n'
        'ContainerFrameCombinedBags.shown = false\n'
        'GameMenuFrame = __newFrame("GameMenuFrame", UIParent)\n'
        'GameMenuFrame.rect = {0, 0, 150, 200}\n'
        'GameMenuFrame.shown = false\n'
        'FFScale = {HomeSlots=function() return {minimapBottom=300, bottomBarTop=980} end,\n'
        '           ApplyLayout=function(r) __bump("ApplyLayout") return true end,\n'
        '           ActiveLayoutName=function() return "ThorSpanHome" end}\n')

lua, g = new_env(4400, 1080, BAGS)
login(g)
g.__flush()
check("bags: residency opens the bags at login", calls(g, "OpenAllBags") >= 1)
p = g.__placed("ContainerFrameCombinedBags")
check("bags: anchored inside the home region, right-aligned under the minimap",
      p is not None and p.x > 600 and (p.x + 256 * p.scale * 1.40625) <= 1240 and p.y >= 300,
      f"{dict(p) if p else None}")
check("bags: FFScale.ApplyLayout called when nothing registered a listener", calls(g, "ApplyLayout") >= 1)

# Escape must reach the game menu: FFSpan hooks neither Escape nor CloseAllBags
before_open = calls(g, "OpenAllBags")
lua.execute("CloseAllBags()")
g.__flush()
check("bags: closing the bags does NOT re-open them (Escape trap)",
      calls(g, "OpenAllBags") == before_open and g.ContainerFrameCombinedBags.shown is False)
# ...but the game menu closing resumes residency
lua.execute("GameMenuFrame:Show()")
g.__flush()
lua.execute("GameMenuFrame:Hide()")
g.__flush()
check("bags: residency resumes when the game menu closes", calls(g, "OpenAllBags") > before_open)

# loading screen end also resumes
before_open = calls(g, "OpenAllBags")
g.__fire("LOADING_SCREEN_DISABLED")
g.__flush()
check("bags: residency resumes when a loading screen ends", calls(g, "OpenAllBags") > before_open)

# "two presses for now": Escape reaches the game menu, and residency comes back when it closes
lua, g = new_env(4400, 1080, BAGS)
login(g)
g.__flush()
first = g.__escape()
g.__flush()
second = g.__escape()
g.__flush()
check("escape: press 1 closes the bags, press 2 reaches the game menu",
      first == "closed windows" and second == "opened menu" and g.GameMenuFrame.shown is True,
      f"1={first} 2={second}")
before_open = calls(g, "OpenAllBags")
third = g.__escape()
g.__flush()
check("escape: press 3 closes the menu and residency resumes",
      third == "closed menu" and g.GameMenuFrame.shown is False
      and calls(g, "OpenAllBags") > before_open, f"3={third}")

# FFScale absent -> the minimap bottom and bottom-bar top are measured here instead
NOFFSCALE = ('ContainerFrameCombinedBags = __newFrame("ContainerFrameCombinedBags", UIParent)\n'
             'ContainerFrameCombinedBags.rect = {0,0,256,320} ContainerFrameCombinedBags.shown=false\n'
             'MinimapCluster = __newFrame("MinimapCluster", UIParent)\n'
             'MinimapCluster.rect = {640, 490, 220, 256}\n'   # top-left px y = 1080-(490+256)*1.40625
             'MicroMenuContainer = __newFrame("MicroMenuContainer", UIParent)\n'
             'MicroMenuContainer.rect = {16, 30, 800, 40}\n')
lua, g = new_env(4400, 1080, NOFFSCALE)
login(g)
g.__flush()
minimap_bottom = 1080 - 490 * 1.40625          # bottom edge of MinimapCluster, top-left origin
bar_top = 1080 - (30 + 40) * 1.40625           # top edge of MicroMenuContainer
p = g.__placed("ContainerFrameCombinedBags")
check("bags: without FFScale the column is measured from the minimap and the bottom bar",
      p is not None and p.y >= minimap_bottom and p.y < bar_top and p.x + 360 <= 1240,
      f"placed={dict(p) if p else None} minimapBottom={minimap_bottom} barTop={bar_top}")

# bank containers never take the resident slot
BANK = BAGS + ('ContainerFrame5 = __newFrame("ContainerFrame5", UIParent)\n'
               'ContainerFrame5.rect = {0,0,200,240} ContainerFrame5.id = 101\n')
lua, g = new_env(4400, 1080, BANK)
login(g)
g.__flush()
bagp, bankp = g.__placed("ContainerFrameCombinedBags"), g.__placed("ContainerFrame5")
check("bags: a bank container is placed left of the resident column, never in it",
      bagp is not None and bankp is not None and bankp.x < bagp.x and bankp.x >= 0,
      f"bags={dict(bagp) if bagp else None} bank={dict(bankp) if bankp else None}")

# a column too small for a usable touch target is reported, not silently shrunk away
TINY = BAGS.replace("minimapBottom=300, bottomBarTop=980", "minimapBottom=300, bottomBarTop=420") \
           .replace("rect = {0, 0, 256, 320}", "rect = {0, 0, 256, 900}")
lua, g = new_env(4400, 1080, TINY)
login(g)
g.__flush()
rec = g.FFSpanDB.home["TestRealm-Fatty"]
msgs = [row.d for row in rec.log.values() if row.e == "bags"]
check("bags: a column that would shrink bags below the touch minimum is logged",
      any("usability fail" in str(m) for m in msgs), f"{msgs}")

# =============================================================== 5. window placement =============
WIN = (BAGS +
       'CharacterFrame = __newFrame("CharacterFrame", UIParent)\n'
       'CharacterFrame.rect = {0,0,240,300} CharacterFrame.shown=false\n'
       'MerchantFrame = __newFrame("MerchantFrame", UIParent)\n'
       'MerchantFrame.rect = {0,0,240,300} MerchantFrame.shown=false\n'
       'BankFrame = __newFrame("BankFrame", UIParent)\n'
       'BankFrame.rect = {0,0,500,300} BankFrame.shown=false\n'
       'WorldMapFrame = __newFrame("WorldMapFrame", UIParent)\n'
       'WorldMapFrame.rect = {0,0,500,400} WorldMapFrame.shown=false\n'
       'PlayerSpellsFrame = __newFrame("PlayerSpellsFrame", UIParent)\n'
       'PlayerSpellsFrame.rect = {0,0,600,450} PlayerSpellsFrame.shown=false\n'
       'PlayerSpellsUtil = {FrameTabs={SpellBook=1, ClassTalents=2, ClassSpecializations=3}}\n'
       'PlayerSpellsFrame.tab = 1\n'
       'function PlayerSpellsFrame:GetTab() return self.tab end\n')

lua, g = new_env(4400, 1080, WIN)
login(g)
g.__flush()
lua.execute("CharacterFrame:Show()")
g.__flush()
p = g.__placed("CharacterFrame")
check("windows: a bag companion lands in the lane, left of the bags, inside the home region",
      p is not None and p.x >= 16 and (p.x + 240 * p.scale * 1.40625) <= 1240,
      f"{dict(p) if p else None}")

lua.execute("WorldMapFrame:Show()")
g.__flush()
p = g.__placed("WorldMapFrame")
w_px = 500 * (p.scale if p else 1) * 1.40625
check("windows: a standalone window is centred on the home region and never crosses x=1240",
      p is not None and p.x >= 16 and (p.x + w_px) <= 1240
      and abs((p.x + w_px / 2) - 620) < 1.0,
      f"{dict(p) if p else None} w={w_px}")

# talents take over the top screen; the spellbook tab comes back to the home screen
lua.execute("PlayerSpellsFrame.tab = 2 PlayerSpellsFrame:Show()")
g.__flush()
p = g.__placed("PlayerSpellsFrame")
check("windows: the talents tab is placed on the game rect (x >= 1240)",
      p is not None and p.x >= 1240 and (p.x + 600 * p.scale * 1.40625) <= 3160,
      f"{dict(p) if p else None}")
talent_scale = p.scale if p else None
lua.execute("PlayerSpellsFrame.tab = 1")
g.FFSpan.Home.PlaceAll("tabswitch")
p2 = g.__placed("PlayerSpellsFrame")
check("windows: switching to the spellbook tab moves it back to the home region",
      p2 is not None and (p2.x + 600 * p2.scale * 1.40625) <= 1240, f"{dict(p2) if p2 else None}")
g.FFSpan.Home.PlaceAll("tabswitch")
g.FFSpan.Home.PlaceAll("tabswitch")
p3 = g.__placed("PlayerSpellsFrame")
check("windows: repeated passes never compound the scale",
      p3 is not None and abs(p3.scale - p2.scale) < 1e-9, f"{p2.scale} -> {p3.scale}")
lua.execute("PlayerSpellsFrame.tab = 2")
g.FFSpan.Home.PlaceAll("tabswitch")
p4 = g.__placed("PlayerSpellsFrame")
check("windows: talents<->spellbook round trip is stable",
      p4 is not None and abs(p4.scale - talent_scale) < 1e-9, f"{talent_scale} -> {p4.scale}")

# both stay when they genuinely fit -- in their OWN slots, never overlapping
lua, g = new_env(4400, 1080, WIN)
login(g)
g.__flush()
lua.execute("CharacterFrame:Show()")
g.__flush()
lua.execute("MerchantFrame:Show()")
g.__flush()
a, b = g.__placed("CharacterFrame"), g.__placed("MerchantFrame")
w_px = 240 * 1.40625
check("windows: two companions that fit share the lane in separate, non-overlapping slots",
      g.CharacterFrame.shown is True and g.MerchantFrame.shown is True
      and a is not None and b is not None and abs(a.x - b.x) >= w_px
      and max(a.x, b.x) + w_px <= 1240,
      f"char={dict(a) if a else None} merchant={dict(b) if b else None}")

# ...and the newer one replaces the older when they cannot both fit
lua, g = new_env(4400, 1080, WIN)
login(g)
g.__flush()
lua.execute("CharacterFrame:Show()")
g.__flush()
lua.execute("BankFrame:Show()")
g.__flush()
check("windows: the newer companion replaces the older one when the lane cannot hold both",
      g.BankFrame.shown is True and g.CharacterFrame.shown is False,
      f"char={g.CharacterFrame.shown} bank={g.BankFrame.shown}")

# in combat the older one stays visible and is hidden as soon as combat ends
lua, g = new_env(4400, 1080, WIN)
login(g)
g.__flush()
lua.execute("CharacterFrame:Show()")
g.__flush()
g.__combat = True
lua.execute("BankFrame:Show()")
g.__flush()
check("combat: no panel is hidden while in combat", g.CharacterFrame.shown is True)
g.__combat = False
g.__fire("PLAYER_REGEN_ENABLED")
g.__flush()
check("combat: the queued eviction runs once combat ends", g.CharacterFrame.shown is False)

# a protected frame is deferred in combat, then placed at regen -- and never re-opened if closed
lua, g = new_env(4400, 1080, WIN)
login(g)
g.__flush()
g.__combat = True
lua.execute("WorldMapFrame.protected = true WorldMapFrame:Show()")
g.__flush()
check("combat: a protected frame is not moved in combat", g.__placed("WorldMapFrame") is None)
g.__combat = False
g.__fire("PLAYER_REGEN_ENABLED")
g.__flush()
p = g.__placed("WorldMapFrame")
check("combat: the deferred placement runs at PLAYER_REGEN_ENABLED", p is not None and p.x >= 16)

lua, g = new_env(4400, 1080, WIN)
login(g)
g.__flush()
g.__combat = True
lua.execute("CharacterFrame.protected = true CharacterFrame:Show()")
g.__flush()
lua.execute("CharacterFrame:Hide()")
g.__combat = False
g.__fire("PLAYER_REGEN_ENABLED")
g.__flush()
check("combat: a window the player closed is never re-opened from the stale queue",
      g.CharacterFrame.shown is False and g.__placed("CharacterFrame") is None)

# Blizzard's own panel pass must be followed by FFSpan's, for EVERY visible managed window
lua, g = new_env(4400, 1080, WIN)
login(g)
g.__flush()
lua.execute("CharacterFrame:Show() WorldMapFrame:Show()")
g.__flush()
lua.execute('CharacterFrame:ClearAllPoints() CharacterFrame:SetPoint("TOPLEFT", UIParent, "BOTTOMLEFT", 2000, 500)'
            ' WorldMapFrame:ClearAllPoints() WorldMapFrame:SetPoint("TOPLEFT", UIParent, "BOTTOMLEFT", 2000, 500)')
# the delegate is local+forbidden on a real client; the GLOBAL dispatch is what
# addons can hook, and it is what Blizzard itself calls via securecall before frame:Show()
lua.execute("UpdateUIPanelPositions(CharacterFrame)")
g.__flush()
a, b = g.__placed("CharacterFrame"), g.__placed("WorldMapFrame")
check("hook: the panel-manager post-hook re-places every visible managed window",
      a is not None and b is not None and a.x <= 1240 and b.x <= 1240,
      f"char={dict(a) if a else None} map={dict(b) if b else None}")
check("hook: the post-hook terminates (recursion guard holds)", calls(g, "UpdateUIPanelPositions") == 1,
      f"native passes={calls(g, 'UpdateUIPanelPositions')}")

# v2.6: maximize is the BIG map on the BIG screen. Blizzard's real shape (Cata/Blizzard_WorldMap.lua
# SynchronizeDisplayState + Cata/Blizzard_WorldMap.xml:40-57, loaded by the Mists TOC): fixed
# 1024x768 / 610x438 sizes, a BlackoutFrame anchored to UIParent's corners shown only when
# maximized, and the panel manager's own anchor landing a frame later (device: TOP -> UIParent TOP).
MAPMAX = WIN + r'''
WorldMapFrame.BlackoutFrame = __newFrame(nil, WorldMapFrame)
WorldMapFrame.BlackoutFrame.points = {{"TOPLEFT", UIParent, "TOPLEFT", 0, 0},
                                      {"BOTTOMRIGHT", UIParent, "BOTTOMRIGHT", 0, 0}}
WorldMapFrame.BlackoutFrame.shown = false
function WorldMapFrame:IsMaximized() return self.isMaximized == true end
local function sync(self)
    if self.isMaximized then self.rect = {0, 0, 1024, 768}; self.BlackoutFrame:Show()
    else self.rect = {0, 0, 610, 438}; self.BlackoutFrame:Hide() end
    local f = self
    C_Timer.After(0, function()
        f:ClearAllPoints()
        if f.isMaximized then f:SetPoint("TOP", UIParent, "TOP", 0, 0)
        else f:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 16, -10) end
    end)
end
function WorldMapFrame:Maximize() self.isMaximized = true; sync(self) end
function WorldMapFrame:Minimize() self.isMaximized = false; sync(self) end
'''
lua, g = new_env(4400, 1080, MAPMAX)
login(g)
g.__flush()
lua.execute("WorldMapFrame.rect = {0, 0, 610, 438} WorldMapFrame:Show()")
g.__flush()
small = g.__placed("WorldMapFrame")
check("map: the ordinary map is a page on the home screen",
      small is not None and small.x >= 16 and (small.x + 610 * small.scale * 1.40625) <= 1240,
      f"{dict(small) if small else None}")
lua.execute("WorldMapFrame:Maximize()")
g.__flush()
big = g.__placed("WorldMapFrame")
bf = g.WorldMapFrame.BlackoutFrame
check("map: maximize puts the big map on the top screen, after Blizzard's own late anchor",
      big is not None and big.point == "TOPLEFT" and big.x >= 1240
      and (big.x + 1024 * big.scale * 1.40625) <= 3160 and big.y >= 0
      and (big.y + 768 * big.scale * 1.40625) <= 1080,
      f"{dict(big) if big else None}")
check("map: the maximized map is bigger than the page it replaced", big.scale * 1024 > small.scale * 610)
def anchors(frame):
    # (point, relativeTo name) -- lupa wrappers do not compare Lua tables by identity
    return [(p[1], p[2] and p[2].name) for p in frame.points.values()]


check("map: the blackout covers only the world view, so the home screen stays live",
      anchors(bf) == [("TOPLEFT", "WorldFrame"), ("BOTTOMRIGHT", "WorldFrame")], f"{anchors(bf)}")
check("map: the dump expects the maximized map on the top screen",
      g.FFSpan.ManagedIntent().WorldMapFrame == "top")
lua.execute("WorldMapFrame:Minimize()")
g.__flush()
back = g.__placed("WorldMapFrame")
check("map: minimize brings it back to the home screen",
      back is not None and (back.x + 610 * back.scale * 1.40625) <= 1240 and back.x >= 16,
      f"{dict(back) if back else None}")
lua.execute('SlashCmdList.FFSPAN("home off")')
g.__flush()
check("map: home off gives the blackout back its own UIParent anchors",
      anchors(bf) == [("TOPLEFT", "UIParent"), ("BOTTOMRIGHT", "UIParent")], f"{anchors(bf)}")

# v2.6.3 map probe (read-only diagnostic for the Classic zero-canvas errors). Classic's shape:
# ScrollContainer anchored TOPLEFT/BOTTOMRIGHT inside the map (Cata/Blizzard_WorldMap.xml:5-9),
# a QuestLog side panel hidden by SetQuestLogPanelShown(false) BEFORE SynchronizeDisplayState, and
# MaximizeUIPanel re-anchoring to "top" synchronously (UIParentPanelManager.lua:143-147).
PROBE = MAPMAX + r'''
local sc = __newFrame(nil, WorldMapFrame)
sc.points = {{"TOPLEFT", WorldMapFrame, "TOPLEFT", 11, -70}, {"BOTTOMRIGHT", WorldMapFrame, "BOTTOMRIGHT", -11, 30}}
sc.rect = {11, 30, 1002, 668}
function sc:GetSize() return self.rect[3], self.rect[4] end
sc.Child = __newFrame(nil, sc)
function sc.Child:GetLeft() return nil end   -- the device's broken state: :748 nil arithmetic
function sc.Child:GetTop() return nil end
sc.baseScale = 0
sc.zoomLevels = {{scale = 0}}
WorldMapFrame.ScrollContainer = sc
WorldMapFrame.QuestLog = __newFrame(nil, WorldMapFrame)
function WorldMapFrame:GetSize() return self.rect[3], self.rect[4] end
function WorldMapFrame:OnFrameSizeChanged() __bump("OnFrameSizeChanged") end
function MaximizeUIPanel(frame) frame:ClearAllPoints(); frame:SetPoint("TOP", UIParent, "TOP", 0, 0) end
function RestoreUIPanelArea(frame) end
'''
lua, g = new_env(4400, 1080, PROBE)
login(g)
g.__flush()
lua.execute("WorldMapFrame.isMaximized = true WorldMapFrame.rect = {0, 0, 1024, 768} WorldMapFrame:Show()")
g.__flush()
lua.execute("WorldMapFrame.QuestLog:Hide() MaximizeUIPanel(WorldMapFrame)")
g.__flush()
check("probe: off by default -- its rect reads would hide the very staleness it looks for",
      not g.FFSpanDB.mapProbe)
lua.execute('SlashCmdList.FFSPAN("mapprobe on")')
check("probe: /ffspan mapprobe on turns it on", g.FFSpanDB.mapProbeOn is True)
before_map, before_sc = anchors(g.WorldMapFrame), anchors(g.WorldMapFrame.ScrollContainer)
n0 = len(g.FFSpanDB.mapProbe or {}) if g.FFSpanDB.mapProbe else 0
lua.execute("WorldMapFrame.QuestLog:Hide() MaximizeUIPanel(WorldMapFrame) WorldMapFrame:OnFrameSizeChanged()")
rows_now = [dict(r) for r in g.FFSpanDB.mapProbe.values()][n0:]
evs = [r.get("ev") for r in rows_now]
check("probe: records the QuestLog hide, MaximizeUIPanel and a clean canvas pass, in order",
      evs == ["questlog hide", "MaximizeUIPanel", "canvas ok"], f"{evs}")
mx = rows_now[1] if len(rows_now) > 1 else {}
check("probe: a row carries the map's anchors, the ScrollContainer size and the zoom scale",
      "TOP>UIParent.TOP" in (mx.get("map") or "") and "1002x668" in (mx.get("sc") or "")
      and mx.get("z1") == 0 and mx.get("max") is True and mx.get("ql") is False
      and "left=nil" in (mx.get("child") or ""), f"{mx}")
g.__flush()
evs2 = [dict(r).get("ev") for r in g.FFSpanDB.mapProbe.values()][n0:]
check("probe: each hook also records the next frame", "questlog hide +1" in evs2 and "MaximizeUIPanel +1" in evs2,
      f"{evs2}")
check("probe: probing moves nothing (map anchors are Blizzard's, ScrollContainer untouched)",
      anchors(g.WorldMapFrame) == [("TOP", "UIParent")] and anchors(g.WorldMapFrame.ScrollContainer) == before_sc,
      f"map {before_map} -> {anchors(g.WorldMapFrame)}; sc {anchors(g.WorldMapFrame.ScrollContainer)}")
check("probe: the Blizzard call still runs exactly once under the hook", calls(g, "OnFrameSizeChanged") == 1,
      f"{calls(g, 'OnFrameSizeChanged')}")
lua.execute("for i = 1, 100 do WorldMapFrame.QuestLog:Hide() end")
check("probe: the ring is bounded", len(g.FFSpanDB.mapProbe) <= 64, f"{len(g.FFSpanDB.mapProbe)}")
lua.execute('SlashCmdList.FFSPAN("mapprobe off")')
n1 = len(g.FFSpanDB.mapProbe)
lua.execute("WorldMapFrame.QuestLog:Hide()")
g.__flush()
check("probe: /ffspan mapprobe off stops it", not g.FFSpanDB.mapProbeOn and len(g.FFSpanDB.mapProbe) == n1)
lua, g = new_env(1920, 1080, PROBE)
login(g)
g.__flush()
lua.execute('SlashCmdList.FFSPAN("mapprobe on")')
lua.execute("WorldMapFrame:Show() WorldMapFrame.QuestLog:Hide() MaximizeUIPanel(WorldMapFrame)")
g.__flush()
check("probe: silent on a normal 1920x1080 launch", not g.FFSpanDB or not g.FFSpanDB.mapProbe)

# v2.6.4 the fix, against a model of what the device showed (09-25 A/B): a SCALE change leaves the
# map's rects unresolved; ScrollContainer:GetWidth() then reads 0 without resolving them (what
# CreateZoomLevels :427 got), while GetRect/GetSize resolve. Classic's chain: SynchronizeDisplayState
# -> MaximizeUIPanel (MoveUIPanel's securecall to UpdateUIPanelPositions fires FFSpan's pass, which
# re-scales the map, then the "top" anchor) -> OnFrameSizeChanged -> CreateZoomLevels.
LAZY = PROBE + r'''
local sc = WorldMapFrame.ScrollContainer
local function stale() WorldMapFrame.__stale = true; sc.__stale = true; sc.Child.__stale = true end
local setScale = WorldMapFrame.SetScale
function WorldMapFrame:SetScale(s) setScale(self, s); stale() end
function sc:GetWidth() if self.__stale then return 0 end return self.rect[3] end
for _, f in ipairs({WorldMapFrame, sc, sc.Child}) do
    for _, key in ipairs({"GetRect", "GetSize"}) do
        local orig = f[key]
        if orig then f[key] = function(self, ...) self.__stale = nil; return orig(self, ...) end end
    end
end
function MaximizeUIPanel(frame)
    UpdateUIPanelPositions(frame)
    frame:ClearAllPoints(); frame:SetPoint("TOP", UIParent, "TOP", 0, 0)
end
function WorldMapFrame:SynchronizeDisplayState()
    MaximizeUIPanel(self)
    __zoomWidth = self.ScrollContainer:GetWidth()
end
'''
lua, g = new_env(4400, 1080, LAZY)
login(g)
g.__flush()
lua.execute("WorldMapFrame.isMaximized = true WorldMapFrame.rect = {0, 0, 1024, 768} WorldMapFrame:Show()")
g.__flush()
lua.execute("__zoomWidth = nil WorldMapFrame:SynchronizeDisplayState()")
check("map fix: Blizzard's canvas reads the real ScrollContainer width after the re-scale",
      g.__zoomWidth == 1002, f"width={g.__zoomWidth}")
lua.execute("__keep = FFSpan.MapMax.resolve FFSpan.MapMax.resolve = function() end")
lua.execute("__zoomWidth = nil WorldMapFrame:SynchronizeDisplayState()")
check("map fix control: without the resolve the model reproduces the device's zero width",
      g.__zoomWidth == 0, f"width={g.__zoomWidth}")
lua.execute('SlashCmdList.FFSPAN("home off")')
g.__flush()
lua.execute("WorldMapFrame.ScrollContainer:GetRect() __zoomWidth = nil WorldMapFrame:SynchronizeDisplayState()")
check("map fix control: with home off (no re-scale) Blizzard's own chain is clean even unresolved",
      g.__zoomWidth == 1002, f"width={g.__zoomWidth}")
lua.execute("FFSpan.MapMax.resolve = __keep")

# disabling home while retries are still queued must cancel them
CPLATE = '__makeConsolePort(true) ContainerFrameCombinedBags = __newFrame("ContainerFrameCombinedBags", UIParent)'
lua, g = new_env(4400, 1080, CPLATE)
login(g)
check("queue: retries are still pending while a frame is missing", g.__reg("WorldMapFrame") == "absent")
lua.execute('SlashCmdList.FFSPAN("home off")')
lua.execute('WorldMapFrame = __newFrame("WorldMapFrame", UIParent)')
g.__flush()
g.__fire("ADDON_LOADED")
g.__flush()
check("queue: a queued retry does nothing after home is switched off",
      g.__reg("WorldMapFrame") == "absent", f"{g.__reg('WorldMapFrame')}")

# home off restores the anchors and scale the windows had
lua, g = new_env(4400, 1080, WIN)
lua.execute('CharacterFrame:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 11, -22) CharacterFrame:SetScale(0.9)')
login(g)
g.__flush()
lua.execute("CharacterFrame:Show()")
g.__flush()
moved = g.__placed("CharacterFrame")
lua.execute('SlashCmdList.FFSPAN("home off")')
g.__flush()
restored = lua.eval('(function() local p,r,rp,x,y = CharacterFrame:GetPoint(1)'
                    ' return string.format("%s|%s|%.2f|%.2f|%.4f", p, rp, x, y, CharacterFrame:GetScale()) end)()')
check("restore: home off puts moved windows back on their exact anchor and scale",
      restored == "TOPLEFT|TOPLEFT|11.00|-22.00|0.9000", f"moved={dict(moved) if moved else None} now={restored}")

# ...and a protected frame that could not be restored during combat is restored at regen
lua, g = new_env(4400, 1080, WIN)
lua.execute('CharacterFrame:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 11, -22) CharacterFrame.protected = true')
login(g)
g.__flush()
lua.execute("CharacterFrame:Show()")
g.__flush()
g.__combat = True
lua.execute('SlashCmdList.FFSPAN("home off")')
g.__flush()
during = lua.eval('(function() local p,r,rp,x,y = CharacterFrame:GetPoint(1) return string.format("%.2f|%.2f", x, y) end)()')
check("restore: a protected frame is NOT force-moved during a combat-time home off", during != "11.00|-22.00")
g.__combat = False
g.__fire("PLAYER_REGEN_ENABLED")
g.__flush()
after = lua.eval('(function() local p,r,rp,x,y = CharacterFrame:GetPoint(1) return string.format("%s|%.2f|%.2f", p, x, y) end)()')
check("restore: the deferred restore completes at PLAYER_REGEN_ENABLED",
      after == "TOPLEFT|11.00|-22.00", f"during={during} after={after}")

# the resident bags can never starve the companion lane
lua, g = new_env(4400, 1080, WIN.replace("rect = {0, 0, 256, 320}", "rect = {0, 0, 2000, 320}"))
login(g)
g.__flush()
lua.execute("CharacterFrame:Show()")
g.__flush()
bagp, charp = g.__placed("ContainerFrameCombinedBags"), g.__placed("CharacterFrame")
check("bags: an over-wide bag frame is capped so the companion lane survives",
      bagp is not None and charp is not None and charp.x >= 16 and charp.x < bagp.x,
      f"bags={dict(bagp) if bagp else None} char={dict(charp) if charp else None}")

# =============================================================== 6. dump at 4400 =================
lua, g = new_env(4400, 1080, WIN)
login(g)
g.__flush()
lua.execute('SlashCmdList.FFSPAN("dump home")')
d = g.FFSpanDB and g.FFSpanDB.dumps and g.FFSpanDB.dumps["home"]
check("dump: /ffspan dump works at 4400x1080", d is not None and d.label == "home")
check("dump: records the game and home rects + home state",
      d is not None and abs(d.gameRect.x - 1240) < 1e-9 and abs(d.homeRect.w - 1240) < 1e-9
      and d.homeEligible is True and d.homeEnabled is True)
check("dump: records the FFScale layout identity", d is not None and d.editModeLayout == "ThorSpanHome")
rows = {r.name: r for r in d.frames.values()} if d else {}
wf = rows.get("WorldFrame")
check("dump: WorldFrame is intended-top and actually on top",
      wf is not None and wf.intendedScreen == "top" and wf.actualScreen == "top",
      f"{dict(wf) if wf else None}")
check("dump: rows carry protection state", wf is not None and wf.protected is not None)

# a top frame parked in the home region is flagged
lua, g = new_env(4400, 1080, WIN + 'BuffFrame = __newFrame("BuffFrame", UIParent) BuffFrame.rect={0,0,100,50}\n')
login(g)
g.__flush()
lua.execute('SlashCmdList.FFSPAN("dump viol")')
d = g.FFSpanDB.dumps["viol"]
names = [v.name for v in d.screenViolations.values()]
check("dump: an intended-top frame sitting on the home screen is flagged",
      "BuffFrame" in names and d.violationCount >= 1, f"{names}")

# 3160 keeps working unchanged
lua, g = new_env(3160, 1080)
login(g)
lua.execute('SlashCmdList.FFSPAN("dump centre")')
d = g.FFSpanDB and g.FFSpanDB.dumps and g.FFSpanDB.dumps["centre"]
check("dump: 3160 still dumps, with no home rect", d is not None and d.homeRect is None
      and d.homeEligible is False and abs(d.gameRect.x - 620) < 1e-9)

lua, g = new_env(1920, 1080)
login(g)
lua.execute('SlashCmdList.FFSPAN("dump")')
check("dump: stock 1920 still refuses and writes nothing", g.FFSpanDB is None)

# =============================================================== 7. slash surface ================
lua, g = new_env(4400, 1080, WIN)
login(g)
g.__printed = lua.table()
lua.execute('SlashCmdList.FFSPAN("home status")')
check("slash: /ffspan home status prints the state",
      any("canvas 4400x1080" in p and "eligible=yes" in p for p in g.__printed.values()),
      f"{list(g.__printed.values())}")
g.__printed = lua.table()
lua.execute('SlashCmdList.FFSPAN("home wat")')
check("slash: an unknown home argument prints usage",
      any("usage: /ffspan home" in p for p in g.__printed.values()))
g.__printed = lua.table()
lua.execute('SlashCmdList.FFSPAN("")')
check("slash: plain /ffspan still prints the v2.0 status line",
      any("physical" in p for p in g.__printed.values()))

# =============================================================== 8. Baganator onboarding gate ====
# v2.5.5: the "first-run welcome open" wait used to be gated to Classic only (soft.enabled), so on
# a fresh RETAIL account with the Baganator welcome chooser still open, computeUsable() fell
# straight through to the generic "not yet initialised" verdict -- which LATCHES (usableDecided)
# and only re-arms on ADDON_LOADED of Baganator/Syndicator, which had already fired by then.
# Picking a bag view then never recovered resident bags on Retail (see FFSpan_Home.lua v2.5.5).
# `S`, `soft` and the bare `baganatorUsable` all live inside the addon's own loaded chunk and are
# NOT reachable from a standalone lua.eval() in this harness (confirmed: both `S.BaganatorWhyNot()`
# and the un-local'd `baganatorUsable()` raise "global ... is nil" from outside), so this proves the
# regression at the boundary that IS reachable: a full login must complete without a Lua error once
# the onboarding branch stops being skipped on Retail -- the exact new path this fix takes that it
# never took before. A pre-fix regression here would be a hard crash, not a silent wrong answer.
BAGANATOR_WELCOME = '''
Baganator = {API = {Constants = {}}}
Syndicator = true
function IsAddOnLoaded(name) return name == "Syndicator" end
Baganator_WelcomeFrame = __newFrame("Baganator_WelcomeFrame", UIParent)
'''

for wow_id, label in ((2, "classic"), (1, "retail")):
    ok, err = True, None
    try:
        lua, g = new_env(4400, 1080,
                          WIN + BAGANATOR_WELCOME + f'WOW_PROJECT_ID = {wow_id} WOW_PROJECT_MAINLINE = 1\n')
        login(g)
        g.__flush()
    except Exception as e:
        ok, err = False, e
    check(f"baganator: {label} login completes with the welcome chooser open (onboarding path runs, no error)",
          ok, err)

# =============================================================== 9. Baganator soft recovery ======
# Retail latched NOT_INIT and later had a shown frame in the unseen strip. The dump establishes
# failed discovery, not frame-creation timing. Installed829 normally builds both views at login.
# These synthetic late-frame cases test recovery beyond that ordinary cold-start path.

# Defensive-only fixture: a hypothetical late frame becomes discoverable during a bag press.
# This is NOT Baganator829's actual ToggleAllBags implementation; that toggles existing frames.
BAGANATOR_LAZY = '''
Baganator = {API = {Constants = {}}}
Syndicator = true
__loadedAddons.Syndicator = true   -- computeUsable's addonIsLoaded() prefers C_AddOns, not the global
C_Container = {GetContainerNumSlots = function(i) return i == 0 and 16 or 0 end}
NUM_BAG_SLOTS = 4
__bagFrame = nil
function ToggleAllBags()
    __bump("ToggleAllBags")
    if not __bagFrame then
        __bagFrame = __newFrame("Baganator_SingleViewBackpackViewFrame", UIParent)
        __bagFrame.shown = false
        table.insert(UIParent.children, __bagFrame)
    end
    __bagFrame.shown = not __bagFrame.shown
end
'''

# ---- fresh Retail: early NOT_INIT, ladder exhausted, late frame, explicit toggle recovers+docks --
lua, g = new_env(4400, 1080, WIN + BAGANATOR_LAZY + 'WOW_PROJECT_ID = 1 WOW_PROJECT_MAINLINE = 1\n')
login(g)  # login's own flush already drains the whole 2/5/15/45s ladder; no frame exists yet
check("soft/retail: NOT_INIT latches, and the ladder (now running on Retail too) alone does not "
      "recover a frame that was never there",
      g.FFSpan.BaganatorUsable() is False
      and g.FFSpan.BaganatorWhyNot() == "loaded but never initialised (no bag view)",
      f"{g.FFSpan.BaganatorWhyNot()}")
lua.execute("ToggleAllBags()")  # the EXPLICIT press, minutes later: Baganator builds+shows its view
g.__flush()                     # runs the guarded one-way recheck the toggle hook just scheduled
check("soft/retail: an explicit toggle after the ladder is spent still recovers usable",
      g.FFSpan.BaganatorUsable() is True and g.FFSpan.BaganatorWhyNot() is None,
      f"usable={g.FFSpan.BaganatorUsable()} why={g.FFSpan.BaganatorWhyNot()}")
check("soft/retail: the recovered view actually gets docked (SetPoint ran) once",
      g.__placed("Baganator_SingleViewBackpackViewFrame") is not None)

# ---- the welcome chooser's own preview is never stolen, even though it is a shown UIParent child -
CHOOSER_PREVIEW = '''
Baganator = {API = {Constants = {}}}
Syndicator = true
__loadedAddons.Syndicator = true   -- computeUsable's addonIsLoaded() prefers C_AddOns, not the global
Baganator_WelcomeFrame = __newFrame("Baganator_WelcomeFrame", UIParent)
Baganator_WelcomeFrame.shown = true
__preview = __newFrame("Baganator_SingleViewBackpackViewFrame", UIParent)
__preview.shown = true
table.insert(UIParent.children, __preview)
'''
lua, g = new_env(4400, 1080, WIN + CHOOSER_PREVIEW + 'WOW_PROJECT_ID = 1 WOW_PROJECT_MAINLINE = 1\n')
login(g)
g.__flush()
check("soft/retail: the chooser's own shown preview is not promoted to usable while it is open",
      g.FFSpan.BaganatorUsable() is False
      and g.FFSpan.BaganatorWhyNot() == "first-run welcome open (onboarding)",
      f"{g.FFSpan.BaganatorWhyNot()}")
lua.execute("Baganator_WelcomeFrame:Hide()")  # the player's real choice closes the chooser
g.__flush()
check("soft/retail: closing the chooser recovers the SAME frame the preview used "
      "(nothing stolen, nothing lost)",
      g.FFSpan.BaganatorUsable() is True and g.FFSpan.BaganatorBackpack() is not None)

# ---- a hard missing dependency is never promoted, and never even rechecked -----------------------
NO_SYNDICATOR = '''
Baganator = {API = {Constants = {}}}
function IsAddOnLoaded(name) return false end
'''
lua, g = new_env(4400, 1080, WIN + NO_SYNDICATOR + 'WOW_PROJECT_ID = 1 WOW_PROJECT_MAINLINE = 1\n')
login(g)
g.__flush()
check("soft/retail: Syndicator missing is a hard no",
      g.FFSpan.BaganatorWhyNot() == "Syndicator not loaded")
lua.execute('local f = __newFrame("Baganator_SingleViewBackpackViewFrame", UIParent)\n'
            'f.shown = true\n'
            'table.insert(UIParent.children, f)\n')
lua.execute("ToggleAllBags()")
g.__flush()
check("soft/retail: a hard no is never promoted by a later frame or an explicit toggle",
      g.FFSpan.BaganatorUsable() is False and g.FFSpan.BaganatorWhyNot() == "Syndicator not loaded",
      f"{g.FFSpan.BaganatorWhyNot()}")

# ---- an already-usable Retail account is unaffected by any of this -------------------------------
ALREADY_USABLE = '''
Baganator = {API = {Constants = {}}}
Syndicator = true
__loadedAddons.Syndicator = true   -- computeUsable's addonIsLoaded() prefers C_AddOns, not the global
UISpecialFrames = {"Baganator_SingleViewBackpackViewFrame"}
__newFrame("Baganator_SingleViewBackpackViewFrame", UIParent)
'''
lua, g = new_env(4400, 1080, WIN + ALREADY_USABLE + 'WOW_PROJECT_ID = 1 WOW_PROJECT_MAINLINE = 1\n')
login(g)
g.__flush()
check("soft/retail: an already-configured account is usable immediately, no soft path involved",
      g.FFSpan.BaganatorUsable() is True and g.FFSpan.BaganatorWhyNot() is None)
lua.execute("ToggleAllBags()")
g.__flush()
check("soft/retail: toggling an already-usable account is still a no-op on the verdict",
      g.FFSpan.BaganatorUsable() is True and g.FFSpan.BaganatorWhyNot() is None)

# ---- off-home (stock 1920) never engages the soft machinery, and never errors --------------------
lua, g = new_env(1920, 1080, BAGANATOR_LAZY + 'WOW_PROJECT_ID = 1 WOW_PROJECT_MAINLINE = 1\n')
ok, err = True, None
try:
    login(g)
    lua.execute("ToggleAllBags()")
    g.__flush()
except Exception as e:
    ok, err = False, e
check("soft/stock: stock 1920 (home ineligible) never errors and never decides a verdict",
      ok and g.FFSpan.BaganatorWhyNot() is None, err)

# ---- combat defers the recheck's mutation; it recovers cleanly once combat ends -------------------
lua, g = new_env(4400, 1080, WIN + BAGANATOR_LAZY + 'WOW_PROJECT_ID = 1 WOW_PROJECT_MAINLINE = 1\n')
login(g)
g.__flush()
g.__combat = True
lua.execute("ToggleAllBags()")
g.__flush()
check("soft/combat: an explicit toggle in combat does not mutate frames or flip the verdict",
      g.FFSpan.BaganatorUsable() is False
      and g.__placed("Baganator_SingleViewBackpackViewFrame") is None,
      f"usable={g.FFSpan.BaganatorUsable()}")
check("soft/combat: no timer polling while waiting for combat to end", len(list(g.__timers.values())) == 0)
g.__combat = False
g.__fire("PLAYER_REGEN_ENABLED")
g.__flush()
check("soft/combat: the deferred recheck completes once combat ends, with no further player action",
      g.FFSpan.BaganatorUsable() is True
      and g.__placed("Baganator_SingleViewBackpackViewFrame") is not None)

# ---- REAL cold-start shape (source-confirmed, installed829): Baganator's Skins/Initialize.lua
# builds its frame group at ITS OWN PLAYER_LOGIN and ViewManagement/Initialize.lua registers both
# views in UISpecialFrames there too -- well before FFSpan's own readiness point, and with no
# manual bag press involved at all. ToggleAllBags only shows/hides that already-built frame; it
# never creates it. The 09-24 dump found the frame reachable only through UIParent's children
# (not UISpecialFrames), so that is what this fixture models -- distinct from the late-created,
# defensive-only synthetic fixture above (BAGANATOR_LAZY), which stays as bounded extra coverage.
COLD_START_HIDDEN = '''
Baganator = {API = {Constants = {}}}
Syndicator = true
__loadedAddons.Syndicator = true
C_Container = {GetContainerNumSlots = function(i) return i == 0 and 16 or 0 end}
NUM_BAG_SLOTS = 4
Baganator_SingleViewBackpackViewFrame = __newFrame("Baganator_SingleViewBackpackViewFrame", UIParent)
Baganator_SingleViewBackpackViewFrame.shown = false
table.insert(UIParent.children, Baganator_SingleViewBackpackViewFrame)
function ToggleAllBags()
    __bump("ToggleAllBags")
    Baganator_SingleViewBackpackViewFrame.shown = not Baganator_SingleViewBackpackViewFrame.shown
end
'''
lua, g = new_env(4400, 1080, WIN + COLD_START_HIDDEN + 'WOW_PROJECT_ID = 1 WOW_PROJECT_MAINLINE = 1\n')
login(g)  # no player action at all -- just entering the world with the frame already built+hidden
g.__flush()
check("soft/retail: a hidden frame that already exists at readiness opens and resides "
      "automatically, with no manual ToggleAllBags",
      g.FFSpan.BaganatorUsable() is True and g.FFSpan.BaganatorWhyNot() is None
      and g.__placed("Baganator_SingleViewBackpackViewFrame") is not None,
      f"usable={g.FFSpan.BaganatorUsable()} why={g.FFSpan.BaganatorWhyNot()} "
      f"placed={g.__placed('Baganator_SingleViewBackpackViewFrame')}")

# =============================================================== 10. real multi-view discovery ===
# Installed829 creates/registers both views via pairs(), not just the selected one. A hidden
# category listed first must not be mistaken for the active single-grid backpack.
MULTI_VIEW = '''
Baganator = {API = {Constants = {}}}
__loadedAddons.Syndicator = true
BAGANATOR_CURRENT_PROFILE = "DEFAULT"
BAGANATOR_CONFIG = {Profiles = {DEFAULT = {bag_view_type="single", current_skin="blizzard"}}}
__single = __newFrame("Baganator_SingleViewBackpackViewFrameblizzard", UIParent)
__category = __newFrame("Baganator_CategoryViewBackpackViewFrameblizzard", UIParent)
__old = __newFrame("Baganator_SingleViewBackpackViewFramedark", UIParent)
__single.shown, __category.shown, __old.shown = false, false, false
UIParent.children = {__category, __old, __single}
UISpecialFrames = {__category:GetName(), __old:GetName(), __single:GetName()}
function ToggleAllBags() __single.shown = not __single.shown end
'''
lua, g = new_env(4400, 1080, WIN + MULTI_VIEW)
check("views: hidden selected single/skin wins over first UISpecialFrames entry",
      g.FFSpan.BaganatorBackpack().GetName(g.FFSpan.BaganatorBackpack()) ==
      "Baganator_SingleViewBackpackViewFrameblizzard")
lua.execute('BAGANATOR_CONFIG.Profiles.DEFAULT.bag_view_type="category"')
check("views: hidden category selection is honored without rewriting the profile",
      lua.eval('FFSpan.BaganatorBackpack() == __category'))
lua.execute('__single.shown=true')
check("views: actually shown backpack beats an unshown config choice",
      lua.eval('FFSpan.BaganatorBackpack() == __single'))
lua.execute('UISpecialFrames={} __single.shown=false')
check("views: UIParent-only fallback uses the same selected-view rule",
      lua.eval('FFSpan.BaganatorBackpack() == __category'))
lua.execute('UISpecialFrames={__category:GetName(), __single:GetName()} '
            'Baganator_WelcomeFrame=__newFrame("Baganator_WelcomeFrame", UIParent)')
check("views: chooser previews are unavailable even when UISpecialFrames contains both",
      g.FFSpan.BaganatorBackpack() is None)
lua.execute('Baganator_WelcomeFrame:Hide() BAGANATOR_CONFIG.Profiles.DEFAULT.bag_view_type="single"')
login(g)
check("views: cold login opens the actual selected backpack, not its hidden sibling",
      g.__single.shown is True and g.__category.shown is False
      and lua.eval('FFSpan.BaganatorBackpack() == __single'))

lua, g = new_env(4400, 1080, WIN + BAGANATOR_LAZY)
login(g)
lua.execute('ToggleAllBags=function() end')
g.__fire("ADDON_LOADED", "Baganator")
g.__flush()
check("views: a replaced toggle without a real view cannot promote usable",
      g.FFSpan.BaganatorUsable() is False)

lua, g = new_env(4400, 1080, WIN + MULTI_VIEW + '''
function ToggleAllBags() __bump("ToggleAllBags") end
''')
login(g)
check("views: an unready Syndicator no-op never recursively toggles through FFSpan's post-hook",
      calls(g, "ToggleAllBags") < 20 and g.__single.shown is False)

# =============================================================== 11. asynchronous bag geometry ===
# Baganator829 API/Main.lua queues RequestLayoutUpdate with After(0), not a synchronous resize.
# Real observed chrome is 30x81 units, deliberately different from the solver's first estimate.
ASYNC_BAG = WIN + r'''
Baganator = {API = {Constants = {}}}
__loadedAddons.Syndicator = true
BAGANATOR_CURRENT_PROFILE = "DEFAULT"
BAGANATOR_CONFIG = {Profiles = {DEFAULT = {
    bag_view_type="single", current_skin="blizzard", bag_view_width=4, bag_icon_size=37
}}}
__slots = 60
C_Container = {GetContainerNumSlots=function(i) return i==0 and __slots or 0 end}
__bag = __newFrame("Baganator_SingleViewBackpackViewFrameblizzard", UIParent)
__bag.rect={0,0,230,240}
__bag.shown=false
UISpecialFrames={__bag:GetName()}
UIParent.children={__bag}
function ToggleAllBags() __bag.shown=not __bag.shown end
function Baganator.API.RequestLayoutUpdate()
    __bump("RequestLayoutUpdate")
    C_Timer.After(0, function()
        local cfg=BAGANATOR_CONFIG.Profiles.DEFAULT
        local pitch=cfg.bag_icon_size+4
        -- v2.6.5: set __bagMinW to model the real Baganator, which never draws its window
        -- narrower than its header (~387 units on the device, 09-25); a narrower grid then sits
        -- inside that minimum window. 0 keeps the older fixtures' plain grid + chrome window.
        local w=math.max(cfg.bag_view_width*pitch-4+30, __bagMinW or 0)
        local h=math.ceil(__slots/cfg.bag_view_width)*pitch+81
        __bag.rect[3],__bag.rect[4]=w,h
        local p=__bag.points[1]
        if p then __bag:ClearAllPoints(); __bag:SetPoint(unpack(p)) end
        if __bag.hs_OnSizeChanged then __bag.hs_OnSizeChanged(__bag,w,h) end
    end)
end
MinimapCluster=__newFrame("MinimapCluster",UIParent)
MinimapCluster.rect={733/1.40625,560/1.40625,491/1.40625,504/1.40625}
FFScale.HomeSlots=function() return {minimapBottom=520,bottomBarTop=1064,width=491} end
CharacterFrame.rect={0,0,695,485}
'''
lua, g = new_env(4400,1080,ASYNC_BAG)
login(g)
g.__flush()
r=g.__px("Baganator_SingleViewBackpackViewFrameblizzard")
check("async bags: settled width never crosses the lower-screen seam",
      r.x >= 16 and r.x+r.w <= 1224.01, str(dict(r)))
check("async bags: settled height stays below minimap and above bottom strip",
      r.y >= 532-0.01 and r.y+r.h <= 1056.01, str(dict(r)))
check("async bags: layout settles without recurring timer feedback",
      len(list(g.__timers.values())) == 0 and calls(g,"RequestLayoutUpdate") < 8)

lua, g = new_env(4400,1080,ASYNC_BAG + '__slots=16\n__bagMinW=387\n')
login(g)
lua.execute("CharacterFrame:Show()")
g.__flush()
bag=g.__px("Baganator_SingleViewBackpackViewFrameblizzard")
comp=g.__px("CharacterFrame")
check("companion: character clears both resident minimap and bags",
      comp.x+comp.w <= 733-16+0.01 and comp.x+comp.w <= bag.x-16+0.01,
      f"character={dict(comp)} bag={dict(bag)}")
check("companion: small inventories keep native header width instead of two columns",
      bag.w/1.40625 >= 300 and g.BAGANATOR_CONFIG.Profiles.DEFAULT.bag_view_width >= 6,
      f"width={bag.w} cols={g.BAGANATOR_CONFIG.Profiles.DEFAULT.bag_view_width}")
check("companion: negotiated geometry settles without endless grid refresh",
      len(list(g.__timers.values())) == 0 and calls(g,"RequestLayoutUpdate") < 12)

lua, g = new_env(4400,1080,ASYNC_BAG)
login(g)
lua.execute('__bag.hs_OnSizeChanged(__bag)')
check("async bags: real size changes queue one settling pass", len(list(g.__timers.values())) == 1)
lua.execute('__bag.hs_OnSizeChanged(__bag) __bag.hs_OnSizeChanged(__bag)')
check("async bags: repeated size events coalesce", len(list(g.__timers.values())) == 1)
lua.execute('SlashCmdList.FFSPAN("home off")')
g.__flush()
check("async bags: teardown invalidates pending layout work",
      len(list(g.__timers.values())) == 0 and 'applied=no' in g.FFSpan.Home.StatusLine())

lua, g = new_env(1920,1080,ASYNC_BAG)
login(g)
check("async bags: stock single-screen does not configure or hook the bag frame",
      calls(g,"RequestLayoutUpdate") == 0 and g.__bag.hs_OnSizeChanged is None)

lua, g = new_env(4400,1080,ASYNC_BAG + '''
__callbacks={}
EventRegistry={RegisterCallback=function(_,name,fn) __callbacks[name]=fn end}
''')
login(g)
lua.execute('PlayerSpellsFrame:Show() __bag:Hide() PlayerSpellsFrame.tab=2 '
            '__callbacks["PlayerSpellsFrame.TabSet"]()')
g.__flush()
check("spells: explicit Talents tab restores resident bags without changing top routing",
      g.__bag.shown is True and g.__placed("PlayerSpellsFrame").x >= 1240)
lua.execute('__callbacks["PlayerSpellsFrame.TabSet"]() PlayerSpellsFrame:Hide() __bag:Hide()')
g.__flush()
# 2.9.0: before always-open bags this asserted the bags STAYED hidden (the two-press rule). Now a
# hidden Baganator bag always comes back -- through keepOpen, not the stale tab callback.
check("spells: after the window closed a hidden bag comes back (2.9.0 always open), no error",
      g.__bag.shown is True)

# =============================================================== 12. v2.6 layers + tooltip sides =
lua, g = new_env(4400, 1080, ASYNC_BAG)
login(g)
g.__flush()
check("layers: resident bags drop below page windows while home is on", g.__bag.strata == "LOW",
      str(g.__bag.strata))
lua.execute('SlashCmdList.FFSPAN("home off")')
g.__flush()
check("layers: home off gives the bags their own strata back", g.__bag.strata == "MEDIUM",
      str(g.__bag.strata))

# Baganator keeps its window at least as wide as its header (~387 units on the device). The
# measured "chrome" must not grow with every smaller icon, and the floor must be learned.
MINW = ASYNC_BAG + "__bagMinW=387\n"
lua, g = new_env(4400, 1080, MINW)
login(g)
g.__flush()
lua.execute("CharacterFrame:Show()")
g.__flush()
notes = [str(n.d) for n in g.FFSpanDB.home["TestRealm-Fatty"].notes.values()]
chrome = [float(m.split(": ")[1].split(" x ")[0]) for m in notes if "chrome measured" in m]
check("bags: measured chrome never inflates past the real 30 units",
      chrome and max(chrome) <= 31, f"{chrome}")
check("bags: Baganator's minimum width is learned as the header floor",
      any("minimum width measured: 387" in m for m in notes), f"{[m for m in notes if 'minimum' in m]}")
check("bags: a companion does not shrink icons below what the width floor can use",
      g.BAGANATOR_CONFIG.Profiles.DEFAULT.bag_icon_size >= 30,
      f"icon={g.BAGANATOR_CONFIG.Profiles.DEFAULT.bag_icon_size}")
check("bags: the learned minimum is remembered for the next session",
      g.FFSpanDB.bagWindowMinW is not None and abs(g.FFSpanDB.bagWindowMinW - 387) < 1,
      str(g.FFSpanDB.bagWindowMinW))

# v2.6.5 (device 09-25 08:5x): the minimum is a floor on the WINDOW, not a width the grid has to
# reach. 60 slots in a column just over the learned 387.4-unit minimum: the old rule rejected
# every pitch whose whole columns rounded a few units short (icons 37..26 all failed here, so the
# companion floor dropped to 29 or none); the window rule keeps full-size icons.
lua, g = new_env(4400, 1080, 'FFSpanDB = {bagWindowMinW = 387.4}')
login(g)
grid = g.FFSpan.SolveBagGrid(390, 405, 60, 8)
check("bags: a column just over Baganator's minimum keeps full-size icons (was 29 or none)",
      grid is not None and grid.icon >= 33, str(grid and (grid.icon, grid.cols, grid.rows)))
check("bags: ...and the solve reports the window Baganator will actually draw",
      grid is not None and 387.4 <= grid.w <= 390.5, str(grid and grid.w))
check("bags: a column below the minimum still refuses (the window cannot shrink)",
      g.FFSpan.SolveBagGrid(380, 405, 60, 8) is None)
check("bags: the column request is never narrower than the window",
      g.FFSpan.MinBagWidthUnits(405, 16) >= 387.4, str(g.FFSpan.MinBagWidthUnits(405, 16)))

# WoW re-applies an owner's ANCHOR_RIGHT on every refresh, which fires neither OnShow nor
# OnSizeChanged: the side has to be decided on the anchor TYPE, and again at every SetOwner.
TIP = BAGS + r'''
local q = 1080 / 768
local function slot(name, x)
    local f = __newFrame(name, UIParent)
    f.rect = {x / q, (1080 - 835) / q, 48 / q, 48 / q}
    return f
end
__owner, __lowner, __towner = slot("__TipOwner", 1150), slot("__TipOwnerL", 100), slot("__TipOwnerT", 3000)
GameTooltip = __newFrame("GameTooltip", UIParent)
GameTooltip.shown = false
GameTooltip.tw, GameTooltip.th = 353 / q, 163 / q
local function place(tt)
    local o = tt.owner
    if not o then return end
    local l, b, w, h = o:GetRect()
    if tt.anchorType == "ANCHOR_RIGHT" then tt.rect = {l + w, b + h, tt.tw, tt.th}
    elseif tt.anchorType == "ANCHOR_LEFT" then tt.rect = {l - tt.tw, b + h, tt.tw, tt.th} end
end
function GameTooltip:SetOwner(owner, anchor) self.owner, self.anchorType = owner, anchor; place(self) end
function GameTooltip:GetOwner() return self.owner end
function GameTooltip:GetAnchorType() return self.anchorType end
function GameTooltip:SetAnchorType(anchor) self.anchorType = anchor; place(self) end
-- Blizzard's CalculateItemTooltipAnchors: SetOwner(ANCHOR_NONE), then ONE manual point beside
-- the slot, re-run on every refresh while the tooltip stays shown
local baseSetPoint = GameTooltip.SetPoint
function GameTooltip:SetPoint(p, r, rp, x, y)
    if r and r ~= UIParent and p == "BOTTOMLEFT" and rp == "TOPRIGHT" then
        local l, b, w, h = r:GetRect()
        self.points[#self.points + 1] = {p, r, rp, x or 0, y or 0}
        self.rect = {l + w, b + h, self.tw, self.th}
        return
    end
    return baseSetPoint(self, p, r, rp, x, y)
end
function __slotRefresh()
    GameTooltip:SetOwner(__owner, "ANCHOR_NONE")
    GameTooltip:ClearAllPoints()
    GameTooltip:SetPoint("BOTTOMLEFT", __owner, "TOPRIGHT")
end
'''
lua, g = new_env(4400, 1080, TIP)
login(g)
g.__flush()
lua.execute('GameTooltip:SetOwner(__owner, "ANCHOR_RIGHT") GameTooltip:Show()')
g.__flush()
r = g.__px("GameTooltip")
check("tooltip: a right-half bottom-screen owner opens leftward, inside the bottom screen",
      g.GameTooltip.anchorType == "ANCHOR_LEFT" and r["x"] >= 0 and r["x"] + r["w"] <= 1240, str(dict(r)))
lua.execute('GameTooltip:SetOwner(__owner, "ANCHOR_RIGHT")')   # the owner's refresh, still shown
check("tooltip: the owner's refresh re-anchor is flipped again at once",
      g.GameTooltip.anchorType == "ANCHOR_LEFT")
lua.execute('GameTooltip:SetOwner(__lowner, "ANCHOR_RIGHT")')
g.__flush()
check("tooltip: a left-half owner keeps opening right", g.GameTooltip.anchorType == "ANCHOR_RIGHT")
lua.execute('GameTooltip:SetOwner(__towner, "ANCHOR_RIGHT")')
g.__flush()
r = g.__px("GameTooltip")
check("tooltip: a right-half top-screen owner opens left, never into the unseen strip",
      g.GameTooltip.anchorType == "ANCHOR_LEFT" and r["x"] >= 1240 and r["x"] + r["w"] <= 3160, str(dict(r)))
lua, g = new_env(1920, 1080, TIP)
login(g)
lua.execute('GameTooltip:SetOwner(__owner, "ANCHOR_RIGHT")')
check("tooltip: stock single-screen leaves the owner's anchor alone",
      g.GameTooltip.anchorType == "ANCHOR_RIGHT")

# 07:22 flash: the correction must land INSIDE the owner's own call -- never a frame later
lua, g = new_env(4400, 1080, TIP)
login(g)
g.__flush()
lua.execute('GameTooltip:Show() __slotRefresh()')
r = g.__px("GameTooltip")
check("tooltip: a bag slot's manual right-side anchor is corrected inside the same call",
      r["x"] + r["w"] <= 1240 and r["x"] >= 0 and len(list(g.__timers.values())) == 0, str(dict(r)))
for _ in range(3):
    lua.execute('__slotRefresh()')          # the slot's refreshes, tooltip still shown
    r = g.__px("GameTooltip")
    if r["x"] + r["w"] > 1240:
        break
check("tooltip: every refresh re-anchor is corrected before it can be drawn (no flash)",
      r["x"] + r["w"] <= 1240 and len(list(g.__timers.values())) == 0, str(dict(r)))

# =============================================================== 9. Glassy chat width (v2.6) =====
# Glassy's real contract, not a paraphrase of FFSpan: an AceDB profile with a defaults metatable
# (frameWidth 600 is INHERITED, not stored), the options slider's own write-then-dispatch path
# (Modules/ConfigChatPages.lua:192-194), synchronous subscribers that resize the frames
# (MainContainerFrame.lua:41-49, MoverFrame.lua:297-299), and a mover that only moves.
GLASSY = BAGS.replace(
    'HomeSlots=function() return {minimapBottom=300, bottomBarTop=980} end',
    'HomeSlots=function() return {minimapBottom=300, bottomBarTop=980,'
    ' chat={x=29, y=585, w=691, h=495}} end') + r'''
__glassyDefaults = {frameWidth = 600, frameHeight = 250}
GlassyDB = GlassyDB or {profileKeys = {}, profiles = {Default = {}}}
local profile = setmetatable(GlassyDB.profiles.Default, {__index = __glassyDefaults})
Glassy = {db = {profile = profile}, listeners = {}}
function Glassy.db:GetCurrentProfile() return "Default" end
function Glassy:Subscribe(msg, fn)
    self.listeners[msg] = self.listeners[msg] or {}
    table.insert(self.listeners[msg], fn)
end
function Glassy:Dispatch(msg, key)
    __bump("GlassyDispatch")
    for _, fn in ipairs(self.listeners[msg] or {}) do fn(key) end
end
GlassyMoverFrame = __newFrame("GlassyMoverFrame", UIParent)
GlassyMoverFrame.rect = {0, 0, profile.frameWidth, 352}
GlassyFrame = __newFrame("GlassyFrame", UIParent)
GlassyFrame.rect = {0, 0, profile.frameWidth, 352}
function GlassyMoverFrame:SetDragPosition(left, bottom)
    __bump("SetDragPosition")
    self.rect = {left, bottom, self.rect[3], self.rect[4]}
    GlassyFrame.rect = {left, bottom, GlassyFrame.rect[3], GlassyFrame.rect[4]}
end
Glassy:Subscribe("Glassy/UPDATE_CONFIG", function(key)
    if key == "frameWidth" then
        GlassyFrame.rect[3] = Glassy.db.profile.frameWidth
        GlassyMoverFrame.rect[3] = Glassy.db.profile.frameWidth
    end
end)
'''

def raw_width(lua):
    # what is actually STORED -- reading through the profile would fall back to the default
    return lua.eval('rawget(GlassyDB.profiles.Default, "frameWidth")')


# v2.7 (FFScale 1.9: the micro menu is a bar across the bottom, so the chat slot is SHORTER than
# Glassy's envelope). Device numbers: frameHeight 250 (Glassy's default, not stored) inside a
# 352-unit (495 px) envelope, so 102 units of tabs and edit box; the new slot is 371 px.
GLASSY_SHORT = GLASSY.replace("chat={x=29, y=585, w=691, h=495}", "chat={x=29, y=585, w=691, h=371}") + r'''
Glassy:Subscribe("Glassy/UPDATE_CONFIG", function(key)
    if key == "frameHeight" then
        GlassyFrame.rect[4] = Glassy.db.profile.frameHeight + 102
        GlassyMoverFrame.rect[4] = Glassy.db.profile.frameHeight + 102
    end
end)
'''
lua, g = new_env(4400, 1080, GLASSY_SHORT)
login(g)
g.__flush()
g.FFSpan.Home.PlaceAll("next pass")       # the pass straight after a change only waits
g.FFSpan.Home.PlaceAll("settled pass")
env_h = g.GlassyFrame.rect[4] * 1080 / 768
check("glassy height: the 495 px chat is fitted into the 371 px slot through Glassy's own frameHeight",
      lua.eval('rawget(GlassyDB.profiles.Default, "frameHeight")') == 161 and env_h <= 371 + 0.5,
      f"frameHeight={lua.eval('rawget(GlassyDB.profiles.Default, \"frameHeight\")')} env={env_h:.1f}")
before = calls(g, "GlassyDispatch")
g.FFSpan.Home.PlaceAll("repeat")
g.FFSpan.Home.PlaceAll("repeat")
check("glassy height: settled passes never re-dispatch an unchanged height",
      calls(g, "GlassyDispatch") == before, f"{before} -> {calls(g, 'GlassyDispatch')}")
lua.execute('SlashCmdList.FFSPAN("home off")')
g.__flush()
check("glassy height: home off puts the inherited default height back (stored value cleared)",
      lua.eval('rawget(GlassyDB.profiles.Default, "frameHeight")') is None)


lua, g = new_env(4400, 1080, GLASSY)
login(g)
g.__flush()
env_w = g.GlassyFrame.rect[3] * 1080 / 768
check("glassy: the 844 px chat is narrowed into the 691 px slot through Glassy's own setting",
      g.GlassyDB.profiles.Default.frameWidth == 491 and env_w <= 691 and calls(g, "GlassyDispatch") >= 1,
      f"frameWidth={g.GlassyDB.profiles.Default.frameWidth} env={env_w}")
check("glassy: placement verifies the narrowed chat inside the slot", g.FFSpan.GlassyFits() is True)
journal = g.GlassyDB.FFSpanWidthRestore
check("glassy: the original is journalled in GlassyDB, beside the value it describes",
      journal is not None and journal.Default is not None and journal.Default.effectiveWidth == 600)
before = calls(g, "GlassyDispatch")
g.FFSpan.Home.PlaceAll("repeat")
g.FFSpan.Home.PlaceAll("repeat")
check("glassy: repeated placement passes never re-dispatch an unchanged width",
      calls(g, "GlassyDispatch") == before, f"{before} -> {calls(g, 'GlassyDispatch')}")
g.__combat = True
lua.execute("GlassyDB.profiles.Default.frameWidth = 600")   # something else widened it mid-fight
g.FFSpan.Home.PlaceAll("combat pass")
check("glassy: nothing is written or dispatched in combat",
      g.GlassyDB.profiles.Default.frameWidth == 600 and calls(g, "GlassyDispatch") == before)
g.__combat = False
g.FFSpan.Home.PlaceAll("after combat")
check("glassy: the next pass out of combat fits it again",
      g.GlassyDB.profiles.Default.frameWidth == 491)

lua, g = new_env(4400, 1080, GLASSY)
login(g)
g.__flush()
lua.execute('SlashCmdList.FFSPAN("home off")')
g.__flush()
check("glassy: home off puts the INHERITED default back (stored value cleared, not written as 600)",
      raw_width(lua) is None and g.GlassyFrame.rect[3] == 600,
      f"raw={raw_width(lua)} frame={g.GlassyFrame.rect[3]}")

# logout: data only -- the saved file must never carry the dual-screen width
lua, g = new_env(4400, 1080, GLASSY)
login(g)
g.__flush()
before = calls(g, "GlassyDispatch")
g.__fire("PLAYER_LOGOUT")
check("glassy: logout restores the saved width without a dispatch",
      raw_width(lua) is None and calls(g, "GlassyDispatch") == before
      and lua.eval('GlassyDB.FFSpanWidthRestore.Default') is None,
      f"raw={raw_width(lua)} dispatches {before}->{calls(g, 'GlassyDispatch')}")

# a width the player chose by hand while home was on is theirs; restore leaves it alone
lua, g = new_env(4400, 1080, GLASSY)
login(g)
g.__flush()
lua.execute("GlassyDB.profiles.Default.frameWidth = 450 Glassy:Dispatch('Glassy/UPDATE_CONFIG', 'frameWidth')")
lua.execute('SlashCmdList.FFSPAN("home off")')
g.__flush()
check("glassy: a width the player set by hand is never overwritten on restore",
      g.GlassyDB.profiles.Default.frameWidth == 450)

# the stock single-screen client finishes a narrowing left by a session that never logged out
LEFTOVER = ('GlassyDB = {profileKeys = {}, profiles = {Default = {frameWidth = 491}},'
            ' FFSpanWidthRestore = {Default = {rawFrameWidth = "\\1FFSpanRawNil\\1",'
            ' effectiveWidth = 600, appliedWidth = 491}}}\n')
lua, g = new_env(1920, 1080, LEFTOVER + GLASSY)
login(g)
g.__flush()
check("glassy: a stock 1920 login restores a width a crashed dual-screen session left behind",
      raw_width(lua) is None and g.GlassyFrame.rect[3] == 600,
      f"raw={raw_width(lua)} frame={g.GlassyFrame.rect[3]}")

# ================================================================ 2.9.0 always-open bags ===
# 2026-09-25: the bags should just be open all the time. Baganator's bags only
# (every flavor on the Thor); Blizzard's own bags keep the two-press rule (section above).
# Escape's list, modelled as Blizzard runs it: CloseSpecialWindows hides and reports "found".
ESCAPE_LIST = r'''
function CloseSpecialWindows()
    local found
    for _, name in pairs(UISpecialFrames) do
        local f = _G[name]
        if f and f:IsShown() then f:Hide(); found = 1 end
    end
    return found
end
'''
BAG = "Baganator_SingleViewBackpackViewFrameblizzard"
lua, g = new_env(4400, 1080, ASYNC_BAG + ESCAPE_LIST)
login(g)
g.__flush()
check("always-open: the bags are up after login", g.__bag.shown is True)
check("always-open: the resident backpack view is off Escape's list while home is on",
      BAG not in [str(v) for v in g.UISpecialFrames.values()],
      str([str(v) for v in g.UISpecialFrames.values()]))
found = lua.eval("CloseSpecialWindows()")
check("always-open: Escape's close pass neither hides the bags nor counts them as closed",
      g.__bag.shown is True and found is None)
lua.execute("__bag:Hide()")     # the view's own X
check("always-open: hidden by its own X -> still down for this frame", g.__bag.shown is False)
g.__flush()
check("always-open: ...and back on the next frame", g.__bag.shown is True)
lua.execute("ToggleAllBags()")  # the bag key / ring Inventory
g.__flush()
check("always-open: the bag toggle cannot put them away either", g.__bag.shown is True)

g.__combat = True
lua.execute("__bag:Hide()")
g.__flush()
check("always-open: in combat nothing is re-opened (protected item buttons)", g.__bag.shown is False)
g.__combat = False
g.__fire("PLAYER_REGEN_ENABLED")
g.__flush()
check("always-open: ...they come back when combat ends", g.__bag.shown is True)

lua.execute('SlashCmdList.FFSPAN("home off")')
g.__flush()
check("always-open: home off puts the view back on Escape's list",
      [str(v) for v in g.UISpecialFrames.values()].count(BAG) == 1)
lua.execute("__bag:Hide()")
g.__flush()
check("always-open: with home off a hidden bag stays hidden (stock behaviour)", g.__bag.shown is False)
lua.execute('SlashCmdList.FFSPAN("home on")')
g.__flush()
check("always-open: home on again -> off Escape's list again, no duplicates left behind",
      BAG not in [str(v) for v in g.UISpecialFrames.values()])

print()
print(f"{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
