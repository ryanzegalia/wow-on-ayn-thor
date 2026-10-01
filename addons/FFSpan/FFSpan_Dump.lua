-- FFSpan_Dump.lua -- bounded, read-only frame geometry diagnostics.
local S = _G.FFSpan
if not S then return end
local D = CreateFrame('Frame', 'FFSpanDumpEvents')
local unpack = unpack or table.unpack
local MAX_ROWS, MAX_VISITS, MAX_DEPTH, MAX_POINTS = 400,800,6,16
local function safe(fn,...)
    local ok,a,b,c,d,e=pcall(fn,...)
    if ok then return a,b,c,d,e end
end
local function global(name)
    return safe(function() return _G[name] end)
end
local function str(value)
    return safe(function()
        if value==nil then return nil end
        return tostring(value):sub(1,240)
    end)
end
local function num(value)
    return safe(function()
        if type(value)~='number' or value~=value
            or value==math.huge or value==-math.huge then return nil end
        return tonumber(string.format('%.6f',value))
    end)
end
local function boolean(value)
    return safe(function()
        if value==nil then return nil end
        if value then return true else return false end
    end)
end
local function method(f,key,errors,...)
    local args={...}
    local ok,a,b,c,d,e=pcall(function()
        local fn=f and f[key]
        if type(fn)~='function' then return nil end
        return fn(f,unpack(args))
    end)
    if ok then return a,b,c,d,e end
    if errors then errors[#errors+1]=key end
end
local function field(f,key)
    return safe(function() return f[key] end)
end
local function forbidden(f)
    local ok,value=pcall(function()
        if f.IsForbidden then return f:IsForbidden() end
        return false
    end)
    if not ok then return true end
    return boolean(value)~=false
end
local function frameName(f)
    if type(f)=='string' then return str(f) end
    if not f then return nil end
    if forbidden(f) then return '<forbidden>' end
    return str(method(f,'GetName')) or '<anonymous>'
end
-- Both dump gates accept every geometry the layout core supports (3160 centre-game and 4400 home);
-- S.SupportedSpan is the single source of truth so the gates cannot drift from FFSpan_Layout again.
local function exactSpan()
    return safe(function() return S.SupportedSpan and S.SupportedSpan() end)==true
end
-- Which screen a frame's envelope is supposed to land on, and whether it actually does. `home`
-- exists only at 4400; at 3160 every frame is expected on the game screen or the side gutters.
local HOME_FRAMES={MinimapCluster=true,Minimap=true,ObjectiveTrackerFrame=true,
    MicroButtonAndBagsBar=true,BagsBar=true,MicroMenu=true,MicroMenuContainer=true,
    MainMenuBarBackpackButton=true,CharacterMicroButton=true,DurabilityFrame=true,
    StatusTrackingBarManager=true,MainStatusTrackingBarContainer=true,
    ContainerFrameCombinedBags=true,GeneralDockManager=true,GlassyFrame=true,
    WorldMapFrame=true,CharacterFrame=true,MerchantFrame=true,GameMenuFrame=true,
    LootFrame=false}
local TOP_FRAMES={WorldFrame=true,BuffFrame=true,DebuffFrame=true,GameTooltip=true,
    GameTooltipDefaultContainer=true,BossTargetFrameContainer=true,CompactArenaFrame=true,
    PlayerFrame=true,TargetFrame=true,TargetFrameToT=true,FocusFrame=true,PetFrame=true,
    PartyFrame=true,CompactRaidFrameManager=true,CompactRaidFrameContainer=true,
    UIErrorsFrame=true,RaidWarningFrame=true,RaidBossEmoteFrame=true,ZoneTextFrame=true,
    TalkingHeadFrame=true,ImmersionFrame=true,QuestFrame=true,GossipFrame=true,
    StaticPopup1=true,GroupLootContainer=true,ExtraAbilityContainer=true,
    MainMenuBarVehicleLeaveButton=true,VehicleSeatIndicator=true,LossOfControlFrame=true,
    PlayerCastingBarFrame=true,CastingBarFrame=true,EncounterTimeline=true,
    MirrorTimerContainer=true,EssentialCooldownViewer=true,
    ConsolePortBarManager=true,ConsolePortBarCluster=true,ConsolePortToolbar=true,
    ConsolePortCrosshair=true}
for i=1,13 do HOME_FRAMES['ContainerFrame'..i]=true end
-- v2.2: the managed WINDOWS come from FFSpan_Home's own policy table (S.ManagedIntent),
-- so the dump and the placement pass can never disagree about where a window belongs -- and the
-- spellbook/talents split is read live rather than guessed. A named frame with no mapping at all
-- is reported as 'unknown', never silently as a pass.
local function intendedScreen(name,homeActive,managed)
    if not name then return nil end
    if managed and managed[name] then
        if not homeActive then return 'top' end   -- off home every window belongs to the game rect
        return managed[name]
    end
    if homeActive and HOME_FRAMES[name] then return 'home' end
    if TOP_FRAMES[name] then return 'top' end
    return nil
end
-- containment on ALL FOUR edges: a window above or below the panel, or with a negative left, is
-- not "on" that screen just because its right edge happens to fall inside it.
local function within(r,x0,x1,y0,y1)
    if not r then return false end
    return r.x>=x0-0.5 and (r.x+r.width)<=x1+0.5 and r.y>=y0-0.5 and (r.y+r.height)<=y1+0.5
end
local function capture(reason)
    local pw,ph=S.GetPhysicalSize()
    local game=safe(function() return S.GameRect and S.GameRect() end)
    local home=safe(function() return S.HomeRect and S.HomeRect() end)
    local out={version=2,reason=reason,
        capturedAt=safe(date,'%Y-%m-%d %H:%M:%S'),
        physicalWidth=pw,physicalHeight=ph,
        gameRect=game,homeRect=home,
        uiParentEffectiveScale=num(method(UIParent,'GetEffectiveScale')),
        limits={rows=MAX_ROWS,visits=MAX_VISITS,depth=MAX_DEPTH,anchors=MAX_POINTS},
        frames={},missingNamed={},forbiddenSkipped=0,visited=0,truncated=false,
        screenViolations={},unmapped={},
        coordinateOrigin='physical canvas top-left',
        projectID=num(global('WOW_PROJECT_ID')),
        mainlineProjectID=num(global('WOW_PROJECT_MAINLINE'))}
    local buildVersion, buildNumber, buildDate, interfaceVersion=safe(_G.GetBuildInfo)
    out.clientBuild={version=str(buildVersion),build=str(buildNumber),date=str(buildDate),interface=num(interfaceVersion)}
    local offhand=global('Offhand')
    out.offhandLoaded=offhand~=nil
    out.offhandEnabled=boolean(safe(function() return offhand and offhand.db and offhand.db.enabled end))
    out.centreGameApplied=boolean(safe(function() return S.CentreCore and S.CentreCore.applied end))
    out.homeEligible=boolean(safe(function() return S.HomeEligible and S.HomeEligible() end))
    out.homeEnabled=boolean(safe(function() return S.HomeEnabled and S.HomeEnabled() end))
    out.homeStatus=str(safe(function() return S.Home and S.Home.StatusLine and S.Home.StatusLine() end))
    out.editModeLayout=str(safe(function()
        local fs=global('FFScale')
        return fs and fs.ActiveLayoutName and fs.ActiveLayoutName()
    end))
    -- v2.2: "home" expectations only apply when home is actually ENABLED, not merely
    -- eligible -- with home off at 4400 every window belongs to the game rect.
    local homeActive=out.homeEnabled==true
    local managedIntent=safe(function() return S.ManagedIntent and S.ManagedIntent() end)
    out.homeActiveForIntent=homeActive
    out.panelHook=str(safe(function() return S.Home and S.Home.PanelHook and S.Home.PanelHook() end))
    out.layoutConfirmed=boolean(safe(function()
        return S.Home and S.Home.LayoutConfirmed and S.Home.LayoutConfirmed() end))
    -- v2.2.1: an estimated column is an APPROVED degraded mode, not a measured one --
    -- a capture has to say which, or zero violations reads as more than it is.
    out.layoutSlotSource=str(safe(function()
        return S.Home and S.Home.LayoutSource and S.Home.LayoutSource() end))
    out.layoutDegraded=boolean(safe(function()
        return S.Home and S.Home.LayoutDegraded and S.Home.LayoutDegraded() end))
    -- v2.3: the windows FFSpan deliberately did NOT place because they refuse SetScale and
    -- do not fit their class area, plus the negotiated bag scale.
    -- v2.4: frames whose scale readback still disagreed after Blizzard's checkFit
    -- pass AND FFSpan's re-apply -- a diagnostic, not a placement decision. Plus which hook caught the
    -- rescale, and any transient (tooltip/menu/flyout) currently straddling a panel edge.
    out.scaleRefused=safe(function()
        return S.Home and S.Home.ScaleRefused and S.Home.ScaleRefused() end)
    -- ...and who most likely pinned each one, so the evidence is in the capture
    out.positionOwners=safe(function()
        return S.Home and S.Home.PositionOwners and S.Home.PositionOwners() end)
    out.scaleOwners=safe(function()
        return S.Home and S.Home.ScaleOwners and S.Home.ScaleOwners() end)
    out.baganator=str(safe(function()
        if not (S.BaganatorUsable and S.BaganatorUsable()) then
            return 'unusable: ' .. tostring(S.BaganatorWhyNot and S.BaganatorWhyNot() or 'absent')
        end
        return 'usable'
    end))
    out.scaleHook=str(safe(function()
        return S.Home and S.Home.ScaleHook and S.Home.ScaleHook() end))
    out.transientOffPanel=safe(function() return S.TransientOffPanel and S.TransientOffPanel() end)
    out.transientOffPanelCount=num(safe(function()
        local t = S.TransientOffPanel and S.TransientOffPanel()
        return t and #t or 0 end))
    out.bagScale=num(safe(function()
        return S.Home and S.Home.BagScale and S.Home.BagScale() end))
    -- v2.6.5: who holds the micro buttons (FFSpan_Micro.lua): blizzard / consoleport / mixed
    out.microMenu=safe(function() return S.MicroMenu and S.MicroMenu.Status and S.MicroMenu.Status() end)
    out.microMenuUnits=safe(function() return S.MicroMenuUnits and S.MicroMenuUnits() end)
    local rowByFrame,walked={},{}
    local function add(f,source,isSystem)
        if not f then return end
        if forbidden(f) then out.forbiddenSkipped=out.forbiddenSkipped+1;return end
        local row=rowByFrame[f]
        if not row then
            if #out.frames>=MAX_ROWS then out.truncated=true;return end
            row={name=frameName(f),sources={},anchors={},readErrors={}}
            rowByFrame[f]=row;out.frames[#out.frames+1]=row
            row.id=#out.frames
            local er=row.readErrors
            row.shown=boolean(method(f,'IsShown',er))
            row.visible=boolean(method(f,'IsVisible',er))
            row.alpha=num(method(f,'GetAlpha',er))
            row.effectiveAlpha=num(method(f,'GetEffectiveAlpha',er))
            row.strata=str(method(f,'GetFrameStrata',er))
            row.level=num(method(f,'GetFrameLevel',er))
            row.effectiveScale=num(method(f,'GetEffectiveScale',er))
            row.parent=frameName(method(f,'GetParent',er))
            local left,bottom,width,height=method(f,'GetRect',er)
            local rootRect=safe(function()
                local l,b,w,h=num(left),num(bottom),num(width),num(height)
                if not(l and b and w and h and row.effectiveScale) then return nil end
                local q=row.effectiveScale*ph/768
                return {x=num(l*q),y=num(ph-(b+h)*q),width=num(w*q),height=num(h*q)}
            end)
            -- v2.2: containment is judged on the VISIBLE ENVELOPE -- hanging tabs,
            -- portraits and side panels are what actually cross a screen edge. FFSpan_Home's
            -- envelope helper is the same one placement uses, so the two cannot disagree.
            local env=safe(function()
                local e=S.EnvelopePx and S.EnvelopePx(f)
                if type(e)~='table' then return nil end
                local x,y,w,h=num(e.x),num(e.y),num(e.w),num(e.h)
                if not(x and y and w and h and w>0 and h>0) then return nil end
                return {x=x,y=y,width=w,height=h}
            end)
            row.rect=rootRect
            row.envelope=env
            row.envelopeSource=env and 'visible-envelope' or (rootRect and 'root-rect' or nil)
            if not rootRect and not env then er[#er+1]='physicalRectUnavailable' end
            row.protected=boolean(method(f,'IsProtected',er))
            -- Intended vs actual screen. A hidden/unmeasurable/unmapped row is UNKNOWN, never a pass.
            row.intendedScreen=intendedScreen(row.name,homeActive,managedIntent)
            if row.name and not row.intendedScreen then
                row.intendedScreen='unknown'
                if #out.unmapped<MAX_ROWS then out.unmapped[#out.unmapped+1]=row.name end
            end
            local box=env or rootRect
            if box then
                local gl=game and game.x or 0
                local gr=game and (game.x+game.w) or pw
                if row.visible==false then row.actualScreen='hidden'
                elseif home and within(box,0,home.w,0,ph) then row.actualScreen='home'
                elseif within(box,gl,gr,0,ph) then row.actualScreen='top'
                elseif within(box,gr,pw,0,ph) then row.actualScreen='unshown'
                else row.actualScreen='split' end
                if row.visible~=false and row.intendedScreen and row.intendedScreen~='unknown'
                    and row.actualScreen~=row.intendedScreen then
                    row.screenViolation=true
                    if #out.screenViolations<MAX_ROWS then
                        out.screenViolations[#out.screenViolations+1]={name=row.name,
                            intended=row.intendedScreen,actual=row.actualScreen,
                            x=box.x,y=box.y,width=box.width,height=box.height,
                            measured=row.envelopeSource}
                    end
                end
            else
                row.actualScreen='unknown'
            end
            local count=num(method(f,'GetNumPoints',er)) or 0
            count=math.max(0,math.floor(count))
            row.anchorsTruncated=count>MAX_POINTS
            for i=1,math.min(count,MAX_POINTS) do
                local p,r,rp,x,y=method(f,'GetPoint',er,i)
                row.anchors[#row.anchors+1]={point=str(p),relativeTo=frameName(r),
                    relativePoint=str(rp),x=num(x),y=num(y)}
            end
        end
        row.sources[source]=true
        if isSystem then
            row.system=num(field(f,'system'))
            row.systemIndex=num(field(f,'systemIndex'))
            row.inDefaultPosition=boolean(method(f,'IsInDefaultPosition',row.readErrors))
            row.editModeSystem=true
        end
        return row
    end
    local manager=global('EditModeManagerFrame')
    local systems=manager and field(manager,'registeredSystemFrames')
    if type(systems)=='table' then
        local count=safe(function() return #systems end) or 0
        out.registeredSystemCount=count
        if count>MAX_ROWS then out.truncated=true end
        for i=1,math.min(count,MAX_ROWS) do
            add(safe(function() return systems[i] end),'editMode',true)
        end
    end
    local names={
        'UIParent','WorldFrame','ConsolePortBarManager','ConsolePortBarCluster','ConsolePortToolbar',
        'ConsolePortCrosshair','MinimapCluster','Minimap','ObjectiveTrackerFrame',
        'BuffFrame','DebuffFrame','ExternalDefensivesFrame','GlassyFrame','GlassyMoverFrame',
        'GeneralDockManager','MicroButtonAndBagsBar','BagsBar','MicroMenu','MicroMenuContainer',
        'MainMenuBarBackpackButton','CharacterMicroButton','ContainerFrameCombinedBags',
        'PlayerFrame','TargetFrame','TargetFrameToT','FocusFrame','PetFrame','PartyFrame',
        'PartyMemberFrame1','CompactPartyFrame','CompactRaidFrameManager','CompactRaidFrameContainer',
        'BossTargetFrameContainer','CompactArenaFrame','PlayerCastingBarFrame','CastingBarFrame',
        'UIErrorsFrame','RaidWarningFrame','RaidBossEmoteFrame','CriticalEncounterWarnings',
        'MediumEncounterWarnings','MinorEncounterWarnings','GameTooltip','GameTooltipDefaultContainer',
        'WorldMapFrame','CharacterFrame','LootFrame','GameMenuFrame','StaticPopup1',
        'QuestFrame','GossipFrame','ImmersionFrame','MerchantFrame','TalkingHeadFrame',
        'LossOfControlFrame','StatusTrackingBarManager','MainStatusTrackingBarContainer',
        'EssentialCooldownViewer','ExtraAbilityContainer','MainMenuBarVehicleLeaveButton',
        'DurabilityFrame','VehicleSeatIndicator','EncounterTimeline','MirrorTimerContainer',
        'NamePlateDriverFrame', -- UNVERIFIED optional candidate, not assumed present.
        -- home-screen additions: every window FFSpan_Home manages,
        -- plus the frames that are intended-top but anchored off a UIParent edge.
        'FFSpanMarker','ZoneTextFrame','SubZoneTextFrame','GroupLootContainer',
        'StaticPopup2','StaticPopup3','StaticPopup4',
        'MinimapBackdrop','MinimapZoneTextButton','MinimapCompassTexture',
        'ExpansionLandingPageMinimapButton','QueueStatusFrame','QueueStatusButton',
        'ReadyCheckFrame','AchievementFrame','CollectionsJournal','CalendarFrame',
        'SettingsPanel','ProfessionsBookFrame','PlayerSpellsFrame','MailFrame','OpenMailFrame',
        'BankFrame','TradeFrame','AuctionHouseFrame','ProfessionsFrame','ItemSocketingFrame',
        'WardrobeFrame','ObjectiveTrackerBlocksFrame','GlassyChatFrame','GlassyDock',
    }
    local chatCount=num(global('NUM_CHAT_WINDOWS')) or 10
    for i=1,math.min(50,math.max(1,math.floor(chatCount))) do
        names[#names+1]='ChatFrame'..i
        names[#names+1]='ChatFrame'..i..'EditBox'
    end
    for i=1,13 do names[#names+1]='ContainerFrame'..i end
    for _,name in ipairs(names) do
        local f=global(name)
        if f then add(f,'named',false) else out.missingNamed[#out.missingNamed+1]=name end
    end
    local queue={}
    for _,name in ipairs({'ConsolePortBarManager','UIParent','WorldFrame'}) do
        local f=global(name)
        if f then queue[#queue+1]={f=f,depth=0} end
    end
    local cursor=1
    while cursor<=#queue and out.visited<MAX_VISITS and #out.frames<MAX_ROWS do
        local item=queue[cursor];cursor=cursor+1
        local f=item.f
        if not walked[f] then
            walked[f]=true;out.visited=out.visited+1
            if not forbidden(f) then
                local name=str(method(f,'GetName'))
                local visible=boolean(method(f,'IsVisible'))
                if name and visible then add(f,'visibleDescendant',false) end
                if item.depth<MAX_DEPTH then
                    local children=safe(function() return {f:GetChildren()} end)
                    if children then
                        local available=math.max(0,MAX_VISITS-#queue)
                        if #children>available then out.truncated=true end
                        for i=1,math.min(#children,available) do
                            queue[#queue+1]={f=children[i],depth=item.depth+1}
                        end
                    end
                else out.depthLimited=true end
            else out.forbiddenSkipped=out.forbiddenSkipped+1 end
        end
    end
    if cursor<=#queue then out.truncated=true end
    out.frameCount=#out.frames
    out.violationCount=#out.screenViolations
    out.unmappedCount=#out.unmapped
    return out
end
-- Snapshots are kept by label so one play session can capture several UI states for layout work:
-- /ffspan dump            -> FFSpanDB.dumps.manual
-- /ffspan dump bags       -> FFSpanDB.dumps.bags   (label: letters/digits/_-, max 24 chars)
-- logout / reload         -> FFSpanDB.dumps.logout
-- At most MAX_LABELS labels; the oldest label is dropped first. SavedVariables reach disk on a
-- clean logout or /reload, so take the manual snapshots, then log out or /reload.
local MAX_LABELS = 12
local function dump(reason, label)
    label = label or reason
    local manual = reason=='manual'
    if not exactSpan() then
        if manual then safe(print,'FFSpan dump requires a supported span canvas (3160x1080 or 4400x1080).') end
        return false
    end
    local ok,result=pcall(capture,reason)
    if not ok or type(result)~='table' then
        if manual then safe(print,'FFSpan dump failed; previous snapshot retained.') end
        return false
    end
    result.label=label
    local saved=pcall(function()
        if type(FFSpanDB)~='table' then FFSpanDB={} end
        if type(FFSpanDB.dumps)~='table' then FFSpanDB.dumps={} end
        if type(FFSpanDB.dumpOrder)~='table' then FFSpanDB.dumpOrder={} end
        FFSpanDB.dump=nil -- v1 single slot, superseded by dumps[label]
        local order=FFSpanDB.dumpOrder
        for i=#order,1,-1 do if order[i]==label then table.remove(order,i) end end
        order[#order+1]=label
        while #order>MAX_LABELS do FFSpanDB.dumps[table.remove(order,1)]=nil end
        FFSpanDB.dumps[label]=result
    end)
    if saved and manual then
        safe(print,('FFSpan dump "%s": %d frames, %d intended-screen violation(s)%s. /reload or log out to save it.')
            :format(label,result.frameCount,result.violationCount or 0,
                result.truncated and ' (bounded/truncated)' or ''))
    end
    return saved
end
S.DumpFrames=dump

-- Automatic snapshots for layout work: a controller player should not have to type commands.
-- Each label is captured once per session, shortly after the state appears (layout settles first);
-- nothing here moves or shows anything. Labels: base (15 s after entering the world, after FFScale's
-- +12 s pass), bags, map, char, menu (Game Menu), target, combat, group.
local autoDone={}
local function auto(label,delay)
    if autoDone[label] or not exactSpan() then return end
    autoDone[label]=true
    safe(C_Timer.After,delay or 0.5,function()
        -- 2026-09-25: automatic captures stay quiet in chat -- the cyan "[FFSpan] captured
        -- layout: X" line read as developer clutter at ordinary login/menu use. The capture
        -- itself (SavedVariables write) and any failure/warning inside dump() are unchanged;
        -- manual /ffspan dump still reports (dump()'s own `manual` branch, untouched).
        dump('auto',label)
    end)
end
local hookedShow={}
local function onShow(name,label)
    local f=global(name)
    if not f or hookedShow[name] or forbidden(f) then return end
    if safe(function() f:HookScript('OnShow',function() auto(label) end) return true end) then
        hookedShow[name]=true
    end
end
-- v2.6.3 DIAGNOSTIC, read-only. Classic 09-25 07:38-07:47: opening the already-maximized map
-- raised Frame:SetScale(): Scale must be > 0 from MapCanvas_ScrollContainerMixin.lua:624. Its
-- CreateZoomLevels (:425-429) takes min(ScrollContainer width, height / art size), so the
-- ScrollContainer measured ZERO inside Cata/Blizzard_WorldMap.lua SynchronizeDisplayState :66,
-- reached from Wrath/QuestLogOwnerMixin.lua SetQuestLogPanelShown(false) :150 <- SetDisplayState(2)
-- :110 (WorldMapMixin:OnShow :328-335 re-syncs a maximized map on every open). Whether FFSpan's
-- placement or Blizzard's own path leaves it at zero is not decidable from the source, so record
-- the geometry at the last points that can be observed before :66 -- QuestLog OnHide (:147, before
-- :150), MaximizeUIPanel / RestoreUIPanelArea (:36 / :63), both OnSizeChanged scripts -- and
-- again one frame later. 'canvas ok' rows are OnFrameSizeChanged calls that did NOT error.
-- v2.6.4: OPT-IN (/ffspan mapprobe on|off, default off). Its rect reads resolve the very rects
-- whose staleness caused the errors (see mapMax.resolve in FFSpan_Home.lua), so a probe that is
-- always on would hide a regression instead of recording it.
local MAX_PROBE=64
local probeHooked={}
-- two decimals, trailing zeros dropped: the same text on WoW's Lua 5.1 and the test VM
local function n2(v)
    local x=num(v)
    if x==nil then return 'nil' end
    return (('%.2f'):format(x):gsub('%.?0+$',''))
end
local function pointsText(f)
    local n=num(method(f,'GetNumPoints')) or 0
    local out={}
    for i=1,math.min(n,4) do
        local p,rel,rp,x,y=method(f,'GetPoint',nil,i)
        out[#out+1]=('%s>%s.%s %s,%s'):format(str(p) or '?',frameName(rel) or 'nil',str(rp) or '?',
            n2(x),n2(y))
    end
    return n2(n)..' '..table.concat(out,'; ')
end
local function rectText(f)
    local l,b,w,h=method(f,'GetRect')
    if l==nil then return 'rect=nil' end
    return ('rect=%s,%s %sx%s'):format(n2(l),n2(b),n2(w),n2(h))
end
local function geometry(f)
    if not f then return 'absent' end
    local w,h=method(f,'GetSize')
    return ('%s | %sx%s s%s e%s %s'):format(pointsText(f),n2(w),n2(h),
        n2(method(f,'GetScale')),n2(method(f,'GetEffectiveScale')),rectText(f))
end
local function probeMap(event)
    if not (type(FFSpanDB)=='table' and FFSpanDB.mapProbeOn==true) then return end
    if not exactSpan() then return end
    local map=global('WorldMapFrame')
    if not map then return end
    local sc,ql,bo=field(map,'ScrollContainer'),field(map,'QuestLog'),field(map,'BlackoutFrame')
    local child=sc and field(sc,'Child')
    local zl=sc and field(sc,'zoomLevels')
    local row={
        t=safe(date,'%H:%M:%S'), s=num(safe(GetTime)), ev=str(event),
        placing=boolean(safe(function() return S.HomePlacing and S.HomePlacing() end)),
        home=boolean(safe(function() return S.HomeEligible and S.HomeEligible() end)),
        max=boolean(method(map,'IsMaximized')), shown=boolean(method(map,'IsShown')),
        ql=boolean(ql and method(ql,'IsShown')),
        map=str(geometry(map)), sc=str(sc and geometry(sc)),
        child=child and str(('left=%s top=%s scale=%s'):format(n2(method(child,'GetLeft')),
            n2(method(child,'GetTop')),n2(method(child,'GetScale')))) or nil,
        base=num(sc and field(sc,'baseScale')),
        z1=num(safe(function() return zl[1].scale end)),
        blackout=bo and str(pointsText(bo)) or nil,
    }
    if type(FFSpanDB)~='table' then FFSpanDB={} end
    if type(FFSpanDB.mapProbe)~='table' then FFSpanDB.mapProbe={} end
    local rows=FFSpanDB.mapProbe
    rows[#rows+1]=row
    while #rows>MAX_PROBE do table.remove(rows,1) end
end
local function probeNow(event)
    safe(probeMap,event)
    safe(C_Timer.After,0,function() safe(probeMap,event..' +1') end)
end
local function hookMapProbe()
    local map=global('WorldMapFrame')
    if not map or forbidden(map) then return end
    local function once(key,install)
        if probeHooked[key] then return end
        if safe(function() install() return true end) then probeHooked[key]=true end
    end
    for _,name in ipairs({'MaximizeUIPanel','RestoreUIPanelArea'}) do
        if type(global(name))=='function' then
            once(name,function()
                hooksecurefunc(name,function(frame) if frame==map then probeNow(name) end end)
            end)
        end
    end
    once('map:size',function() map:HookScript('OnSizeChanged',function() probeNow('map size') end) end)
    local sc,ql=field(map,'ScrollContainer'),field(map,'QuestLog')
    if sc then
        once('sc:size',function() sc:HookScript('OnSizeChanged',function() probeNow('sc size') end) end)
    end
    if ql then
        once('ql:hide',function() ql:HookScript('OnHide',function() probeNow('questlog hide') end) end)
        once('ql:show',function() ql:HookScript('OnShow',function() probeNow('questlog show') end) end)
    end
    if type(field(map,'OnFrameSizeChanged'))=='function' then
        once('canvas',function()
            hooksecurefunc(map,'OnFrameSizeChanged',function() safe(probeMap,'canvas ok') end)
        end)
    end
end
S.ProbeMap=probeMap
local function hookShows()
    onShow('ContainerFrameCombinedBags','bags')
    onShow('ContainerFrame1','bags')
    onShow('WorldMapFrame','map')
    onShow('CharacterFrame','char')
    onShow('GameMenuFrame','menu')
    safe(hookMapProbe)
end
D:RegisterEvent('PLAYER_LOGOUT')
D:RegisterEvent('PLAYER_ENTERING_WORLD')
D:RegisterEvent('ADDON_LOADED') -- WorldMapFrame etc. can be load-on-demand
D:RegisterEvent('PLAYER_TARGET_CHANGED')
D:RegisterEvent('PLAYER_REGEN_DISABLED')
D:RegisterEvent('GROUP_ROSTER_UPDATE')
D:RegisterEvent('ADDON_ACTION_BLOCKED')
D:RegisterEvent('ADDON_ACTION_FORBIDDEN')
-- Observe the client's protection verdict, never suppress or retry it. The popup names an addon,
-- not the blocked function; save that function so a real failure is not diagnosed from a guess.
local function recordBlocked(event, addon, action)
    if not exactSpan() then return end
    if type(FFSpanDB)~='table' then FFSpanDB={} end
    if type(FFSpanDB.protectionEvents)~='table' then FFSpanDB.protectionEvents={} end
    local rows=FFSpanDB.protectionEvents
    rows[#rows+1]={event=event,addon=str(addon),action=str(action),
        at=safe(date,'%Y-%m-%d %H:%M:%S'),projectID=num(global('WOW_PROJECT_ID'))}
    while #rows>24 do table.remove(rows,1) end
end
D:SetScript('OnEvent',function(_,event,addon,action)
    if event=='ADDON_ACTION_BLOCKED' or event=='ADDON_ACTION_FORBIDDEN' then
        safe(recordBlocked,event,addon,action)
    elseif event=='PLAYER_LOGOUT' then dump('logout')
    elseif event=='PLAYER_ENTERING_WORLD' then hookShows(); auto('base',15)
    elseif event=='ADDON_LOADED' then hookShows()
    elseif event=='PLAYER_TARGET_CHANGED' then
        if safe(UnitExists,'target') then auto('target',1) end
    elseif event=='PLAYER_REGEN_DISABLED' then auto('combat',2)
    elseif event=='GROUP_ROSTER_UPDATE' then
        if safe(IsInGroup) then auto('group',2) end
    end
end)
local prior=SlashCmdList['FFSPAN']
SlashCmdList['FFSPAN']=function(message)
    local probe=safe(function()
        return type(message)=='string' and message:match('^%s*mapprobe%s+(%a+)%s*$')
    end)
    if probe=='on' or probe=='off' then
        if type(FFSpanDB)~='table' then FFSpanDB={} end
        FFSpanDB.mapProbeOn=(probe=='on') or nil
        safe(print,'FFSpan: map probe '..probe..' (rows in FFSpanDB.mapProbe, written at logout).')
        return
    end
    local label=safe(function()
        if type(message)~='string' then return nil end
        local rest=message:match('^%s*dump%s*(.-)%s*$')
        if not rest then return nil end
        if rest=='' then return 'manual' end
        return rest:match('^[%w_%-]+$') and rest:sub(1,24) or false
    end)
    if label then dump('manual',label)
    elseif label==false then safe(print,'FFSpan: dump label must be letters, digits, _ or - (e.g. /ffspan dump bags).')
    elseif prior then prior(message) end
end
