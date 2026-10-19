import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pload.cli import build_parser, main
from pload.completion import candidates
from pload.installer import write_launcher
from pload.settings import save_settings


@pytest.fixture
def completion_home(tmp_path, monkeypatch):
    home = tmp_path / "data"
    monkeypatch.setenv("PLOAD_HOME", str(home))
    monkeypatch.delenv("PLOAD_VENVS_DIR", raising=False)
    monkeypatch.delenv("PLOAD_STATE_DIR", raising=False)
    save_settings(home, {"repositories": {"lab": {"kind": "ssh", "location": "host:/data"}}})
    state = home / "state"
    state.mkdir()
    environment = home / "venvs" / "data-tools"
    environment.mkdir(parents=True)
    (environment / "pyvenv.cfg").touch()
    (state / "environments.json").write_text(json.dumps({"environments": [{
        "id": "v3", "name": "data-tools", "path": str(environment),
        "description": "Data analysis",
    }]}), encoding="utf-8")
    (state / "python-runtimes.json").write_text(json.dumps({"runtimes": [{
        "id": "py2", "alias": "uv-v3.12.8", "version": "3.12.8", "source": "uv",
        "path": sys.executable,
    }]}), encoding="utf-8")
    return home


def complete(*args):
    return dict(candidates(build_parser(), ["pload", *args], len(args)))


@pytest.mark.parametrize(("words", "expected"), [
    (("",), {"new", "ls", "python", "py", "remote", "v3", "data-tools", "."}),
    (("v",), {"v3"}),
    (("py", ""), {"install", "list", "ls", "path", "p"}),
    (("new", "-v", "py"), {"py2"}),
    (("new", "--version=py"), {"--version=py2"}),
    (("init", "--version", "uv"), {"uv-v3.12.8"}),
    (("py", "p", "py"), {"py2"}),
    (("py", "install", "3."), {"3.12", "3.12.8"}),
    (("py", "ls", "-f", "uv,c"), {"uv,conda"}),
    (("py", "ls", "--filter", ""), {"uv", "conda", "sys"}),
    (("new", "--package-strategy", ""), {"auto", "custom"}),
    (("rm", "v"), {"v3"}),
    (("rm", "-n", "v3", "data"), {"data-tools"}),
    (("path", ""), {"v3", "data-tools", "."}),
    (("path", "v3", "--shell", ""), {"bash", "zsh", "fish", "powershell"}),
    (("describe", "v"), {"v3"}),
    (("remote", "add", "numpy", "--from", "v"), {"v3"}),
    (("remote", "add", "numpy", "--remote", ""), {"lab"}),
    (("repo", "remove", ""), {"lab"}),
    (("cfg", ""), {"show", "set"}),
    (("cfg", "set", "pip-"), {"pip-source", "pip-index"}),
    (("cfg", "set", "pip-source", ""), {"official", "tsinghua", "aliyun", "ustc"}),
    (("shell", "z"), {"zsh"}),
    (("new", "--"), {"--name", "--version", "--message", "--package-strategy"}),
    (("new", "-h", "-"), {"-d", "--detailed"}),
])
def test_contextual_completion(completion_home, words, expected):
    result = complete(*words)
    assert expected <= result.keys()
    assert all(item.startswith(words[-1]) for item in result)


def test_new_names_and_descriptions_are_free_text(completion_home):
    assert complete("new", "--name", "") == {}
    assert complete("new", "-m", "") == {}
    assert "py2" not in complete("py", "install", "")


def test_every_command_and_alias_exposes_all_of_its_options(completion_home):
    def visit(parser, words):
        offered = complete(*words, "-")
        assert set(parser._option_string_actions) <= offered.keys(), words
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    visit(child, [*words, name])

    visit(build_parser(), [])


def test_completion_uses_overridden_roots_and_is_read_only(completion_home, tmp_path, monkeypatch):
    other = tmp_path / "other root"
    (other / "fresh").mkdir(parents=True)
    (other / "fresh" / "pyvenv.cfg").touch()
    before = {path: path.read_bytes() for path in completion_home.rglob("*") if path.is_file()}

    def forbid(*args, **kwargs):
        pytest.fail("completion must not execute tools, probe Python, or contact remote resources")

    monkeypatch.setattr(subprocess, "run", forbid)
    assert "fresh" in complete("--venvs-dir", str(other), "rm", "fr")
    assert "v3" in complete("v")
    assert "py2" in complete("new", "-v", "py")
    after = {path: path.read_bytes() for path in completion_home.rglob("*") if path.is_file()}
    assert before == after


def test_candidates_refresh_after_create_and_remove(completion_home):
    path = completion_home / "venvs" / "fresh"
    assert "fresh" not in complete("")
    path.mkdir()
    marker = path / "pyvenv.cfg"
    marker.touch()
    assert "fresh" in complete("fr")
    marker.unlink()
    assert "fresh" not in complete("fr")


def test_package_completion_does_not_register_discovered_environments(completion_home):
    environment = completion_home / "venvs" / "discovered"
    packages = environment / "lib" / "python3.12" / "site-packages"
    packages.mkdir(parents=True)
    (environment / "pyvenv.cfg").touch()
    (packages / "my_package-1.0.dist-info").mkdir()
    registry = completion_home / "state" / "environments.json"
    before = registry.read_bytes()
    assert "my-package" in complete(
        "remote", "add", "--from", "discovered", "my"
    )
    assert registry.read_bytes() == before


