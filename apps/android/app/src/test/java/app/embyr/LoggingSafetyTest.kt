package app.embyr

import app.embyr.core.logging.LogCategory
import app.embyr.core.logging.LogEvent
import app.embyr.core.logging.RetryCategory
import app.embyr.core.logging.RouteId
import app.embyr.core.logging.SafeLogFormatter
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LoggingSafetyTest {
    @Test fun malformedRequestIdCannotSmuggleSecretsIntoLogs() {
        val output = SafeLogFormatter.format(
            LogEvent(
                category = LogCategory.NETWORK,
                routeId = RouteId.WORLD,
                status = 409,
                requestId = "Bearer secret-token refresh-token private-reflection",
                retry = RetryCategory.EXACT_REPLAY,
            ),
        )
        assertTrue(output.contains("route=WORLD status=409"))
        assertFalse(output.contains("secret-token"))
        assertFalse(output.contains("private-reflection"))
    }
}
