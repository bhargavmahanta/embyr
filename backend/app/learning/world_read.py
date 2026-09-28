"""Owned snapshots and recoverable complete-suffix World history."""

from sqlalchemy import text

from app.api.errors import AppError
from app.api.m6_read_dtos import WorldDeltaPage, WorldSnapshot
from app.learning.read_transactions import integrity_error
from app.learning.world_projection import world_id, world_seed

REGION_COLUMNS = "id,region_key,primary_domain_id,logical_x,logical_y,logical_width,logical_height,visual_archetype"
NODE_COLUMNS = "id,entity_id,entity_version,region_id,logical_x,logical_y,depth,visual_archetype,visual_seed,growth_state,revision"


async def root_for(session, user):
    return (
        (
            await session.execute(
                text(
                    "select id,current_revision,layout_version,generation_seed from learner_worlds where user_id=:u"
                ),
                {"u": user},
            )
        )
        .mappings()
        .one_or_none()
    )


async def world_snapshot(session, user):
    root = await root_for(session, user)
    regions, nodes = [], []
    if root:
        scope = {"u": user, "w": root["id"]}
        regions = list(
            (
                await session.execute(
                    text(
                        f"select {REGION_COLUMNS} from world_regions where user_id=:u and world_id=:w order by region_key,id"
                    ),
                    scope,
                )
            ).mappings()
        )
        nodes = list(
            (
                await session.execute(
                    text(
                        f"select {NODE_COLUMNS} from world_nodes where user_id=:u and world_id=:w order by entity_id,id"
                    ),
                    scope,
                )
            ).mappings()
        )
        if any(n["revision"] > root["current_revision"] for n in nodes):
            raise integrity_error()
    return WorldSnapshot(
        revision=root["current_revision"] if root else 0,
        layout_version=root["layout_version"] if root else 1,
        generation_seed=root["generation_seed"] if root else world_seed(world_id(user)),
        regions=regions,
        nodes=nodes,
        connections=[],
        artifacts=[],
    )


def resync(cursor, head):
    return AppError(
        code="WORLD_RESYNC_REQUIRED",
        status=409,
        title="World resync required",
        detail="Fetch the World snapshot before requesting further changes.",
        details={"after_revision": cursor, "current_revision": head},
    )


async def world_changes(session, user, cursor, limit):
    root = await root_for(session, user)
    head = root["current_revision"] if root else 0
    if cursor > head:
        raise resync(cursor, head)
    if cursor == head:
        return WorldDeltaPage(
            from_revision=cursor,
            to_revision=head,
            current_revision=head,
            has_more=False,
            changes=[],
        )
    params = {
        "u": user,
        "w": root["id"],
        "cursor": cursor,
        "head": head,
        "limit": limit,
    }
    # uq_world_changes_world_revision plus this complete range count proves
    # continuity without loading any payload, including beyond the page limit.
    count = await session.scalar(
        text("""select count(*) from world_changes
        where user_id=:u and world_id=:w and revision>:cursor and revision<=:head"""),
        params,
    )
    if count != head - cursor:
        raise resync(cursor, head)
    rows = list(
        (
            await session.execute(
                text("""select revision,change_type as type,object_id,payload
        from world_changes where user_id=:u and world_id=:w and revision>:cursor
        and revision<=:head order by revision limit :limit"""),
                params,
            )
        ).mappings()
    )
    if not rows:
        raise integrity_error()
    end = rows[-1]["revision"]
    return WorldDeltaPage(
        from_revision=cursor,
        to_revision=end,
        current_revision=head,
        has_more=end < head,
        changes=rows,
    )
