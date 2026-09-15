# ADR 0002 — Modular Monolith Backend

Status: Accepted
Date: 2026-09-15

## Context

The backend needs clear domain boundaries without the operational cost and
distributed-system complexity of independently deployed services.

## Decision

Build a Python and FastAPI modular monolith. Keep modules explicit inside one
deployable backend and use a Python worker for asynchronous processing.

## Alternatives Considered

Starting with microservices was rejected because the project has not produced
evidence that independent deployment or scaling outweighs the added complexity.

## Consequences

The initial backend remains simpler to develop, test, and operate. Module
boundaries must remain clear enough that measured future needs can support
extraction without requiring it prematurely.
