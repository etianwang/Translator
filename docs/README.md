# Translator harness

This folder is the implementation contract for the React + Axum rewrite.

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
cd frontend; npm run dev
```

The React dev server proxies `/api` to Axum at `http://127.0.0.1:3000`.

For the packaged EXE, copy `.env.example` to `.env` in the same folder as the EXE and set `DOCLINGO_API_KEY` there. `.env` is local-only and must not be committed.
