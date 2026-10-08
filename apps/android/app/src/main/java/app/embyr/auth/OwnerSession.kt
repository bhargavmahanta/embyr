package app.embyr.auth

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

data class OwnerBinding(val ownerId: String, val generation: Long)

/** The mapped internal learner ID is a namespace, never an authentication credential. */
class OwnerSession {
    private val mutableOwner = MutableStateFlow<String?>(null)
    val owner: StateFlow<String?> = mutableOwner
    private var generation = 0L
    private val mutableBinding = MutableStateFlow<OwnerBinding?>(null)
    val binding: StateFlow<OwnerBinding?> = mutableBinding
    private var ownerScope = CoroutineScope(SupervisorJob())

    @Synchronized
    fun switchTo(mappedOwnerId: String?) {
        generation = Math.addExact(generation, 1L)
        mutableBinding.value = null
        mutableOwner.value = null
        ownerScope.cancel()
        ownerScope = CoroutineScope(SupervisorJob())
        mutableOwner.value = mappedOwnerId
        mutableBinding.value = mappedOwnerId?.let { OwnerBinding(it, generation) }
    }

    @Synchronized
    fun capture(): OwnerBinding = binding.value ?: error("Mapped learner identity is unresolved")

    fun isActive(expected: OwnerBinding): Boolean = binding.value == expected
    fun requireActive(expected: OwnerBinding) { check(isActive(expected)) { "Learner binding changed" } }

    @Synchronized
    fun scopeFor(expected: OwnerBinding): CoroutineScope {
        requireActive(expected)
        return ownerScope
    }

    fun requireOwner(): String = owner.value ?: error("Mapped learner identity is unresolved")

    @Synchronized
    fun scopeFor(mappedOwnerId: String): CoroutineScope {
        check(requireOwner() == mappedOwnerId)
        return ownerScope
    }
}
