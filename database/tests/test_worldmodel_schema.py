from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _assert_constraint(connection, expected: str, statement, parameters) -> None:
    with pytest.raises(IntegrityError) as error, connection.begin_nested():
        connection.execute(statement, parameters)

    assert error.value.orig.diag.constraint_name == expected


def _insert_user(connection):
    return connection.execute(
        text(
            """
            insert into app_users (auth_provider, auth_subject)
            values ('test', :subject)
            returning id
            """
        ),
        {"subject": str(uuid4())},
    ).scalar_one()


def _insert_entity(connection, *, entity_type: str = "TOPIC"):
    return connection.execute(
        text(
            """
            insert into learning_entities (canonical_key, entity_type, status)
            values (:key, :entity_type, 'REVIEWED')
            returning id
            """
        ),
        {"key": f"world-{uuid4()}", "entity_type": entity_type},
    ).scalar_one()


def _insert_world(connection, *, user_id, generation_seed=None, layout_version: int = 1):
    return connection.execute(
        text(
            """
            insert into learner_worlds (user_id, generation_seed, layout_version)
            values (:user_id, :generation_seed, :layout_version)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "generation_seed": generation_seed or uuid4().hex,
            "layout_version": layout_version,
        },
    ).scalar_one()


def _insert_region(
    connection,
    *,
    user_id,
    world_id,
    region_key=None,
    primary_domain_id=None,
    logical_width: float = 1.0,
    logical_height: float = 1.0,
):
    return connection.execute(
        text(
            """
            insert into world_regions
              (user_id, world_id, region_key, primary_domain_id, logical_x,
               logical_y, logical_width, logical_height, visual_archetype)
            values
              (:user_id, :world_id, :region_key, :primary_domain_id, 0.25,
               0.60, :logical_width, :logical_height, 'grove')
            returning id
            """
        ),
        {
            "user_id": user_id,
            "world_id": world_id,
            "region_key": region_key or f"region-{uuid4()}",
            "primary_domain_id": primary_domain_id,
            "logical_width": logical_width,
            "logical_height": logical_height,
        },
    ).scalar_one()


def _insert_node(
    connection,
    *,
    user_id,
    world_id,
    entity_id,
    region_id=None,
    depth: int = 0,
    revision: int = 1,
    growth_state: str = "SEED",
):
    return connection.execute(
        text(
            """
            insert into world_nodes
              (user_id, world_id, entity_id, region_id, logical_x, logical_y,
               depth, visual_archetype, visual_seed, growth_state,
               first_placed_at, last_growth_at, revision)
            values
              (:user_id, :world_id, :entity_id, :region_id, 0.42, 0.71,
               :depth, 'branching_tree', :visual_seed, :growth_state,
               now(), now(), :revision)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "world_id": world_id,
            "entity_id": entity_id,
            "region_id": region_id,
            "depth": depth,
            "visual_seed": uuid4().hex,
            "growth_state": growth_state,
            "revision": revision,
        },
    ).scalar_one()


