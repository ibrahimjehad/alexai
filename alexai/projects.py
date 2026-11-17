"""Business projects. `project_id` is the tenant boundary: every function resolves paths
inside projects/<project_id>/ and refuses anything that escapes it."""
from __future__ import annotations

from pathlib import Path

from .paths import layout
from .util import AlexAIError, atomic_write_text, is_kebab, today

BRIEF_TEMPLATE = """# {name}

_Project id: `{project_id}` · created {date}_

## Business
{description}

## Offer today
- What is sold, price, delivery:

## Customer (avatar)
- Who, pain, dream outcome:

## Numbers
- Monthly revenue:
- Gross margin:
- Customer acquisition cost (CAC):
- Lifetime gross profit (LTGP):
- Leads / month, conversion rate, churn:

## Constraints and goals
-
"""

DECISIONS_TEMPLATE = "# Decisions: {name}\n\nDated log, newest at the bottom. One entry per decision.\n"


def _project_dir(project_id: str, root=None, must_exist: bool = True) -> Path:
    if not is_kebab(project_id):
        raise AlexAIError(f"invalid project id {project_id!r}: must be kebab-case (a-z, 0-9, '-')")
    base = layout(root).projects.resolve()
    pdir = (base / project_id).resolve()
    if pdir.parent != base:
        raise AlexAIError("project path escapes the projects folder")
    if must_exist and not pdir.is_dir():
        raise AlexAIError(f"project {project_id!r} does not exist")
    return pdir


def _safe_path(project_id: str, relpath: str, root=None) -> Path:
    """Resolve `relpath` inside the project folder or raise. Rejects absolute paths, '..',
    and symlinks that point outside the project."""
    pdir = _project_dir(project_id, root)
    if not relpath or relpath.startswith(("/", "~")) or "\x00" in relpath:
        raise AlexAIError(f"path {relpath!r} must be relative to the project folder")
    if any(part == ".." for part in Path(relpath).parts):
        raise AlexAIError(f"path {relpath!r} may not contain '..'")
    target = (pdir / relpath).resolve()
    if target != pdir and pdir not in target.parents:
        raise AlexAIError(f"path {relpath!r} resolves outside project {project_id!r}")
    return target


def new_project(project_id: str, name: str | None = None, description: str = "", root=None) -> dict:
    pdir = _project_dir(project_id, root, must_exist=False)
    if pdir.exists():
        raise AlexAIError(f"project {project_id!r} already exists")
    name = name or project_id.replace("-", " ").title()
    (pdir / "deliverables").mkdir(parents=True)
    (pdir / "sessions").mkdir()
    (pdir / "deliverables" / ".gitkeep").touch()
    (pdir / "sessions" / ".gitkeep").touch()
    atomic_write_text(pdir / "brief.md", BRIEF_TEMPLATE.format(
        name=name, project_id=project_id, date=today(), description=description or "-"))
    atomic_write_text(pdir / "decisions.md", DECISIONS_TEMPLATE.format(name=name))
    return {"id": project_id, "path": str(pdir), "files": list_files(project_id, root)}


def list_projects(root=None) -> list[dict]:
    base = layout(root).projects
    if not base.exists():
        return []
    out = []
    for p in sorted(base.iterdir()):
        if p.is_dir() and is_kebab(p.name) and (p / "brief.md").exists():
            first = (p / "brief.md").read_text(encoding="utf-8").splitlines()[:1]
            out.append({"id": p.name, "name": first[0].lstrip("# ").strip() if first else p.name})
    return out


def list_files(project_id: str, root=None) -> list[str]:
    pdir = _project_dir(project_id, root)
    return sorted(str(p.relative_to(pdir)) for p in pdir.rglob("*")
                  if p.is_file() and p.name != ".gitkeep" and pdir in p.resolve().parents)


def read_project(project_id: str, relpath: str | None = None, root=None) -> dict:
    """No relpath: brief + decisions + file list. With relpath: that file's content."""
    if relpath:
        path = _safe_path(project_id, relpath, root)
        if not path.is_file():
            raise AlexAIError(f"{relpath!r} not found in project {project_id!r}")
        return {"id": project_id, "path": relpath, "content": path.read_text(encoding="utf-8")}
    pdir = _project_dir(project_id, root)
    return {
        "id": project_id,
        "brief": (pdir / "brief.md").read_text(encoding="utf-8"),
        "decisions": (pdir / "decisions.md").read_text(encoding="utf-8"),
        "files": list_files(project_id, root),
    }


def write_project_file(project_id: str, relpath: str, content: str, root=None) -> dict:
    path = _safe_path(project_id, relpath, root)
    if path == _project_dir(project_id, root):
        raise AlexAIError("cannot write to the project folder itself")
    atomic_write_text(path, content)
    return {"id": project_id, "path": relpath, "bytes": len(content.encode("utf-8"))}


def append_decision(project_id: str, text: str, date: str | None = None, root=None) -> dict:
    text = (text or "").strip()
    if not text:
        raise AlexAIError("decision text is empty")
    path = _safe_path(project_id, "decisions.md", root)
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    entry = f"\n## {date or today()}\n{text}\n"
    atomic_write_text(path, current.rstrip("\n") + "\n" + entry)
    return {"id": project_id, "path": "decisions.md", "appended": entry.strip()}
