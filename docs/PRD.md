# PRD — Unified document translator

## Goal

Replace the three PyQt translators with one local React + Axum application. Users add one or more documents, choose an output folder and target language, then run a persistent Doclingo translation queue.

## Primary flow

1. Drag files into the drop zone or choose multiple files.
2. Pick output folder and target language.
3. Optionally enable OCR and translated output filenames.
4. Start the queue.
5. Open each completed translation from the side queue or output folder.

## Scope

- One desktop-oriented page using the approved side-queue layout.
- Any document accepted by Doclingo; no client extension whitelist.
- Persistent FIFO queue; one active job in V1.
- Upload, remote progress polling, download, retry, cancellation, history.
- Output-folder selection and safe output naming.
- Doclingo credentials stay server-side in OS credential storage.

## Naming

When translated-name metadata is available, save `<translated-base-name>.<source-extension>`. If translation fails or returns an invalid name, save `<original-base-name>_<target-language>.<source-extension>`. Add ` (2)`, ` (3)`, etc. before the extension if needed. Never overwrite a file.

## Non-goals for V1

- The legacy Excel adjacent-column bilingual output, DeepL, and glossary replacement.
- CAD-specific translation.
- User accounts, cloud sync, queue prioritization, configurable concurrency.

## Acceptance criteria

- A user can add multiple files by drag/drop or native multi-file picker.
- A user cannot start without at least one file, output folder, and target language.
- Completed translations appear in the chosen output folder and remain accessible after restart.
- Restart resumes remote jobs with a query key and requeues jobs interrupted before submission completes.
- An unsupported file ends as `failed` with Doclingo's reason and can be removed or retried.
