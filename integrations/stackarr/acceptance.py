# SPDX-License-Identifier: GPL-3.0-only
"""Actual isolated Stackarr/Hermes/Jellyfin journey; never use a production engine.

Uses the real pinned MCP server and Hermes consent modules, with a deterministic
test approval surface. No model, cloud account, human acceptance or OS installation
claim is made. All application data is synthetic and the original is preserved.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import struct
import subprocess
import tarfile
import time
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError
import wave

from mcp_client import StackarrClient, payload
from isolation import validate_isolation

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / '.runtime'
STACKARR = 'polyphonic/stackarr@sha256:def56c90a322a7eda3faa2e13a00596673bf9c0ed77a2190283d01fa23536b28'
JELLYFIN = 'jellyfin/jellyfin@sha256:1694ff069f0c9dafb283c36765175606866769f5d72f2ed56b6a0f1be922fc37'
TOOL = 'stackarr_manage_container_resource'


class Jellyfin:
    def __init__(self, port):
        self.base = f'http://127.0.0.1:{port}'
        self.token = None
        self.user = None

    def request(self, path, body=None, method=None):
        headers = {'Content-Type': 'application/json',
                   'Authorization': 'MediaBrowser Client="Community Lab acceptance", Device="Isolated trial", DeviceId="community-lab-trial", Version="0.1.0"'}
        if self.token:
            headers['X-Emby-Token'] = self.token
        data = json.dumps(body).encode() if body is not None else None
        with urlopen(Request(self.base + path, data=data, headers=headers, method=method), timeout=10) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    def ready(self):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                with urlopen(self.base + '/health', timeout=5) as response:
                    if response.status != 200:
                        raise OSError('Jellyfin is not healthy')
                info = self.request('/System/Info/Public')
                if not info.get('Id') or not info.get('Version'):
                    raise OSError('Jellyfin is still returning startup metadata')
                if self.token:
                    self.request('/Items?limit=0')
                return info
            except (OSError, ValueError):
                time.sleep(1)
        raise RuntimeError('Jellyfin did not become ready within 60 seconds')

    def login(self, password):
        deadline = time.monotonic() + 60
        while True:
            try:
                reply = self.request('/Users/AuthenticateByName', {'Username': 'lab-owner', 'Pw': password})
                self.token = reply['AccessToken']
                self.user = reply['User']['Id']
                return
            except HTTPError as error:
                if error.code != 503 or time.monotonic() >= deadline:
                    raise
                time.sleep(1)

    def audio(self):
        return self.request('/Items?' + urlencode({'userId': self.user, 'recursive': 'true',
                            'includeItemTypes': 'Audio', 'fields': 'Path'}))['Items']


class Trial:
    def __init__(self, args):
        self.isolation = validate_isolation(args.docker_host)
        self.docker = ['docker', '--host', args.docker_host]
        self.evidence = {'started': datetime.now(timezone.utc).isoformat(), 'checks': []}
        self.out = RUNTIME / ('acceptance-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        self.out.mkdir(mode=0o700)
        self.recovery_name = 'lab-recovery-' + self.out.name.removeprefix('acceptance-').lower()
        self.info = json.loads(self.run('info', '--format', '{{json .}}'))
        if self.info['ID'] != args.engine_id or self.info['Name'] != 'colima-lab':
            raise ValueError('Dedicated engine identity mismatch')
        self.evidence['engine'] = {k: self.info[k] for k in ('ID', 'Name', 'OperatingSystem', 'Architecture', 'ServerVersion')}
        self.evidence['images'] = {'stackarr': STACKARR, 'jellyfin': JELLYFIN}
        self.ids = {}
        for name in ('lab-stackarr', 'lab-media'):
            item = self.inspect(name)
            if item['Config']['Labels'].get('community-lab.trial') != 'true':
                raise ValueError('Unowned container')
            expected_image = STACKARR if name == 'lab-stackarr' else JELLYFIN
            if item['Config']['Image'] != expected_image:
                raise ValueError('Unexpected container image')
            expected_mounts = ({'/stackarr-config': 'lab-stackarr-config'} if name == 'lab-stackarr' else
                               {'/config': 'lab-media-config', '/cache': 'lab-media-cache', '/media': 'lab-media-library'})
            volumes = {m['Destination']: m.get('Name') for m in item['Mounts'] if m['Type'] == 'volume'}
            binds = [m for m in item['Mounts'] if m['Type'] != 'volume']
            if volumes != expected_mounts:
                raise ValueError('Unexpected trial volumes')
            if name == 'lab-stackarr':
                if len(binds) != 1 or binds[0]['Source'] != '/var/run/docker.sock' or binds[0]['Destination'] != '/var/run/docker.sock':
                    raise ValueError('Unexpected management mount')
            elif binds:
                raise ValueError('Private or host mounts are outside the trial')
            if item['HostConfig']['Privileged'] or item['HostConfig']['NetworkMode'] == 'host':
                raise ValueError('Privileged or host-network containers are outside the trial')
            for bindings in item['HostConfig']['PortBindings'].values():
                if any(binding['HostIp'] != '127.0.0.1' for binding in bindings):
                    raise ValueError('Only loopback publication is allowed')
            self.ids[name] = item['Id']
        names = self.run('ps', '-a', '--format', '{{.Names}}').splitlines()
        for name in set(names) - {'lab-stackarr', 'lab-media'}:
            prior = self.inspect(name)
            if not name.startswith('lab-recovery-') or prior['State']['Running'] or prior['Config']['Labels'].get('community-lab.trial') != 'true':
                raise ValueError('Only stopped, owned earlier recovery attempts may coexist')
        self.check('isolated_engine_and_exact_images', True)

    def run(self, *args, **kwargs):
        return subprocess.check_output(self.docker + list(args), text=True, timeout=60, **kwargs).strip()

    def inspect(self, name):
        return json.loads(self.run('inspect', name))[0]

    def guard(self, name):
        validate_isolation(self.docker[2])
        item = self.inspect(name)
        if item['Id'] != self.ids[name] or item['Config']['Labels'].get('community-lab.trial') != 'true':
            raise RuntimeError('Target changed since preflight')
        return item

    def check(self, name, condition, **details):
        self.evidence['checks'].append({'name': name, 'passed': bool(condition), **details})
        (self.out / 'result.json').write_text(json.dumps(self.evidence, indent=2) + '\n')
        print(name + ': ' + ('PASS' if condition else 'FAIL'), flush=True)
        if not condition:
            raise AssertionError(name)

    def action(self, action, *, profile='admin', choice='once', baseline=False, elicitation=True, extra=None):
        before = self.guard('lab-media')['State']
        arguments = {'kind': 'container', 'action': action, 'id': 'lab-media'}
        if extra:
            arguments.update(extra)
        with StackarrClient(self.docker, profile, RUNTIME, baseline=baseline, elicitation=elicitation) as client:
            result = payload(client.call(TOOL, arguments, choice=choice))
            events = client.events
        after = self.guard('lab-media')['State']
        self.evidence.setdefault('actions', []).append({'profile': profile, 'choice': choice,
            'baseline': baseline, 'arguments': arguments, 'result': result, 'events': events,
            'before': before, 'after': after})
        return result, events, before, after

    def seed(self):
        api = Jellyfin(18096)
        info = api.ready()
        password_file = RUNTIME / 'trial-password'
        if not info['StartupWizardCompleted']:
            password = secrets.token_urlsafe(24)
            password_file.write_text(password)
            password_file.chmod(0o600)
            api.request('/Startup/Configuration', {'ServerName': 'Community Lab trial', 'UICulture': 'en-US',
                        'MetadataCountryCode': 'US', 'PreferredMetadataLanguage': 'en'})
            api.request('/Startup/User')
            api.request('/Startup/User', {'Name': 'lab-owner', 'Password': password})
            api.request('/Startup/RemoteAccess', {'EnableRemoteAccess': False, 'EnableAutomaticPortMapping': False})
            api.request('/Startup/Complete', {}, 'POST')
        password = password_file.read_text()
        api.login(password)
        media = RUNTIME / 'Community Bell.wav'
        with wave.open(str(media), 'wb') as stream:
            stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            stream.writeframes(b''.join(struct.pack('<h', int(1600 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(32000)))
        self.run('cp', str(media), 'lab-media:/media/Community Bell.wav')
        libraries = api.request('/Library/VirtualFolders')
        if not libraries:
            api.request('/Library/VirtualFolders?' + urlencode({'name': 'Community Reference', 'collectionType': 'music',
                        'paths': '/media', 'refreshLibrary': 'true'}), {'LibraryOptions': {
                        'EnableInternetProviders': False, 'EnableRealtimeMonitor': False,
                        'TypeOptions': [{'Type': t, 'MetadataFetchers': [], 'ImageFetchers': []}
                                        for t in ('MusicAlbum', 'MusicArtist', 'Audio')]}})
        api.request('/Library/Refresh', {}, 'POST')
        deadline = time.monotonic() + 60
        items = []
        while time.monotonic() < deadline:
            items = api.audio()
            if items:
                break
            time.sleep(1)
        self.check('actual_library_indexed_original_media', len(items) == 1, items=items)
        item = items[0]
        api.request('/UserFavoriteItems/' + item['Id'] + '?userId=' + api.user, {}, 'POST')
        item = api.audio()[0]
        self.check('application_favourite_saved', item['UserData']['IsFavorite'], item_id=item['Id'])
        self.evidence['media_sha256'] = hashlib.sha256(media.read_bytes()).hexdigest()
        self.evidence['original_server_id'] = info['Id']
        return api, password, item

    def backup(self, volume, filename):
        path = self.out / filename
        with path.open('wb') as output:
            subprocess.run(self.docker + ['run', '--rm', '--network', 'none', '--user', '0', '--cap-drop', 'ALL',
                           '--security-opt', 'no-new-privileges', '--mount', f'type=volume,src={volume},dst=/data,readonly',
                           '--entrypoint', 'tar', STACKARR, '-C', '/data', '-cf', '-', '.'],
                           stdout=output, check=True, timeout=60)
        path.chmod(0o600)
        with tarfile.open(path) as archive:
            for member in archive:
                if member.name.startswith('/') or '..' in Path(member.name).parts or member.issym() or member.islnk():
                    raise RuntimeError('Unexpected archive path or link')
        self.evidence.setdefault('backups', {})[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path

    def restore_volume(self, path, name):
        self.run('volume', 'create', '--label', 'community-lab.trial=true', name)
        with path.open('rb') as source:
            subprocess.run(self.docker + ['run', '--rm', '-i', '--network', 'none', '--user', '0', '--cap-drop', 'ALL',
                           '--security-opt', 'no-new-privileges', '--mount', f'type=volume,src={name},dst=/data',
                           '--entrypoint', 'tar', STACKARR, '-C', '/data', '-xf', '-', '--no-same-owner'],
                           stdin=source, check=True, timeout=60)

    def execute(self):
        api, password, original_item = self.seed()
        with StackarrClient(self.docker, 'observe', RUNTIME) as client:
            observed = payload(client.call('stackarr_get_container_overview'))
        self.check('actual_stackarr_observe', observed.get('dockerAvailable') is True,
                   counts=observed.get('counts'))
        cases = [('observe', 'once', False, True, None), ('manage', 'once', False, True, None),
                 ('admin', 'once', True, True, None), ('admin', 'decline', False, True, None),
                 ('admin', 'session', False, True, None), ('admin', 'always', False, True, None),
                 ('admin', 'cancel', False, True, None), ('admin', 'timeout', False, True, None),
                 ('admin', 'once', False, False, None),
                 ('admin', 'once', False, True, {'reason': 'x' * 210})]
        for i, (profile, choice, baseline, elicit, extra) in enumerate(cases, 1):
            result, events, before, after = self.action('restart', profile=profile, choice=choice,
                                           baseline=baseline, elicitation=elicit, extra=extra)
            self.check(f'refusal_{i}_{profile}_{choice}', result.get('accepted') is not True
                       and before['StartedAt'] == after['StartedAt'] and after['Running'],
                       baseline=baseline, elicitation=elicit)
        result, events, before, after = self.action('restart')
        self.check('approved_real_restart', result.get('accepted') is True and before['StartedAt'] != after['StartedAt']
                   and after['Running'] and len(events) == 1)
        api.ready()
        self.check('restart_independent_application_readback', api.audio()[0]['UserData']['IsFavorite'])
        try:
            result, _, _, after = self.action('stop')
            self.check('consistent_backup_service_stopped', result.get('accepted') is True and not after['Running'])
            config = self.backup('lab-media-config', 'config.tar')
            media = self.backup('lab-media-library', 'media.tar')
            self.restore_volume(config, self.recovery_name + '-config')
            self.restore_volume(media, self.recovery_name + '-media')
        finally:
            if not self.guard('lab-media')['State']['Running']:
                result, _, _, after = self.action('start')
                if result.get('accepted') is not True or not after['Running']:
                    raise RuntimeError('Original service restart failed; retained data remains available')
        api.ready()
        self.run('run', '-d', '--name', self.recovery_name, '--label', 'community-lab.trial=true',
                 '--security-opt', 'no-new-privileges', '--cap-drop', 'ALL', '--pids-limit', '256', '--memory', '768m',
                 '--publish', '127.0.0.1:18097:8096', '--mount', f'type=volume,src={self.recovery_name}-config,dst=/config',
                 '--mount', f'type=volume,src={self.recovery_name}-media,dst=/media,readonly',
                 '--mount', f'type=volume,src={self.recovery_name}-cache,dst=/cache', JELLYFIN)
        recovered = Jellyfin(18097)
        recovered_info = recovered.ready()
        recovered.login(password)
        restored_items = recovered.audio()
        self.check('recovered_application_records_and_login', len(restored_items) == 1 and
                   restored_items[0]['Id'] == original_item['Id'] and restored_items[0]['UserData']['IsFavorite'],
                   items=restored_items, server_id=recovered_info['Id'])
        download = self.out / 'recovered.wav'
        self.run('cp', self.recovery_name + ':/media/Community Bell.wav', str(download))
        self.check('recovered_media_bytes', hashlib.sha256(download.read_bytes()).hexdigest() == self.evidence['media_sha256'])
        recovery_inspect = self.inspect(self.recovery_name)
        original_inspect = self.guard('lab-media')
        orig_vols = {x.get('Name') for x in original_inspect['Mounts']}
        recovered_vols = {x.get('Name') for x in recovery_inspect['Mounts']}
        self.check('separate_recovery_instance_and_volumes', original_inspect['Id'] != recovery_inspect['Id']
                   and not orig_vols.intersection(recovered_vols))
        self.run('stop', '--time', '10', self.recovery_name)
        api.ready()
        self.check('rollback_original_remains_usable', api.audio()[0]['UserData']['IsFavorite']
                   and not self.inspect(self.recovery_name)['State']['Running'])
        self.evidence['completed'] = datetime.now(timezone.utc).isoformat()
        self.check('journey_complete', True)
        print('Local evidence:', self.out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker-host', required=True)
    parser.add_argument('--engine-id', required=True)
    parser.add_argument('--run-disposable-trial', action='store_true', required=True)
    trial = Trial(parser.parse_args())
    try:
        trial.execute()
    except BaseException as error:
        trial.evidence['failure'] = type(error).__name__ + ': ' + str(error)
        (trial.out / 'result.json').write_text(json.dumps(trial.evidence, indent=2) + '\n')
        # Retain failed recovery data without leaving a second active server.
        if trial.recovery_name in trial.run('ps', '-a', '--format', '{{.Names}}').splitlines():
            recovery = trial.inspect(trial.recovery_name)
            if recovery['Config']['Labels'].get('community-lab.trial') == 'true':
                trial.run('stop', '--time', '10', trial.recovery_name)
        raise
