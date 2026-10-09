package app.embyr.feature.memory

import androidx.lifecycle.*
import app.embyr.AppContainer
import app.embyr.auth.*
import app.embyr.core.model.ExplicitInterestDto
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*

 data class MemoryUiState(val binding: OwnerBinding? = null, val read: MemoryRead? = null, val busy: Boolean = false, val message: String? = null)

class MemoryViewModel(private val owners: OwnerSession, private val repository: MemoryRepository) : ViewModel() {
    private val mutable = MutableStateFlow(MemoryUiState())
    val ui: StateFlow<MemoryUiState> = mutable
    val activeBinding = owners.binding
    private var job: Job? = null
    init { viewModelScope.launch {
        owners.binding.collect { binding ->
            job?.cancel()
            mutable.value = MemoryUiState(binding)
        }
    } }
    fun open() = action { binding ->
        val saved = repository.cached(binding)
        if (owners.isActive(binding)) mutable.value = mutable.value.copy(read = saved)
        repository.refresh(binding)
    }
    fun refresh() = action { repository.refresh(it) }
    fun put(row: ExplicitInterestDto, preference: String) = action { repository.put(it, row, preference) }
    fun applySaved(id: String) = action { repository.applySaved(it, id) }
    fun adopt(id: String) = action { repository.adoptCurrent(it, id) }
    private fun action(block: suspend (OwnerBinding) -> MemoryRead) {
        val binding = owners.binding.value ?: return
        if (job?.isActive == true) return
        mutable.value = mutable.value.copy(busy = true, message = null)
        job = owners.scopeFor(binding).launch(Dispatchers.Main.immediate) {
            try {
                val result = block(binding)
                if (owners.isActive(binding)) mutable.value = mutable.value.copy(read = result)
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: IllegalArgumentException) { if (owners.isActive(binding)) mutable.value = mutable.value.copy(message = "Refresh the current choice before continuing.") }
            catch (_: IllegalStateException) { if (owners.isActive(binding)) mutable.value = mutable.value.copy(message = "Could not finish. Refresh and try again.") }
            finally { if (owners.isActive(binding)) mutable.value = mutable.value.copy(busy = false) }
        }
    }
    class Factory(private val container: AppContainer) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST") override fun <T : ViewModel> create(modelClass: Class<T>): T = MemoryViewModel(container.ownerSession, container.memory) as T
    }
}
