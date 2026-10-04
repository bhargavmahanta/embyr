"""Install ordered factual capture; no learner/world projection or backfill.

Capture is deferred until source writes are complete. Helpers are trigger-only,
owned by the existing non-login maintenance identity, with no runtime EXECUTE.
No source locks are obtained after the head lock. All writes are transactional.
"""

from pathlib import Path
from runpy import run_path

import sqlalchemy as sa
from alembic import op

revision = "0020_learner_projection_foundation"
down_revision = "0019_response_lock_security"
branch_labels = None
depends_on = None


TABLES = """
create table public.projection_source_heads (
 user_id uuid primary key references public.app_users(id) on delete cascade,
 source_sequence bigint not null default 0,
 bootstrap_state text not null default 'REQUIRED',
 baseline_through_sequence bigint, cutoff_source_sequence bigint, cutoff_at timestamptz,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 constraint ck_projection_source_heads_sequence check(source_sequence >= 0),
 constraint ck_projection_source_heads_bootstrap_state check(bootstrap_state in ('REQUIRED','READY')),
 constraint ck_projection_source_heads_baseline check(baseline_through_sequence is null or baseline_through_sequence > 0),
 constraint ck_projection_source_heads_cutoff check(cutoff_source_sequence is null or cutoff_source_sequence >= 0)
);
create table public.projection_inputs (
 user_id uuid not null references public.app_users(id) on delete cascade,
 source_sequence bigint not null,
 contract_version text not null default 'projection-input/v1', schema_version integer not null default 1,
 source_kind text not null, source_key text not null, source_group text not null,
 source_time timestamptz not null, facts jsonb not null, ledger_event_id uuid, evidence_id uuid,
 constraint pk_projection_inputs primary key(user_id,source_sequence),
 constraint uq_projection_inputs_source unique(user_id,source_kind,source_key),
 constraint fk_projection_inputs_event_owner foreign key(user_id,ledger_event_id) references public.learning_events(user_id,id),
 constraint fk_projection_inputs_evidence_owner foreign key(user_id,evidence_id) references public.learning_evidence(user_id,id),
 constraint ck_projection_inputs_sequence check(source_sequence > 0),
 constraint ck_projection_inputs_version check(contract_version='projection-input/v1' and schema_version=1),
 constraint ck_projection_inputs_group check(source_group ~ '^[0-9]{1,20}$'),
 constraint ck_projection_inputs_facts check(jsonb_typeof(facts)='object'),
 constraint ck_projection_inputs_source check(
  (source_kind='LEDGER' and ledger_event_id is not null and evidence_id is null
   and source_key=ledger_event_id::text and facts->>'event_id'=source_key)
  or (source_kind='EVIDENCE' and evidence_id is not null and ledger_event_id is null
   and facts->>'evidence_id'=evidence_id::text and facts->>'resulting_status' in ('ACTIVE','SUPERSEDED','REVOKED')
   and source_key=evidence_id::text || ':' || (facts->>'resulting_status'))
  or (source_kind='BOOTSTRAP' and ledger_event_id is null and evidence_id is null and source_key='learner-projection/v1:baseline'))
);
create index ix_projection_inputs_group on public.projection_inputs(user_id,source_group,source_sequence);
create table public.learner_projection_checkpoints (
 user_id uuid primary key references public.app_users(id) on delete cascade,
 processed_source_sequence bigint not null default 0, generation bigint not null default 1,
 input_contract_version text not null default 'projection-input/v1',
 worker_contract_version text not null default 'projection-worker/v1',
 learner_contract_version text not null default 'learner-projection/v1',
 world_contract_version text not null default 'world-projection/v1',
 input_fingerprint text, output_fingerprint text, blocking_group text, failure_code text,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 constraint ck_learner_projection_checkpoints_horizon check(processed_source_sequence>=0 and generation>=1),
 constraint ck_learner_projection_checkpoints_versions check(input_contract_version='projection-input/v1' and worker_contract_version='projection-worker/v1' and learner_contract_version='learner-projection/v1' and world_contract_version='world-projection/v1'),
 constraint ck_learner_projection_checkpoints_group check(blocking_group is null or blocking_group ~ '^[0-9]{1,20}$'),
 constraint ck_learner_projection_checkpoints_failure check(failure_code is null or failure_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
 constraint ck_learner_projection_checkpoints_fingerprints check((input_fingerprint is null or input_fingerprint ~ '^[0-9a-f]{64}$') and (output_fingerprint is null or output_fingerprint ~ '^[0-9a-f]{64}$'))
);
"""


