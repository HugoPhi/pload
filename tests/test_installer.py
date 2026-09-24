import json
import os
from argparse import Namespace
from pathlib import Path
from subprocess import CompletedProcess

from pload import installer
from pload.installer import (
    PIP_SOURCE_CHOICES,
    PYPI_ALIYUN_INDEX,
    PYPI_OFFICIAL_INDEX,
    PYPI_TSINGHUA_INDEX,
    PYPI_USTC_INDEX,
    ask_choice,
    collect_settings,
    configure_shell,
    install_private_runtime,
    installed_pload_version,
    run,
    write_launcher,
)
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
    assert settings["pip_index"] == PYPI_TSINGHUA_INDEX


def test_official_pip_source_is_explicit(tmp_path):
    settings = collect_settings(installer_args(tmp_path, pip_source="official"))

    assert settings["pip_index"] == PYPI_OFFICIAL_INDEX


def test_setup_preserves_repositories_and_custom_state(tmp_path):
    from pload.settings import save_settings

    original = {
        "repositories": {"lab": {"kind": "ssh", "location": "host:/srv/pload"}},
        "state_dir": str(tmp_path / "custom-state"),
    }
    save_settings(tmp_path / "pload", original)
    collected = collect_settings(installer_args(tmp_path))
    assert collected["repositories"] == original["repositories"]
    assert collected["state_dir"] == original["state_dir"]


def test_additional_pip_source_presets(tmp_path):
    ustc = collect_settings(installer_args(tmp_path, pip_source="ustc"))
    aliyun = collect_settings(installer_args(tmp_path, pip_source="aliyun"))

    assert ustc["pip_index"] == PYPI_USTC_INDEX
    assert aliyun["pip_index"] == PYPI_ALIYUN_INDEX


def test_guided_choice_accepts_numeric_selection(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: "3")

    selected = ask_choice("Package source", PIP_SOURCE_CHOICES, "official")

    assert selected == "ustc"
    output = capsys.readouterr().out
    assert "Official PyPI" in output
    assert "Tsinghua University" in output
    assert "Alibaba Cloud" in output


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


def test_installed_version_is_read_from_private_runtime(monkeypatch, tmp_path):
    python = tmp_path / "runtime" / "python"

    def completed(command, **kwargs):
        return CompletedProcess(command, 0, stdout="0.6.1\n", stderr="")

    monkeypatch.setattr(installer.subprocess, "run", completed)

    assert installed_pload_version(python) == "0.6.1"


def test_private_install_ignores_ambient_pip_index(monkeypatch, tmp_path):
    settings = collect_settings(installer_args(tmp_path, pip_source="official"))
    python = installer.runtime_python(Path(settings["home"]) / "runtime")
    python.parent.mkdir(parents=True)
    python.touch()
    captured = {}

    def completed(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return CompletedProcess(command, 0)

    monkeypatch.setenv("PIP_INDEX_URL", "https://ambient.example/simple")
    monkeypatch.setenv("PIP_EXTRA_INDEX_URL", "https://extra.example/simple")
    monkeypatch.setattr(installer.subprocess, "run", completed)

    install_private_runtime(settings)

    assert captured["command"][-4:-2] == ["--index-url", PYPI_OFFICIAL_INDEX]
    assert "PIP_INDEX_URL" not in captured["env"]
    assert "PIP_EXTRA_INDEX_URL" not in captured["env"]


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


def test_installer_has_brief_and_detailed_help(capsys):
    assert run(["-h"]) == 0
    brief = capsys.readouterr().out
    assert "colored, numbered guided setup" in brief
    assert "pload-install -h -d" in brief
    assert "--downloads-json-url" in brief
    assert "--home, -H" in brief
    assert brief.splitlines()[0].startswith("usage: pload-install")

    assert run(["-h", "-d"]) == 0
    detailed = capsys.readouterr().out
    assert "What an interactive run looks like" in detailed
    assert "Enter a number" in detailed
    assert "Resulting layout" in detailed
    assert "What the installer changes" in detailed
    assert "--downloads-json-url" in detailed
    assert "--pip-source" in detailed


def test_installer_long_options_have_short_forms():
    parser = installer.build_parser()
    args = parser.parse_args([
        "-H", "/tmp/pload", "-b", "/tmp/bin", "-E", "/tmp/venvs",
        "-p", "/tmp/pythons", "-s", "official", "-m", "https://example.test",
        "-j", "/tmp/downloads.json", "-P", "official", "-i", "https://pypi.org/simple",
        "-k", "pload==0.8.1", "-S", "none", "-y", "-N",
    ])

    assert args.home == "/tmp/pload"
    assert args.bin_dir == "/tmp/bin"
    assert args.no_runtime_install is True


def test_post_install_welcome_screen_contains_ascii_and_next_steps(capsys, tmp_path):
    settings = installer_args(tmp_path, shell="none")
    installer.print_welcome_screen(
        "0.8.7", Path(settings.home) / "bin" / "pload", vars(settings)
    )

    output = capsys.readouterr().out
    assert "pload 0.8.7 is ready" in output
    assert "____" in output
    assert "pload cfg" in output
    assert "pload new -n data -v 3.12" in output
