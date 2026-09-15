# ADR 0003 — PostgreSQL Primary Database

Status: Accepted
Date: 2026-09-15

## Context

Embyr needs durable relational data, an ontology graph, and semantic retrieval
without creating multiple sources of truth before their value is demonstrated.

## Decision

Use PostgreSQL as the primary database. Represent the ontology graph
relationally and use pgvector for semantic retrieval.

## Alternatives Considered

Neo4j and a separate vector database were considered and rejected for the
initial system. Either requires evidence that PostgreSQL cannot meet a measured
need before adoption.

## Consequences

Transactional, graph-related, and vector-backed data share one operational
foundation. Schema and query design must be measured as the system grows, and a
specialized store remains an evidence-driven future option.
