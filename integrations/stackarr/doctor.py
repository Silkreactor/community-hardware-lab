# SPDX-License-Identifier: GPL-3.0-only
"""Read-only, no-login report for the existing isolated lab reference."""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener

from acceptance import RUNTIME, STACKARR, JELLYFIN
from isolation import validate_isolation


def finding(state, summary, guidance):
    return {'state': state, 'summary': summary, 'guidance': guidance}


def storage_result(output):
    """Parse POSIX df output. Never render filesystem or mount names."""
    try:
        rows = output.strip().splitlines()[1:]
        if len(rows) != 2:
            raise ValueError('Expected the two requested filesystems')
        volumes = []
        for label, line in zip(('System storage', 'Service storage'), rows):
            fields = line.split()
            if len(fields) != 6 or not fields[4].endswith('%'):
                raise ValueError('Invalid df row')
            total, used, available = map(int, fields[1:4])
            percent = int(fields[4][:-1])
            if total <= 0 or min(used, available, percent) < 0 or percent > 100 or used > total or available > total:
                raise ValueError('Invalid df values')
            state = 'low' if percent >= 90 or available < 1024 * 1024 else 'known'
            volumes.append({'label': label, 'state': state, 'available_gib': round(available / 1024**2, 2), 'used_percent': percent})
        low = any(v['state'] == 'low' for v in volumes)
        return {**finding('low' if low else 'known', 'Storage needs attention.' if low else 'Space is available in the checked guest filesystems.',
                         'Ask an operator to review storage before adding data; nothing was deleted.' if low else 'These are guest filesystems, not the Mac drive or a hardware-health test.'), 'volumes': volumes}
    except (ValueError, IndexError, TypeError):
        return finding('unknown', 'Storage could not be measured.', 'Ask an operator to check guest storage; unknown does not mean empty or full.')


def backup_result(evidence, engine_id, now, runtime=RUNTIME):
    unknown = finding('unknown', 'Current backup protection is not verified.', 'Keep another copy of important data and arrange a recovery check; no backup was created by this report.')
    if evidence is None:
        return unknown
    try:
        path = Path(evidence)
        root = runtime.resolve(strict=True)
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root) or path.stat().st_size > 2 * 1024**2:
            return unknown
        record = json.loads(path.read_text())
        when = datetime.fromisoformat(record['completed'])
        if when.tzinfo is None or when > now:
            return unknown
        if record['engine']['ID'] != engine_id or record['images'] != {'stackarr': STACKARR, 'jellyfin': JELLYFIN}:
            return unknown
        required = {'journey_complete', 'recovered_application_records_and_login', 'recovered_media_bytes',
                    'separate_recovery_instance_and_volumes', 'rollback_original_remains_usable'}
        checks = record['checks']
        if not isinstance(checks, list) or any(c.get('passed') is not True for c in checks):
            return unknown
        if not required.issubset({c['name'] for c in checks}):
            return unknown
        for name in ('config.tar', 'media.tar'):
            archive = path.parent / name
            if archive.is_symlink() or not archive.is_file() or archive.stat().st_size > 1024**3:
                return unknown
            with archive.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != record['backups'][name]:
                return unknown
        stale = now - when > timedelta(hours=24)
        return {**finding('stale' if stale else 'recorded',
                         'An older recovery-test record and its archives still match.' if stale else 'A recent recovery-test record and its archives still match.',
                         'This covers the earlier sample library only. New changes, off-machine copies and current recoverability are not verified.'),
                'tested_at': when.astimezone(timezone.utc).isoformat(), 'freshness_limit_hours': 24}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return unknown


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def public_jellyfin():
    # No credentials, environment proxy or redirect to another service.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(Request('http://127.0.0.1:18096/health'), timeout=5) as reply:
        if reply.status != 200:
            return False
    with opener.open(Request('http://127.0.0.1:18096/System/Info/Public'), timeout=5) as reply:
        raw = reply.read(65537)
    if len(raw) > 65536:
        return False
    info = json.loads(raw)
    return info.get('Version') == '10.11.8' and bool(info.get('Id')) and info.get('StartupWizardCompleted') is True


