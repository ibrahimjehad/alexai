# Alex AI

A knowledge brain built from Alex Hormozi's material, plus an agent that uses it to plan offers, lead generation and sales for any business.

## Layers (kept strictly separate)
| Layer | Where | What |
|---|---|---|
| Brain | `brain/` | Plain data. `notes/` (one idea per file), `sources/` (one record per source), `manifest.json` (source registry and pipeline stages), `index.json` / `index.md` (generated). Nothing in it is specific to Claude Code. |
| Tools | `alexai/` | Python package with importable functions (`search_brain`, `get_note`, `validate`, `build_index`, `new_project`, `read_project`, ingestion...) and a thin CLI over them. |
| Agent | `agent/` | `instructions.md` (the behaviour rules) and `skills/` (`feed`, `new-project`, `work`). `CLAUDE.md` imports the rules, and `.claude/skills` is a symlink to `agent/skills`. |

Raw material lives in `raw/`: `audio/` (gitignored), `transcripts/` and `pdfs/`. Business work lives in `projects/<id>/`, which holds `brief.md`, `decisions.md`, `deliverables/` and `sessions/`.

## Note schema
Each `brain/notes/<id>.md` has YAML frontmatter with the required fields `id, type (framework|concept|tactic|example|definition), title, author, topics, sources: [{id, ref}], related, updated`. Two fields are optional: `questions` (3 to 6 plain-language questions the note answers, in a business owner's own words) and `aliases` (other everyday names for the idea). Search indexes both, so a question can find a note even when the two share no words. The full rules are in `alexai/schema.py` and the `feed` skill.

## Setup
```
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
cp .env.example .env    # then set ELEVENLABS_API_KEY
```

## Commands
All commands take `--json`.
```
python -m alexai brain search "raise prices" -k 5 [--topics offers] [--type framework] [--mode hybrid|lexical|semantic]
python -m alexai brain get|list|validate|index|prune-models
python -m alexai eval retrieval [--k 8] [--mode ...] [--questions F] [--json]  # recall@k, MRR, lenient / reachable / solved (by `style` if set)
python -m alexai eval bakeoff --models a,b --questions <file> [--questions <file2>]   # compare embedding models
python -m alexai project new <id> | list | read <id> [path] | write <id> <path> | decide <id> "text"
python -m alexai ingest add --preset hormozi-100m-offers     # or <rss|pdf> --collection ...
python -m alexai ingest fetch|transcribe|run <ids...>|--all [--force]
python -m alexai ingest status | estimate [--rate-per-hour X] | mark-distilled <id>
```
Process every pending episode in sequence. The run is resumable and skips finished stages:
```
python -m alexai ingest run --all
```

## Meaning-based search (optional)
`brain search` can also match by meaning, so "my clients say it's too pricey" finds pricing notes that share none of those words. It runs a small embedding model locally (FastEmbed + onnxruntime, no PyTorch, no API, nothing leaves the machine) and fuses it with the word search. Default model: `BAAI/bge-small-en-v1.5` (~67 MB, downloaded once).
- **Enable:** `.venv/bin/pip install -e '.[semantic]'`, then `python -m alexai brain index` (downloads the model and embeds the notes; later runs re-embed only changed notes). Without the extra or the model, search silently stays lexical and `brain index` prints one line saying so.
- **Modes:** `brain search ... --mode hybrid|lexical|semantic` (default hybrid when available); the same flag works on `eval retrieval`. `ALEXAI_SEMANTIC=off` disables it entirely.
- **Fusion:** hybrid = 0.4 x z(word score) + 0.6 x z(meaning score), each z-normalised over the notes being searched (`brain.fuse`), then the single best note of each ranker is guaranteed a place in the returned top k (`brain.keep_top`). Score fusion keeps how far ahead a note is, where rank fusion (RRF, used before) flattened it to a rank: RRF pushed 12 word-search #1 hits and 9 meaning #1 hits out of the top 8 on the dev questions; now none. Recall is flat for weights 0.3-0.5. Settings: `FUSION_*` in `alexai/brain.py`.
- **Reranker (optional, off):** `alexai/rerank.py` can rescore the top 20 fused notes with a local ONNX cross-encoder (FastEmbed `TextCrossEncoder`, default `BAAI/bge-reranker-base`, ~1.1 GB) that sees each note's title, aliases, first line and its question closest to the query; its rank is blended with the fused rank. It is off because its gain on the dev questions was within noise (+3 expected notes of 130, MRR +0.01 to +0.06) for ~0.8 s extra per CLI search. Turn on with `ALEXAI_RERANK=on` (model: `ALEXAI_RERANK_MODEL`), then run `brain index` once to download it; search never downloads. Any object with `model_id` and `score(query, texts)` can be injected with `rerank.set_reranker(...)`.
- **Where things live:** the model under `models/` in the repo (override with `ALEXAI_MODEL_DIR`); note vectors under `<data root>/.cache/vectors/<model>.npz`, keyed by note content hash + model id. Both are gitignored, derived data, safe to delete. `brain prune-models` removes downloaded models other than the ones in use.
- **Other models / backends:** set `ALEXAI_EMBED_MODEL` to another FastEmbed model (add its query prefix to `MODEL_PREFIXES` in `alexai/semantic.py`), and compare candidates with `python -m alexai eval bakeoff --models a,b --questions <file>`. Any object with `model_id`, `dim`, `embed_documents(texts)` and `embed_query(text)` can be injected with `semantic.set_embedder(...)` (a hosted API, a different runtime); `VectorStore` (brute-force numpy cosine) is the one place to swap in a vector database. A server keeps the model and vectors in memory after the first search.

## Retrieval evals
`eval retrieval --questions <file>` scores `brain search` on a YAML list of `{id, question, expect_notes, style?, accept_notes?}`. Besides recall@k and MRR (overall and per `style`) it prints:
- **lenient recall@k**: an expected note also counts as found when one of that question's `accept_notes` (other notes that would answer it acceptably) is in the top k;
- **reachable@k**: an expected note also counts when it is in `related` of one of the top 3 results (the agent is told to follow related links);
- **questions solved@k**: share of questions with at least one expected note in the top k.

`evals/questions.yaml` and `evals/retrieval_holdout.yaml` are the tuning sets; further held-out files are for validation only, never for tuning.

## Transcription
Transcription goes through pluggable backends in `alexai/pipeline/transcribe.py`:
- `elevenlabs` is the default. It uses ElevenLabs Scribe, model `scribe_v3`, and needs `ELEVENLABS_API_KEY`.
- `local` is optional. It runs mlx-whisper or faster-whisper and needs `pip install -e '.[local]'`. Select it with `--backend local`.

## Tests
`.venv/bin/python -m pytest -q`

## Hosting later (Claude Agent SDK)
- **Agent:** load `agent/instructions.md` as the system prompt and `agent/skills/*/SKILL.md` as skills, unchanged.
- **Tools:** import `alexai` functions and register them as SDK tools (`search_brain`, `get_note`, `read_project`, `write_project_file`, `append_decision`, and so on). Alternatively, let the agent run the CLI with `--json`.
- **Data:** every function takes `root=` (or the `ALEXAI_ROOT` environment variable), so the server can point at any data volume.
- **Tenancy:** `project_id` is the tenant boundary. Project functions reject invalid ids, `..`, absolute paths and symlink escapes. Expose only the project functions, never raw file access, and bind each session to one `project_id`.
- **Search:** `search_brain` is the single entry point (lexical, semantic or hybrid), so backends can change without touching callers. Install the `semantic` extra on the server and run `brain index` once to fetch the model.
