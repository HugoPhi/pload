import json
import os
from argparse import Namespace

from pload import installer
from pload.installer import collect_settings, configure_shell, run, write_launcher
from pload.settings import USTC_PYTHON_MIRROR


def installer_args(tmp_path, **overrides):
    values = {
        "home": str(tmp_path / "pload"),
        "bin_dir": str(tmp_path / "bin"),
        "venvs_dir": None,
        "python_dir": None,
        "source": "ustc",
        "mirror_url": None,
        "downloads_json_url": None,
        "pip_source": "tsinghua",
        "pip_index": None,
        "package_spec": None,
        "shell": "none",
        "yes": True,
        "no_runtime_install": True,
    }
    values.update(overrides)
    return Namespace(**values)


def test_non_interactive_installer_collects_isolated_paths(tmp_path):
    settings = collect_settings(installer_args(tmp_path))

    assert settings["home"] == str((tmp_path / "pload").resolve())
    assert settings["venvs_dir"] == str((tmp_path / "pload" / "venvs").resolve())
    assert settings["python"]["install_dir"] == str(
        (tmp_path / "pload" / "pythons").resolve()
    )
    assert settings["python"]["mirror"] == USTC_PYTHON_MIRROR
    assert settings["pip_index"] == "https://pypi.tuna.tsinghua.edu.cn/simple"


def test_config_only_install_writes_reusable_configuration(tmp_path):
    result = run([
        "--yes",
        "--no-runtime-install",
        "--home", str(tmp_path / "pload"),
        "--bin-dir", str(tmp_path / "bin"),
        "--source", "official",
    ])

    assert result == 0
    data = json.loads((tmp_path / "pload" / "config.json").read_text(encoding="utf-8"))
    assert data["python"]["source"] == "official"
    assert data["shell"] == "none"


def test_launcher_uses_private_runtime_and_fixed_home(tmp_path):
    settings = collect_settings(installer_args(tmp_path, source="official"))
    if os.name == "nt":
        python = tmp_path / "runtime" / "Scripts" / "python.exe"
    else:
        python = tmp_path / "runtime" / "bin" / "python"

    launcher = write_launcher(settings, python)
    content = launcher.read_text(encoding="utf-8")

    assert str(python) in content
    assert settings["home"] in content
    assert "pload.cli" in content
    if os.name != "nt":
        assert os.access(launcher, os.X_OK)


def test_shell_configuration_updates_existing_managed_block(monkeypatch, tmp_path):
    profile = tmp_path / ".bashrc"
    profile.write_text(
        "export KEEP=this\n\n"
        "# >>> pload initialize >>>\nold setup\n# <<< pload initialize <<<\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(installer, "profile_path", lambda shell: profile)
    settings = collect_settings(installer_args(tmp_path, shell="bash"))

    configure_shell(settings)
    content = profile.read_text(encoding="utf-8")

    assert "export KEEP=this" in content
    assert "old setup" not in content
    assert settings["bin_dir"] in content
    assert content.count("# >>> pload initialize >>>") == 1
