---
name: feed
description: Ingest a new source (podcast feed, PDF, video, article) into the Alex AI brain, or adjust existing knowledge. Covers add, fetch, transcribe, reading the transcript, and distilling atomic notes plus a source record, then validating and indexing. Use when the user wants to add, feed, import or correct knowledge.
---

# Feed: add or adjust knowledge

Feed mode is the only mode that writes to `brain/`. Run every command from the repo root.

## 1. Register the source
- Known collections: `python -m alexai ingest add --preset hormozi-100m-offers` (or `hormozi-100m-leads`).
- A new podcast feed: `python -m alexai ingest add <rss-url> --collection <kebab> --id-prefix <author-collection> --title-regex '<regex capturing the part number>'`.
- A PDF: `python -m alexai ingest add <path-or-url.pdf> --kind pdf --collection <kebab> --id-prefix <source-id>`.
- YouTube and web adapters are still stubs. Tell the user rather than working around them.
- Never take audio from Spotify or any other DRM stream. Use only public RSS enclosures.
- Check the result with `python -m alexai ingest status` (and `ingest estimate` to see the audio hours still pending).

## 2. Fetch and transcribe
- `python -m alexai ingest run <source-id>` fetches and then transcribes. Use `--all` to process everything pending. Re-running is safe: finished stages are skipped, and `--force` redoes a stage.
- Transcription uses ElevenLabs Scribe and needs `ELEVENLABS_API_KEY` in `.env`. If the key is missing, stop and ask the user to add it. Never print the key.
- The output is `raw/transcripts/<source-id>.txt`, with a `[mm:ss]` marker on each paragraph. The `.json` beside it holds the exact segments.

## 3. Read and filter
- Read the whole `.txt` transcript.
- Drop intros, outros, ads, sponsor reads, calls to action and repetition. Keep only the ideas.

## 4. Distill into atomic notes
- Write one idea per file at `brain/notes/<id>.md`. The id is kebab-case, prefixed by topic (for example `offers-value-equation`), and must equal the filename.
- Frontmatter must have these fields: `id, type (framework|concept|tactic|example|definition), title, author, topics, sources: [{id, ref}], related, updated`, plus the optional `questions: [...]` and `aliases: [...]` (lists of non-empty strings). No other fields are allowed. The `ref` gives the part and timestamp, such as `"Part 3, ~12:40"`, taken from the nearest `[mm:ss]` marker.
- Write 3 to 6 `questions` a business owner would ask in everyday words, which this note answers (for example "What can I sell right after a customer's first purchase?"). Avoid the framework's own name and jargon, because search already matches the title and body. Add `aliases` where the idea has other common names or everyday phrases (for example `[add-on offer, cross-sell]`). Search indexes both fields, and `brain validate` warns when a framework, tactic, definition or concept note has no `questions`.
- Body: start with a one-line summary sentence, then the idea in your own words. Add steps or a formula if the idea has one, then when to use it. Quote only short phrases, never long passages.
- Before you create a note, run `brain search` for the same idea. If a note already exists, refine it rather than duplicate it, and add the new source to its `sources`.
- If the new material contradicts or changes an existing note, show the user the diff (old versus new) and wait for approval before you save it.
- Link related notes in both directions with `related`.

## 5. Source record
- Write `brain/sources/<source-id>.md`. Its frontmatter has `id, author, collection, title, kind, url, duration_sec, notes: [every note id from this source]`, copied from the manifest entry. The body is a summary of 3 to 6 sentences.

## 6. Check, index, mark
1. `python -m alexai brain validate`: fix every error, and review the warnings.
2. `python -m alexai brain index`, then `python -m alexai eval retrieval --k 8` and report recall@8 plus any missed notes.
3. `python -m alexai ingest mark-distilled <source-id>`
4. Report to the user: the notes you created or changed, any conflicts you resolved, and gaps you noticed.
