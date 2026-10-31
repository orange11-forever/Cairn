import base64
import subprocess
from pathlib import Path

import pytest
from cairn_api.errors import ApiProblem
from cairn_api.workspace.local import DesktopWorkspace


def repository(tmp_path: Path) -> tuple[DesktopWorkspace, Path]:
    data, code = tmp_path / "data", tmp_path / "code"
    data.mkdir()
    code.mkdir()
    subprocess.run(["git", "-C", str(code), "init", "-b", "main"], check=True, capture_output=True)
    return DesktopWorkspace(
        data, Path("/usr/bin/git"), None, base64.b64encode, base64.b64decode
    ), code


def test_architecture_snapshot_reads_real_sources_but_excludes_ignored_secrets_and_links(
    tmp_path: Path,
) -> None:
    from cairn_api.workspace.architecture import read_snapshot

    workspace, code = repository(tmp_path)
    (code / "src").mkdir()
    (code / "package.json").write_text(
        '{"dependencies":{"react":"19"},"scripts":{"build":"vite build"}}'
    )
    (code / "src/main.ts").write_text(
        'import { createRoot } from "react-dom/client";\ncreateRoot(document.body);'
    )
    (code / ".env").write_text("API_KEY=never-send")
    (code / ".gitignore").write_text("private.py\n")
    (code / "private.py").write_text("private-source-never-send")
    outside = tmp_path / "outside.py"
    outside.write_text("outside-secret-never-send")
    (code / "src/link.py").symlink_to(outside)
    (code / "src/binary.py").write_bytes(b"\x00binary")
    value = read_snapshot(workspace, str(code))
    rendered = value.model_dump_json()
    assert "createRoot" in rendered and "react" in rendered
    assert (
        "never-send" not in rendered
        and "outside-secret" not in rendered
        and "\\u0000" not in rendered
    )
    assert {source.path for source in value.sources} == {"package.json", "src/main.ts"}
    assert all(source.start_line == 1 for source in value.sources)
    assert len(value.digest) == 64


def test_snapshot_is_bounded_and_marks_partial_coverage(tmp_path: Path) -> None:
    from cairn_api.workspace.architecture import MAX_SOURCES, read_snapshot

    workspace, code = repository(tmp_path)
    for index in range(MAX_SOURCES + 5):
        (code / f"module{index}.py").write_text('print("source")\n' * 700)
    value = read_snapshot(workspace, str(code))
    assert len(value.sources) <= MAX_SOURCES
    assert sum(len(source.content) for source in value.sources) <= 64000
    assert value.truncated is True
    assert all(source.truncated for source in value.sources)


def test_snapshot_fingerprint_changes_with_source_and_secret_values_are_redacted(
    tmp_path: Path,
) -> None:
    from cairn_api.workspace.architecture import read_snapshot

    workspace, code = repository(tmp_path)
    path = code / "main.py"
    path.write_text('API_KEY = "sk-example-secret-value"\nprint("first")')
    before = read_snapshot(workspace, str(code))
    assert "sk-example-secret-value" not in before.model_dump_json()
    assert "[REDACTED]" in before.model_dump_json()
    path.write_text('print("second")')
    assert read_snapshot(workspace, str(code)).digest != before.digest


def test_snapshot_never_reads_source_outside_bound_repository(tmp_path: Path) -> None:
    from cairn_api.workspace.architecture import read_snapshot

    workspace, code = repository(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "main.py").write_text("do not disclose")
    (code / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ApiProblem) as error:
        read_snapshot(workspace, str(code))
    assert error.value.code == "architecture_no_sources"


def test_model_evidence_redacts_database_urls_and_cloud_credentials(tmp_path: Path) -> None:
    from cairn_api.workspace.architecture import read_snapshot

    workspace, code = repository(tmp_path)
    (code / "config.py").write_text(
        'DATABASE_URL = "postgresql://alice:private-db-password@db/project"\nAWS_SECRET_ACCESS_KEY = "cloud-secret-example"\nAWS_ACCESS_KEY_ID = "AKIA1234567890123456"\n'
    )
    evidence = read_snapshot(workspace, str(code)).evidence()
    combined = "\n".join(source.text for source in evidence)
    assert "private-db-password" not in combined
    assert "cloud-secret-example" not in combined
    assert "AKIA1234567890123456" not in combined
    assert "[REDACTED]" in combined


def test_source_inventory_honors_global_ignore_without_running_helpers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cairn_api.workspace.architecture import read_snapshot

    workspace, code = repository(tmp_path)
    ignored = tmp_path / "global-ignore"
    ignored.write_text("personal.py\n")
    config = tmp_path / "global-git-config"
    config.write_text(
        f"[core]\n excludesFile = {ignored}\n fsmonitor = touch {tmp_path / 'unexpected'}\n"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    (code / "main.py").write_text('print("public source")')
    (code / "personal.py").write_text("private-content")
    snapshot = read_snapshot(workspace, str(code))
    assert [source.path for source in snapshot.sources] == ["main.py"]
    assert not (tmp_path / "unexpected").exists()


def test_branch_only_change_invalidates_snapshot(tmp_path: Path) -> None:
    from cairn_api.workspace.architecture import read_snapshot

    workspace, code = repository(tmp_path)
    (code / "main.py").write_text('print("entry")')
    before = read_snapshot(workspace, str(code))
    subprocess.run(
        ["git", "-C", str(code), "symbolic-ref", "HEAD", "refs/heads/another"], check=True
    )
    after = read_snapshot(workspace, str(code))
    assert before.head == after.head
    assert before.branch != after.branch
    assert before.digest != after.digest


def test_git_file_inventory_stops_at_its_output_limit(tmp_path: Path) -> None:
    workspace, code = repository(tmp_path)
    fake_git = tmp_path / "fake-git"
    fake_git.write_text(
        '#!/usr/bin/env python3\nimport sys\nsys.stdout.buffer.write(b"a" * 2000001)\n'
    )
    fake_git.chmod(0o700)
    workspace.git = fake_git
    with pytest.raises(ApiProblem) as error:
        workspace.source_paths(code)
    assert error.value.code == "architecture_repository_too_large"


def test_makefile_unquoted_credentials_are_removed_from_model_evidence(tmp_path: Path) -> None:
    from cairn_api.workspace.architecture import read_snapshot

    workspace, code = repository(tmp_path)
    (code / 'Makefile').write_text('API_KEY = plain-secret-value\nTOKEN := private-token-value\nexport DB_PASSWORD ?= database-password-value\nall:\n\tcmake --build build\n')
    rendered = '\n'.join(item.text for item in read_snapshot(workspace, str(code)).evidence())
    for secret in ('plain-secret-value', 'private-token-value', 'database-password-value'):
        assert secret not in rendered
    assert 'cmake --build build' in rendered
