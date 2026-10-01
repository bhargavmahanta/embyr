package app.embyr.feature.journey

import app.embyr.auth.OwnerSession
import app.embyr.core.model.RecommendationDecisionRequestDto
import app.embyr.core.model.RecommendationDecisionResult
import app.embyr.core.model.RecommendationRequestDto
import app.embyr.core.model.RecommendationResult
import app.embyr.core.network.ApiResult
import app.embyr.core.network.EmbyrApi
import app.embyr.core.network.TransportError
import app.embyr.core.storage.CommandDispatcher
import app.embyr.core.storage.CommandEntity
import app.embyr.core.storage.CommandOutbox
import app.embyr.core.storage.CommandState
import app.embyr.core.storage.JourneyStore
import app.embyr.core.storage.ReplayWindow
import app.embyr.core.storage.TransmissionOutcome
import java.util.UUID
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.Json

sealed interface RecommendationOutcome {
    data class Found(val recommendationId: String) : RecommendationOutcome
    data object NoResult : RecommendationOutcome
    data class Accepted(val recommendationId: String, val explorationId: String) : RecommendationOutcome
    data class Skipped(val recommendationId: String) : RecommendationOutcome
    data object Pending : RecommendationOutcome
    data object Unresolved : RecommendationOutcome
    data class Failed(val error: TransportError) : RecommendationOutcome
}

