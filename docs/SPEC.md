# Technical specification

## Architecture

`Slint native UI → SQLite repository + one queue worker → Doclingo API`.

The native UI never receives the Doclingo key. Axum remains available for local integration; the worker is the only component that calls Doclingo.

## Job record

```text
id, original_name, source_path, output_dir, target_language,
ocr_enabled, translate_filename, status, progress, remote_query_key,
output_path, error, created_at, updated_at
```

## States

```text
queued -> uploading -> translating -> downloading -> completed
              |              |               |
              +------------> failed <--------+
queued -> cancelled
uploading/translating/downloading -> cancelled
```

`cancelled` stops local work. If Doclingo has no remote-cancel API, its remote job may continue but the app stops polling and never downloads it.

## Restart recovery

- `translating` or `downloading` with `remote_query_key`: return to `queued` and resume from remote status polling.
- `uploading` without `remote_query_key`: return to `queued`.
- `completed`, `failed`, `cancelled`: unchanged.

## Worker algorithm

1. Read the oldest `queued` job.
2. If it has no remote key: set `uploading`, submit it, store query key.
3. Set `translating`; poll Doclingo every five seconds.
4. On success: set `downloading`, download to a unique temporary output path, then atomically move it to the final output path.
5. Set `completed`; on error store a user-readable error and set `failed`.

V1 uses one worker to respect unknown service concurrency limits. Add bounded parallelism only after Doclingo limits are verified.

## Files

- Sources: app-data `inbox/<job-id>/`.
- Downloads: app-data `staging/<job-id>/` until complete.
- Outputs: user-selected folder.
- SQLite: app-data `translator.db`.

The original source is never changed or deleted by the application.

## UI contract

The approved screen has a narrow navigation rail, a main “new translation” panel, and a persistent right-side queue. The required controls are: drag/drop target, multi-file picker, removable selected-file rows, output-folder picker, live target-language selector, live model selector with token-cost ratio, live account-character balance, translated-filename checkbox, OCR checkbox, start button, queue status, retry/cancel/open actions. Metadata refreshes every 30 seconds.
