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
    val owner: String? = null, val session: AssessmentSessionDto? = null,
    val response: AssessmentResponseDto? = null, val responseId: String? = null, val selectedOptionId: String? = null,
    val busy: Boolean = false, val polling: Boolean = false, val message: String? = null,
)
class AssessmentViewModel(
    private val owners: OwnerSession, private val repository: AssessmentRepository,
    private val online: () -> Boolean, private val poller: AssessmentPoller = AssessmentPoller(),
) : ViewModel() {
    private val mutable = MutableStateFlow(AssessmentUiState())
    val ui: StateFlow<AssessmentUiState> = mutable
    private var actionJob: Job? = null; private var pollJob: Job? = null
    private var foreground = false; private var epoch = 0L
    init { viewModelScope.launch {
        owners.owner.collect { owner ->
            epoch++; actionJob?.cancel(); pollJob?.cancel()
            mutable.value = AssessmentUiState(owner = owner)
        }
    } }
    fun start(exploration: String, confidence: String, onStarted: (String) -> Unit) = action {
        val result = repository.start(exploration,confidence)
        mutable.value = mutable.value.copy(message = learningMessage(result))
        if (result == LearningOutcome.Done) {
            // The session ID is from the persisted public resource, never inferred from ACCEPT.
            val row = repository.activitySession()
            row?.let { onStarted(it) }
        }
    }
    fun leave(onLeft: () -> Unit) {
        val owner = owners.owner.value ?: return
        foreground(false)
        owners.scopeFor(owner).launch(Dispatchers.Main.immediate) { repository.leave(); onLeft() }
    }
    fun open(id: String) {
        if (actionJob?.isActive == true) return
        pollJob?.cancel(); epoch++
        mutable.value = AssessmentUiState(owner = owners.owner.value)
        action { render(id,repository.open(id)); beginPolling() }
    }
    fun support(level: String) = action { mutable.value.session?.id?.let { render(it,repository.support(it,level)) } }
    fun answer(option: String) = action { mutable.value.session?.id?.let { render(it,repository.answer(it,option)); beginPolling() } }
    fun retry() {
        if (actionJob?.isActive == true) return
        pollJob?.cancel(); epoch++
        action { mutable.value.session?.id?.let { render(it,repository.retry(it)); beginPolling() } }
    }
    fun recheck() = action { mutable.value.session?.id?.let { render(it,repository.refresh(it)); beginPolling() } }
    fun foreground(value: Boolean) {
        foreground = value
        if (value) beginPolling() else { pollJob?.cancel(); mutable.value = mutable.value.copy(polling = false) }
    }
    private suspend fun render(id: String, result: LearningOutcome) {
        val row = repository.read(id) ?: return
        mutable.value = mutable.value.copy(session = row.session(), response = row.response(), responseId = row.responseId, selectedOptionId = row.selectedOptionId, message = learningMessage(result))
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
    override fun onCleared() { actionJob?.cancel(); pollJob?.cancel() }
    class Factory(private val container: AppContainer) : ViewModelProvider.Factory {
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            @Suppress("UNCHECKED_CAST") return AssessmentViewModel(container.ownerSession,container.assessments,container::isOnline) as T
        }
    }
}
