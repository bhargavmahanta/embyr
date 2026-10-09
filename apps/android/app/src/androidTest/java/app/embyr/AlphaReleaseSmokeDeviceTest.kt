package app.embyr

import android.content.pm.ApplicationInfo
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assume.assumeTrue
import org.junit.Test

/** Feasibility gate for same-signature instrumentation on the actual Alpha release. */
class AlphaReleaseSmokeDeviceTest {
    @Test fun nonDebuggableAlphaLauncherCanBeInstrumented() {
        val target = InstrumentationRegistry.getInstrumentation().targetContext
        assumeTrue("Release-only gate; debug runs do not establish release evidence", target.packageName == "app.embyr.alpha")
        assertEquals("app.embyr.alpha", target.packageName)
        assertFalse(target.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0)
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                assertEquals("app.embyr.alpha", activity.packageName)
                assertFalse(activity.isFinishing)
            }
        }
    }
}
