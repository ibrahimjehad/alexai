"""Thin CLI over the library. Every command supports --json. Exit code 1 on handled errors."""
from __future__ import annotations

import argparse
import json
import sys

from . import brain, evals, manifest, projects
from .pipeline import ingest
from .util import AlexAIError


def _out(args, data, human=None) -> None:
    if args.json or human is None:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(human(data))


def _topics(v):
    return [t.strip() for t in v.split(",") if t.strip()] if v else None


# ---------------------------------------------------------------- brain

def cmd_brain_search(a):
    res = brain.search_brain(a.query, k=a.k, topics=_topics(a.topics), type=a.type, root=a.root, mode=a.mode)
    _out(a, res, lambda r: "\n".join(f"{x['score']:7.3f}  {x['id']}  [{x['type']}] {x['title']}" for x in r)
         or "no matches (brain may be empty: feed it first)")


def cmd_brain_get(a):
    n = brain.get_note(a.id, root=a.root)
    _out(a, n, lambda n: open(brain.layout(a.root).root / n["path"], encoding="utf-8").read())


def cmd_brain_list(a):
    res = brain.list_notes(topics=_topics(a.topics), type=a.type, root=a.root)
    _out(a, res, lambda r: "\n".join(f"{x['id']}  [{x['type']}] {x['title']}" for x in r) or "no notes")


def cmd_brain_validate(a):
    res = brain.validate(root=a.root)
    def human(r):
        lines = [f"{e['file']}: ERROR {e['error']}" for e in r["errors"]]
        lines += [f"{w['file']}: warning {w['warning']}" for w in r["warnings"]]
        lines.append(f"{'OK' if r['ok'] else 'FAILED'}: {r['counts']['notes']} notes, "
                     f"{r['counts']['sources']} source records, {len(r['errors'])} errors, "
                     f"{len(r['warnings'])} warnings")
        return "\n".join(lines)
    _out(a, res, human)
    return 0 if res["ok"] else 1


def _semantic_line(s: dict) -> str:
    if not s.get("enabled"):
        return f"semantic search off ({s['reason']}); search is lexical only. To enable: {s['hint']}"
    return (f"semantic: {s['model']}, {s['notes']} notes / {s['vectors']} vectors, re-embedded {s['embedded']} "
            f"in {s['seconds']}s -> {s['path']}")


def _rerank_line(r: dict) -> str:
    rr = r.get("rerank") or {}
    if rr.get("enabled"):
        return f"\nreranker: {rr['model']}"
    from . import rerank
    return f"\nreranker on but unavailable ({rr.get('reason')})" if rerank.enabled() else ""


def cmd_brain_index(a):
    _out(a, brain.build_index(root=a.root), lambda r: f"indexed {r['notes']} notes -> {r['index_json']}, "
         f"{r['index_md']}\n" + _semantic_line(r["semantic"]) + _rerank_line(r))


def cmd_brain_prune_models(a):
    from . import semantic
    keep = [m.strip() for m in a.keep.split(",")] if a.keep else None
    _out(a, semantic.prune_models(keep, dry_run=a.dry_run),
         lambda r: f"{'would remove' if r['dry_run'] else 'removed'} {len(r['removed'])} model(s) "
         f"{r['removed']}, freed {r['freed_mb']} MB; kept {r['kept']}; model dir now {r['size_mb']} MB")


# ---------------------------------------------------------------- eval

def cmd_eval_retrieval(a):
    res = evals.retrieval(k=a.k, questions=a.questions, root=a.root, mode=a.mode)
    _out(a, res, evals.format_retrieval)


def cmd_eval_bakeoff(a):
    res = evals.bakeoff([m.strip() for m in a.models.split(",") if m.strip()], a.questions or [None],
                        modes=[m.strip() for m in a.modes.split(",")], root=a.root,
                        log=None if a.json else (lambda msg: print(msg, file=sys.stderr, flush=True)))
    _out(a, res, evals.format_bakeoff)


# ---------------------------------------------------------------- project

def cmd_project_new(a):
    _out(a, projects.new_project(a.id, name=a.name, description=a.description or "", root=a.root),
         lambda r: f"created {r['path']}")


def cmd_project_list(a):
    _out(a, projects.list_projects(root=a.root),
         lambda r: "\n".join(f"{p['id']}  {p['name']}" for p in r) or "no projects")


