"""Exercise activation in a persistent shell, through the installed launcher."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pload.installer import write_launcher


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_create_and_switch_environments_without_restarting_shell(tmp_path, shell):
    executable = shutil.which(shell)
    if os.name == "nt" or not executable:
        pytest.skip(f"{shell} is unavailable")

    home = tmp_path / "pload data"
    bin_dir = tmp_path / "bin"
    write_launcher({"home": str(home), "bin_dir": str(bin_dir)}, Path(sys.executable))
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["PLOAD_VENVS_DIR"] = str(home / "venvs")
    env["PLOAD_STATE_DIR"] = str(home / "state")
    env["NO_COLOR"] = "1"
    env["PLOAD_NO_PROGRESS"] = "1"
    env["SHELL"] = executable
    env.pop("VIRTUAL_ENV", None)
    script = r'''
set -eu
# Reproduce a just-installed terminal: the launcher works but no function exists.
pload new -n first
if pload first 2>missing-name.txt; then exit 1; fi
if pload v1 2>missing-id.txt; then exit 1; fi
test -z "${VIRTUAL_ENV-}"
# Initialize in place, without restarting the shell.
eval "$(command pload shell-init "$1")"
pload first
test "$VIRTUAL_ENV" = "$PLOAD_VENVS_DIR/first"
python -c 'import os, sys; assert sys.prefix == os.environ["VIRTUAL_ENV"]'
# Create and activate a second environment while the first is still active.
pload new -n second
pload v2
test "$VIRTUAL_ENV" = "$PLOAD_VENVS_DIR/second"
python -c 'import os, sys; assert sys.prefix == os.environ["VIRTUAL_ENV"]'
deactivate
pload v1
test "$VIRTUAL_ENV" = "$PLOAD_VENVS_DIR/first"
deactivate
pload init
pload .
test "$VIRTUAL_ENV" = "$PWD/.venv"
python -c 'import os, sys; assert sys.prefix == os.environ["VIRTUAL_ENV"]'
'''
    result = subprocess.run(
        [executable, "-f" if shell == "zsh" else "--noprofile", "-c", script,
         "shell-activation-test", shell],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for filename in ("missing-name.txt", "missing-id.txt"):
        error = (tmp_path / filename).read_text(encoding="utf-8")
        assert "shell activation is not initialized in this terminal" in error
        assert f'eval "$(command pload shell-init {shell})"' in error
