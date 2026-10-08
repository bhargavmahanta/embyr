package app.embyr.feature.assessment

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import app.embyr.AppContainer
import app.embyr.auth.OwnerSession
import app.embyr.core.model.*
import app.embyr.core.storage.*
import app.embyr.feature.exploration.learningMessage
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*

 data class AssessmentUiState(
    val owner: String? = null, val requestedSessionId: String? = null, val session: AssessmentSessionDto? = null,
    val response: AssessmentResponseDto? = null, val responseId: String? = null, val selectedOptionId: String? = null,
    val startPending: Boolean = false, val unconfirmedRequests: List<String> = emptyList(), val startTarget: String? = null, val busy: Boolean = false, val polling: Boolean = false, val message: String? = null,
)
class AssessmentViewModel(
    private val owners: OwnerSession, private val repository: AssessmentRepository,
    private val online: () -> Boolean, private val poller: AssessmentPoller = AssessmentPoller(),
) : ViewModel() {
    private val mutable = MutableStateFlow(AssessmentUiState())
    val ui: StateFlow<AssessmentUiState> = mutable
    private var actionJob: Job? = null; private var pollJob: Job? = null
    private var bindJob: Job? = null; private var leaveJob: Job? = null
    private var displayedExploration: String? = null; private var navigationEpoch = 0L
    private var foreground = false; private var epoch = 0L
    init { viewModelScope.launch {
        owners.owner.collect { owner ->
            epoch++; navigationEpoch++; displayedExploration = null; actionJob?.cancel(); pollJob?.cancel(); bindJob?.cancel(); leaveJob?.cancel()
            mutable.value = AssessmentUiState(owner = owner)
        }
    } }
    fun unbindExploration(exploration: String) {
        if (displayedExploration == exploration) {
            displayedExploration = null; navigationEpoch++; bindJob?.cancel()
            mutable.value = mutable.value.copy(startTarget = null,startPending = false,message = null)
        }
    }
    fun bindExploration(exploration: String) {
        val owner = owners.owner.value ?: return
        bindJob?.cancel(); displayedExploration = exploration; navigationEpoch++
        val navigation = navigationEpoch
        mutable.value = mutable.value.copy(startTarget = exploration,startPending = false,message = null)
        bindJob = owners.scopeFor(owner).launch(Dispatchers.Main.immediate) {
            val pending = repository.hasPendingStart(exploration)
            if (owners.owner.value == owner && navigationEpoch == navigation && displayedExploration == exploration)
                mutable.value = mutable.value.copy(startPending = pending,message = if (pending) "The original check start is unconfirmed. Check that saved request." else null)
        }
    }
    fun recoverStart(exploration: String, onStarted: (String) -> Unit) {
        val navigation = navigationEpoch
        action { showStart(exploration,repository.recoverStart(exploration),navigation,onStarted) }
    }
    fun start(exploration: String, confidence: String, onStarted: (String) -> Unit) {
        val navigation = navigationEpoch
        action { showStart(exploration,repository.start(exploration,confidence),navigation,onStarted) }
    }
    private suspend fun showStart(exploration: String, result: LearningOutcome, navigation: Long, onStarted: (String) -> Unit) {
        if (displayedExploration != exploration || navigationEpoch != navigation) return
        val pending = repository.hasPendingStart(exploration)
        if (displayedExploration != exploration || navigationEpoch != navigation) return
        mutable.value = mutable.value.copy(startPending = pending,message = learningMessage(result))
        if (result == LearningOutcome.Done) {
            val id = repository.storedSession(exploration)
            if (displayedExploration == exploration && navigationEpoch == navigation) id?.let(onStarted)
        }
    }
    fun leave(onLeft: () -> Unit) {
        val owner = owners.owner.value ?: return
        val id = mutable.value.requestedSessionId ?: return
        if (leaveJob?.isActive == true) return
        actionJob?.cancel(); pollJob?.cancel(); epoch++; val generation = epoch
        mutable.value = AssessmentUiState(owner = owner)
        leaveJob = owners.scopeFor(owner).launch(Dispatchers.Main.immediate) {
            repository.leave(id)
            if (owners.owner.value == owner && epoch == generation) onLeft()
        }
    }
    fun open(id: String) {
        actionJob?.cancel(); pollJob?.cancel(); bindJob?.cancel(); leaveJob?.cancel()
        epoch++; navigationEpoch++; displayedExploration = null
        mutable.value = AssessmentUiState(owner = owners.owner.value,requestedSessionId = id)
        action { render(id,repository.open(id)); beginPolling() }
    }
    fun support(level: String) = action { mutable.value.session?.id?.let { render(it,repository.support(it,level)) } }
    fun answer(option: String) = action { mutable.value.session?.id?.let { render(it,repository.answer(it,option)); beginPolling() } }
    fun retry() {
        if (actionJob?.isActive == true) return
        pollJob?.cancel(); epoch++
        action { mutable.value.session?.id?.let { render(it,repository.retry(it)); beginPolling() } }
    }
    fun recheck() {
        if (actionJob?.isActive == true) return
        pollJob?.cancel(); epoch++
        action { (mutable.value.requestedSessionId ?: mutable.value.session?.id)?.let { id ->
            if (repository.read(id) == null) { render(id,repository.open(id)); beginPolling(); return@let }
            val recovered = repository.recover(id)
            val fetched = repository.refresh(id,followCurrent = true)
            render(id,if (recovered == LearningOutcome.Done) fetched else recovered)
            beginPolling()
        } }
    }
    fun foreground(value: Boolean) {
        foreground = value
        if (value) beginPolling() else { pollJob?.cancel(); mutable.value = mutable.value.copy(polling = false) }
    }
    private suspend fun render(id: String, result: LearningOutcome) {
        if (mutable.value.requestedSessionId != id) return
        val row = repository.read(id)
        if (mutable.value.requestedSessionId != id) return
        if (row == null) { mutable.value = mutable.value.copy(message = learningMessage(result)); return }
        mutable.value = mutable.value.copy(session = row.session(), response = row.response(), responseId = row.responseId, selectedOptionId = row.selectedOptionId, unconfirmedRequests = repository.pending(id), message = learningMessage(result))
    }
    private fun beginPolling() {
        val state = mutable.value
        val owner = owners.owner.value ?: return
        val id = state.session?.id ?: return
        if (!foreground || state.responseId == null || state.response?.evaluationStatus in setOf("SUCCEEDED","FAILED") || pollJob?.isActive == true) return
        val generation = epoch
        pollJob = owners.scopeFor(owner).launch(Dispatchers.Main.immediate) {
            mutable.value = mutable.value.copy(polling = true)
            try {
                val end = poller.poll(online) {
                    val result = repository.refresh(id)
                    if (epoch != generation || owners.owner.value != owner) throw CancellationException()
                    render(id,result)
                    mutable.value.response?.evaluationStatus in setOf("SUCCEEDED","FAILED")
                }
                if (end != PollEnd.TERMINAL) mutable.value = mutable.value.copy(message = if (end == PollEnd.OFFLINE) "Offline. Your answer is saved; reconnect and recheck." else "Still processing. You can leave and recheck later.")
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { if (epoch == generation && owners.owner.value == owner) mutable.value = mutable.value.copy(message = "Could not check progress. Recheck your saved answer.") }
            finally { if (epoch == generation && owners.owner.value == owner) mutable.value = mutable.value.copy(polling = false) }
        }
    }
    private fun action(block: suspend () -> Unit) {
        val owner = owners.owner.value ?: return
        if (actionJob?.isActive == true) return
        val generation = epoch; mutable.value = mutable.value.copy(busy = true)
        actionJob = owners.scopeFor(owner).launch(Dispatchers.Main.immediate, start = CoroutineStart.LAZY) {
            try { block() }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { if (epoch == generation && owners.owner.value == owner) mutable.value = mutable.value.copy(message = "Could not finish. Your saved assessment remains available.") }
            finally { if (epoch == generation && owners.owner.value == owner) mutable.value = mutable.value.copy(busy = false) }
        }.also { it.start() }
    }
    override fun onCleared() { actionJob?.cancel(); pollJob?.cancel(); bindJob?.cancel(); leaveJob?.cancel() }
    class Factory(private val container: AppContainer) : ViewModelProvider.Factory {
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            @Suppress("UNCHECKED_CAST") return AssessmentViewModel(container.ownerSession,container.assessments,container::isOnline) as T
        }
    }
}
