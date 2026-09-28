import hashlib
import io
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
    ArtifactRepository,
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
from pload.resource_plan import file_digest, write_plan
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


def plan_and_save(manager, path, **kwargs):
    plan = manager.plan(path, **kwargs)
    manager.save_plan(path, plan)
    return plan


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


def test_manifest_roundtrip_with_automatic_plan_and_package_override(tmp_path):
    data = simple_manifest()
    data["plan"] = {
        "mode": "auto",
        "packages": {
            "numpy": {"method": "index-exact", "location": "default"},
        },
    }
    path = tmp_path / "pload.toml"
    write_configuration(path, data)

    _, loaded = load_manifest(path)

    assert loaded["plan"] == data["plan"]


def test_manifest_rejects_invalid_planning_mode_and_route():
    data = simple_manifest()
    data["plan"] = {"mode": "always-guess"}
    with pytest.raises(PloadError, match="plan.mode"):
        validate_manifest(data)

    data["plan"] = {"mode": "auto", "packages": {"demo": {"method": "magic"}}}
    with pytest.raises(PloadError, match="plan.packages.demo.method"):
        validate_manifest(data)


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


def test_plan_analysis_does_not_create_or_overwrite_saved_choices(tmp_path):
    path = tmp_path / "pload.toml"
    write_configuration(path, simple_manifest())
    manager = DeclarativeEnvironmentManager(ConfigManager(home=tmp_path / "home"))

    plan = manager.plan(path)
    saved_path = Path(plan["plan_path"])
    assert not saved_path.exists()

    manager.save_plan(path, plan)
    before = saved_path.read_bytes()
    manager.plan(path)
    assert saved_path.read_bytes() == before


def test_plan_uses_measurements_instead_of_fixed_fake_times(tmp_path, monkeypatch):
    path = tmp_path / "pload.toml"
    write_configuration(path, simple_manifest())
    monkeypatch.setattr(
        DeclarativeEnvironmentManager, "_network_rtt", staticmethod(lambda url: 0.123),
    )

    route = DeclarativeEnvironmentManager(
        ConfigManager(home=tmp_path / "home")
    ).plan(path)["packages"][0]["selected"]

    assert route["measurement"] == "RTT 123 ms"
    assert "estimated_seconds" not in route


def test_automatic_plan_honors_package_route_override(tmp_path):
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: Path(sys.executable)
    wheel = tiny_wheel(tmp_path / "fixture")
    data = simple_manifest("exact")
    data["environment"].update({
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "system": platform.system(),
        "machine": platform.machine(),
    })
    data["package"][0]["artifact"] = [{
        "filename": wheel.name, "sha256": digest(wheel),
        "tags": ["py3-none-any"], "repositories": [],
        "url": "https://files.invalid/" + wheel.name,
    }]
    data["plan"] = {
        "mode": "auto",
        "packages": {"demo": {"method": "index-exact", "location": "default"}},
    }
    manifest = tmp_path / "pload.toml"
    write_configuration(manifest, data)
    manager = DeclarativeEnvironmentManager(config)
    manager.cache.mkdir(parents=True)
    shutil.copyfile(wheel, manager.cache / wheel.name)

    result = manager.plan(manifest)

    assert result["planning_mode"] == "auto"
    assert result["packages"][0]["selected"]["method"] == "index-exact"
    assert result["packages"][0]["alternatives"] == []


