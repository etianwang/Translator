# Translator harness

This folder is the implementation contract for the native egui + Axum rewrite.

- [PRD](PRD.md): product scope and acceptance criteria
- [SPEC](SPEC.md): architecture, state machine, storage, API
- [API](API.md): frontend/backend HTTP contract
- [TASKS](TASKS.md): delivery order and completion checks
- [TEST_RULES](TEST_RULES.md): required automated checks
- [ADR-001](ADR-001-unified-doclingo-queue.md): unified queue decision

## Development

```powershell
$env:DOCLINGO_API_KEY = "your-key"
cargo run
```

This launches the native Windows window. Axum remains available locally for integration endpoints.

For the packaged EXE, copy `.env.example` to `.env` in the same folder as the EXE and set `DOCLINGO_API_KEY` there. `.env` is local-only and must not be committed.
