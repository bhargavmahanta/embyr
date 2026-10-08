package app.embyr.feature.memory

import app.embyr.auth.*
import app.embyr.core.model.*
import app.embyr.core.network.*
import app.embyr.core.storage.*
import java.util.UUID
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Transport freshness and the server's projection status are separate facts. */
data class MemoryRead(val summary: MemorySummaryDto?, val fetchedAt: Long?, val fresh: Boolean, val error: TransportError?, val operations: List<InterestOperationEntity>)

class MemoryRepository(
    private val api: EmbyrApi, private val owners: OwnerSession, private val store: MemoryStore,
    private val clock: () -> Long = System::currentTimeMillis,
) {
    private val mutex = Mutex()
    suspend fun cached(binding: OwnerBinding): MemoryRead {
        owners.requireActive(binding)
        val cached = store.cache(binding)
        val summary = try { cached?.summary() } catch (_: IllegalArgumentException) { null } catch (_: kotlinx.serialization.SerializationException) { null }
        return MemoryRead(summary, cached?.fetchedAtEpochMs, false, null, store.unresolved(binding))
    }
    suspend fun refresh(binding: OwnerBinding): MemoryRead = mutex.withLock { refreshLocked(binding) }
    private suspend fun refreshLocked(binding: OwnerBinding): MemoryRead {
        owners.requireActive(binding)
        val result = api.memorySummary()
        owners.requireActive(binding)
        return when (result) {
            is ApiResult.Success -> {
                require(result.httpStatus == 200)
                M6Contract.memory(result.value)
                val now = clock()
                store.putCache(binding, result.value, now)
                MemoryRead(result.value, now, true, null, store.unresolved(binding))
            }
            is ApiResult.Failure -> cached(binding).copy(error = result.error)
        }
    }
    /** Called only by an explicit user action using a row actually observed in a summary. */
    suspend fun put(binding: OwnerBinding, observed: ExplicitInterestDto, preference: String): MemoryRead = mutex.withLock {
        owners.requireActive(binding)
        require(preference in M6Contract.preferences)
        val row = requireNotNull(store.cache(binding)?.summary()?.explicitInterests?.find { it.entityId == observed.entityId })
        require(row == observed && row.version < Long.MAX_VALUE)
        require(store.unresolved(binding).none { it.entityId == row.entityId }) { "Resolve the saved intent first" }
        sendNew(binding, row, preference, null)
    }
    suspend fun applySaved(binding: OwnerBinding, operationId: String): MemoryRead = mutex.withLock {
        val current = refreshLocked(binding)
        require(current.fresh) { "Read the current choice before applying" }
        val saved = requireNotNull(store.operation(binding, operationId))
        require(saved.state in setOf("UNCERTAIN", "CONFLICT", "REJECTED"))
        val observed = requireNotNull(current.summary?.explicitInterests?.find { it.entityId == saved.entityId }) { "Choice is outside the bounded summary" }
        require(observed.version >= saved.baseVersion && observed.version < Long.MAX_VALUE)
        sendNew(binding, observed, saved.preference, saved.id)
    }
    suspend fun adoptCurrent(binding: OwnerBinding, operationId: String): MemoryRead = mutex.withLock {
        val current = refreshLocked(binding)
        require(current.fresh)
        val saved = requireNotNull(store.operation(binding, operationId))
        require(saved.state in setOf("UNCERTAIN", "CONFLICT", "REJECTED"))
        val observed = requireNotNull(current.summary?.explicitInterests?.find { it.entityId == saved.entityId })
        // Adoption says nothing about whether the original PUT succeeded.
        store.resolve(binding, saved.id, "ADOPTED", observed.version)
        current.copy(operations = store.unresolved(binding))
    }
    private suspend fun sendNew(binding: OwnerBinding, observed: ExplicitInterestDto, preference: String, replaces: String?): MemoryRead {
        val payload = M6Json.codec.encodeToString(InterestPutDto.serializer(), InterestPutDto(observed.version, preference)).toByteArray()
        val operation = InterestOperationEntity(UUID.randomUUID().toString(), binding.ownerId, observed.entityId, observed.version, preference, payload, clock())
        store.insert(binding, operation) // Crash or cancellation from this point retains the exact uncertain intent.
        replaces?.let { store.resolve(binding, it, "REPLACED") }
        owners.requireActive(binding)
        val response = api.updateInterest(observed.entityId, payload)
        owners.requireActive(binding)
        when (response) {
            is ApiResult.Success -> {
                val value = response.value
                if (response.httpStatus == 200 && value.entityId == observed.entityId && value.preference == preference && value.version == observed.version + 1) {
                    store.resolve(binding, operation.id, "ACKNOWLEDGED", value.version)
                }
            }
            is ApiResult.Failure -> {
                val state = when(val error = response.error) {
                    is TransportError.Authentication, is TransportError.Validation -> "REJECTED"
                    is TransportError.Problem -> if (error.httpStatus == 409) "CONFLICT" else if (error.httpStatus in 400..499) "REJECTED" else "UNCERTAIN"
                    is TransportError.UnexpectedHttp -> if (error.httpStatus == 409) "CONFLICT" else if (error.httpStatus in 400..499) "REJECTED" else "UNCERTAIN"
                    else -> "UNCERTAIN"
                }
                store.resolve(binding, operation.id, state)
            }
        }
        return refreshLocked(binding)
    }
}
