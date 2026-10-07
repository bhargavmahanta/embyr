package app.embyr.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable class EmptyLearningRequest
@Serializable data class ExplorationActionRequest(val action: String, @SerialName("base_version") val baseVersion: Long)
@Serializable data class CompletionRequest(@SerialName("base_version") val baseVersion: Long)
@Serializable data class ReflectionRequest(val text: String)
@Serializable data class ReflectionEditRequest(@SerialName("base_version") val baseVersion: Long, val text: String)
@Serializable data class AssessmentStartRequest(@SerialName("confidence_before") val confidenceBefore: String)
@Serializable data class SupportRequest(@SerialName("interaction_id") val interactionId: String, val level: String)
@Serializable data class ChoiceContent(@SerialName("option_id") val optionId: String)
@Serializable data class AnswerRequest(@SerialName("interaction_id") val interactionId: String, @SerialName("response_type") val responseType: String = "SINGLE_CHOICE", val content: ChoiceContent)