ALLOCATE = """
create function public.m6_append_input(p_user uuid, p_kind text, p_key text,
 p_time timestamptz, p_facts jsonb, p_event uuid, p_evidence uuid) returns bigint
language plpgsql security definer set search_path=pg_catalog,public,pg_temp as $$
declare seq bigint; prior public.projection_inputs; grp text := pg_current_xact_id()::text;
begin
 -- Missing metadata is an integrity failure, never proof of a new user.
 select source_sequence into seq from public.projection_source_heads
 where user_id=p_user for no key update;
 if not found then
  raise exception 'M6_SOURCE_HEAD_MISSING' using errcode='23514';
 end if;
 select * into prior from public.projection_inputs where user_id=p_user
 and source_kind=p_kind and source_key=p_key;
 if found then
  -- A transition time is assigned once. Equivalent recapture does not replace it.
  if prior.source_time is distinct from p_time or
   (prior.facts - 'transition_at') is distinct from (p_facts - 'transition_at') or
   prior.ledger_event_id is distinct from p_event or prior.evidence_id is distinct from p_evidence then
   raise exception 'M6_SOURCE_CONFLICT' using errcode='23514';
  end if;
  return prior.source_sequence;
 end if;
 if seq=9223372036854775807 then
  raise exception 'M6_SEQUENCE_OVERFLOW' using errcode='23514';
 end if;
 seq := seq+1;
 if octet_length(jsonb_build_object('contract_version','projection-input/v1','schema_version',1,
  'user_id',p_user,'source_sequence',seq,'source_kind',p_kind,'source_key',p_key,
  'source_group',grp,'source_time',to_char(p_time at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'facts',p_facts)::text)>8192 then
  raise exception 'M6_RECEIPT_TOO_LARGE' using errcode='23514';
 end if;
 update public.projection_source_heads set source_sequence=seq,updated_at=clock_timestamp() where user_id=p_user;
 insert into public.projection_inputs(user_id,source_sequence,source_kind,source_key,source_group,source_time,facts,ledger_event_id,evidence_id)
 values(p_user,seq,p_kind,p_key,grp,p_time,p_facts,p_event,p_evidence);
 insert into public.jobs(user_id,job_type,status,payload) values(p_user,'LEARNER_PROJECTION','PENDING',
  jsonb_build_object('contract_version','projection-worker/v1','user_id',p_user,'source_group',grp,
   'first_source_sequence',case when p_kind='BOOTSTRAP' then 1 else seq end,'last_source_sequence',seq))
 on conflict (user_id,(payload->>'source_group')) where job_type='LEARNER_PROJECTION'
 do update set payload=jsonb_set(
  case when p_kind='BOOTSTRAP' then jsonb_set(public.jobs.payload,'{first_source_sequence}','1'::jsonb) else public.jobs.payload end,
  '{last_source_sequence}',to_jsonb(seq));
 return seq;
end $$;
"""


