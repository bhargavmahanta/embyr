package app.embyr.feature.assessment

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.*
import app.embyr.feature.exploration.LearningPage
import app.embyr.feature.exploration.LearningStatus

@Composable fun AssessmentScreen(state: AssessmentUiState, support: (String) -> Unit, answer: (String) -> Unit, retry: () -> Unit, recheck: () -> Unit, back: () -> Unit) {
    var selectedOption by rememberSaveable(state.session?.id) { mutableStateOf<String?>(null) }
    val session = state.session
    LearningPage("Optional check") {
        LearningStatus(state.busy,state.message)
        if (state.unconfirmedRequests.isNotEmpty()) {
            Text("Original request unconfirmed: ${state.unconfirmedRequests.joinToString(", ")}")
            OutlinedButton(onClick = recheck, enabled = !state.busy) { Text("Check original request") }
        }
        if (session == null) OutlinedButton(onClick = recheck, enabled = !state.busy) { Text("Refresh optional check") }
        if (session != null) {
            Text(session.interaction.prompt, style = MaterialTheme.typography.titleLarge)
            val immutable = state.responseId != null || state.selectedOptionId != null
            if (state.responseId == null) {
                session.interaction.options.forEach { option ->
                    val selected = (state.selectedOptionId ?: selectedOption) == option.id
                    OutlinedButton(onClick = { selectedOption = option.id }, enabled = !state.busy && !immutable && session.status == "ACTIVE", modifier = Modifier.fillMaxWidth().semantics { this.selected = selected }) { Text(option.label) }
                }
                if (session.status == "ACTIVE") {
                    Button(onClick = { (state.selectedOptionId ?: selectedOption)?.let(answer) }, enabled = !state.busy && (state.selectedOptionId ?: selectedOption) != null) { Text(if (immutable) "Check original answer request" else "Submit choice") }
                    if (!immutable) listOf("SMALL_NUDGE" to "Small nudge", "STRONG_HINT" to "Stronger hint", "MISSING_CONCEPT" to "Missing concept", "EXPLANATION" to "Explanation").forEach { (level,label) ->
                        OutlinedButton(onClick = { support(level) }, enabled = !state.busy) { Text(label) }
                    }
                } else Text("This check is ${session.status.lowercase().replace('_',' ')}. No answer can be submitted.")
            }
            session.deliveredSupport.forEach { Text(it.content.text) }
            if (state.responseId != null) {
                when (state.response?.evaluationStatus) {
                    "SUCCEEDED" -> { Text("Feedback ready", modifier = Modifier.semantics { heading() }); state.response.feedback?.let { Text(it) } }
                    "FAILED" -> {
                        Text("Evaluation failed", modifier = Modifier.semantics { heading() })
                        Text(if (state.response.retryAllowed) "Processing did not finish. You can retry evaluation of the same saved answer." else "This evaluation cannot be retried. Your saved answer is retained.")
                        state.response.feedback?.let { Text(it) }
                        if (state.response.retryAllowed) Button(onClick = retry, enabled = !state.busy) { Text("Retry evaluation") }
                    }
                    else -> Text(if (state.polling) "Checking evaluation progress…" else "Evaluation pending. Recheck when ready.")
                }
                OutlinedButton(onClick = recheck, enabled = !state.busy && !state.polling) { Text("Recheck evaluation") }
            }
        }
        OutlinedButton(onClick = back) { Text("Back to exploration") }
    }
}
