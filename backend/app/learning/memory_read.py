"""Owned Memory read model, pinned to a single published horizon."""

from sqlalchemy import text

from app.api.m6_read_dtos import MemorySummary
from app.learning.read_transactions import integrity_error


async def memory_summary(session, user):
    row = (
        (
            await session.execute(
                text("""
      select u.onboarding_completed_at,h.source_sequence as head, c.processed_source_sequence as processed
      from app_users u
      left join projection_source_heads h on h.user_id=u.id and h.user_id=:u
      left join learner_projection_checkpoints c on c.user_id=u.id and c.user_id=:u
      where u.id=:u
    """),
                {"u": user},
            )
        )
        .mappings()
        .one()
    )
    processed, head = row["processed"] or 0, row["head"] or 0
    if processed > head:
        raise integrity_error()
    failed = await session.scalar(
        text("""select exists(select 1 from jobs where user_id=:u
      and job_type='LEARNER_PROJECTION' and status='FAILED'
      and (payload->>'last_source_sequence')::bigint > :p)"""),
        {"u": user, "p": processed},
    )
    preference = (
        (
            await session.execute(
                text("""select adventure_preference,preferred_effort,
      support_style,practical_opt_in,version from learner_preferences where user_id=:u"""),
                {"u": user},
            )
        )
        .mappings()
        .one_or_none()
    )
    if (row["onboarding_completed_at"] is not None) != (preference is not None):
        raise integrity_error()
    interests, interests_truncated = await explicit_interests(session, user)
    recent, recent_truncated = await recently_explored(session, user, processed)
    recognition, recognition_truncated = await recognition_evidence(
        session, user, processed
    )
    return MemorySummary(
        contract_version="memory-summary/v1",
        projection={
            "model_version": "learner-projection/v1",
            "source_sequence": processed,
            "source_head_sequence": head,
            "status": "CURRENT"
            if processed == head
            else "FAILED"
            if failed
            else "PENDING",
        },
        learning_preferences=dict(preference) if preference else None,
        explicit_interests=interests,
        recently_explored=recent,
        recognition_evidence=recognition,
        long_term_interests=[],
        voluntary_revisits=[],
        truncated={
            "explicit_interests": interests_truncated,
            "recently_explored": recent_truncated,
            "recognition_evidence": recognition_truncated,
        },
    )


async def explicit_interests(session, user):
    rows = list(
        (
            await session.execute(
                text("""select p.entity_id,p.preference,p.version,p.updated_at,
       e.id as existing_entity,e.status,e.current_version,v.title,
       v.version as display_version,count(*) over() as total
       from explicit_interest_preferences p
       left join learning_entities e on e.id=p.entity_id
       left join learning_entity_versions v on v.entity_id=e.id and v.version=e.current_version
       where p.user_id=:u order by p.updated_at desc,p.entity_id limit 20"""),
                {"u": user},
            )
        ).mappings()
    )
    items = []
    for r in rows:
        if r["existing_entity"] is None:
            raise integrity_error()
        available = (
            r["status"] in ("REVIEWED", "PUBLISHED")
            and r["current_version"] is not None
        )
        if available and (r["display_version"] is None or not r["title"]):
            raise integrity_error()
        items.append(
            {k: r[k] for k in ["entity_id", "preference", "version", "updated_at"]}
            | {
                "entity_version": r["display_version"] if available else None,
                "title": r["title"][:512] if available else None,
                "availability": "AVAILABLE" if available else "UNAVAILABLE",
            }
        )
    return items, bool(rows and rows[0]["total"] > 20)


async def recently_explored(session, user, processed):
    rows = list(
        (
            await session.execute(
                text("""
      with receipts as (
        select source_sequence,source_time,facts from projection_inputs
        where user_id=:u and source_sequence<=:p and source_kind='LEDGER'
          and facts->>'event_type' in ('EXPLORATION_STARTED','USER_RETURNED','REFLECTION_SUBMITTED','EXPLORATION_COMPLETED')
      ), first_reflections as (
        select distinct on (facts->>'reflection_id') source_sequence
        from receipts where facts->>'event_type'='REFLECTION_SUBMITTED'
        order by facts->>'reflection_id',source_sequence
      ), activity as (
        select (facts->>'entity_id')::uuid as entity_id,
          (facts->>'entity_version')::bigint as entity_version,
          count(distinct facts->>'exploration_id') filter(where facts->>'event_type'='EXPLORATION_STARTED') as started_count,
          count(distinct facts->>'event_id') filter(where facts->>'event_type'='USER_RETURNED') as returned_count,
          count(distinct facts->>'exploration_id') filter(where facts->>'event_type'='EXPLORATION_COMPLETED') as completed_count,
          max(source_time) as latest_activity_at
        from receipts where facts->>'event_type'<>'REFLECTION_SUBMITTED'
          or source_sequence in(select source_sequence from first_reflections)
        group by facts->>'entity_id',facts->>'entity_version'
      ) select a.*,v.title,count(*) over() as total from activity a
      left join learning_entity_versions v on v.entity_id=a.entity_id and v.version=a.entity_version
      where a.started_count>0 order by a.latest_activity_at desc,a.entity_id,a.entity_version limit 10
    """),
                {"u": user, "p": processed},
            )
        ).mappings()
    )
    result = []
    for r in rows:
        if not r["title"]:
            raise integrity_error()
        result.append(
            {
                k: r[k]
                for k in [
                    "entity_id",
                    "entity_version",
                    "started_count",
                    "returned_count",
                    "completed_count",
                    "latest_activity_at",
                ]
            }
            | {"title": r["title"][:512]}
        )
    return result, bool(rows and rows[0]["total"] > 10)