def _insert_connection(
    connection,
    *,
    user_id,
    world_id,
    source_world_node_id,
    target_world_node_id,
    ontology_edge_id=None,
    revision: int = 1,
    importance: float = 0.5,
    is_visible: bool = True,
):
    return connection.execute(
        text(
            """
            insert into world_connections
              (user_id, world_id, source_world_node_id, target_world_node_id,
               ontology_edge_id, connection_type, importance, is_visible,
               revision)
            values
              (:user_id, :world_id, :source_world_node_id,
               :target_world_node_id, :ontology_edge_id, 'BUILDS_ON',
               :importance, :is_visible, :revision)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "world_id": world_id,
            "source_world_node_id": source_world_node_id,
            "target_world_node_id": target_world_node_id,
            "ontology_edge_id": ontology_edge_id,
            "importance": importance,
            "is_visible": is_visible,
            "revision": revision,
        },
    ).scalar_one()


def _insert_change(
    connection,
    *,
    user_id,
    world_id,
    revision: int,
    change_type: str = "NODE_ADDED",
    object_type: str = "NODE",
    object_id=None,
    payload=None,
):
    return connection.execute(
        text(
            """
            insert into world_changes
              (user_id, world_id, revision, change_type, object_type,
               object_id, payload)
            values
              (:user_id, :world_id, :revision, :change_type, :object_type,
               :object_id, cast(:payload as jsonb))
            returning id
            """
        ),
        {
            "user_id": user_id,
            "world_id": world_id,
            "revision": revision,
            "change_type": change_type,
            "object_type": object_type,
            "object_id": object_id or uuid4(),
            "payload": json.dumps(payload or {}),
        },
    ).scalar_one()


def _advance_revision(connection, *, user_id) -> int:
    connection.execute(
        text(
            "select current_revision from learner_worlds "
            "where user_id = :user_id for update"
        ),
        {"user_id": user_id},
    ).scalar_one()
    return connection.execute(
        text(
            """
            update learner_worlds
               set current_revision = current_revision + 1,
                   updated_at = now()
             where user_id = :user_id
            returning current_revision
            """
        ),
        {"user_id": user_id},
    ).scalar_one()


def _load_snapshot(connection, *, user_id):
    world = connection.execute(
        text(
            """
            select id, generation_seed, layout_version, current_revision
              from learner_worlds
             where user_id = :user_id
            """
        ),
        {"user_id": user_id},
    ).one()
    regions = connection.execute(
        text(
            """
            select id, region_key, logical_x, logical_y, logical_width,
                   logical_height, visual_archetype
              from world_regions
             where user_id = :user_id
             order by region_key
            """
        ),
        {"user_id": user_id},
    ).all()
    nodes = connection.execute(
        text(
            """
            select id, entity_id, region_id, logical_x, logical_y, depth,
                   growth_state, revision
              from world_nodes
             where user_id = :user_id
             order by id
            """
        ),
        {"user_id": user_id},
    ).all()
    connections = connection.execute(
        text(
            """
            select id, source_world_node_id, target_world_node_id,
                   connection_type, importance, is_visible, revision
              from world_connections
             where user_id = :user_id
             order by id
            """
        ),
        {"user_id": user_id},
    ).all()
    artifacts = connection.execute(
        text(
            """
            select id, artifact_id, region_id, logical_x, logical_y, depth,
                   revision
              from world_artifacts
             where user_id = :user_id
             order by id
            """
        ),
        {"user_id": user_id},
    ).all()
    return {
        "revision": world.current_revision,
        "layout_version": world.layout_version,
        "generation_seed": world.generation_seed,
        "regions": regions,
        "nodes": nodes,
        "connections": connections,
        "artifacts": artifacts,
    }


def _load_changes(connection, *, world_id, after_revision: int, limit: int):
    rows = connection.execute(
        text(
            """
            select id, revision, change_type, object_type, object_id, payload
              from world_changes
             where world_id = :world_id
               and revision > :after_revision
             order by revision
             limit :limit
            """
        ),
        {
            "world_id": world_id,
            "after_revision": after_revision,
            "limit": limit,
        },
    ).all()
    head = connection.execute(
        text("select current_revision from learner_worlds where id = :world_id"),
        {"world_id": world_id},
    ).scalar_one()
    to_revision = rows[-1].revision if rows else after_revision
    has_more = connection.execute(
        text(
            """
            select exists(
                select 1 from world_changes
                 where world_id = :world_id and revision > :to_revision
            )
            """
        ),
        {"world_id": world_id, "to_revision": to_revision},
    ).scalar_one()
    return to_revision, head, has_more, rows


def _resync_required(connection, *, world_id, after_revision: int) -> bool:
    oldest = connection.execute(
        text("select min(revision) from world_changes where world_id = :world_id"),
        {"world_id": world_id},
    ).scalar_one()
    if oldest is None:
        return False
    return oldest > after_revision + 1


def _insert_practical_graph(connection, *, user_id=None):
    user_id = user_id or _insert_user(connection)
    entity_id = connection.execute(
        text(
            """
            insert into learning_entities (canonical_key, entity_type, status)
            values (:key, 'TECHNIQUE', 'REVIEWED') returning id
            """
        ),
        {"key": f"artifact-{uuid4()}"},
    ).scalar_one()
    connection.execute(
        text(
            """
            insert into learning_entity_versions
              (entity_id, version, title, summary, knowledge_types, scope)
            values
              (:entity_id, 1, 'Artifact topic', 'Summary',
               array['PROCEDURAL'], 'NORMAL')
            """
        ),
        {"entity_id": entity_id},
    )
    challenge_id = connection.execute(
        text(
            """
            insert into practical_challenges (entity_id)
            values (:entity_id) returning id
            """
        ),
        {"entity_id": entity_id},
    ).scalar_one()
    challenge_version_id = connection.execute(
        text(
            """
            insert into practical_challenge_versions
              (challenge_id, entity_id, entity_version, version, prompt,
               target_techniques, estimated_effort_minutes, materials,
               environment_constraints, physical_requirements,
               evidence_requirements, status)
            values
              (:challenge_id, :entity_id, 1, 1, 'Make an artifact',
               '["composition"]'::jsonb, 30, '["paper"]'::jsonb,
               '[]'::jsonb, '[]'::jsonb, '{"media":["image"]}'::jsonb,
               'REVIEWED')
            returning id
            """
        ),
        {"challenge_id": challenge_id, "entity_id": entity_id},
    ).scalar_one()
    exploration_id = connection.execute(
        text(
            """
            insert into explorations
              (user_id, entity_id, entity_version, practical_challenge_id,
               practical_challenge_version_id, learning_intent, status,
               started_at)
            values
              (:user_id, :entity_id, 1, :challenge_id,
               :challenge_version_id, 'PRACTICAL_SUPPORT', 'ACTIVE', now())
            returning id
            """
        ),
        {
            "user_id": user_id,
            "entity_id": entity_id,
            "challenge_id": challenge_id,
            "challenge_version_id": challenge_version_id,
        },
    ).scalar_one()
    reflection_id = connection.execute(
        text(
            """
            insert into reflections (user_id, exploration_id, entity_id, text)
            values (:user_id, :exploration_id, :entity_id, 'Reflection')
            returning id
            """
        ),
        {
            "user_id": user_id,
            "exploration_id": exploration_id,
            "entity_id": entity_id,
        },
    ).scalar_one()
    return {
        "user_id": user_id,
        "entity_id": entity_id,
        "challenge_id": challenge_id,
        "challenge_version_id": challenge_version_id,
        "exploration_id": exploration_id,
        "reflection_id": reflection_id,
    }


def _insert_artifact(connection, graph):
    object_key = f"users/{graph['user_id']}/artifacts/{uuid4()}"
    upload_id = connection.execute(
        text(
            """
            insert into upload_sessions
              (user_id, purpose, declared_content_type, declared_size_bytes,
               object_key, status, completed_at, validated_at)
            values
              (:user_id, 'ARTIFACT', 'image/jpeg', 1024, :object_key,
               'VALIDATED', now(), now())
            returning id
            """
        ),
        {"user_id": graph["user_id"], "object_key": object_key},
    ).scalar_one()
    media_object_id = connection.execute(
        text(
            """
            insert into media_objects
              (user_id, upload_id, object_key, validated_content_type,
               validated_size_bytes, sha256, metadata_stripped)
            values
              (:user_id, :upload_id, :object_key, 'image/jpeg', 1000,
               :sha256, true)
            returning id
            """
        ),
        {
            "user_id": graph["user_id"],
            "upload_id": upload_id,
            "object_key": object_key,
            "sha256": uuid4().hex,
        },
    ).scalar_one()
    return connection.execute(
        text(
            """
            insert into artifacts
              (user_id, practical_challenge_id,
               practical_challenge_version_id, exploration_id,
               media_object_id, reflection_id)
            values
              (:user_id, :challenge_id, :challenge_version_id,
               :exploration_id, :media_object_id, :reflection_id)
            returning id
            """
        ),
        {**graph, "media_object_id": media_object_id},
    ).scalar_one()


def _insert_world_artifact(
    connection,
    *,
    user_id,
    world_id,
    artifact_id,
    region_id=None,
    revision: int = 1,
):
    return connection.execute(
        text(
            """
            insert into world_artifacts
              (user_id, world_id, artifact_id, region_id, logical_x,
               logical_y, depth, visual_archetype, visual_seed, revision)
            values
              (:user_id, :world_id, :artifact_id, :region_id, 0.55, 0.35,
               0, 'landmark', :visual_seed, :revision)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "world_id": world_id,
            "artifact_id": artifact_id,
            "region_id": region_id,
            "visual_seed": uuid4().hex,
            "revision": revision,
        },
    ).scalar_one()


