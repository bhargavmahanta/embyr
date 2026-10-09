package app.embyr.core.storage

import androidx.room.withTransaction
import app.embyr.auth.OwnerBinding
import app.embyr.auth.OwnerSession
import app.embyr.core.model.*
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonElement

/** Generation changes on every cache commit, even when the public revision does not change. */
data class WorldStamp(val revision: Long, val generation: Long)
data class CachedWorld(val snapshot: WorldSnapshotDto, val stamp: WorldStamp)

interface WorldStore {
    suspend fun getWorld(ownerId: String): WorldSnapshotDto?
    suspend fun replaceSnapshot(ownerId: String, snapshot: WorldSnapshotDto, committedAtEpochMs: Long)
    suspend fun stamp(binding: OwnerBinding): WorldStamp?
    suspend fun read(binding: OwnerBinding): CachedWorld?
    suspend fun applyDelta(binding: OwnerBinding, expected: WorldStamp, page: WorldDeltaPageDto, time: Long): CachedWorld
    suspend fun resync(binding: OwnerBinding, expected: WorldStamp?, snapshot: WorldSnapshotDto, time: Long): CachedWorld
}

class RoomWorldStore(private val database: EmbyrDatabase, private val owners: OwnerSession) : WorldStore {
    private val dao = database.worldDao()
    private val json = M6Json.codec
    private suspend fun <T> guarded(binding: OwnerBinding, block: suspend () -> T): T = database.withTransaction {
        owners.requireActive(binding)
        val result = block()
        owners.requireActive(binding)
        result
    }
    private suspend fun currentStamp(owner: String): WorldStamp? = dao.meta(owner)?.let { WorldStamp(it.revision, it.cacheGeneration) }
    override suspend fun stamp(binding: OwnerBinding) = guarded(binding) { currentStamp(binding.ownerId) }
    override suspend fun read(binding: OwnerBinding): CachedWorld? = guarded(binding) { load(binding.ownerId) }
    private suspend fun load(owner: String): CachedWorld? {
        val meta = dao.meta(owner) ?: return null
        val aux = dao.aux(owner) ?: throw IllegalArgumentException("World auxiliary snapshot missing")
        require(meta.ownerId == owner && aux.ownerId == owner && meta.cacheGeneration >= 0)
        val snapshot = WorldSnapshotDto(
            meta.revision, meta.layoutVersion, meta.generationSeed,
            dao.regions(owner).map { row -> json.decodeFromString(WorldRegionDto.serializer(), row.payloadJson).also { require(row.ownerId == owner && row.objectId == it.id) } }
                .sortedWith(compareBy<WorldRegionDto> { it.regionKey }.thenBy { it.id }),
            dao.nodes(owner).map { row -> json.decodeFromString(WorldNodeDto.serializer(), row.payloadJson).also { require(row.ownerId == owner && row.objectId == it.id) } }
                .sortedWith(compareBy<WorldNodeDto> { it.entityId }.thenBy { it.id }),
            json.decodeFromString(ListSerializer(JsonElement.serializer()), aux.connectionsJson),
            json.decodeFromString(ListSerializer(JsonElement.serializer()), aux.artifactsJson),
        )
        return CachedWorld(M6Contract.snapshot(snapshot), WorldStamp(meta.revision, meta.cacheGeneration))
    }
    override suspend fun getWorld(ownerId: String): WorldSnapshotDto? {
        val binding = owners.capture(); check(binding.ownerId == ownerId)
        return read(binding)?.snapshot
    }
    override suspend fun replaceSnapshot(ownerId: String, snapshot: WorldSnapshotDto, committedAtEpochMs: Long) {
        val binding = owners.capture(); check(binding.ownerId == ownerId)
        guarded(binding) {
            val previous = currentStamp(ownerId)
            require(snapshot.revision >= (previous?.revision ?: 0)) { "A stale World snapshot cannot replace a newer revision" }
            write(ownerId, snapshot, previous, committedAtEpochMs)
        }
    }
    override suspend fun applyDelta(binding: OwnerBinding, expected: WorldStamp, page: WorldDeltaPageDto, time: Long): CachedWorld = guarded(binding) {
        require(currentStamp(binding.ownerId) == expected) { "World cache changed" }
        val current = requireNotNull(load(binding.ownerId))
        write(binding.ownerId, WorldReducer.apply(current.snapshot, page), expected, time)
    }
    /** Dedicated CAS recovery permits a legitimate lower revision, never an unguarded replacement. */
    override suspend fun resync(binding: OwnerBinding, expected: WorldStamp?, snapshot: WorldSnapshotDto, time: Long): CachedWorld = guarded(binding) {
        require(currentStamp(binding.ownerId) == expected) { "World cache changed during recovery" }
        write(binding.ownerId, snapshot, expected, time)
    }
    private suspend fun write(owner: String, snapshot: WorldSnapshotDto, previous: WorldStamp?, time: Long): CachedWorld {
        M6Contract.snapshot(snapshot)
        val nextGeneration = Math.addExact(previous?.generation ?: 0L, 1L)
        dao.deleteRegions(owner); dao.deleteNodes(owner)
        dao.putRegions(snapshot.regions.map { WorldRegionEntity(owner, it.id, json.encodeToString(WorldRegionDto.serializer(), it)) })
        dao.putNodes(snapshot.nodes.map { WorldNodeEntity(owner, it.id, json.encodeToString(WorldNodeDto.serializer(), it)) })
        dao.putAux(WorldAuxEntity(owner, json.encodeToString(ListSerializer(JsonElement.serializer()), snapshot.connections), json.encodeToString(ListSerializer(JsonElement.serializer()), snapshot.artifacts)))
        dao.putMeta(WorldMetaEntity(owner, snapshot.revision, snapshot.layoutVersion, snapshot.generationSeed, time, nextGeneration))
        return CachedWorld(snapshot, WorldStamp(snapshot.revision, nextGeneration))
    }
}
