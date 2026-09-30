package app.embyr.core.storage

import app.embyr.auth.OwnerSession
import java.io.IOException
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.cancel
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

enum class CommandState { PENDING, IN_FLIGHT, ACKNOWLEDGED, AMBIGUOUS, EXPIRED, RESOLVED }

interface CommandOutbox {
    suspend fun enqueue(command: CommandEntity)
    suspend fun get(ownerId: String, id: String): CommandEntity?
    suspend fun unresolved(ownerId: String): List<CommandEntity>
    suspend fun mark(ownerId: String, id: String, state: CommandState, resultReference: String? = null)
    suspend fun markAttempt(ownerId: String, id: String, nowEpochMs: Long)
}

class RoomCommandOutbox(private val dao: CommandDao, private val owners: OwnerSession) : CommandOutbox {
    override suspend fun enqueue(command: CommandEntity) {
        check(owners.requireOwner() == command.ownerId)
        dao.insert(command)
    }
    override suspend fun get(ownerId: String, id: String): CommandEntity? {
        check(owners.requireOwner() == ownerId)
        return dao.get(ownerId, id)
    }
    override suspend fun unresolved(ownerId: String): List<CommandEntity> {
        check(owners.requireOwner() == ownerId)
        return dao.unresolved(ownerId)
    }
    override suspend fun mark(ownerId: String, id: String, state: CommandState, resultReference: String?) {
        check(owners.requireOwner() == ownerId)
        check(dao.updateState(ownerId, id, state.name, resultReference) == 1)
    }
    override suspend fun markAttempt(ownerId: String, id: String, nowEpochMs: Long) {
        check(owners.requireOwner() == ownerId)
        check(dao.markAttempt(ownerId, id, nowEpochMs) == 1)
    }
}

object CanonicalPayload {
    @OptIn(ExperimentalSerializationApi::class)
    private val json = Json { encodeDefaults = true; explicitNulls = true }

    fun <T> encode(serializer: KSerializer<T>, value: T): ByteArray {
        val element = json.encodeToJsonElement(serializer, value)
        return canonical(element).toByteArray(Charsets.UTF_8)
    }

    private fun canonical(element: JsonElement): String = when (element) {
        is JsonObject -> element.entries.sortedBy { it.key }.joinToString(",", "{", "}") {
            "${json.encodeToString(String.serializer(), it.key)}:${canonical(it.value)}"
        }
        is kotlinx.serialization.json.JsonArray -> element.joinToString(",", "[", "]") { canonical(it) }
        else -> element.toString()
    }
}

object ReplayWindow {
    const val SERVER_WINDOW_MS = 24L * 60 * 60 * 1000
    const val SAFE_WINDOW_MS = 23L * 60 * 60 * 1000

    fun mayReplay(createdAtEpochMs: Long, nowEpochMs: Long): Boolean =
        nowEpochMs >= createdAtEpochMs && nowEpochMs - createdAtEpochMs < SAFE_WINDOW_MS
}

sealed interface TransmissionOutcome {
    data class Acknowledged(val resultReference: String? = null) : TransmissionOutcome
    data object Ambiguous : TransmissionOutcome
    data object Rejected : TransmissionOutcome
}

/** The only send path accepts a command that has already committed in Room. */
class CommandDispatcher(private val outbox: CommandOutbox, private val owners: OwnerSession) {
    private companion object {
        // Shared by dispatcher instances in this process; fixed stripes avoid retaining one lock per command.
        val retryLocks = Array(64) { Mutex() }
    }

    suspend fun <T> persistThenSend(
        ownerId: String,
        method: String,
        relativeRoute: String,
        serializer: KSerializer<T>,
        payload: T,
        nowEpochMs: Long,
        transmit: suspend (CommandEntity) -> TransmissionOutcome,
    ): CommandEntity {
        require(method == "POST")
        require(relativeRoute.startsWith("api/v1/") && "?" !in relativeRoute)
        val command = CommandEntity(
            id = UUID.randomUUID().toString(),
            ownerId = ownerId,
            method = method,
            relativeRoute = relativeRoute,
            canonicalPayload = CanonicalPayload.encode(serializer, payload),
            idempotencyKey = UUID.randomUUID().toString(),
            createdAtEpochMs = nowEpochMs,
            state = CommandState.PENDING.name,
        )
        outbox.enqueue(command) // Commit before any network call.
        retry(ownerId, command.id, nowEpochMs, transmit)
        return outbox.get(ownerId, command.id) ?: error("Committed command disappeared")
    }

    suspend fun retry(
        ownerId: String,
        id: String,
        nowEpochMs: Long,
        transmit: suspend (CommandEntity) -> TransmissionOutcome,
    ): CommandState = retryLocks[((31 * ownerId.hashCode() + id.hashCode()) and Int.MAX_VALUE) % retryLocks.size].withLock {
        val command = outbox.get(ownerId, id) ?: error("No command for owner")
        val prior = CommandState.valueOf(command.state)
        if (prior == CommandState.ACKNOWLEDGED || prior == CommandState.RESOLVED || prior == CommandState.EXPIRED) return@withLock prior
        if (!ReplayWindow.mayReplay(command.createdAtEpochMs, nowEpochMs)) {
            outbox.mark(ownerId, id, CommandState.EXPIRED)
            return@withLock CommandState.EXPIRED
        }
        outbox.markAttempt(ownerId, id, nowEpochMs)
        val attempt = owners.scopeFor(ownerId).async { transmit(command) }
        val outcome = try {
            attempt.await()
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: IOException) {
            TransmissionOutcome.Ambiguous
        } finally {
            if (!attempt.isCompleted) attempt.cancel()
        }
        val next = when (outcome) {
            is TransmissionOutcome.Acknowledged -> CommandState.ACKNOWLEDGED
            TransmissionOutcome.Ambiguous -> CommandState.AMBIGUOUS
            TransmissionOutcome.Rejected -> CommandState.RESOLVED
        }
        outbox.mark(ownerId, id, next, (outcome as? TransmissionOutcome.Acknowledged)?.resultReference)
        next
    }
}