async def recognition_evidence(session, user, processed):
    # Only OBJECTIVE provenance already published at this checkpoint is a
    # candidate. Current operational rows can veto, never contribute new IDs.
    rows = list(
        (
            await session.execute(
                text("""
      with projected as (
        select s.objective_id,l.learning_evidence_id,pi.source_time,pi.facts
        from learner_objective_state s
        join state_evidence_links l on l.user_id=s.user_id and l.user_id=:u
          and l.target_id=s.objective_id and l.state_dimension='OBJECTIVE'
        join projection_inputs pi on pi.user_id=l.user_id and pi.user_id=:u
          and pi.evidence_id=l.learning_evidence_id and pi.source_kind='EVIDENCE'
          and pi.source_sequence<=:p and pi.facts->>'resulting_status'='ACTIVE'
        where s.user_id=:u and s.model_version='learner-projection/v1'
          and s.categorical_state='DEVELOPING' and l.learning_event_id is null and l.weight is null
      ), surviving as (
        select p.objective_id,(p.facts->>'entity_id')::uuid as entity_id,
          (p.facts->>'entity_version')::bigint as entity_version,
          (p.facts->>'response_id')::uuid as response_id,
          p.source_time,p.facts->>'support_level' is not null as support_required
        from projected p
        join learning_evidence e on e.user_id=:u and e.id=p.learning_evidence_id
        join evaluation_runs r on r.user_id=:u and r.id=e.evaluation_run_id
        join assessment_responses a on a.user_id=:u and a.id=r.response_id
        join assessment_sessions s on s.user_id=:u and s.id=a.assessment_session_id
        join assessment_interactions i on i.user_id=:u and i.id=a.interaction_id
          and i.assessment_session_id=s.id
        join explorations x on x.user_id=:u and x.id=s.exploration_id
        join learning_objectives o on o.id=p.objective_id and o.entity_id=e.entity_id
        where e.status='ACTIVE' and e.source_type='ASSESSMENT_RESPONSE'
          and e.evidence_type='RECOGNITION' and e.evidence_strength='WEAK'
          and r.status='SUCCEEDED' and r.result='SUPPORTED'
          and r.evaluator_version='deterministic-evaluation/v1'
          and r.confidence is not null and r.confidence between 0 and 1
          and e.evaluation_confidence=r.confidence
          and e.support_level is not distinct from a.support_used
          and e.source_id=a.id and i.objective_id=e.objective_id and e.objective_id=p.objective_id
          and x.entity_id=e.entity_id and x.entity_version=s.entity_version
          and o.entity_version=s.entity_version
          and p.facts->>'entity_id'=e.entity_id::text
          and (p.facts->>'entity_version')::bigint=s.entity_version
          and p.facts->>'response_id'=a.id::text
          and p.facts->>'evaluation_run_id'=r.id::text
          and p.facts->>'objective_id'=e.objective_id::text
          and p.facts->>'evaluator_version'=r.evaluator_version
          and p.facts->>'rubric_version'=r.rubric_version
          and (p.facts->>'classification_confidence')::double precision=r.confidence
          and p.facts->>'support_level' is not distinct from e.support_level
          and p.facts->>'evaluation_status'='SUCCEEDED'
          and p.facts->>'evaluation_result'='SUPPORTED'
      ), grouped as (
        select objective_id,entity_id,entity_version,count(distinct response_id) as evidence_count,
          bool_or(support_required) as support_required,max(source_time) as last_evidence_at
        from surviving group by objective_id,entity_id,entity_version
      ) select *,count(*) over() as total from grouped order by last_evidence_at desc,objective_id limit 10
    """),
                {"u": user, "p": processed},
            )
        ).mappings()
    )
    return [
        {
            k: r[k]
            for k in [
                "objective_id",
                "entity_id",
                "entity_version",
                "evidence_count",
                "support_required",
                "last_evidence_at",
            ]
        }
        | {"summary": "Recognition evidence recorded."}
        for r in rows
    ], bool(rows and rows[0]["total"] > 10)
