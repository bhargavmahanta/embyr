package app.embyr

import app.embyr.auth.OwnerSession
import app.embyr.core.model.*
import app.embyr.core.network.*
import app.embyr.core.storage.*
import app.embyr.feature.exploration.ExplorationRepository
import app.embyr.feature.exploration.base
import app.embyr.feature.exploration.ExplorationViewModel
import app.embyr.feature.exploration.ExplorationUiState
import app.embyr.feature.exploration.withAssessmentStart
import app.embyr.feature.assessment.AssessmentUiState
import app.embyr.feature.assessment.AssessmentViewModel
import kotlinx.coroutines.test.*
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import app.embyr.feature.assessment.AssessmentRepository
import app.embyr.feature.assessment.AssessmentPoller
import app.embyr.feature.assessment.PollEnd
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import kotlinx.serialization.json.Json
import java.io.File

class LearningFlowTest {
    private val json = Json { ignoreUnknownKeys = true }
    private fun example(key: String): String {
        val root = generateSequence(File(requireNotNull(System.getProperty("user.dir"))).canonicalFile) { it.parentFile }
            .first { File(it, "docs/api/fixtures/learning-lifecycle-v1.json").exists() }
        val fixture = json.parseToJsonElement(File(root, "docs/api/fixtures/learning-lifecycle-v1.json").readText()) as kotlinx.serialization.json.JsonObject
        return fixture.getValue(key).toString()
    }
    private fun detail() = json.decodeFromString(ExplorationDetailDto.serializer(), example("exploration"))
    private fun session() = json.decodeFromString(AssessmentSessionDto.serializer(), example("session"))

    @Test fun reflectedDraftSurvivesConflictAndNeverBlindlyRetriesPatch() = runBlocking {
        val f = Fixture(); val base = detail(); val original = base.copy(status = "ACTIVE", reflection = ReflectionDto("reflection",base.id,base.entityId,"Original",1,"now","now"))
        f.api.detail = original
        val repo = f.exploration()
        repo.open(original.id)
        repo.saveDraft(original.id, "My retained draft")
        f.api.editResult = ApiResult.Failure(TransportError.Problem(409, ProblemDetails(code = "VERSION_CONFLICT")))
        assertTrue(repo.saveReflection(original.id) is LearningOutcome.Conflict)
        assertEquals("My retained draft", f.store.exploration("a", original.id).draft)
        assertEquals(1, f.api.edits)
        repo.open(original.id)
        assertEquals(1, f.api.edits) // GET/refetch cannot resubmit a versioned edit.
    }

    @Test fun lostDeliveryAckReusesExactCommandAndReceiptPrecedesAck() = runBlocking {
        val f = Fixture(); val original = detail().copy(delivery = null, status = "ACTIVE")
        f.api.detail = original; val repo = f.exploration(); repo.open(original.id)
        f.api.deliveryResult = ApiResult.Failure(TransportError.AmbiguousTimeout)
        assertEquals(LearningOutcome.Pending, repo.deliver(original.id))
        val first = f.outbox.rows.values.single()
        f.api.deliveryResult = ApiResult.Success(requireNotNull(detail().delivery), 200)
        assertTrue(f.exploration().deliver(original.id) is LearningOutcome.Done)
        assertEquals(1, f.outbox.rows.size)
        assertEquals(f.api.deliveries[0], f.api.deliveries[1])
        assertEquals(CommandState.ACKNOWLEDGED.name, f.outbox.rows.getValue(first.id).state)
        assertNotNull(f.store.receipts["a" to first.id])
        assertNotNull(f.store.exploration("a", original.id).detail()?.delivery)
    }

