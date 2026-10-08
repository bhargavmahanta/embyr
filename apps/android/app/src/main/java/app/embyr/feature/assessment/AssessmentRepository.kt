package app.embyr.feature.assessment

import app.embyr.core.model.*
import app.embyr.core.network.*
import app.embyr.auth.OwnerSession
import app.embyr.core.storage.*

class AssessmentRepository(
    private val api: LearningApi, private val answerApi: EmbyrApi, private val owners: OwnerSession,
    private val store: LearningStore, private val commands: LearningCommands,
) {
    private val json = LearningJson.codec
    suspend fun hasPendingStart(exploration: String) = commands.hasPending("api/v1/explorations/$exploration/assessment-sessions")
    suspend fun recoverStart(exploration: String): LearningOutcome {
        val original = commands.pending("api/v1/explorations/$exploration/assessment-sessions").firstOrNull()
            ?: return LearningOutcome.Invalid("There is no saved start request to recover.")
        val body = json.decodeFromString(AssessmentStartRequest.serializer(),original.canonicalPayload.decodeToString())
        return start(exploration,body.confidenceBefore)
    }
    suspend fun pending(id: String): List<String> {
        val row = read(id) ?: return emptyList()
        return buildList {
            if (hasPendingStart(row.explorationId)) add("start")
            commands.pending("api/v1/assessment-sessions/$id/").forEach {
                add(if (it.relativeRoute.endsWith("/responses")) "answer" else "support")
            }
            row.responseId?.let { rid -> if (commands.hasPending("api/v1/assessment-responses/$rid/evaluation-retries")) add("retry") }
        }.distinct()
    }
    suspend fun recover(id: String): LearningOutcome {
        val row = read(id) ?: return LearningOutcome.Invalid("Refresh the assessment first.")
        var outcome: LearningOutcome = LearningOutcome.Done
        for (kind in pending(id)) {
            val result = when (kind) {
                "start" -> recoverStart(row.explorationId)
                "answer" -> {
                    val original = commands.pending("api/v1/assessment-sessions/$id/responses").first()
                    answer(id,json.decodeFromString(AnswerRequest.serializer(),original.canonicalPayload.decodeToString()).content.optionId)
                }
                "support" -> {
                    val original = commands.pending("api/v1/assessment-sessions/$id/support-requests").first()
                    support(id,json.decodeFromString(SupportRequest.serializer(),original.canonicalPayload.decodeToString()).level)
                }
                "retry" -> retry(id)
                else -> LearningOutcome.Unknown
            }
            if (result != LearningOutcome.Done) outcome = result
        }
        return outcome
    }
    suspend fun leave(id: String) {
        val owner = owners.requireOwner(); val current = store.activity(owner)
        if (current.sessionId == id) store.putActivity(current.copy(sessionId = null))
    }
    suspend fun storedSession(exploration: String): String? = store.assessmentForExploration(owners.requireOwner(),exploration).singleOrNull()?.sessionId
    suspend fun read(id: String) = store.assessment(owners.requireOwner(),id)
    private suspend fun saveSession(owner: String, value: AssessmentSessionDto) {
        store.updateAssessment(owner,value.id) { prior ->
            (prior ?: AssessmentStateEntity(owner,value.id,value.explorationId,""))
                .copy(sessionJson = json.encodeToString(AssessmentSessionDto.serializer(),value),responseId = prior?.responseId ?: value.responseId)
        }
    }
    suspend fun start(exploration: String, confidence: String): LearningOutcome {
        require(confidence in setOf("FUZZY","MAIN_IDEA","COULD_EXPLAIN","CHALLENGE_ME"))
        val owner = owners.requireOwner()
        val result = commands.post("api/v1/explorations/$exploration/assessment-sessions", AssessmentStartRequest.serializer(), AssessmentStartRequest(confidence), AssessmentSessionDto.serializer(),
            send = { api.startAssessment(exploration, it.canonicalPayload, it.idempotencyKey) }, persist = { check(it.explorationId == exploration); saveSession(owner,it) }, reference = { it.id },
            reconcile = { command ->
                val original = json.decodeFromString(AssessmentStartRequest.serializer(),command.canonicalPayload.decodeToString())
                when (val detail = api.exploration(exploration)) {
                is ApiResult.Failure -> null
                is ApiResult.Success -> detail.value.assessmentSession?.let { ref ->
                    (api.assessmentSession(ref.id) as? ApiResult.Success)?.value?.takeIf { it.explorationId == exploration && it.confidenceBefore == original.confidenceBefore }
                }
            } })
        return result
    }
    suspend fun open(id: String): LearningOutcome {
        val owner = owners.requireOwner()
        return when (val result = api.assessmentSession(id)) {
            is ApiResult.Failure -> LearningOutcome.Failed(result.error)
            is ApiResult.Success -> {
                check(result.value.id == id); saveSession(owner,result.value)
                store.putActivity(ActivityStateEntity(owner,result.value.explorationId,id))
                refresh(id)
            }
        }
    }
    suspend fun refresh(id: String, followCurrent: Boolean = false): LearningOutcome {
        val owner = owners.requireOwner(); val row = store.assessment(owner,id) ?: return LearningOutcome.Invalid("Refresh the assessment first.")
        val responseId = row.responseId ?: return LearningOutcome.Done
        return when (val result = api.assessmentResponse(responseId)) {
            is ApiResult.Failure -> LearningOutcome.Failed(result.error)
            is ApiResult.Success -> {
                val value = result.value; check(value.responseId == responseId && value.assessmentSessionId == id)
                var accepted = false
                store.updateAssessment(owner,id) { latestRow ->
                    val latest = requireNotNull(latestRow)
                    if (latest.knownRunId != row.knownRunId || (!followCurrent && row.responseJson == null && row.knownRunId != null && value.evaluationRunId != row.knownRunId)) latest
                    else {
                        accepted = true
                        latest.copy(responseJson = json.encodeToString(AssessmentResponseDto.serializer(),value), knownRunId = value.evaluationRunId ?: latest.knownRunId)
                    }
                }
                if (accepted) LearningOutcome.Done else LearningOutcome.Pending
            }
        }
    }
    suspend fun support(id: String, level: String): LearningOutcome {
        require(level in setOf("SMALL_NUDGE","STRONG_HINT","MISSING_CONCEPT","EXPLANATION"))
        val owner = owners.requireOwner(); val row = read(id) ?: return LearningOutcome.Invalid("Refresh the assessment first.")
        val s = row.session(); val route = "api/v1/assessment-sessions/$id/support-requests"
        if (!commands.hasPending(route)) {
            if (s.deliveredSupport.any { it.level == level }) return LearningOutcome.Done
            if (row.responseId != null || s.status != "ACTIVE") return LearningOutcome.Invalid("Support is available before answering an active check.")
        }
        return commands.post(route, SupportRequest.serializer(), SupportRequest(s.interaction.id,level), SupportDto.serializer(),
            send = { api.requestSupport(id,it.canonicalPayload,it.idempotencyKey) }, persist = { value ->
                store.updateAssessment(owner,id) { row ->
                    val latest = requireNotNull(row); val session = latest.session()
                    val next = session.copy(deliveredSupport = session.deliveredSupport.filterNot { it.id == value.id } + value)
                    latest.copy(sessionJson = json.encodeToString(AssessmentSessionDto.serializer(),next))
                }
            }, reference = { it.id }, reconcile = { command ->
                val submitted = json.decodeFromString(SupportRequest.serializer(),command.canonicalPayload.decodeToString())
                (api.assessmentSession(id) as? ApiResult.Success)?.value?.takeIf { it.interaction.id == submitted.interactionId }?.deliveredSupport?.firstOrNull { it.level == submitted.level }
            })
    }
    suspend fun answer(id: String, option: String): LearningOutcome {
        val owner = owners.requireOwner(); val row = read(id) ?: return LearningOutcome.Invalid("Refresh the assessment first.")
        val s = row.session(); val route = "api/v1/assessment-sessions/$id/responses"
        if (!commands.hasPending(route)) {
            if (row.responseId != null) return refresh(id)
            if (s.status != "ACTIVE" || s.interaction.options.none { it.id == option }) return LearningOutcome.Invalid("Choose one returned option in this active check.")
            store.putAssessment(row.copy(selectedOptionId = option))
        }
        val result = commands.post(route, AnswerRequest.serializer(), AnswerRequest(s.interaction.id,content = ChoiceContent(option)), AnswerAcknowledgmentDto.serializer(),
            send = { answerApi.submitAnswer(id,it.canonicalPayload,it.idempotencyKey) }, persist = { ack ->
                store.updateAssessment(owner,id) { latest -> requireNotNull(latest).copy(responseId = ack.responseId) }
            }, reference = { it.responseId }, reconcile = { command ->
                command.knownResultReference?.let { rid -> (api.assessmentResponse(rid) as? ApiResult.Success)?.value }
                    ?.takeIf { it.assessmentSessionId == id }?.let { AnswerAcknowledgmentDto(it.responseId,"PENDING","WAITING_FOR_EVALUATION",null) }
            })
        if (result == LearningOutcome.Done) refresh(id)
        return result
    }
    suspend fun retry(id: String): LearningOutcome {
        val owner = owners.requireOwner(); val row = read(id) ?: return LearningOutcome.Invalid("Refresh the assessment first.")
        val responseId = row.responseId ?: return LearningOutcome.Invalid("There is no submitted answer to retry.")
        val route = "api/v1/assessment-responses/$responseId/evaluation-retries"
        val response = row.response()
        if (!commands.hasPending(route) && (response?.evaluationStatus != "FAILED" || !response.retryAllowed)) return LearningOutcome.Invalid("Retry is unavailable for this evaluation.")
        val result = commands.post(route, EmptyLearningRequest.serializer(), EmptyLearningRequest(), EvaluationRetryDto.serializer(),
            send = { api.retryEvaluation(responseId,it.canonicalPayload,it.idempotencyKey) }, persist = { ack ->
                check(ack.responseId == responseId)
                store.updateAssessment(owner,id) { latestRow ->
                    val latest = requireNotNull(latestRow)
                    if (latest.knownRunId != ack.evaluationRunId) latest.copy(knownRunId = ack.evaluationRunId,responseJson = null) else latest
                }
            }, reference = { it.evaluationRunId }, reconcile = { command ->
                command.knownResultReference?.let { run -> (api.assessmentResponse(responseId) as? ApiResult.Success)?.value?.takeIf { it.evaluationRunId == run } }
                    ?.let { EvaluationRetryDto(responseId,"PENDING","WAITING_FOR_EVALUATION",null,requireNotNull(it.evaluationRunId)) }
            })
        if (result == LearningOutcome.Done) refresh(id,followCurrent = true)
        return result
    }
}
