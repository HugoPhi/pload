import platform
import shutil
import sys
import zipfile
from pathlib import Path

import pytest
from packaging.tags import platform_tags

import pload.declarative as declarative_module
from pload.cli import build_parser, main, shell_script
from pload.declarative import (
    DeclarativeEnvironmentManager,
    dump_lock,
    dump_manifest,
    load_lock,
    load_manifest,
    lock_path,
    validate_manifest,
)
from pload.errors import PloadError
from pload.managers.platform import ConfigManager
from pload.managers.venv import VenvManager
from pload.settings import save_settings
from pload.snapshots import digest, execute


def tiny_wheel(directory, tag="py3-none-any", distribution="pload_demo", version="1.0"):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{distribution}-{version}-{tag}.whl"
    module = distribution.replace("-", "_")
    project = distribution.replace("_", "-")
    with zipfile.ZipFile(path, "w") as wheel:
        wheel.writestr(f"{module}.py", "answer = 42\n")
        wheel.writestr(
            f"{distribution}-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: {project}\nVersion: {version}\n",
        )
        wheel.writestr(
            f"{distribution}-{version}.dist-info/WHEEL",
            f"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: {tag}\n",
        )
        wheel.writestr(f"{distribution}-{version}.dist-info/RECORD", "")
    return path


def simple_manifest(mode="compatible"):
    return {
        "schema": 1,
        "name": "demo",
        "environment": {
            "python": "3.12.1", "implementation": "cpython",
            "system": "Linux", "machine": "x86_64",
            "dependencies": ["demo==1.0"],
        },
        "policy": {
            "reproducibility": mode, "network": "allow",
            "source_build": "fallback", "publish_missing_artifacts": True,
            "repositories": [],
        },
        "sources": {"default": {"kind": "index", "url": "https://pypi.org/simple"}},
        "repositories": {},
        "capabilities": {},
        "package": [{
            "name": "demo", "version": "1.0", "sources": ["default"], "artifact": [],
        }],
    }


def write_configuration(path, data, with_lock=True):
    path.write_text(dump_manifest(data), encoding="utf-8")
    if with_lock and data.get("package"):
        locked = dict(data)
        locked["resolved_dependencies"] = [
            f"{item['name']}=={item['version']}" for item in data["package"]
        ]
        lock_path(path).write_text(dump_lock(path, locked), encoding="utf-8")


def test_manifest_roundtrip(tmp_path):
    data = simple_manifest()
    path = tmp_path / "pload.toml"
    write_configuration(path, data)
    loaded_path, loaded = load_manifest(path)
    assert loaded_path == path
    assert loaded["environment"] == data["environment"]
    assert loaded["package"] == []
    _, locked, current = load_lock(path, loaded)
    assert current is True
    assert locked["package"] == data["package"]


def test_lock_migrates_legacy_embedded_lock_without_resolving(tmp_path, monkeypatch):
    data = simple_manifest("exact")
    path = tmp_path / "pload.toml"
    legacy = dump_manifest(data) + """
[[package]]
name = "demo"
version = "1.0"
sources = ["default"]
"""
    path.write_text(legacy, encoding="utf-8")
    monkeypatch.setattr(
        declarative_module, "execute",
        lambda *args, **kwargs: pytest.fail("legacy migration invoked the resolver"),
    )

    result = DeclarativeEnvironmentManager(ConfigManager(home=tmp_path / "home")).lock(path)

    assert result["migrated"] is True
    assert "[[package]]" not in path.read_text(encoding="utf-8")
    _, configuration = load_manifest(path)
    _, locked, current = load_lock(path, configuration)
    assert current is True
    assert locked["package"][0]["name"] == "demo"


def test_manifest_accepts_unpinned_requirements_but_rejects_direct_urls():
    data = simple_manifest()
    data["environment"]["dependencies"] = ["demo>=1"]
    validate_manifest(data)
    data["environment"]["dependencies"] = ["demo @ https://example.com/demo.whl"]
    with pytest.raises(PloadError, match="direct-URL"):
        validate_manifest(data)


