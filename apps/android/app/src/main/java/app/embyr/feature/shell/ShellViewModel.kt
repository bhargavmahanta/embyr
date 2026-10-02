package app.embyr.feature.shell

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import app.embyr.AppContainer
import app.embyr.auth.EmailCodeResult
import app.embyr.auth.AuthState
import app.embyr.core.model.ExplorationListItemDto
import app.embyr.core.model.ProfileDto
import app.embyr.core.model.RecommendationDto
import app.embyr.core.model.StarterInterestDto
import app.embyr.core.network.ApiResult
import app.embyr.core.network.TransportError
import app.embyr.feature.journey.OnboardingOutcome
import app.embyr.feature.journey.OnboardingRepository
import app.embyr.feature.journey.RecommendationOutcome
import app.embyr.feature.journey.RecommendationRepository
import app.embyr.feature.journey.SessionOutcome
import app.embyr.feature.journey.SessionRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlin.coroutines.coroutineContext

enum class JourneyScreen { RESTORING, SIGNED_OUT, ONBOARDING, ENTRY, RECOMMENDATION, EXPLORATION_READY, RECOVERABLE_ERROR }

data class JourneyUiState(
    val screen: JourneyScreen = JourneyScreen.RESTORING,
    val busy: Boolean = false,
    val message: String? = null,
    val email: String = "",
    val code: String = "",
    val awaitingCode: Boolean = false,
    val profile: ProfileDto? = null,
    val starters: List<StarterInterestDto> = emptyList(),
    val selectedIds: List<String> = emptyList(),
    val explorations: List<ExplorationListItemDto> = emptyList(),
    val recommendation: RecommendationDto? = null,
    val noResult: Boolean = false,
    val acceptedExplorationId: String? = null,
    val unresolved: Boolean = false,
    val decisionOutstanding: Boolean = false,
    val onboardingPending: Boolean = false,
    val recommendationPending: Boolean = false,
)

interface JourneyActions {
    fun setEmail(value: String)
    fun setCode(value: String)
    fun sendCode()
    fun verifyCode()
    fun retryStartup()
    fun retryStarters()
    fun toggleStarter(id: String)
    fun submitOnboarding(explicitNewAfterExpiry: Boolean = false)
    fun refreshEntry()
    fun showLatestRecommendation()
    fun showExplorationReady()
    fun requestRecommendation(mode: String, explicitNewAfterExpiry: Boolean = false)
    fun retryGeneration()
    fun decide(decision: String)
    fun retryDecision()
    fun backToEntry()
    fun signOut()
}

class ShellViewModel(private val container: AppContainer) : ViewModel(), JourneyActions {
    private val auth = container.authGateway
    private val session = SessionRepository(auth, container.embyrApi, container.ownerSession)
    private val onboarding = OnboardingRepository(container.embyrApi, container.ownerSession, container.journeyStore, container.commandOutbox, container.commandDispatcher)
    private val recommendations = RecommendationRepository(container.embyrApi, container.ownerSession, container.journeyStore, container.commandOutbox, container.commandDispatcher)
    private val mutable = MutableStateFlow(JourneyUiState())
    private var currentAction: Job? = null
    private var restoreJob: Job? = null
    val ui: StateFlow<JourneyUiState> = mutable

    init {
        viewModelScope.launch {
            auth.state.collect { state ->
                if (state == AuthState.SignedOut) {
                    currentAction?.cancel()
                    currentAction = null
                    restoreJob?.cancel()
                    restoreJob = null
                    mutable.value = JourneyUiState(screen = JourneyScreen.SIGNED_OUT)
                }
            }
        }
        restoreJob = viewModelScope.launch(start = CoroutineStart.LAZY) { restore() }
        restoreJob?.start()
    }

    override fun setEmail(value: String) { mutable.value = mutable.value.copy(email = value, message = null) }
    override fun setCode(value: String) { mutable.value = mutable.value.copy(code = value, message = null) }

    override fun sendCode() = action {
        val email = mutable.value.email.trim()
        if (!email.contains('@') || email.length > 254) {
            mutable.value = mutable.value.copy(message = "Enter a valid email address.")
            return@action
        }
        when (val result = auth.requestEmailCode(email)) {
            EmailCodeResult.Sent -> mutable.value = mutable.value.copy(awaitingCode = true, code = "", message = "Check your email for a sign-in code.")
            is EmailCodeResult.Failed -> mutable.value = mutable.value.copy(message = result.reason)
            else -> Unit
        }
    }

