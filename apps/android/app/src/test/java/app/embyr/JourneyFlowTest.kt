package app.embyr

import app.embyr.auth.AuthGateway
import app.embyr.auth.AuthState
import app.embyr.auth.EmailCodeResult
import app.embyr.auth.OwnerSession
import app.embyr.auth.SessionIdentity
import app.embyr.core.model.*
import app.embyr.core.network.*
import app.embyr.core.storage.*
import app.embyr.feature.journey.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class JourneyFlowTest {
    private val ownerA = "00000000-0000-0000-0000-000000000001"
    private val ownerB = "00000000-0000-0000-0000-000000000002"
    private val recId = "00000000-0000-0000-0000-000000000003"
    private val explorationId = "00000000-0000-0000-0000-000000000004"

    @Test fun bootstrapRefreshesOnceBeforeBindingMappedOwnerAndGetsMe() = runBlocking {
        val owners = OwnerSession()
        val api = FakeApi(ownerA)
        api.bootstrapResults += ApiResult.Failure(TransportError.Authentication())
        api.bootstrapResults += ok(profile(ownerA))
        val auth = FakeAuth()
        val outcome = SessionRepository(auth, api, owners).bootstrap()
        assertTrue(outcome is SessionOutcome.Ready)
        assertEquals(ownerA, owners.requireOwner())
        assertEquals(1, auth.refreshes)
        assertEquals(2, api.bootstrapCalls)
        assertEquals(1, api.profileCalls)
    }

    @Test fun unmappedIdentityNeverBindsOwnerOrRetriesWithRefresh() = runBlocking {
        val owners = OwnerSession()
        val api = FakeApi(ownerA)
        api.bootstrapResults += ApiResult.Failure(TransportError.Authentication(ProblemDetails(code = "UNMAPPED_IDENTITY", requestId = "request-1")))
        val auth = FakeAuth()
        val outcome = SessionRepository(auth, api, owners).bootstrap()
        assertTrue(outcome is SessionOutcome.Recoverable)
        assertEquals(null, owners.owner.value)
        assertEquals(0, auth.refreshes)
        assertEquals(1, api.bootstrapCalls)
    }

    @Test fun onboardingHasFrozenPayloadOneKeyAndExactRetryAfterAmbiguity() = runBlocking {
        val fixture = Fixture(ownerA)
        val starterId = "00000000-0000-0000-0000-000000000005"
        fixture.api.onboardingResults += ApiResult.Failure(TransportError.Network("IO"))
        fixture.api.onboardingResults += ok(OnboardingResultDto(preferences(), "2026-10-01T00:00:00Z"))
        val repo = fixture.onboarding()
        assertEquals(OnboardingOutcome.Pending, repo.submit(listOf(starterId)))
        assertEquals(OnboardingOutcome.Completed, repo.submit(listOf(starterId)))
        assertEquals(1, fixture.outbox.commands.size)
        assertEquals(2, fixture.api.onboardingCalls.size)
        assertEquals(fixture.api.onboardingCalls[0], fixture.api.onboardingCalls[1])
        assertEquals(
            "{\"adventure_preference\":\"BALANCED\",\"motivations\":[],\"practical_opt_in\":false,\"preferred_effort\":\"15_20_MIN\",\"starter_interest_entity_ids\":[\"$starterId\"],\"support_style\":\"SMALL_HINT\"}",
            fixture.api.onboardingCalls[0].second,
        )
    }

    @Test fun onboardingAuthenticationLossKeepsExactCommandForSameOwnerReauth() = runBlocking {
        val fixture = Fixture(ownerA)
        val auth = FakeAuth()
        fixture.api.onboardingResults += ApiResult.Failure(TransportError.Authentication())
        fixture.api.onboardingResults += ok(OnboardingResultDto(preferences(), "2026-10-01T00:00:00Z"))
        assertEquals(OnboardingOutcome.Pending, fixture.onboarding().submit(emptyList()))
        val original = fixture.outbox.commands.values.single()
        assertEquals(CommandState.AMBIGUOUS.name, original.state)
        auth.state.value = AuthState.SignedOut
        fixture.owners.switchTo(null)
        assertEquals(null, fixture.owners.owner.value)
        assertEquals(AuthState.SignedOut, auth.state.value)
        auth.state.value = AuthState.TokenAvailable(SessionIdentity("external-subject"))
        assertTrue(SessionRepository(auth, fixture.api, fixture.owners).bootstrap() is SessionOutcome.Ready)
        assertEquals(OnboardingOutcome.Completed, fixture.onboarding().resume())
        assertEquals(1, fixture.outbox.commands.size)
        assertEquals(fixture.api.onboardingCalls[0], fixture.api.onboardingCalls[1])
        assertEquals(original.idempotencyKey, fixture.outbox.commands.values.single().idempotencyKey)
        assertArrayEquals(original.canonicalPayload, fixture.outbox.commands.values.single().canonicalPayload)
    }

    @Test fun interruptedOnboardingCommandIsInvisibleToAnotherOwnerAndAvailableOnReturn() = runBlocking {
        val fixture = Fixture(ownerA)
        val auth = FakeAuth()
        fixture.api.onboardingResults += ApiResult.Failure(TransportError.Authentication())
        fixture.api.onboardingResults += ok(OnboardingResultDto(preferences(), "2026-10-01T00:00:00Z"))
        assertEquals(OnboardingOutcome.Pending, fixture.onboarding().submit(emptyList()))
        val original = fixture.outbox.commands.values.single()
        auth.state.value = AuthState.SignedOut
        fixture.owners.switchTo(null)
        auth.state.value = AuthState.TokenAvailable(SessionIdentity("other-external-subject"))
        fixture.api.profileValue = profile(ownerB)
        assertTrue(SessionRepository(auth, fixture.api, fixture.owners).bootstrap() is SessionOutcome.Ready)
        assertEquals(emptyList<CommandEntity>(), fixture.outbox.unresolved(ownerB))
        assertEquals(null, fixture.outbox.get(ownerB, original.id))
        assertEquals(null, fixture.onboarding().resume())
        assertEquals(1, fixture.api.onboardingCalls.size)
        assertEquals(original, fixture.outbox.commands.values.single())
        fixture.owners.switchTo(null)
        fixture.api.profileValue = profile(ownerA)
        assertTrue(SessionRepository(auth, fixture.api, fixture.owners).bootstrap() is SessionOutcome.Ready)
        assertEquals(OnboardingOutcome.Completed, fixture.onboarding().resume())
        assertEquals(fixture.api.onboardingCalls[0], fixture.api.onboardingCalls[1])
    }

    @Test fun expiredOnboardingReconcilesWithMeWithoutPost() = runBlocking {
        val fixture = Fixture(ownerA, now = ReplayWindow.SAFE_WINDOW_MS + 1)
        fixture.outbox.enqueue(command("api/v1/me/onboarding/complete", ownerA, 0))
        fixture.api.profileValue = profile(ownerA, complete = true)
        assertEquals(OnboardingOutcome.Reconciled, fixture.onboarding().resume())
        assertEquals(0, fixture.api.onboardingCalls.size)
        assertEquals(CommandState.RESOLVED.name, fixture.outbox.commands.values.single().state)
    }

    @Test fun invalidStarterRefreshKeepsOnlyCurrentSelectionForExplicitResubmit() = runBlocking {
        val fixture = Fixture(ownerA)
        val valid = "00000000-0000-0000-0000-000000000005"
        val stale = "00000000-0000-0000-0000-000000000006"
        fixture.api.starterItems = listOf(StarterInterestDto(valid, "AREA", 1, "Astronomy", "Sky"))
        fixture.api.onboardingResults += ApiResult.Failure(TransportError.Problem(422, ProblemDetails(code = "INVALID_STARTER_INTEREST")))
        assertEquals(OnboardingOutcome.InvalidStarters(listOf(valid)), fixture.onboarding().submit(listOf(valid, stale)))
        assertEquals(listOf(valid), fixture.store.read(ownerA).selectedStarterIds)
        assertEquals(1, fixture.api.onboardingCalls.size)
    }

    @Test fun alreadyCompletedOnboardingReconcilesThroughMe() = runBlocking {
        val fixture = Fixture(ownerA)
        fixture.api.profileValue = profile(ownerA, complete = true)
        fixture.api.onboardingResults += ApiResult.Failure(TransportError.Problem(409, ProblemDetails(code = "ONBOARDING_ALREADY_COMPLETED")))
        assertEquals(OnboardingOutcome.Reconciled, fixture.onboarding().submit(emptyList()))
        assertEquals(1, fixture.api.profileCalls)
        assertEquals(CommandState.RESOLVED.name, fixture.outbox.commands.values.single().state)
    }

    @Test fun recommendationPresentationCommitsBeforeAcknowledgmentAndNoResultIsSuccess() = runBlocking {
        val fixture = Fixture(ownerA)
        fixture.api.recommendationResults += ok(RecommendationResult.Found(recommendation()))
        fixture.api.recommendationResults += ok(RecommendationResult.NoResult)
        fixture.store.beforePresentation = { assertEquals(CommandState.IN_FLIGHT.name, fixture.outbox.commands.values.last().state) }
        assertEquals(RecommendationOutcome.Found(recId), fixture.recommendations().generate("EXPLORE"))
        assertEquals(recId, fixture.store.read(ownerA).presentation?.id)
        assertEquals(RecommendationOutcome.NoResult, fixture.recommendations().generate("SURPRISE"))
        assertTrue(fixture.store.read(ownerA).noResult)
        assertEquals(2, fixture.outbox.commands.size)
    }

    @Test fun recommendationAuthenticationLossReplaysSameGenerationAfterReauth() = runBlocking {
        val fixture = Fixture(ownerA)
        val auth = FakeAuth()
        fixture.api.recommendationResults += ApiResult.Failure(TransportError.Authentication())
        fixture.api.recommendationResults += ok(RecommendationResult.NoResult)
        assertEquals(RecommendationOutcome.Pending, fixture.recommendations().generate("EXPLORE"))
        val original = fixture.outbox.commands.values.single()
        assertEquals(CommandState.AMBIGUOUS.name, original.state)
        auth.state.value = AuthState.SignedOut
        fixture.owners.switchTo(null)
        auth.state.value = AuthState.TokenAvailable(SessionIdentity("external-subject"))
        fixture.api.profileValue = profile(ownerA, complete = true)
        assertTrue(SessionRepository(auth, fixture.api, fixture.owners).bootstrap() is SessionOutcome.Ready)
        assertEquals(RecommendationOutcome.NoResult, fixture.recommendations().resumeGeneration())
        assertEquals(1, fixture.outbox.commands.size)
        assertEquals(fixture.api.recommendationCalls[0], fixture.api.recommendationCalls[1])
        assertEquals(original.idempotencyKey, fixture.outbox.commands.values.single().idempotencyKey)
        assertArrayEquals(original.canonicalPayload, fixture.outbox.commands.values.single().canonicalPayload)
    }

    @Test fun decisionAuthenticationLossReplaysSameAcceptAfterReauth() = runBlocking {
        val fixture = Fixture(ownerA)
        val auth = FakeAuth()
        fixture.api.decisionResults += ApiResult.Failure(TransportError.Authentication())
        fixture.api.decisionResults += ok(RecommendationDecisionResult.Accepted(accepted()))
        assertEquals(RecommendationOutcome.Pending, fixture.recommendations().decide(recId, "ACCEPT"))
        val original = fixture.outbox.commands.values.single()
        assertEquals(CommandState.AMBIGUOUS.name, original.state)
        auth.state.value = AuthState.SignedOut
        fixture.owners.switchTo(null)
        auth.state.value = AuthState.TokenAvailable(SessionIdentity("external-subject"))
        fixture.api.profileValue = profile(ownerA, complete = true)
        assertTrue(SessionRepository(auth, fixture.api, fixture.owners).bootstrap() is SessionOutcome.Ready)
        assertEquals(RecommendationOutcome.Accepted(recId, explorationId), fixture.recommendations().resumeDecision())
        assertEquals(1, fixture.outbox.commands.size)
        assertEquals(fixture.api.decisionCalls[0], fixture.api.decisionCalls[1])
        assertEquals(original.idempotencyKey, fixture.outbox.commands.values.single().idempotencyKey)
        assertArrayEquals(original.canonicalPayload, fixture.outbox.commands.values.single().canonicalPayload)
    }

    @Test fun commandInProgressRetriesSameRecommendationCommandWithBoundedBackoff() = runBlocking {
        val fixture = Fixture(ownerA)
        fixture.api.recommendationResults += ApiResult.Failure(TransportError.Problem(409, ProblemDetails(code = "COMMAND_IN_PROGRESS")))
        fixture.api.recommendationResults += ok(RecommendationResult.Found(recommendation()))
        assertEquals(RecommendationOutcome.Found(recId), fixture.recommendations().generate("EXPLORE"))
        assertEquals(2, fixture.api.recommendationCalls.size)
        assertEquals(fixture.api.recommendationCalls[0], fixture.api.recommendationCalls[1])
        assertEquals(1, fixture.outbox.commands.size)
    }

    @Test fun acceptAndSkipKeepDistinctResponsesAndPersistHandoff() = runBlocking {
        val fixture = Fixture(ownerA)
        fixture.store.savePresentation(ownerA, recommendation())
        fixture.api.decisionResults += ok(RecommendationDecisionResult.Accepted(accepted()))
        assertEquals(RecommendationOutcome.Accepted(recId, explorationId), fixture.recommendations().decide(recId, "ACCEPT"))
        assertEquals(explorationId, fixture.store.read(ownerA).acceptedExplorationId)
        assertEquals(null, fixture.store.read(ownerA).presentation)
        val secondId = "00000000-0000-0000-0000-000000000006"
        fixture.store.savePresentation(ownerA, recommendation().copy(id = secondId))
        fixture.api.decisionResults += ok(RecommendationDecisionResult.Skipped(SkippedRecommendationDto(secondId, "SKIP")))
        assertEquals(RecommendationOutcome.Skipped(secondId), fixture.recommendations().decide(secondId, "SKIP"))
        assertEquals(secondId, fixture.store.read(ownerA).skippedRecommendationId)
        assertEquals(null, fixture.store.read(ownerA).presentation)
    }

    @Test fun expiredAcceptFindsExactRecommendationAcrossBoundedPages() = runBlocking {
        val fixture = Fixture(ownerA, now = ReplayWindow.SAFE_WINDOW_MS + 1)
        fixture.outbox.enqueue(command("api/v1/recommendations/$recId/decision", ownerA, 0, "{\"decision\":\"ACCEPT\",\"reason\":null}"))
        fixture.api.pages += ok(ExplorationPageDto(listOf(ExplorationListItemDto("other", "different", "ACTIVE")), "cursor-2"))
        fixture.api.pages += ok(ExplorationPageDto(listOf(ExplorationListItemDto(explorationId, recId, "ACTIVE")), null))
        assertEquals(RecommendationOutcome.Accepted(recId, explorationId), fixture.recommendations().resumeDecision())
        assertEquals(2, fixture.api.explorationCalls)
        assertEquals(0, fixture.api.decisionCalls.size)
        assertEquals(explorationId, fixture.store.read(ownerA).acceptedExplorationId)
    }

    @Test fun expiredSkipRemainsUnresolvedAndOwnerCannotReadOtherDraft() = runBlocking {
        val fixture = Fixture(ownerA, now = ReplayWindow.SAFE_WINDOW_MS + 1)
        fixture.outbox.enqueue(command("api/v1/recommendations/$recId/decision", ownerA, 0, "{\"decision\":\"SKIP\",\"reason\":null}"))
        fixture.store.saveDraft(ownerA, listOf(recId))
        assertEquals(RecommendationOutcome.Unresolved, fixture.recommendations().resumeDecision())
        assertEquals(0, fixture.api.explorationCalls)
        fixture.owners.switchTo(ownerB)
        assertEquals(emptyList<String>(), fixture.store.read(ownerB).selectedStarterIds)
        try {
            fixture.store.read(ownerA)
            fail("Cross-owner read succeeded")
        } catch (_: IllegalStateException) { }
    }

    @Test fun acceptReconciliationStopsAtFivePagesWithoutInferringFromOtherFields() = runBlocking {
        val fixture = Fixture(ownerA, now = ReplayWindow.SAFE_WINDOW_MS + 1)
        fixture.outbox.enqueue(command("api/v1/recommendations/$recId/decision", ownerA, 0, "{\"decision\":\"ACCEPT\",\"reason\":null}"))
        repeat(5) { index ->
            fixture.api.pages += ok(ExplorationPageDto(listOf(ExplorationListItemDto("exploration-$index", "different", "ACTIVE")), "cursor-${index + 1}"))
        }
        assertEquals(RecommendationOutcome.Unresolved, fixture.recommendations().resumeDecision())
        assertEquals(5, fixture.api.explorationCalls)
        assertEquals(null, fixture.store.read(ownerA).acceptedExplorationId)
    }

    @Test fun alreadyDecidedSkipDoesNotPretendDecisionIsKnown() = runBlocking {
        val fixture = Fixture(ownerA)
        fixture.api.decisionResults += ApiResult.Failure(TransportError.Problem(409, ProblemDetails(code = "RECOMMENDATION_ALREADY_DECIDED")))
        assertEquals(RecommendationOutcome.Unresolved, fixture.recommendations().decide(recId, "SKIP"))
        assertEquals(CommandState.AMBIGUOUS.name, fixture.outbox.commands.values.single().state)
        assertEquals(null, fixture.store.read(ownerA).skippedRecommendationId)
    }

    private fun profile(id: String, complete: Boolean = false) = ProfileDto(id, if (complete) "2026-10-01T00:00:00Z" else null, null, 0)
    private fun preferences() = PreferencesDto("BALANCED", "15_20_MIN", "SMALL_HINT", false, 1)
    private fun recommendation() = RecommendationDto(recId, "ENTITY", RecommendationEntityDto(recId, "Starter"), null, "EXPLORE", "NEAR", null, null, "2026-10-01T00:00:00Z")
    private fun accepted() = AcceptedExplorationDto(explorationId, RecommendationEntityDto(recId, "Starter"), 1, null, "DIRECT_INTEREST", "ACTIVE", "2026-10-01T00:00:00Z", null, null, null, 1)
    private fun command(route: String, owner: String, created: Long, payload: String = "{}") =
        CommandEntity("cmd-1", owner, "POST", route, payload.toByteArray(), "key-1", created, CommandState.AMBIGUOUS.name)
    private fun <T> ok(value: T) = ApiResult.Success(value, 200)

    private inner class Fixture(owner: String, private val now: Long = 1000) {
        val owners = OwnerSession().apply { switchTo(owner) }
        val api = FakeApi(owner)
        val outbox = MemoryOutbox()
        val store = MemoryJourneyStore(owners)
        val dispatcher = CommandDispatcher(outbox, owners)
        fun onboarding() = OnboardingRepository(api, owners, store, outbox, dispatcher) { now }
        fun recommendations() = RecommendationRepository(api, owners, store, outbox, dispatcher) { now }
    }

    private class FakeAuth : AuthGateway {
        override val state = MutableStateFlow<AuthState>(AuthState.TokenAvailable(SessionIdentity("external-subject")))
        var refreshes = 0
        override suspend fun restoreSession() = state.value
        override suspend fun refreshSession(expectedAccessToken: String?): Boolean { refreshes++; return true }
        override suspend fun signOut() { state.value = AuthState.SignedOut }
        override suspend fun accessToken() = "token"
        override suspend fun requestEmailCode(email: String) = EmailCodeResult.Sent
        override suspend fun verifyEmailCode(email: String, code: String) = EmailCodeResult.Authenticated
    }

    private class FakeApi(owner: String) : EmbyrApi {
        var profileValue = ProfileDto(owner, null, null, 0)
        var starterItems: List<StarterInterestDto> = emptyList()
        var bootstrapCalls = 0
        var profileCalls = 0
        var explorationCalls = 0
        val bootstrapResults = ArrayDeque<ApiResult<ProfileDto>>()
        val onboardingResults = ArrayDeque<ApiResult<OnboardingResultDto>>()
        val recommendationResults = ArrayDeque<ApiResult<RecommendationResult>>()
        val decisionResults = ArrayDeque<ApiResult<RecommendationDecisionResult>>()
        val pages = ArrayDeque<ApiResult<ExplorationPageDto>>()
        val onboardingCalls = mutableListOf<Pair<String, String>>()
        val decisionCalls = mutableListOf<Pair<String, String>>()
        val recommendationCalls = mutableListOf<Pair<String, String>>()
        override suspend fun bootstrap(): ApiResult<ProfileDto> { bootstrapCalls++; return bootstrapResults.removeFirstOrNull() ?: ApiResult.Success(profileValue, 200) }
        override suspend fun profile(): ApiResult<ProfileDto> { profileCalls++; return ApiResult.Success(profileValue, 200) }
        override suspend fun starterInterests() = ApiResult.Success(StarterInterestPageDto(starterItems), 200)
        override suspend fun completeOnboarding(canonicalPayload: ByteArray, idempotencyKey: String): ApiResult<OnboardingResultDto> {
            onboardingCalls += idempotencyKey to canonicalPayload.decodeToString()
            return onboardingResults.removeFirst()
        }
        override suspend fun explorations(limit: Int, cursor: String?): ApiResult<ExplorationPageDto> {
            explorationCalls++
            return pages.removeFirstOrNull() ?: ApiResult.Success(ExplorationPageDto(emptyList(), null), 200)
        }
        override suspend fun decideRecommendation(recommendationId: String, canonicalPayload: ByteArray, idempotencyKey: String): ApiResult<RecommendationDecisionResult> {
            decisionCalls += idempotencyKey to canonicalPayload.decodeToString()
            return decisionResults.removeFirst()
        }
        override suspend fun world(): ApiResult<WorldSnapshotDto> = error("Unused")
        override suspend fun memorySummary(): ApiResult<app.embyr.core.model.MemorySummaryDto> = error("Unused")
        override suspend fun updateInterest(entityId: String, canonicalPayload: ByteArray): ApiResult<app.embyr.core.model.InterestResultDto> = error("Unused")
        override suspend fun worldChanges(afterRevision: Long, limit: Int): ApiResult<WorldDeltaPageDto> = error("Unused")
        override suspend fun nextRecommendation(canonicalPayload: ByteArray, idempotencyKey: String): ApiResult<RecommendationResult> {
            recommendationCalls += idempotencyKey to canonicalPayload.decodeToString()
            return recommendationResults.removeFirst()
        }
        override suspend fun submitAnswer(sessionId: String, canonicalPayload: ByteArray, idempotencyKey: String): ApiResult<AnswerAcknowledgmentDto> = error("Unused")
    }

    private class MemoryOutbox : CommandOutbox {
        val commands = linkedMapOf<String, CommandEntity>()
        override suspend fun enqueue(command: CommandEntity) { commands[command.id] = command }
        override suspend fun get(ownerId: String, id: String) = commands[id]?.takeIf { it.ownerId == ownerId }
        override suspend fun unresolved(ownerId: String) = commands.values.filter { it.ownerId == ownerId && it.state in setOf("PENDING", "IN_FLIGHT", "AMBIGUOUS", "EXPIRED") }
        override suspend fun mark(ownerId: String, id: String, state: CommandState, resultReference: String?) {
            val old = requireNotNull(get(ownerId, id)); commands[id] = old.copy(state = state.name, knownResultReference = resultReference)
        }
        override suspend fun markAttempt(ownerId: String, id: String, nowEpochMs: Long) {
            val old = requireNotNull(get(ownerId, id)); commands[id] = old.copy(state = CommandState.IN_FLIGHT.name, attempts = old.attempts + 1)
        }
    }

    private class MemoryJourneyStore(private val owners: OwnerSession) : JourneyStore {
        private val rows = mutableMapOf<String, JourneySnapshot>()
        var beforePresentation: (() -> Unit)? = null
        override suspend fun read(ownerId: String): JourneySnapshot { check(owners.requireOwner() == ownerId); return rows[ownerId] ?: JourneySnapshot() }
        override suspend fun saveDraft(ownerId: String, ids: List<String>) { rows[ownerId] = read(ownerId).copy(selectedStarterIds = ids) }
        override suspend fun savePresentation(ownerId: String, result: RecommendationDto?) {
            beforePresentation?.invoke(); rows[ownerId] = read(ownerId).copy(presentation = result, noResult = result == null)
        }
        override suspend fun saveAcceptance(ownerId: String, recommendationId: String, explorationId: String) {
            rows[ownerId] = read(ownerId).copy(presentation = null, noResult = false, acceptedRecommendationId = recommendationId, acceptedExplorationId = explorationId)
        }
        override suspend fun saveSkip(ownerId: String, recommendationId: String) { rows[ownerId] = read(ownerId).copy(presentation = null, noResult = false, skippedRecommendationId = recommendationId) }
    }
}