class RecommendationRepository(
    private val api: EmbyrApi,
    private val owners: OwnerSession,
    private val store: JourneyStore,
    private val outbox: CommandOutbox,
    private val dispatcher: CommandDispatcher,
    private val now: () -> Long = System::currentTimeMillis,
) {
    private companion object { val mutex = Mutex() }
    private val json = Json { ignoreUnknownKeys = true }
    private val nextRoute = "api/v1/recommendations/next"
    private val decisionPrefix = "api/v1/recommendations/"

    suspend fun generate(mode: String, explicitNewAfterExpiry: Boolean = false): RecommendationOutcome = mutex.withLock {
        require(mode == "EXPLORE" || mode == "SURPRISE")
        val owner = owners.requireOwner()
        val previous = outbox.unresolved(owner).lastOrNull { it.relativeRoute == nextRoute }
        if (previous != null) {
            val resumed = resumeNextLocked(previous)
            if (resumed != RecommendationOutcome.Unresolved || !explicitNewAfterExpiry) return@withLock resumed
            outbox.mark(owner, previous.id, CommandState.RESOLVED)
        }
        var latest: RecommendationOutcome = RecommendationOutcome.Pending
        dispatcher.persistThenSend(
            owner, "POST", nextRoute, RecommendationRequestDto.serializer(), RecommendationRequestDto(mode), now(),
        ) { command -> transmitNext(command) { latest = it } }
        latest
    }

    suspend fun resumeGeneration(): RecommendationOutcome? = mutex.withLock {
        val owner = owners.requireOwner()
        outbox.unresolved(owner).lastOrNull { it.relativeRoute == nextRoute }?.let { resumeNextLocked(it) }
    }

    private suspend fun resumeNextLocked(command: CommandEntity): RecommendationOutcome {
        if (!ReplayWindow.mayReplay(command.createdAtEpochMs, now())) {
            outbox.mark(command.ownerId, command.id, CommandState.EXPIRED)
            return RecommendationOutcome.Unresolved
        }
        var latest: RecommendationOutcome = RecommendationOutcome.Pending
        dispatcher.retry(command.ownerId, command.id, now()) { transmitNext(it) { result -> latest = result } }
        return latest
    }

    private suspend fun transmitNext(command: CommandEntity, set: (RecommendationOutcome) -> Unit): TransmissionOutcome {
        repeat(3) { attempt ->
            when (val response = api.nextRecommendation(command.canonicalPayload, command.idempotencyKey)) {
                is ApiResult.Success -> {
                    val result = response.value
                    // The public presentation commits before the dispatcher acknowledges the command.
                    when (result) {
                        is RecommendationResult.Found -> {
                            store.savePresentation(command.ownerId, result.recommendation)
                            set(RecommendationOutcome.Found(result.recommendation.id))
                        }
                        RecommendationResult.NoResult -> {
                            store.savePresentation(command.ownerId, null)
                            set(RecommendationOutcome.NoResult)
                        }
                    }
                    return TransmissionOutcome.Acknowledged()
                }
                is ApiResult.Failure -> {
                    if (response.error.code() == "COMMAND_IN_PROGRESS") {
                        if (attempt < 2) delay((attempt + 1) * 400L)
                        return@repeat
                    }
                    return classifyFailure(response.error, set)
                }
            }
        }
        set(RecommendationOutcome.Pending)
        return TransmissionOutcome.Ambiguous
    }

    suspend fun decide(recommendationId: String, decision: String): RecommendationOutcome = mutex.withLock {
        require(runCatching { UUID.fromString(recommendationId) }.isSuccess)
        require(decision == "ACCEPT" || decision == "SKIP")
        val owner = owners.requireOwner()
        val route = "$decisionPrefix$recommendationId/decision"
        val previous = outbox.unresolved(owner).lastOrNull { it.relativeRoute == route }
        if (previous != null) return@withLock resumeDecisionLocked(previous)
        var latest: RecommendationOutcome = RecommendationOutcome.Pending
        dispatcher.persistThenSend(
            owner, "POST", route, RecommendationDecisionRequestDto.serializer(), RecommendationDecisionRequestDto(decision), now(),
        ) { command -> transmitDecision(command) { latest = it } }
        latest
    }

    suspend fun resumeDecision(): RecommendationOutcome? = mutex.withLock {
        val owner = owners.requireOwner()
        outbox.unresolved(owner).lastOrNull { it.relativeRoute.startsWith(decisionPrefix) && it.relativeRoute.endsWith("/decision") }
            ?.let { resumeDecisionLocked(it) }
    }

    private suspend fun resumeDecisionLocked(command: CommandEntity): RecommendationOutcome {
        if (!ReplayWindow.mayReplay(command.createdAtEpochMs, now())) {
            outbox.mark(command.ownerId, command.id, CommandState.EXPIRED)
            return if (intendedDecision(command) == "ACCEPT") reconcileAccept(command) else RecommendationOutcome.Unresolved
        }
        var latest: RecommendationOutcome = RecommendationOutcome.Pending
        dispatcher.retry(command.ownerId, command.id, now()) { transmitDecision(it) { result -> latest = result } }
        return latest
    }

    private suspend fun transmitDecision(command: CommandEntity, set: (RecommendationOutcome) -> Unit): TransmissionOutcome {
        val id = recommendationId(command)
        val intended = intendedDecision(command)
        val response = api.decideRecommendation(id, command.canonicalPayload, command.idempotencyKey)
        return when (response) {
            is ApiResult.Success -> when (val result = response.value) {
                is RecommendationDecisionResult.Accepted -> {
                    if (intended != "ACCEPT") {
                        set(RecommendationOutcome.Unresolved)
                        TransmissionOutcome.Ambiguous
                    } else {
                        store.saveAcceptance(command.ownerId, id, result.exploration.id)
                        set(RecommendationOutcome.Accepted(id, result.exploration.id))
                        TransmissionOutcome.Acknowledged(result.exploration.id)
                    }
                }
                is RecommendationDecisionResult.Skipped -> {
                    if (intended != "SKIP" || result.result.recommendationId != id) {
                        set(RecommendationOutcome.Unresolved)
                        TransmissionOutcome.Ambiguous
                    } else {
                        store.saveSkip(command.ownerId, id)
                        set(RecommendationOutcome.Skipped(id))
                        TransmissionOutcome.Acknowledged(id)
                    }
                }
            }
            is ApiResult.Failure -> {
                if (response.error.code() == "RECOMMENDATION_ALREADY_DECIDED") {
                    val reconciled = if (intended == "ACCEPT") reconcileAccept(command) else RecommendationOutcome.Unresolved
                    set(reconciled)
                    if (reconciled is RecommendationOutcome.Accepted) TransmissionOutcome.Resolved(reconciled.explorationId) else TransmissionOutcome.Ambiguous
                } else classifyFailure(response.error, set)
            }
        }
    }

    private suspend fun reconcileAccept(command: CommandEntity): RecommendationOutcome {
        val id = recommendationId(command)
        var cursor: String? = null
        repeat(5) {
            when (val page = api.explorations(100, cursor)) {
                is ApiResult.Failure -> return RecommendationOutcome.Unresolved
                is ApiResult.Success -> {
                    val match = page.value.items.firstOrNull { it.recommendationId == id }
                    if (match != null) {
                        store.saveAcceptance(command.ownerId, id, match.id)
                        outbox.mark(command.ownerId, command.id, CommandState.RESOLVED, match.id)
                        return RecommendationOutcome.Accepted(id, match.id)
                    }
                    cursor = page.value.nextCursor ?: return RecommendationOutcome.Unresolved
                }
            }
        }
        return RecommendationOutcome.Unresolved
    }

    private fun intendedDecision(command: CommandEntity): String =
        json.decodeFromString(RecommendationDecisionRequestDto.serializer(), command.canonicalPayload.decodeToString()).decision

    private fun recommendationId(command: CommandEntity): String =
        command.relativeRoute.removePrefix(decisionPrefix).removeSuffix("/decision")

    private fun classifyFailure(error: TransportError, set: (RecommendationOutcome) -> Unit): TransmissionOutcome {
        return if (error is TransportError.Network || error is TransportError.AmbiguousTimeout || error.code() == "COMMAND_IN_PROGRESS") {
            set(RecommendationOutcome.Pending)
            TransmissionOutcome.Ambiguous
        } else {
            set(RecommendationOutcome.Failed(error))
            TransmissionOutcome.Rejected
        }
    }
}
