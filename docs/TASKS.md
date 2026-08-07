# Implementation tasks

## 1. Scaffold

- Create Rust workspace with Axum service and egui native app.
- Add application-data path discovery and local launch command.
- Done when the native window opens in development.

## 2. Storage and settings

- Create SQLite migrations and job repository.
- Add non-secret preferences and OS-backed Doclingo key retrieval.
- Done when restart recovery is covered by tests.

## 3. Doclingo client and worker

- Implement submit, status, and download calls with timeouts.
- Implement single-worker state transitions and cancellation checks.
- Done when a mocked client completes, fails, and resumes jobs.

## 4. API

- Implement upload, list, retry, cancel, output, and settings endpoints.
- Validate write access to output directory before enqueueing.
- Done when API contract tests pass.

## 5. Native egui UI

- Implement approved side-queue layout.
- Add drag/drop, multi-file selection, output-folder picker, target language, options, start button, and queue actions.
- Poll jobs while the page is open.
- Done when the full primary flow works against a mocked API.

## 6. Packaging and migration

- Package the local application for Windows.
- Remove hard-coded legacy API keys from repository history/current files.
- Archive legacy PyQt implementation after release verification.
- Done when packaged app completes a real non-sensitive smoke translation.
