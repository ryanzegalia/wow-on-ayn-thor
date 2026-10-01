-- FFSpan_Layout.lua -- centre-game core, plus the geometry/home contract the other modules and
-- FFScale read. No HUD/deck layout here.
--
-- Supported spanned canvases (h must be 1080; the top panel is always the centred 16:9 box):
--   3160x1080 -> game at x 620..2540, 620 px of UI canvas each side  (centre-game, unchanged)
--   4400x1080 -> game at x 1240..3160, home screen at x 0..1240, x 3160..4400 shown nowhere
-- Everything is derived from the measured canvas, never hard-coded: G = h*16/9, L = (w-G)/2.
local S = _G.FFSpan
if not S then return end
local E = CreateFrame('Frame', 'FFSpanCentreEvents')
S.CentreCore = E
local unpack = unpack or table.unpack
local busy, queued, active, warned, hooked = false, false, false, false, false
local original
local Apply, Request

local SUPPORTED = {[3160] = true, [4400] = true}
local HOME_WIDTH = 4400

-- w,h,gameWidth,gameLeft for a supported spanned canvas; nil otherwise.
local function geometry()
    local w, h = S.GetPhysicalSize()
    if not w or not h or h <= 0 then return nil end
    if not S.IsSpanned() then return nil end
    if h ~= 1080 or not SUPPORTED[w] then return nil end
    local g = h * 16 / 9
    return w, h, g, (w - g) / 2
end
local function exactSpan() return geometry() ~= nil end
S.SupportedSpan = exactSpan

-- ---- contract: -----------------physical px, canvas TOP-LEFT origin, y grows downward ----------
function S.GameRect()
    local w, h, g, l = geometry()
    if not w then return nil end
    return {x = l, y = 0, w = g, h = h}
end
function S.HomeRect()
    local w, h, _, l = geometry()
    if not w or w ~= HOME_WIDTH then return nil end
    return {x = 0, y = 0, w = l, h = h}
end
function S.HomeEligible()
    return geometry() == HOME_WIDTH
end

-- Per-character home state lives in FFSpanDB.home[<realm-character>]; FFSpanDB is account-wide, so
-- the character key is what keeps one character's home session off another's.
local function charKey()
    local ok, name = pcall(function() return UnitName and UnitName('player') end)
    if not ok or not name or name == '' then return nil end
    local ok2, realm = pcall(function() return GetRealmName and GetRealmName() end)
    if ok2 and realm and realm ~= '' then return realm .. '-' .. name end
    return name
end
S.CharacterKey = charKey

-- create=true builds the table chain; otherwise returns nil when nothing is stored yet.
local function homeRecord(create)
    local key = charKey()
    if not key then return nil end
    if type(FFSpanDB) ~= 'table' then
        if not create then return nil end
        FFSpanDB = {}
    end
    if type(FFSpanDB.home) ~= 'table' then
        if not create then return nil end
        FFSpanDB.home = {}
    end
    local rec = FFSpanDB.home[key]
    if type(rec) ~= 'table' then
        if not create then return nil end
        rec = {}
        FFSpanDB.home[key] = rec
    end
    return rec, key
end
S.HomeRecord = homeRecord

function S.HomeEnabled()
    if not S.HomeEligible() then return false end
    local rec = homeRecord(false)
    return not (rec and rec.enabled == false)
end

local listeners = {}
function S.RegisterHomeListener(fn)
    if type(fn) ~= 'function' then return false end
    for _, f in ipairs(listeners) do if f == fn then return true end end
    listeners[#listeners + 1] = fn
    return true
end
function S.HomeListenerCount() return #listeners end
function S.NotifyHomeListeners(enabled, reason)
    for _, fn in ipairs(listeners) do pcall(fn, enabled and true or false, reason) end
end

-- ---- centre-game core (unchanged behaviour at 3160) --------------------------------------------
local function points(f)
    local t = {}
    for i = 1, f:GetNumPoints() do t[i] = {f:GetPoint(i)} end
    return t
end
local function matches(f,i,p,x,y)
    local a,b,c,d,e=f:GetPoint(i)
    return a==p and b==UIParent and c=='BOTTOMLEFT'
        and math.abs((d or 0)-x)<.001 and math.abs((e or 0)-y)<.001
end
local function restore()
    if not active then return end
    WorldFrame:ClearAllPoints()
    for _,p in ipairs(original or {}) do WorldFrame:SetPoint(unpack(p)) end
    active=false; E.applied=false
end
local function work()
    if not exactSpan() or _G.Offhand then
        if exactSpan() and _G.Offhand and not warned then
            warned=true
            print('FFSpan centre-game: remove Offhand from active AddOns and reload.')
        end
        restore(); return
    end
    if not original then original=points(WorldFrame) end
    if not hooked then
        hooked=true
        for _,key in ipairs({'SetPoint','SetAllPoints','ClearAllPoints'}) do
            hooksecurefunc(WorldFrame,key,function()
                if active and not busy then Request() end
            end)
        end
    end
    local _,h,g,l=geometry()
    local q=WorldFrame:GetEffectiveScale()*h/768
    if not q or q<=0 then return end
    local x1,x2,top=l/q,(l+g)/q,h/q
    active=true
    if WorldFrame:GetNumPoints()~=2
        or not matches(WorldFrame,1,'BOTTOMLEFT',x1,0)
        or not matches(WorldFrame,2,'TOPRIGHT',x2,top) then
        WorldFrame:ClearAllPoints()
        WorldFrame:SetPoint('BOTTOMLEFT',UIParent,'BOTTOMLEFT',x1,0)
        WorldFrame:SetPoint('TOPRIGHT',UIParent,'BOTTOMLEFT',x2,top)
    end
    E.applied=true
end
Apply=function()
    if InCombatLockdown() then return end
    busy=true
    local ok,err=pcall(work)
    busy=false
    if not ok then
        E.applied=false
        print('FFSpan centre-game failed: '..tostring(err))
    end
end
Request=function()
    if busy or queued then return end
    if not exactSpan() and not active then return end
    if InCombatLockdown() then return end -- regen always retries
    queued=true
    C_Timer.After(0,function() queued=false;Apply() end)
end
E.Apply=Apply -- mock-test entry; same combat and geometry gates
for _,event in ipairs({'PLAYER_LOGIN','PLAYER_ENTERING_WORLD','ADDON_LOADED',
    'DISPLAY_SIZE_CHANGED','UI_SCALE_CHANGED','PLAYER_REGEN_ENABLED'}) do
    E:RegisterEvent(event)
end
E:SetScript('OnEvent',Request)
