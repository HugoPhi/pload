import os
from pathlib import Path
from subprocess import CompletedProcess

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


def test_managed_python_names_exclude_windows_libraries():
    matches = ConfigManager._is_python_executable_name

    assert matches("python.exe", "win32")
    assert matches("python3.exe", "win32")
    assert matches("python3.12.exe", "win32")
    assert not matches("python3.dll", "win32")
    assert not matches("python312.dll", "win32")
    assert not matches("pythonw.exe", "win32")


def test_managed_python_names_match_versioned_unix_executables():
    matches = ConfigManager._is_python_executable_name

    assert matches("python", "linux")
    assert matches("python3", "darwin")
    assert matches("python3.12", "linux")
    assert not matches("python3.pc", "linux")


def test_managed_minor_request_selects_newest_patch(monkeypatch, tmp_path):
    config = ConfigManager(home=tmp_path / "home")
    older = tmp_path / "python-3.8.15"
    newer = tmp_path / "python-3.8.20"
    monkeypatch.setattr(config, "managed_python_candidates", lambda: [older, newer])

    def version_result(command, **kwargs):
        version = "3.8.15" if Path(command[0]) == older else "3.8.20"
        return CompletedProcess(command, 0, stdout=f"Python {version}\n", stderr="")

    monkeypatch.setattr("pload.managers.platform.subprocess.run", version_result)

    assert config.find_managed_python("3.8") == newer.resolve()
