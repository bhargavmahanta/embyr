package app.embyr.feature.assessment

import kotlinx.coroutines.delay
import kotlinx.coroutines.withTimeoutOrNull

enum class PollEnd { TERMINAL, BUDGET, OFFLINE }
/** One foreground caller; cancellation belongs to the owner/lifecycle coordinator. */
class AssessmentPoller(
    private val now: () -> Long = System::currentTimeMillis,
    private val wait: suspend (Long) -> Unit = { delay(it) },
) {
    suspend fun poll(online: () -> Boolean, readTerminal: suspend () -> Boolean): PollEnd {
        val started = now()
        for (attempt in 0 until 8) {
            if (!online()) return PollEnd.OFFLINE
            val elapsed = now() - started
            if (elapsed !in 0 until 60000) return PollEnd.BUDGET
            val terminal = withTimeoutOrNull(60000 - elapsed) { readTerminal() } ?: return PollEnd.BUDGET
            if (terminal) return PollEnd.TERMINAL
            if (attempt < 7) {
                val pause = minOf(1000L shl minOf(attempt,3), 60000 - (now() - started))
                if (pause <= 0) return PollEnd.BUDGET
                wait(pause)
            }
        }
        return PollEnd.BUDGET
    }
}
