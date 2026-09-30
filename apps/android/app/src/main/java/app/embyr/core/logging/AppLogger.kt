package app.embyr.core.logging

import android.util.Log

enum class LogCategory { AUTH, NETWORK, STORAGE, SHELL }
enum class RetryCategory { NONE, REFRESH, EXACT_REPLAY, EXPIRED }
enum class RouteId { BOOTSTRAP, PROFILE, RECOMMENDATION_NEXT, ASSESSMENT_ANSWER, WORLD, WORLD_CHANGES }

data class LogEvent(
    val category: LogCategory,
    val routeId: RouteId? = null,
    val status: Int? = null,
    val requestId: String? = null,
    val durationMs: Long? = null,
    val retry: RetryCategory = RetryCategory.NONE,
)

interface AppLogger {
    fun record(event: LogEvent)
}

/** Deliberately has no body, token, exception-message, or arbitrary-message argument. */
class AndroidAppLogger : AppLogger {
    override fun record(event: LogEvent) {
        Log.i("Embyr", SafeLogFormatter.format(event))
    }
}

object SafeLogFormatter {
    fun format(event: LogEvent): String {
        val requestId = event.requestId?.takeIf {
            it.matches(Regex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"))
        }
        return listOfNotNull(
            event.category.name,
            event.routeId?.let { "route=${it.name}" },
            event.status?.takeIf { it in 100..599 }?.let { "status=$it" },
            requestId?.let { "request_id=$it" },
            event.durationMs?.takeIf { it >= 0 }?.let { "duration_ms=$it" },
            "retry=${event.retry.name}",
        ).joinToString(" ")
    }
}
