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
        assert len(connection.execute(select(OntologyEdge.id)).all()) == 2
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
