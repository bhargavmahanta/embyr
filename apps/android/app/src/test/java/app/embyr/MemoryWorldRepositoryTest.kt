package app.embyr

import app.embyr.auth.*
import app.embyr.core.model.*
import app.embyr.core.network.*
import app.embyr.core.storage.*
import app.embyr.feature.memory.MemoryRepository
import app.embyr.feature.world.WorldRepository
import java.io.File
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.*
import org.junit.Test

object M6Fixtures {
    private val values = run {
        val root = generateSequence(File(requireNotNull(System.getProperty("user.dir"))).canonicalFile) { it.parentFile }
            .first { File(it,"docs/api/fixtures/m6-v1.json").isFile }
        Json.parseToJsonElement(File(root,"docs/api/fixtures/m6-v1.json").readText()).jsonObject.getValue("public_examples").jsonObject
    }
    fun memory(name: String = "memory_current") = Json.decodeFromJsonElement(MemorySummaryDto.serializer(), values.getValue(name))
    fun world(name: String = "world_empty") = Json.decodeFromJsonElement(WorldSnapshotDto.serializer(), values.getValue(name))
    fun page(name: String) = Json.decodeFromJsonElement(WorldDeltaPageDto.serializer(), values.getValue(name))
}

class MemoryWorldRepositoryTest {
    @Test fun ambiguousPutPersistsExactIntentAndMatchingReadIsNotAcknowledgment() = runBlocking {
        val owners = OwnerSession().apply { switchTo("a") }; val binding = owners.capture()
        val store = TestMemoryStore(owners); val api = ProjectionApi(); val repository = MemoryRepository(api, owners, store)
        val first = repository.refresh(binding)
        val choice = first.summary!!.explicitInterests.first()
        api.put = { id, bytes ->
            val operation = store.rows.values.single()
            assertArrayEquals(bytes, operation.canonicalPayload) // Must exist before network dispatch.
            val intent = Json.decodeFromString(InterestPutDto.serializer(), bytes.decodeToString())
            assertEquals(choice.version, intent.baseVersion)
            api.memory = api.memory.copy(explicitInterests = api.memory.explicitInterests.map {
                if (it.entityId == id) it.copy(preference = intent.preference, version = it.version + 1) else it
            })
            ApiResult.Failure(TransportError.AmbiguousTimeout)
        }
        val uncertain = repository.put(binding, choice, "LESS")
        assertEquals("UNCERTAIN", uncertain.operations.single().state)
        assertEquals("LESS", uncertain.summary!!.explicitInterests.first().preference)
        val restored = MemoryRepository(api, owners, store)
        restored.cached(binding); restored.refresh(binding); restored.refresh(binding)
        assertEquals(1, api.putCalls)
        assertEquals("UNCERTAIN", store.rows.values.single().state)
        val adopted = restored.adoptCurrent(binding, store.rows.values.single().id)
        assertTrue(adopted.operations.isEmpty())
        assertEquals("ADOPTED", store.rows.values.single().state)
        assertEquals(1, api.putCalls)
    }
    @Test fun conflictRequiresExplicitNewOperationAgainstObservedVersion() = runBlocking {
        val owners = OwnerSession().apply { switchTo("a") }; val binding = owners.capture()
        val store = TestMemoryStore(owners); val api = ProjectionApi(); val repository = MemoryRepository(api, owners, store)
        val observed = repository.refresh(binding).summary!!.explicitInterests.first()
        api.put = { _, _ -> ApiResult.Failure(TransportError.Problem(409, ProblemDetails(code = "VERSION_CONFLICT"))) }
        val conflict = repository.put(binding, observed, "PAUSED").operations.single()
        assertEquals("CONFLICT", conflict.state)
        repository.refresh(binding)
        assertEquals(1, api.putCalls)
        api.memory = api.memory.copy(explicitInterests = api.memory.explicitInterests.map {
            if (it.entityId == observed.entityId) it.copy(version = observed.version + 2) else it
        })
        api.put = { id, payload ->
            val body = Json.decodeFromString(InterestPutDto.serializer(), payload.decodeToString())
            assertEquals(observed.version + 2, body.baseVersion)
            assertEquals("PAUSED", body.preference)
            ApiResult.Success(InterestResultDto(id, body.preference, body.baseVersion + 1), 200)
        }
        repository.applySaved(binding, conflict.id)
        assertEquals(2, api.putCalls)
        assertEquals(2, store.rows.size)
        assertEquals("REPLACED", store.rows.getValue(conflict.id).state)
        assertEquals("ACKNOWLEDGED", store.rows.values.last().state)
    }
    @Test fun missingBoundedRowStaysUnresolvedAndNeverInventsBaseZero() = runBlocking {
        val owners = OwnerSession().apply { switchTo("a") }; val binding = owners.capture()
        val store = TestMemoryStore(owners); val api = ProjectionApi(); val repo = MemoryRepository(api, owners, store)
        val observed = repo.refresh(binding).summary!!.explicitInterests.first()
        val operation = repo.put(binding, observed, "MORE").operations.single()
        api.memory = M6Fixtures.memory("memory_empty")
        assertThrows(IllegalArgumentException::class.java) { runBlocking { repo.applySaved(binding, operation.id) } }
        assertThrows(IllegalArgumentException::class.java) { runBlocking { repo.adoptCurrent(binding, operation.id) } }
        assertEquals(1, api.putCalls)
        assertEquals("UNCERTAIN", store.rows.getValue(operation.id).state)
    }
    @Test fun memoryRejectsLateReadAndPutAfterAToBToA() = runBlocking {
        val owners = OwnerSession().apply { switchTo("a") }; val initial = owners.capture()
        val store = TestMemoryStore(owners); val api = ProjectionApi(); val repo = MemoryRepository(api, owners, store)
        val choice = repo.refresh(initial).summary!!.explicitInterests.first()
        api.put = { _, _ -> owners.switchTo("b"); owners.switchTo("a"); ApiResult.Success(InterestResultDto(choice.entityId, "MORE", choice.version + 1), 200) }
        assertThrows(IllegalStateException::class.java) { runBlocking { repo.put(initial, choice, "MORE") } }
        assertEquals("UNCERTAIN", store.rows.values.single().state)
        val rebound = owners.capture()
        assertNotEquals(initial.generation, rebound.generation)
        api.onMemory = { owners.switchTo("b"); owners.switchTo("a") }
        assertThrows(IllegalStateException::class.java) { runBlocking { repo.refresh(rebound) } }
        assertEquals(1, store.cacheWrites)
    }
    @Test fun unavailableChoicePreservesNullTitlePinAndSavedPreference() {
        val summary = M6Fixtures.memory("memory_current")
        val first = summary.explicitInterests.first().copy(availability = "UNAVAILABLE", title = null, entityVersion = null, preference = "NOT_INTERESTED")
        assertEquals(first, M6Contract.memory(summary.copy(explicitInterests = listOf(first))).explicitInterests.single())
        assertThrows(IllegalArgumentException::class.java) { M6Contract.memory(summary.copy(explicitInterests = listOf(first.copy(title = "Guess")))) }
    }
    @Test fun projectionStatusAndSemanticFreshnessRemainIndependent() {
        for (name in listOf("memory_current", "memory_empty", "memory_pending_filtered", "memory_failed")) M6Contract.memory(M6Fixtures.memory(name))
        val current = M6Fixtures.memory()
        assertThrows(IllegalArgumentException::class.java) { M6Contract.memory(current.copy(projection = current.projection.copy(status = "FAILED"))) }
        val invalidTime = current.explicitInterests.first().copy(updatedAt = "nonsenseZ")
        assertThrows(IllegalArgumentException::class.java) { M6Contract.memory(current.copy(explicitInterests = listOf(invalidTime))) }
    }
    @Test fun worldContinuesFromCommittedCursorWhenHeadAdvances() = runBlocking {
        val owners = OwnerSession().apply { switchTo("a") }; val binding = owners.capture()
        val store = TestWorldStore(owners); val api = ProjectionApi(); val repo = WorldRepository(api, owners, store)
        repo.synchronize(binding)
        val second = M6Fixtures.page("delta_page_2").copy(currentRevision = 5, hasMore = true)
        val final = growth(M6Fixtures.world("world_populated"), 5, false)
        val pages = ArrayDeque(listOf(M6Fixtures.page("delta_page_1"), second, final))
        api.changes = { after, limit -> assertEquals(500, limit); val page = pages.removeFirst(); assertEquals(page.fromRevision, after); ApiResult.Success(page, 200) }
        val result = repo.synchronize(binding)
        assertEquals(5L, result.cache!!.snapshot.revision)
        assertTrue(result.fresh); assertFalse(result.more)
        assertEquals(3, api.deltaCalls)
    }
    @Test fun worldBoundsPagingAndOffersContinuation() = runBlocking {
        val owners = OwnerSession().apply { switchTo("a") }; val binding = owners.capture()
        val store = TestWorldStore(owners); val api = ProjectionApi().apply { world = M6Fixtures.world("world_populated") }
        val repo = WorldRepository(api, owners, store); repo.synchronize(binding)
        api.changes = { after, _ -> ApiResult.Success(growth(store.cached!!.snapshot, after + 1, true), 200) }
        val result = repo.synchronize(binding)
        assertEquals(20, api.deltaCalls); assertEquals(24L, result.cache!!.snapshot.revision); assertTrue(result.more)
    }
    @Test fun invalidDeltaRecoversOnceAndInvalidRecoveryRemainsVisible() = runBlocking {
        val owners = OwnerSession().apply { switchTo("a") }; val binding = owners.capture()
        val store = TestWorldStore(owners); val api = ProjectionApi().apply { world = M6Fixtures.world("world_populated") }
        val repo = WorldRepository(api, owners, store); repo.synchronize(binding)
        api.world = api.world.copy(layoutVersion = 2)
        api.changes = { _, _ -> ApiResult.Failure(TransportError.Decode(200)) }
        val result = repo.synchronize(binding)
        assertEquals(2, api.snapshotCalls); assertEquals(1, api.deltaCalls)
        assertNotNull(result.error); assertTrue(result.recovered); assertEquals(4L, result.cache!!.snapshot.revision)
    }
    @Test fun aheadCursorCanRecoverLowerButStaleReplacementCannotCommit() = runBlocking {
        val owners = OwnerSession().apply { switchTo("a") }; val binding = owners.capture()
        val store = TestWorldStore(owners); val api = ProjectionApi().apply { world = M6Fixtures.world("world_populated") }
        val repo = WorldRepository(api, owners, store); val previous = repo.synchronize(binding).cache!!
        api.world = M6Fixtures.world()
        api.changes = { _, _ -> ApiResult.Failure(TransportError.UnexpectedHttp(409,null)) }
        assertEquals(0L, repo.synchronize(binding).cache!!.snapshot.revision)
        assertThrows(IllegalArgumentException::class.java) { runBlocking { store.resync(binding, previous.stamp, api.world, 1) } }
        Unit
    }
    @Test fun worldLateAToBToAResponseAndNetworkFailureNeverLeakOtherOwners() = runBlocking {
        val owners = OwnerSession().apply { switchTo("a") }; val binding = owners.capture()
        val store = TestWorldStore(owners); val api = ProjectionApi(); val repo = WorldRepository(api, owners, store)
        repo.synchronize(binding)
        api.changes = { _, _ -> owners.switchTo("b"); owners.switchTo("a"); ApiResult.Success(M6Fixtures.page("delta_page_1"),200) }
        assertThrows(IllegalStateException::class.java) { runBlocking { repo.synchronize(binding) } }
        assertEquals(0L, store.cached!!.snapshot.revision)
        owners.switchTo("b")
        assertNull(repo.cached(owners.capture()).cache)
    }
    private fun growth(current: WorldSnapshotDto, revision: Long, more: Boolean): WorldDeltaPageDto {
        val first = current.nodes.first()
        val next = first.copy(growthState = if (first.growthState == "YOUNG") "SPROUT" else "YOUNG", revision = revision)
        return WorldDeltaPageDto(revision-1, revision, revision + if(more) 1 else 0, more,
            listOf(WorldChangeDto(revision,"NODE_GROWTH_CHANGED",next.id,NodePayloadDto("world-delta/v1",next))))
    }
}

