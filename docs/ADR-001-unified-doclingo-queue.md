# ADR-001 — One Doclingo-backed queue

## Decision

Replace individual PDF, PPT, and Excel translation implementations with one Doclingo-backed document job queue.

## Context

The current project duplicates GUI, upload, polling, download, and error handling across document types. It also includes a separate DeepL-based Excel path with incompatible output behavior.

## Consequences

- One code path supports every format Doclingo accepts.
- Queue reliability, retries, and secure credential handling are implemented once.
- Legacy Excel bilingual-column output and glossary replacement are explicitly deferred instead of partially recreated.
- One serial worker is intentionally retained in V1; increase concurrency only after service limits and user demand justify it.