def test_configured_route_must_exist_in_automatic_plan(tmp_path):
    data = simple_manifest()
    data["plan"] = {
        "mode": "auto",
        "packages": {"demo": {"method": "repository", "location": "missing"}},
    }
    path = tmp_path / "pload.toml"
    write_configuration(path, data)

    package = DeclarativeEnvironmentManager(
        ConfigManager(home=tmp_path / "home")
    ).plan(path)["packages"][0]

    assert package["selected"] is None
    assert package["rejections"][0]["reason"].endswith("repository:missing")


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

    plan = plan_and_save(manager, manifest)
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
    assert plan_and_save(manager, manifest)["packages"][0]["selected"]["method"] == "cache"

    original_execute = declarative_module.execute

    def reject_package_network(command, *args, **kwargs):
        if "download" in command:
            pytest.fail("a cache plan attempted a package download")
        if "install" in command and "--no-index" not in command:
            pytest.fail("a cache plan allowed pip index access")
        return original_execute(command, *args, **kwargs)

    monkeypatch.setattr(declarative_module, "execute", reject_package_network)
    progress = []
    restored = manager.apply(manifest, progress=progress.append)
    output = original_execute([
        config.get_pip_command(restored)[0], "-c", "import pload_demo; print(pload_demo.answer)",
    ])
    assert output == "42"
    assert any(
        event.startswith("DOWNLOAD\tpload-demo==1.0\t") for event in progress
    )


def test_apply_can_materialize_project_local_environment(tmp_path):
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: Path(sys.executable)
    data = simple_manifest("exact")
    data["environment"].update({
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "system": platform.system(),
        "machine": platform.machine(),
        "dependencies": [],
    })
    data["package"] = []
    project = tmp_path / "project"
    project.mkdir()
    manifest = project / "pload.toml"
    write_configuration(manifest, data, with_lock=False)
    manager = DeclarativeEnvironmentManager(config)
    plan_and_save(manager, manifest)

    restored = manager.apply(manifest, target=project / ".venv")

    assert restored == project / ".venv"
    assert (restored / "pyvenv.cfg").is_file()
    assert manager.apply(manifest, target=project / ".venv") == restored


def test_plan_discovers_and_apply_uses_exact_external_cache(tmp_path, monkeypatch):
    external_cache = tmp_path / "pip-cache"
    wheel = tiny_wheel(external_cache)
    config_home = tmp_path / "home"
    save_settings(config_home, {"resource_cache_dirs": [str(external_cache)]})
    config = ConfigManager(home=config_home)
    config.get_python_path = lambda version=None: Path(sys.executable)
    data = simple_manifest("exact")
    data["name"] = "external-cache"
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
            "tags": ["py3-none-any"], "repositories": [],
        }],
    }]
    manifest = tmp_path / "project" / "pload.toml"
    manifest.parent.mkdir()
    write_configuration(manifest, data)
    manager = DeclarativeEnvironmentManager(config)

    selected = plan_and_save(manager, manifest)["packages"][0]["selected"]
    assert selected["method"] == "external-cache"
    assert selected["location"] == str(wheel.resolve())
    manager.cache.mkdir(parents=True)
    shutil.copyfile(wheel, manager.cache / wheel.name)

    original_execute = declarative_module.execute
    original_acquire = manager._acquire
    acquisition_methods = []

    def record_acquisition(*args, **kwargs):
        acquisition_methods.append(args[3]["method"])
        return original_acquire(*args, **kwargs)

    def reject_download(command, *args, **kwargs):
        if "download" in command:
            pytest.fail("external-cache route attempted a download")
        return original_execute(command, *args, **kwargs)

    monkeypatch.setattr(declarative_module, "execute", reject_download)
    monkeypatch.setattr(manager, "_acquire", record_acquisition)
    restored = manager.apply(manifest)
    assert acquisition_methods == ["external-cache"]
    assert digest(manager.cache / wheel.name) == digest(wheel)
    assert original_execute([
        config.get_pip_command(restored)[0], "-c",
        "import pload_demo; print(pload_demo.answer)",
    ]) == "42"