def cmd_project_read(a):
    res = projects.read_project(a.id, a.path, root=a.root)
    _out(a, res, lambda r: r["content"] if "content" in r else
         f"{r['brief']}\n---\n{r['decisions']}\n---\nfiles: {', '.join(r['files'])}")


def cmd_project_write(a):
    content = a.content if a.content is not None else sys.stdin.read()
    _out(a, projects.write_project_file(a.id, a.path, content, root=a.root),
         lambda r: f"wrote {r['bytes']} bytes to {a.id}/{r['path']}")


def cmd_project_decide(a):
    _out(a, projects.append_decision(a.id, a.text, date=a.date, root=a.root),
         lambda r: f"appended to {a.id}/decisions.md")


# ---------------------------------------------------------------- ingest

def cmd_ingest_add(a):
    res = ingest.add(a.url, preset=a.preset, kind=a.kind, collection=a.collection, author=a.author,
                     id_prefix=a.id_prefix, title_regex=a.title_regex, title_template=a.title_template,
                     root=a.root)
    _out(a, res, lambda r: f"matched {len(r['matched'])}: added {len(r['added'])}, updated "
         f"{len(r['updated'])}, unchanged {len(r['unchanged'])}"
         + (f"; MISSING {r['missing']}" if r.get("missing") else ""))


def _each(a, fn):
    ids = ingest._select(a.ids, a.all, a.root)
    results, rc = [], 0
    for sid in ids:
        try:
            r = fn(sid)
        except ingest.stt.ConfigError:
            raise
        except AlexAIError as exc:
            r, rc = {"id": sid, "status": "error", "error": str(exc)}, 1
        results.append(r)
        if not a.json:
            print(f"{r['id']}: {r['status']}" + (f" ({r['error']})" if r.get("error") else "")
                  + (f" {r['elapsed_sec']}s" if r.get("elapsed_sec") is not None else ""), flush=True)
    if a.json:
        _out(a, results)
    return rc


def cmd_ingest_fetch(a):
    return _each(a, lambda sid: ingest.fetch(sid, force=a.force, root=a.root))


def cmd_ingest_transcribe(a):
    return _each(a, lambda sid: ingest.transcribe(sid, force=a.force, backend=a.backend,
                                                  model=a.model, root=a.root))


def cmd_ingest_run(a):
    log = None if a.json else (lambda r: print(json.dumps(r), flush=True))
    res = ingest.run(a.ids, a.all, force=a.force, backend=a.backend, model=a.model, root=a.root, log=log)
    _out(a, res, lambda r: f"done {len(r['done'])}, failed {len(r['failed'])}")
    return 1 if res["failed"] else 0


def cmd_ingest_status(a):
    res = manifest.status(root=a.root)
    def human(r):
        rows = [f"{'id':32} F T D  title"]
        for s in r["sources"]:
            flags = " ".join("x" if s[k] else "." for k in ("fetched", "transcribed", "distilled"))
            rows.append(f"{s['id']:32} {flags}  {s['title']}" + (f"  !! {s['error']}" if s["error"] else ""))
        c = r["counts"]
        rows.append(f"{r['total']} sources: fetched {c['fetched']}, transcribed {c['transcribed']}, "
                    f"distilled {c['distilled']}")
        return "\n".join(rows)
    _out(a, res, human)


def cmd_ingest_estimate(a):
    res = ingest.estimate(root=a.root)
    if a.rate_per_hour is not None:
        res["rate_per_hour"] = a.rate_per_hour
        res["estimated_cost"] = round(res["total_hours"] * a.rate_per_hour, 2)
    _out(a, res, lambda r: f"{r['pending_sources']} sources pending, {r['total_min']} min "
         f"({r['total_hours']} h) of audio" + (f"; est. cost {r['estimated_cost']} at "
         f"{r['rate_per_hour']}/h" if "estimated_cost" in r else "")
         + (f"; unknown duration: {r['unknown_duration']}" if r["unknown_duration"] else ""))