def test_paths_with_spaces_and_config_files(completion_home, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "my project").mkdir()
    (tmp_path / "my project" / "pload.toml").touch()
    (tmp_path / "plain.txt").touch()
    assert "my project/" in complete("init", "-P", "my")
    assert "./my project/" in complete("./my")
    assert "my project/pload.toml" in complete("apply", "my project/")
    assert "plain.txt" not in complete("plan", "")


def test_completion_protocol_never_prints_help(completion_home, capsys):
    assert main(["__complete", "3", "pload", "new", "-h", "-"]) == 0
    output = capsys.readouterr()
    assert "--detailed\t" in output.out
    assert "USAGE" not in output.out
    assert not output.err
    assert main(["__complete", "bad"]) == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("prefix", ["my\\ project/ch", "'my project/ch", '"my project/ch'])
def test_shell_quoted_paths_are_parsed_without_evaluation(
    completion_home, tmp_path, monkeypatch, capsys, prefix,
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "my project" / "child folder").mkdir(parents=True)
    assert main(["__complete", "--unquote", "3", "pload", "init", "-P", prefix]) == 0
    assert "my project/child folder/\t" in capsys.readouterr().out


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_registered_shell_completion_reads_live_candidates(completion_home, tmp_path, shell):
    executable = shutil.which(shell)
    if os.name == "nt" or not executable:
        pytest.skip(f"{shell} unavailable")
    bin_dir = tmp_path / "bin"
    write_launcher({"home": str(completion_home), "bin_dir": str(bin_dir)}, Path(sys.executable))
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["ZDOTDIR"] = str(tmp_path)
    env["PLOAD_COMPLETION_TEST_ROOT"] = str(tmp_path)
    (tmp_path / "my project" / "child folder").mkdir(parents=True)
    if shell == "bash":
        script = r'''
set -e
eval "$(command pload shell-init bash)"
complete -p pload
COMP_WORDS=(pload new -v py)
COMP_CWORD=3
_pload_complete
printf '%s\n' "${COMPREPLY[@]}"
COMP_WORDS=(pload v)
COMP_CWORD=1
_pload_complete
printf '%s\n' "${COMPREPLY[@]}"
# Readline must not insert --version= twice. Cover both Bash token layouts.
COMP_WORDBREAKS='=:'
COMP_WORDS=(pload new --version=py)
COMP_CWORD=2
_pload_complete
test "${COMPREPLY[0]}" = py2
COMP_WORDS=(pload new --version = py)
COMP_CWORD=4
_pload_complete
test "${COMPREPLY[0]}" = py2
COMP_WORDS=(pload init -P "$PLOAD_COMPLETION_TEST_ROOT/my\\ project/ch")
COMP_CWORD=3
_pload_complete
test "${COMPREPLY[0]}" = "$PLOAD_COMPLETION_TEST_ROOT/my project/child folder/"
'''
    else:
        script = r'''
set -e
eval "$(command pload shell-init zsh)"
test "${_comps[pload]}" = _pload_complete
# Capture arguments passed to zsh's native completion engine.
compadd() { print -rl -- "$@"; }
words=(pload new -v py)
CURRENT=4
_pload_complete
words=(pload v)
CURRENT=2
_pload_complete
words=(pload init -P "$PLOAD_COMPLETION_TEST_ROOT/my\\ project/ch")
CURRENT=4
_pload_complete
'''
    result = subprocess.run(
        [executable, "-f" if shell == "zsh" else "--noprofile", "-c", script],
        env=env, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "py2" in result.stdout.splitlines()
    assert "v3" in result.stdout.splitlines()


@pytest.mark.parametrize("shell", ["fish", "pwsh"])
def test_other_shells_native_completion(completion_home, tmp_path, shell):
    executable = shutil.which(shell)
    if not executable:
        pytest.skip(f"{shell} unavailable")
    bin_dir = tmp_path / "bin"
    write_launcher({"home": str(completion_home), "bin_dir": str(bin_dir)}, Path(sys.executable))
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    if shell == "fish":
        script = """
command pload shell-init fish | source
complete -C 'pload new -v py'
complete -C 'pload v'
"""
        command = [executable, "--no-config", "-c", script]
    else:
        script = """
$ErrorActionPreference = 'Stop'
$backend = Get-Command pload -CommandType Application | Select-Object -First 1
Invoke-Expression ((& $backend.Source shell-init powershell) -join "`n")
$line = 'pload new -v py'
(TabExpansion2 -inputScript $line -cursorColumn $line.Length).CompletionMatches | ForEach-Object { $_.ListItemText }
$line = 'pload v'
(TabExpansion2 -inputScript $line -cursorColumn $line.Length).CompletionMatches | ForEach-Object { $_.ListItemText }
"""
        command = [executable, "-NoProfile", "-NonInteractive", "-Command", script]
    result = subprocess.run(
        command, env=env, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    values = {line.split("\t", 1)[0] for line in result.stdout.splitlines()}
    assert {"py2", "v3"} <= values
