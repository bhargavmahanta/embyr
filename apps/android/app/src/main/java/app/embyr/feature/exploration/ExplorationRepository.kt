package app.embyr.feature.exploration

import app.embyr.core.model.*
import app.embyr.core.network.*
import app.embyr.auth.OwnerSession
import app.embyr.core.storage.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.serialization.json.Json

class ExplorationRepository(
    private val api: LearningApi, private val owners: OwnerSession,
    private val store: LearningStore, private val commands: LearningCommands,
) {
    private val json = LearningJson.codec
    private val editMutex = Mutex()
    suspend fun restoreReceipts() = commands.recoverReceipts()
    suspend fun pending(id: String): List<String> = commands.pending("api/v1/explorations/$id/").map { it.relativeRoute.substringAfterLast('/') }.distinct()
    suspend fun recover(id: String): LearningOutcome {
        var outcome: LearningOutcome = LearningOutcome.Done
        commands.pending("api/v1/explorations/$id/").forEach { command ->
            val result = when (command.relativeRoute.substringAfterLast('/')) {
                "delivery" -> deliver(id)
                "actions" -> action(id,json.decodeFromString(ExplorationActionRequest.serializer(),command.canonicalPayload.decodeToString()).action)
                "completion" -> complete(id)
                "reflections" -> saveReflection(id)
                else -> LearningOutcome.Unknown
            }
            if (result != LearningOutcome.Done) outcome = result
        }
        return outcome
    }
    suspend fun page(cursor: String? = null) = api.explorationList(50, cursor)
    suspend fun read(id: String) = store.exploration(owners.requireOwner(), id)
    suspend fun open(id: String): LearningOutcome {
        val owner = owners.requireOwner()
        return when (val result = api.exploration(id)) {
            is ApiResult.Failure -> LearningOutcome.Failed(result.error)
            is ApiResult.Success -> {
                check(result.value.id == id)
                store.updateExploration(owner, id) { row -> row.copy(
                    detailJson = json.encodeToString(ExplorationDetailDto.serializer(), result.value),
                    draft = if (row.draftInitialized) row.draft else result.value.reflection?.text.orEmpty(),
                    draftInitialized = true,
                ) }
                LearningOutcome.Done
            }
        }
    }
    suspend fun select(id: String?) {
        val owner = owners.requireOwner(); val prior = store.activity(owner)
        store.putActivity(if (id != null && prior.explorationId == id) prior else ActivityStateEntity(owner,id))
    }
    suspend fun saveDraft(id: String, text: String) {
        require(text.length <= 10000)
        store.updateExploration(owners.requireOwner(), id) { it.copy(draft = text, draftInitialized = true) }
    }
    suspend fun deliver(id: String): LearningOutcome {
        val owner = owners.requireOwner()
        return commands.post("api/v1/explorations/$id/delivery", EmptyLearningRequest.serializer(), EmptyLearningRequest(), DeliveryDto.serializer(),
            send = { api.deliver(id, it.canonicalPayload, it.idempotencyKey) },
            persist = { delivery -> store.updateExploration(owner,id) { row -> row.copy(detailJson = json.encodeToString(ExplorationDetailDto.serializer(), requireNotNull(row.detail()).copy(delivery = delivery))) } },
            reference = { it.contentId }, reconcile = { open(id); read(id).detail()?.delivery })
    }
    suspend fun action(id: String, action: String): LearningOutcome {
        require(action in setOf("RETURN", "PAUSE", "RESUME"))
        val owner = owners.requireOwner()
        val detail = read(id).detail() ?: return LearningOutcome.Invalid("Refresh this exploration first.")
        if (!commands.hasPending("api/v1/explorations/$id/actions") && (detail.status == "COMPLETED" || (action == "PAUSE" && detail.status != "ACTIVE") || (action == "RESUME" && detail.status != "PAUSED"))) return LearningOutcome.Invalid("This action is unavailable in the current state.")
        val result = commands.post("api/v1/explorations/$id/actions", ExplorationActionRequest.serializer(), ExplorationActionRequest(action, detail.version), ExplorationDto.serializer(),
            send = { api.explorationAction(id, it.canonicalPayload, it.idempotencyKey) }, persist = { saveLifecycle(owner, it) }, reference = { it.id },
            reconcile = { open(id); null })
        if (result is LearningOutcome.Conflict) open(id)
        return result
    }
    suspend fun complete(id: String): LearningOutcome {
        val owner = owners.requireOwner()
        val detail = read(id).detail() ?: return LearningOutcome.Invalid("Refresh this exploration first.")
        if (detail.status == "COMPLETED" && !commands.hasPending("api/v1/explorations/$id/completion")) return LearningOutcome.Done
        val result = commands.post("api/v1/explorations/$id/completion", CompletionRequest.serializer(), CompletionRequest(detail.version), ExplorationDto.serializer(),
            send = { api.completeExploration(id, it.canonicalPayload, it.idempotencyKey) }, persist = { saveLifecycle(owner, it) }, reference = { it.id },
            reconcile = { open(id); read(id).detail()?.takeIf { it.status == "COMPLETED" }?.base() })
        if (result is LearningOutcome.Conflict) open(id)
        return result
    }
    private suspend fun saveLifecycle(owner: String, value: ExplorationDto) {
        store.updateExploration(owner, value.id) { row ->
            val d = requireNotNull(row.detail())
            if (value.version < d.version) row else row.copy(detailJson = json.encodeToString(ExplorationDetailDto.serializer(), d.copy(status = value.status, version = value.version, returnedAt = value.returnedAt, pausedAt = value.pausedAt, completedAt = value.completedAt)))
        }
    }
    private suspend fun saveReflectionValue(owner: String, id: String, value: ReflectionDto) {
        check(value.explorationId == id)
        store.updateExploration(owner,id) { row -> row.copy(detailJson = json.encodeToString(ExplorationDetailDto.serializer(), requireNotNull(row.detail()).copy(reflection = value))) }
    }
    suspend fun saveReflection(id: String, applyFresh: Boolean = false): LearningOutcome {
        if (!editMutex.tryLock()) return LearningOutcome.Pending
        try {
            val owner = owners.requireOwner(); var row = read(id)
            if (row.draft.isBlank() || row.draft.length > 10000) return LearningOutcome.Invalid("Write a reflection of 1–10000 characters.")
            if (row.editJson != null && !applyFresh) return reconcileEdit(id)
            val reflection = row.detail()?.reflection
            if (reflection == null || commands.hasPending("api/v1/explorations/$id/reflections")) {
                return commands.post("api/v1/explorations/$id/reflections", ReflectionRequest.serializer(), ReflectionRequest(row.draft), ReflectionDto.serializer(),
                    send = { api.createReflection(id, it.canonicalPayload, it.idempotencyKey) }, persist = { saveReflectionValue(owner,id,it) }, reference = { it.id },
                    reconcile = { command -> open(id); read(id).detail()?.reflection?.takeIf { it.id == command.knownResultReference } })
            }
            if (applyFresh) {
                val refreshed = open(id); if (refreshed != LearningOutcome.Done) return refreshed
                row = read(id)
                if (row.detail()?.reflection?.id != reflection.id) return LearningOutcome.Unknown
                if (row.detail()?.reflection?.version != reflection.version) return LearningOutcome.Conflict("The server changed again. Review this refreshed version before applying your draft.")
            }
            val current = requireNotNull(row.detail()?.reflection)
            if (current.text == row.draft) {
                store.updateExploration(owner,id) { it.copy(editJson = null, editState = null, editReflectionId = null) }
                return LearningOutcome.Done
            }
            val payload = ReflectionEditRequest(current.version, row.draft)
            val bytes = CanonicalPayload.encode(ReflectionEditRequest.serializer(), payload)
            store.updateExploration(owner,id) { it.copy(editJson = bytes.decodeToString(), editReflectionId = current.id, editState = "IN_FLIGHT") }
            return when (val result = api.editReflection(current.id, bytes)) {
                is ApiResult.Success -> {
                    saveReflectionValue(owner,id,result.value)
                    store.updateExploration(owner,id) { it.copy(editJson = null, editReflectionId = null, editState = null) }
                    LearningOutcome.Done
                }
                is ApiResult.Failure -> {
                    val conflict = result.error is TransportError.Problem && result.error.details.code == "VERSION_CONFLICT"
                    store.updateExploration(owner,id) { it.copy(editState = if (conflict) "CONFLICT" else "UNKNOWN") }
                    if (conflict) { open(id); LearningOutcome.Conflict("Your draft is retained. Review the current reflection before applying it again.") }
                    else LearningOutcome.Unknown
                }
            }
        } finally { editMutex.unlock() }
    }
    suspend fun reconcileEdit(id: String): LearningOutcome {
        val owner = owners.requireOwner(); val row = read(id); val raw = row.editJson ?: return LearningOutcome.Done
        val submitted = json.decodeFromString(ReflectionEditRequest.serializer(), raw)
        val fetched = open(id); if (fetched != LearningOutcome.Done) return fetched
        val server = read(id).detail()?.reflection ?: return LearningOutcome.Unknown
        if (server.id != row.editReflectionId) return LearningOutcome.Unknown
        if (server.version > submitted.baseVersion && server.text == submitted.text) {
            store.updateExploration(owner,id) { it.copy(editJson = null, editReflectionId = null, editState = null) }
            return LearningOutcome.Done
        }
        return if (server.version > submitted.baseVersion) LearningOutcome.Conflict("The server reflection changed; your draft is retained.") else LearningOutcome.Unknown
    }
}

fun ExplorationDetailDto.base() = ExplorationDto(id, entityId, entityVersion, recommendationId, practicalChallengeId, practicalChallengeVersionId, learningIntent, status, startedAt, returnedAt, pausedAt, completedAt, version)
