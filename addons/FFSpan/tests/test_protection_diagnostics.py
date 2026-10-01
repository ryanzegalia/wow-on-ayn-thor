"""Passive protection-event diagnostics, using the real FFSpan dump module."""
from pathlib import Path
import unittest
from lupa import LuaRuntime

SOURCE = Path(__file__).resolve().parents[1] / 'FFSpan_Dump.lua'


class ProtectionDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
            FFSpan = {SupportedSpan = function() return true end}
            SlashCmdList = {}
            WOW_PROJECT_ID = 1
            date = function() return '2026-09-25 00:10:00' end
            events = {}
            CreateFrame = function()
                return {
                    RegisterEvent = function(_, name) events[name] = true end,
                    SetScript = function(_, _, fn) onEvent = fn end,
                }
            end
        ''')
        self.lua.execute(SOURCE.read_text(encoding='utf-8'))

    def test_both_protection_events_record_the_actual_action(self):
        self.lua.execute('''
            assert(events.ADDON_ACTION_BLOCKED and events.ADDON_ACTION_FORBIDDEN)
            onEvent(nil, 'ADDON_ACTION_BLOCKED', 'FFBinds', 'SetCVar()')
            onEvent(nil, 'ADDON_ACTION_FORBIDDEN', 'OtherAddon', 'RunScript()')
            assert(#FFSpanDB.protectionEvents == 2)
            assert(FFSpanDB.protectionEvents[1].addon == 'FFBinds')
            assert(FFSpanDB.protectionEvents[1].action == 'SetCVar()')
            assert(FFSpanDB.protectionEvents[2].event == 'ADDON_ACTION_FORBIDDEN')
            assert(FFSpanDB.protectionEvents[2].projectID == 1)
        ''')

    def test_single_screen_does_not_collect_events(self):
        self.lua.execute('''
            FFSpan.SupportedSpan = function() return false end
            onEvent(nil, 'ADDON_ACTION_BLOCKED', 'FFBinds', 'SetCVar()')
            assert(FFSpanDB == nil)
        ''')

    def test_history_is_bounded_and_retains_recent_events(self):
        self.lua.execute('''
            for i=1,40 do onEvent(nil, 'ADDON_ACTION_BLOCKED', 'FFBinds', 'action'..i) end
            assert(#FFSpanDB.protectionEvents == 24)
            assert(FFSpanDB.protectionEvents[1].action == 'action17')
            assert(FFSpanDB.protectionEvents[24].action == 'action40')
        ''')

    def test_missing_and_oversized_event_arguments_are_safe(self):
        self.lua.execute('''
            onEvent(nil, 'ADDON_ACTION_FORBIDDEN', nil, nil)
            onEvent(nil, 'ADDON_ACTION_BLOCKED', string.rep('x', 500), 'action')
            assert(#FFSpanDB.protectionEvents == 2)
            assert(FFSpanDB.protectionEvents[1].action == nil)
            assert(#FFSpanDB.protectionEvents[2].addon == 240)
        ''')


if __name__ == '__main__':
    unittest.main()
