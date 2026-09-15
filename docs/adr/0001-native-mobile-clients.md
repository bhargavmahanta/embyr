# ADR 0001 — Native Mobile Clients

Status: Accepted
Date: 2026-09-15

## Context

Embyr's living personal world depends on high-quality platform interaction and a
native rendering experience. The project needs a clear first-client priority
without constraining a future iOS implementation.

## Decision

Build Android first using Kotlin and Jetpack Compose. A future iOS client will
use Swift, SwiftUI, and SpriteKit.

## Alternatives Considered

A cross-platform-first client was considered and rejected. The native approach
is preferred for product quality, platform integration, and renderer control.

## Consequences

Android can evolve against its platform's strengths. The future iOS client will
be a separate native implementation, so shared behavior must come from explicit
contracts rather than shared UI code.
