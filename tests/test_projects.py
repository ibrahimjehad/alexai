import pytest

from alexai import projects
from alexai.util import AlexAIError


def test_project_lifecycle(root):
    projects.new_project("acme-gym", name="Acme Gym", root=root)
    assert [p["id"] for p in projects.list_projects(root)] == ["acme-gym"]
    projects.write_project_file("acme-gym", "deliverables/offer.md", "# Offer", root=root)
    projects.append_decision("acme-gym", "Use a 30-day guarantee.", date="2026-11-16", root=root)
    data = projects.read_project("acme-gym", root=root)
    assert "## 2026-11-16\nUse a 30-day guarantee." in data["decisions"]
    assert "deliverables/offer.md" in data["files"]
    with pytest.raises(AlexAIError, match="already exists"):
        projects.new_project("acme-gym", root=root)


@pytest.mark.parametrize("bad_id", ["../etc", "Acme", "a/b", "", ".", "..", "acme gym", "/tmp/x"])
def test_bad_project_ids_refused(root, bad_id):
    with pytest.raises(AlexAIError):
        projects.new_project(bad_id, root=root)
    with pytest.raises(AlexAIError):
        projects.read_project(bad_id, root=root)


@pytest.mark.parametrize("bad_path", ["../other/brief.md", "/etc/passwd", "deliverables/../../other/brief.md",
                                      "~/x", "../../brain/notes/x.md"])
def test_path_traversal_refused(root, bad_path):
    projects.new_project("acme-gym", root=root)
    projects.new_project("other", root=root)
    with pytest.raises(AlexAIError):
        projects.read_project("acme-gym", bad_path, root=root)
    with pytest.raises(AlexAIError):
        projects.write_project_file("acme-gym", bad_path, "x", root=root)


def test_symlink_escape_refused(root):
    projects.new_project("acme-gym", root=root)
    projects.new_project("other", root=root)
    (root / "projects/acme-gym/link").symlink_to(root / "projects/other")
    with pytest.raises(AlexAIError, match="outside"):
        projects.read_project("acme-gym", "link/brief.md", root=root)