    @Test fun expiredUnknownReturnDoesNotIssueAnotherMutation() = runBlocking {
        val f = Fixture(); val original = detail().copy(status = "PAUSED")
        f.api.detail = original; val repo = f.exploration(); repo.open(original.id)
        f.api.actionResult = ApiResult.Failure(TransportError.AmbiguousTimeout)
        assertEquals(LearningOutcome.Pending, repo.action(original.id, "RETURN"))
        f.clock += ReplayWindow.SAFE_WINDOW_MS
        assertEquals(LearningOutcome.Unknown, repo.action(original.id, "RETURN"))
        assertEquals(1, f.api.actions.size)
        assertTrue(f.api.actions.single().contains("\"action\":\"RETURN\""))
        assertTrue(f.api.actions.single().contains("\"base_version\":"))
        assertEquals("PAUSED", f.store.exploration("a", original.id).detail()?.status)
    }

    @Test fun assessment202ReceiptCannotOverrideCurrentSucceededRead() = runBlocking {
        val f = Fixture(); val s = session().copy(status = "ACTIVE", responseId = null, evaluation = null, evaluationStatus = null)
        f.api.session = s
        f.store.putAssessment(AssessmentStateEntity("a", s.id, s.explorationId, json.encodeToString(AssessmentSessionDto.serializer(), s)))
        f.api.current = response(s.id, "SUCCEEDED", "run-1", false)
        assertTrue(f.assessment().answer(s.id, s.interaction.options.first().id) is LearningOutcome.Done)
        val row = requireNotNull(f.store.assessment("a", s.id))
        assertEquals("response", row.responseId)
        assertEquals("SUCCEEDED", row.response()?.evaluationStatus)
        assertEquals(1, f.api.answerCalls)
        f.assessment().answer(s.id, s.interaction.options.first().id)
        assertEquals(1, f.api.answerCalls)
    }

    @Test fun eligibleRetryUsesNewRunAndNeverResubmitsAnswer() = runBlocking {
        val f = Fixture(); val s = session(); f.api.session = s
        val failed = response(s.id, "FAILED", "old-run", true)
        f.store.putAssessment(AssessmentStateEntity("a", s.id, s.explorationId, json.encodeToString(AssessmentSessionDto.serializer(), s), json.encodeToString(AssessmentResponseDto.serializer(), failed), "response", "old-run", "option"))
        f.api.current = response(s.id, "PENDING", "new-run", false)
        assertTrue(f.assessment().retry(s.id) is LearningOutcome.Done)
        assertEquals(0, f.api.answerCalls)
        assertEquals(1, f.api.retries)
        assertEquals("new-run", f.store.assessment("a", s.id)?.knownRunId)
        f.assessment().retry(s.id)
        assertEquals(1, f.api.retries)
    }

    @Test fun noneligibleFailureRejectsRetryEvenWhileSessionWaits() = runBlocking {
        val f = Fixture(); val s = session().copy(status = "WAITING_FOR_EVALUATION"); f.api.session = s
        val failed = response(s.id, "FAILED", "run", false)
        f.store.putAssessment(AssessmentStateEntity("a", s.id, s.explorationId, json.encodeToString(AssessmentSessionDto.serializer(), s), json.encodeToString(AssessmentResponseDto.serializer(), failed), "response", "run"))
        assertTrue(f.assessment().retry(s.id) is LearningOutcome.Invalid)
        assertEquals(0, f.api.retries)
    }

    @Test fun pollingIsFiniteAndStopsOnFailureOrOffline() = runBlocking {
        var reads = 0; var time = 0L; val delays = mutableListOf<Long>()
        val poller = AssessmentPoller(now = { time }, wait = { delays += it; time += it })
        assertEquals(PollEnd.BUDGET, poller.poll({ true }) { reads++; false })
        assertEquals(8, reads)
        assertEquals(listOf(1000L, 2000L, 4000L, 8000L, 8000L, 8000L, 8000L), delays)
        reads = 0
        assertEquals(PollEnd.OFFLINE, poller.poll({ false }) { reads++; false })
        assertEquals(0, reads)
        assertEquals(PollEnd.TERMINAL, poller.poll({ true }) { reads++; true })
        assertEquals(1, reads)
    }

