package app.embyr.core.storage

import androidx.room.withTransaction
import app.embyr.auth.OwnerSession
import app.embyr.core.model.WorldNodeDto
import app.embyr.core.model.WorldRegionDto
import app.embyr.core.model.WorldSnapshotDto
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement

interface WorldStore {
    suspend fun getWorld(ownerId: String): WorldSnapshotDto?
    suspend fun replaceSnapshot(ownerId: String, snapshot: WorldSnapshotDto, committedAtEpochMs: Long)
}

class RoomWorldStore(private val database: EmbyrDatabase, private val owners: OwnerSession) : WorldStore {
    private val dao = database.worldDao()
    private val json = Json { ignoreUnknownKeys = false }

    override suspend fun getWorld(ownerId: String): WorldSnapshotDto? {
        check(owners.requireOwner() == ownerId)
        val snapshot = database.withTransaction {
            val meta = dao.meta(ownerId) ?: return@withTransaction null
            val aux = dao.aux(ownerId) ?: error("World auxiliary snapshot missing")
            WorldSnapshotDto(
                revision = meta.revision,
                layoutVersion = meta.layoutVersion,
                generationSeed = meta.generationSeed,
                regions = dao.regions(ownerId).map { json.decodeFromString(WorldRegionDto.serializer(), it.payloadJson) },
                nodes = dao.nodes(ownerId).map { json.decodeFromString(WorldNodeDto.serializer(), it.payloadJson) },
                connections = json.decodeFromString(ListSerializer(JsonElement.serializer()), aux.connectionsJson),
                artifacts = json.decodeFromString(ListSerializer(JsonElement.serializer()), aux.artifactsJson),
            )
        }
        check(owners.requireOwner() == ownerId)
        return snapshot
    }

    override suspend fun replaceSnapshot(ownerId: String, snapshot: WorldSnapshotDto, committedAtEpochMs: Long) {
        require(ownerId.isNotBlank())
        check(owners.requireOwner() == ownerId)
        require(snapshot.revision >= 0)
        database.withTransaction {
            require(snapshot.revision >= (dao.meta(ownerId)?.revision ?: 0L)) {
                "A stale World snapshot cannot replace a newer revision"
            }
            dao.deleteRegions(ownerId)
            dao.deleteNodes(ownerId)
            dao.putRegions(snapshot.regions.map {
                WorldRegionEntity(ownerId, it.id, json.encodeToString(WorldRegionDto.serializer(), it))
            })
            dao.putNodes(snapshot.nodes.map {
                WorldNodeEntity(ownerId, it.id, json.encodeToString(WorldNodeDto.serializer(), it))
            })
            dao.putAux(
                WorldAuxEntity(
                    ownerId,
                    json.encodeToString(ListSerializer(JsonElement.serializer()), snapshot.connections),
                    json.encodeToString(ListSerializer(JsonElement.serializer()), snapshot.artifacts),
                ),
            )
            dao.putMeta(
                WorldMetaEntity(
                    ownerId,
                    snapshot.revision,
                    snapshot.layoutVersion,
                    snapshot.generationSeed,
                    committedAtEpochMs,
                ),
            )
        }
    }
}
