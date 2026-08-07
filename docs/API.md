# API contract

All endpoints are local to the Axum process and prefixed with `/api`.

## Jobs

`POST /jobs` accepts `multipart/form-data`:

```text
files[]            required, one or more files
output_dir         required, absolute local path
target_language    required, Doclingo language code
ocr_enabled        optional boolean, default false
translate_filename optional boolean, default true
```

Returns `201` and created job records in `queued` state.

`GET /jobs` returns active and recent jobs ordered by creation time.

`POST /jobs/:id/start` transitions a queued batch/job into worker processing. The UI only enables it when its required inputs are valid.

`POST /jobs/:id/retry` resets a failed job to `queued` and clears error, output path, progress, and remote key.

`DELETE /jobs/:id` cancels queued or active local work, or removes a terminal record. It never deletes the user's output file.

`GET /jobs/:id/output` serves a completed output file for the UI's “Open” action.

## Settings

`GET /settings` returns non-secret defaults: default output directory, target language, OCR, and filename behavior.

`PATCH /settings` updates those defaults. Secret-management endpoints are deliberately absent from the browser API; the backend uses OS credential storage.

## Live Doclingo metadata

`GET /metadata` calls Doclingo with the server-side API key and returns:

- `models`: `engine_name` and `token_cost_ratio` from `/models`.
- `languages`: display name and code from `/gettranslatorlanguagelist?internationalCode=zh-CN`.
- `account`: live `total_words`, `vip_words`, `bag_words`, and account status from `/getapiuserinfo`.

The frontend refreshes metadata every 30 seconds and sends the selected `model` with each job submission.

## Error shape

```json
{"error":{"code":"OUTPUT_DIR_UNAVAILABLE","message":"The output folder cannot be written."}}
```

Common codes: `NO_FILES`, `OUTPUT_DIR_UNAVAILABLE`, `INVALID_LANGUAGE`, `DOCLINGO_REJECTED`, `DOCLINGO_UNAVAILABLE`, `DOWNLOAD_FAILED`, `JOB_NOT_FOUND`.