    @Test fun accountSwitchCannotReadOrReplayOtherOwnersCommand() = runBlocking {
        val f = Fixture(); val d = detail().copy(delivery = null); f.api.detail = d
        f.exploration().open(d.id)
        f.api.deliveryResult = ApiResult.Failure(TransportError.Authentication())
        f.exploration().deliver(d.id)
        f.owners.switchTo("b")
        assertNull(f.store.exploration("b", d.id).detail())
        assertTrue(f.outbox.unresolved("b").isEmpty())
        f.owners.switchTo("a")
        f.api.deliveryResult = ApiResult.Success(requireNotNull(detail().delivery), 200)
        assertTrue(f.exploration().deliver(d.id) is LearningOutcome.Done)
        assertEquals(1, f.outbox.rows.size)
    }

    @Test fun lateOldRunCannotReplaceNewRetryProgress() = runBlocking {
        val f = Fixture(); val s = session(); f.api.session = s
        val newer = response(s.id,"PENDING","new-run",false)
        f.store.putAssessment(AssessmentStateEntity("a",s.id,s.explorationId,json.encodeToString(AssessmentSessionDto.serializer(),s),responseId = "response",knownRunId = "new-run"))
        f.api.current = response(s.id,"SUCCEEDED","old-run",false)
        assertEquals(LearningOutcome.Pending,f.assessment().refresh(s.id))
        assertNull(f.store.assessment("a",s.id)?.response())
        assertEquals("new-run",f.store.assessment("a",s.id)?.knownRunId)
        f.api.current = newer
        assertEquals(LearningOutcome.Done,f.assessment().refresh(s.id))
        assertEquals("new-run",f.store.assessment("a",s.id)?.response()?.evaluationRunId)
    }

    @Test fun unavailableReviewedContentKeepsAcceptedParentAndDraft() = runBlocking {
        val f = Fixture(); val d = detail().copy(delivery = null); f.api.detail = d
        val repo = f.exploration(); repo.open(d.id); repo.saveDraft(d.id,"Keep my words")
        f.api.deliveryResult = ApiResult.Failure(TransportError.Problem(503,ProblemDetails(code = "EXPLORATION_CONTENT_UNAVAILABLE")))
        assertTrue(repo.deliver(d.id) is LearningOutcome.Failed)
        val saved = f.store.exploration("a",d.id)
        assertEquals(d.id,saved.detail()?.id); assertEquals("Keep my words",saved.draft)
        assertNull(saved.detail()?.delivery)
    }

    @Test fun completionUsesObservedVersionAndNeverSubmitsAnAssessment() = runBlocking {
        val f = Fixture(); val d = detail().copy(status = "ACTIVE",version = 7); f.api.detail = d
        val repo = f.exploration(); repo.open(d.id)
        f.api.completionResult = ApiResult.Success(d.base().copy(status = "COMPLETED",version = 8,completedAt = "now"),200)
        assertEquals(LearningOutcome.Done,repo.complete(d.id))
        assertEquals(listOf("{\"base_version\":7}"),f.api.completions)
        assertEquals("COMPLETED",f.store.exploration("a",d.id).detail()?.status)
        assertEquals(0,f.api.answerCalls)
        repo.complete(d.id); assertEquals(1,f.api.completions.size)
    }

