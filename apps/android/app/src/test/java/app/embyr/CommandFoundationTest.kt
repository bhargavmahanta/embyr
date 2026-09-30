package app.embyr

import app.embyr.auth.OwnerSession
import app.embyr.core.storage.CanonicalPayload
import app.embyr.core.storage.CommandDispatcher
import app.embyr.core.storage.CommandEntity
import app.embyr.core.storage.CommandOutbox
import app.embyr.core.storage.CommandState
import app.embyr.core.storage.ReplayWindow
import app.embyr.core.storage.TransmissionOutcome
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.launch
import kotlinx.coroutines.yield
import kotlinx.serialization.Serializable
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CommandFoundationTest {
    @Serializable private data class Payload(val z: Int, val a: String? = null, val nested: Nested = Nested(3, 2))
    @Serializable private data class Nested(val y: Int, val x: Int)

    @Test fun canonicalPayloadHasSortedKeysExplicitNullAndDefaults() {
        assertEquals(
            "{\"a\":null,\"nested\":{\"x\":2,\"y\":3},\"z\":1}",
            CanonicalPayload.encode(Payload.serializer(), Payload(1)).toString(Charsets.UTF_8),
        )
    }

    @Test fun persistBeforeSendAndExactRetry() = runBlocking {
        val outbox = MemoryOutbox()
        val owners = OwnerSession().apply { switchTo("owner-a") }
        val dispatcher = CommandDispatcher(outbox, owners)
        var original: CommandEntity? = null
        val result = dispatcher.persistThenSend("owner-a", "POST", "api/v1/recommendations/next", Payload.serializer(), Payload(1), 1000) {
            original = it
            assertTrue(outbox.commands.containsKey(it.id))
            TransmissionOutcome.Ambiguous
        }
        assertEquals(CommandState.AMBIGUOUS.name, result.state)
        val first = requireNotNull(original)
        val state = dispatcher.retry("owner-a", first.id, 2000) {
            assertEquals(first.idempotencyKey, it.idempotencyKey)
            assertEquals(first.relativeRoute, it.relativeRoute)
            assertArrayEquals(first.canonicalPayload, it.canonicalPayload)
            TransmissionOutcome.Acknowledged("result-1")
        }
        assertEquals(CommandState.ACKNOWLEDGED, state)
        assertEquals("result-1", outbox.get("owner-a", first.id)?.knownResultReference)
        assertEquals(null, outbox.get("owner-b", first.id))
    }

    @Test fun expiredAmbiguityNeverSends() = runBlocking {
        val outbox = MemoryOutbox()
        val command = CommandEntity("id", "owner-a", "POST", "api/v1/test", byteArrayOf(1), "key", 1000, "AMBIGUOUS")
        outbox.enqueue(command)
        val owners = OwnerSession().apply { switchTo("owner-a") }
        val dispatcher = CommandDispatcher(outbox, owners)
        val result = dispatcher.retry("owner-a", "id", 1000 + ReplayWindow.SAFE_WINDOW_MS) {
            error("Expired command was sent")
        }
        assertEquals(CommandState.EXPIRED, result)
        assertEquals(CommandState.EXPIRED, dispatcher.retry("owner-a", "id", 1001) { error("Expired command was revived") })
        assertFalse(ReplayWindow.mayReplay(1000, 1000 + ReplayWindow.SAFE_WINDOW_MS))
    }

    @Test fun ownerTransitionCancelsOldOwnerWork() = runBlocking {
        val owners = OwnerSession().apply { switchTo("owner-a") }
        val work = owners.scopeFor("owner-a").launch { awaitCancellation() }
        owners.switchTo("owner-b")
        work.join()
        assertTrue(work.isCancelled)
        assertEquals("owner-b", owners.requireOwner())
    }

    @Test fun concurrentRetriesCannotOverwriteAcknowledgment() = runBlocking {
        val outbox = MemoryOutbox()
        val owners = OwnerSession().apply { switchTo("owner-a") }
        outbox.enqueue(CommandEntity("id", "owner-a", "POST", "api/v1/test", byteArrayOf(1), "key", 1000, "AMBIGUOUS"))
        val firstStarted = CompletableDeferred<Unit>()
        val releaseFirst = CompletableDeferred<Unit>()
        val first = async {
            CommandDispatcher(outbox, owners).retry("owner-a", "id", 2000) {
                firstStarted.complete(Unit)
                releaseFirst.await()
                TransmissionOutcome.Acknowledged("known-result")
            }
        }
        firstStarted.await()
        val second = async {
            CommandDispatcher(outbox, owners).retry("owner-a", "id", 2000) {
                error("A concurrent retry transmitted after acknowledgment")
            }
        }
        yield()
        assertFalse(second.isCompleted)
        releaseFirst.complete(Unit)
        assertEquals(CommandState.ACKNOWLEDGED, first.await())
        assertEquals(CommandState.ACKNOWLEDGED, second.await())
        assertEquals("known-result", outbox.get("owner-a", "id")?.knownResultReference)
        assertEquals(1, outbox.get("owner-a", "id")?.attempts)
    }

    private class MemoryOutbox : CommandOutbox {
        val commands = mutableMapOf<String, CommandEntity>()
        override suspend fun enqueue(command: CommandEntity) { commands[command.id] = command }
        override suspend fun get(ownerId: String, id: String) = commands[id]?.takeIf { it.ownerId == ownerId }
        override suspend fun unresolved(ownerId: String) = commands.values.filter { it.ownerId == ownerId && it.state != "ACKNOWLEDGED" }
        override suspend fun mark(ownerId: String, id: String, state: CommandState, resultReference: String?) {
            val current = requireNotNull(get(ownerId, id))
            commands[id] = current.copy(state = state.name, knownResultReference = resultReference)
        }
        override suspend fun markAttempt(ownerId: String, id: String, nowEpochMs: Long) {
            val current = requireNotNull(get(ownerId, id))
            commands[id] = current.copy(state = "IN_FLIGHT", attempts = current.attempts + 1, lastAttemptAtEpochMs = nowEpochMs)
        }
    }
}
