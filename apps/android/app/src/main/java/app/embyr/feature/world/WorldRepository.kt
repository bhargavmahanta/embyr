package app.embyr.feature.world

import app.embyr.auth.*
import app.embyr.core.model.*
import app.embyr.core.network.*
import app.embyr.core.storage.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.SerializationException

 data class WorldRead(val cache: CachedWorld?, val fresh: Boolean = false, val more: Boolean = false, val error: TransportError? = null, val recovered: Boolean = false)

class WorldRepository(private val api: EmbyrApi, private val owners: OwnerSession, private val store: WorldStore, private val clock: () -> Long = System::currentTimeMillis) {
    // The repository is application-scoped: syncs for the same learner cannot overlap.
    private val mutex = Mutex()
    suspend fun cached(binding: OwnerBinding): WorldRead {
        owners.requireActive(binding)
        return try { WorldRead(store.read(binding)) }
        catch (_: SerializationException) { WorldRead(null, error = TransportError.Decode(200)) }
        catch (_: IllegalArgumentException) { WorldRead(null, error = TransportError.Decode(200)) }
    }
    suspend fun synchronize(binding: OwnerBinding): WorldRead = mutex.withLock {
        owners.requireActive(binding)
        var read = cached(binding)
        var cache = read.cache
        var recoveryUsed = false
        suspend fun snapshot(recovery: Boolean): WorldRead {
            if (recovery) {
                if (recoveryUsed) return WorldRead(cache, error = TransportError.Decode(200), recovered = true)
                recoveryUsed = true
            }
            val expected = store.stamp(binding)
            val result = api.world()
            owners.requireActive(binding)
            return when (result) {
                is ApiResult.Failure -> WorldRead(cache, error = result.error, recovered = recoveryUsed)
                is ApiResult.Success -> try {
                    require(result.httpStatus == 200)
                    val replacement = M6Contract.snapshot(result.value)
                    cache = store.resync(binding, expected, replacement, clock())
                    WorldRead(cache, fresh = true, recovered = recoveryUsed)
                } catch (_: IllegalArgumentException) { WorldRead(cache, error = TransportError.Decode(200), recovered = recoveryUsed) }
            }
        }
        if (cache == null) return@withLock snapshot(recovery = read.error != null)
        repeat(20) {
            val previous = requireNotNull(cache)
            val response = api.worldChanges(previous.snapshot.revision, 500)
            owners.requireActive(binding)
            when (response) {
                is ApiResult.Failure -> {
                    val invalid = response.error is TransportError.WorldResync || response.error is TransportError.Decode ||
                        (response.error is TransportError.Problem && response.error.httpStatus == 409) ||
                        (response.error is TransportError.UnexpectedHttp && response.error.httpStatus == 409)
                    return@withLock if (invalid) snapshot(true) else WorldRead(cache, error = response.error)
                }
                is ApiResult.Success -> {
                    try {
                        require(response.httpStatus == 200)
                        val page = M6Contract.delta(response.value)
                        cache = store.applyDelta(binding, previous.stamp, page, clock())
                        if (!page.hasMore) return@withLock WorldRead(cache, fresh = true)
                    } catch (_: IllegalArgumentException) { return@withLock snapshot(true) }
                }
            }
        }
        WorldRead(cache, fresh = true, more = true)
    }
}
