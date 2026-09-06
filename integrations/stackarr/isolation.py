# SPDX-License-Identifier: GPL-3.0-only
"""Read-only socket/config pairing guard shared by provisioning and acceptance."""
from pathlib import Path
import stat

import yaml


class UniqueSafeLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError('Ambiguous duplicate YAML key')
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def lab_socket_path():
    """The one supported reference socket; no runtime discovery or adoption."""
    return Path.home() / '.colima/lab/docker.sock'


def validate_isolation(host):
    home = Path.home()
    expected_socket = lab_socket_path()
    config_path = home / '.colima/_lima/colima-lab/lima.yaml'
    if not isinstance(host, str) or not host.startswith('unix:///'):
        raise ValueError('Dedicated absolute Unix socket required')
    try:
        supplied = Path(host.removeprefix('unix://')).resolve(strict=True)
        expected = expected_socket.resolve(strict=True)
        if supplied != expected or not stat.S_ISSOCK(supplied.stat().st_mode):
            raise ValueError('Socket is not the actual dedicated lab socket')
        # Reject relocated/symlinked pairing records, which could describe another VM.
        if config_path.is_symlink() or config_path.resolve(strict=True) != config_path.absolute():
            raise ValueError('Unexpected relocated VM configuration')
        config = yaml.load(config_path.read_text(), Loader=UniqueSafeLoader)
    except (OSError, yaml.YAMLError, TypeError) as error:
        raise ValueError('Cannot verify dedicated socket/configuration pairing') from error
    if not isinstance(config, dict) or config.get('vmType') != 'vz':
        raise ValueError('Expected the dedicated VZ VM configuration')
    if config.get('mounts') not in (None, []):
        raise ValueError('Host mounts are outside the trial')
    ssh = config.get('ssh')
    if not isinstance(ssh, dict) or ssh.get('forwardAgent') is not False or ssh.get('loadDotSSHPubKeys') is not False:
        raise ValueError('SSH agent/key isolation is not verified')
    forwards = config.get('portForwards')
    if not isinstance(forwards, list) or any(not isinstance(f, dict) for f in forwards):
        raise ValueError('Socket forwarding configuration missing')
    docker = [f for f in forwards if f.get('guestSocket') == '/var/run/docker.sock']
    if len(docker) != 1 or docker[0].get('hostSocket') != str(expected_socket):
        raise ValueError('VM Docker socket is not paired to the supplied socket')
    return {'socket': str(expected), 'config': str(config_path)}
