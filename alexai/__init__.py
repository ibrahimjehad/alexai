"""Alex AI core library. Import these functions directly (e.g. from a server exposing them
as agent tools); the CLI in alexai.cli is only a thin wrapper."""
from .brain import build_index, get_note, list_notes, search_brain, validate
from .projects import append_decision, list_projects, new_project, read_project, write_project_file

__all__ = ["search_brain", "get_note", "list_notes", "validate", "build_index",
           "new_project", "list_projects", "read_project", "write_project_file", "append_decision"]
__version__ = "0.1.0"