def test_plan_reuses_package_from_compatible_pload_environment(tmp_path, monkeypatch):
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: Path(sys.executable)
    wheel = tiny_wheel(tmp_path / "fixture")
    source = VenvManager(config).create_venv(name="package-source")
    original_execute = declarative_module.execute
    original_execute(config.get_pip_command(source) + [
        "install", "--no-index", "--find-links", str(wheel.parent), "pload-demo==1.0",
    ])
    data = simple_manifest("exact")
    data["name"] = "environment-copy"
    data["environment"].update({
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "system": platform.system(),
        "machine": platform.machine(),
        "dependencies": ["pload-demo==1.0"],
    })
    data["package"] = [{
        "name": "pload-demo", "version": "1.0", "sources": ["default"],
        "artifact": [],
    }]
    manifest = tmp_path / "project" / "pload.toml"
    manifest.parent.mkdir()
    write_configuration(manifest, data)
    manager = DeclarativeEnvironmentManager(config)

    selected = plan_and_save(manager, manifest)["packages"][0]["selected"]
    assert selected["method"] == "environment-copy"
    assert selected["location"] == str(source)
    assert len(selected["fingerprint"]) == 64

    def reject_package_network(command, *args, **kwargs):
        if "download" in command or ("install" in command and "--no-index" not in command):
            pytest.fail("environment-copy route attempted package network access")
        return original_execute(command, *args, **kwargs)

    monkeypatch.setattr(declarative_module, "execute", reject_package_network)
    restored = manager.apply(manifest)
    assert original_execute([
        config.get_pip_command(restored)[0], "-c",
        "import pload_demo; print(pload_demo.answer)",
    ]) == "42"


def test_plan_resolves_metadata_once_without_downloading_wheels(tmp_path, monkeypatch):
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
    resolver_calls = []

    def fake_metadata(requirements, sources, environment, supported_tags):
        resolver_calls.append(list(requirements))
        return [{
            "name": "pload-demo", "version": "1.0", "sources": ["default"],
            "artifact": [{
                "filename": wheel.name, "sha256": digest(wheel),
                "tags": ["py3-none-any"], "repositories": [],
                "url": "https://example.invalid/" + wheel.name,
                "size": wheel.stat().st_size, "metadata_sha256": "",
            }],
        }]

    monkeypatch.setattr(declarative_module, "resolve_metadata", fake_metadata)
    before = manifest.read_bytes()
    first = manager.plan(manifest)
    assert first["lock"]["status"] == "generated"
    assert first["lock"]["required"] is False
    assert first["packages"][0]["selected"]["method"] == "index-exact"
    assert resolver_calls == [["pload-demo>=1"]]
    assert manifest.read_bytes() == before
    assert lock_path(manifest).is_file()
    _, configuration = load_manifest(manifest)
    assert configuration["environment"]["dependencies"] == ["pload-demo>=1"]
    _, locked, current = load_lock(manifest, configuration)
    assert current is True
    assert locked["environment"]["dependencies"] == ["pload-demo==1.0"]
    assert locked["package"][0]["artifact"][0]["filename"] == wheel.name

    second = manager.plan(manifest)
    assert second["lock"]["status"] == "current"
    assert len(resolver_calls) == 1
    manager.cache.mkdir(parents=True)
    shutil.copyfile(wheel, manager.cache / wheel.name)
    plan_and_save(manager, manifest)
    restored = manager.apply(manifest)
    assert len(resolver_calls) == 1
    output = original_execute([
        config.get_pip_command(restored)[0], "-c", "import pload_demo; print(pload_demo.answer)",
    ])
    assert output == "42"