def test_manifest_rejects_secrets_in_shareable_sources():
    data = simple_manifest()
    data["sources"]["default"]["url"] = "https://user:secret@example.com/simple?token=x"
    with pytest.raises(PloadError, match="credentials"):
        validate_manifest(data)


def test_manifest_rejects_dangling_provider_references():
    data = simple_manifest()
    data["package"][0]["sources"] = ["missing"]
    with pytest.raises(PloadError, match="unknown source"):
        validate_manifest(data)


def test_manifest_allows_dependency_edits_to_make_the_package_lock_stale():
    data = simple_manifest()
    data["environment"]["dependencies"] = ["other==1.0"]
    validate_manifest(data)


def test_manifest_rejects_unknown_policy_repository():
    data = simple_manifest()
    data["policy"]["repositories"] = ["missing"]
    with pytest.raises(PloadError, match="unknown repositories"):
        validate_manifest(data)


def test_compatible_plan_uses_index_and_offline_reports_missing(tmp_path):
    path = tmp_path / "pload.toml"
    write_configuration(path, simple_manifest())
    manager = DeclarativeEnvironmentManager(ConfigManager(home=tmp_path / "home"))
    assert manager.plan(path)["packages"][0]["selected"]["method"] == "index-resolve"
    assert manager.plan(path, offline=True)["packages"][0]["selected"] is None


def test_exact_configuration_requires_an_artifact_route(tmp_path):
    data = simple_manifest("exact")
    path = tmp_path / "pload.toml"
    write_configuration(path, data)
    manager = DeclarativeEnvironmentManager(ConfigManager(home=tmp_path / "home"))
    assert manager.plan(path)["ready"] is False


def test_changed_python_rejects_incompatible_cached_wheel_before_apply(tmp_path, monkeypatch):
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: Path(sys.executable)
    incompatible_tag = f"cp37-cp37m-{next(iter(platform_tags()))}"
    wheel = tiny_wheel(tmp_path / "fixture", incompatible_tag)
    data = simple_manifest("exact")
    data["name"] = "changed-python"
    data["environment"].update({
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "system": platform.system(),
        "machine": platform.machine(),
        "dependencies": ["pload-demo==1.0"],
    })
    data["package"] = [{
        "name": "pload-demo", "version": "1.0", "sources": ["default"],
        "artifact": [{
            "filename": wheel.name, "sha256": digest(wheel),
            "tags": [incompatible_tag], "repositories": [],
        }],
    }]
    manifest = tmp_path / "pload.toml"
    write_configuration(manifest, data)
    manager = DeclarativeEnvironmentManager(config)
    manager.cache.mkdir(parents=True)
    shutil.copyfile(wheel, manager.cache / wheel.name)

    plan = manager.plan(manifest)
    package = plan["packages"][0]
    assert package["selected"] is None
    assert package["rejections"][0]["artifact"] == wheel.name
    assert "incompatible with" in package["rejections"][0]["reason"]
    assert plan["ready"] is False

    monkeypatch.setattr(
        VenvManager, "create_venv",
        lambda *args, **kwargs: pytest.fail("apply created an environment for an invalid plan"),
    )
    monkeypatch.setattr(
        manager, "_acquire",
        lambda *args, **kwargs: pytest.fail("apply downloaded an incompatible artifact"),
    )
    with pytest.raises(PloadError, match="incompatible with"):
        manager.apply(manifest)

    data["policy"]["reproducibility"] = "compatible"
    write_configuration(manifest, data)
    compatible = manager.plan(manifest)["packages"][0]
    assert compatible["selected"]["method"] == "index-resolve"
    assert compatible["selected"]["status"] == "network"


