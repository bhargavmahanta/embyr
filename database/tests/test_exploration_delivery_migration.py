"""M5 additive delivery persistence and worker privilege boundary."""
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from conftest import make_alembic_config

BEFORE = "0017_idempotency_key_reuse"
AFTER = "0018_exploration_delivery"


def seed(connection):
    user = connection.execute(text("insert into app_users(auth_provider,auth_subject) values ('test',:s) returning id"), {"s": str(uuid4())}).scalar_one()
    entity = connection.execute(text("insert into learning_entities(canonical_key,entity_type,status) values (:k,'TOPIC','REVIEWED') returning id"), {"k": str(uuid4())}).scalar_one()
    connection.execute(text("insert into learning_entity_versions(entity_id,version,title,summary,knowledge_types,scope) values (:e,1,'Title','Summary',array['CONCEPTUAL'],'NORMAL'),(:e,2,'Title2','Summary',array['CONCEPTUAL'],'NORMAL')"), {"e": entity})
    exploration = connection.execute(text("insert into explorations(user_id,entity_id,entity_version,learning_intent,status,started_at) values (:u,:e,1,'DIRECT_INTEREST','ACTIVE',now()) returning id"), {"u": user,"e": entity}).scalar_one()
    return user, exploration


def test_delivery_upgrade_guards_downgrade_and_deletion(isolated_migration_database):
    db = isolated_migration_database
    config = make_alembic_config(db.url)
    command.upgrade(config, BEFORE)
    with db.engine.begin() as connection:
        user, exploration = seed(connection)
    command.upgrade(config, AFTER)
    with db.engine.begin() as connection:
        assert connection.execute(text("select delivery_snapshot,delivery_contract_version from explorations where id=:id"), {"id": exploration}).one() == (None, None)
        for sql in ["delivery_snapshot='{}'::jsonb", "delivery_contract_version='exploration-delivery/v1'"]:
            with pytest.raises(DBAPIError), connection.begin_nested():
                connection.execute(text(f"update explorations set {sql} where id=:id"), {"id": exploration})
        connection.execute(text("update explorations set delivery_snapshot='{}'::jsonb,delivery_contract_version='exploration-delivery/v1' where id=:id"), {"id": exploration})
        for sql in ["delivery_snapshot='{}'::jsonb,delivery_contract_version=null", "delivery_snapshot=null,delivery_contract_version=null", "delivery_snapshot='[]'::jsonb", "delivery_contract_version='v2'", "entity_version=2", "user_id=gen_random_uuid()"]:
            with pytest.raises(DBAPIError), connection.begin_nested():
                connection.execute(text(f"update explorations set {sql} where id=:id"), {"id": exploration})
        connection.execute(text("update explorations set version=version+1 where id=:id"), {"id": exploration})
        connection.execute(text("delete from app_users where id=:id"), {"id": user})
        assert connection.execute(text("select count(*) from explorations where id=:id"), {"id": exploration}).scalar_one() == 0
    command.downgrade(config, BEFORE)
    with db.engine.connect() as connection:
        assert connection.execute(text("select count(*) from information_schema.columns where table_name='explorations' and column_name like 'delivery_%'")).scalar_one() == 0
        assert not connection.execute(text("select has_column_privilege('app_worker','assessment_sessions','status','UPDATE')")).scalar_one()
    command.upgrade(config, AFTER)
    command.check(config)


def test_worker_only_gets_session_finalization_columns(isolated_migrated_database):
    with isolated_migrated_database.engine.connect() as connection:
        for column in ['status','completed_at']:
            assert connection.execute(text("select has_column_privilege('app_worker','assessment_sessions',:c,'UPDATE')"), {"c": column}).scalar_one()
        for column in ['id','user_id','exploration_id','confidence_before']:
            assert not connection.execute(text("select has_column_privilege('app_worker','assessment_sessions',:c,'UPDATE')"), {"c": column}).scalar_one()
        for role, table, privilege in [('app_worker','assessment_sessions','INSERT'),('app_worker','assessment_sessions','DELETE'),('app_backend','learning_evidence','INSERT')]:
            assert not connection.execute(text("select has_table_privilege(:r,:t,:p)"), {"r":role,'t':table,'p':privilege}).scalar_one()


def test_worker_can_finalize_but_cannot_change_session_identity(isolated_migrated_database):
    with isolated_migrated_database.engine.begin() as connection:
        user, exploration = seed(connection)
        session = connection.execute(text("""
            insert into assessment_sessions
                (user_id,exploration_id,entity_version,strategy_version,
                 confidence_before,status,started_at)
            values (:u,:e,1,'assessment-strategy/v1','FUZZY','ACTIVE',now())
            returning id
        """), {"u": user, "e": exploration}).scalar_one()
        connection.execute(text("set local role app_worker"))
        connection.execute(text("""
            update assessment_sessions set status='COMPLETED',completed_at=now()
            where id=:id
        """), {"id": session})
        for assignment in ["confidence_before='MAIN_IDEA'", "entity_version=2", "user_id=gen_random_uuid()"]:
            with pytest.raises(DBAPIError), connection.begin_nested():
                connection.execute(text(f"update assessment_sessions set {assignment} where id=:id"), {"id": session})
        assert connection.execute(text("select status from assessment_sessions where id=:id"), {"id": session}).scalar_one() == 'COMPLETED'
