package app.embyr

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import app.embyr.core.model.RecommendationDto
import app.embyr.core.model.RecommendationEntityDto
import app.embyr.core.model.StarterInterestDto
import app.embyr.feature.shell.JourneyActions
import app.embyr.feature.shell.JourneyContent
import app.embyr.feature.shell.JourneyScreen
import app.embyr.feature.shell.JourneyUiState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class JourneyComposeTest {
    @get:Rule val compose = createComposeRule()
    private val actions = FakeActions()

    @Test fun signedOutCodeFlowShowsVerificationAndResend() {
        compose.setContent { JourneyContent(JourneyUiState(screen = JourneyScreen.SIGNED_OUT, email = "learner@example.com", awaitingCode = true, code = "123456"), actions) }
        compose.onNodeWithText("Email code").assertIsDisplayed()
        compose.onNodeWithText("Verify code").performClick()
        compose.onNodeWithText("Resend code").performClick()
        assertEquals(listOf("verify", "send"), actions.calls)
    }

    @Test fun onboardingHasOnlyStarterSelectionAndExplicitContinue() {
        compose.setContent {
            JourneyContent(
                JourneyUiState(screen = JourneyScreen.ONBOARDING, starters = listOf(StarterInterestDto("starter", "AREA", 1, "Astronomy", "Explore the sky"))),
                actions,
            )
        }
        compose.onNodeWithTag("starter-starter").performClick()
        compose.onNodeWithText("Continue").performClick()
        assertEquals(listOf("starter:starter", "onboarding:false"), actions.calls)
    }

    @Test fun entryDoesNotGenerateUntilLearnerChoosesMode() {
        compose.setContent { JourneyContent(JourneyUiState(screen = JourneyScreen.ENTRY), actions) }
        compose.onNodeWithText("Ready to explore").assertIsDisplayed()
        assertTrue(actions.calls.isEmpty())
        compose.onNodeWithText("Explore").performClick()
        compose.onNodeWithText("Surprise me").performClick()
        assertEquals(listOf("mode:EXPLORE:false", "mode:SURPRISE:false"), actions.calls)
    }

    @Test fun noResultOffersExplicitAlternativeAndFoundHasSeparateDecisions() {
        val state = mutableStateOf(JourneyUiState(screen = JourneyScreen.RECOMMENDATION, noResult = true))
        compose.setContent { JourneyContent(state.value, actions) }
        compose.onNodeWithText("Nothing fits this mode right now. You can choose another mode whenever you like.").assertIsDisplayed()
        compose.onNodeWithText("Try Surprise").performClick()
        compose.runOnUiThread {
            state.value = JourneyUiState(
                screen = JourneyScreen.RECOMMENDATION,
                recommendation = RecommendationDto("rec", "ENTITY", RecommendationEntityDto("entity", "Astronomy"), null, "EXPLORE", "NEAR", null, null, "2026-10-01T00:00:00Z"),
            )
        }
        compose.onNodeWithText("Astronomy").assertIsDisplayed()
        compose.onNodeWithText("Accept").performClick()
        compose.onNodeWithText("Skip").performClick()
        assertEquals(listOf("mode:SURPRISE:false", "decision:ACCEPT", "decision:SKIP"), actions.calls)
    }

    private class FakeActions : JourneyActions {
        val calls = mutableListOf<String>()
        override fun setEmail(value: String) { calls += "email" }
        override fun setCode(value: String) { calls += "code" }
        override fun sendCode() { calls += "send" }
        override fun verifyCode() { calls += "verify" }
        override fun retryStartup() { calls += "startup" }
        override fun retryStarters() { calls += "starters" }
        override fun toggleStarter(id: String) { calls += "starter:$id" }
        override fun submitOnboarding(explicitNewAfterExpiry: Boolean) { calls += "onboarding:$explicitNewAfterExpiry" }
        override fun refreshEntry() { calls += "refresh" }
        override fun showLatestRecommendation() { calls += "latest" }
        override fun showExplorationReady() { calls += "ready" }
        override fun requestRecommendation(mode: String, explicitNewAfterExpiry: Boolean) { calls += "mode:$mode:$explicitNewAfterExpiry" }
        override fun retryGeneration() { calls += "retry-generation" }
        override fun decide(decision: String) { calls += "decision:$decision" }
        override fun retryDecision() { calls += "retry-decision" }
        override fun backToEntry() { calls += "back" }
        override fun signOut() { calls += "sign-out" }
    }
}
