package app.embyr.core.storage

import app.embyr.auth.OwnerSession
import app.embyr.core.model.RecommendationDto
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

data class JourneySnapshot(
    val selectedStarterIds: List<String> = emptyList(),
    val presentation: RecommendationDto? = null,
    val noResult: Boolean = false,
    val acceptedExplorationId: String? = null,
    val acceptedRecommendationId: String? = null,
    val skippedRecommendationId: String? = null,
)

interface JourneyStore {
    suspend fun read(ownerId: String): JourneySnapshot
    suspend fun saveDraft(ownerId: String, ids: List<String>)
    suspend fun savePresentation(ownerId: String, result: RecommendationDto?)
    suspend fun saveAcceptance(ownerId: String, recommendationId: String, explorationId: String)
    suspend fun saveSkip(ownerId: String, recommendationId: String)
}

class RoomJourneyStore(private val dao: JourneyDao, private val owners: OwnerSession) : JourneyStore {
    private val mutex = Mutex()
    private val json = Json { ignoreUnknownKeys = true }
    private val idsSerializer = ListSerializer(String.serializer())

    override suspend fun read(ownerId: String): JourneySnapshot {
        check(owners.requireOwner() == ownerId)
        return (dao.get(ownerId) ?: JourneyEntity(ownerId)).let { row ->
            JourneySnapshot(
                selectedStarterIds = json.decodeFromString(idsSerializer, row.draftStarterIdsJson),
                presentation = row.presentationJson?.let { json.decodeFromString(RecommendationDto.serializer(), it) },
                noResult = row.noResult,
                acceptedExplorationId = row.acceptedExplorationId,
                acceptedRecommendationId = row.acceptedRecommendationId,
                skippedRecommendationId = row.skippedRecommendationId,
            )
        }
    }

    override suspend fun saveDraft(ownerId: String, ids: List<String>) = update(ownerId) {
        it.copy(draftStarterIdsJson = json.encodeToString(idsSerializer, ids))
    }

    override suspend fun savePresentation(ownerId: String, result: RecommendationDto?) = update(ownerId) {
        it.copy(
            presentationJson = result?.let { dto -> json.encodeToString(RecommendationDto.serializer(), dto) },
            noResult = result == null,
        )
    }

    override suspend fun saveAcceptance(ownerId: String, recommendationId: String, explorationId: String) = update(ownerId) {
        it.copy(
            presentationJson = null, noResult = false,
            acceptedRecommendationId = recommendationId, acceptedExplorationId = explorationId,
        )
    }

    override suspend fun saveSkip(ownerId: String, recommendationId: String) = update(ownerId) {
        it.copy(presentationJson = null, noResult = false, skippedRecommendationId = recommendationId)
    }

    private suspend fun update(ownerId: String, change: (JourneyEntity) -> JourneyEntity) {
        check(owners.requireOwner() == ownerId)
        mutex.withLock {
            dao.put(change(dao.get(ownerId) ?: JourneyEntity(ownerId)))
        }
    }
}
