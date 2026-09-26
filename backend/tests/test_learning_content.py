import copy
import json
from uuid import UUID

import pytest

from app.learning import content


def attest(monkeypatch, tmp_path):
    path = tmp_path / 'review.json'
    path.write_text(json.dumps({'package_sha256': content.package_digest(), 'reviewer': 'Explicit test reviewer', 'reviewed_at': '2026-09-26T00:00:00Z', 'decision': 'APPROVED', 'review_kind': 'TEST'}))
    monkeypatch.setenv('EMBYR_CONTENT_REVIEW_ATTESTATION', str(path))
    monkeypatch.setenv('EMBYR_CONTENT_ALLOW_TEST_ATTESTATION', '1')


def test_unreviewed_package_cannot_be_delivered(monkeypatch):
    monkeypatch.delenv('EMBYR_CONTENT_REVIEW_ATTESTATION', raising=False)
    assert content.get_definition(content.starter_entity_ids()[0], 1) is None


def test_exact_version_immutable_copy_and_public_redaction(monkeypatch, tmp_path):
    attest(monkeypatch, tmp_path)
    entity = content.starter_entity_ids()[0]
    definition = content.get_definition(entity, 1)
    assert definition is not None
    content.validate_definition(definition)
    assert content.get_definition(entity, 2) is None
    public = content.public_delivery(definition)
    assert 'assessment' not in public
    assert 'option_results' not in json.dumps(public)
    definition['work_prompt'] = 'changed'
    assert content.get_definition(entity, 1)['work_prompt'] != 'changed'


@pytest.mark.parametrize('mutation', [
    lambda d: d['assessment']['options'].append(copy.deepcopy(d['assessment']['options'][0])),
    lambda d: d['assessment']['option_results'].pop('not-sure'),
    lambda d: d['assessment']['support'].pop('EXPLANATION'),
    lambda d: d['assessment'].update(objective_id=str(UUID(int=9))),
    lambda d: d.update(delivery_contract_version='future'),
    lambda d: next(v for v in d['assessment']['option_results'].values() if v['result'] == 'SUPPORTED').update(result='UNCERTAIN'),
])
def test_invalid_definition_rejected(mutation):
    definition = copy.deepcopy(content.load_package()['definitions'][0])
    mutation(definition)
    with pytest.raises(ValueError):
        content.validate_definition(definition)


def test_coverage_is_exact_and_independent_of_ranking(monkeypatch, tmp_path):
    attest(monkeypatch, tmp_path)
    rows = [(UUID(d['entity_id']), d['entity_version']) for d in content.load_package()['definitions']]
    content.require_coverage(rows)
    with pytest.raises(ValueError, match='coverage'):
        content.require_coverage(rows + [(UUID(int=99), 1)])


@pytest.mark.parametrize('mutation', [
    lambda a: a['options'][0].update(id=[]),
    lambda a: a.update(options=None),
    lambda a: a.update(support=None),
    lambda a: a.update(option_results=[]),
    lambda a: a.update(evaluator_version='future'),
])
def test_assessment_validator_normalizes_malformed_structures(mutation):
    assessment = content.load_package()['definitions'][0]['assessment']
    mutation(assessment)
    with pytest.raises(ValueError):
        content.validate_assessment(assessment)


def test_review_digest_change_and_test_attestation_disabled_fail_closed(monkeypatch, tmp_path):
    attest(monkeypatch, tmp_path)
    monkeypatch.delenv('EMBYR_CONTENT_ALLOW_TEST_ATTESTATION')
    assert content.get_definition(content.starter_entity_ids()[0], 1) is None
    monkeypatch.setenv('EMBYR_CONTENT_ALLOW_TEST_ATTESTATION', '1')
    path = tmp_path / 'review.json'
    data = json.loads(path.read_text())
    data['package_sha256'] = '0' * 64
    path.write_text(json.dumps(data))
    assert content.get_definition(content.starter_entity_ids()[0], 1) is None


def test_public_delivery_drops_unknown_private_fields():
    definition = content.load_package()['definitions'][0]
    definition['secret'] = 'private marker'
    definition['assessment']['secret'] = 'another private marker'
    public = content.public_delivery(definition)
    assert 'private marker' not in json.dumps(public)


def test_public_recognition_option_ids_are_opaque_and_not_answer_keys():
    for definition in content.load_package()['definitions']:
        assessment = definition['assessment']
        public_options = [{key: option[key] for key in ('id', 'label')}
                          for option in assessment['options']]
        for option in public_options:
            if option['id'] == 'not-sure':
                continue
            assert str(UUID(option['id'])) == option['id']
            assert option['id'] in assessment['option_results']
        assert {option['id'] for option in public_options}.isdisjoint({'correct', 'incorrect'})


@pytest.mark.parametrize('approval', [None, [], 'approved', 1, True])
def test_malformed_top_level_approval_is_rejected_and_runtime_unavailable(monkeypatch, tmp_path, approval):
    with pytest.raises(ValueError):
        content.validate_attestation(approval)
    path = tmp_path / 'malformed.json'
    path.write_text(json.dumps(approval))
    monkeypatch.setenv('EMBYR_CONTENT_REVIEW_ATTESTATION', str(path))
    assert content.get_definition(content.starter_entity_ids()[0], 1) is None