LEDGER = """
create function public.m6_capture_ledger(ev public.learning_events) returns bigint
language plpgsql security definer set search_path=pg_catalog,public,pg_temp as $$
declare ex public.explorations; sess public.assessment_sessions;
 resp public.assessment_responses; run public.evaluation_runs; refl public.reflections;
 reco public.recommendations; pref public.explicit_interest_preferences;
 pref_version integer; entity_version integer; facts jsonb; existing jsonb;
 rid uuid; eid uuid; fid uuid; recid uuid;
begin
 if ev.schema_version<>1 or ev.event_type not in (
  'ONBOARDING_COMPLETED','EXPLICIT_INTEREST_CHANGED','RECOMMENDATION_ACCEPTED','RECOMMENDATION_SKIPPED',
  'EXPLORATION_STARTED','EXPLORATION_WORK_PREPARED','USER_RETURNED','EXPLORATION_PAUSED','EXPLORATION_RESUMED',
  'REFLECTION_SUBMITTED','REFLECTION_UPDATED','ASSESSMENT_STARTED','HINT_REQUESTED',
  'ASSESSMENT_RESPONSE_SUBMITTED','ASSESSMENT_EVALUATED','ASSESSMENT_EVALUATION_FAILED',
  'ASSESSMENT_EVALUATION_RETRY_REQUESTED','ASSESSMENT_COMPLETED','ASSESSMENT_ABANDONED','EXPLORATION_COMPLETED') then
  raise exception 'M6_UNSUPPORTED_SOURCE' using errcode='23514';
 end if;
 if ev.exploration_id is not null then
  select * into ex from public.explorations where user_id=ev.user_id and id=ev.exploration_id;
  if not found or ex.entity_id is distinct from ev.entity_id then
   raise exception 'M6_SOURCE_LINEAGE' using errcode='23514';
  end if;
  entity_version := ex.entity_version;
 elsif ev.event_type not in ('ONBOARDING_COMPLETED','EXPLICIT_INTEREST_CHANGED','RECOMMENDATION_SKIPPED') then
  raise exception 'M6_SOURCE_LINEAGE' using errcode='23514';
 end if;
 if ev.event_type like 'ASSESSMENT_%' or ev.event_type='HINT_REQUESTED' then
  select * into sess from public.assessment_sessions where user_id=ev.user_id and id=ev.assessment_session_id;
  if not found or sess.exploration_id is distinct from ex.id or sess.entity_version is distinct from entity_version then
   raise exception 'M6_SOURCE_LINEAGE' using errcode='23514';
  end if;
 end if;
 -- Metadata supplies candidate identifiers only; authoritative owned rows decide.
 if ev.event_type in ('ASSESSMENT_RESPONSE_SUBMITTED','ASSESSMENT_EVALUATED',
  'ASSESSMENT_EVALUATION_FAILED','ASSESSMENT_EVALUATION_RETRY_REQUESTED','ASSESSMENT_COMPLETED') then
  eid := (ev.metadata->>'evaluation_run_id')::uuid;
  select * into run from public.evaluation_runs where user_id=ev.user_id and id=eid;
  if not found then raise exception 'M6_SOURCE_LINEAGE' using errcode='23514'; end if;
  rid := run.response_id;
  select * into resp from public.assessment_responses where user_id=ev.user_id and id=rid;
  if not found or resp.assessment_session_id is distinct from sess.id
   or (ev.event_type<>'ASSESSMENT_COMPLETED' and rid is distinct from (ev.metadata->>'response_id')::uuid) then
   raise exception 'M6_SOURCE_LINEAGE' using errcode='23514';
  end if;
 end if;
 if ev.event_type in ('REFLECTION_SUBMITTED','REFLECTION_UPDATED') then
  fid := (ev.metadata->>'reflection_id')::uuid;
  select * into refl from public.reflections where user_id=ev.user_id and id=fid;
  if not found or refl.exploration_id is distinct from ex.id or refl.entity_id is distinct from ev.entity_id then
   raise exception 'M6_SOURCE_LINEAGE' using errcode='23514';
  end if;
 end if;
 if ev.event_type in ('RECOMMENDATION_ACCEPTED','RECOMMENDATION_SKIPPED') or
  (ev.event_type='EXPLORATION_STARTED' and ex.recommendation_id is not null) then
  recid := (ev.metadata->>'recommendation_id')::uuid;
  select * into reco from public.recommendations where user_id=ev.user_id and id=recid;
  if not found or reco.entity_id is distinct from ev.entity_id or
   (ev.exploration_id is not null and (ex.recommendation_id is distinct from reco.id or ex.entity_version is distinct from reco.entity_version)) then
   raise exception 'M6_SOURCE_LINEAGE' using errcode='23514';
  end if;
  entity_version := reco.entity_version;
 end if;
 select pi.facts into existing from public.projection_inputs pi where pi.user_id=ev.user_id
 and pi.source_kind='LEDGER' and pi.source_key=ev.id::text;
 if ev.event_type='EXPLICIT_INTEREST_CHANGED' then
  select * into pref from public.explicit_interest_preferences where user_id=ev.user_id and entity_id=ev.entity_id;
  if existing is not null then
   pref.preference := existing->>'preference'; pref.version := (existing->>'preference_version')::integer;
  end if;
  if pref.preference is null or pref.preference is distinct from ev.metadata->>'preference'
   or pref.version is distinct from (ev.metadata->>'version')::integer then
   raise exception 'M6_SOURCE_LINEAGE' using errcode='23514';
  end if;
  pref_version := pref.version;
 elsif ev.event_type='ONBOARDING_COMPLETED' then
  select version into pref_version from public.learner_preferences where user_id=ev.user_id;
  if existing is not null then pref_version := (existing->>'preference_version')::integer; end if;
  if pref_version is null or pref_version is distinct from (ev.metadata->>'preferences_version')::integer then
   raise exception 'M6_SOURCE_LINEAGE' using errcode='23514';
  end if;
 end if;
 facts := jsonb_build_object('event_id',ev.id,'event_type',ev.event_type,'source_schema_version',ev.schema_version,
  'entity_id',ev.entity_id,'entity_version',entity_version,'exploration_id',ev.exploration_id,
  'assessment_session_id',sess.id,'response_id',rid,'evaluation_run_id',eid,'reflection_id',fid,
  'recommendation_id',recid,'command_id',ev.command_id,'event_ordinal',ev.event_ordinal,
  'preference',pref.preference,'preference_version',pref_version);
 return public.m6_append_input(ev.user_id,'LEDGER',ev.id::text,ev.occurred_at,facts,ev.id,null);
exception when invalid_text_representation or numeric_value_out_of_range then
 raise exception 'M6_SOURCE_LINEAGE' using errcode='23514';
end $$;
"""


