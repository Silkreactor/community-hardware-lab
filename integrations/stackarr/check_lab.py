# SPDX-License-Identifier: GPL-3.0-only
"""Convenient entry to the existing doctor for the reviewed local reference."""
import argparse
import hashlib
import json
from pathlib import Path
import uuid

try:
    from doctor import RUNTIME, report, render
    from isolation import lab_socket_path
    from mcp_client import _unique_object
except ImportError:
    print('The lab checking tools are incomplete. Ask the person who set up your lab to prepare them. Nothing was installed or started.')
    raise SystemExit(2)

# Integrity anchor for the already-reviewed PR1 acceptance record. Identity is
# read from that record, never copied into another editable configuration file.
# This shortcut supports that reference only; it is not automatic enrollment.
REFERENCE = Path('acceptance-20260905T193021Z/result.json')
REFERENCE_SHA256 = '5d23085da1108455a2af0d1749ae1b11c9cddcb5673bd40c31648841d260b686'


class SetupProblem(ValueError):
    pass


def read_local(path, runtime):
    try:
        if runtime.resolve(strict=True) != runtime.absolute() or path.resolve(strict=True) != path.absolute():
            raise SetupProblem('The saved setup was moved or linked elsewhere.')
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise SetupProblem('The saved setup cannot be read safely.')
        return path.read_bytes()
    except (OSError, RuntimeError) as error:
        raise SetupProblem('The saved setup is missing or unreadable.') from error


def load_reference(runtime=RUNTIME):
    path = runtime / REFERENCE
    raw = read_local(path, runtime)
    if hashlib.sha256(raw).hexdigest() != REFERENCE_SHA256:
        raise SetupProblem('The saved setup has changed since it was verified.')
    try:
        record = json.loads(raw, object_pairs_hook=_unique_object)
        engine_id = record['engine']['ID']
        if str(uuid.UUID(engine_id)) != engine_id or record['engine']['Name'] != 'colima-lab':
            raise ValueError('Unexpected reference identity')
        host = 'unix://' + str(lab_socket_path())
        # The optional provisioning receipt is not a fallback authority. If it
        # exists it must agree exactly; never silently choose one over the other.
        setup_path = runtime / 'engine.json'
        if setup_path.exists() or setup_path.is_symlink():
            setup = json.loads(read_local(setup_path, runtime), object_pairs_hook=_unique_object)
            if setup != {'id': engine_id, 'host': host, 'name': 'colima-lab'}:
                raise SetupProblem('Two saved setup records disagree.')
        return host, engine_id, path
    except SetupProblem:
        raise
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise SetupProblem('The saved setup is incomplete or ambiguous.') from error


def main(argv=None):
    parser = argparse.ArgumentParser(prog='check-my-lab', description='Check your existing isolated lab. No login, automatic starts or repairs.')
    parser.add_argument('--details', action='store_true', help='Explain every observation')
    parser.add_argument('--json', action='store_true', help='Print structured observations')
    args = parser.parse_args(argv)
    try:
        host, engine_id, evidence = load_reference()
    except SetupProblem as error:
        result = {'state': 'unknown', 'summary': 'Your previously verified lab could not be identified.',
                  'reason': str(error), 'guidance': 'Ask the person who set up your lab to restore or review its saved setup. Nothing was started or changed.'}
        print(json.dumps(result, indent=2) if args.json else '\n'.join(result[key] for key in ('summary', 'reason', 'guidance')))
        return 2
    result = report(host, engine_id, evidence)
    print(json.dumps(result, indent=2) if args.json else render(result, args.details))
    return 0 if result['lab']['state'] == 'known' else 2


if __name__ == '__main__':
    raise SystemExit(main())
