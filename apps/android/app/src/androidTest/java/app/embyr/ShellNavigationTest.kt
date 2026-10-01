package app.embyr

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.assertTrue
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ShellNavigationTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()

    @Test fun signedOutShowsEmailCodeEntryWithoutPrivateLearnerData() {
        compose.waitUntil(60_000) {
            compose.onAllNodesWithText("Sign in").fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText("Sign in").assertIsDisplayed()
        compose.onNodeWithText("Email address").performTextInput("learner@example.com")
        compose.onNodeWithText("Send code").assertIsDisplayed()
        assertTrue(compose.onAllNodesWithText("Ready to explore").fetchSemanticsNodes().isEmpty())
    }
}
