"""Immutable exact-version pilot definitions, gated by explicit review attestation.

Repository assets are drafts. A digest-bound external attestation is necessary
before runtime delivery; no migration or application startup provisions content.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
from uuid import UUID

LEVELS = {'SMALL_NUDGE', 'STRONG_HINT', 'MISSING_CONCEPT', 'EXPLANATION'}
CONTRACTS = {'strategy_version': 'assessment-strategy/v1',
             'interaction_contract_version': 'assessment-interaction/v1',
             'evaluator_version': 'deterministic-evaluation/v1',
             'evidence_contract_version': 'assessment-evidence/v1'}
PUBLIC_FIELDS = ('content_id', 'content_version', 'entity_id', 'entity_version',
                 'objective_id', 'delivery_contract_version', 'work_prompt',
                 'effort_guidance', 'search_nudges', 'reflection_prompt')


def _package_bytes():
    return files('app.learning').joinpath('packages/pilot-v1.json').read_bytes()


def package_digest() -> str:
    return hashlib.sha256(_package_bytes()).hexdigest()


def load_package() -> dict:
    package = json.loads(_package_bytes())
    identities = set()
    for definition in package['definitions']:
        validate_definition(definition)
        identity = (definition['entity_id'], definition['entity_version'])
        if identity in identities:
            raise ValueError('Duplicate content identity')
        identities.add(identity)
    for entity in package['entities']:
        definitions = [d for d in package['definitions'] if d['entity_id'] == entity['id']]
        if len(definitions) != 1 or definitions[0]['objective_id'] != entity['objective_id']:
            raise ValueError('Entity objective coherence')
    return package


def validate_attestation(attestation: dict, *, allow_test: bool = False) -> None:
    if (attestation.get('package_sha256') != package_digest()
            or attestation.get('decision') != 'APPROVED'
            or attestation.get('review_kind') not in ({'HUMAN', 'TEST'} if allow_test else {'HUMAN'})
            or not isinstance(attestation.get('reviewer'), str)
            or not attestation['reviewer'].strip()):
        raise ValueError('A digest-bound human review approval is required')
    try:
        reviewed_at = datetime.fromisoformat(attestation['reviewed_at'].replace('Z', '+00:00'))
        if reviewed_at.tzinfo is None:
            raise ValueError('timezone required')
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError('Review timestamp must include timezone') from exc


def _approved() -> bool:
    path = os.environ.get('EMBYR_CONTENT_REVIEW_ATTESTATION')
    if not path:
        return False
    try:
        validate_attestation(json.loads(Path(path).read_text()),
                             allow_test=os.environ.get('EMBYR_CONTENT_ALLOW_TEST_ATTESTATION') == '1')
    except (OSError, ValueError, TypeError):
        return False
    return True


def starter_entity_ids() -> list[UUID]:
    return [UUID(e['id']) for e in load_package()['entities'] if e['entity_type'] in {'DOMAIN', 'AREA'}]


def get_definition(entity_id: UUID, entity_version: int) -> dict | None:
    if not _approved():
        return None
    for definition in load_package()['definitions']:
        if definition['entity_id'] == str(entity_id) and definition['entity_version'] == entity_version:
            return deepcopy(definition)
    return None


def validate_definition(definition: dict) -> None:
    try:
        for key in ('content_id', 'entity_id', 'objective_id'):
            UUID(definition[key])
        for key in ('content_version', 'entity_version'):
            if type(definition[key]) is not int or definition[key] < 1:
                raise ValueError('Positive integer version required')
        if definition['delivery_contract_version'] != 'exploration-delivery/v1':
            raise ValueError('Unsupported delivery contract')
        for key in ('work_prompt', 'effort_guidance', 'reflection_prompt'):
            if not isinstance(definition[key], str) or not definition[key].strip():
                raise ValueError('Nonempty delivery text required')
        nudges = definition['search_nudges']
        if not isinstance(nudges, list) or not nudges or any(not isinstance(n, str) or not n.strip() for n in nudges):
            raise ValueError('Search nudges required')
        assessment = definition['assessment']
        if assessment['objective_id'] != definition['objective_id']:
            raise ValueError('Objective mismatch')
        validate_assessment(assessment)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Malformed content definition') from exc


def validate_assessment(assessment: dict) -> None:
    try:
        if any(assessment[key] != value for key, value in CONTRACTS.items()):
            raise ValueError('Unsupported assessment contract')
        UUID(assessment['objective_id'])
        UUID(assessment['rubric_id'])
        if type(assessment['rubric_version']) is not int or assessment['rubric_version'] < 1:
            raise ValueError('Invalid rubric version')
        if not isinstance(assessment['prompt'], str) or not assessment['prompt'].strip():
            raise ValueError('Recognition prompt required')
        options = assessment['options']
        ids = [option['id'] for option in options]
        if len(ids) < 3 or len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i.strip() for i in ids):
            raise ValueError('Unique recognition options required')
        if any(not isinstance(o['label'], str) or not o['label'].strip() for o in options):
            raise ValueError('Option labels required')
        mappings = assessment['option_results']
        if set(mappings) != set(ids):
            raise ValueError('Complete exact option mapping required')
        expected_confidence = {'SUPPORTED': 1.0, 'INSUFFICIENT_EVIDENCE': 1.0, 'UNCERTAIN': 0.0}
        results = []
        for option_id, result in mappings.items():
            if result['result'] not in expected_confidence or type(result['confidence']) not in (float, int) or result['confidence'] != expected_confidence[result['result']]:
                raise ValueError('Invalid deterministic result mapping')
            if not isinstance(result['feedback'], str) or not result['feedback'].strip():
                raise ValueError('Feedback required')
            results.append(result['result'])
        if results.count('SUPPORTED') != 1 or results.count('UNCERTAIN') != 1 or 'INSUFFICIENT_EVIDENCE' not in results or mappings.get('not-sure', {}).get('result') != 'UNCERTAIN':
            raise ValueError('Correct, incorrect and not-sure mappings required')
        support = assessment['support']
        if set(support) != LEVELS or any(not isinstance(s, str) or not s.strip() for s in support.values()):
            raise ValueError('Four complete support levels required')
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Malformed content definition') from exc


def public_delivery(definition: dict) -> dict:
    """Construct a positive whitelist; never serialize the private assessment."""
    validate_definition(definition)
    return {key: deepcopy(definition[key]) for key in PUBLIC_FIELDS}


def require_coverage(current_versions) -> None:
    """Release gate only; never called by recommendation ranking or retrieval."""
    missing = [(str(entity_id), version) for entity_id, version in current_versions
               if get_definition(entity_id, version) is None]
    if missing:
        raise ValueError(f'Reviewed content coverage missing for {len(missing)} current entity versions')