def test_learner_world_can_be_created(migrated_connection):
    user_id = _insert_user(migrated_connection)

    world_id = _insert_world(migrated_connection, user_id=user_id)

    row = migrated_connection.execute(
        text(
            "select current_revision, layout_version from learner_worlds "
            "where id = :id"
        ),
        {"id": world_id},
    ).one()
    assert row[0] == 0
    assert row[1] == 1


def test_learner_has_at_most_one_world(migrated_connection):
    user_id = _insert_user(migrated_connection)
    _insert_world(migrated_connection, user_id=user_id)

    _assert_constraint(
        migrated_connection,
        "uq_learner_worlds_user_id",
        text(
            """
            insert into learner_worlds (user_id, generation_seed, layout_version)
            values (:user_id, 'seed', 1)
            """
        ),
        {"user_id": user_id},
    )


def test_negative_current_revision_rejected(migrated_connection):
    user_id = _insert_user(migrated_connection)

    _assert_constraint(
        migrated_connection,
        "ck_learner_worlds_current_revision",
        text(
            """
            insert into learner_worlds
              (user_id, generation_seed, layout_version, current_revision)
            values (:user_id, 'seed', 1, -1)
            """
        ),
        {"user_id": user_id},
    )


def test_region_requires_positive_dimensions(migrated_connection):
    user_id = _insert_user(migrated_connection)
    world_id = _insert_world(migrated_connection, user_id=user_id)

    _assert_constraint(
        migrated_connection,
        "ck_world_regions_logical_width",
        text(
            """
            insert into world_regions
              (user_id, world_id, region_key, logical_x, logical_y,
               logical_width, logical_height, visual_archetype)
            values (:user_id, :world_id, 'tech', 0, 0, 0, 1, 'grove')
            """
        ),
        {"user_id": user_id, "world_id": world_id},
    )


