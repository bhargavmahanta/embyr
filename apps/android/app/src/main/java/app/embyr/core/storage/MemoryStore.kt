package app.embyr.core.storage

import androidx.room.*
import app.embyr.auth.OwnerBinding
import app.embyr.auth.OwnerSession
import app.embyr.core.model.*
import kotlinx.serialization.json.Json

@Entity(tableName = "memory_cache", primaryKeys = ["ownerId"])
data class MemoryCacheEntity(val ownerId: String, val summaryJson: String, val fetchedAtEpochMs: Long)

/** A PUT is an observed-version intent, never an idempotent POST command. */
@Entity(tableName = "interest_operations", primaryKeys = ["id"], indices = [Index(value = ["ownerId", "createdAtEpochMs"])])
data class InterestOperationEntity(
    val id: String, val ownerId: String, val entityId: String, val baseVersion: Long,
    val preference: String, val canonicalPayload: ByteArray, val createdAtEpochMs: Long,
    val state: String = "UNCERTAIN", val acknowledgedVersion: Long? = null,
)

@Dao interface MemoryDao {
    @Query("SELECT * FROM memory_cache WHERE ownerId = :owner") suspend fun cache(owner: String): MemoryCacheEntity?
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun putCache(row: MemoryCacheEntity)
    @Insert(onConflict = OnConflictStrategy.ABORT) suspend fun insertOperation(row: InterestOperationEntity)
    @Query("SELECT * FROM interest_operations WHERE ownerId = :owner AND state IN ('UNCERTAIN','CONFLICT','REJECTED') ORDER BY createdAtEpochMs, id")
    suspend fun unresolved(owner: String): List<InterestOperationEntity>
    @Query("SELECT * FROM interest_operations WHERE ownerId = :owner AND id = :id") suspend fun operation(owner: String, id: String): InterestOperationEntity?
    @Query("UPDATE interest_operations SET state = :state, acknowledgedVersion = :version WHERE ownerId = :owner AND id = :id")
    suspend fun resolve(owner: String, id: String, state: String, version: Long?): Int
}

interface MemoryStore {
    suspend fun cache(binding: OwnerBinding): MemoryCacheEntity?
    suspend fun putCache(binding: OwnerBinding, summary: MemorySummaryDto, time: Long)
    suspend fun insert(binding: OwnerBinding, row: InterestOperationEntity)
    suspend fun unresolved(binding: OwnerBinding): List<InterestOperationEntity>
    suspend fun operation(binding: OwnerBinding, id: String): InterestOperationEntity?
    suspend fun resolve(binding: OwnerBinding, id: String, state: String, version: Long? = null)
}

object M6Json { val codec = Json { ignoreUnknownKeys = false } }
fun MemoryCacheEntity.summary(): MemorySummaryDto = M6Contract.memory(M6Json.codec.decodeFromString(MemorySummaryDto.serializer(), summaryJson))

class RoomMemoryStore(private val database: EmbyrDatabase, private val owners: OwnerSession) : MemoryStore {
    private val dao = database.memoryDao()
    private suspend fun <T> guarded(binding: OwnerBinding, block: suspend () -> T): T = database.withTransaction {
        owners.requireActive(binding)
        val result = block()
        owners.requireActive(binding)
        result
    }
    override suspend fun cache(binding: OwnerBinding) = guarded(binding) { dao.cache(binding.ownerId)?.also { require(it.ownerId == binding.ownerId) } }
    override suspend fun putCache(binding: OwnerBinding, summary: MemorySummaryDto, time: Long) = guarded(binding) {
        M6Contract.memory(summary)
        dao.putCache(MemoryCacheEntity(binding.ownerId, M6Json.codec.encodeToString(MemorySummaryDto.serializer(), summary), time))
    }
    override suspend fun insert(binding: OwnerBinding, row: InterestOperationEntity) = guarded(binding) {
        require(row.ownerId == binding.ownerId)
        dao.insertOperation(row)
    }
    override suspend fun unresolved(binding: OwnerBinding) = guarded(binding) { dao.unresolved(binding.ownerId) }
    override suspend fun operation(binding: OwnerBinding, id: String) = guarded(binding) { dao.operation(binding.ownerId, id) }
    override suspend fun resolve(binding: OwnerBinding, id: String, state: String, version: Long?) = guarded(binding) {
        check(dao.resolve(binding.ownerId, id, state, version) == 1)
    }
}
