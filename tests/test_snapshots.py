import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from pload.cli import build_parser, main, shell_script
from pload.errors import PloadError
from pload.managers.platform import ConfigManager
from pload.managers.venv import VenvManager
from pload.reproduction import ReproductionPlanner, summarize_plan
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
    manifest = validate_bundle(snapshot)
    assert manifest["packages"][0]["name"] == "pload-demo"
    assert manifest["packages"][0]["artifacts"][0]["sha256"] == digest(
        snapshot / "wheels" / "pload_demo-1.0-py3-none-any.whl"
    )
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
    for command in ("export", "restore", "plan", "repo"):
        assert main([command, "-h"]) == 0
        for shell in ("bash", "zsh", "fish", "powershell"):
            assert command in shell_script(shell)
    assert "--bundle" in capsys.readouterr().out


def test_plan_command_shows_selected_method(tmp_path, capsys):
    config = ConfigManager(home=tmp_path)
    snapshot = recipe(SnapshotManager(config).path("demo"))
    data = json.loads((snapshot / "snapshot.json").read_text())
    data["index_url"] = "https://pypi.org/simple"
    (snapshot / "requirements.txt").write_text("demo==1.0\n", encoding="utf-8")
    data["files"]["requirements.txt"] = digest(snapshot / "requirements.txt")
    write_json(snapshot / "snapshot.json", data)
    assert main(["-H", str(tmp_path), "plan", "demo", "-a"]) == 0
    output = capsys.readouterr().out
    assert "demo" in output
    assert "recorded-index" in output


def test_restore_parser_keeps_snapshot_and_package_sources_separate():
    args = build_parser().parse_args([
        "restore", "training", "-n", "copy",
        "-s", "torch=https://download.pytorch.org/whl/cu121",
    ])
    assert args.source == "training"
    assert args.package_sources == ["torch=https://download.pytorch.org/whl/cu121"]


def test_planned_restore_tries_next_candidate(tmp_path, monkeypatch):
    manager = SnapshotManager(ConfigManager(home=tmp_path / "home"))
    wheel = tiny_wheel(tmp_path / "wheels")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("pload-demo==1.0\n", encoding="utf-8")
    attempts = []

    def fake_execute(command, capture=True, cwd=None):
        attempts.append(command)
        if "https://unavailable.example/simple" in command:
            raise PloadError("simulated unavailable index")
        return ""

    monkeypatch.setattr("pload.snapshots.execute", fake_execute)
    plans = [{
        "name": "pload-demo", "version": "1.0",
        "selected": {
            "method": "package-index", "location": "https://unavailable.example/simple",
            "availability": "network", "score": 75, "reason": "test",
        },
        "alternatives": [{
            "method": "find-links", "location": str(wheel),
            "availability": "ready", "score": 70, "reason": "test",
        }],
    }]
    manager._execute_plan(tmp_path / "environment", requirements, plans)
    assert any("https://unavailable.example/simple" in command for command in attempts)
    assert any(any(str(wheel) in part for part in command) for command in attempts)


def test_repository_list_alias(tmp_path, capsys):
    assert main(["-H", str(tmp_path), "repo", "ls"]) == 0
    assert capsys.readouterr().out.strip() == "{}"


def test_source_credentials_are_not_recorded():
    assert public_index("https://user:secret@example.com/simple?token=secret") == (
        "https://example.com/simple"
    )


def test_reproduction_planner_prefers_exact_artifacts_then_sources(tmp_path):
    wheel = tiny_wheel(tmp_path / "snapshot" / "wheels")
    data = {
        "packages": [{
            "name": "pload-demo", "version": "1.0",
            "sources": ["https://pypi.org/simple"],
            "artifacts": [{
                "file": "wheels/" + wheel.name,
                "sha256": digest(wheel), "kind": "wheel",
            }],
        }],
    }
    planner = ReproductionPlanner(tmp_path / "snapshot", data)
    plan = planner.plan(sources=["pload-demo=https://download.example/cuda"])
    assert plan[0]["selected"]["method"] == "snapshot-wheel"
    assert [item["method"] for item in plan[0]["alternatives"]][:2] == [
        "package-index", "recorded-index",
    ]
    wheel.unlink()
    online = planner.plan(sources=["pload-demo=https://download.example/cuda"])
    assert online[0]["selected"]["method"] == "package-index"
    assert online[0]["selected"]["availability"] == "network"
    offline = planner.plan(offline=True)
    assert offline[0]["selected"] is None
    assert summarize_plan(offline)["unavailable"] == 1


def test_planner_uses_pip_default_when_recipe_has_no_recorded_index(tmp_path):
    data = {"packages": [{
        "name": "demo", "version": "1.0", "sources": [], "artifacts": [],
    }]}
    plan = ReproductionPlanner(tmp_path / "snapshot", data).plan()
    assert plan[0]["selected"]["method"] == "pip-default-index"
    assert plan[0]["alternatives"][0]["method"] == "pip-default-source-build"