def test_region_rejects_cross_user_world(migrated_connection):
    owner_id = _insert_user(migrated_connection)
    other_id = _insert_user(migrated_connection)
    owner_world = _insert_world(migrated_connection, user_id=owner_id)

    _assert_constraint(
        migrated_connection,
        "fk_world_regions_world_owner",
        text(
            """
            insert into world_regions
              (user_id, world_id, region_key, logical_x, logical_y,
               logical_width, logical_height, visual_archetype)
            values (:user_id, :world_id, 'tech', 0, 0, 1, 1, 'grove')
            """
        ),
        {"user_id": other_id, "world_id": owner_world},
    )


def test_region_accepts_primary_domain(migrated_connection):
    user_id = _insert_user(migrated_connection)
    world_id = _insert_world(migrated_connection, user_id=user_id)
    domain_id = _insert_entity(migrated_connection, entity_type="DOMAIN")

    region_id = _insert_region(
        migrated_connection,
        user_id=user_id,
        world_id=world_id,
        primary_domain_id=domain_id,
    )

    stored = migrated_connection.execute(
        text("select primary_domain_id from world_regions where id = :id"),
        {"id": region_id},
    ).scalar_one()
    assert stored == domain_id


def test_node_requires_distinct_entity_per_world(migrated_connection):
    user_id = _insert_user(migrated_connection)
    world_id = _insert_world(migrated_connection, user_id=user_id)
    entity_id = _insert_entity(migrated_connection)
    _insert_node(
        migrated_connection, user_id=user_id, world_id=world_id, entity_id=entity_id
    )

    _assert_constraint(
        migrated_connection,
        "uq_world_nodes_world_entity",
        text(
            """
            insert into world_nodes
              (user_id, world_id, entity_id, logical_x, logical_y, depth,
               visual_archetype, visual_seed, growth_state, first_placed_at,
               last_growth_at, revision)
            values
              (:user_id, :world_id, :entity_id, 0.1, 0.1, 0, 'branching_tree',
               'seed', 'SEED', now(), now(), 1)
            """
        ),
        {"user_id": user_id, "world_id": world_id, "entity_id": entity_id},
    )


def test_node_rejects_negative_depth(migrated_connection):
    user_id = _insert_user(migrated_connection)
    world_id = _insert_world(migrated_connection, user_id=user_id)
    entity_id = _insert_entity(migrated_connection)

    _assert_constraint(
        migrated_connection,
        "ck_world_nodes_depth",
        text(
            """
            insert into world_nodes
              (user_id, world_id, entity_id, logical_x, logical_y, depth,
               visual_archetype, visual_seed, growth_state, first_placed_at,
               last_growth_at, revision)
            values
              (:user_id, :world_id, :entity_id, 0.1, 0.1, -1, 'branching_tree',
               'seed', 'SEED', now(), now(), 1)
            """
        ),
        {"user_id": user_id, "world_id": world_id, "entity_id": entity_id},
    )


def test_node_rejects_cross_user_world(migrated_connection):
    owner_id = _insert_user(migrated_connection)
    other_id = _insert_user(migrated_connection)
    owner_world = _insert_world(migrated_connection, user_id=owner_id)
    entity_id = _insert_entity(migrated_connection)

    _assert_constraint(
        migrated_connection,
        "fk_world_nodes_world_owner",
        text(
            """
            insert into world_nodes
              (user_id, world_id, entity_id, logical_x, logical_y, depth,
               visual_archetype, visual_seed, growth_state, first_placed_at,
               last_growth_at, revision)
            values
              (:user_id, :world_id, :entity_id, 0.1, 0.1, 0, 'branching_tree',
               'seed', 'SEED', now(), now(), 1)
            """
        ),
        {"user_id": other_id, "world_id": owner_world, "entity_id": entity_id},
    )


