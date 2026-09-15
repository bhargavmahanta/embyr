# ADR 0004 — WorldModel and Renderer Boundary

Status: Accepted
Date: 2026-09-15

## Context

Embyr needs one semantic representation of a person's world while allowing each
mobile platform to deliver a high-quality native visual experience.

## Decision

The backend owns the semantic `WorldModel`; clients own rendering. Android will
use a custom native forest renderer, and the future iOS client will use a
SpriteKit renderer.

Both clients render the same semantic world, but their results do not need to be
pixel-identical.

## Alternatives Considered

Server-owned rendering and a pixel-identical cross-platform renderer were
rejected because they would weaken native control and couple semantic meaning to
one visual implementation.

## Consequences

The `WorldModel` contract must describe meaning without prescribing pixels.
Client renderers may evolve independently while preserving the same semantic
content and product intent.