TRIGGERS = """
create function public.m6_input_shape() returns trigger
language plpgsql set search_path=pg_catalog,public,pg_temp as $$
declare keys text[]; k text; v jsonb;
begin
 if not isfinite(new.source_time) or
  new.source_time < timestamptz '0001-01-01 00:00:00+00' or
  new.source_time >= timestamptz '10000-01-01 00:00:00+00' then
  raise exception 'M6_SOURCE_TIME' using errcode='23514';
 end if;
 if new.source_kind='LEDGER' then
  keys := array['event_id','event_type','source_schema_version','entity_id','entity_version','exploration_id',
   'assessment_session_id','response_id','evaluation_run_id','reflection_id','recommendation_id','command_id',
   'event_ordinal','preference','preference_version'];
  if new.facts->>'event_id' is distinct from new.ledger_event_id::text or
   new.facts->'source_schema_version' is distinct from '1'::jsonb or not exists(
   select 1 from public.learning_events e where e.user_id=new.user_id and e.id=new.ledger_event_id
    and e.event_type=new.facts->>'event_type' and e.schema_version=1) then
   raise exception 'M6_FACT_SHAPE' using errcode='23514';
  end if;
 elsif new.source_kind='EVIDENCE' then
  keys := array['evidence_id','resulting_status','source_type','source_id','evidence_type','evidence_strength',
   'objective_id','entity_id','entity_version','response_id','evaluation_run_id','evaluation_status','evaluation_result',
   'evaluator_version','rubric_version','support_level','classification_confidence','transition_at'];
  if new.facts->>'evidence_id' is distinct from new.evidence_id::text or
   new.facts->>'source_type' is distinct from 'ASSESSMENT_RESPONSE' or
   new.facts->>'evidence_type' is distinct from 'RECOGNITION' or new.facts->>'evidence_strength' is distinct from 'WEAK' or
   new.facts->>'source_id' is distinct from new.facts->>'response_id' or
   jsonb_typeof(new.facts->'evaluator_version') is distinct from 'string' or
   jsonb_typeof(new.facts->'rubric_version') is distinct from 'string' or
   length(new.facts->>'evaluator_version') not between 1 and 64 or length(new.facts->>'rubric_version') not between 1 and 64 then
   raise exception 'M6_FACT_SHAPE' using errcode='23514';
  end if;
 elsif new.source_kind='BOOTSTRAP' then
  keys := array['cutoff_source_sequence','cutoff_at'];
  if jsonb_typeof(new.facts->'cutoff_source_sequence') is distinct from 'number' or
   not (new.facts->>'cutoff_source_sequence' ~ '^(0|[1-9][0-9]{0,18})$') or
   (new.facts->>'cutoff_source_sequence')::bigint>=new.source_sequence or
   jsonb_typeof(new.facts->'cutoff_at') is distinct from 'string' or
   not (new.facts->>'cutoff_at' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?Z$') or
   (new.facts->>'cutoff_at')::timestamptz is distinct from new.source_time then
   raise exception 'M6_FACT_SHAPE' using errcode='23514';
  end if;
 else raise exception 'M6_FACT_SHAPE' using errcode='23514';
 end if;
 if jsonb_typeof(new.facts) is distinct from 'object' or not(new.facts ?& keys) or new.facts-keys<>'{}'::jsonb then
  raise exception 'M6_FACT_SHAPE' using errcode='23514';
 end if;
 for k,v in select key,value from jsonb_each(new.facts) loop
  if k like '%_id' and (new.source_kind='EVIDENCE' or v<>'null'::jsonb) and
   (jsonb_typeof(v) is distinct from 'string' or not(v#>>'{}' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')) then
   raise exception 'M6_FACT_SHAPE' using errcode='23514';
  end if;
  if k in ('entity_version','preference_version','event_ordinal') and v<>'null'::jsonb and
   (jsonb_typeof(v) is distinct from 'number' or not(v#>>'{}' ~ '^(0|[1-9][0-9]{0,18})$') or
    (v#>>'{}')::numeric>9223372036854775807 or
    (k<>'event_ordinal' and (v#>>'{}')::numeric<1) or (k='event_ordinal' and (v#>>'{}')::numeric>32767)) then
   raise exception 'M6_FACT_SHAPE' using errcode='23514';
  end if;
  if k='classification_confidence' and v<>'null'::jsonb and
   (jsonb_typeof(v) is distinct from 'number' or not((v#>>'{}')::numeric between 0 and 1)) then
   raise exception 'M6_FACT_SHAPE' using errcode='23514';
  end if;
 end loop;
 if octet_length(jsonb_build_object('contract_version',new.contract_version,'schema_version',new.schema_version,
  'user_id',new.user_id,'source_sequence',new.source_sequence,'source_kind',new.source_kind,'source_key',new.source_key,
  'source_group',new.source_group,'source_time',to_char(new.source_time at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'facts',new.facts)::text)>8192 then
  raise exception 'M6_RECEIPT_TOO_LARGE' using errcode='23514';
 end if;
 return new;
exception when invalid_text_representation or numeric_value_out_of_range or invalid_datetime_format then
 raise exception 'M6_FACT_SHAPE' using errcode='23514';
end $$;
create trigger trg_m6_input_shape before insert on public.projection_inputs
for each row execute function public.m6_input_shape();

create function public.m6_capture_event_trigger() returns trigger
language plpgsql security definer set search_path=pg_catalog,public,pg_temp as $$
begin
 if current_setting('role',true)='app_backend' and new.user_id is distinct from
  nullif(current_setting('app.user_id',true),'')::uuid then
  raise exception 'M6_SOURCE_OWNER' using errcode='42501';
 end if;
 perform public.m6_capture_ledger(new);
 return null;
end $$;
create constraint trigger ct_m6_capture_event after insert on public.learning_events
deferrable initially deferred for each row execute function public.m6_capture_event_trigger();

create function public.m6_capture_evidence_trigger() returns trigger
language plpgsql security definer set search_path=pg_catalog,public,pg_temp as $$
declare lineage record; facts jsonb;
begin
 if tg_op='UPDATE' and new.status=old.status then return null; end if;
 if new.source_type<>'ASSESSMENT_RESPONSE' or new.evidence_type<>'RECOGNITION' or new.evidence_strength<>'WEAK' then
  raise exception 'M6_UNSUPPORTED_SOURCE' using errcode='23514';
 end if;
 select r.id as response_id, r.support_used, er.status as evaluation_status, er.result, er.confidence,
  er.evaluator_version, er.rubric_version, e.entity_version into lineage
 from public.evaluation_runs er
 join public.assessment_responses r on r.user_id=er.user_id and r.id=er.response_id
 join public.assessment_interactions ai on ai.user_id=r.user_id and ai.id=r.interaction_id and ai.assessment_session_id=r.assessment_session_id
 join public.assessment_sessions s on s.user_id=r.user_id and s.id=r.assessment_session_id
 join public.explorations e on e.user_id=s.user_id and e.id=s.exploration_id and e.entity_version=s.entity_version
 join public.learning_objectives o on o.id=ai.objective_id and o.entity_id=e.entity_id and o.entity_version=e.entity_version
 where er.user_id=new.user_id and er.id=new.evaluation_run_id and r.id=new.source_id
 and o.id=new.objective_id and e.entity_id=new.entity_id;
 if not found or new.support_level is distinct from lineage.support_used or
  new.evaluation_confidence is distinct from lineage.confidence or
  (new.evaluation_confidence is not null and not (new.evaluation_confidence>=0 and new.evaluation_confidence<=1)) or
  length(lineage.evaluator_version) not between 1 and 64 or length(lineage.rubric_version) not between 1 and 64 then
  raise exception 'M6_SOURCE_LINEAGE' using errcode='23514';
 end if;
 facts := jsonb_build_object('evidence_id',new.id,'resulting_status',new.status,
  'source_type',new.source_type,'source_id',new.source_id,'evidence_type',new.evidence_type,
  'evidence_strength',new.evidence_strength,'objective_id',new.objective_id,'entity_id',new.entity_id,
  'entity_version',lineage.entity_version,'response_id',lineage.response_id,'evaluation_run_id',new.evaluation_run_id,
  'evaluation_status',lineage.evaluation_status,'evaluation_result',lineage.result,
  'evaluator_version',lineage.evaluator_version,'rubric_version',lineage.rubric_version,
  'support_level',new.support_level,'classification_confidence',new.evaluation_confidence,
  'transition_at',to_char(clock_timestamp() at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
 perform public.m6_append_input(new.user_id,'EVIDENCE',new.id::text || ':' || new.status,new.created_at,facts,null,new.id);
 return null;
end $$;
create constraint trigger ct_m6_capture_evidence after insert or update on public.learning_evidence
deferrable initially deferred for each row execute function public.m6_capture_evidence_trigger();

create function public.m6_final_run_snapshot() returns trigger
language plpgsql set search_path=pg_catalog,public,pg_temp as $$
begin
 -- Normally capture runs after all source writes. If a caller forces deferred
 -- constraints immediate, refuse a later source change that would stale an
 -- already immutable snapshot. SELECT only: no reverse source/head locks.
 if exists(select 1 from public.projection_inputs pi where pi.user_id=new.user_id
  and pi.source_kind='EVIDENCE' and pi.source_group=pg_current_xact_id()::text
  and pi.facts->>'evaluation_run_id'=new.id::text
  and pi.facts->>'evaluation_status' is distinct from new.status) then
  raise exception 'M6_FINAL_STATUS_CHANGED' using errcode='23514';
 end if;
 return new;
end $$;
create trigger trg_m6_final_run_snapshot after update of status on public.evaluation_runs
for each row execute function public.m6_final_run_snapshot();

create function public.m6_initialize_user() returns trigger
language plpgsql security definer set search_path=pg_catalog,public,pg_temp as $$
begin
 -- This INSERT trigger is the proof of post-installation creation.
 insert into public.projection_source_heads(user_id,bootstrap_state) values(new.id,'READY');
 insert into public.learner_projection_checkpoints(user_id) values(new.id);
 return new;
end $$;
create trigger trg_m6_initialize_user after insert on public.app_users
for each row execute function public.m6_initialize_user();

create function public.m6_input_immutable() returns trigger
language plpgsql set search_path=pg_catalog,public,pg_temp as $$
begin
 if tg_op='DELETE' and current_user='app_maintenance' then return old; end if;
 raise exception 'M6_INPUT_IMMUTABLE' using errcode='55000';
end $$;
create trigger trg_m6_input_immutable before update or delete on public.projection_inputs
for each row execute function public.m6_input_immutable();

create function public.m6_validate_job() returns trigger
language plpgsql set search_path=pg_catalog,public,pg_temp as $$
declare first_seq bigint; last_seq bigint; n bigint; grp text;
begin
 if new.job_type<>'LEARNER_PROJECTION' then return null; end if;
 -- Read the final row: capture can extend its range repeatedly in one transaction.
 select j.payload->>'source_group',(j.payload->>'first_source_sequence')::bigint,
  (j.payload->>'last_source_sequence')::bigint into grp,first_seq,last_seq
 from public.jobs j where j.id=new.id and j.user_id=new.user_id;
 if not found then return null; end if;
 -- A future bootstrap job covers a complete prefix, potentially including
 -- previously captured live groups. Recognize only its validated marker and
 -- ready metadata; no bootstrap/import operator is installed here.
 if exists(select 1 from public.projection_inputs where user_id=new.user_id and source_group=grp and source_kind='BOOTSTRAP') then
 if first_seq<>1 or not exists(select 1 from public.projection_inputs pi
  join public.projection_source_heads h on h.user_id=pi.user_id
  where pi.user_id=new.user_id and pi.source_group=grp and pi.source_sequence=last_seq
   and pi.source_kind='BOOTSTRAP' and h.bootstrap_state='READY' and h.baseline_through_sequence=last_seq
   and h.cutoff_source_sequence=(pi.facts->>'cutoff_source_sequence')::bigint
   and h.cutoff_at=pi.source_time) then
  raise exception 'M6_JOB_RANGE' using errcode='23514';
 end if;
  select count(*) into n from public.projection_inputs where user_id=new.user_id and source_sequence between 1 and last_seq;
  if n<>last_seq or exists(select 1 from public.projection_inputs where user_id=new.user_id and source_group=grp and source_sequence>last_seq) then
   raise exception 'M6_JOB_RANGE' using errcode='23514';
  end if;
  return null;
 end if;
 select count(*) into n from public.projection_inputs where user_id=new.user_id and source_group=grp;
 if first_seq<1 or last_seq<first_seq or n<>last_seq-first_seq+1 or not exists(
  select 1 from public.projection_inputs where user_id=new.user_id and source_group=grp and source_sequence=first_seq)
 or not exists(select 1 from public.projection_inputs where user_id=new.user_id and source_group=grp and source_sequence=last_seq) then
  raise exception 'M6_JOB_RANGE' using errcode='23514';
 end if;
 return null;
end $$;
create constraint trigger ct_m6_job_range after insert or update on public.jobs
deferrable initially deferred for each row execute function public.m6_validate_job();

create function public.m6_job_shape() returns trigger
language plpgsql set search_path=pg_catalog,public,pg_temp as $$
begin
 -- Check the effective database identity, including direct runtime logins.
 -- Capture calls this invoker guard as its SECURITY DEFINER owner instead.
 if (new.job_type='LEARNER_PROJECTION' or
  (tg_op='UPDATE' and old.job_type='LEARNER_PROJECTION')) and current_user='app_backend' then
  raise exception 'M6_JOB_ROLE' using errcode='42501';
 end if;
 if tg_op='INSERT' and new.job_type='LEARNER_PROJECTION' and
  (new.status is distinct from 'PENDING' or new.attempt_count is distinct from 0 or
   new.locked_at is not null or new.locked_by is not null or new.completed_at is not null) then
  raise exception 'M6_JOB_INITIAL_STATE' using errcode='23514';
 end if;
 if tg_op='UPDATE' and old.job_type='LEARNER_PROJECTION' and current_user='app_maintenance' and
  (to_jsonb(new)-'payload' is distinct from to_jsonb(old)-'payload' or
   old.payload->>'source_group' is distinct from pg_current_xact_id()::text) then
  raise exception 'M6_JOB_LIFECYCLE' using errcode='42501';
 end if;
 if tg_op='UPDATE' and new.job_type is distinct from old.job_type and
  (old.job_type='LEARNER_PROJECTION' or new.job_type='LEARNER_PROJECTION') then
  raise exception 'M6_JOB_IDENTITY' using errcode='23514';
 end if;
 if new.job_type<>'LEARNER_PROJECTION' then return new; end if;
 if new.user_id is null or jsonb_typeof(new.payload) is distinct from 'object' or
  new.payload - array['contract_version','user_id','source_group','first_source_sequence','last_source_sequence'] <> '{}'::jsonb or
  not (new.payload ?& array['contract_version','user_id','source_group','first_source_sequence','last_source_sequence']) or
  jsonb_typeof(new.payload->'contract_version') is distinct from 'string' or
  jsonb_typeof(new.payload->'user_id') is distinct from 'string' or
  jsonb_typeof(new.payload->'source_group') is distinct from 'string' or
  new.payload->>'contract_version' is distinct from 'projection-worker/v1' or new.payload->>'user_id' is distinct from new.user_id::text or
  not (new.payload->>'source_group' ~ '^[0-9]{1,20}$') or
  jsonb_typeof(new.payload->'first_source_sequence') is distinct from 'number' or jsonb_typeof(new.payload->'last_source_sequence') is distinct from 'number' or
  not (new.payload->>'first_source_sequence' ~ '^[1-9][0-9]{0,18}$') or
  not (new.payload->>'last_source_sequence' ~ '^[1-9][0-9]{0,18}$') then
  raise exception 'M6_JOB_SHAPE' using errcode='23514';
 end if;
 if tg_op='UPDATE' and (new.user_id is distinct from old.user_id or
  new.payload is distinct from old.payload and
  (old.payload->>'source_group'<>pg_current_xact_id()::text or
   (new.payload - 'last_source_sequence' is distinct from old.payload - 'last_source_sequence'
    and not (new.payload - array['first_source_sequence','last_source_sequence'] = old.payload - array['first_source_sequence','last_source_sequence']
     and new.payload->>'first_source_sequence'='1' and exists(select 1 from public.projection_inputs pi
      where pi.user_id=new.user_id and pi.source_group=new.payload->>'source_group'
       and pi.source_kind='BOOTSTRAP' and pi.source_sequence=(new.payload->>'last_source_sequence')::bigint))))) then
  raise exception 'M6_JOB_IDENTITY' using errcode='23514';
 end if;
 return new;
end $$;
create trigger trg_m6_job_shape before insert or update on public.jobs
for each row execute function public.m6_job_shape();

create function public.m6_lock_source_owner(p_user uuid) returns boolean
language plpgsql security definer set search_path=pg_catalog,public,pg_temp as $$
declare caller text;
begin
 caller := coalesce(nullif(current_setting('role',true),'none'),session_user);
 if pg_has_role(caller,'app_backend','USAGE') and not
  (select rolsuper from pg_roles where rolname=caller) and p_user is distinct from
  nullif(current_setting('app.user_id',true),'')::uuid then
  raise exception 'M6_SOURCE_OWNER' using errcode='42501';
 end if;
 perform 1 from public.app_users where id=p_user for key share;
 return found;
end $$;

create function public.m6_recapture_event(p_user uuid, p_event uuid) returns bigint
language plpgsql security definer set search_path=pg_catalog,public,pg_temp as $$
declare ev public.learning_events; caller text;
begin
 caller := coalesce(nullif(current_setting('role',true),'none'),session_user);
 if not public.m6_lock_source_owner(p_user) then
  raise exception 'M6_SOURCE_OWNER' using errcode='42501';
 end if;
 select * into ev from public.learning_events where id=p_event and user_id=p_user;
 if not found then
  raise exception 'M6_SOURCE_OWNER' using errcode='42501';
 end if;
 return public.m6_capture_ledger(ev);
end $$;
"""