def test_node_rejects_cross_user_region(migrated_connection):
    owner_id = _insert_user(migrated_connection)
    other_id = _insert_user(migrated_connection)
    owner_world = _insert_world(migrated_connection, user_id=owner_id)
    other_world = _insert_world(migrated_connection, user_id=other_id)
    other_region = _insert_region(
        migrated_connection, user_id=other_id, world_id=other_world
    )
    entity_id = _insert_entity(migrated_connection)

    _assert_constraint(
        migrated_connection,
        "fk_world_nodes_region_owner",
        text(
            """
            insert into world_nodes
              (user_id, world_id, entity_id, region_id, logical_x, logical_y,
               depth, visual_archetype, visual_seed, growth_state,
               first_placed_at, last_growth_at, revision)
            values
              (:user_id, :world_id, :entity_id, :region_id, 0.1, 0.1, 0,
               'branching_tree', 'seed', 'SEED', now(), now(), 1)
            """
        ),
        {
            "user_id": owner_id,
            "world_id": owner_world,
            "entity_id": entity_id,
            "region_id": other_region,
        },
    )


def test_node_growth_state_is_not_constrained(migrated_connection):
    user_id = _insert_user(migrated_connection)
    world_id = _insert_world(migrated_connection, user_id=user_id)
    entity_id = _insert_entity(migrated_connection)

    node_id = _insert_node(
        migrated_connection,
        user_id=user_id,
        world_id=world_id,
        entity_id=entity_id,
        growth_state="EMERGENT_CANOPY",
    )

    stored = migrated_connection.execute(
        text("select growth_state from world_nodes where id = :id"),
        {"id": node_id},
    ).scalar_one()
    assert stored == "EMERGENT_CANOPY"


def test_connection_rejects_cross_user_source_node(migrated_connection):
    owner_id = _insert_user(migrated_connection)
    other_id = _insert_user(migrated_connection)
    owner_world = _insert_world(migrated_connection, user_id=owner_id)
    other_world = _insert_world(migrated_connection, user_id=other_id)
    entity = _insert_entity(migrated_connection)
    other_entity = _insert_entity(migrated_connection)
    owner_node = _insert_node(
        migrated_connection, user_id=owner_id, world_id=owner_world, entity_id=entity
    )
    other_node = _insert_node(
        migrated_connection,
        user_id=other_id,
        world_id=other_world,
        entity_id=other_entity,
    )

    _assert_constraint(
        migrated_connection,
        "fk_world_connections_source_node_owner",
        text(
            """
            insert into world_connections
              (user_id, world_id, source_world_node_id, target_world_node_id,
               connection_type, importance, is_visible, revision)
            values
              (:user_id, :world_id, :source, :target, 'BUILDS_ON', 0.5, true, 1)
            """
        ),
        {
            "user_id": other_id,
            "world_id": other_world,
            "source": owner_node,
            "target": other_node,
        },
    )


def test_connection_rejects_cross_user_target_node(migrated_connection):
    owner_id = _insert_user(migrated_connection)
    other_id = _insert_user(migrated_connection)
    owner_world = _insert_world(migrated_connection, user_id=owner_id)
    other_world = _insert_world(migrated_connection, user_id=other_id)
    entity = _insert_entity(migrated_connection)
    other_entity = _insert_entity(migrated_connection)
    owner_node = _insert_node(
        migrated_connection, user_id=owner_id, world_id=owner_world, entity_id=entity
    )
    other_node = _insert_node(
        migrated_connection,
        user_id=other_id,
        world_id=other_world,
        entity_id=other_entity,
    )

    _assert_constraint(
        migrated_connection,
        "fk_world_connections_target_node_owner",
        text(
            """
            insert into world_connections
              (user_id, world_id, source_world_node_id, target_world_node_id,
               connection_type, importance, is_visible, revision)
            values
              (:user_id, :world_id, :source, :target, 'BUILDS_ON', 0.5, true, 1)
            """
        ),
        {
            "user_id": other_id,
            "world_id": other_world,
            "source": other_node,
            "target": owner_node,
        },
    )


def test_connection_accepts_ontology_edge(migrated_connection):
    user_id = _insert_user(migrated_connection)
    world_id = _insert_world(migrated_connection, user_id=user_id)
    source_entity = _insert_entity(migrated_connection)
    target_entity = _insert_entity(migrated_connection)
    source_node = _insert_node(
        migrated_connection,
        user_id=user_id,
        world_id=world_id,
        entity_id=source_entity,
    )
    target_node = _insert_node(
        migrated_connection,
        user_id=user_id,
        world_id=world_id,
        entity_id=target_entity,
    )
    edge_id = migrated_connection.execute(
        text(
            """
            insert into ontology_edges
              (source_entity_id, target_entity_id, relationship_type,
               confidence, status)
            values (:source, :target, 'BUILDS_ON', 0.9, 'REVIEWED')
            returning id
            """
        ),
        {"source": source_entity, "target": target_entity},
    ).scalar_one()

    connection_id = _insert_connection(
        migrated_connection,
        user_id=user_id,
        world_id=world_id,
        source_world_node_id=source_node,
        target_world_node_id=target_node,
        ontology_edge_id=edge_id,
    )

    stored = migrated_connection.execute(
        text("select ontology_edge_id from world_connections where id = :id"),
        {"id": connection_id},
    ).scalar_one()
    assert stored == edge_id