def test_cache_plan_applies_without_package_network_access(tmp_path, monkeypatch):
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: Path(sys.executable)
    wheel = tiny_wheel(tmp_path / "fixture")
    data = simple_manifest("exact")
    data["name"] = "cache-only"
    data["environment"].update({
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "system": platform.system(),
        "machine": platform.machine(),
        "dependencies": ["pload-demo==1.0"],
    })
    data["policy"]["publish_missing_artifacts"] = False
    data["package"] = [{
        "name": "pload-demo", "version": "1.0", "sources": ["default"],
        "artifact": [{
            "filename": wheel.name, "sha256": digest(wheel),
            "tags": ["py3-none-any"], "repositories": [],
        }],
    }]
    manifest = tmp_path / "pload.toml"
    write_configuration(manifest, data)
    manager = DeclarativeEnvironmentManager(config)
    manager.cache.mkdir(parents=True)
    shutil.copyfile(wheel, manager.cache / wheel.name)
    assert manager.plan(manifest)["packages"][0]["selected"]["method"] == "cache"

    original_execute = declarative_module.execute

    def reject_package_network(command, *args, **kwargs):
        if "download" in command:
            pytest.fail("a cache plan attempted a package download")
        if "install" in command and "--no-index" not in command:
            pytest.fail("a cache plan allowed pip index access")
        return original_execute(command, *args, **kwargs)

    monkeypatch.setattr(declarative_module, "execute", reject_package_network)
    restored = manager.apply(manifest)
    output = original_execute([
        config.get_pip_command(restored)[0], "-c", "import pload_demo; print(pload_demo.answer)",
    ])
    assert output == "42"


def test_lock_resolves_once_and_plan_remains_read_only(tmp_path, monkeypatch):
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: Path(sys.executable)
    wheel = tiny_wheel(tmp_path / "fixture")
    data = simple_manifest("exact")
    data["name"] = "auto-locked"
    data["environment"].update({
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "system": platform.system(),
        "machine": platform.machine(),
        "dependencies": ["pload-demo>=1"],
    })
    data["policy"]["publish_missing_artifacts"] = False
    data["package"] = []
    manifest = tmp_path / "pload.toml"
    write_configuration(manifest, data, with_lock=False)
    manager = DeclarativeEnvironmentManager(config)
    original_execute = declarative_module.execute
    download_calls = []

    def fake_resolver(command, *args, **kwargs):
        if "download" in command:
            download_calls.append(command)
            assert "--no-deps" not in command
            destination = Path(command[command.index("--dest") + 1])
            shutil.copyfile(wheel, destination / wheel.name)
            return ""
        if "install" in command:
            assert "--no-index" in command
        return original_execute(command, *args, **kwargs)

    monkeypatch.setattr(declarative_module, "execute", fake_resolver)
    before = manifest.read_bytes()
    pending = manager.plan(manifest)
    assert pending["lock"]["status"] == "missing"
    assert pending["lock"]["required"] is True
    assert pending["packages"][0]["selected"]["method"] == "lock-required"
    assert download_calls == []
    assert manifest.read_bytes() == before
    assert not lock_path(manifest).exists()

    result = manager.lock(manifest)
    assert result["requested"] == ["pload-demo>=1"]
    assert result["resolved"] == ["pload-demo==1.0"]
    first = manager.plan(manifest)
    assert first["lock"]["status"] == "current"
    assert first["packages"][0]["selected"]["method"] == "cache"
    _, configuration = load_manifest(manifest)
    assert configuration["environment"]["dependencies"] == ["pload-demo>=1"]
    _, locked, current = load_lock(manifest, configuration)
    assert current is True
    assert locked["environment"]["dependencies"] == ["pload-demo==1.0"]
    assert locked["package"][0]["artifact"][0]["filename"] == wheel.name

    second = manager.plan(manifest)
    assert second["lock"]["status"] == "current"
    assert len(download_calls) == 1
    restored = manager.apply(manifest)
    assert len(download_calls) == 1
    output = original_execute([
        config.get_pip_command(restored)[0], "-c", "import pload_demo; print(pload_demo.answer)",
    ])
    assert output == "42"


