import platform
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from pload.cli import build_parser, main, shell_script
from pload.declarative import (
    DeclarativeEnvironmentManager,
    dump_manifest,
    load_manifest,
    validate_manifest,
)
from pload.errors import PloadError
from pload.managers.platform import ConfigManager
from pload.managers.venv import VenvManager
from pload.settings import save_settings
from pload.snapshots import digest, execute


def tiny_wheel(directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "pload_demo-1.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as wheel:
        wheel.writestr("pload_demo.py", "answer = 42\n")
        wheel.writestr(
            "pload_demo-1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: pload-demo\nVersion: 1.0\n",
        )
        wheel.writestr(
            "pload_demo-1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        wheel.writestr("pload_demo-1.0.dist-info/RECORD", "")
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


def test_manifest_roundtrip(tmp_path):
    data = simple_manifest()
    path = tmp_path / "pload.toml"
    path.write_text(dump_manifest(data), encoding="utf-8")
    loaded_path, loaded = load_manifest(path)
    assert loaded_path == path
    assert loaded == data


def test_manifest_requires_exact_pins():
    data = simple_manifest()
    data["environment"]["dependencies"] = ["demo>=1"]
    with pytest.raises(PloadError, match="exact"):
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


def test_manifest_rejects_mismatched_dependency_and_package_locks():
    data = simple_manifest()
    data["environment"]["dependencies"] = ["other==1.0"]
    with pytest.raises(PloadError, match="same pins"):
        validate_manifest(data)


def test_manifest_rejects_unknown_policy_repository():
    data = simple_manifest()
    data["policy"]["repositories"] = ["missing"]
    with pytest.raises(PloadError, match="unknown repositories"):
        validate_manifest(data)


def test_compatible_plan_uses_index_and_offline_reports_missing(tmp_path):
    path = tmp_path / "pload.toml"
    path.write_text(dump_manifest(simple_manifest()), encoding="utf-8")
    manager = DeclarativeEnvironmentManager(ConfigManager(home=tmp_path / "home"))
    assert manager.plan(path)["packages"][0]["selected"]["method"] == "index-resolve"
    assert manager.plan(path, offline=True)["packages"][0]["selected"] is None


def test_exact_configuration_requires_an_artifact_route(tmp_path):
    data = simple_manifest("exact")
    path = tmp_path / "pload.toml"
    path.write_text(dump_manifest(data), encoding="utf-8")
    manager = DeclarativeEnvironmentManager(ConfigManager(home=tmp_path / "home"))
    assert manager.plan(path)["ready"] is False


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
    artifact = data["package"][0]["artifact"][0]
    assert data["sources"]["default"]["url"] == "https://example.invalid/simple"
    assert data["package"][0]["sources"] == ["package-pload-demo"]
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
    manifest.write_text(dump_manifest(data), encoding="utf-8")
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
    manifest.write_text(dump_manifest(data), encoding="utf-8")
    DeclarativeEnvironmentManager(config).apply(manifest)
    assert (repository / "objects" / checksum).is_file()


def test_declarative_commands_and_shell_integration(capsys):
    parser = build_parser()
    assert parser.parse_args(["describe", "v1", "-o", "env.toml"]).output == "env.toml"
    parsed = parser.parse_args([
        "describe", "v1", "-s", "torch=https://download.pytorch.org/whl/cu121",
    ])
    assert parsed.package_sources == ["torch=https://download.pytorch.org/whl/cu121"]
    assert parser.parse_args(["apply"]).file == "pload.toml"
    for command in ("describe", "plan", "apply"):
        assert main([command, "-h"]) == 0
        for shell in ("bash", "zsh", "fish", "powershell"):
            assert command in shell_script(shell)
    assert "--mode" in capsys.readouterr().out