    @Test fun cancelledPollCannotContinueOrStartAnotherRead() = runBlocking {
        var reads = 0
        val entered = CompletableDeferred<Unit>()
        val job = launch { AssessmentPoller().poll({ true }) { reads++; entered.complete(Unit); awaitCancellation() } }
        entered.await(); job.cancelAndJoin()
        assertEquals(1,reads)
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    @Test fun restoredDetailOpenIsNotDroppedBySuspendedInitialPage() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val f = Fixture(); val d = detail(); f.api.detail = d
            f.store.putActivity(ActivityStateEntity("a",d.id,"session"))
            val waiting = CompletableDeferred<Unit>(); f.api.pageWait = waiting
            val vm = ExplorationViewModel(f.owners,f.store,f.exploration())
            runCurrent()
            assertEquals(d.id,vm.ui.value.restoreExploration)
            vm.open(d.id); waiting.complete(Unit); runCurrent()
            assertEquals(d.id,vm.ui.value.selected)
            assertEquals(d.id,vm.ui.value.detail?.id)
            assertEquals("session",f.store.activity("a").sessionId)
            vm.refresh(); runCurrent(); assertNotNull(vm.ui.value.detail)
            f.owners.switchTo(null); runCurrent()
            assertNull(vm.ui.value.detail)
        } finally { Dispatchers.resetMain() }
    }

    @Test fun expiredStartUsesOriginalConfidenceAndNeverNewPost() = runBlocking {
        val f = Fixture(); val d = detail(); val s = session().copy(explorationId = d.id,confidenceBefore = "MAIN_IDEA")
        f.api.detail = d.copy(assessmentSession = AssessmentReferenceDto(s.id,s.status)); f.api.session = s
        f.api.startResult = ApiResult.Failure(TransportError.AmbiguousTimeout)
        assertEquals(LearningOutcome.Pending,f.assessment().start(d.id,"FUZZY"))
        f.clock += ReplayWindow.SAFE_WINDOW_MS
        assertEquals(LearningOutcome.Unknown,f.assessment().start(d.id,"MAIN_IDEA"))
        assertEquals(1,f.api.starts.size)
        f.api.session = s.copy(confidenceBefore = "FUZZY")
        assertEquals(LearningOutcome.Done,f.assessment().start(d.id,"MAIN_IDEA"))
        assertEquals(1,f.api.starts.size)
    }

    @Test fun preparedDeliveryRefreshesVersionBeforeNextLifecycle() = runBlocking {
        val f = Fixture(); val d = detail().copy(delivery = null,version = 4,status = "ACTIVE"); f.api.detail = d
        val repo = f.exploration(); repo.open(d.id)
        val work = requireNotNull(detail().delivery)
        f.api.deliveryResult = ApiResult.Success(work,200)
        f.api.afterDelivery = { f.api.detail = d.copy(delivery = work,version = 5) }
        assertEquals(LearningOutcome.Done,repo.deliver(d.id))
        assertEquals(5L,repo.read(d.id).detail()?.version)
        f.api.actionResult = ApiResult.Success(d.base().copy(version = 6,status = "PAUSED"),200)
        assertEquals(LearningOutcome.Done,repo.action(d.id,"PAUSE"))
        assertEquals("{\"action\":\"PAUSE\",\"base_version\":5}",f.api.actions.single())
    }

    @Test fun initiatingDetailShowsTargetedStartBusyAndFailure() {
        val detail = ExplorationUiState(owner = "a",selected = "exploration")
        val start = AssessmentUiState(owner = "a",startTarget = "exploration",busy = true,message = "Saved request pending")
        assertTrue(detail.withAssessmentStart(start).busy)
        assertEquals("Saved request pending",detail.withAssessmentStart(start).message)
        assertFalse(detail.withAssessmentStart(start.copy(startTarget = "other")).busy)
        assertFalse(detail.withAssessmentStart(start.copy(owner = "b")).busy)
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    @Test fun currentFeedbackKeepsOriginalLostAnswerRecoveryVisible() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val f = Fixture(); val s = session().copy(status = "ACTIVE",responseId = null)
            f.api.session = s
            f.store.putAssessment(AssessmentStateEntity("a",s.id,s.explorationId,json.encodeToString(AssessmentSessionDto.serializer(),s)))
            f.api.answerResult = ApiResult.Failure(TransportError.AmbiguousTimeout)
            assertEquals(LearningOutcome.Pending,f.assessment().answer(s.id,s.interaction.options.first().id))
            val original = f.outbox.rows.values.single()
            f.api.session = s.copy(responseId = "response",status = "COMPLETED")
            f.api.current = response(s.id,"SUCCEEDED","run",false)
            val vm = AssessmentViewModel(f.owners,f.assessment(),{ true })
            runCurrent(); vm.open(s.id); runCurrent()
            assertEquals("SUCCEEDED",vm.ui.value.response?.evaluationStatus)
            assertTrue(vm.ui.value.unconfirmedRequests.contains("answer"))
            f.api.answerResult = ApiResult.Success(AnswerAcknowledgmentDto("response","PENDING","WAITING_FOR_EVALUATION",null),202)
            vm.recheck(); runCurrent()
            withContext(Dispatchers.Default) { withTimeout(3000) { vm.ui.first { !it.busy && it.unconfirmedRequests.isEmpty() } } }
            assertEquals(f.api.answerRequests[0],f.api.answerRequests[1])
            assertEquals(CommandState.ACKNOWLEDGED.name,f.outbox.rows.getValue(original.id).state)
            assertTrue(vm.ui.value.unconfirmedRequests.isEmpty())
            assertEquals("SUCCEEDED",vm.ui.value.response?.evaluationStatus)
            f.owners.switchTo(null); runCurrent()
        } finally { Dispatchers.resetMain() }
    }

    @Test fun lostRetryAckRecoversSameKeyEvenAfterCurrentSuccess() = runBlocking {
        val f = Fixture(); val s = session(); f.api.session = s
        val failed = response(s.id,"FAILED","old-run",true)
        f.store.putAssessment(AssessmentStateEntity("a",s.id,s.explorationId,json.encodeToString(AssessmentSessionDto.serializer(),s),json.encodeToString(AssessmentResponseDto.serializer(),failed),"response","old-run","option"))
        f.api.retryResult = ApiResult.Failure(TransportError.AmbiguousTimeout)
        assertEquals(LearningOutcome.Pending,f.assessment().retry(s.id))
        f.api.current = response(s.id,"SUCCEEDED","new-run",false)
        f.assessment().open(s.id)
        assertEquals(listOf("retry"),f.assessment().pending(s.id))
        f.api.retryResult = ApiResult.Success(EvaluationRetryDto("response","PENDING","WAITING_FOR_EVALUATION",null,"new-run"),202)
        assertEquals(LearningOutcome.Done,f.assessment().recover(s.id))
        assertEquals(f.api.retryRequests[0],f.api.retryRequests[1])
        assertEquals("SUCCEEDED",f.store.assessment("a",s.id)?.response()?.evaluationStatus)
        assertEquals(0,f.api.answerCalls)
        assertTrue(f.assessment().pending(s.id).isEmpty())
    }

    @Test fun expiredUnknownAnswerKeepsProgressAndUnconfirmedProvenance() = runBlocking {
        val f = Fixture(); val s = session().copy(status = "ACTIVE",responseId = null); f.api.session = s
        f.store.putAssessment(AssessmentStateEntity("a",s.id,s.explorationId,json.encodeToString(AssessmentSessionDto.serializer(),s)))
        f.api.answerResult = ApiResult.Failure(TransportError.AmbiguousTimeout)
        f.assessment().answer(s.id,s.interaction.options.first().id)
        f.api.session = s.copy(responseId = "response",status = "COMPLETED")
        f.api.current = response(s.id,"SUCCEEDED","run",false)
        f.assessment().open(s.id); f.clock += ReplayWindow.SAFE_WINDOW_MS
        assertEquals(LearningOutcome.Unknown,f.assessment().recover(s.id))
        assertEquals(LearningOutcome.Done,f.assessment().refresh(s.id))
        assertEquals("SUCCEEDED",f.store.assessment("a",s.id)?.response()?.evaluationStatus)
        assertEquals(listOf("answer"),f.assessment().pending(s.id))
        assertEquals(1,f.api.answerCalls)
        assertEquals(CommandState.EXPIRED.name,f.outbox.rows.values.single().state)
    }

    @Test fun lostStartRecoversOriginalBytesAndKnownSession() = runBlocking {
        val f = Fixture(); val d = detail(); val s = session().copy(explorationId = d.id,confidenceBefore = "FUZZY")
        f.api.detail = d.copy(assessmentSession = AssessmentReferenceDto(s.id,s.status)); f.api.session = s
        f.api.startResult = ApiResult.Failure(TransportError.AmbiguousTimeout)
        assertEquals(LearningOutcome.Pending,f.assessment().start(d.id,"FUZZY"))
        assertTrue(f.assessment().hasPendingStart(d.id))
        f.api.startResult = ApiResult.Success(s,200)
        assertEquals(LearningOutcome.Done,f.assessment().recoverStart(d.id))
        assertEquals(f.api.starts[0],f.api.starts[1]); assertEquals(1,f.outbox.rows.size)
        assertEquals(s.id,f.assessment().storedSession(d.id))
        assertFalse(f.assessment().hasPendingStart(d.id))
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    @Test fun openingAnotherCheckSupersedesSuspendedPreviousAction() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val f = Fixture(); val waiting = CompletableDeferred<Unit>()
        try {
            val a = session().copy(id = "session-a",status = "ACTIVE",responseId = null)
            val b = a.copy(id = "session-b",explorationId = "exploration-b")
            f.api.session = a; f.api.supportWait = waiting
            val vm = AssessmentViewModel(f.owners,f.assessment(),{ true })
            runCurrent(); vm.open(a.id); runCurrent(); vm.support("SMALL_NUDGE"); runCurrent()
            withContext(Dispatchers.Default) { withTimeout(3000) { f.api.supportEntered.await() } }
            f.api.session = b; vm.open(b.id); runCurrent()
            assertEquals(b.id,vm.ui.value.session?.id)
            waiting.complete(Unit); runCurrent()
            assertEquals(b.id,vm.ui.value.session?.id)
            assertTrue(f.outbox.unresolved("a").any { it.relativeRoute == "api/v1/assessment-sessions/session-a/support-requests" })
        } finally { waiting.complete(Unit); f.owners.switchTo(null); runCurrent(); Dispatchers.resetMain() }
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    @Test fun lateStartDoesNotNavigateOrOverwriteDepartedDestination() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val f = Fixture(); val waiting = CompletableDeferred<Unit>()
        try {
            val d = detail(); val s = session().copy(explorationId = d.id)
            f.api.startWait = waiting; f.api.startResult = ApiResult.Success(s,200)
            val vm = AssessmentViewModel(f.owners,f.assessment(),{ true }); var navigations = 0
            runCurrent(); vm.bindExploration(d.id); runCurrent()
            vm.start(d.id,"FUZZY") { navigations++ }; runCurrent()
            withContext(Dispatchers.Default) { withTimeout(3000) { f.api.startEntered.await() } }
            vm.unbindExploration(d.id); f.store.putActivity(ActivityStateEntity("a","other-exploration"))
            waiting.complete(Unit); runCurrent()
            withContext(Dispatchers.Default) { withTimeout(3000) { vm.ui.first { !it.busy } } }
            assertEquals(0,navigations)
            assertEquals("other-exploration",f.store.activity("a").explorationId)
            assertNotNull(f.store.assessment("a",s.id))
            assertEquals(CommandState.ACKNOWLEDGED.name,f.outbox.rows.values.single().state)
        } finally { waiting.complete(Unit); f.owners.switchTo(null); runCurrent(); Dispatchers.resetMain() }
    }

    private fun response(sessionId: String, status: String, run: String, retry: Boolean) = AssessmentResponseDto("response", sessionId, "WAITING_FOR_EVALUATION", null, run, status, null, null, null, if (status == "FAILED") "PROCESSING_UNAVAILABLE" else null, retry)

    private inner class Fixture {
        val owners = OwnerSession().apply { switchTo("a") }; val store = MemoryLearningStore(owners); val outbox = MemoryLearningOutbox(store); val api = TestLearningApi(); var clock = 1000L
        val commands = LearningCommands(outbox, CommandDispatcher(outbox, owners), owners, store) { clock }
        fun exploration() = ExplorationRepository(api, owners, store, commands)
        fun assessment() = AssessmentRepository(api, api, owners, store, commands)
    }
}