def test_plan_marks_only_user_declared_packages_as_direct(tmp_path, monkeypatch):
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: Path(sys.executable)
    root_wheel = tiny_wheel(tmp_path / "fixture", distribution="root_demo")
    child_wheel = tiny_wheel(tmp_path / "fixture", distribution="child_demo")
    data = simple_manifest("exact")
    data["environment"].update({
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "system": platform.system(),
        "machine": platform.machine(),
        "dependencies": ["root-demo"],
    })
    data["package"] = []
    manifest = tmp_path / "pload.toml"
    write_configuration(manifest, data, with_lock=False)

    def fake_metadata(requirements, sources, environment, supported_tags):
        return [
            {"name": name, "version": "1.0", "sources": ["default"],
             "artifact": [{"filename": wheel.name, "sha256": digest(wheel),
                            "tags": ["py3-none-any"], "repositories": []}]}
            for name, wheel in (("child-demo", child_wheel), ("root-demo", root_wheel))
        ]

    monkeypatch.setattr(declarative_module, "resolve_metadata", fake_metadata)
    plan = DeclarativeEnvironmentManager(config).plan(manifest)

    assert {item["name"]: item["direct"] for item in plan["packages"]} == {
        "child-demo": False, "root-demo": True,
    }


def test_plan_refreshes_stale_lock_using_only_metadata(tmp_path, monkeypatch):
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

    def fake_metadata(requirements, sources, environment, supported_tags):
        calls.append(list(requirements))
        return [
            {"name": name, "version": "1.0", "sources": ["default"],
             "artifact": [{"filename": wheel.name, "sha256": digest(wheel),
                            "tags": ["py3-none-any"], "repositories": []}]}
            for name, wheel in (("pload-demo", demo), ("extra-demo", extra))
        ]

    monkeypatch.setattr(declarative_module, "resolve_metadata", fake_metadata)
    before_manifest = manifest.read_bytes()
    before_lock = lock_path(manifest).read_bytes()
    plan = manager.plan(manifest)
    assert plan["lock"]["status"] == "generated"
    assert plan["lock"]["required"] is False
    assert calls == [["pload-demo==1.0", "extra-demo"]]
    assert manifest.read_bytes() == before_manifest
    assert lock_path(manifest).read_bytes() != before_lock
    _, configuration = load_manifest(manifest)
    assert configuration["environment"]["dependencies"] == [
        "pload-demo==1.0", "extra-demo",
    ]
    _, locked, current = load_lock(manifest, configuration)
    assert current is True
    assert {item["name"] for item in locked["package"]} == {"extra-demo", "pload-demo"}


def test_describe_plan_apply_through_content_repository(tmp_path, monkeypatch):
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
    assert artifact["repositories"] == []
    assert not (repository / "objects" / artifact["sha256"]).exists()
    manager.publish_package("pload-demo", "source", "lab")
    assert (repository / "objects" / artifact["sha256"]).is_file()
    assert any("Locking pload-demo==1.0" in item for item in describe_progress)
    assert not any("Publishing" in item for item in describe_progress)

    shutil.rmtree(source_config.home / "cache")
    target_config = ConfigManager(home=tmp_path / "target-home")
    target_config.get_python_path = lambda version=None: Path(sys.executable)
    target = DeclarativeEnvironmentManager(target_config)
    plan = plan_and_save(target, manifest)
    assert plan["packages"][0]["selected"]["method"] == "repository"
    target.cache.mkdir(parents=True)
    shutil.copyfile(wheel, target.cache / artifact["filename"])
    original_fetch = declarative_module.ArtifactRepository.fetch.__func__
    fetches = []

    def record_fetch(cls, *args, **kwargs):
        fetches.append(args[1])
        return original_fetch(cls, *args, **kwargs)

    monkeypatch.setattr(
        declarative_module.ArtifactRepository, "fetch", classmethod(record_fetch),
    )
    apply_progress = []
    restored = target.apply(manifest, progress=apply_progress.append)
    assert fetches == [artifact["sha256"]]
    output = execute([target_config.get_pip_command(restored)[0], "-c",
                      "import pload_demo; print(pload_demo.answer)"])
    assert output == "42"
    assert target.apply(manifest) == restored
    assert digest(target.cache / artifact["filename"]) == artifact["sha256"]
    assert any(
        item.startswith("PACKAGE\t1/1\trepository\tpload-demo==1.0")
        for item in apply_progress
    )
    assert any("DONE verified exact requirements" in item for item in apply_progress)


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


