"""Explicit, atomic ontology provisioning using a separately supplied operator URL."""
import argparse
import json
import os
from pathlib import Path
from uuid import UUID, uuid5

from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects.postgresql import insert

from app.db.models.ontology import EntityDomain, LearningEntity, LearningEntityVersion, LearningObjective, OntologyEdge
from app.learning.content import load_package, validate_attestation


def _ensure(connection, model, values, identity):
    table = model.__table__
    connection.execute(insert(table).values(**values).on_conflict_do_nothing())
    predicate = [table.c[key] == value for key, value in identity.items()]
    actual = connection.execute(select(table).where(*predicate)).mappings().one_or_none()
    if actual is None or any(actual[key] != value for key, value in values.items()):
        raise ValueError(f'Immutable pilot identity conflicts in {table.name}')


def provision(connection, attestation, *, allow_test=False):
    """Caller owns transaction; all writes roll back on any conflict or gap."""
    validate_attestation(attestation, allow_test=allow_test)
    package = load_package()
    namespace = UUID(package['package_id'])
    connection.execute(text('select pg_advisory_xact_lock(548523907)'))
    provenance = {'content_package_id': package['package_id'], 'content_package_version': package['package_version']}
    domain_id = UUID(next(e['id'] for e in package['entities'] if e['entity_type'] == 'DOMAIN'))
    for entity in package['entities']:
        entity_id = UUID(entity['id'])
        # Null current_version permits the cyclic entity/version FK to be populated.
        connection.execute(insert(LearningEntity).values(id=entity_id, canonical_key=entity['canonical_key'], entity_type=entity['entity_type'], status='REVIEWED', current_version=None).on_conflict_do_nothing())
        existing = connection.execute(select(LearningEntity.__table__).where(LearningEntity.id == entity_id)).mappings().one_or_none()
        if existing is None or any(existing[k] != entity[k] for k in ('canonical_key', 'entity_type')) or existing['status'] not in {'REVIEWED','PUBLISHED'} or existing['current_version'] not in {None,1}:
            raise ValueError('Immutable pilot entity identity conflicts')
        _ensure(connection, LearningEntityVersion, dict(id=uuid5(namespace, entity['canonical_key']+'/version/1'), entity_id=entity_id, version=1, title=entity['title'], summary=entity['summary'], knowledge_types=['CONCEPTUAL'], scope='NORMAL', difficulty_prior=0.1, estimated_effort_minutes=10, provenance=provenance, source_metadata={'content_review':attestation}), {'entity_id':entity_id, 'version':1})
        connection.execute(LearningEntity.__table__.update().where(LearningEntity.id == entity_id, LearningEntity.current_version.is_(None)).values(current_version=1))
        _ensure(connection, LearningObjective, dict(id=UUID(entity['objective_id']), entity_id=entity_id, entity_version=1, objective_type='RECOGNITION', description=entity['objective'], importance=1.0), {'id':UUID(entity['objective_id'])})
        _ensure(connection, EntityDomain, dict(entity_id=entity_id, domain_id=domain_id, is_primary=True, membership_strength=1.0), {'entity_id':entity_id,'domain_id':domain_id})
    for child, parent in zip(package['entities'][1:], package['entities'][:-1]):
        for relationship, suffix in (('PART_OF', 'part-of'), ('RELATED_TO', 'related-to')):
            edge_id = uuid5(namespace, child['canonical_key']+'/'+suffix)
            _ensure(connection, OntologyEdge, dict(id=edge_id,source_entity_id=UUID(child['id']),target_entity_id=UUID(parent['id']),source_entity_version=1,target_entity_version=1,relationship_type=relationship,confidence=1.0,status='ACTIVE',provenance=provenance), {'id':edge_id})
    check_database_coverage(connection, attestation, allow_test=allow_test)


def check_database_coverage(connection, attestation, *, allow_test=False):
    validate_attestation(attestation, allow_test=allow_test)
    available = {(UUID(d['entity_id']),d['entity_version']) for d in load_package()['definitions']}
    current = connection.execute(select(LearningEntity.id,LearningEntity.current_version).where(LearningEntity.status.in_(['REVIEWED','PUBLISHED']))).all()
    if any((row.id,row.current_version) not in available for row in current):
        raise ValueError('Reviewed content coverage missing for current REVIEWED/PUBLISHED entity versions')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-attestation', required=True, type=Path)
    parser.add_argument('--check-only', action='store_true')
    arguments = parser.parse_args()
    # URL stays out of command arguments, reports and exception text.
    url = os.environ.get('EMBYR_CONTENT_OPERATOR_DATABASE_URL')
    if not url:
        parser.error('EMBYR_CONTENT_OPERATOR_DATABASE_URL is required')
    attestation = json.loads(arguments.review_attestation.read_text())
    validate_attestation(attestation)  # CLI never permits test attestation.
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            if arguments.check_only:
                check_database_coverage(connection,attestation)
            else:
                provision(connection,attestation)
    finally:
        engine.dispose()
    print('Reviewed content coverage verified.' if arguments.check_only else 'Reviewed pilot content provisioned; coverage verified.')


if __name__ == '__main__':
    main()
