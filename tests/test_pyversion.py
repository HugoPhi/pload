import os
from dataclasses import replace
from pathlib import Path

import pytest

from pload.errors import PloadError
from pload.managers.platform import ConfigManager
from pload.managers.pyversion import PythonManager, PythonRuntime


def test_source_filter_accepts_commas_spaces_and_aliases():
    assert PythonManager.parse_sources(["uv,", "conda", "system", "managed"]) == {
        "uv", "conda", "sys"
    }


def test_source_filter_rejects_unknown_types():
    with pytest.raises(PloadError, match="unknown Python source"):
        PythonManager.parse_sources(["mystery"])


def test_unresolvable_windows_alias_uses_absolute_path(monkeypatch, tmp_path):
    alias = tmp_path / "python.exe"
    original_resolve = Path.resolve

    def inaccessible(self):
        if self == alias:
            raise OSError("inaccessible app execution alias")
        return original_resolve(self)

    monkeypatch.setattr(Path, "resolve", inaccessible)
    assert PythonManager._resolved_path(alias) == alias.absolute()
    assert PythonManager._path_key(alias) == os.path.normcase(str(alias.absolute()))


def test_discovery_deduplicates_resolved_paths_and_filters(monkeypatch, tmp_path):
    python = tmp_path / "python3.12"
    python.touch()
    alias = tmp_path / "python3"
    alias.symlink_to(python)
    manager = PythonManager(ConfigManager(home=tmp_path / "home"))

    monkeypatch.setattr(
        manager,
        "_candidate_paths",
        lambda selected=None: [("uv", python), ("other", alias)],
    )
    monkeypatch.setattr(
        manager,
        "_probe",
        lambda path, source: PythonRuntime("3.12.8", source, path.resolve(), "CPython"),
    )

    discovered = manager.discover(["uv"])

    assert discovered == [PythonRuntime(
        "3.12.8", "uv", python.resolve(), "CPython", "py1", "uv-v3.12.8"
    )]


def test_find_python_chooses_newest_matching_patch(monkeypatch, tmp_path):
    manager = PythonManager(ConfigManager(home=tmp_path / "home"))
    runtimes = [
        PythonRuntime("3.11.8", "sys", Path("/python/3.11.8")),
        PythonRuntime("3.11.10", "conda", Path("/python/3.11.10")),
        PythonRuntime("3.12.4", "uv", Path("/python/3.12.4")),
    ]
    monkeypatch.setattr(manager, "discover", lambda sources=None: runtimes)

    assert manager.find_python("3.11") == Path("/python/3.11.10")
    assert manager.find_python("3.12.4") == Path("/python/3.12.4")
    assert manager.find_python("3.10") is None


def test_runtime_table_includes_type_and_path():
    uv_path = Path("/opt/uv/python")
    conda_path = Path("/opt/conda/python")
    lines = PythonManager.format_runtimes([
        PythonRuntime("3.12.8", "uv", uv_path),
        PythonRuntime("3.11.9", "conda", conda_path),
    ])

    assert lines[0].split() == ["ID", "ALIAS", "VERSION", "TYPE", "PATH"]
    assert any("3.12.8" in line and "uv" in line and str(uv_path) in line for line in lines)
    assert any("3.11.9" in line and "conda" in line for line in lines)


def test_python_registry_assigns_ids_and_resolves_id_or_alias(monkeypatch, tmp_path):
    manager = PythonManager(ConfigManager(home=tmp_path / "home"))
    uv_path = tmp_path / "uv-python"
    conda_path = tmp_path / "conda-python"
    runtimes = [
        PythonRuntime("3.8.10", "uv", uv_path),
        PythonRuntime("3.11.9", "conda", conda_path),
    ]
    monkeypatch.setattr(manager, "_candidate_paths", lambda selected=None: [])
    monkeypatch.setattr(manager, "_probe", lambda path, source: None)
    monkeypatch.setattr(manager, "discover", lambda sources=None: [
        replace(runtimes[0], id="py1", alias="uv-v3.8.10"),
        replace(runtimes[1], id="py2", alias="conda-v3.11.9"),
    ])

    assert manager.find_python("py1") == uv_path
    assert manager.find_python("uv-v3.8.10") == uv_path
    assert manager.find_python("py1:uv-v3.8.10") == uv_path