def test_apply_requires_a_saved_plan_and_never_auto_publishes(tmp_path):
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
    manager = DeclarativeEnvironmentManager(config)
    with pytest.raises(PloadError, match="plan is missing"):
        manager.apply(manifest)
    plan_and_save(manager, manifest)
    manager.apply(manifest)
    assert not (repository / "objects" / checksum).exists()


def test_remote_add_explicitly_publishes_one_installed_package(tmp_path):
    repository = tmp_path / "remote"
    config_home = tmp_path / "home"
    save_settings(config_home, {
        "repositories": {"lab": {"kind": "local", "location": str(repository)}},
    })
    config = ConfigManager(home=config_home)
    config.get_python_path = lambda version=None: Path(sys.executable)
    wheel = tiny_wheel(tmp_path / "fixture")
    source = VenvManager(config).create_venv(name="remote-source")
    execute(config.get_pip_command(source) + [
        "install", "--no-index", "--find-links", str(wheel.parent), "pload-demo==1.0",
    ])
    manager = DeclarativeEnvironmentManager(config)
    manager.cache.mkdir(parents=True)
    shutil.copyfile(wheel, manager.cache / wheel.name)

    result = manager.publish_package("pload-demo", "remote-source", "lab")

    assert result["sha256"] == digest(wheel)
    assert (repository / "objects" / digest(wheel)).is_file()
    record = (
        repository / "packages" / "pload-demo" / "1.0" / f"{wheel.name}.json"
    )
    assert record.is_file()
    assert '"sha256": "' + digest(wheel) + '"' in record.read_text(encoding="utf-8")


def test_apply_obeys_selected_route_without_fallback(tmp_path, monkeypatch):
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: Path(sys.executable)
    wheel = tiny_wheel(tmp_path / "artifacts")
    data = simple_manifest("exact")
    data["name"] = "strict-route"
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
            "tags": ["py3-none-any"], "repositories": [],
        }],
    }]
    manifest = tmp_path / "pload.toml"
    write_configuration(manifest, data)
    manager = DeclarativeEnvironmentManager(config)
    manager.cache.mkdir(parents=True)
    shutil.copyfile(wheel, manager.cache / wheel.name)
    wheel.unlink()
    plan_and_save(manager, manifest)
    (manager.cache / wheel.name).unlink()

    with pytest.raises(PloadError, match="planned route failed.*cache"):
        manager.apply(manifest)


def test_apply_downloads_the_exact_url_saved_by_plan(tmp_path, monkeypatch):
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: Path(sys.executable)
    wheel = tiny_wheel(tmp_path / "fixture")
    data = simple_manifest("exact")
    data["name"] = "exact-url"
    data["environment"].update({
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "system": platform.system(),
        "machine": platform.machine(),
        "dependencies": ["pload-demo==1.0"],
    })
    artifact_url = "https://files.example.invalid/" + wheel.name
    data["package"] = [{
        "name": "pload-demo", "version": "1.0", "sources": ["default"],
        "artifact": [{
            "filename": wheel.name, "sha256": digest(wheel),
            "tags": ["py3-none-any"], "repositories": [],
            "url": artifact_url, "size": wheel.stat().st_size,
        }],
    }]
    manifest = tmp_path / "project" / "pload.toml"
    manifest.parent.mkdir()
    write_configuration(manifest, data)
    manager = DeclarativeEnvironmentManager(config)
    assert plan_and_save(manager, manifest)["packages"][0]["selected"]["method"] == "index-exact"
    manager.cache.mkdir(parents=True)
    shutil.copyfile(wheel, manager.cache / wheel.name)
    requested = []

    def fake_urlopen(request, timeout):
        requested.append(request.full_url)
        return io.BytesIO(wheel.read_bytes())

    monkeypatch.setattr(declarative_module, "urlopen", fake_urlopen)
    progress = []
    restored = manager.apply(manifest, progress=progress.append)
    assert requested == [artifact_url]
    assert any(
        item.startswith("PACKAGE\t1/1\tindex-exact\tpload-demo==1.0")
        for item in progress
    )
    assert any(
        item.startswith(f"SOURCE\tpload-demo==1.0\tdownloading from {artifact_url}")
        for item in progress
    )
    assert any(item.startswith("DOWNLOAD\tpload-demo==1.0\t") for item in progress)
    assert execute([
        config.get_pip_command(restored)[0], "-c",
        "import pload_demo; print(pload_demo.answer)",
    ]) == "42"