def test_plan_relocks_when_new_dependency_makes_existing_lock_stale(tmp_path, monkeypatch):
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: Path(sys.executable)
    demo = tiny_wheel(tmp_path / "fixture")
    extra = tiny_wheel(tmp_path / "fixture", distribution="extra_demo")
    data = simple_manifest("exact")
    data["environment"].update({
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "system": platform.system(),
        "machine": platform.machine(),
        "dependencies": ["pload-demo==1.0"],
    })
    manifest = tmp_path / "pload.toml"
    write_configuration(manifest, data)
    data["environment"]["dependencies"].append("extra-demo")
    write_configuration(manifest, data, with_lock=False)
    manager = DeclarativeEnvironmentManager(config)
    calls = []

    def fake_resolver(command, *args, **kwargs):
        if "download" not in command:
            return ""
        calls.append(command)
        assert "--find-links" in command
        assert "pload-demo==1.0" in command
        assert "extra-demo" in command
        destination = Path(command[command.index("--dest") + 1])
        shutil.copyfile(demo, destination / demo.name)
        shutil.copyfile(extra, destination / extra.name)
        return ""

    monkeypatch.setattr(declarative_module, "execute", fake_resolver)
    before_manifest = manifest.read_bytes()
    before_lock = lock_path(manifest).read_bytes()
    plan = manager.plan(manifest)
    assert plan["lock"]["status"] == "stale"
    assert plan["lock"]["required"] is True
    assert calls == []
    assert manifest.read_bytes() == before_manifest
    assert lock_path(manifest).read_bytes() == before_lock
    with pytest.raises(PloadError, match="pload lock"):
        manager.apply(manifest)

    progress = []
    result = manager.lock(manifest, progress=progress.append)
    assert len(calls) == 1
    assert progress == [
        f"Configuration changed; resolving dependencies for Python {platform.python_version()}"
    ]
    assert result["requested"] == ["pload-demo==1.0", "extra-demo"]
    assert result["resolved"] == ["extra-demo==1.0", "pload-demo==1.0"]
    _, configuration = load_manifest(manifest)
    assert configuration["environment"]["dependencies"] == [
        "pload-demo==1.0", "extra-demo",
    ]
    _, locked, current = load_lock(manifest, configuration)
    assert current is True
    assert {item["name"] for item in locked["package"]} == {"extra-demo", "pload-demo"}


def test_describe_plan_apply_through_content_repository(tmp_path):
    source_config = ConfigManager(home=tmp_path / "source-home")
    repository = tmp_path / "artifact-store"
    save_settings(source_config.home, {
        "repositories": {"lab": {"kind": "local", "location": str(repository)}},
        "pip_index": "https://user:secret@example.invalid/simple?token=x",
    })
    source_config = ConfigManager(home=tmp_path / "source-home")
    wheel = tiny_wheel(tmp_path / "fixture")
    source = VenvManager(source_config).create_venv(name="source")
    execute(source_config.get_pip_command(source) + [
        "install", "--no-index", "--find-links", str(wheel.parent), "pload-demo==1.0",
    ])
    manager = DeclarativeEnvironmentManager(source_config)
    manager.cache.mkdir(parents=True)
    shutil.copyfile(wheel, manager.cache / wheel.name)
    describe_progress = []
    manifest = manager.describe(
        "source", tmp_path / "pload.toml", name="restored",
        sources=["pload-demo=https://download.example.invalid/cu121"],
        progress=describe_progress.append,
    )
    _, data = load_manifest(manifest)
    _, locked, current = load_lock(manifest, data)
    assert current is True
    artifact = locked["package"][0]["artifact"][0]
    assert data["sources"]["default"]["url"] == "https://example.invalid/simple"
    assert locked["package"][0]["sources"] == ["package-pload-demo"]
    assert data["sources"]["package-pload-demo"]["url"].endswith("/cu121")
    assert artifact["repositories"] == ["lab"]
    assert (repository / "objects" / artifact["sha256"]).is_file()
    assert any("Locking pload-demo==1.0" in item for item in describe_progress)
    assert any("Publishing 1 locked artifact" in item for item in describe_progress)

    shutil.rmtree(source_config.home / "cache")
    target_config = ConfigManager(home=tmp_path / "target-home")
    target_config.get_python_path = lambda version=None: Path(sys.executable)
    target = DeclarativeEnvironmentManager(target_config)
    plan = target.plan(manifest)
    assert plan["packages"][0]["selected"]["method"] == "repository"
    apply_progress = []
    restored = target.apply(manifest, progress=apply_progress.append)
    output = execute([target_config.get_pip_command(restored)[0], "-c",
                      "import pload_demo; print(pload_demo.answer)"])
    assert output == "42"
    assert target.apply(manifest) == restored
    assert digest(target.cache / artifact["filename"]) == artifact["sha256"]
    assert any("Preparing pload-demo==1.0" in item for item in apply_progress)
    assert any("Verified exact requirements" in item for item in apply_progress)


