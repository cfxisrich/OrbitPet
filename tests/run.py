import os
from pathlib import Path
import subprocess
import sys

project = Path(__file__).resolve().parents[1]
environment = dict(os.environ)
environment.pop('QT_QPA_PLATFORM', None)
environment.pop('QT_SCALE_FACTOR', None)
for test in sorted((project / 'tests').glob('test_*.py')):
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', test.name, '-v'], cwd=project, env=environment)
    if result.returncode:
        raise SystemExit(result.returncode)