    override fun verifyCode() = action {
        val code = mutable.value.code.trim()
        if (code.isEmpty()) {
            mutable.value = mutable.value.copy(message = "Enter the code from your email.")
            return@action
        }
        when (val result = auth.verifyEmailCode(mutable.value.email, code)) {
            EmailCodeResult.Authenticated -> {
                mutable.value = mutable.value.copy(email = "", code = "", awaitingCode = false, screen = JourneyScreen.RESTORING)
                enterFromSession(session.bootstrap())
            }
            is EmailCodeResult.Failed -> mutable.value = mutable.value.copy(message = result.reason)
            else -> Unit
        }
    }

    override fun retryStartup() = action {
        enterFromSession(if (auth.state.value is AuthState.TokenAvailable) session.bootstrap() else session.restore())
    }
    override fun retryStarters() = action { loadOnboarding() }

    override fun toggleStarter(id: String) {
        if (mutable.value.onboardingPending) return
        val current = mutable.value.selectedIds
        val next = if (id in current) current - id else if (current.size < 20) current + id else {
            mutable.value = mutable.value.copy(message = "Choose up to 20 interests.")
            return
        }
        mutable.value = mutable.value.copy(selectedIds = next, message = null)
        viewModelScope.launch {
            try { onboarding.saveDraft(next) }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) {
                if (mutable.value.screen == JourneyScreen.ONBOARDING) {
                    mutable.value = mutable.value.copy(message = "Selection could not be saved. Try again.")
                }
            }
        }
    }

    override fun submitOnboarding(explicitNewAfterExpiry: Boolean) = action {
        when (val result = onboarding.submit(mutable.value.selectedIds, explicitNewAfterExpiry)) {
            OnboardingOutcome.Completed, OnboardingOutcome.Reconciled -> {
                mutable.value = mutable.value.copy(onboardingPending = false)
                refreshAfterOnboarding()
            }
            is OnboardingOutcome.InvalidStarters -> {
                mutable.value = mutable.value.copy(selectedIds = result.remainingIds, onboardingPending = false, message = "Some interests changed. Review your choices and submit again.")
                loadOnboarding()
            }
            OnboardingOutcome.Unresolved -> mutable.value = mutable.value.copy(unresolved = true, onboardingPending = false, message = "The previous submission could not be confirmed. You can start a new attempt when ready.")
            OnboardingOutcome.Pending -> mutable.value = mutable.value.copy(onboardingPending = true, message = "Submission is pending. Retry to check its result.")
            is OnboardingOutcome.Failed -> mutable.value = mutable.value.copy(onboardingPending = false, message = messageFor(result.error))
        }
    }

    override fun refreshEntry() = action { loadEntry() }
    override fun showLatestRecommendation() { mutable.value = mutable.value.copy(screen = JourneyScreen.RECOMMENDATION) }
    override fun showExplorationReady() { if (mutable.value.acceptedExplorationId != null) mutable.value = mutable.value.copy(screen = JourneyScreen.EXPLORATION_READY) }
    override fun requestRecommendation(mode: String, explicitNewAfterExpiry: Boolean) = action {
        if (mutable.value.decisionOutstanding) {
            mutable.value = mutable.value.copy(message = "Resolve the previous decision before requesting another suggestion.")
            return@action
        }
        mutable.value = mutable.value.copy(screen = JourneyScreen.RECOMMENDATION, message = null, unresolved = false, recommendation = null, noResult = false)
        applyRecommendation(recommendations.generate(mode, explicitNewAfterExpiry))
    }
    override fun retryGeneration() = action {
        recommendations.resumeGeneration()?.let { applyRecommendation(it) }
    }
    override fun decide(decision: String) = action {
        val id = mutable.value.recommendation?.id ?: return@action
        val result = recommendations.decide(id, decision)
        applyRecommendation(result)
        mutable.value = mutable.value.copy(decisionOutstanding = result == RecommendationOutcome.Pending || result == RecommendationOutcome.Unresolved)
    }
    override fun retryDecision() = action {
        val result = recommendations.resumeDecision() ?: return@action
        applyRecommendation(result)
        mutable.value = mutable.value.copy(decisionOutstanding = result == RecommendationOutcome.Pending || result == RecommendationOutcome.Unresolved)
    }
    override fun backToEntry() = action { loadEntry() }
    override fun signOut() {
        currentAction?.cancel()
        currentAction = null
        mutable.value = JourneyUiState(screen = JourneyScreen.RESTORING, busy = true)
        viewModelScope.launch {
            try { auth.signOut() }
            finally { mutable.value = JourneyUiState(screen = JourneyScreen.SIGNED_OUT) }
        }
    }

    private suspend fun restore() {
        mutable.value = JourneyUiState(screen = JourneyScreen.RESTORING, busy = true)
        try { enterFromSession(session.restore()) }
        catch (cancelled: CancellationException) { throw cancelled }
        catch (_: Exception) { mutable.value = mutable.value.copy(screen = JourneyScreen.RECOVERABLE_ERROR, message = "Session could not be restored. Retry or sign out.") }
        finally { mutable.value = mutable.value.copy(busy = false) }
    }

    private suspend fun enterFromSession(outcome: SessionOutcome) {
        if (auth.state.value == AuthState.SignedOut) {
            mutable.value = JourneyUiState(screen = JourneyScreen.SIGNED_OUT)
            return
        }
        when (outcome) {
            SessionOutcome.SignedOut -> mutable.value = JourneyUiState(screen = JourneyScreen.SIGNED_OUT)
            is SessionOutcome.Recoverable -> mutable.value = mutable.value.copy(screen = JourneyScreen.RECOVERABLE_ERROR, message = outcome.error?.let(::messageFor) ?: "Profile could not be verified. Retry.")
            is SessionOutcome.Ready -> {
                mutable.value = mutable.value.copy(profile = outcome.profile, message = null)
                if (outcome.profile.onboardingCompletedAt == null) {
                    val prior = onboarding.resume()
                    if (prior == OnboardingOutcome.Completed || prior == OnboardingOutcome.Reconciled) refreshAfterOnboarding()
                    else {
                        loadOnboarding()
                        if (prior == OnboardingOutcome.Unresolved) mutable.value = mutable.value.copy(unresolved = true, message = "A prior submission remains unresolved.")
                        if (prior == OnboardingOutcome.Pending) mutable.value = mutable.value.copy(onboardingPending = true, message = "Submission is pending. Retry to check its result.")
                    }
                } else loadEntry()
            }
        }
    }

    private suspend fun loadOnboarding() {
        val ids = onboarding.draft()
        when (val result = onboarding.starters()) {
            is ApiResult.Success -> mutable.value = mutable.value.copy(
                screen = JourneyScreen.ONBOARDING, starters = result.value.items, selectedIds = ids,
                message = if (result.value.items.isEmpty()) "No starter interests are available right now. You may continue with none." else mutable.value.message,
            )
            is ApiResult.Failure -> mutable.value = mutable.value.copy(screen = JourneyScreen.ONBOARDING, selectedIds = ids, message = messageFor(result.error))
        }
    }

    private suspend fun refreshAfterOnboarding() {
        when (val result = session.profile()) {
            is ApiResult.Success -> {
                if (result.value.onboardingCompletedAt != null && result.value.id == container.ownerSession.requireOwner()) {
                    mutable.value = mutable.value.copy(profile = result.value, unresolved = false)
                    loadEntry()
                } else mutable.value = mutable.value.copy(message = "Profile is still updating. Retry in a moment.")
            }
            is ApiResult.Failure -> if (result.error is TransportError.Authentication) {
                auth.signOut()
                mutable.value = JourneyUiState(screen = JourneyScreen.SIGNED_OUT, message = "Your session expired. Sign in again.")
            } else mutable.value = mutable.value.copy(message = messageFor(result.error))
        }
    }

    private suspend fun loadEntry() {
        val profile = session.profile()
        if (profile is ApiResult.Failure && profile.error is TransportError.Authentication) {
            auth.signOut()
            mutable.value = JourneyUiState(screen = JourneyScreen.SIGNED_OUT, message = "Your session expired. Sign in again.")
            return
        }
        if (profile !is ApiResult.Success || profile.value.id != container.ownerSession.requireOwner()) {
            mutable.value = mutable.value.copy(screen = JourneyScreen.RECOVERABLE_ERROR, message = (profile as? ApiResult.Failure)?.error?.let(::messageFor) ?: "Profile could not be verified.")
            return
        }
        val list = container.embyrApi.explorations(20)
        val snapshot = container.journeyStore.read(container.ownerSession.requireOwner())
        mutable.value = mutable.value.copy(
            screen = JourneyScreen.ENTRY, profile = profile.value,
            explorations = (list as? ApiResult.Success)?.value?.items.orEmpty(),
            recommendation = snapshot.presentation, noResult = snapshot.noResult,
            acceptedExplorationId = snapshot.acceptedExplorationId,
            message = (list as? ApiResult.Failure)?.error?.let(::messageFor),
        )
        recommendations.resumeDecision()?.let {
            applyRecommendation(it)
            mutable.value = mutable.value.copy(decisionOutstanding = it == RecommendationOutcome.Pending || it == RecommendationOutcome.Unresolved)
            return
        }
        recommendations.resumeGeneration()?.let {
            if (it == RecommendationOutcome.Pending || it == RecommendationOutcome.Unresolved) {
                mutable.value = mutable.value.copy(recommendation = null, noResult = false)
            }
            applyRecommendation(it)
        }
    }

    private suspend fun applyRecommendation(outcome: RecommendationOutcome) {
        when (outcome) {
            is RecommendationOutcome.Found -> {
                val snapshot = container.journeyStore.read(container.ownerSession.requireOwner())
                mutable.value = mutable.value.copy(screen = JourneyScreen.RECOMMENDATION, recommendation = snapshot.presentation, noResult = false, recommendationPending = false, message = null)
            }
            RecommendationOutcome.NoResult -> mutable.value = mutable.value.copy(screen = JourneyScreen.RECOMMENDATION, recommendation = null, noResult = true, recommendationPending = false, message = null)
            is RecommendationOutcome.Accepted -> mutable.value = mutable.value.copy(screen = JourneyScreen.EXPLORATION_READY, acceptedExplorationId = outcome.explorationId, recommendationPending = false, message = null)
            is RecommendationOutcome.Skipped -> mutable.value = mutable.value.copy(screen = JourneyScreen.ENTRY, recommendation = null, recommendationPending = false, message = "Skipped. Choose another mode whenever you like.")
            RecommendationOutcome.Pending -> mutable.value = mutable.value.copy(screen = JourneyScreen.RECOMMENDATION, recommendationPending = true, message = "This action is still pending. Retry to check its result.")
            RecommendationOutcome.Unresolved -> mutable.value = mutable.value.copy(screen = JourneyScreen.RECOMMENDATION, unresolved = true, recommendationPending = false, message = "The previous action could not be confirmed.")
            is RecommendationOutcome.Failed -> mutable.value = mutable.value.copy(screen = JourneyScreen.RECOMMENDATION, recommendationPending = false, message = messageFor(outcome.error))
        }
    }

    private fun action(block: suspend () -> Unit) {
        if (mutable.value.busy) return
        mutable.value = mutable.value.copy(busy = true)
        val job = viewModelScope.launch(start = CoroutineStart.LAZY) {
            try { block() }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { mutable.value = mutable.value.copy(message = "Something went wrong. Retry when ready.") }
            finally {
                if (currentAction == coroutineContext[Job]) {
                    currentAction = null
                    mutable.value = mutable.value.copy(busy = false)
                }
            }
        }
        currentAction = job
        job.start()
    }

    private fun messageFor(error: TransportError): String = when (error) {
        is TransportError.Problem -> when (error.details.code) {
            "RECOMMENDATION_GENERATION_UNAVAILABLE" -> "Recommendations are temporarily unavailable. Try again later."
            "IDEMPOTENCY_KEY_REUSED" -> "This request could not be safely repeated. Retry from the current screen."
            "UNMAPPED_IDENTITY" -> "Your account could not be linked. Contact the alpha team."
            else -> "Request failed (${error.details.code ?: error.httpStatus}).${error.details.requestId?.let { " Reference: $it" } ?: ""}"
        }
        is TransportError.Authentication -> if (error.details?.code == "UNMAPPED_IDENTITY") "Your account could not be linked. Contact the alpha team." else "Your session expired. Sign in again."
        is TransportError.Network, TransportError.AmbiguousTimeout -> "Connection interrupted. Retry to check the result."
        else -> "Request failed. Retry when ready."
    }

    class Factory(private val container: AppContainer) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            require(modelClass == ShellViewModel::class.java)
            return ShellViewModel(container) as T
        }
    }
}
