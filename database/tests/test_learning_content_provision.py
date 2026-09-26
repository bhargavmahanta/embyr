import pytest
from sqlalchemy import select

from app.db.models.ontology import EntityDomain, LearningEntity, OntologyEdge
from app.learning.content import load_package, package_digest
from app.learning import provision_content


def review():
    return {'package_sha256':package_digest(), 'reviewer':'Explicit test reviewer', 'reviewed_at':'2026-09-26T00:00:00Z', 'decision':'APPROVED', 'review_kind':'TEST'}


def test_provision_rejects_test_review_by_default(isolated_migrated_database):
    with isolated_migrated_database.engine.begin() as connection:
        with pytest.raises(ValueError, match='human review'):
            provision_content.provision(connection, review())
        assert not connection.execute(select(LearningEntity.id)).all()


def test_provision_is_stable_connected_and_coverage_checks_all_current_versions(isolated_migrated_database):
    with isolated_migrated_database.engine.begin() as connection:
        provision_content.provision(connection, review(), allow_test=True)
        provision_content.provision(connection, review(), allow_test=True)
        assert len(connection.execute(select(LearningEntity.id)).all()) == 3
        assert len(connection.execute(select(OntologyEdge.id)).all()) == 4
        assert sorted(connection.execute(select(OntologyEdge.relationship_type)).scalars()) == ['PART_OF', 'PART_OF', 'RELATED_TO', 'RELATED_TO']
        assert len(connection.execute(select(EntityDomain.entity_id)).all()) == 3
        provision_content.check_database_coverage(connection, review(), allow_test=True)
        entity_id = load_package()['entities'][0]['id']
        from sqlalchemy import text
        connection.execute(text("update learning_entities set status='PUBLISHED' where id=:id"), {'id':entity_id})
        provision_content.check_database_coverage(connection, review(), allow_test=True)


def test_global_coverage_failure_rolls_back_pilot_provision(isolated_migrated_database):
    from sqlalchemy import text
    from uuid import uuid4
    engine = isolated_migrated_database.engine
    unknown = uuid4()
    with engine.begin() as connection:
        connection.execute(text("insert into learning_entities(id,canonical_key,entity_type,status) values(:id,'uncovered','TOPIC','PUBLISHED')"), {'id':unknown})
    with pytest.raises(ValueError, match='coverage'):
        with engine.begin() as connection:
            provision_content.provision(connection, review(), allow_test=True)
    with engine.connect() as connection:
        assert connection.execute(select(LearningEntity.id)).all() == [(unknown,)]


def test_provision_refuses_changed_immutable_version(isolated_migrated_database):
    from sqlalchemy import text
    with isolated_migrated_database.engine.begin() as connection:
        provision_content.provision(connection, review(), allow_test=True)
        connection.execute(text("update learning_entity_versions set title='changed'"))
        with pytest.raises(ValueError, match='Immutable'):
            with connection.begin_nested():
                provision_content.provision(connection, review(), allow_test=True)


@pytest.mark.parametrize('anchor_index', [0, 2])
def test_pilot_is_discoverable_by_frozen_bidirectional_m4_graph_retrieval(isolated_migrated_database, anchor_index):
    from uuid import UUID, uuid4
    from sqlalchemy import text
    from app.recommendation.snapshot import QUERIES, build_production_snapshot
    from app.recommendation.retrieval import retrieve_candidates

    package = load_package()
    user_id = uuid4()
    anchor_id = UUID(package['entities'][anchor_index]['id'])
    with isolated_migrated_database.engine.begin() as connection:
        provision_content.provision(connection, review(), allow_test=True)
        rows = {name: list(connection.execute(text(query), {'user_id':user_id}).mappings())
                for name, query in QUERIES.items()}
    # Explicit choice anchors the frozen input; no embedding or provider calls.
    rows['preferences'] = [{'entity_id':anchor_id, 'entity_version':1, 'preference':'MORE', 'version':1}]
    candidates = retrieve_candidates(build_production_snapshot(user_id, rows), {})
    graphs = {candidate['target_entity_id']: source['provenance']['hop_distance']
              for candidate in candidates for source in candidate['source_paths']
              if source['source'] == 'GRAPH'}
    expected = {entity['id']: abs(index - anchor_index)
                for index, entity in enumerate(package['entities']) if index != anchor_index}
    assert graphs == expected
    assert all(candidate['eligibility_state'] == 'ELIGIBLE' for candidate in candidates)
