package app.embyr.core.network

import app.embyr.core.model.WorldResyncRequiredDto
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
data class ProblemDetails(
    val type: String? = null,
    val title: String? = null,
    val status: Int? = null,
    val detail: String? = null,
    val code: String? = null,
    @SerialName("request_id") val requestId: String? = null,
    // Error-adapter-only extension point. It is never a feature transport model.
    val details: JsonElement? = null,
)

@Serializable
data class FastApiValidationError(val detail: List<FastApiValidationIssue>)

@Serializable
data class FastApiValidationIssue(
    val loc: List<JsonElement>,
    val msg: String,
    val type: String,
)

sealed interface TransportError {
    data class Network(val kind: String) : TransportError
    data object AmbiguousTimeout : TransportError
    data class Problem(val httpStatus: Int, val details: ProblemDetails) : TransportError
    data class Validation(val httpStatus: Int, val issues: List<FastApiValidationIssue>) : TransportError
    data class WorldResync(val response: WorldResyncRequiredDto) : TransportError
    data class UnexpectedHttp(val httpStatus: Int, val requestId: String?) : TransportError
    data class Decode(val httpStatus: Int) : TransportError
    data class Authentication(val details: ProblemDetails? = null) : TransportError
}

sealed interface ApiResult<out T> {
    data class Success<T>(val value: T, val httpStatus: Int) : ApiResult<T>
    data class Failure(val error: TransportError) : ApiResult<Nothing>
}
