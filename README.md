# Alex AI

**A business strategist agent built on Alex Hormozi's frameworks.** Alex AI has a knowledge base distilled from Hormozi's books and podcast, called the brain. It uses that knowledge to plan offers, lead generation, sales and pricing for any business, and it cites the exact source behind every recommendation.

It runs inside [Claude Code](https://claude.com/claude-code). Open this folder, describe your business, and Alex AI interviews you, searches the brain, applies the right framework and records every decision you accept.

> **Private repo.** It contains transcripts and audio of copyrighted material. Don't make it public or share the files outside the team.

---

## What it does

| Mode | You say something like | What happens |
|---|---|---|
| **Strategy** | "Start a new project for my gym" / "Let's work on the gym's offer" | Creates a project folder for that one business, interviews you for the brief, then runs strategy sessions. It searches the brain first, names the framework it is using, asks for your real numbers (price, margin, CAC, churn) and saves decisions and deliverables. |
| **Feed** | "Feed this podcast episode" / "Add this PDF" | Downloads, transcribes and reads new material. It distils the material into short notes in its own words, validates them and rebuilds the search index. This is the only mode that changes the brain. |

How it behaves:
- **Brain first.** It searches the brain before answering and cites each note it uses, for example `[offers-value-equation | hormozi-100m-offers-p03, Part 3 ~12:40]`. Anything that doesn't come from the brain is labelled **general knowledge**.
- **A strategist, not an impersonation.** It applies Hormozi's frameworks in a neutral voice and always answers in English.
- **Businesses never mix.** Each business is a separate folder under `projects/`. A session reads only the brain and that one project.

## What's in the repo

| Folder | What it holds |
|---|---|
| `brain/` | **The knowledge.** About 410 notes, one idea per file: 151 leads, 97 money models, 83 sales and 79 offers. It also has 47 source records and a generated index (`index.json`, `index.md`). All plain Markdown and YAML. |
| `raw/transcripts/` | Timestamped transcripts (`.txt` + `.json`) of every source the brain was built from. |
| `raw/audio/` | The original audio (47 MP3s, ~830 MB) from the public RSS feed of *The Game with Alex Hormozi*. |
| `alexai/` | **The tools.** A Python package and CLI for search, notes, projects, ingestion, transcription and evals. |
| `agent/` | **The behaviour.** `instructions.md` holds the rules, and `skills/` holds the three workflows: `feed`, `new-project` and `work`. `CLAUDE.md` loads them into Claude Code, and `.claude/skills` links to `agent/skills`. |
| `evals/` | Question sets that measure how well search finds the right notes. |
| `tests/` | The automated test suite (pytest). |

### Sources in the brain
| Source | Parts |
|---|---|
| *$100M Offers* (audiobook) | 7 |
| *$100M Leads* (audiobook) | 11 |
| *$100M Money Models* (audiobook) | 9 |
| *The Game* podcast, sales episodes | 20 |

### Not in the repo (by design)
| What | Why | How you get it |
|---|---|---|
| `projects/` | Your business work is private to your machine. | Created on your machine the first time you start a project. |
| `models/` | The local search model (~67 MB) is a download cache. | Downloaded automatically by `brain index` (see Setup). |
| `.cache/` | Note vectors are derived data. | Rebuilt by `brain index`. |
| `.env` | API keys. | Copy `.env.example` and add your own. |

## How it works

```
 You ──► Claude Code ──reads──► CLAUDE.md + agent/instructions.md + agent/skills/
              │
              ├──runs──► python -m alexai brain search "..."   (hybrid search over brain/)
              ├──runs──► python -m alexai brain get <note>
              └──runs──► python -m alexai project read|write|decide <id>   (projects/<id>/ only)
```

The design keeps three layers apart, so each one can change without touching the others:

| Layer | Where | What |
|---|---|---|
| Brain | `brain/` | Plain data. `notes/` (one idea per file), `sources/` (one record per source), `manifest.json` (source registry and pipeline stages), `index.json` / `index.md` (generated). Nothing in it is specific to Claude Code. |
| Tools | `alexai/` | A Python package with importable functions (`search_brain`, `get_note`, `validate`, `build_index`, `new_project`, `read_project`, ingestion...) and a thin CLI over them. |
| Agent | `agent/` | `instructions.md` (the behaviour rules) and `skills/` (`feed`, `new-project`, `work`). |

**Search** combines two methods. Keyword matching finds exact terms. Meaning-based matching uses a small embedding model running locally, `BAAI/bge-small-en-v1.5` through FastEmbed/ONNX, so nothing leaves your machine. With both, "my clients say it's too pricey" still finds the pricing notes even though they share none of those words.

**The ingestion pipeline** (feed mode) runs `add → fetch → transcribe → distil → validate → index`. It is resumable and skips stages that are already done. Transcription uses ElevenLabs Scribe by default. A local Whisper backend is optional.

---

## Setup

### Requirements
- macOS or Linux (Windows works through WSL)
- Python **3.11+**
- [Claude Code](https://claude.com/claude-code) with your own Claude account
- An ElevenLabs API key, **only** if you will feed new audio

### Install

```bash
git clone https://github.com/mmnowmedia/alexai.git
```

```bash
cd alexai
```

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -e '.[dev,semantic,pdf]'
```

```bash
cp .env.example .env
```

Then open `.env` and set `ELEVENLABS_API_KEY` if you will feed new audio. Leave it empty otherwise.

### Build the search index (one time)

```bash
.venv/bin/python -m alexai brain index
```

This downloads the local search model into `models/` and embeds every note. Later runs only re-embed notes that changed.

### Check that it works

```bash
.venv/bin/python -m alexai brain search "raise prices" -k 5
```

```bash
.venv/bin/python -m pytest -q
```

### Use it

```bash
claude
```

Start Claude Code in the repo folder. It loads the Alex AI rules automatically. Then just talk to it:
- *"Start a new project for my coffee shop."*
- *"Let's work on coffee-shop. I want more leads without paid ads."*
- *"Feed episode 940 of The Game."*

### Getting updates
```bash
git pull
```
```bash
.venv/bin/python -m alexai brain index
```
Your `projects/` folder is never touched by a pull. If you change the brain in feed mode, commit and push those notes so the whole team gets them. Never commit anything from `projects/`, because `.gitignore` blocks it.

---

# Technical reference

### Note schema
Each `brain/notes/<id>.md` has YAML frontmatter with the required fields `id, type (framework|concept|tactic|example|definition), title, author, topics, sources: [{id, ref}], related, updated`. Two fields are optional: `questions` (3 to 6 plain-language questions the note answers, in a business owner's own words) and `aliases` (other everyday names for the idea). Search indexes both, so a question can find a note even when the two share no words. The full rules are in `alexai/schema.py` and the `feed` skill.

### Commands
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

### Meaning-based search (optional)
`brain search` can also match by meaning, so "my clients say it's too pricey" finds pricing notes that share none of those words. It runs a small embedding model locally (FastEmbed + onnxruntime, no PyTorch, no API, nothing leaves the machine) and fuses it with the word search. Default model: `BAAI/bge-small-en-v1.5` (~67 MB, downloaded once).
- **Enable:** `.venv/bin/pip install -e '.[semantic]'`, then `python -m alexai brain index` (downloads the model and embeds the notes; later runs re-embed only changed notes). Without the extra or the model, search silently stays lexical and `brain index` prints one line saying so.
- **Modes:** `brain search ... --mode hybrid|lexical|semantic` (default hybrid when available); the same flag works on `eval retrieval`. `ALEXAI_SEMANTIC=off` disables it entirely.
- **Fusion:** hybrid = 0.4 x z(word score) + 0.6 x z(meaning score), each z-normalised over the notes being searched (`brain.fuse`), then the single best note of each ranker is guaranteed a place in the returned top k (`brain.keep_top`). Score fusion keeps how far ahead a note is, where rank fusion (RRF, used before) flattened it to a rank: RRF pushed 12 word-search #1 hits and 9 meaning #1 hits out of the top 8 on the dev questions; now none. Recall is flat for weights 0.3-0.5. Settings: `FUSION_*` in `alexai/brain.py`.
- **Reranker (optional, off):** `alexai/rerank.py` can rescore the top 20 fused notes with a local ONNX cross-encoder (FastEmbed `TextCrossEncoder`, default `BAAI/bge-reranker-base`, ~1.1 GB) that sees each note's title, aliases, first line and its question closest to the query; its rank is blended with the fused rank. It is off because its gain on the dev questions was within noise (+3 expected notes of 130, MRR +0.01 to +0.06) for ~0.8 s extra per CLI search. Turn on with `ALEXAI_RERANK=on` (model: `ALEXAI_RERANK_MODEL`), then run `brain index` once to download it; search never downloads. Any object with `model_id` and `score(query, texts)` can be injected with `rerank.set_reranker(...)`.
- **Where things live:** the model under `models/` in the repo (override with `ALEXAI_MODEL_DIR`); note vectors under `<data root>/.cache/vectors/<model>.npz`, keyed by note content hash + model id. Both are gitignored, derived data, safe to delete. `brain prune-models` removes downloaded models other than the ones in use.
- **Other models / backends:** set `ALEXAI_EMBED_MODEL` to another FastEmbed model (add its query prefix to `MODEL_PREFIXES` in `alexai/semantic.py`), and compare candidates with `python -m alexai eval bakeoff --models a,b --questions <file>`. Any object with `model_id`, `dim`, `embed_documents(texts)` and `embed_query(text)` can be injected with `semantic.set_embedder(...)` (a hosted API, a different runtime); `VectorStore` (brute-force numpy cosine) is the one place to swap in a vector database. A server keeps the model and vectors in memory after the first search.

### Retrieval evals
`eval retrieval --questions <file>` scores `brain search` on a YAML list of `{id, question, expect_notes, style?, accept_notes?}`. Besides recall@k and MRR (overall and per `style`) it prints:
- **lenient recall@k**: an expected note also counts as found when one of that question's `accept_notes` (other notes that would answer it acceptably) is in the top k;
- **reachable@k**: an expected note also counts when it is in `related` of one of the top 3 results (the agent is told to follow related links);
- **questions solved@k**: share of questions with at least one expected note in the top k.

`evals/questions.yaml` and `evals/retrieval_holdout.yaml` are the tuning sets; further held-out files are for validation only, never for tuning.

### Transcription
Transcription goes through pluggable backends in `alexai/pipeline/transcribe.py`:
- `elevenlabs` is the default. It uses ElevenLabs Scribe, model `scribe_v3`, and needs `ELEVENLABS_API_KEY`.
- `local` is optional. It runs mlx-whisper or faster-whisper and needs `pip install -e '.[local]'`. Select it with `--backend local`.

### Tests
`.venv/bin/python -m pytest -q`

### Hosting later (Claude Agent SDK)
- **Agent:** load `agent/instructions.md` as the system prompt and `agent/skills/*/SKILL.md` as skills, unchanged.
- **Tools:** import `alexai` functions and register them as SDK tools (`search_brain`, `get_note`, `read_project`, `write_project_file`, `append_decision`, and so on). Alternatively, let the agent run the CLI with `--json`.
- **Data:** every function takes `root=` (or the `ALEXAI_ROOT` environment variable), so the server can point at any data volume.
- **Tenancy:** `project_id` is the tenant boundary. Project functions reject invalid ids, `..`, absolute paths and symlink escapes. Expose only the project functions, never raw file access, and bind each session to one `project_id`.
- **Search:** `search_brain` is the single entry point (lexical, semantic or hybrid), so backends can change without touching callers. Install the `semantic` extra on the server and run `brain index` once to fetch the model.