class MemoryLearningStore(private val owners: OwnerSession) : LearningStore {
    private val explorations = mutableMapOf<Pair<String,String>, ExplorationStateEntity>()
    private val assessments = mutableMapOf<Pair<String,String>, AssessmentStateEntity>()
    private val activities = mutableMapOf<String, ActivityStateEntity>()
    val receipts = mutableMapOf<Pair<String,String>, LearningReceiptEntity>()
    override suspend fun exploration(owner: String, id: String): ExplorationStateEntity { check(owners.requireOwner() == owner); return explorations[owner to id] ?: ExplorationStateEntity(owner, id) }
    override suspend fun updateExploration(owner: String, id: String, change: (ExplorationStateEntity) -> ExplorationStateEntity) { explorations[owner to id] = change(exploration(owner,id)) }
    override suspend fun assessment(owner: String, id: String): AssessmentStateEntity? { check(owners.requireOwner() == owner); return assessments[owner to id] }
    override suspend fun assessmentForExploration(owner: String, exploration: String): List<AssessmentStateEntity> { check(owners.requireOwner() == owner); return assessments.values.filter { it.ownerId == owner && it.explorationId == exploration } }
    override suspend fun updateAssessment(owner: String, id: String, change: (AssessmentStateEntity?) -> AssessmentStateEntity) { putAssessment(change(assessment(owner,id))) }
    override suspend fun putAssessment(row: AssessmentStateEntity) { check(owners.requireOwner() == row.ownerId); assessments[row.ownerId to row.sessionId] = row }
    override suspend fun activity(owner: String) = activities[owner] ?: ActivityStateEntity(owner)
    override suspend fun putActivity(row: ActivityStateEntity) { activities[row.ownerId] = row }
    override suspend fun receipt(owner: String, command: String) = receipts[owner to command]
    override suspend fun putReceipt(row: LearningReceiptEntity) { receipts[row.ownerId to row.commandId] = row }
}
class MemoryLearningOutbox(private val store: MemoryLearningStore) : CommandOutbox {
    val rows = linkedMapOf<String, CommandEntity>()
    override suspend fun enqueue(command: CommandEntity) { rows[command.id] = command }
    override suspend fun get(ownerId: String, id: String) = rows[id]?.takeIf { it.ownerId == ownerId }
    override suspend fun unresolved(ownerId: String) = rows.values.filter { it.ownerId == ownerId && it.state in setOf("PENDING","IN_FLIGHT","AMBIGUOUS","EXPIRED") }
    override suspend fun mark(ownerId: String, id: String, state: CommandState, resultReference: String?) {
        if (state == CommandState.ACKNOWLEDGED) assertNotNull("Receipt must precede acknowledgment", store.receipts[ownerId to id])
        rows[id] = requireNotNull(get(ownerId,id)).copy(state = state.name, knownResultReference = resultReference)
    }
    override suspend fun markAttempt(ownerId: String, id: String, nowEpochMs: Long) { rows[id] = requireNotNull(get(ownerId,id)).copy(state = "IN_FLIGHT") }
}

