# SPDX-License-Identifier: GPL-3.0-only
"""Acquire pinned public sources and an isolated wheel-only Python environment.

Run with Python 3.12. Does not start a VM, a service or a model provider.
Existing source directories must match the pinned clean or exact patched state.
"""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RUNTIME = ROOT / '.runtime'
HERMES = '5fc308a70719a83cccdbba4c0e39c23f5a8239d5'
STACKARR = '91100909f3b87afe27afbbe0348e8456701560eb'
HASHES = {
    'tools/approval.py': ('0e73896fa6f81afc3a54608e4c32b510bb1109058dbd1636b0667fbca67619fb',
                          '3ef45f8f66c8cfe7f10cb9e8625b85fd3d245d4a466721540593226aad97bd55'),
    'tools/mcp_tool.py': ('27ebdfd52712971b8d8ee2c34a8a6652e1cbf899fb96043efb3d101d5adc3265',
                          '67cdf6d8c4251d9dc6a143d85840e4e558201d79994110a750b0489a4e25cef1'),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args):
    return subprocess.check_output(list(map(str, args)), text=True, timeout=300).strip()


def acquire(name, url, pin, tag=None):
    path = RUNTIME / name
    if not path.exists():
        if tag:
            run('git', 'clone', '--depth', '1', '--branch', tag, url, path)
        else:
            run('git', 'clone', '--filter=blob:none', '--no-checkout', url, path)
            run('git', '-C', path, 'sparse-checkout', 'set', 'tools', 'hermes_cli', 'gateway', 'utils')
            run('git', '-C', path, 'checkout', pin)
    if run('git', '-C', path, 'rev-parse', 'HEAD') != pin:
        raise RuntimeError('Existing source does not match pin: ' + name)
    return path


def prepare():
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('Use Python 3.12 for this pinned compatibility environment')
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    RUNTIME.chmod(0o700)
    (RUNTIME / 'empty-home').mkdir(exist_ok=True)
    patch = HERE / 'compat/stackarr-explicit-consent.patch'
    bridge = HERE / 'compat/consent_bridge.py'
    if digest(patch) != '028c8b252c7d0f0496dc5d6968557fab6b4d7fd3eabe1099440f340e2b2aa7a6':
        raise RuntimeError('Reviewed patch checksum mismatch')
    if digest(bridge) != '30ad5b433994fab08122ef7f70cbdf21f97c9a31057df2199ede9b4d7439c4b3':
        raise RuntimeError('Reviewed bridge checksum mismatch')
    stackarr = acquire('stackarr', 'https://github.com/polyphonic/stackarr.git', STACKARR, 'v0.3.0-alpha.19')
    if run('git', '-C', stackarr, 'status', '--porcelain'):
        raise RuntimeError('Stackarr checkout is modified')
    hermes = acquire('hermes-fix', 'https://github.com/NousResearch/hermes-agent.git', HERMES)
    changes = set(run('git', '-C', hermes, 'diff', '--name-only').splitlines())
    if changes - set(HASHES) or run('git', '-C', hermes, 'ls-files', '--others', '--exclude-standard'):
        raise RuntimeError('Unexpected Hermes changes')
    for filename, hashes in HASHES.items():
        baseline = RUNTIME / 'hermes-baseline' / filename
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_bytes(subprocess.check_output(['git', '-C', str(hermes), 'show', HERMES + ':' + filename]))
        if digest(baseline) != hashes[0] or digest(hermes / filename) not in hashes:
            raise RuntimeError('Hermes module checksum mismatch')
    if all(digest(hermes / filename) == hashes[0] for filename, hashes in HASHES.items()):
        run('git', '-C', hermes, 'apply', '--check', patch)
        run('git', '-C', hermes, 'apply', patch)
    if not all(digest(hermes / filename) == hashes[1] for filename, hashes in HASHES.items()):
        raise RuntimeError('Expected exact repaired Hermes modules')
    shutil.copyfile(bridge, RUNTIME / 'consent_bridge.py')
    if not (RUNTIME / 'venv').exists():
        run(sys.executable, '-m', 'venv', RUNTIME / 'venv')
    run(RUNTIME / 'venv/bin/python', '-m', 'pip', 'install', '--only-binary=:all:', '-r', HERE / 'requirements.txt')
    run(RUNTIME / 'venv/bin/python', '-m', 'pip', 'check')
    print('Exact public source pins, repaired modules and Python dependencies verified.')


if __name__ == '__main__':
    prepare()