def test_apply_rolls_back_a_new_environment_after_install_failure(tmp_path):
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: Path(sys.executable)
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    broken = artifact_dir / "demo-1.0-py3-none-any.whl"
    broken.write_bytes(b"not a wheel")
    data = simple_manifest("exact")
    data["environment"].update({
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "system": platform.system(),
        "machine": platform.machine(),
    })
    data["package"][0]["artifact"] = [{
        "filename": broken.name, "sha256": digest(broken),
        "tags": ["py3-none-any"], "repositories": [],
    }]
    manifest = tmp_path / "pload.toml"
    write_configuration(manifest, data)
    with pytest.raises(PloadError):
        DeclarativeEnvironmentManager(config).apply(manifest)
    with pytest.raises(PloadError):
        VenvManager(config).resolve_existing("demo")


def test_apply_publishes_acquired_artifacts_to_policy_repository(tmp_path):
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: Path(sys.executable)
    wheel = tiny_wheel(tmp_path / "artifacts")
    checksum = digest(wheel)
    repository = tmp_path / "store"
    data = simple_manifest("exact")
    data["name"] = "published"
    data["environment"].update({
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "system": platform.system(),
        "machine": platform.machine(),
        "dependencies": ["pload-demo==1.0"],
    })
    data["policy"]["repositories"] = ["lab"]
    data["repositories"] = {
        "lab": {"kind": "local", "location": str(repository)},
    }
    data["package"] = [{
        "name": "pload-demo", "version": "1.0", "sources": ["default"],
        "artifact": [{
            "filename": wheel.name, "sha256": checksum,
            "tags": ["py3-none-any"], "repositories": [],
        }],
    }]
    manifest = tmp_path / "pload.toml"
    write_configuration(manifest, data)
    DeclarativeEnvironmentManager(config).apply(manifest)
    assert (repository / "objects" / checksum).is_file()


def test_declarative_commands_and_shell_integration(capsys):
    parser = build_parser()
    assert parser.parse_args(["describe", "v1", "-o", "env.toml"]).output == "env.toml"
    parsed = parser.parse_args([
        "describe", "v1", "-s", "torch=https://download.pytorch.org/whl/cu121",
    ])
    assert parsed.package_sources == ["torch=https://download.pytorch.org/whl/cu121"]
    assert parser.parse_args(["lock"]).file == "pload.toml"
    assert parser.parse_args(["apply"]).file == "pload.toml"
    for command in ("describe", "lock", "plan", "apply"):
        assert main([command, "-h"]) == 0
        for shell in ("bash", "zsh", "fish", "powershell"):
            assert command in shell_script(shell)
    assert "--mode" in capsys.readouterr().out
