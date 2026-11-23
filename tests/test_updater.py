import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from updater import Release, UpdateBox, parse_release, save_download, start_install


def metadata():
    return {'tag_name': 'v2.10.0', 'draft': False, 'prerelease': False, 'body': '更新说明',
            'assets': [{'name': 'OrbitPet.exe', 'size': 4, 'digest': 'sha256:' + hashlib.sha256(b'test').hexdigest(),
                        'browser_download_url': 'https://github.com/cfxisrich/OrbitPet/releases/download/v2.10.0/OrbitPet.exe'}]}


class ReleaseTests(unittest.TestCase):
    def test_only_newer_stable_release_from_our_repo(self):
        self.assertEqual(parse_release(metadata(), '2.9.0').version, '2.10.0')
        self.assertIsNone(parse_release(metadata(), '2.10.0'))
        self.assertIsNone(parse_release(metadata(), '3.0.0'))
        for field in ('draft', 'prerelease'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse_release(dict(metadata(), **{field: True}), '2.9.0')
        for field, value in (('browser_download_url', 'https://example.org/OrbitPet.exe'), ('digest', None)):
            payload = metadata()
            payload['assets'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse_release(payload, '2.9.0')

    def test_download_preserves_verified_stage_on_corruption_or_interruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'updates'
            release = parse_release(metadata(), '2.3.0')
            observed = []
            target = save_download(io.BytesIO(b'test'), release, directory, observed.append)
            self.assertEqual(observed[-1], 100)
            for content in (b'bad!', b'te', b'testx'):
                with self.subTest(content=content), self.assertRaises(ValueError):
                    save_download(io.BytesIO(content), release, directory, observed.append)
                self.assertEqual(target.read_bytes(), b'test')
            self.assertEqual(list(directory.iterdir()), [target])

    def test_install_waits_for_idle_and_requires_click(self):
        app = QApplication.instance() or QApplication([])
        box = UpdateBox(Path('unused'))
        called = []
        box.install_requested.connect(lambda: called.append(True))
        box.set_busy(True)
        box.show_package(Path('unused'))
        self.assertFalse(box.action.isEnabled())
        box.set_busy(False)
        self.assertEqual(called, [])
        box.action.click()
        self.assertEqual(called, [True])
        box.close()


class WindowsInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='Orbit 更新 & $ ')
        cls.addClassCleanup(cls.temp.cleanup)
        project = Path(cls.temp.name)
        source = project / 'fixture.cs'
        source.write_text('''
using System;
using System.Diagnostics;
using System.IO;
class Fixture {
    static int Main(string[] args) {
        if (args.Length == 1 && args[0] == "--update-error") {
            File.WriteAllText("recovered.flag", Process.GetCurrentProcess().Id.ToString());
            return 0;
        }
        if (Environment.GetEnvironmentVariable("ORBIT_TEST_FAIL") == "1") return 1;
        string token = Environment.GetEnvironmentVariable("ORBIT_UPDATE_ID");
        File.WriteAllText(Path.Combine("data", "updates", token + ".ready"), "");
        return 0;
    }
}
''', encoding='utf-8')
        cls.fixture = project / 'fixture.exe'
        compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        subprocess.run([compiler, '/nologo', '/target:winexe', '/out:' + str(cls.fixture), source], check=True)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir=self.temp.name)))
        self.exe = self.root / 'Orbit.exe'
        self.stage = self.root / 'data/updates/OrbitPet.download'
        self.stage.parent.mkdir(parents=True)
        shutil.copyfile(self.fixture, self.stage)
        self.old = self.fixture.read_bytes() + b'previous'
        self.exe.write_bytes(self.old)
        self.data = self.root / 'data/keep.txt'
        self.data.write_text('existing')
        self.digest = hashlib.sha256(self.stage.read_bytes()).hexdigest()

    def test_real_windows_swap_and_restart(self):
        worker = start_install(self.exe, self.stage, self.digest, 987654321)
        self.assertEqual(worker.wait(timeout=30), 0)
        self.assertEqual(self.exe.read_bytes(), self.fixture.read_bytes())
        self.assertEqual(Path(str(self.exe) + '.previous.bak').read_bytes(), self.old)
        self.assertEqual(self.data.read_text(), 'existing')

    def test_new_app_start_failure_restores_previous_exe_and_data(self):
        with patch.dict(os.environ, ORBIT_TEST_FAIL='1'):
            worker = start_install(self.exe, self.stage, self.digest, 987654321)
            self.assertEqual(worker.wait(timeout=30), 1)
        for _ in range(100):
            if (self.root / 'recovered.flag').exists():
                break
            time.sleep(.05)
        self.assertTrue((self.root / 'recovered.flag').is_file())
        # Acknowledgement precedes process exit and Windows still holds its image file.
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                        "$p=Get-Process -Id ([int](Get-Content -LiteralPath recovered.flag)) -ErrorAction SilentlyContinue; "
                        "if ($p -and !$p.WaitForExit(5000)) { exit 1 }; exit 0"], cwd=self.root, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(self.exe.read_bytes(), self.old)
        self.assertEqual(self.data.read_text(), 'existing')
        self.assertIn('startup', (self.stage.parent / 'last-error.txt').read_text('utf-8'))
