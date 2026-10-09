package app.embyr.core.model

import java.time.Instant

/** Closed public v1 semantics. Validating a read never derives learner state. */
object M6Contract {
    const val MAX_REVISION = 2147483647L
    val preferences = setOf("NEUTRAL", "MORE", "LESS", "PAUSED", "NOT_INTERESTED")
    private val uuid = Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    private val seed = Regex("[0-9a-f]{64}")
    fun id(value: String) { require(uuid.matches(value)) { "Invalid public identifier" } }
    private fun time(value: String): Instant {
        require(value.endsWith('Z'))
        return try { Instant.parse(value) } catch (_: java.time.format.DateTimeParseException) {
            throw IllegalArgumentException("Invalid public timestamp")
        }
    }
    private fun title(value: String) { require(value.isNotEmpty() && value.codePointCount(0,value.length) <= 512) }
    private fun revision(value: Long) { require(value in 0..MAX_REVISION) }

    fun memory(value: MemorySummaryDto): MemorySummaryDto = value.also { m ->
        require(m.contractVersion == "memory-summary/v1")
        val p = m.projection
        require(p.modelVersion == "learner-projection/v1" && p.sourceSequence >= 0 && p.sourceSequence <= p.sourceHeadSequence)
        require(p.status in setOf("CURRENT", "PENDING", "FAILED"))
        require((p.status == "CURRENT") == (p.sourceSequence == p.sourceHeadSequence))
        m.learningPreferences?.let {
            require(it.version > 0)
            listOf(it.adventurePreference,it.preferredEffort,it.supportStyle).forEach { s -> require(s.isNotEmpty() && s.codePointCount(0,s.length) <= 64) }
        }
        require(m.explicitInterests.size <= 20 && m.explicitInterests.map { it.entityId }.distinct().size == m.explicitInterests.size)
        m.explicitInterests.forEach {
            id(it.entityId); require(it.version > 0 && it.preference in preferences); time(it.updatedAt)
            when(it.availability) {
                "AVAILABLE" -> { require(it.entityVersion != null && it.entityVersion > 0 && it.title != null); title(it.title) }
                "UNAVAILABLE" -> require(it.entityVersion == null && it.title == null)
                else -> throw IllegalArgumentException("Unsupported availability")
            }
        }
        require(m.explicitInterests == m.explicitInterests.sortedWith(compareByDescending<ExplicitInterestDto> { time(it.updatedAt) }.thenBy { it.entityId }))
        require(m.recentlyExplored.size <= 10 && m.recentlyExplored.map { it.entityId to it.entityVersion }.distinct().size == m.recentlyExplored.size)
        m.recentlyExplored.forEach {
            id(it.entityId); require(it.entityVersion > 0 && it.startedCount > 0 && it.returnedCount >= 0 && it.completedCount in 0..it.startedCount)
            title(it.title); time(it.latestActivityAt)
        }
        require(m.recentlyExplored == m.recentlyExplored.sortedWith(compareByDescending<RecentExplorationDto> { time(it.latestActivityAt) }.thenBy { it.entityId }.thenBy { it.entityVersion }))
        require(m.recognitionEvidence.size <= 10 && m.recognitionEvidence.map { it.objectiveId }.distinct().size == m.recognitionEvidence.size)
        m.recognitionEvidence.forEach {
            id(it.objectiveId); id(it.entityId); require(it.entityVersion > 0 && it.evidenceCount > 0)
            require(it.summary == "Recognition evidence recorded."); time(it.lastEvidenceAt)
        }
        require(m.recognitionEvidence == m.recognitionEvidence.sortedWith(compareByDescending<RecognitionEvidenceDto> { time(it.lastEvidenceAt) }.thenBy { it.objectiveId }))
        require(m.longTermInterests.isEmpty() && m.voluntaryRevisits.isEmpty())
        require(!m.truncated.explicitInterests || m.explicitInterests.size == 20)
        require(!m.truncated.recentlyExplored || m.recentlyExplored.size == 10)
        require(!m.truncated.recognitionEvidence || m.recognitionEvidence.size == 10)
    }

    fun region(r: WorldRegionDto) {
        id(r.id); require(r.regionKey == "discovery" && r.primaryDomainId == null && r.logicalX == 0 && r.logicalY == 0 && r.logicalWidth == 1 && r.logicalHeight == 1 && r.visualArchetype == "grove")
    }
    fun node(n: WorldNodeDto) {
        id(n.id); id(n.entityId); id(n.regionId)
        require(n.entityVersion > 0 && n.depth == 0 && n.visualArchetype == "branching_tree")
        require(n.logicalX.isFinite() && n.logicalX in 0.0..1.0 && n.logicalY.isFinite() && n.logicalY in 0.0..1.0)
        require(seed.matches(n.visualSeed) && n.growthState in setOf("SEED","SPROUT","YOUNG") && n.revision in 1..MAX_REVISION)
    }
    fun snapshot(value: WorldSnapshotDto): WorldSnapshotDto = value.also { w ->
        revision(w.revision); require(w.layoutVersion == 1 && seed.matches(w.generationSeed))
        require(w.connections.isEmpty() && w.artifacts.isEmpty() && w.regions.size <= 1)
        w.regions.forEach(::region); w.nodes.forEach(::node)
        require(w.nodes.map { it.id }.distinct().size == w.nodes.size && w.nodes.map { it.entityId }.distinct().size == w.nodes.size)
        val regions = w.regions.map { it.id }.toSet()
        require(w.nodes.all { it.regionId in regions && it.revision <= w.revision })
        require(w.regions == w.regions.sortedWith(compareBy<WorldRegionDto> { it.regionKey }.thenBy { it.id }))
        require(w.nodes == w.nodes.sortedWith(compareBy<WorldNodeDto> { it.entityId }.thenBy { it.id }))
    }
    fun delta(value: WorldDeltaPageDto): WorldDeltaPageDto = value.also { p ->
        revision(p.fromRevision); revision(p.toRevision); revision(p.currentRevision)
        require(p.fromRevision <= p.toRevision && p.toRevision <= p.currentRevision && p.hasMore == (p.toRevision < p.currentRevision))
        require(p.changes.size <= 1000 && p.toRevision - p.fromRevision == p.changes.size.toLong())
        require(p.changes.isNotEmpty() || p.fromRevision == p.currentRevision)
        p.changes.forEachIndexed { i, c ->
            id(c.objectId); require(c.revision == p.fromRevision+i+1L)
            when(val payload = c.payload) {
                is RegionPayloadDto -> { require(c.type == "REGION_ADDED" && payload.schemaVersion == "world-delta/v1" && payload.`object`.id == c.objectId); region(payload.`object`) }
                is NodePayloadDto -> { require(c.type in setOf("NODE_ADDED","NODE_GROWTH_CHANGED") && payload.schemaVersion == "world-delta/v1" && payload.`object`.id == c.objectId && payload.`object`.revision == c.revision); node(payload.`object`) }
            }
        }
    }
    fun resync(value: WorldResyncRequiredDto): WorldResyncRequiredDto = value.also {
        require(it.type == "about:blank" && it.title == "World resync required" && it.status == 409 && it.code == "WORLD_RESYNC_REQUIRED")
        require(it.detail == "Fetch the World snapshot before requesting further changes.")
        id(it.requestId); require(it.details.afterRevision >= 0); revision(it.details.currentRevision)
    }
}
