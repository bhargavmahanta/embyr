package app.embyr

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.runtime.mutableStateOf
import app.embyr.feature.assessment.*
import app.embyr.feature.exploration.*
import app.embyr.core.model.*
import org.junit.Rule
import org.junit.Test

class LearningComposeTest {
    @get:Rule val compose = createComposeRule()
    private fun session() = AssessmentSessionDto("session","exploration","WAITING_FOR_EVALUATION","FUZZY","assessment-strategy/v1",InteractionDto("interaction","RECOGNITION","Reviewed question","v1","v1","v1","v1",listOf(AssessmentOptionDto("option","Reviewed option"))),emptyList(),"response",null,"PENDING",null,false)
    private fun response(status: String, retry: Boolean) = AssessmentResponseDto("response","session","WAITING_FOR_EVALUATION",null,"run",status,null,null,"Public feedback",if(status == "FAILED") "PROCESSING_UNAVAILABLE" else null,retry)
    @Test fun failedEvaluationOverridesWaitingSessionAndNoneligibleRetryIsHidden() {
        compose.setContent { AssessmentScreen(AssessmentUiState(owner = "a",session = session(),response = response("FAILED",false),responseId = "response"),{}, {}, {}, {}, {}) }
        compose.onNodeWithText("Evaluation failed").assertIsDisplayed()
        compose.onNodeWithText("Retry evaluation").assertDoesNotExist()
        compose.onNodeWithText("Evaluation pending. Recheck when ready.").assertDoesNotExist()
    }
    @Test fun eligibleFailureAndLateSuccessHaveRecoverableVisibleFeedback() {
        val state = mutableStateOf(AssessmentUiState(owner = "a",session = session(),response = response("FAILED",true),responseId = "response"))
        compose.setContent { AssessmentScreen(state.value,{}, {}, {}, {}, {}) }
        compose.onNodeWithText("Retry evaluation").assertIsDisplayed()
        compose.runOnUiThread { state.value = state.value.copy(response = response("SUCCEEDED",false)) }
        compose.onNodeWithText("Feedback ready").assertIsDisplayed()
        compose.onNodeWithText("Public feedback").assertIsDisplayed()
        compose.onNodeWithText("Retry evaluation").assertDoesNotExist()
    }
    @Test fun pendingHasExplicitRecheckAndNoAnswerResubmission() {
        compose.setContent { AssessmentScreen(AssessmentUiState(owner = "a",session = session(),responseId = "response"),{}, {}, {}, {}, {}) }
        compose.onNodeWithText("Evaluation pending. Recheck when ready.").assertIsDisplayed()
        compose.onNodeWithText("Recheck evaluation").assertIsDisplayed()
        compose.onNodeWithText("Submit choice").assertDoesNotExist()
    }
    @Test fun succeededFeedbackDoesNotHideOriginalUnconfirmedCommand() {
        compose.setContent { AssessmentScreen(AssessmentUiState(owner = "a",session = session(),response = response("SUCCEEDED",false),responseId = "response",unconfirmedRequests = listOf("answer")),{}, {}, {}, {}, {}) }
        compose.onNodeWithText("Feedback ready").assertIsDisplayed()
        compose.onNodeWithText("Original request unconfirmed: answer").assertIsDisplayed()
        compose.onNodeWithText("Check original request").assertIsDisplayed()
    }
    @Test fun nativeBackUsesTheSameLeaveActionAsTheVisibleBackButton() {
        val left = mutableStateOf(false)
        compose.setContent {
            if (left.value) androidx.compose.material3.Text("Back at exploration")
            else AssessmentScreen(AssessmentUiState(owner = "a",session = session(),responseId = "response"),{}, {}, {}, {}, { left.value = true })
        }
        compose.onNodeWithText("Optional check").assertIsDisplayed()
        androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK)
        compose.onNodeWithText("Back at exploration").assertIsDisplayed()
    }
    @Test fun emptyExplorationListProvidesRefreshAndEntryRecovery() {
        compose.setContent { ExplorationListScreen(ExplorationUiState(owner = "a"),{}, {}, {}, {}) }
        compose.onNodeWithText("No explorations yet. Accept a suggestion to begin.").assertIsDisplayed()
        compose.onNodeWithText("Refresh explorations").assertIsDisplayed()
        compose.onNodeWithText("Back to entry").assertIsDisplayed()
    }
    @Test fun nativeDetailBackLeavesOnceInsteadOfReenteringAcceptHandoff() {
        val left = mutableStateOf(false)
        var leaves = 0
        compose.setContent {
            if (left.value) androidx.compose.material3.Text("Back at exploration list")
            else ExplorationDetailScreen(ExplorationUiState(owner = "a"), {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, { leaves++; left.value = true })
        }
        androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK)
        compose.onNodeWithText("Back at exploration list").assertIsDisplayed()
        org.junit.Assert.assertEquals(1, leaves)
    }
    @Test fun nativeListBackLeavesOnceInsteadOfReturningToDetail() {
        val left = mutableStateOf(false)
        var leaves = 0
        compose.setContent {
            if (left.value) androidx.compose.material3.Text("Back at entry")
            else ExplorationListScreen(ExplorationUiState(owner = "a"), {}, {}, {}, { leaves++; left.value = true })
        }
        androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK)
        compose.onNodeWithText("Back at entry").assertIsDisplayed()
        org.junit.Assert.assertEquals(1, leaves)
    }
}
