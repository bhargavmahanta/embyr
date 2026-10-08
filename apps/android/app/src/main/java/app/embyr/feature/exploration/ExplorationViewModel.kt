package app.embyr.feature.exploration

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import app.embyr.AppContainer
import app.embyr.auth.OwnerSession
import app.embyr.core.model.*
import app.embyr.core.network.*
import app.embyr.core.storage.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*

 data class ExplorationUiState(
    val owner: String? = null, val items: List<ExplorationDto> = emptyList(), val nextCursor: String? = null,
    val selected: String? = null, val detail: ExplorationDetailDto? = null, val draft: String = "",
    val busy: Boolean = false, val message: String? = null, val editOutstanding: Boolean = false,
    val assessmentStartPending: Boolean = false, val lifecycleNeedsRefresh: Boolean = false, val pendingOperations: List<String> = emptyList(), val restoreExploration: String? = null, val restoreSession: String? = null,
)
class ExplorationViewModel(private val owners: OwnerSession, private val store: LearningStore, private val repository: ExplorationRepository) : ViewModel() {
    private val mutable = MutableStateFlow(ExplorationUiState())
    val ui: StateFlow<ExplorationUiState> = mutable
    val activeOwner = owners.owner
    private var actionJob: Job? = null
    private var draftJob: Job? = null
    private var epoch = 0L
    private val cursors = mutableSetOf<String>()
    init { viewModelScope.launch {
        owners.owner.collect { owner ->
            epoch++; actionJob?.cancel(); draftJob?.cancel(); cursors.clear()
            mutable.value = ExplorationUiState(owner = owner)
            if (owner != null) runAction {
                repository.restoreReceipts()
                val saved = store.activity(owner)
                mutable.value = mutable.value.copy(restoreExploration = saved.explorationId, restoreSession = saved.sessionId)
                loadPage(null)
            }
        }
    } }
    fun consumeRestore() { mutable.value = mutable.value.copy(restoreExploration = null, restoreSession = null) }
    fun list() = runAction { repository.select(null); loadPage(null) }
    fun more() = runAction { mutable.value.nextCursor?.let { loadPage(it) } }
    private suspend fun loadPage(cursor: String?) {
        if (cursor == null) cursors.clear()
        if (cursor != null && cursor in cursors) { mutable.value = mutable.value.copy(nextCursor = null, message = "No further page is available."); return }
        val owner = owners.requireOwner()
        when (val result = repository.page(cursor)) {
            is ApiResult.Failure -> mutable.value = mutable.value.copy(message = learningMessage(LearningOutcome.Failed(result.error)))
            is ApiResult.Success -> {
                check(owners.requireOwner() == owner)
                if (cursor != null) cursors += cursor
                val items = ((if (cursor == null) emptyList() else mutable.value.items) + result.value.items).distinctBy { it.id }
                val next = result.value.nextCursor?.takeUnless { it == cursor || it in cursors }
                mutable.value = mutable.value.copy(items = items, nextCursor = next, message = null)
            }
        }
    }
    fun open(id: String) {
        actionJob?.cancel(); epoch++
        runAction {
        mutable.value = mutable.value.copy(selected = id, detail = null, draft = "", message = null)
        repository.select(id)
        val outcome = repository.open(id); render(id, outcome)
        }
    }
    fun refresh() = runAction { mutable.value.selected?.let { render(it, repository.open(it)) } }
    fun setDraft(value: String) {
        val owner = owners.owner.value ?: return; val id = mutable.value.selected ?: return
        if (value.length > 10000) return
        mutable.value = mutable.value.copy(draft = value)
        val previous = draftJob
        draftJob = owners.scopeFor(owner).launch(Dispatchers.Main.immediate) {
            previous?.join()
            repository.saveDraft(id,value)
        }
    }
    fun deliver() = mutate { repository.deliver(it) }
    fun action(action: String) = mutate { repository.action(it, action) }
    fun complete() = mutate { repository.complete(it) }
    fun saveReflection(applyFresh: Boolean = false) = mutate { id ->
        draftJob?.join(); repository.saveDraft(id,mutable.value.draft)
        repository.saveReflection(id,applyFresh)
    }
    fun recover() = mutate { repository.recover(it) }
    fun recheckEdit() = mutate { repository.reconcileEdit(it) }
    private fun mutate(block: suspend (String) -> LearningOutcome) = runAction {
        mutable.value.selected?.let { render(it,block(it)) }
    }
    private suspend fun render(id: String, result: LearningOutcome) {
        val row = repository.read(id)
        mutable.value = mutable.value.copy(detail = row.detail(), draft = row.draft, editOutstanding = row.editJson != null, lifecycleNeedsRefresh = row.lifecycleNeedsRefresh, pendingOperations = repository.pending(id), message = learningMessage(result))
    }
    private fun runAction(block: suspend () -> Unit) {
        val owner = owners.owner.value ?: return
        if (actionJob?.isActive == true) return
        val generation = epoch
        mutable.value = mutable.value.copy(busy = true)
        actionJob = owners.scopeFor(owner).launch(Dispatchers.Main.immediate, start = CoroutineStart.LAZY) {
            try { block() }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { if (generation == epoch && owners.owner.value == owner) mutable.value = mutable.value.copy(message = "Could not finish. Your saved requests and draft remain available.") }
            finally { if (generation == epoch && owners.owner.value == owner) mutable.value = mutable.value.copy(busy = false) }
        }.also { it.start() }
    }
    override fun onCleared() { actionJob?.cancel(); draftJob?.cancel() }
    class Factory(private val container: AppContainer) : ViewModelProvider.Factory {
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            @Suppress("UNCHECKED_CAST") return ExplorationViewModel(container.ownerSession,container.learningStore,container.explorations) as T
        }
    }
}
fun learningMessage(outcome: LearningOutcome): String? = when (outcome) {
    LearningOutcome.Done -> null
    LearningOutcome.Pending -> "The original request is pending. Check again to recover that same request."
    LearningOutcome.Unknown -> "The earlier outcome is unconfirmed. Review the server state; do not start a duplicate request."
    is LearningOutcome.Conflict -> outcome.message
    is LearningOutcome.Invalid -> outcome.message
    is LearningOutcome.Failed -> when (val error = outcome.error) {
        is TransportError.Authentication -> "Sign in again to recover your saved request."
        is TransportError.Problem -> when (error.details.code) {
            "EXPLORATION_CONTENT_UNAVAILABLE" -> "Reviewed work is temporarily unavailable. Your exploration is retained; try preparing it again."
            "VERSION_CONFLICT" -> "This changed on the server. Refresh and review before applying again."
            else -> "The server could not finish this action. Refresh and try again."
        }
        else -> "Could not connect. Your saved data remains available; try again."
    }
}

fun ExplorationUiState.withAssessmentStart(assessment: app.embyr.feature.assessment.AssessmentUiState): ExplorationUiState {
    if (owner == null || assessment.owner != owner || assessment.startTarget != selected) return this
    return copy(busy = busy || assessment.busy, message = assessment.message ?: message, assessmentStartPending = assessment.startPending)
}
