import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QVBoxLayout


REPOSITORY = 'cfxisrich/OrbitPet'
LATEST = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
VERSION_PATTERN = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'


@dataclass(frozen=True)
class Release:
    version: str
    notes: str
    url: str
    digest: str
    size: int


class ReleaseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme != 'https' or target.netloc not in (
                'github.com', 'api.github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'):
            raise ValueError('GitHub 返回了不受支持的下载地址。')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def parse_release(payload, current: str) -> Release | None:
    tag = payload['tag_name']
    if (payload['draft'] or payload['prerelease'] or not isinstance(tag, str)
            or not re.fullmatch('v' + VERSION_PATTERN, tag)):
        raise ValueError('GitHub 发布信息中没有正式版本号。')
    version = tag[1:]
    if tuple(map(int, version.split('.'))) <= tuple(map(int, current.split('.'))):
        return None
    url = f'https://github.com/{REPOSITORY}/releases/download/{tag}/OrbitPet.exe'
    for asset in payload['assets']:
        if asset['name'] != 'OrbitPet.exe':
            continue
        digest = asset.get('digest') or ''
        if (asset['browser_download_url'] != url or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest)
                or type(asset['size']) is not int or asset['size'] <= 0):
            raise ValueError('发布附件缺少有效的下载地址、大小或 SHA-256 校验值。')
        return Release(version, payload.get('body') or '', url, digest[7:], asset['size'])
    raise ValueError('这个版本尚未上传 OrbitPet.exe。')


def check_release(current):
    request = Request(LATEST, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'OrbitPet/' + current})
    try:
        with build_opener(ReleaseRedirect()).open(request, timeout=20) as response:
            return parse_release(json.load(response), current)
    except HTTPError as error:
        if error.code == 404:
            raise ValueError('GitHub 上还没有公开的正式版本。') from error
        raise


def save_download(stream, release, directory, progress):
    directory.mkdir(parents=True, exist_ok=True)
    total = percent = 0
    digest = hashlib.sha256()
    part = tempfile.NamedTemporaryFile(dir=directory, suffix='.part', delete=False)
    try:
        with part:
            while chunk := stream.read(256 * 1024):
                total += len(chunk)
                if total > release.size:
                    raise ValueError('下载文件超出发布附件的大小。')
                part.write(chunk)
                digest.update(chunk)
                if total * 100 // release.size != percent:
                    percent = total * 100 // release.size
                    progress(percent)
        if total != release.size or digest.hexdigest() != release.digest:
            raise ValueError('下载的文件未通过 SHA-256 或大小校验，请重新下载。')
        target = directory / 'OrbitPet.download'
        os.replace(part.name, target)
        return target
    finally:
        Path(part.name).unlink(missing_ok=True)


