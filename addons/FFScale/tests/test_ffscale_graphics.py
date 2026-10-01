#!/usr/bin/env python3
"""
Tests for FFScale_Graphics.lua -- the independent, conservative all-flavor graphics profile.

Runs real Lua via lupa, same harness (`ffscale_harness.new_env`) as test_ffscale_layouts.py /
test_ffscale_home.py, but with its OWN CVar mock: the shared MOCK_API has none (FFScale.lua
never touched a CVar before this module), so GetCVar/SetCVar/C_CVar are defined here via
`cvar_preamble()` and passed through `new_env(..., preamble=...)`.

This module's contract is behavioural (supported/unsupported, no-op, error isolation,
persistence), not a recorded layout, so assertions are direct values pulled out of the real Lua
state through a tiny JSON encoder (`__ffgfxJSON`, defined per-env below) rather than golden-text
diffing -- that sidesteps any dependence on how lupa marshals nested Lua tables.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import lupa  # noqa: F401  -- imported for the same environment guard ffscale_harness uses
except ImportError:  # pragma: no cover - environment guard
    print("SKIP: python module 'lupa' is not installed -- cannot run mocked-API tests.")
    sys.exit(0)

from ffscale_harness import compare_golden, login, new_env, record

PROFILE_CVARS = [
    "graphicsShadowQuality", "graphicsLiquidDetail", "graphicsPBRLiquidDetail", "graphicsSSAO",
    "graphicsSunshafts", "graphicsDepthEffects", "graphicsComputeEffects", "graphicsLightMode",
    "graphicsBloomUserMult", "graphicsViewDistance", "graphicsEnvironmentDetail",
    "graphicsGroundClutter", "graphicsProjectedTextures", "projectedTextures",
    "RAIDsettingsEnabled", "RenderScale", "maxFPS",
]

# Cvars this module must NEVER touch (my exclusion list).
FORBIDDEN_CVARS = [
    "graphicsQuality", "graphicsSpellDensity", "particleDensity", "spellClutter",
    "spellVisualDensityFilterSetting", "textureResolution", "worldTextureResolution",
    "uiScale", "useUiScale", "Gamma", "WindowedMaximized", "VSync", "MSAA",
    "graphicsAntiAliasingMode", "gxApi", "gxWindow",
]

# The profile's own target values -- a client already sitting here needs zero writes.
TARGET_DEFAULTS = {
    "graphicsShadowQuality": "0", "graphicsLiquidDetail": "0", "graphicsPBRLiquidDetail": "0",
    "graphicsSSAO": "0", "graphicsSunshafts": "0", "graphicsDepthEffects": "0",
    "graphicsComputeEffects": "0", "graphicsLightMode": "0", "graphicsBloomUserMult": "0",
    "graphicsViewDistance": "2", "graphicsEnvironmentDetail": "2", "graphicsGroundClutter": "1",
    "graphicsProjectedTextures": "1", "projectedTextures": "1", "RAIDsettingsEnabled": "0",
    "RenderScale": "0.75", "maxFPS": "60",
}

# Deliberately expensive defaults, as a fresh/stock client would have before any apply.
STOCK_DEFAULTS = {
    "graphicsShadowQuality": "3", "graphicsLiquidDetail": "3", "graphicsPBRLiquidDetail": "1",
    "graphicsSSAO": "2", "graphicsSunshafts": "1", "graphicsDepthEffects": "1",
    "graphicsComputeEffects": "1", "graphicsLightMode": "2", "graphicsBloomUserMult": "1",
    "graphicsViewDistance": "6", "graphicsEnvironmentDetail": "6", "graphicsGroundClutter": "3",
    "graphicsProjectedTextures": "0", "projectedTextures": "0", "RAIDsettingsEnabled": "1",
    "RenderScale": "1", "maxFPS": "0",
}


def _lua_str(v):
    return json.dumps(str(v))


def _lua_table(d):
    if not d:
        return "{}"
    parts = []
    for k, v in d.items():
        val = "true" if v is True else _lua_str(v)
        parts.append("[%s]=%s" % (_lua_str(k), val))
    return "{" + ",".join(parts) + "}"


# A tiny, self-contained JSON encoder for Lua -- lets Python read back Status()/__cvars/etc.
# via plain Lua STRINGS (guaranteed to marshal to a Python str) instead of depending on how
# lupa marshals nested Lua tables.
_JSON_HELPER = r"""
function __ffgfxJSON(v)
    local t = type(v)
    if t == "nil" then return "null" end
    if t == "boolean" then return v and "true" or "false" end
    if t == "number" then return tostring(v) end
    if t == "string" then
        local s = v:gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", "\\n")
        return '"' .. s .. '"'
    end
    if t == "table" then
        local n = 0
        for _ in pairs(v) do n = n + 1 end
        if n == 0 then return "[]" end   -- Lua can't distinguish empty-array/empty-object;
                                          -- every empty check on the Python side treats them
                                          -- as an empty list, so pick that representation.
        local isArray = true
        for i = 1, n do if v[i] == nil then isArray = false break end end
        if isArray then
            local parts = {}
            for i = 1, n do parts[i] = __ffgfxJSON(v[i]) end
            return "[" .. table.concat(parts, ",") .. "]"
        else
            local keys = {}
            for k in pairs(v) do keys[#keys + 1] = k end
            table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
            local parts = {}
            for _, k in ipairs(keys) do
                parts[#parts + 1] = __ffgfxJSON(tostring(k)) .. ":" .. __ffgfxJSON(v[k])
            end
            return "{" .. table.concat(parts, ",") .. "}"
        end
    end
    return "null"
end
"""


def cvar_preamble(defaults, fail=None, readback_override=None):
    """FFScale_Graphics's OWN CVar mock -- ffscale_harness's shared MOCK_API has none.
    `defaults` = the only cvars that "exist" on this simulated client (anything else reads back
    nil, exactly like an unsupported name on a real client). `fail` = cvar names whose setter
    should pcall-throw. `readback_override` = cvar name -> what GetCVar returns AFTER a set,
    to simulate a client that reformats the value it was just given."""
    fail_map = {name: True for name in (fail or [])}
    body = """
__cvarDefaults = %s
__cvarSetShouldFail = %s
__cvarReadbackOverride = %s
__cvars = {}
for k, v in pairs(__cvarDefaults) do __cvars[k] = v end
__cvarSetCalls = {}
local function ffgfx_get(name) return __cvars[name] end
local function ffgfx_set(name, value)
    __cvarSetCalls[#__cvarSetCalls + 1] = { name = name, value = tostring(value) }
    if __cvarSetShouldFail[name] then error('simulated failure: ' .. tostring(name)) end
    if __cvarReadbackOverride[name] ~= nil then
        __cvars[name] = __cvarReadbackOverride[name]
    else
        __cvars[name] = tostring(value)
    end
end
GetCVar = ffgfx_get
SetCVar = ffgfx_set
C_CVar = { GetCVar = ffgfx_get, SetCVar = ffgfx_set }
""" % (_lua_table(defaults), _lua_table(fail_map), _lua_table(readback_override or {}))
    return _JSON_HELPER + body


def make_env(defaults, fail=None, readback_override=None, retail=True):
    return new_env(1920, 1080, retail=retail,
                   preamble=cvar_preamble(defaults, fail, readback_override),
                   extra_files=["FFScale.lua", "FFScale_Graphics.lua"])


def call_json(lua, expr):
    return json.loads(lua.eval("__ffgfxJSON(%s)" % expr))


def set_calls(lua):
    return json.loads(lua.eval("__ffgfxJSON(__cvarSetCalls)"))


def fire_login(g):
    g.__fire("PLAYER_LOGIN")
    return g.__flush()


# --------------------------------------------------------------------------------- tests

def test_supported_applied_unsupported_missing():
    defaults = dict(STOCK_DEFAULTS)
    del defaults["RAIDsettingsEnabled"]
    del defaults["graphicsPBRLiquidDetail"]
    lua, g = make_env(defaults)
    fire_login(g)
    status = call_json(lua, "FFScale.Graphics.Status()")
    assert sorted(status["missing"]) == ["RAIDsettingsEnabled", "graphicsPBRLiquidDetail"]
    assert status["applied"]["graphicsShadowQuality"] == "0"
    assert not status["rejected"]


def test_login_applies_once_after_2s_timer_not_on_other_events():
    lua, g = make_env(dict(STOCK_DEFAULTS))
    g.__fire("PLAYER_LOGIN")
    assert set_calls(lua) == [], "must not apply synchronously inside the event handler"
    timers = call_json(lua, "__timerLog")
    assert 2 in timers, "must schedule the apply via C_Timer.After(2, ...)"
    g.__flush()
    calls_after_login = set_calls(lua)
    assert len(calls_after_login) > 0

    g.__fire("PLAYER_ENTERING_WORLD")   # a zone change must never re-trigger this module
    g.__flush()
    assert set_calls(lua) == calls_after_login


def test_one_setting_error_does_not_abort_the_rest():
    lua, g = make_env(dict(STOCK_DEFAULTS), fail=["graphicsSSAO"])
    fire_login(g)
    status = call_json(lua, "FFScale.Graphics.Status()")
    assert "graphicsSSAO" in status["rejected"]
    assert status["applied"]["graphicsShadowQuality"] == "0"
    assert status["applied"]["maxFPS"] == "60"
    assert status["applied"]["RenderScale"] == "0.75"


def test_noop_when_already_at_target():
    lua, g = make_env(dict(TARGET_DEFAULTS))
    fire_login(g)
    assert set_calls(lua) == [], "already-correct cvars must not be re-written"
    status = call_json(lua, "FFScale.Graphics.Status()")
    assert len(status["applied"]) == len(PROFILE_CVARS)
    assert not status["rejected"] and not status["missing"]


def test_numeric_readback_normalization():
    defaults = dict(TARGET_DEFAULTS)
    defaults["RenderScale"] = "0.750000"          # numerically equal, differently formatted
    lua, g = make_env(defaults)
    fire_login(g)
    assert set_calls(lua) == [], "0.750000 == 0.75 must count as already applied"

    lua2, g2 = make_env(dict(STOCK_DEFAULTS), readback_override={"RenderScale": "0.750000"})
    fire_login(g2)
    status = call_json(lua2, "FFScale.Graphics.Status()")
    assert status["applied"].get("RenderScale") == "0.750000"
    assert "RenderScale" not in status["rejected"]


def test_originals_preserved_once_and_kept_across_relogin():
    lua, g = make_env(dict(STOCK_DEFAULTS))
    fire_login(g)
    originals_1 = call_json(lua, "FFScaleGraphicsDB.originals")
    assert originals_1["graphicsShadowQuality"] == "3"

    fire_login(g)   # a second login in the same session -- SavedVariables persist across relogin
    originals_2 = call_json(lua, "FFScaleGraphicsDB.originals")
    assert originals_2 == originals_1, "a later apply must never overwrite preserved originals"


def test_restore_reverts_values_and_disables_autoapply():
    lua, g = make_env(dict(STOCK_DEFAULTS))
    fire_login(g)
    lua.execute("SlashCmdList['FFGRAPHICS']('restore')")
    cur = call_json(lua, "__cvars")
    for name, orig in STOCK_DEFAULTS.items():
        assert cur[name] == orig, "restore must put every original value back"
    assert call_json(lua, "FFScaleGraphicsDB.enabled") is False

    calls_before = len(set_calls(lua))
    fire_login(g)
    assert len(set_calls(lua)) == calls_before, "restore must disable future autoapply"


def test_restore_reports_a_rejected_readback_honestly():
    lua, g = make_env(dict(STOCK_DEFAULTS))
    fire_login(g)
    lua.execute('__cvarReadbackOverride["RenderScale"] = "0.5"')
    lua.execute('FFScale.Graphics.Restore()')
    status = call_json(lua, 'FFScale.Graphics.Status()')
    assert status['rejected']['RenderScale']['error'] == 'readback-mismatch'
    assert 'RenderScale' not in status['applied']
    assert status['enabled'] is False


def test_global_api_fallback_and_empty_cvar():
    lua, g = make_env(dict(STOCK_DEFAULTS, graphicsSSAO=''))
    lua.execute('C_CVar = nil')
    fire_login(g)
    status = call_json(lua, 'FFScale.Graphics.Status()')
    assert 'graphicsSSAO' in status['missing']
    assert status['applied']['maxFPS'] == '60'
    assert not status['rejected']


def test_off_stops_autoapply_without_reverting_values():
    lua, g = make_env(dict(STOCK_DEFAULTS))
    fire_login(g)
    applied_values = call_json(lua, "__cvars")
    lua.execute("SlashCmdList['FFGRAPHICS']('off')")
    assert call_json(lua, "FFScaleGraphicsDB.enabled") is False
    assert call_json(lua, "__cvars") == applied_values, "off must not change current values"

    calls_before = len(set_calls(lua))
    fire_login(g)
    assert len(set_calls(lua)) == calls_before


def test_apply_slash_reenables_autoapply():
    lua, g = make_env(dict(STOCK_DEFAULTS))
    fire_login(g)
    lua.execute("SlashCmdList['FFGRAPHICS']('off')")
    lua.execute("SlashCmdList['FFGRAPHICS']('apply')")
    assert call_json(lua, "FFScaleGraphicsDB.enabled") is True
    status = call_json(lua, "FFScale.Graphics.Status()")
    assert status["applied"]["graphicsShadowQuality"] == "0"


def test_no_unintended_cvars_touched():
    lua, g = make_env(dict(STOCK_DEFAULTS))
    fire_login(g)
    touched = {c["name"] for c in set_calls(lua)}
    assert touched <= set(PROFILE_CVARS)
    for name in FORBIDDEN_CVARS:
        assert name not in touched


def test_all_flavor_classic_and_retail_match():
    results = {}
    for retail in (True, False):
        lua, g = make_env(dict(STOCK_DEFAULTS), retail=retail)
        fire_login(g)
        results[retail] = call_json(lua, "FFScale.Graphics.Status()")
    assert results[True]["applied"] == results[False]["applied"]
    assert results[True]["rejected"] == results[False]["rejected"]
    assert results[True]["missing"] == results[False]["missing"]


def test_existing_ffscale_golden_untouched_when_graphics_loaded_alongside():
    """Loading FFScale_Graphics.lua in the real production order (after FFScale.lua) must not
    change one byte of FFScale's own recorded Edit Mode behaviour."""
    lua, g = new_env(1920, 1080, retail=True,
                      preamble=cvar_preamble(dict(STOCK_DEFAULTS)),
                      extra_files=["FFScale.lua", "FFScale_Graphics.lua"])
    login(g)  # PLAYER_ENTERING_WORLD -- FFScale's own layout pass
    actual = record(lua, g)
    ok, detail = compare_golden("retail_1920_login", actual, update=False)
    assert ok, detail


_TEST_FUNCS = [(n, f) for n, f in sorted(globals().items())
               if n.startswith("test_") and callable(f)]

if __name__ == "__main__":
    failures = 0
    for name, fn in _TEST_FUNCS:
        try:
            fn()
            print("PASS", name)
        except AssertionError as e:
            failures += 1
            print("FAIL", name, "--", e)
        except Exception as e:  # noqa: BLE001 - report, don't hide
            failures += 1
            print("ERROR", name, "--", repr(e))
    print("%d/%d passed" % (len(_TEST_FUNCS) - failures, len(_TEST_FUNCS)))
    sys.exit(1 if failures else 0)