FUNCTIONS = (
    "m6_append_input(uuid,text,text,timestamptz,jsonb,uuid,uuid)",
    "m6_capture_ledger(public.learning_events)",
    "m6_capture_event_trigger()",
    "m6_capture_evidence_trigger()",
    "m6_initialize_user()",
    "m6_lock_source_owner(uuid)",
    "m6_recapture_event(uuid,uuid)",
)


def _deletion_sql(*, expanded: bool) -> str:
    # Reuse the immutable predecessor's exact deletion order, then add metadata
    # before its source FKs. A user lock fences every late FK-backed source/job.
    old = run_path(str(Path(__file__).with_name("0011a_account_deletion.py")))
    sql = old["_maintenance_function_sql"]().replace(
        "create function", "create or replace function", 1
    )
    if expanded:
        sql = sql.replace(
            "    delete from public.state_evidence_links",
            """
    perform 1 from public.app_users where id=p_user_id for update;
    if not found then return; end if;
    delete from public.jobs where user_id=p_user_id;
    delete from public.projection_inputs where user_id=p_user_id;
    delete from public.learner_projection_checkpoints where user_id=p_user_id;
    delete from public.projection_source_heads where user_id=p_user_id;
    delete from public.state_evidence_links""",
            1,
        )
    return sql