private class ProjectionApi : EmbyrApi by TestLearningApi() {
    var memory = M6Fixtures.memory(); var world = M6Fixtures.world()
    var putCalls = 0; var snapshotCalls = 0; var deltaCalls = 0
    var onMemory: () -> Unit = {}
    var put: suspend (String, ByteArray) -> ApiResult<InterestResultDto> = { _, _ -> ApiResult.Failure(TransportError.AmbiguousTimeout) }
    var changes: suspend (Long, Int) -> ApiResult<WorldDeltaPageDto> = { after, _ -> ApiResult.Success(WorldDeltaPageDto(after,after,after,false,emptyList()),200) }
    override suspend fun memorySummary(): ApiResult<MemorySummaryDto> { onMemory(); return ApiResult.Success(memory,200) }
    override suspend fun updateInterest(entityId: String, canonicalPayload: ByteArray): ApiResult<InterestResultDto> { putCalls++; return put(entityId,canonicalPayload) }
    override suspend fun world(): ApiResult<WorldSnapshotDto> { snapshotCalls++; return ApiResult.Success(world,200) }
    override suspend fun worldChanges(afterRevision: Long, limit: Int): ApiResult<WorldDeltaPageDto> { deltaCalls++; return changes(afterRevision,limit) }
}
private class TestMemoryStore(private val owners: OwnerSession) : MemoryStore {
    var saved: MemoryCacheEntity? = null; val rows = linkedMapOf<String,InterestOperationEntity>(); var cacheWrites = 0
    override suspend fun cache(binding: OwnerBinding): MemoryCacheEntity? { owners.requireActive(binding); return saved?.takeIf { it.ownerId == binding.ownerId } }
    override suspend fun putCache(binding: OwnerBinding, summary: MemorySummaryDto, time: Long) { owners.requireActive(binding); cacheWrites++; saved = MemoryCacheEntity(binding.ownerId,Json.encodeToString(MemorySummaryDto.serializer(),summary),time) }
    override suspend fun insert(binding: OwnerBinding, row: InterestOperationEntity) { owners.requireActive(binding); rows[row.id] = row }
    override suspend fun unresolved(binding: OwnerBinding): List<InterestOperationEntity> { owners.requireActive(binding); return rows.values.filter { it.ownerId == binding.ownerId && it.state in setOf("UNCERTAIN","CONFLICT","REJECTED") } }
    override suspend fun operation(binding: OwnerBinding, id: String): InterestOperationEntity? { owners.requireActive(binding); return rows[id]?.takeIf { it.ownerId == binding.ownerId } }
    override suspend fun resolve(binding: OwnerBinding, id: String, state: String, version: Long?) { owners.requireActive(binding); rows[id] = rows.getValue(id).copy(state = state,acknowledgedVersion = version) }
}
private class TestWorldStore(private val owners: OwnerSession) : WorldStore {
    private val worlds = mutableMapOf<String,CachedWorld>()
    val cached: CachedWorld? get() = worlds["a"]
    override suspend fun getWorld(ownerId: String) = worlds[ownerId]?.snapshot
    override suspend fun replaceSnapshot(ownerId: String, snapshot: WorldSnapshotDto, committedAtEpochMs: Long) { error("Unused") }
    override suspend fun stamp(binding: OwnerBinding): WorldStamp? { owners.requireActive(binding); return worlds[binding.ownerId]?.stamp }
    override suspend fun read(binding: OwnerBinding): CachedWorld? { owners.requireActive(binding); return worlds[binding.ownerId] }
    override suspend fun applyDelta(binding: OwnerBinding, expected: WorldStamp, page: WorldDeltaPageDto, time: Long): CachedWorld = resync(binding,expected,WorldReducer.apply(requireNotNull(read(binding)).snapshot,page),time)
    override suspend fun resync(binding: OwnerBinding, expected: WorldStamp?, snapshot: WorldSnapshotDto, time: Long): CachedWorld {
        owners.requireActive(binding); require(stamp(binding) == expected); M6Contract.snapshot(snapshot)
        return CachedWorld(snapshot,WorldStamp(snapshot.revision,(expected?.generation ?: 0)+1)).also { worlds[binding.ownerId] = it }
    }
}
