package app.embyr.core.model

/** Applies complete public replacements; the store commits objects and cursor together. */
object WorldReducer {
    fun apply(current: WorldSnapshotDto, page: WorldDeltaPageDto): WorldSnapshotDto {
        M6Contract.snapshot(current)
        M6Contract.delta(page)
        require(page.fromRevision == current.revision) { "Noncontiguous World page" }
        val regions = current.regions.associateBy { it.id }.toMutableMap()
        val nodes = current.nodes.associateBy { it.id }.toMutableMap()
        page.changes.forEach { change ->
            when (val payload = change.payload) {
                is RegionPayloadDto -> {
                    require(change.type == "REGION_ADDED" && regions.isEmpty())
                    regions[payload.`object`.id] = payload.`object`
                }
                is NodePayloadDto -> {
                    val next = payload.`object`
                    require(next.regionId in regions)
                    when (change.type) {
                        "NODE_ADDED" -> {
                            require(next.id !in nodes && nodes.values.none { it.entityId == next.entityId })
                            nodes[next.id] = next
                        }
                        "NODE_GROWTH_CHANGED" -> {
                            val previous = requireNotNull(nodes[next.id])
                            require(previous.copy(growthState = next.growthState, revision = next.revision) == next)
                            require(previous.growthState != next.growthState)
                            nodes[next.id] = next
                        }
                        else -> throw IllegalArgumentException("Unsupported World change")
                    }
                }
            }
        }
        return M6Contract.snapshot(current.copy(
            revision = page.toRevision,
            regions = regions.values.sortedWith(compareBy<WorldRegionDto> { it.regionKey }.thenBy { it.id }),
            nodes = nodes.values.sortedWith(compareBy<WorldNodeDto> { it.entityId }.thenBy { it.id }),
        ))
    }
}
