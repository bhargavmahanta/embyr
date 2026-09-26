"""Response validation locks canonical history without backend ontology writes."""
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
import pytest
from alembic import command

from conftest import make_alembic_config
from test_assessment_schema import _valid_graph, _insert_user


def insert_response(connection, graph):
    return connection.execute(text("""
        insert into assessment_responses
          (user_id,assessment_session_id,interaction_id,response_type,response_content)
        values (:user_id,:session_id,:interaction_id,'FREE_TEXT','{"text":"Answer"}'::jsonb)
        returning id
    """), graph).scalar_one()


def test_owned_backend_answer_and_crossowner_boundary(isolated_migrated_database):
    with isolated_migrated_database.engine.begin() as connection:
        graph = _valid_graph(connection)
        other = _insert_user(connection)
        foreign_graph = _valid_graph(connection)
        connection.execute(text("set local role app_backend"))
        connection.execute(text("select set_config('app.user_id',:u,true)"), {'u': str(graph['user_id'])})
        assert insert_response(connection, graph)
        assert not connection.scalar(text("select has_table_privilege('app_backend','learning_objectives','UPDATE')"))
        assert not connection.scalar(text("select has_table_privilege('app_backend','learning_evidence','INSERT')"))
        with pytest.raises(DBAPIError) as error, connection.begin_nested():
            insert_response(connection, {**foreign_graph, "user_id": graph["user_id"]})
        assert error.value.orig.sqlstate == "23503"
        # A caller-controlled temporary relation must not shadow the catalog
        # used to decide whether the invoker is a trusted administrator.
        connection.execute(text("create temporary table pg_roles (rolname text, rolsuper boolean) on commit drop"))
        connection.execute(text("insert into pg_roles values ('app_backend',true)"))
        connection.execute(text("select set_config('app.user_id',:u,true)"), {'u': str(other)})
        with pytest.raises(DBAPIError) as error, connection.begin_nested():
            insert_response(connection, graph)
        assert error.value.orig.sqlstate == "42501"
        assert "transaction identity" in str(error.value.orig)


def test_trigger_security_and_metadata(isolated_migrated_database):
    db = isolated_migrated_database
    with db.engine.connect() as connection:
        row = connection.execute(text("""
            select p.prosecdef,p.proconfig,r.rolname
              from pg_proc p join pg_roles r on r.oid=p.proowner
             where p.oid='public.validate_assessment_response_objective_version()'::regprocedure
        """)).one()
        assert row.prosecdef
        assert row.rolname == 'app_maintenance'
        assert 'search_path=pg_catalog, public' in row.proconfig
        assert not connection.scalar(text("select has_function_privilege('app_backend','public.validate_assessment_response_objective_version()','EXECUTE')"))
        for table in ["assessment_interactions", "assessment_sessions", "explorations", "learning_objectives"]:
            assert connection.scalar(text("select has_column_privilege('app_maintenance',:t,'id','UPDATE')"), {"t": table})
            assert not connection.scalar(text("select has_table_privilege('app_maintenance',:t,'UPDATE')"), {"t": table})
        assert not connection.scalar(text("select has_column_privilege('app_backend','learning_objectives','id','UPDATE')"))
    command.check(make_alembic_config(db.url))



def test_security_upgrade_downgrade(isolated_migration_database):
    db = isolated_migration_database
    config = make_alembic_config(db.url)
    command.upgrade(config, "0018_exploration_delivery")
    command.upgrade(config, "0019_response_lock_security")
    command.downgrade(config, "0018_exploration_delivery")
    with db.engine.connect() as connection:
        assert not connection.scalar(text("select prosecdef from pg_proc where oid='public.validate_assessment_response_objective_version()'::regprocedure"))
        assert not connection.scalar(text("select has_column_privilege('app_maintenance','learning_objectives','id','UPDATE')"))
    command.upgrade(config, "head")
    command.check(config)