def test_exact_download_reports_frequent_real_byte_progress(tmp_path, monkeypatch):
    payload = b"x" * (declarative_module.DOWNLOAD_CHUNK_SIZE * 4)
    source = tmp_path / "source.whl"
    source.write_bytes(payload)
    response = io.BytesIO(payload)
    response.headers = {"Content-Length": str(len(payload))}
    monkeypatch.setattr(
        declarative_module, "urlopen", lambda request, timeout: response
    )
    ticks = iter((0, 0.04, 0.08, 0.12, 0.16))
    monkeypatch.setattr(declarative_module.time, "monotonic", lambda: next(ticks))
    config = ConfigManager(home=tmp_path / "home")
    manager = DeclarativeEnvironmentManager(config)
    stage = tmp_path / "stage"
    stage.mkdir()
    destination = tmp_path / "output" / "demo.whl"
    destination.parent.mkdir()
    artifact = {
        "filename": "demo.whl",
        "sha256": digest(source),
        "size": len(payload),
        "url": "https://files.example.invalid/demo.whl",
    }
    package = {"name": "demo", "version": "1.0"}
    selected = {"method": "index-exact", "location": "default", "artifact": artifact}
    events = []

    manager._acquire(
        tmp_path / "pload.toml",
        {"sources": {"default": {"url": "https://example.invalid/simple"}}},
        package,
        selected,
        destination,
        stage,
        Path(sys.executable),
        progress=events.append,
    )

    downloads = [event for event in events if event.startswith("DOWNLOAD\t")]
    assert len(downloads) >= 3
    assert downloads[-1].split("\t")[2:] == [str(len(payload)), str(len(payload))]
    assert destination.read_bytes() == payload


def test_local_repository_fetch_streams_real_byte_progress(tmp_path, monkeypatch):
    payload = b"r" * (declarative_module.DOWNLOAD_CHUNK_SIZE * 4)
    checksum = hashlib.sha256(payload).hexdigest()
    repository = tmp_path / "repository"
    source = repository / "objects" / checksum
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    ticks = iter((0, 0.04, 0.08, 0.12, 0.16))
    monkeypatch.setattr(declarative_module.time, "monotonic", lambda: next(ticks))
    destination = tmp_path / "downloaded.whl"
    events = []

    ArtifactRepository.fetch(
        {"kind": "local", "location": str(repository)},
        checksum,
        destination,
        tmp_path,
        progress=lambda received, total: events.append((received, total)),
        expected_size=0,
    )

    assert len(events) >= 3
    assert events[-1] == (len(payload), len(payload))
    assert destination.read_bytes() == payload


