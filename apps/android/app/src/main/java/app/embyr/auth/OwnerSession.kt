package app.embyr.auth

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/** The mapped internal learner ID is a namespace, never an authentication credential. */
class OwnerSession {
    private val mutableOwner = MutableStateFlow<String?>(null)
    val owner: StateFlow<String?> = mutableOwner
    private var ownerScope = CoroutineScope(SupervisorJob())

    @Synchronized
    fun switchTo(mappedOwnerId: String?) {
        mutableOwner.value = null
        ownerScope.cancel()
        ownerScope = CoroutineScope(SupervisorJob())
        mutableOwner.value = mappedOwnerId
    }

    fun requireOwner(): String = owner.value ?: error("Mapped learner identity is unresolved")

    @Synchronized
    fun scopeFor(mappedOwnerId: String): CoroutineScope {
        check(requireOwner() == mappedOwnerId)
        return ownerScope
    }
}
