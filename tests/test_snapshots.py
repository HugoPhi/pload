import json
import shutil
import sys
import zipfile

import pytest

from pload.cli import build_parser, main, shell_script
from pload.errors import PloadError
from pload.managers.platform import ConfigManager
from pload.managers.venv import VenvManager
from pload.snapshots import (
    RepositoryManager,
    SnapshotManager,
    digest,
    execute,
    public_index,
    validate_bundle,
    write_json,
)


def tiny_wheel(directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "pload_demo-1.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as wheel:
        wheel.writestr("pload_demo.py", "answer = 42\n")
        wheel.writestr("pload_demo-1.0.dist-info/METADATA",
                       "Metadata-Version: 2.1\nName: pload-demo\nVersion: 1.0\n")
        wheel.writestr("pload_demo-1.0.dist-info/WHEEL",
                       "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        wheel.writestr("pload_demo-1.0.dist-info/RECORD", "")
    return path


def recipe(path):
    path.mkdir(parents=True)
    (path / "requirements.txt").write_text("", encoding="utf-8")
    write_json(path / "snapshot.json", {
        "schema": 1, "runtime": {},
        "files": {"requirements.txt": digest(path / "requirements.txt")},
    })
    return path


def test_offline_roundtrip_external_interpreter_and_shared_cache(tmp_path):
    config = ConfigManager(home=tmp_path / "home")
    wheels = tmp_path / "existing-wheels"
    tiny_wheel(wheels)
    source = VenvManager(config).create_venv(name="source")
    execute(config.get_pip_command(source) + ["install", "--no-index", "--find-links",
                                            str(wheels), "pload-demo==1.0"])
    manager = SnapshotManager(config)
    python = config.get_pip_command(source)[0]
    snapshot = manager.export("demo", python=python, bundle="all", links=[str(wheels)])
    assert (snapshot / "requirements.txt").read_text().strip() == "pload-demo==1.0"
    assert (manager.wheels / "pload_demo-1.0-py3-none-any.whl").is_file()
    restored = manager.restore("demo", "restored", version=sys.executable, offline=True)
    output = execute([config.get_pip_command(restored)[0], "-c",
                      "import pload_demo; print(pload_demo.answer)"])
    assert output == "42"
    # A restored wheel has direct_url metadata; exporting it again must reuse
    # the exact original archive from the shared cache, not require an index.
    reexport = manager.export("restored-again", environment="restored", bundle="all")
    assert validate_bundle(reexport)["files"] == validate_bundle(snapshot)["files"]
    with pytest.raises(PloadError, match="already exists"):
        manager.export("demo", python=python)
    repos = RepositoryManager(config)
    repos.add("local", str(tmp_path / "remote"), "local")
    repos.transfer("local", "demo", push=True)
    second = ConfigManager(home=tmp_path / "second")
    reader = RepositoryManager(second)
    reader.add("local", str(tmp_path / "remote"), "local")
    reader.transfer("local", "demo")
    validate_bundle(reader.snapshots.path("demo"))
    assert (reader.snapshots.wheels / "pload_demo-1.0-py3-none-any.whl").exists()


def test_tampering_is_rejected_before_creating_environment(tmp_path):
    manager = SnapshotManager(ConfigManager(home=tmp_path))
    snapshot = recipe(manager.path("demo"))
    (snapshot / "requirements.txt").write_text("unexpected==1\n", encoding="utf-8")
    with pytest.raises(PloadError, match="checksum"):
        manager.restore("demo", "nope")
    assert not manager.config.venv_path.exists()


@pytest.mark.parametrize("filename", ["../escape.whl", "/tmp/escape.whl", "wheels/../../escape.whl"])
def test_unsafe_manifest_paths_rejected(tmp_path, filename):
    snapshot = recipe(tmp_path / "demo")
    data = json.loads((snapshot / "snapshot.json").read_text())
    data["files"][filename] = "0" * 64
    write_json(snapshot / "snapshot.json", data)
    with pytest.raises(PloadError, match="invalid snapshot file"):
        validate_bundle(snapshot)


def test_runtime_mismatch_does_not_create_environment(tmp_path):
    manager = SnapshotManager(ConfigManager(home=tmp_path))
    recipe(manager.path("demo"))
    with pytest.raises(PloadError, match="mismatch"):
        manager.restore("demo", "nope", version=sys.executable)
    assert not manager.config.venv_path.exists()


@pytest.mark.parametrize("location", ["-oProxyCommand:x", "host:relative", "host:/a/../b",
                                      "host:/a;touch-b", "host:/"])
def test_ssh_location_validation(location):
    with pytest.raises(PloadError):
        RepositoryManager.ssh_location(location)


def test_git_recipe_roundtrip(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("Git is optional")
    for key, value in {"GIT_AUTHOR_NAME": "pload test", "GIT_COMMITTER_NAME": "pload test",
                       "GIT_AUTHOR_EMAIL": "test@example.invalid",
                       "GIT_COMMITTER_EMAIL": "test@example.invalid"}.items():
        monkeypatch.setenv(key, value)
    bare = tmp_path / "remote.git"
    execute(["git", "init", "--bare", str(bare)])
    writer = RepositoryManager(ConfigManager(home=tmp_path / "writer"))
    recipe(writer.snapshots.path("demo"))
    writer.add("git", str(bare), "git")
    writer.transfer("git", "demo", push=True)
    reader = RepositoryManager(ConfigManager(home=tmp_path / "reader"))
    reader.add("git", str(bare), "git")
    reader.transfer("git", "demo")
    validate_bundle(reader.snapshots.path("demo"))


def test_commands_and_shell_integration(capsys):
    assert build_parser().parse_args(["export", "example", "-b", "all"]).bundle == "all"
    for command in ("export", "restore", "repo"):
        assert main([command, "-h"]) == 0
        for shell in ("bash", "zsh", "fish", "powershell"):
            assert command in shell_script(shell)
    assert "--bundle" in capsys.readouterr().out


def test_source_credentials_are_not_recorded():
    assert public_index("https://user:secret@example.com/simple?token=secret") == (
        "https://example.com/simple"
    )


def test_conda_export_is_explicitly_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr("pload.snapshots.probe", lambda _: {"conda": True})
    manager = SnapshotManager(ConfigManager(home=tmp_path))
    with pytest.raises(PloadError, match="Conda"):
        manager.export("native", python=sys.executable)
    assert not manager.path("native").exists()


def test_editable_source_is_not_silently_pinned(tmp_path, monkeypatch):
    monkeypatch.setattr("pload.snapshots.probe", lambda _: {
        "packages": [{"name": "editable", "version": "1.0", "direct_url":
                      json.dumps({"url": "file:///source", "dir_info": {"editable": True}})}],
    })
    manager = SnapshotManager(ConfigManager(home=tmp_path))
    with pytest.raises(PloadError, match="original wheel"):
        manager.export("source", python=sys.executable, bundle="all")
    assert not manager.path("source").exists()


def test_local_repository_refuses_overwrite(tmp_path):
    manager = RepositoryManager(ConfigManager(home=tmp_path / "home"))
    recipe(manager.snapshots.path("demo"))
    manager.add("disk", str(tmp_path / "remote"), "local")
    manager.transfer("disk", "demo", push=True)
    with pytest.raises(PloadError, match="already exists"):
        manager.transfer("disk", "demo", push=True)
    manager.remove("disk")
    validate_bundle(tmp_path / "remote" / "demo")


def test_offline_requirements_cannot_fetch_direct_urls(tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("package @ https://example.invalid/package.whl\n")
    manager = SnapshotManager(ConfigManager(home=tmp_path / "home"))
    with pytest.raises(PloadError, match="validated snapshot"):
        manager.restore(str(requirements), "offline", offline=True)
    assert not manager.config.venv_path.exists()