def test_ssh_repository_fetch_streams_real_bytes(tmp_path, monkeypatch):
    chunk = b"s" * declarative_module.DOWNLOAD_CHUNK_SIZE
    payload = chunk * 4
    checksum = hashlib.sha256(payload).hexdigest()

    class StreamingOutput:
        def __init__(self):
            self.parts = 0

        def readline(self, size):
            return f"{len(payload)}\n".encode()

        def read1(self, size):
            if self.parts < 4:
                self.parts += 1
                return chunk
            return b""

    class StreamingSsh:
        def __init__(self, command, stdout, stderr):
            self.stdout = StreamingOutput()
            self.stderr = io.BytesIO()
            self.returncode = 0

        def poll(self):
            return 0

        def kill(self):
            self.returncode = -1

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(declarative_module.subprocess, "Popen", StreamingSsh)
    ticks = iter((0, 0.04, 0.08, 0.12, 0.16, 0.20))
    monkeypatch.setattr(declarative_module.time, "monotonic", lambda: next(ticks))
    events = []
    destination = tmp_path / "ssh-download.whl"

    ArtifactRepository.fetch(
        {"kind": "ssh", "location": "example:/repository"},
        checksum,
        destination,
        tmp_path,
        progress=lambda received, total: events.append((received, total)),
        expected_size=0,
    )

    assert [received for received, _ in events[:4]] == [
        len(chunk), len(chunk) * 2, len(chunk) * 3, len(chunk) * 4,
    ]
    assert events[-1] == (len(payload), len(payload))
    assert destination.read_bytes() == payload


def test_offline_apply_rejects_saved_network_route(tmp_path, monkeypatch):
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: Path(sys.executable)
    wheel = tiny_wheel(tmp_path / "fixture")
    data = simple_manifest("exact")
    data["environment"].update({
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "system": platform.system(),
        "machine": platform.machine(),
    })
    data["package"][0]["artifact"] = [{
        "filename": wheel.name, "sha256": digest(wheel),
        "tags": ["py3-none-any"], "repositories": [],
        "url": "https://example.invalid/" + wheel.name,
    }]
    manifest = tmp_path / "pload.toml"
    write_configuration(manifest, data)
    manager = DeclarativeEnvironmentManager(config)
    plan_and_save(manager, manifest)
    monkeypatch.setattr(
        declarative_module, "urlopen",
        lambda *args, **kwargs: pytest.fail("offline apply opened the network"),
    )

    with pytest.raises(PloadError, match="offline apply forbids.*network route"):
        manager.apply(manifest, offline=True)


def test_apply_refuses_to_replace_missing_planned_python(tmp_path):
    planned_python = tmp_path / "planned-python"
    planned_python.write_text("placeholder", encoding="utf-8")
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: planned_python
    manifest = tmp_path / "pload.toml"
    data = simple_manifest("compatible")
    data["environment"]["dependencies"] = []
    data["package"] = []
    write_configuration(manifest, data, with_lock=False)
    manager = DeclarativeEnvironmentManager(config)
    plan_and_save(manager, manifest)
    planned_python.unlink()

    with pytest.raises(PloadError, match="planned Python interpreter.*disappeared"):
        manager.apply(manifest)


def test_compatible_index_route_disables_pip_cache(tmp_path, monkeypatch):
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: Path(sys.executable)
    manifest = tmp_path / "pload.toml"
    write_configuration(manifest, simple_manifest("compatible"))
    manager = DeclarativeEnvironmentManager(config)
    plan_and_save(manager, manifest)
    monkeypatch.setattr(manager, "_check_runtime", lambda *args: None)
    environment = tmp_path / "environment"

    def create_environment(*args, **kwargs):
        environment.mkdir()
        return environment

    monkeypatch.setattr(VenvManager, "create_venv", create_environment)
    commands = []
    monkeypatch.setattr(
        declarative_module, "execute",
        lambda command, *args, **kwargs: commands.append(command) or "",
    )

    manager.apply(manifest)

    route_command = next(command for command in commands if "demo==1.0" in command)
    assert "--no-cache-dir" in route_command


def test_apply_rejects_plan_that_omits_a_locked_package(tmp_path):
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: Path(sys.executable)
    data = simple_manifest("exact")
    data["environment"].update({
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "system": platform.system(),
        "machine": platform.machine(),
    })
    manifest = tmp_path / "pload.toml"
    write_configuration(manifest, data)
    manager = DeclarativeEnvironmentManager(config)
    generated = manager.plan(manifest)
    generated["packages"] = []
    generated["ready"] = True
    write_plan(
        manifest, declarative_module.configuration_digest(data),
        file_digest(lock_path(manifest)), generated,
    )
    with pytest.raises(PloadError, match="do not match the current lock"):
        manager.apply(manifest)