# Paths and digests travel as process environment data, never as PowerShell source.
INSTALL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$exe = $env:ORBIT_UPDATE_EXE
$stage = $env:ORBIT_UPDATE_STAGE
$dir = [IO.Path]::GetDirectoryName($stage)
$backup = $exe + '.previous.bak'
$readyFile = [IO.Path]::Combine($dir, $env:ORBIT_UPDATE_ID + '.ready')
$replaced = $false
$start = [Diagnostics.ProcessStartInfo]::new($exe)
$start.UseShellExecute = $false
$start.WorkingDirectory = [IO.Path]::GetDirectoryName($exe)
try {
    $original = Get-Process -Id ([int]$env:ORBIT_UPDATE_PID) -ErrorAction SilentlyContinue
    if ($original -and !$original.WaitForExit(60000)) {
        [IO.File]::WriteAllText([IO.Path]::Combine($dir, 'last-error.txt'), 'Orbit 未在时限内退出，旧版仍保留。')
        exit 1
    }
    $hash = [Security.Cryptography.SHA256]::Create()
    $file = [IO.File]::OpenRead($stage)
    try { $digest = [BitConverter]::ToString($hash.ComputeHash($file)).Replace('-', '') }
    finally { $file.Dispose(); $hash.Dispose() }
    if ($digest -ne $env:ORBIT_UPDATE_HASH) { throw 'SHA-256 mismatch' }
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    while (!$replaced) {
        try {
            [IO.File]::Replace($stage, $exe, $backup)
            $replaced = $true
        } catch [IO.IOException] {
            if (($_.Exception.GetBaseException().HResult -band 65535) -notin 32,33 -or [DateTime]::UtcNow -ge $deadline) { throw }
            Start-Sleep -Milliseconds 250
        }
    }
    $newApp = [Diagnostics.Process]::Start($start)
    $deadline = [DateTime]::UtcNow.AddMinutes(2)
    while (![IO.File]::Exists($readyFile)) {
        if ($newApp.WaitForExit(250) -and ![IO.File]::Exists($readyFile)) { throw 'Updated Orbit exited before startup completed' }
        if ([DateTime]::UtcNow -ge $deadline -and ![IO.File]::Exists($readyFile)) {
            if (!$newApp.HasExited) {
                & ([IO.Path]::Combine([Environment]::SystemDirectory, 'taskkill.exe')) /PID $newApp.Id /T /F | Out-Null
                if (!$newApp.WaitForExit(10000)) { throw 'Updated Orbit could not finish startup or exit' }
            }
            throw 'Updated Orbit startup timed out'
        }
    }
    [IO.File]::Delete($readyFile)
} catch {
    if ($replaced) { [IO.File]::Replace($backup, $exe, ($stage + '.failed')) }
    [IO.File]::WriteAllText([IO.Path]::Combine($dir, 'last-error.txt'), $_.Exception.Message)
    $start.EnvironmentVariables.Remove('ORBIT_UPDATE_ID')
    $start.Arguments = '--update-error'
    [void][Diagnostics.Process]::Start($start)
    exit 1
}
"""


def start_install(executable: Path, stage: Path, digest: str, parent_pid: int):
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    env = dict(os.environ, ORBIT_UPDATE_EXE=str(executable), ORBIT_UPDATE_STAGE=str(stage),
               ORBIT_UPDATE_HASH=digest, ORBIT_UPDATE_PID=str(parent_pid), ORBIT_UPDATE_ID=uuid.uuid4().hex,
               PYINSTALLER_RESET_ENVIRONMENT='1')
    return subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive', '-Command', INSTALL_SCRIPT],
                            cwd=executable.parent, env=env, creationflags=subprocess.CREATE_NO_WINDOW)


def confirm_startup(directory: Path):
    token = os.environ.pop('ORBIT_UPDATE_ID', '')
    if re.fullmatch('[0-9a-f]{32}', token):
        (directory / 'updates' / (token + '.ready')).touch()


class UpdateBox(QFrame):
    checked = Signal(object)
    downloaded = Signal(object)
    progress = Signal(int)
    failed = Signal(str)
    install_requested = Signal()

    def __init__(self, data_dir):
        super().__init__()
        self.setObjectName('SoftCard')
        self.directory = data_dir / 'updates'
        self.release = None
        self.stage = None
        self.busy = False
        self.status = QLabel('从 GitHub Releases 检查正式版本。')
        self.notes = QLabel()
        for label in (self.status, self.notes):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
        self.notes.hide()
        self.action = QPushButton('检查更新')
        self.action.clicked.connect(self.activate)
        layout = QVBoxLayout(self)
        heading = QLabel('版本更新')
        heading.setObjectName('SectionTitle')
        for widget in (heading, self.status, self.notes, self.action):
            layout.addWidget(widget)
        self.checked.connect(self.show_release)
        self.downloaded.connect(self.show_package)
        self.progress.connect(self.show_progress)
        self.failed.connect(self.show_error)

    def activate(self):
        if self.stage:
            self.install_requested.emit()
            return
        self.action.setEnabled(False)
        self.status.setText('正在连接 GitHub…' if self.release is None else '正在下载并校验…')
        threading.Thread(target=self.fetch, args=(QApplication.applicationVersion(), self.release),
                         name='orbit-release', daemon=True).start()

    def fetch(self, current, release):
        try:
            if release is None:
                self.checked.emit(check_release(current))
                return
            with build_opener(ReleaseRedirect()).open(release.url, timeout=30) as response:
                self.downloaded.emit(save_download(response, release, self.directory, self.progress.emit))
        except (OSError, HTTPException, ValueError, TypeError, KeyError) as error:
            self.failed.emit(str(error))

    def show_release(self, release):
        self.release = release
        self.action.setEnabled(True)
        if release is None:
            self.notes.hide()
            self.action.setText('检查更新')
            self.status.setText('当前已是最新正式版。')
            return
        self.notes.setText(release.notes)
        self.notes.setVisible(bool(release.notes))
        self.status.setText(f'可更新至 {release.version} · {release.size / 1048576:.1f} MB')
        self.action.setText('下载新版')
        if not getattr(sys, 'frozen', False):
            self.status.setText(f'最新版本 {release.version}。请从打包版检查并安装更新。')
            self.action.setText('重新检查')
            self.release = None

    def show_progress(self, percent):
        self.status.setText(f'正在下载并校验 · {percent}%')

    def show_package(self, stage):
        self.stage = stage
        self.action.setText('重启并安装')
        self.set_busy(self.busy)

    def set_busy(self, busy):
        self.busy = busy
        if self.stage:
            self.action.setEnabled(not busy)
            self.status.setText('等待聊天回复和计时结束后即可安装。' if busy else '下载校验通过，可以重启安装。')

    def show_error(self, message):
        self.status.setText('更新失败：' + message)
        self.action.setEnabled(True)