def cmd_ingest_distilled(a):
    _out(a, ingest.mark_distilled(a.id, root=a.root), lambda r: f"{a.id}: distilled at {r['stages']['distilled']}")


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--root", default=None, help="data root (default: $ALEXAI_ROOT or repo)")

    p = argparse.ArgumentParser(prog="alexai", description="Alex AI brain, projects and ingestion tools")
    top = p.add_subparsers(dest="group", required=True)

    def sub(parent, name, fn, help_):
        sp = parent.add_parser(name, parents=[common], help=help_)
        sp.set_defaults(fn=fn)
        return sp

    b = top.add_parser("brain", help="search and maintain the knowledge brain").add_subparsers(dest="cmd", required=True)
    s = sub(b, "search", cmd_brain_search, "rank notes for a query")
    s.add_argument("query"); s.add_argument("-k", type=int, default=8)
    s.add_argument("--topics", help="comma-separated topic filter"); s.add_argument("--type")
    s.add_argument("--mode", choices=brain.SEARCH_MODES,
                   help="hybrid (default when semantic search is available) | lexical | semantic")
    s = sub(b, "get", cmd_brain_get, "print one note"); s.add_argument("id")
    s = sub(b, "list", cmd_brain_list, "list notes"); s.add_argument("--topics"); s.add_argument("--type")
    sub(b, "validate", cmd_brain_validate, "validate notes, source records, references")
    sub(b, "index", cmd_brain_index, "rebuild brain/index.json, index.md and the semantic vectors")
    s = sub(b, "prune-models", cmd_brain_prune_models, "delete downloaded models except the embedding model (and reranker) in use")
    s.add_argument("--keep", help="comma-separated model ids to keep (default: the configured model)")
    s.add_argument("--dry-run", action="store_true")

    ev = top.add_parser("eval", help="evaluate the brain").add_subparsers(dest="cmd", required=True)
    s = sub(ev, "retrieval", cmd_eval_retrieval, "recall@k + MRR of brain search on evals/questions.yaml")
    s.add_argument("-k", "--k", type=int, default=8)
    s.add_argument("--questions", help="questions YAML (default: <root>/evals/questions.yaml)")
    s.add_argument("--mode", choices=brain.SEARCH_MODES, help="search mode (default: hybrid if available)")
    s = sub(ev, "bakeoff", cmd_eval_bakeoff, "compare embedding models on one or more questions files")
    s.add_argument("--models", required=True, help="comma-separated FastEmbed model ids (downloaded if missing)")
    s.add_argument("--questions", action="append", help="questions YAML; repeat for several files")
    s.add_argument("--modes", default="semantic,hybrid", help="comma-separated modes to score")

    pr = top.add_parser("project", help="business projects").add_subparsers(dest="cmd", required=True)
    s = sub(pr, "new", cmd_project_new, "create a project"); s.add_argument("id")
    s.add_argument("--name"); s.add_argument("--description")
    sub(pr, "list", cmd_project_list, "list projects")
    s = sub(pr, "read", cmd_project_read, "read brief+decisions, or one file"); s.add_argument("id"); s.add_argument("path", nargs="?")
    s = sub(pr, "write", cmd_project_write, "write a file inside a project (content from --content or stdin)")
    s.add_argument("id"); s.add_argument("path"); s.add_argument("--content")
    s = sub(pr, "decide", cmd_project_decide, "append a dated entry to decisions.md")
    s.add_argument("id"); s.add_argument("text"); s.add_argument("--date")

    ig = top.add_parser("ingest", help="source ingestion pipeline").add_subparsers(dest="cmd", required=True)
    s = sub(ig, "add", cmd_ingest_add, "register sources from a feed/pdf/url")
    s.add_argument("url", nargs="?"); s.add_argument("--preset"); s.add_argument("--kind")
    s.add_argument("--collection"); s.add_argument("--author", default="alex-hormozi")
    s.add_argument("--id-prefix"); s.add_argument("--title-regex"); s.add_argument("--title-template")
    for name, fn, h in (("fetch", cmd_ingest_fetch, "download raw files"),
                        ("transcribe", cmd_ingest_transcribe, "transcribe fetched audio / extract pdf text"),
                        ("run", cmd_ingest_run, "fetch + transcribe sequentially (resumable)")):
        s = sub(ig, name, fn, h)
        s.add_argument("ids", nargs="*"); s.add_argument("--all", action="store_true")
        s.add_argument("--force", action="store_true")
        if name != "fetch":
            s.add_argument("--backend", help="elevenlabs (default) | local")
            s.add_argument("--model", help="override model id (default scribe_v3)")
    sub(ig, "status", cmd_ingest_status, "pipeline state of every source")
    s = sub(ig, "estimate", cmd_ingest_estimate, "audio duration still to transcribe")
    s.add_argument("--rate-per-hour", type=float, help="your plan's price per audio hour")
    s = sub(ig, "mark-distilled", cmd_ingest_distilled, "mark a source distilled after notes are written")
    s.add_argument("id")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rc = args.fn(args)
        return rc or 0
    except (AlexAIError, NotImplementedError) as exc:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1