class TestLearningApi : LearningApi, EmbyrApi {
    lateinit var detail: ExplorationDetailDto
    lateinit var session: AssessmentSessionDto
    lateinit var current: AssessmentResponseDto
    var deliveryResult: ApiResult<DeliveryDto> = ApiResult.Failure(TransportError.Network("offline"))
    var editResult: ApiResult<ReflectionDto> = ApiResult.Failure(TransportError.Network("offline"))
    var actionResult: ApiResult<ExplorationDto> = ApiResult.Failure(TransportError.Network("offline"))
    val starts = mutableListOf<Pair<String,String>>()
    var startResult: ApiResult<AssessmentSessionDto> = ApiResult.Failure(TransportError.Network("offline"))
    var pageWait: CompletableDeferred<Unit>? = null
    var startWait: CompletableDeferred<Unit>? = null
    val startEntered = CompletableDeferred<Unit>()
    var supportWait: CompletableDeferred<Unit>? = null
    val supportEntered = CompletableDeferred<Unit>()
    var afterDelivery: (() -> Unit)? = null
    val deliveries = mutableListOf<Pair<String,String>>()
    val actions = mutableListOf<String>()
    val completions = mutableListOf<String>()
    var completionResult: ApiResult<ExplorationDto> = ApiResult.Failure(TransportError.Network("offline"))
    val answerRequests = mutableListOf<Pair<String,String>>()
    var answerResult: ApiResult<AnswerAcknowledgmentDto> = ApiResult.Success(AnswerAcknowledgmentDto("response","PENDING","WAITING_FOR_EVALUATION",null),202)
    val retryRequests = mutableListOf<Pair<String,String>>()
    var retryResult: ApiResult<EvaluationRetryDto> = ApiResult.Success(EvaluationRetryDto("response","PENDING","WAITING_FOR_EVALUATION",null,"new-run"),202)
    var edits = 0; var answerCalls = 0; var retries = 0
    override suspend fun explorationList(limit: Int, cursor: String?): ApiResult<ExplorationListDto> { pageWait?.await(); return ApiResult.Success(ExplorationListDto(emptyList(),null),200) }
    override suspend fun exploration(id: String) = ApiResult.Success(detail, 200)
    override suspend fun deliver(id: String, payload: ByteArray, key: String): ApiResult<DeliveryDto> { deliveries += key to payload.decodeToString(); if (deliveryResult is ApiResult.Success) {
            if (afterDelivery != null) afterDelivery?.invoke() else detail = detail.copy(delivery = (deliveryResult as ApiResult.Success).value,version = detail.version + 1)
        }; return deliveryResult }
    override suspend fun explorationAction(id: String, payload: ByteArray, key: String): ApiResult<ExplorationDto> { actions += payload.decodeToString(); return actionResult }
    override suspend fun completeExploration(id: String, payload: ByteArray, key: String): ApiResult<ExplorationDto> { completions += payload.decodeToString(); return completionResult }
    override suspend fun createReflection(id: String, payload: ByteArray, key: String): ApiResult<ReflectionDto> = error("Unused")
    override suspend fun editReflection(id: String, payload: ByteArray): ApiResult<ReflectionDto> { edits++; return editResult }
    override suspend fun startAssessment(id: String, payload: ByteArray, key: String): ApiResult<AssessmentSessionDto> { starts += key to payload.decodeToString(); startEntered.complete(Unit); startWait?.await(); return startResult }
    override suspend fun assessmentSession(id: String) = ApiResult.Success(session,200)
    override suspend fun requestSupport(id: String, payload: ByteArray, key: String): ApiResult<SupportDto> { supportEntered.complete(Unit); supportWait?.await(); return ApiResult.Success(SupportDto("support","SMALL_NUDGE",SupportContentDto("Reviewed nudge")),200) }
    override suspend fun assessmentResponse(id: String) = ApiResult.Success(current, 200)
    override suspend fun retryEvaluation(id: String, payload: ByteArray, key: String): ApiResult<EvaluationRetryDto> { retries++; retryRequests += key to payload.decodeToString(); return retryResult }
    override suspend fun submitAnswer(sessionId: String, canonicalPayload: ByteArray, idempotencyKey: String): ApiResult<AnswerAcknowledgmentDto> { answerCalls++; answerRequests += idempotencyKey to canonicalPayload.decodeToString(); return answerResult }
    override suspend fun bootstrap(): ApiResult<ProfileDto> = error("Unused")
    override suspend fun profile(): ApiResult<ProfileDto> = error("Unused")
    override suspend fun starterInterests(): ApiResult<StarterInterestPageDto> = error("Unused")
    override suspend fun completeOnboarding(canonicalPayload: ByteArray, idempotencyKey: String): ApiResult<OnboardingResultDto> = error("Unused")
    override suspend fun explorations(limit: Int, cursor: String?): ApiResult<ExplorationPageDto> = error("Unused")
    override suspend fun decideRecommendation(recommendationId: String, canonicalPayload: ByteArray, idempotencyKey: String): ApiResult<RecommendationDecisionResult> = error("Unused")
    override suspend fun world(): ApiResult<WorldSnapshotDto> = error("Unused")
    override suspend fun worldChanges(afterRevision: Long): ApiResult<WorldDeltaPageDto> = error("Unused")
    override suspend fun nextRecommendation(canonicalPayload: ByteArray, idempotencyKey: String): ApiResult<RecommendationResult> = error("Unused")
}
