package app.embyr.core.storage

import app.embyr.auth.OwnerSession
import app.embyr.core.network.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.serialization.KSerializer

sealed interface LearningOutcome {
    data object Done : LearningOutcome
    data object Pending : LearningOutcome
    data object Unknown : LearningOutcome
    data class Conflict(val message: String = "This changed on the server. Review the current state before applying again.") : LearningOutcome
    data class Invalid(val message: String) : LearningOutcome
    data class Failed(val error: TransportError) : LearningOutcome
}

/** A receipt and public presentation are committed before the POST dispatcher ACK. */
class LearningCommands(
    private val outbox: CommandOutbox, private val dispatcher: CommandDispatcher,
    private val owners: OwnerSession, private val store: LearningStore,
    private val now: () -> Long = System::currentTimeMillis,
) {
    suspend fun pending(prefix: String): List<CommandEntity> = outbox.unresolved(owners.requireOwner()).filter { it.relativeRoute.startsWith(prefix) }
    suspend fun recoverReceipts() {
        val owner = owners.requireOwner()
        outbox.unresolved(owner).forEach { command ->
            store.receipt(owner,command.id)?.let { receipt -> outbox.mark(owner,command.id,CommandState.RESOLVED,receipt.resultReference) }
        }
    }
    suspend fun hasPending(route: String): Boolean = outbox.unresolved(owners.requireOwner()).any { it.relativeRoute == route }
    private val mutex = Mutex()
    suspend fun <P, R> post(
        route: String, payloadSerializer: KSerializer<P>, payload: P, resultSerializer: KSerializer<R>,
        send: suspend (CommandEntity) -> ApiResult<R>, persist: suspend (R) -> Unit,
        reference: (R) -> String? = { null }, reconcile: suspend (CommandEntity) -> R? = { null },
    ): LearningOutcome {
        if (!mutex.tryLock()) return LearningOutcome.Pending
        try {
            val owner = owners.requireOwner()
            val previous = outbox.unresolved(owner).lastOrNull { it.relativeRoute == route }
            if (previous != null) {
                val receipt = store.receipt(owner, previous.id)
                if (receipt != null) {
                    persist(LearningJson.codec.decodeFromString(resultSerializer, receipt.resultJson))
                    outbox.mark(owner, previous.id, CommandState.RESOLVED, receipt.resultReference)
                    return LearningOutcome.Done
                }
                if (!ReplayWindow.mayReplay(previous.createdAtEpochMs, now())) {
                    outbox.mark(owner, previous.id, CommandState.EXPIRED)
                    val recovered = reconcile(previous) ?: return LearningOutcome.Unknown
                    persist(recovered)
                    store.putReceipt(LearningReceiptEntity(owner, previous.id, LearningJson.codec.encodeToString(resultSerializer, recovered), reference(recovered)))
                    outbox.mark(owner, previous.id, CommandState.RESOLVED, reference(recovered))
                    return LearningOutcome.Done
                }
            }
            var result: LearningOutcome = LearningOutcome.Pending
            val transmit: suspend (CommandEntity) -> TransmissionOutcome = { command ->
                when (val response = send(command)) {
                    is ApiResult.Success -> {
                        persist(response.value)
                        store.putReceipt(LearningReceiptEntity(owner, command.id, LearningJson.codec.encodeToString(resultSerializer, response.value), reference(response.value)))
                        result = LearningOutcome.Done
                        TransmissionOutcome.Acknowledged(reference(response.value))
                    }
                    is ApiResult.Failure -> {
                        val error = response.error
                        if (ambiguous(error)) {
                            if (error is TransportError.Problem && error.details.code == "EXPLORATION_CONTENT_UNAVAILABLE") result = LearningOutcome.Failed(error)
                            TransmissionOutcome.Ambiguous
                        } else {
                            result = if (error is TransportError.Problem && error.details.code == "VERSION_CONFLICT") LearningOutcome.Conflict() else LearningOutcome.Failed(error)
                            TransmissionOutcome.Rejected
                        }
                    }
                }
            }
            if (previous != null) dispatcher.retry(owner, previous.id, now(), transmit)
            else dispatcher.persistThenSend(owner, "POST", route, payloadSerializer, payload, now(), transmit)
            return result
        } finally { mutex.unlock() }
    }
    private fun ambiguous(error: TransportError): Boolean = when (error) {
        is TransportError.Authentication, is TransportError.Network, TransportError.AmbiguousTimeout, is TransportError.Decode -> true
        is TransportError.Problem -> error.httpStatus >= 500 || error.details.code == "COMMAND_IN_PROGRESS"
        is TransportError.UnexpectedHttp -> error.httpStatus >= 500 || error.httpStatus in 200..299
        else -> false
    }
}
