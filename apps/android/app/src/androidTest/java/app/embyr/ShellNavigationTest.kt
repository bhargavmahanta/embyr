package app.embyr

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ShellNavigationTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()

    @Test fun signedOutAndReadyPlaceholdersNavigateWithoutPrivateData() {
        compose.waitUntil(60_000) {
            compose.onAllNodesWithText("Signed out").fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText("Signed out").assertIsDisplayed()
        compose.onNodeWithText("View navigation preview").performScrollTo().performClick()
        compose.onNodeWithText("Shell preview").assertIsDisplayed()
        compose.onNodeWithText("No private learner data is available in this placeholder").assertIsDisplayed()
        compose.onNodeWithText("Back to signed-out placeholder").performScrollTo().performClick()
        compose.waitUntil(10_000) {
            try {
                compose.onNodeWithText("Signed out").assertIsDisplayed()
                true
            } catch (_: AssertionError) {
                false
            }
        }
        compose.onNodeWithText("Signed out").assertIsDisplayed()
    }
}