def test_world_artifact_requires_per_world_uniqueness(migrated_connection):
    graph = _insert_practical_graph(migrated_connection)
    user_id = graph["user_id"]
    world_id = _insert_world(migrated_connection, user_id=user_id)
    artifact_id = _insert_artifact(migrated_connection, graph)
    _insert_world_artifact(
        migrated_connection,
        user_id=user_id,
        world_id=world_id,
        artifact_id=artifact_id,
    )

    _assert_constraint(
        migrated_connection,
        "uq_world_artifacts_world_artifact",
        text(
            """
            insert into world_artifacts
              (user_id, world_id, artifact_id, logical_x, logical_y, depth,
               visual_archetype, visual_seed, revision)
            values (:user_id, :world_id, :artifact_id, 0.1, 0.1, 0, 'landmark',
                    'seed', 1)
            """
        ),
        {"user_id": user_id, "world_id": world_id, "artifact_id": artifact_id},
    )


def test_world_artifact_rejects_cross_user_world(migrated_connection):
    graph = _insert_practical_graph(migrated_connection)
    owner_id = graph["user_id"]
    other_id = _insert_user(migrated_connection)
    artifact_id = _insert_artifact(migrated_connection, graph)
    other_world = _insert_world(migrated_connection, user_id=other_id)

    _assert_constraint(
        migrated_connection,
        "fk_world_artifacts_world_owner",
        text(
            """
            insert into world_artifacts
              (user_id, world_id, artifact_id, logical_x, logical_y, depth,
               visual_archetype, visual_seed, revision)
            values (:user_id, :world_id, :artifact_id, 0.1, 0.1, 0, 'landmark',
                    'seed', 1)
            """
        ),
        {"user_id": owner_id, "world_id": other_world, "artifact_id": artifact_id},
    )


def test_world_artifact_rejects_cross_user_artifact(migrated_connection):
    graph = _insert_practical_graph(migrated_connection)
    owner_id = graph["user_id"]
    other_id = _insert_user(migrated_connection)
    artifact_id = _insert_artifact(migrated_connection, graph)
    other_world = _insert_world(migrated_connection, user_id=other_id)

    _assert_constraint(
        migrated_connection,
        "fk_world_artifacts_artifact_owner",
        text(
            """
            insert into world_artifacts
              (user_id, world_id, artifact_id, logical_x, logical_y, depth,
               visual_archetype, visual_seed, revision)
            values (:user_id, :world_id, :artifact_id, 0.1, 0.1, 0, 'landmark',
                    'seed', 1)
            """
        ),
        {"user_id": other_id, "world_id": other_world, "artifact_id": artifact_id},
    )


def test_world_change_rejects_contextual_duplicate_revision(migrated_connection):
    user_id = _insert_user(migrated_connection)
    world_id = _insert_world(migrated_connection, user_id=user_id)
    _insert_change(migrated_connection, user_id=user_id, world_id=world_id, revision=1)

    _assert_constraint(
        migrated_connection,
        "uq_world_changes_world_revision",
        text(
            """
            insert into world_changes
              (user_id, world_id, revision, change_type, object_type, object_id,
               payload)
            values (:user_id, :world_id, 1, 'NODE_ADDED', 'NODE', :object_id,
                    '{}'::jsonb)
            """
        ),
        {"user_id": user_id, "world_id": world_id, "object_id": uuid4()},
    )


def test_world_change_rejects_cross_user_world(migrated_connection):
    owner_id = _insert_user(migrated_connection)
    other_id = _insert_user(migrated_connection)
    owner_world = _insert_world(migrated_connection, user_id=owner_id)

    _assert_constraint(
        migrated_connection,
        "fk_world_changes_world_owner",
        text(
            """
            insert into world_changes
              (user_id, world_id, revision, change_type, object_type, object_id,
               payload)
            values (:user_id, :world_id, 1, 'NODE_ADDED', 'NODE', :object_id,
                    '{}'::jsonb)
            """
        ),
        {"user_id": other_id, "world_id": owner_world, "object_id": uuid4()},
    )