def upgrade():
    # The required revision identity exceeds Alembic's default VARCHAR(32).
    # Widen its bookkeeping column without changing any historical revision.
    op.alter_column(
        "alembic_version",
        "version_num",
        type_=sa.String(64),
        existing_type=sa.String(32),
    )
    _maintenance_execute("""do $$ begin
     if exists(select 1 from public.world_regions group by world_id,region_key having count(*)>1) then
      raise exception 'M6_REGION_DUPLICATES: resolve historical world_regions before 0020' using errcode='23505';
     end if;
    end $$""")
    op.alter_column(
        "learner_objective_state",
        "understanding_estimate",
        existing_type=sa.Double(),
        nullable=True,
    )
    op.add_column(
        "world_nodes", sa.Column("entity_version", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_world_nodes_entity_version",
        "world_nodes",
        "learning_entity_versions",
        ["entity_id", "entity_version"],
        ["entity_id", "version"],
    )
    op.create_check_constraint(
        "ck_world_nodes_entity_version",
        "world_nodes",
        "entity_version is null or entity_version>0",
    )
    op.create_unique_constraint(
        "uq_world_regions_world_key", "world_regions", ["world_id", "region_key"]
    )
    op.execute(TABLES)
    for table in (
        "projection_source_heads",
        "projection_inputs",
        "learner_projection_checkpoints",
    ):
        op.execute(f"alter table public.{table} enable row level security")
        op.execute(f"alter table public.{table} force row level security")
        op.execute(f"revoke all on public.{table} from public,app_backend,app_worker")
        op.execute(f"grant select on public.{table} to app_backend,app_worker")
        privileges = (
            "select,insert,delete"
            if table != "projection_source_heads"
            else "select,insert,update,delete"
        )
        op.execute(f"grant {privileges} on public.{table} to app_maintenance")
        op.execute(
            f"create policy {table}_owner_read on public.{table} for select to app_backend using(user_id=nullif(current_setting('app.user_id',true),'')::uuid)"
        )
        op.execute(f"""do $$ declare r text; begin
         for r in select rolname from pg_roles where rolname in ('anon','authenticated','service_role') loop
          execute format('revoke all on public.{table} from %I',r);
         end loop; end $$""")
    op.execute("grant update on public.learner_projection_checkpoints to app_worker")
    op.execute("grant update (id) on public.app_users to app_maintenance")
    # No backfill/import: initialize only the empty metadata of existing users.
    _maintenance_execute(
        "insert into public.projection_source_heads(user_id) select id from public.app_users"
    )
    _maintenance_execute(
        "insert into public.learner_projection_checkpoints(user_id) select id from public.app_users"
    )
    op.execute(
        "create unique index uq_jobs_projection_group on public.jobs(user_id,(payload->>'source_group')) where job_type='LEARNER_PROJECTION'"
    )
    op.execute(ALLOCATE)
    op.execute(LEDGER)
    op.execute(TRIGGERS)
    op.execute("grant select,insert,update on public.jobs to app_maintenance")
    op.execute("grant create on schema public to app_maintenance")
    guards = (
        "m6_input_shape()",
        "m6_input_immutable()",
        "m6_validate_job()",
        "m6_job_shape()",
        "m6_final_run_snapshot()",
    )
    # app_owner can revoke client grants only while it still owns these
    # functions; it does not inherit app_maintenance's ownership privileges.
    for function in (*FUNCTIONS, *guards):
        op.execute(f"""do $$ declare r text; begin
         for r in select rolname from pg_roles where rolname in ('anon','authenticated','service_role') loop
          execute format('revoke all on function public.{function} from %I',r);
         end loop; end $$""")
    for function in (*FUNCTIONS, *guards):
        op.execute(
            f"revoke all on function public.{function} from public,app_backend,app_worker"
        )
    op.execute(
        "grant execute on function public.m6_recapture_event(uuid,uuid),public.m6_lock_source_owner(uuid) to app_backend,app_worker"
    )
    for function in FUNCTIONS:
        op.execute(f"alter function public.{function} owner to app_maintenance")
    # This predecessor function is already owned by app_maintenance under
    # 0012; replace it as that role while its schema CREATE grant is active.
    _maintenance_execute(_deletion_sql(expanded=True))
    op.execute("revoke create on schema public from app_maintenance")


def downgrade():
    # A populated null estimate has no honest numeric inverse. Never synthesize
    # a value during rollback: the operator must resolve it before downgrading.
    _maintenance_execute("""do $$ begin
     if exists(select 1 from public.learner_objective_state where understanding_estimate is null) then
      raise exception 'M6_DOWNGRADE_NULL_ESTIMATE' using errcode='23514';
     end if;
    end $$""")
    op.execute(_deletion_sql(expanded=False))
    for table, trigger in (
        ("learning_events", "ct_m6_capture_event"),
        ("learning_evidence", "ct_m6_capture_evidence"),
        ("app_users", "trg_m6_initialize_user"),
        ("projection_inputs", "trg_m6_input_immutable"),
        ("projection_inputs", "trg_m6_input_shape"),
        ("jobs", "ct_m6_job_range"),
        ("jobs", "trg_m6_job_shape"),
        ("evaluation_runs", "trg_m6_final_run_snapshot"),
    ):
        op.execute(f"drop trigger {trigger} on public.{table}")
    for function in reversed(FUNCTIONS):
        op.execute(f"drop function public.{function}")
    for function in (
        "m6_input_shape()",
        "m6_input_immutable()",
        "m6_validate_job()",
        "m6_job_shape()",
        "m6_final_run_snapshot()",
    ):
        op.execute(f"drop function public.{function}")
    op.execute("drop index public.uq_jobs_projection_group")
    _maintenance_execute("delete from public.jobs where job_type='LEARNER_PROJECTION'")
    for table in (
        "projection_inputs",
        "learner_projection_checkpoints",
        "projection_source_heads",
    ):
        op.drop_table(table)
    op.execute("revoke update (id) on public.app_users from app_maintenance")
    op.execute("revoke insert,update on public.jobs from app_maintenance")
    op.drop_constraint("uq_world_regions_world_key", "world_regions", type_="unique")
    op.drop_constraint("ck_world_nodes_entity_version", "world_nodes", type_="check")
    op.drop_constraint(
        "fk_world_nodes_entity_version", "world_nodes", type_="foreignkey"
    )
    op.drop_column("world_nodes", "entity_version")
    op.alter_column(
        "learner_objective_state",
        "understanding_estimate",
        existing_type=sa.Double(),
        nullable=False,
    )


def _maintenance_execute(sql: str):
    """Read/seed forced-RLS rows using the provisioned maintenance membership.

    The object owner is deliberately NOBYPASSRLS. Do not let a migration
    preflight silently see an empty relation under FORCE RLS. Role changes are
    local to Alembic's transaction; failure rolls the role back with the DDL.
    """
    bind = op.get_bind()
    owner = bind.scalar(sa.text("select current_user"))
    quoted = bind.dialect.identifier_preparer.quote(owner)
    op.execute("set local role app_maintenance")
    op.execute(sql)
    op.execute(f"set local role {quoted}")
