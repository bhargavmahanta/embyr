package app.embyr.core.storage

import androidx.room.Entity
import androidx.room.Index

@Entity(
    tableName = "commands",
    primaryKeys = ["id"],
    indices = [
        Index(value = ["ownerId", "idempotencyKey"], unique = true),
        Index(value = ["ownerId", "state", "createdAtEpochMs"]),
        Index(value = ["state"]),
        Index(value = ["createdAtEpochMs"]),
    ],
)
data class CommandEntity(
    val id: String,
    val ownerId: String,
    val method: String,
    val relativeRoute: String,
    val canonicalPayload: ByteArray,
    val idempotencyKey: String,
    val createdAtEpochMs: Long,
    val state: String,
    val knownResultReference: String? = null,
    val attempts: Int = 0,
    val lastAttemptAtEpochMs: Long? = null,
)

@Entity(tableName = "world_meta", primaryKeys = ["ownerId"])
data class WorldMetaEntity(
    val ownerId: String,
    val revision: Long,
    val layoutVersion: Int,
    val generationSeed: String,
    val committedAtEpochMs: Long,
)

@Entity(tableName = "world_regions", primaryKeys = ["ownerId", "objectId"])
data class WorldRegionEntity(val ownerId: String, val objectId: String, val payloadJson: String)

@Entity(tableName = "world_nodes", primaryKeys = ["ownerId", "objectId"])
data class WorldNodeEntity(val ownerId: String, val objectId: String, val payloadJson: String)

@Entity(tableName = "world_aux", primaryKeys = ["ownerId"])
data class WorldAuxEntity(
    val ownerId: String,
    val connectionsJson: String,
    val artifactsJson: String,
)