def test_world_change_rejects_non_positive_revision(migrated_connection):
    user_id = _insert_user(migrated_connection)
    world_id = _insert_world(migrated_connection, user_id=user_id)

    _assert_constraint(
        migrated_connection,
        "ck_world_changes_revision",
        text(
            """
            insert into world_changes
              (user_id, world_id, revision, change_type, object_type, object_id,
               payload)
            values (:user_id, :world_id, 0, 'NODE_ADDED', 'NODE', :object_id,
                    '{}'::jsonb)
            """
        ),
        {"user_id": user_id, "world_id": world_id, "object_id": uuid4()},
    )


def test_revision_advancement_is_contiguous(migrated_connection):
    user_id = _insert_user(migrated_connection)
    world_id = _insert_world(migrated_connection, user_id=user_id)

    allocated = []
    for _ in range(3):
        revision = _advance_revision(migrated_connection, user_id=user_id)
        allocated.append(revision)
        _insert_change(
            migrated_connection,
            user_id=user_id,
            world_id=world_id,
            revision=revision,
        )

    assert allocated == [1, 2, 3]
    revisions = migrated_connection.execute(
        text(
            "select revision from world_changes where world_id = :world_id "
            "order by revision"
        ),
        {"world_id": world_id},
    ).scalars().all()
    assert revisions == [1, 2, 3]


def test_world_head_matches_last_change(migrated_connection):
    user_id = _insert_user(migrated_connection)
    world_id = _insert_world(migrated_connection, user_id=user_id)

    for _ in range(2):
        revision = _advance_revision(migrated_connection, user_id=user_id)
        _insert_change(
            migrated_connection,
            user_id=user_id,
            world_id=world_id,
            revision=revision,
        )

    head, last = migrated_connection.execute(
        text(
            """
            select lw.current_revision, max(wc.revision)
              from learner_worlds lw
              join world_changes wc on wc.world_id = lw.id
             where lw.id = :world_id
             group by lw.current_revision
            """
        ),
        {"world_id": world_id},
    ).one()
    assert head == last == 2


def test_snapshot_reconstruction_from_projection_tables(migrated_connection):
    graph = _insert_practical_graph(migrated_connection)
    user_id = graph["user_id"]
    world_id = _insert_world(
        migrated_connection, user_id=user_id, generation_seed="opaque-seed"
    )
    domain_id = _insert_entity(migrated_connection, entity_type="DOMAIN")
    region_id = _insert_region(
        migrated_connection,
        user_id=user_id,
        world_id=world_id,
        region_key="technology",
        primary_domain_id=domain_id,
    )
    source_entity = _insert_entity(migrated_connection)
    target_entity = _insert_entity(migrated_connection)
    source_node = _insert_node(
        migrated_connection,
        user_id=user_id,
        world_id=world_id,
        entity_id=source_entity,
        region_id=region_id,
        growth_state="YOUNG",
    )
    target_node = _insert_node(
        migrated_connection,
        user_id=user_id,
        world_id=world_id,
        entity_id=target_entity,
        region_id=region_id,
    )
    _insert_connection(
        migrated_connection,
        user_id=user_id,
        world_id=world_id,
        source_world_node_id=source_node,
        target_world_node_id=target_node,
    )
    artifact_id = _insert_artifact(migrated_connection, graph)
    world_artifact_id = _insert_world_artifact(
        migrated_connection,
        user_id=user_id,
        world_id=world_id,
        artifact_id=artifact_id,
        region_id=region_id,
    )
    for _ in range(4):
        revision = _advance_revision(migrated_connection, user_id=user_id)
        _insert_change(
            migrated_connection,
            user_id=user_id,
            world_id=world_id,
            revision=revision,
        )

    snapshot = _load_snapshot(migrated_connection, user_id=user_id)

    assert snapshot["revision"] == 4
    assert snapshot["layout_version"] == 1
    assert snapshot["generation_seed"] == "opaque-seed"
    assert len(snapshot["regions"]) == 1
    assert snapshot["regions"][0].region_key == "technology"
    assert len(snapshot["nodes"]) == 2
    node_ids = {row.id for row in snapshot["nodes"]}
    assert node_ids == {source_node, target_node}
    assert len(snapshot["connections"]) == 1
    assert snapshot["connections"][0].source_world_node_id == source_node
    assert snapshot["connections"][0].target_world_node_id == target_node
    assert len(snapshot["artifacts"]) == 1
    assert snapshot["artifacts"][0].id == world_artifact_id


