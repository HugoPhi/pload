from subprocess import CompletedProcess

import pytest
from packaging.tags import Tag

from pload.errors import PloadError
from pload.managers.dependency import DependencyManager
from pload.managers.platform import ConfigManager


def test_failed_package_does_not_stop_later_requirements(tmp_path, monkeypatch):
    manager = DependencyManager(ConfigManager(home=tmp_path / "home"))
    commands = []
    return_codes = iter([1, 0])

    def run(command, check):
        commands.append(command)
        return CompletedProcess(command, next(return_codes))

    monkeypatch.setattr("pload.managers.dependency.subprocess.run", run)

    with pytest.raises(PloadError, match="successful packages were kept"):
        manager.install_dependencies(
            tmp_path / "environment",
            ["not a requirement ???", "missing-package", "working-package"],
        )

    assert len(commands) == 2
    assert "missing-package" in commands[0]
    assert "working-package" in commands[1]


def test_automatic_strategy_prefers_compatible_pload_cache(tmp_path, monkeypatch):
    config = ConfigManager(home=tmp_path / "home")
    cache = config.home / "cache" / "wheels"
    cache.mkdir(parents=True)
    older = cache / "demo-1.0-py3-none-any.whl"
    newest = cache / "demo-2.0-py3-none-any.whl"
    older.touch()
    newest.touch()
    captured = []

    monkeypatch.setattr(
        "pload.managers.dependency._compatible_tags",
        lambda path: {Tag("py3", "none", "any")},
    )
    monkeypatch.setattr(
        "pload.managers.dependency.subprocess.run",
        lambda command, check: captured.append(command) or CompletedProcess(command, 0),
    )

    DependencyManager(config).install_dependencies(
        tmp_path / "environment", ["demo>=1"], strategy="auto",
    )

    assert str(newest) in captured[0]
    assert str(older) not in captured[0]


def test_custom_strategy_can_choose_index_instead_of_cache(tmp_path, monkeypatch):
    config = ConfigManager(home=tmp_path / "home")
    cache = config.home / "cache" / "wheels"
    cache.mkdir(parents=True)
    (cache / "demo-1.0-py3-none-any.whl").touch()
    captured = []

    monkeypatch.setattr(
        "pload.managers.dependency._compatible_tags",
        lambda path: {Tag("py3", "none", "any")},
    )
    monkeypatch.setattr(
        "pload.managers.dependency.ui.select",
        lambda message, choices, **kwargs: choices[-1].value,
    )
    monkeypatch.setattr(
        "pload.managers.dependency.subprocess.run",
        lambda command, check: captured.append(command) or CompletedProcess(command, 0),
    )

    DependencyManager(config).install_dependencies(
        tmp_path / "environment", ["demo>=1"], strategy="custom",
    )

    assert "demo>=1" in captured[0]
    assert not any(item.endswith(".whl") for item in captured[0])
