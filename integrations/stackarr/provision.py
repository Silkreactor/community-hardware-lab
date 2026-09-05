# SPDX-License-Identifier: GPL-3.0-only
"""Create only the first two trial containers in an EMPTY dedicated lab VM."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from acceptance import STACKARR, JELLYFIN, RUNTIME
from isolation import validate_isolation


def provision(host):
    validate_isolation(host)
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    config = RUNTIME / 'docker-config'
    config.mkdir(mode=0o700, exist_ok=True)
    env = {**os.environ, 'DOCKER_CONFIG': str(config)}
    command = ['docker', '--host', host]
    def run(*args, timeout=300):
        return subprocess.check_output(command + list(args), text=True, env=env, timeout=timeout).strip()
    info = json.loads(run('info', '--format', '{{json .}}'))
    if info['Name'] != 'colima-lab' or info['OSType'] != 'linux':
        raise ValueError('Only the dedicated colima-lab Linux engine is allowed')
    if info['Containers'] or run('volume', 'ls', '-q'):
        raise ValueError('Engine is not empty; existing resources are preserved')
    for image in (STACKARR, JELLYFIN):
        run('pull', image)
    label = ['--label', 'community-lab.trial=true']
    for name in ('lab-stackarr-config', 'lab-media-config', 'lab-media-cache', 'lab-media-library'):
        run('volume', 'create', *label, name)
    gid = run('run', '--rm', '--network', 'none', '--mount',
              'type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock',
              '--entrypoint', 'stat', STACKARR, '-c', '%g', '/var/run/docker.sock')
    if not gid.isdigit():
        raise ValueError('Invalid guest socket group')
    protection = ['--security-opt', 'no-new-privileges', '--cap-drop', 'ALL']
    run('run', '-d', '--name', 'lab-stackarr', *label, *protection, '--network', 'none', '--group-add', gid,
        '--pids-limit', '128', '--memory', '512m', '--mount',
        'type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock', '--mount',
        'type=volume,src=lab-stackarr-config,dst=/stackarr-config',
        '-e', 'STACKARR_DATABASE_FILE=/stackarr-config/stackarr.db', '-e', 'STACKARR_REPO_ROOT=/app',
        '-e', 'STACKARR_TELEMETRY_ENDPOINT=', '-e', 'STACKARR_SCHEDULER_ENABLED=false',
        '--entrypoint', 'tail', STACKARR, '-f', '/dev/null')
    run('run', '-d', '--name', 'lab-media', *label, *protection, '--pids-limit', '256', '--memory', '768m',
        '--publish', '127.0.0.1:18096:8096', '--mount', 'type=volume,src=lab-media-config,dst=/config',
        '--mount', 'type=volume,src=lab-media-cache,dst=/cache',
        '--mount', 'type=volume,src=lab-media-library,dst=/media', JELLYFIN)
    (RUNTIME / 'engine.json').write_text(json.dumps({'id': info['ID'], 'host': host, 'name': info['Name']}, indent=2))
    print('Dedicated engine ID:', info['ID'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker-host', required=True)
    provision(parser.parse_args().docker_host)