def test_delta_query_paginates_and_reports_head(migrated_connection):
    user_id = _insert_user(migrated_connection)
    world_id = _insert_world(migrated_connection, user_id=user_id)
    for _ in range(5):
        revision = _advance_revision(migrated_connection, user_id=user_id)
        _insert_change(
            migrated_connection,
            user_id=user_id,
            world_id=world_id,
            revision=revision,
        )

    to_revision, head, has_more, rows = _load_changes(
        migrated_connection, world_id=world_id, after_revision=2, limit=2
    )

    assert [row.revision for row in rows] == [3, 4]
    assert to_revision == 4
    assert head == 5
    assert has_more is True

    to_revision, head, has_more, rows = _load_changes(
        migrated_connection, world_id=world_id, after_revision=4, limit=2
    )
    assert [row.revision for row in rows] == [5]
    assert to_revision == 5
    assert head == 5
    assert has_more is False


def test_delta_query_signals_resync_when_history_is_pruned(migrated_connection):
    user_id = _insert_user(migrated_connection)
    world_id = _insert_world(migrated_connection, user_id=user_id)
    for _ in range(5):
        revision = _advance_revision(migrated_connection, user_id=user_id)
        _insert_change(
            migrated_connection,
            user_id=user_id,
            world_id=world_id,
            revision=revision,
        )

    assert (
        _resync_required(migrated_connection, world_id=world_id, after_revision=0)
        is False
    )

    migrated_connection.execute(
        text(
            "delete from world_changes where world_id = :world_id "
            "and revision <= 2"
        ),
        {"world_id": world_id},
    )

    assert (
        _resync_required(migrated_connection, world_id=world_id, after_revision=0)
        is True
    )
    assert (
        _resync_required(migrated_connection, world_id=world_id, after_revision=2)
        is False
    )


def test_deleting_user_removes_owned_world_graph(migrated_connection):
    user_id = _insert_user(migrated_connection)
    world_id = _insert_world(migrated_connection, user_id=user_id)
    entity = _insert_entity(migrated_connection)
    other_entity = _insert_entity(migrated_connection)
    region_id = _insert_region(
        migrated_connection, user_id=user_id, world_id=world_id
    )
    source_node = _insert_node(
        migrated_connection,
        user_id=user_id,
        world_id=world_id,
        entity_id=entity,
        region_id=region_id,
    )
    target_node = _insert_node(
        migrated_connection,
        user_id=user_id,
        world_id=world_id,
        entity_id=other_entity,
        region_id=region_id,
    )
    _insert_connection(
        migrated_connection,
        user_id=user_id,
        world_id=world_id,
        source_world_node_id=source_node,
        target_world_node_id=target_node,
    )
    _insert_change(migrated_connection, user_id=user_id, world_id=world_id, revision=1)

    migrated_connection.execute(
        text("delete from app_users where id = :id"), {"id": user_id}
    )

    for table in (
        "learner_worlds",
        "world_regions",
        "world_nodes",
        "world_connections",
        "world_artifacts",
        "world_changes",
    ):
        remaining = migrated_connection.execute(
            text(f"select count(*) from {table} where user_id = :id"),
            {"id": user_id},
        ).scalar_one()
        assert remaining == 0


def test_deleting_world_removes_projection_children(migrated_connection):
    user_id = _insert_user(migrated_connection)
    world_id = _insert_world(migrated_connection, user_id=user_id)
    entity = _insert_entity(migrated_connection)
    node_id = _insert_node(
        migrated_connection, user_id=user_id, world_id=world_id, entity_id=entity
    )
    _insert_change(migrated_connection, user_id=user_id, world_id=world_id, revision=1)

    migrated_connection.execute(
        text("delete from learner_worlds where id = :id"), {"id": world_id}
    )

    assert (
        migrated_connection.execute(
            text("select count(*) from world_nodes where id = :id"), {"id": node_id}
        ).scalar_one()
        == 0
    )
    assert (
        migrated_connection.execute(
            text("select count(*) from world_changes where world_id = :id"),
            {"id": world_id},
        ).scalar_one()
        == 0
    )


def test_deleting_region_keeps_nodes_without_region(migrated_connection):
    user_id = _insert_user(migrated_connection)
    world_id = _insert_world(migrated_connection, user_id=user_id)
    region_id = _insert_region(
        migrated_connection, user_id=user_id, world_id=world_id
    )
    entity = _insert_entity(migrated_connection)
    node_id = _insert_node(
        migrated_connection,
        user_id=user_id,
        world_id=world_id,
        entity_id=entity,
        region_id=region_id,
    )

    migrated_connection.execute(
        text("delete from world_regions where id = :id"), {"id": region_id}
    )

    stored = migrated_connection.execute(
        text("select region_id from world_nodes where id = :id"), {"id": node_id}
    ).scalar_one()
    assert stored is None
