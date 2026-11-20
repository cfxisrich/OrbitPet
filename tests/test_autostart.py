import sys
import unittest
import winreg
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import windows


class AutostartTests(unittest.TestCase):
    def test_frozen_and_source_commands_quote_paths(self):
        with patch.object(sys, "executable", r"D:\Orbit 工具\OrbitPet.exe"), patch.object(sys, "frozen", True, create=True):
            self.assertEqual(windows.autostart_command(), '"D:\\Orbit 工具\\OrbitPet.exe" --autostart')
        with patch.object(sys, "executable", r"D:\Python 环境\python.exe"), patch.object(windows, "__file__", r"D:\源码 目录\windows.py"):
            self.assertEqual(windows.autostart_command(), '"D:\\Python 环境\\pythonw.exe" "D:\\源码 目录\\app.py" --autostart')

    def test_registration_targets_current_copy_and_user(self):
        with patch.object(windows, "winreg", spec=winreg) as registry:
            registry.REG_SZ = winreg.REG_SZ
            registry.CreateKeyEx.return_value.__enter__.return_value = "test-key"
            registry.QueryValueEx.return_value = ('"D:\\old\\OrbitPet.exe" --autostart', winreg.REG_SZ)
            windows.set_autostart(False)
            registry.DeleteValue.assert_not_called()
            windows.set_autostart(True)
            registry.CreateKeyEx.assert_called_once_with(registry.HKEY_CURRENT_USER, windows.RUN_KEY, access=registry.KEY_SET_VALUE)
            registry.SetValueEx.assert_called_once_with("test-key", "OrbitPet", 0, winreg.REG_SZ, windows.autostart_command())
            registry.QueryValueEx.return_value = (windows.autostart_command(), winreg.REG_SZ)
            self.assertTrue(windows.autostart_enabled())
            windows.set_autostart(True)
            self.assertEqual(registry.SetValueEx.call_count, 1)

    def test_removal_is_scoped_and_missing_entry_is_disabled(self):
        with patch.object(windows, "winreg", spec=winreg) as registry:
            registry.REG_SZ = winreg.REG_SZ
            registry.OpenKey.return_value.__enter__.return_value = "test-key"
            registry.QueryValueEx.return_value = (windows.autostart_command(), winreg.REG_SZ)
            registry.DeleteValue.return_value = None
            windows.set_autostart(False)
            registry.DeleteValue.assert_called_once_with("test-key", "OrbitPet")
            registry.DeleteValue.side_effect = FileNotFoundError
            windows.set_autostart(False)
            registry.OpenKey.side_effect = FileNotFoundError
            self.assertFalse(windows.autostart_enabled())
            windows.set_autostart(False)

    def test_write_failure_reaches_settings_page(self):
        with patch.object(windows, "winreg", spec=winreg) as registry:
            registry.QueryValueEx.side_effect = FileNotFoundError
            registry.CreateKeyEx.side_effect = PermissionError
            with self.assertRaises(PermissionError):
                windows.set_autostart(True)
