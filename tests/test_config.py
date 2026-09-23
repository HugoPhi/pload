import os
from pathlib import Path

from pload.managers.platform import ConfigManager
from pload.settings import save_settings


def test_explicit_paths_are_fully_isolated(tmp_path):
    config = ConfigManager(
        home=tmp_path / "home",
        venvs_dir=tmp_path / "environments",
        state_dir=tmp_path / "state",
    )

    assert config.home == (tmp_path / "home").resolve()
    assert config.venv_path == (tmp_path / "environments").resolve()
    assert config.state_path == (tmp_path / "state").resolve()


def test_environment_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("PLOAD_HOME", str(tmp_path / "portable"))
    config = ConfigManager()

    assert config.venv_path == (tmp_path / "portable" / "venvs").resolve()
    assert config.state_path == (tmp_path / "portable" / "state").resolve()


def test_local_target_is_relative_to_project(tmp_path):
    config = ConfigManager(home=tmp_path / "home")
    path, name = config.resolve_venv_path(
        is_local=True,
        project_dir=tmp_path / "project",
        target=".runtime/python",
    )

    assert path == (tmp_path / "project" / ".runtime/python").resolve()
    assert name == "python"


def test_current_python_does_not_require_pyenv(tmp_path):
    config = ConfigManager(home=tmp_path / "home")
    assert config.get_python_path() == Path(os.sys.executable).resolve()


def test_legacy_root_is_reused_for_existing_users(monkeypatch, tmp_path):
    monkeypatch.delenv("PLOAD_HOME", raising=False)
    monkeypatch.delenv("PLOAD_VENVS_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    legacy = tmp_path / "venvs"
    (legacy / "scripts").mkdir(parents=True)

    config = ConfigManager()

    assert config.venv_path == legacy.resolve()


def test_explicit_home_never_falls_back_to_legacy(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "venvs" / "scripts").mkdir(parents=True)

    config = ConfigManager(home=tmp_path / "portable")

    assert config.venv_path == (tmp_path / "portable" / "venvs").resolve()


def test_saved_configuration_controls_all_managed_roots(tmp_path):
    home = tmp_path / "pload"
    save_settings(home, {
        "venvs_dir": str(tmp_path / "envs"),
        "state_dir": str(tmp_path / "state"),
        "python": {
            "install_dir": str(tmp_path / "python"),
            "mirror": "https://mirror.example/releases/download",
        },
    })

    config = ConfigManager(home=home)

    assert config.venv_path == (tmp_path / "envs").resolve()
    assert config.state_path == (tmp_path / "state").resolve()
    assert config.python["install_dir"] == str(tmp_path / "python")
    assert config.python["mirror"] == "https://mirror.example/releases/download"