def test_planner_rejects_wrong_cached_hash_and_keeps_multiple_sources(tmp_path):
    snapshot = tmp_path / "snapshot"
    cache = tmp_path / "cache"
    cache.mkdir()
    wheel = tiny_wheel(cache)
    expected = "0" * 64
    data = {"packages": [{
        "name": "pload-demo", "version": "1.0", "sources": [],
        "artifacts": [{"file": "wheels/" + wheel.name, "sha256": expected}],
    }]}
    plan = ReproductionPlanner(snapshot, data, cache=cache).plan(sources=[
        "pload-demo=https://first.example/simple",
        "pload-demo=https://token:secret@second.example/simple?secret=yes",
        "pload-demo=source:https://github.com/example/pload-demo.git",
    ])
    methods = [(item["method"], item["location"])
               for item in [plan[0]["selected"]] + plan[0]["alternatives"]]
    assert ("shared-cache", str(wheel)) not in methods
    assert ("package-index", "https://first.example/simple") in methods
    assert ("package-index", "https://second.example/simple") in methods
    assert ("source-repository", "https://github.com/example/pload-demo.git") in methods


def test_portable_plan_keeps_only_universal_wheels(tmp_path):
    wheel_dir = tmp_path / "snapshot" / "wheels"
    universal = tiny_wheel(wheel_dir)
    native = wheel_dir / "native_pkg-2.0-cp312-cp312-manylinux_2_17_x86_64.whl"
    native.write_bytes(b"native")
    data = {"packages": [
        {"name": "pload-demo", "version": "1.0", "sources": [],
         "artifacts": [{"file": "wheels/" + universal.name, "sha256": digest(universal)}]},
        {"name": "native-pkg", "version": "2.0", "sources": ["https://pypi.org/simple"],
         "artifacts": [{"file": "wheels/" + native.name, "sha256": digest(native)}]},
    ]}
    plans = ReproductionPlanner(tmp_path / "snapshot", data).plan(portable=True)
    assert plans[0]["selected"]["method"] == "snapshot-wheel"
    assert plans[1]["selected"]["method"] == "recorded-index"


def test_export_records_sanitized_package_specific_source(tmp_path, monkeypatch):
    monkeypatch.setattr("pload.snapshots.probe", lambda _: {
        "python": "3.12.1", "implementation": "cpython", "system": "Linux",
        "machine": "x86_64", "packages": [
            {"name": "torch", "version": "2.5.0+cu121", "direct_url": None},
        ],
    })
    manager = SnapshotManager(ConfigManager(home=tmp_path))
    snapshot = manager.export(
        "cuda", python=sys.executable,
        sources=["torch=https://token:secret@download.pytorch.org/whl/cu121?token=secret"],
    )
    package = validate_bundle(snapshot)["packages"][0]
    assert package["sources"] == [{
        "kind": "index", "url": "https://download.pytorch.org/whl/cu121",
    }]


def test_export_preserves_safe_source_fragment(tmp_path, monkeypatch):
    monkeypatch.setattr("pload.snapshots.probe", lambda _: {
        "python": "3.12.1", "implementation": "cpython", "system": "Linux",
        "machine": "x86_64", "packages": [
            {"name": "demo", "version": "1.0", "direct_url": None},
        ],
    })
    manager = SnapshotManager(ConfigManager(home=tmp_path))
    snapshot = manager.export(
        "source", python=sys.executable,
        sources=["demo=source:https://token:secret@example.com/demo.git?token=x#v1.0"],
    )
    package = validate_bundle(snapshot)["packages"][0]
    assert package["sources"] == [{
        "kind": "source", "url": "https://example.com/demo.git#v1.0",
    }]


def test_export_downloads_special_package_from_its_own_index(tmp_path, monkeypatch):
    monkeypatch.setattr("pload.snapshots.probe", lambda _: {
        "python": "3.12.1", "implementation": "cpython", "system": "Linux",
        "machine": "x86_64", "packages": [
            {"name": "torch", "version": "2.5.0+cu121", "direct_url": None},
        ],
    })
    source_wheel = tiny_wheel(tmp_path / "fixture")
    calls = []

    def fake_execute(command, capture=True, cwd=None):
        calls.append(command)
        if "--no-index" in command:
            raise PloadError("not cached")
        if "https://download.pytorch.org/whl/cu121" not in command:
            raise PloadError("wrong index")
        destination = Path(command[command.index("--dest") + 1])
        shutil.copyfile(source_wheel, destination / "torch-2.5.0+cu121-py3-none-any.whl")
        return ""

    monkeypatch.setattr("pload.snapshots.execute", fake_execute)
    manager = SnapshotManager(ConfigManager(home=tmp_path / "home"))
    snapshot = manager.export(
        "cuda", python=sys.executable, bundle="torch",
        sources=["torch=https://download.pytorch.org/whl/cu121"],
    )
    assert any("https://download.pytorch.org/whl/cu121" in call for call in calls)
    package = validate_bundle(snapshot)["packages"][0]
    assert package["artifacts"][0]["file"].startswith("wheels/torch-")


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