def report(host, engine_id, evidence=None):
    now = datetime.now(timezone.utc)
    result = {'observed_at': now.isoformat(), 'scope': 'Isolated lab reference; one-time observations, no automatic changes.',
              'services': {}, 'storage': storage_result(''),
              'backup': backup_result(evidence, engine_id, now)}

    def command(args):
        validate_isolation(host)
        env = {k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR') if k in os.environ}
        env.update(LC_ALL='C', DOCKER_CONFIG=str(RUNTIME / 'docker-config'))
        return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=15, env=env)

    docker = ['docker', '--host', host]
    try:
        info = json.loads(command(docker + ['info', '--format', '{{json .}}']))
        if info['ID'] != engine_id or info['Name'] != 'colima-lab' or info['OSType'] != 'linux':
            raise ValueError('Wrong engine')
        result['lab'] = finding('known', 'The isolated lab is reachable.', 'This check does not cover other computers or farms.')
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError):
        result['lab'] = finding('unknown', 'The isolated lab cannot be verified.', 'It may be suspended or inaccessible. Ask its operator to check the isolated lab; this report will not start it.')
        for name in ('Service manager', 'Media library'):
            result['services'][name] = finding('unknown', 'Not checked because the lab could not be verified.', 'Verify the lab connection first.')
        return result

    for name, container, image in [('Service manager', 'lab-stackarr', STACKARR), ('Media library', 'lab-media', JELLYFIN)]:
        try:
            item = json.loads(command(docker + ['inspect', container]))[0]
            if item['Config']['Labels'].get('community-lab.trial') != 'true' or item['Config']['Image'] != image:
                raise ValueError('Unsupported service')
            if type(item['State']['Running']) is not bool:
                raise ValueError('Unknown running state')
            if not item['State']['Running']:
                result['services'][name] = finding('stopped', 'The service is stopped.', 'Ask the operator whether this is intentional. No restart was attempted.')
            elif container == 'lab-stackarr':
                result['services'][name] = finding('running', 'The service-manager container is running.', 'Container state only; agent conversations and management actions were not tested.')
            else:
                bindings = item['HostConfig']['PortBindings']
                if bindings.get('8096/tcp') != [{'HostIp': '127.0.0.1', 'HostPort': '18096'}] or item['HostConfig']['NetworkMode'] == 'host':
                    raise ValueError('Unexpected endpoint')
                try:
                    responding = public_jellyfin()
                except (OSError, ValueError, AttributeError, TypeError):
                    responding = False
                result['services'][name] = finding('responding' if responding else 'unavailable',
                    'The media library responds to basic public checks.' if responding else 'The container is running, but the library is not ready.',
                    'Sign-in, playback and your records were not checked.' if responding else 'It may still be starting. Run this check again later; no repair was attempted.')
        except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError, subprocess.SubprocessError):
            result['services'][name] = finding('unknown', 'Service availability could not be verified.', 'Ask the operator to check this service; no change was attempted.')
    try:
        result['storage'] = storage_result(command(['colima', 'ssh', '--profile', 'lab', '--', 'env', 'LC_ALL=C', 'df', '-Pk', '/', '/var/lib/docker']))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return result


def render(result, details=False):
    lines = ['Lab doctor — ' + result['observed_at'], result['scope'], '', result['lab']['summary']]
    for label, item in [*result['services'].items(), ('Storage', result['storage']), ('Backup evidence', result['backup'])]:
        lines.extend(['', f'{label} [{item["state"]}]: {item["summary"]}'])
        if details or label == 'Backup evidence' or item['state'] in ('unknown', 'low', 'stopped', 'unavailable'):
            lines.append(item['guidance'])
        for volume in item.get('volumes', []):
            lines.append(f'  {volume["label"]}: {volume["available_gib"]:.2f} GiB available; {volume["used_percent"]}% used.')
        if 'tested_at' in item:
            lines.append('  Recovery test recorded: ' + item['tested_at'])
    lines.append('\nThis is a snapshot, not a guarantee of safety or a continuous monitor.')
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker-host', required=True)
    parser.add_argument('--engine-id', required=True)
    parser.add_argument('--backup-evidence', type=Path)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--details', action='store_true', help='Include explanations for every check')
    args = parser.parse_args()
    data = report(args.docker_host, args.engine_id, args.backup_evidence)
    print(json.dumps(data, indent=2) if args.json else render(data, args.details))
