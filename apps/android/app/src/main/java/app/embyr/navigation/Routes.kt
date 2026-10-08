package app.embyr.navigation

import kotlinx.serialization.Serializable

@Serializable data object BootstrapRoute
@Serializable data object SignedOutRoute
@Serializable data object ReadyShellRoute
@Serializable data object OnboardingRoute
@Serializable data object RecommendationRoute
@Serializable data object ExplorationReadyRoute
@Serializable data object RecoverableErrorRoute

@Serializable data object ExplorationListRoute
@Serializable data class ExplorationDetailRoute(val id: String)
@Serializable data class AssessmentRoute(val id: String)
