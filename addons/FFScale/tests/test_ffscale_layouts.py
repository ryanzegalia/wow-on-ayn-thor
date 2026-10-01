#!/usr/bin/env python3
"""
CHARACTERIZATION tests for FFScale. Captured against v1.5.1 BEFORE the home-layout work and
frozen as golden text in tests/golden/. Every single-screen path (1920 retail, 3160 retail,
Classic) must keep producing byte-identical output afterwards: the same SaveLayouts payload,
the same SetActiveLayout index, the same bindings calls, the same timer schedule.

Run:               python test_ffscale_layouts.py
Re-record golden:  python test_ffscale_layouts.py --update      (only when a change is intended)
"""
import sys

from ffscale_harness import compare_golden, login, new_env, record

UPDATE = "--update" in sys.argv

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not cond else ""))


def golden(case, lua, g):
    ok, detail = compare_golden(case, record(lua, g), UPDATE)
    check(f"golden: {case}", ok, detail)


# --- 1920x1080 retail login -----------------------------------------------------------------
lua, g = new_env(1920, 1080)
login(g)
golden("retail_1920_login", lua, g)

check("retail 1920: exactly one SaveLayouts", len(list(g.__saveCalls.values())) == 1)
check("retail 1920: SetActiveLayout(4) = 2 presets + raw index 2",
      list(g.__setActiveCalls.values()) == [4], str(list(g.__setActiveCalls.values())))
store = g.__layoutStore
check("retail 1920: foreign layout kept at index 1",
      store.layouts[1].layoutName == "SomeoneElse" and store.layouts[1].customField == "keep me")
check("retail 1920: Thor6in appended as custom index 2, Account type",
      store.layouts[2].layoutName == "Thor6in"
      and store.layouts[2].layoutType == 1, str(store.layouts[2].layoutName))
check("retail 1920: six bindings written once",
      len(list(g.__bindCalls.values())) == 6 and g.__saveBindings == 1,
      f"{len(list(g.__bindCalls.values()))} binds, {g.__saveBindings} saves")
check("retail 1920: timers are 12 s run then 3 s measure",
      list(g.__timerLog.values()) == [12, 3], str(list(g.__timerLog.values())))
check("retail 1920: tracker frame untouched on retail (placeTracker is a no-op)",
      g.WatchFrame is None and g.ObjectiveTrackerFrame is None)

# --- 3160x1080 retail login (centre-game span) ----------------------------------------------
lua3, g3 = new_env(3160, 1080)
login(g3)
golden("retail_3160_login", lua3, g3)
check("retail 3160: same SaveLayouts payload as 1920 (geometry is not read today)",
      lua3.eval("__ser(__saveCalls[1])") == lua.eval("__ser(__saveCalls[1])"))
check("retail 3160: same SetActiveLayout index as 1920",
      list(g3.__setActiveCalls.values()) == list(g.__setActiveCalls.values()))

# --- Classic login --------------------------------------------------------------------------
luac, gc = new_env(1920, 1080, retail=False)
login(gc)
golden("classic_1920_login", luac, gc)
check("classic: totem bar + chat targets applied",
      any("Totem bar" in r for r in gc.FFScaleLog.results.values())
      and any("Chat at the retail spot" in r for r in gc.FFScaleLog.results.values()))
check("classic: tracker placed directly at TOPLEFT 28,-100 scaled 16/12",
      gc.WatchFrame.scale == 16 / 12 and gc.WatchFrame.h == 300
      and gc.WatchFrame.points[1][1] == "TOPLEFT",
      str(gc.WatchFrame.scale))
check("classic: GameTooltip_SetDefaultAnchor hooked once", gc.__hookedGlobals["GameTooltip_SetDefaultAnchor"] == 1)
check("classic: retail-only targets report 'SKIP (system absent)'",
      any("ObjectiveTracker TextSize 16" in r and "SKIP (system absent)" in r
          for r in gc.FFScaleLog.results.values()))

# --- login while in combat: defer to PLAYER_REGEN_ENABLED -----------------------------------
luak, gk = new_env(1920, 1080, preamble="__combat = true")
login(gk)
check("combat: nothing saved while in combat", len(list(gk.__saveCalls.values())) == 0)
check("combat: deferred note recorded", gk.FFScaleLog.deferred is not None)
gk.__combat = False
gk.__fire("PLAYER_REGEN_ENABLED")
gk.__flush()
golden("retail_1920_combat_login", luak, gk)
check("combat: layout applied after regen", len(list(gk.__saveCalls.values())) == 1)
check("combat: payload identical to the uncontested login",
      luak.eval("__ser(__saveCalls[1])") == lua.eval("__ser(__saveCalls[1])"))

# --- /ffscale out of combat, no login -------------------------------------------------------
luas, gs = new_env(1920, 1080)
luas.execute("SlashCmdList['FFSCALE']()")
golden("retail_1920_slash", luas, gs)
check("slash: applies the same payload as a login",
      luas.eval("__ser(__saveCalls[1])") == lua.eval("__ser(__saveCalls[1])"))
check("slash: schedules no timers of its own", len(list(gs.__timerLog.values())) == 0,
      str(list(gs.__timerLog.values())))

print()
print(f"{sum(results)}/{len(results)} passed" + ("  (goldens updated)" if UPDATE else ""))
sys.exit(0 if all(results) else 1)
