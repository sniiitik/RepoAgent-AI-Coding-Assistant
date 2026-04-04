from pathlib import Path

import tools


def test_safe_blocks_paths_outside_workspace(tmp_path):
    tools.set_workspace(str(tmp_path))
    result = tools.read_file("../outside.txt")
    assert "error" in result
    assert "escapes workspace" in result["error"]


def test_create_file_patch_updates_file(tmp_path):
    file_path = tmp_path / "sample.py"
    file_path.write_text("print('hello')\n", encoding="utf-8")
    tools.set_workspace(str(tmp_path))

    result = tools.create_file_patch(
        "sample.py",
        [{"old_text": "hello", "new_text": "world"}],
    )

    assert result["success"] is True
    assert "world" in file_path.read_text(encoding="utf-8")


def test_list_git_diff_returns_branch_and_status(tmp_path):
    tools.set_workspace(str(tmp_path))
    Path(tmp_path / "README.md").write_text("hi\n", encoding="utf-8")
    result = tools.list_git_diff()
    assert "branch" in result
    assert "status" in result or "error" in result
