package app.embyr.feature.journey

import app.embyr.auth.OwnerSession
import app.embyr.core.model.OnboardingRequestDto
import app.embyr.core.model.StarterInterestPageDto
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
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

sealed interface OnboardingOutcome {
    data object Completed : OnboardingOutcome
    data object Reconciled : OnboardingOutcome
    data object Pending : OnboardingOutcome
    data object Unresolved : OnboardingOutcome
    data class InvalidStarters(val remainingIds: List<String>) : OnboardingOutcome
    data class Failed(val error: TransportError) : OnboardingOutcome
}

class OnboardingRepository(
    private val api: EmbyrApi,
    private val owners: OwnerSession,
    private val store: JourneyStore,
    private val outbox: CommandOutbox,
    private val dispatcher: CommandDispatcher,
    private val now: () -> Long = System::currentTimeMillis,
) {
    private companion object { val mutex = Mutex() }
    private val route = "api/v1/me/onboarding/complete"

    suspend fun starters(): ApiResult<StarterInterestPageDto> = api.starterInterests()
    suspend fun draft(): List<String> = store.read(owners.requireOwner()).selectedStarterIds

    suspend fun saveDraft(ids: List<String>) = mutex.withLock {
        validateDraft(ids)
        store.saveDraft(owners.requireOwner(), ids)
    }

    private fun validateDraft(ids: List<String>) {
        require(ids.size <= 20 && ids.distinct().size == ids.size && ids.all { runCatching { UUID.fromString(it) }.isSuccess })
    }

    suspend fun submit(ids: List<String>, explicitNewAfterExpiry: Boolean = false): OnboardingOutcome = mutex.withLock {
        validateDraft(ids)
        val owner = owners.requireOwner()
        store.saveDraft(owner, ids)
        val previous = outbox.unresolved(owner).lastOrNull { it.relativeRoute == route }
        if (previous != null) {
            val resumed = resumeLocked(previous)
            if (resumed != OnboardingOutcome.Unresolved || !explicitNewAfterExpiry) return@withLock resumed
            outbox.mark(owner, previous.id, CommandState.RESOLVED)
        }
        var latest: OnboardingOutcome = OnboardingOutcome.Pending
        val command = dispatcher.persistThenSend(
            owner, "POST", route, OnboardingRequestDto.serializer(), OnboardingRequestDto(starterInterestEntityIds = ids), now(),
        ) { pending -> transmit(pending) { latest = it } }
        when (CommandState.valueOf(command.state)) {
            CommandState.ACKNOWLEDGED -> OnboardingOutcome.Completed
            CommandState.RESOLVED -> latest
            else -> latest
        }
    }

    suspend fun resume(): OnboardingOutcome? = mutex.withLock {
        val owner = owners.requireOwner()
        outbox.unresolved(owner).lastOrNull { it.relativeRoute == route }?.let { resumeLocked(it) }
    }

    private suspend fun resumeLocked(command: CommandEntity): OnboardingOutcome {
        val owner = owners.requireOwner()
        if (!ReplayWindow.mayReplay(command.createdAtEpochMs, now())) {
            outbox.mark(owner, command.id, CommandState.EXPIRED)
            return reconcile(command)
        }
        var latest: OnboardingOutcome = OnboardingOutcome.Pending
        val state = dispatcher.retry(owner, command.id, now()) { transmit(it) { result -> latest = result } }
        return when (state) {
            CommandState.ACKNOWLEDGED -> OnboardingOutcome.Completed
            CommandState.EXPIRED -> reconcile(command)
            else -> latest
        }
    }

    private suspend fun transmit(command: CommandEntity, set: (OnboardingOutcome) -> Unit): TransmissionOutcome {
        val result = api.completeOnboarding(command.canonicalPayload, command.idempotencyKey)
        return when (result) {
            is ApiResult.Success -> {
                set(OnboardingOutcome.Completed)
                TransmissionOutcome.Acknowledged(result.value.onboardingCompletedAt)
            }
            is ApiResult.Failure -> when {
                result.error.code() == "ONBOARDING_ALREADY_COMPLETED" -> {
                    val reconciled = reconcile(command)
                    set(reconciled)
                    if (reconciled == OnboardingOutcome.Reconciled) TransmissionOutcome.Resolved("reconciled") else TransmissionOutcome.Ambiguous
                }
                result.error.code() == "INVALID_STARTER_INTEREST" -> {
                    val valid = (api.starterInterests() as? ApiResult.Success)?.value?.items?.map { it.id }?.toSet()
                    if (valid != null) {
                        val kept = store.read(command.ownerId).selectedStarterIds.filter { it in valid }
                        store.saveDraft(command.ownerId, kept)
                        set(OnboardingOutcome.InvalidStarters(kept))
                    } else set(OnboardingOutcome.Failed(result.error))
                    TransmissionOutcome.Rejected
                }
                result.error is TransportError.Network || result.error is TransportError.AmbiguousTimeout || result.error.code() == "COMMAND_IN_PROGRESS" -> {
                    set(OnboardingOutcome.Pending)
                    TransmissionOutcome.Ambiguous
                }
                else -> {
                    set(OnboardingOutcome.Failed(result.error))
                    TransmissionOutcome.Rejected
                }
            }
        }
    }

    private suspend fun reconcile(command: CommandEntity): OnboardingOutcome {
        val profile = api.profile()
        if (profile is ApiResult.Success && profile.value.id == command.ownerId && profile.value.onboardingCompletedAt != null) {
            outbox.mark(command.ownerId, command.id, CommandState.RESOLVED, "reconciled")
            return OnboardingOutcome.Reconciled
        }
        return OnboardingOutcome.Unresolved
    }
}

internal fun TransportError.code(): String? = (this as? TransportError.Problem)?.details?.code
