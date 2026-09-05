# SPDX-License-Identifier: GPL-3.0-only
"""Resource-aware onboarding recommendations. Does not grant permissions or operate services."""
import argparse
import json
import math
from pathlib import Path

SKILLS = {'beginner': 0, 'comfortable': 1, 'experienced': 2}
MODES = {'minimal_effort', 'learn', 'hands_on'}
DATA_MODES = {'local_only', 'cloud_allowed'}
RESOURCE_FIELDS = ('setup_eur', 'monthly_eur', 'learning_hours', 'minutes_per_week')


def require_number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{name} must be a finite non-negative number.')


def validate_answers(answers):
    if not isinstance(answers, dict):
        raise ValueError('Answers must be an object.')
    for key in RESOURCE_FIELDS:
        require_number(answers.get(key), key)
    if not isinstance(answers.get('skill'), str) or answers['skill'] not in SKILLS:
        raise ValueError('Choose beginner, comfortable or experienced skill.')
    if not isinstance(answers.get('preference'), str) or answers['preference'] not in MODES:
        raise ValueError('Choose minimal_effort, learn or hands_on preference.')
    if not isinstance(answers.get('data_preference'), str) or answers['data_preference'] not in DATA_MODES:
        raise ValueError('Choose local_only or cloud_allowed.')
    if answers.get('impact') not in ('ordinary', 'serious'):
        raise ValueError('Choose ordinary or serious impact. Unknown impact needs assessment first.')
    require_number(answers.get('acceptable_loss_eur', 0), 'acceptable_loss_eur')


def assess(answers, options):
    """Compare supplied options/estimates, never infer that spending or low effort grants authority."""
    validate_answers(answers)
    if not isinstance(options, list):
        raise ValueError('Options must be a list.')
    if answers['impact'] == 'serious':
        return {
            'status': 'specialist_review', 'recommendation': None, 'alternatives': [],
            'summary': 'This job can cause serious harm. Separate specialist design is needed before choosing automation.',
            'execution_authorized': False,
        }
    assessed = []
    seen = set()
    for option in options:
        if not isinstance(option, dict):
            raise ValueError('Each option must be an object.')
        option_id = option.get('id')
        if not isinstance(option_id, str) or not option_id or option_id in seen:
            raise ValueError('Each option needs a unique nonempty id.')
        seen.add(option_id)
        if not isinstance(option.get('name'), str) or not option['name']:
            raise ValueError('Each option needs a name.')
        if (not isinstance(option.get('minimum_skill'), str) or option['minimum_skill'] not in SKILLS
                or not isinstance(option.get('mode'), str) or option['mode'] not in MODES):
            raise ValueError('Invalid option skill or mode.')
        for field in ('local_operation_verified', 'routine_automation_verified', 'recovery_verified'):
            if type(option.get(field)) is not bool:
                raise ValueError(f'{field} must be true or false.')
        if option.get('evidence_kind') not in ('example', 'assessed'):
            raise ValueError('Option evidence_kind must be example or assessed.')
        if not isinstance(option.get('evidence'), str) or not option['evidence'].strip():
            raise ValueError('Each option needs an evidence reference or explicit example label.')
        reasons = []
        needs_assessment = False
        for key in RESOURCE_FIELDS:
            cost = option.get(key)
            if cost is None:
                needs_assessment = True
                reasons.append(f'{key}: requirement not assessed')
            else:
                require_number(cost, key)
                if cost > answers[key]:
                    reasons.append(f'{key}: needs {cost}, available {answers[key]}')
        if SKILLS[option['minimum_skill']] > SKILLS[answers['skill']]:
            reasons.append('More operating skill or a named support person is needed.')
        if answers['data_preference'] == 'local_only' and not option['local_operation_verified']:
            reasons.append('Required local-only operation has not been verified.')
        if not option['recovery_verified']:
            needs_assessment = True
            reasons.append('Recovery has not been verified for this option.')
        state = 'needs_assessment' if needs_assessment else 'does_not_fit'
        if not reasons:
            state = 'example_fit' if option['evidence_kind'] == 'example' else 'candidate_fit'
        routine = ('Eligible to propose bounded routine delegation; specific permissions still need agreement.'
                   if option['routine_automation_verified'] else
                   'Automatic observations only; routine changes still need approval and verification.')
        assessed.append({
            'id': option_id, 'name': option['name'], 'status': state,
            'reasons': reasons, 'mode': option['mode'],
            'effort': {key: option.get(key) for key in RESOURCE_FIELDS},
            'evidence_kind': option['evidence_kind'], 'evidence': option['evidence'],
            'automation': routine,
        })
    # Match desired involvement first, then minimise ongoing effort/cost. Price never expands authority.
    fits = [row for row in assessed if row['status'] in ('candidate_fit', 'example_fit')]
    fits.sort(key=lambda row: (row['evidence_kind'] != 'assessed',
                              row['mode'] != answers['preference'],
                              row['effort']['minutes_per_week'], row['effort']['monthly_eur'], row['id']))
    chosen = fits[0] if fits else None
    status = chosen['status'] if chosen else 'no_supported_fit'
    summary = ('Example only: ' if status == 'example_fit' else '') + (
        f"Start with {chosen['name']}." if chosen else
        'No assessed option fits these resources and requirements. Reduce the supported scope, add support, or reassess resources.')
    return {
        'status': status, 'summary': summary, 'recommendation': chosen,
        'alternatives': [row for row in assessed if chosen is None or row['id'] != chosen['id']],
        'loss_tolerance_eur': answers.get('acceptable_loss_eur', 0),
        'loss_tolerance_note': 'A preference to discuss per service, not spending authority or proof a loss can be contained.',
        'execution_authorized': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('answers', type=Path)
    parser.add_argument('options', type=Path)
    parser.add_argument('--details', action='store_true', help='Show reasoning, alternatives and evidence.')
    args = parser.parse_args()
    try:
        result = assess(json.loads(args.answers.read_text()), json.loads(args.options.read_text()))
    except (ValueError, OSError) as error:
        parser.exit(2, f'Cannot recommend: {error}\n')
    if args.details:
        print(json.dumps(result, indent=2))
    else:
        print(result['summary'])
        if result['recommendation']:
            print(result['recommendation']['automation'])
        print('Recommendation only. No permissions granted or services changed.')


if __name__ == '__main__':
    main()
