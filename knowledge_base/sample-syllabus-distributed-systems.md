# Sample Syllabus — Introduction to Distributed Systems

> Example of the kind of detailed course syllabus you will drop into this
> folder. The Researcher reads these over MCP and uses them to ground the
> course it helps generate (scope, ordering, depth, terminology).

**Audience:** motivated beginners with basic programming experience.
**Format:** every module follows the internal EDGE format (see
`course-style-guide.md`).

## Module 1 — Why Distributed Systems
- What "distributed" means; latency vs throughput.
- Failure as the default, not the exception.

## Module 2 — Communication
- Synchronous request/response vs asynchronous messaging.
- Message queues (e.g. Kafka) and when to prefer them.

## Module 3 — State and Caching
- Stateless services and why they scale.
- Distributed caches (e.g. Redis); cache invalidation and TTLs.

## Module 4 — Coordinating Work
- Orchestration vs choreography.
- Retries, idempotency, and avoiding duplicate work.

## Out of scope (do not cover)
- Consensus algorithms (Paxos/Raft) — reserved for the advanced course.
- Kubernetes operations.
