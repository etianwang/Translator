# Test rules

## Required Rust tests

- State transitions: normal completion, remote failure, download failure, cancellation, retry, restart recovery.
- Output naming: translated name, fallback `original_language.ext`, collision suffix, invalid filename sanitization.
- Repository persistence across a fresh database reopen.
- API validation: no file, inaccessible output folder, invalid language, unknown job.
- Doclingo client uses a local mock server; tests must never call the live service.

## Required React tests

- Drag/drop and multi-file picker add files to the selected list.
- Remove action removes exactly one file.
- Start is disabled until files, output folder, and target language exist.
- Start sends the selected options and files.
- Queue renders queued, translating, completed, failed, and cancelled states.
- Retry and cancel call the expected endpoints.

## Smoke check

Before each release, run one manual local translation using a disposable document and confirm: source preserved, output saved in chosen folder, translated filename or fallback applied, and restart does not lose a queued job.

## Rules

- No real API keys in code, fixtures, logs, screenshots, or test data.
- No test writes outside its temporary directory.
- No network test may call a non-local host.
- Tests assert visible behavior and state, not implementation-private functions.