def test_apply_rejects_tampered_route_status_and_artifact_url(tmp_path):
    config = ConfigManager(home=tmp_path / "home")
    config.get_python_path = lambda version=None: Path(sys.executable)
    data = simple_manifest("exact")
    data["environment"].update({
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "system": platform.system(),
        "machine": platform.machine(),
    })
    wheel = tiny_wheel(tmp_path / "fixture")
    data["package"][0]["artifact"] = [{
        "filename": wheel.name,
        "sha256": digest(wheel),
        "tags": ["py3-none-any"],
        "repositories": [],
        "url": "https://locked.invalid/demo.whl",
    }]
    manifest = tmp_path / "pload.toml"
    write_configuration(manifest, data)
    manager = DeclarativeEnvironmentManager(config)
    generated = manager.plan(manifest)

    generated["packages"][0]["selected"]["status"] = "ready"
    manager.save_plan(manifest, generated)
    with pytest.raises(PloadError, match="route status does not match"):
        manager.apply(manifest)

    generated = manager.plan(manifest)
    generated["packages"][0]["selected"]["artifact"]["url"] = (
        "https://changed.invalid/demo.whl"
    )
    manager.save_plan(manifest, generated)
    with pytest.raises(PloadError, match="artifact URL does not match"):
        manager.apply(manifest)


def test_legacy_exact_download_uses_planned_python_and_disables_pip_cache(
    tmp_path, monkeypatch,
):
    config = ConfigManager(home=tmp_path / "home")
    manager = DeclarativeEnvironmentManager(config)
    wheel = tiny_wheel(tmp_path / "fixture")
    planned_python = tmp_path / "planned-python"
    command_seen = []

    def fake_execute(command, *args, **kwargs):
        command_seen.append(command)
        destination = Path(command[command.index("--dest") + 1])
        shutil.copyfile(wheel, destination / wheel.name)
        return ""

    monkeypatch.setattr(declarative_module, "execute", fake_execute)
    output = tmp_path / "result.whl"
    manager._acquire(
        tmp_path / "pload.toml",
        {"sources": {"default": {"url": "https://index.invalid/simple"}}},
        {"name": "pload-demo", "version": "1.0"},
        {
            "method": "index-exact", "location": "default",
            "artifact": {"filename": wheel.name, "sha256": digest(wheel)},
        },
        output, tmp_path, interpreter=planned_python,
    )

    assert command_seen[0][:3] == [str(planned_python), "-m", "pip"]
    assert "--no-cache-dir" in command_seen[0]
    assert output.read_bytes() == wheel.read_bytes()


def test_declarative_commands_and_shell_integration(capsys):
    parser = build_parser()
    assert parser.parse_args(["describe", "v1", "-o", "env.toml"]).output == "env.toml"
    parsed = parser.parse_args([
        "describe", "v1", "-s", "torch=https://download.pytorch.org/whl/cu121",
    ])
    assert parsed.package_sources == ["torch=https://download.pytorch.org/whl/cu121"]
    assert parser.parse_args(["lock"]).file == "pload.toml"
    assert parser.parse_args(["apply"]).file == "pload.toml"
    assert parser.parse_args(["plan", "--no-ui"]).no_ui is True
    remote = parser.parse_args(["remote", "add", "numpy", "-f", "v10", "-r", "lab"])
    assert (remote.package, remote.environment, remote.repository) == ("numpy", "v10", "lab")
    for command in ("describe", "lock", "plan", "apply"):
        assert main([command, "-h"]) == 0
        for shell in ("bash", "zsh", "fish", "powershell"):
            assert command in shell_script(shell)
    assert "--mode" in capsys.readouterr().out
