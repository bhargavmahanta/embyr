package app.embyr.feature.world

import androidx.lifecycle.*
import app.embyr.AppContainer
import app.embyr.auth.*
import app.embyr.core.model.*
import app.embyr.core.storage.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*

 data class WorldUiState(val binding: OwnerBinding? = null, val read: WorldRead? = null, val names: Map<Pair<String,Long>,String> = emptyMap(), val busy: Boolean = false, val message: String? = null)

class WorldViewModel(private val owners: OwnerSession, private val repository: WorldRepository, private val memoryStore: MemoryStore, private val knownNames: suspend (OwnerBinding) -> Map<Pair<String,Long>,String>) : ViewModel() {
    private val mutable = MutableStateFlow(WorldUiState())
    val ui: StateFlow<WorldUiState> = mutable
    val activeBinding = owners.binding
    private var job: Job? = null
    init { viewModelScope.launch {
        owners.binding.collect { binding ->
            job?.cancel()
            mutable.value = WorldUiState(binding)
        }
    } }
    fun open() = action { binding ->
        val saved = repository.cached(binding)
        if (owners.isActive(binding)) mutable.value = mutable.value.copy(read = saved)
        repository.synchronize(binding)
    }
    fun refresh() = action { repository.synchronize(it) }
    private fun action(block: suspend (OwnerBinding) -> WorldRead) {
        val binding = owners.binding.value ?: return
        if (job?.isActive == true) return
        mutable.value = mutable.value.copy(busy = true, message = null)
        job = owners.scopeFor(binding).launch(Dispatchers.Main.immediate) {
            try {
                val result = block(binding)
                val titles = knownNames(binding).toMutableMap()
                val memory = try { memoryStore.cache(binding)?.summary() } catch (_: IllegalArgumentException) { null } catch (_: kotlinx.serialization.SerializationException) { null }
                memory?.recentlyExplored?.forEach { titles[it.entityId to it.entityVersion] = it.title }
                memory?.explicitInterests?.filter { it.availability == "AVAILABLE" }?.forEach { row -> titles[row.entityId to requireNotNull(row.entityVersion)] = requireNotNull(row.title) }
                owners.requireActive(binding)
                mutable.value = mutable.value.copy(read = result, names = titles)
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: IllegalArgumentException) { if (owners.isActive(binding)) mutable.value = mutable.value.copy(message = "Could not read this World. Refresh to recover.") }
            catch (_: IllegalStateException) { if (owners.isActive(binding)) mutable.value = mutable.value.copy(message = "Could not finish. Refresh to recover.") }
            finally { if (owners.isActive(binding)) mutable.value = mutable.value.copy(busy = false) }
        }
    }
    class Factory(private val container: AppContainer) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST") override fun <T : ViewModel> create(modelClass: Class<T>): T = WorldViewModel(container.ownerSession, container.world, container.memoryStore, container::knownWorldNames) as T
    }
}
