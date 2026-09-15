from sqlalchemy import text


def test_upgrade_head_creates_foundation(migrated_connection):
    names = {
        row[0]
        for row in migrated_connection.execute(
            text("select tablename from pg_tables where schemaname = 'public'")
        )
    }

    assert {"app_users", "user_devices", "idempotency_records", "jobs"} <= names


def test_foundation_extensions_are_enabled(migrated_connection):
    extensions = {
        row[0]
        for row in migrated_connection.execute(
            text("select extname from pg_extension")
        )
    }

    assert {"pgcrypto", "vector"} <= extensions
