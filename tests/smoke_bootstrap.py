"""Cross-platform end-to-end smoke test used by the CI integration job."""

import os
import subprocess
import sys
from pathlib import Path

from pload.installer import run as install


def main():
    root = Path(sys.argv[1]).resolve()
    project = Path(__file__).resolve().parents[1]
    home = root / "data"
    bin_dir = root / "bin"
    result = install([
        "--yes",
        "--home", str(home),
        "--bin-dir", str(bin_dir),
        "--venvs-dir", str(root / "venvs"),
        "--python-dir", str(root / "pythons"),
        "--source", "official",
        "--package-spec", str(project),
        "--shell", "none",
    ])
    if result != 0:
        return result

    launcher = bin_dir / ("pload.cmd" if os.name == "nt" else "pload")
    commands = [
        [str(launcher), "--version"],
        [str(launcher), "python", "install", "3.12"],
        [str(launcher), "py", "p", "3.12"],
        [
            str(launcher), "new", "-n", "smoke", "-v", "3.12",
            "--description", "Cross-platform smoke environment",
        ],
        [str(launcher), "ls"],
        [str(launcher), "p", "v1"],
        [str(launcher), "del", "v1", "--yes"],
    ]
    for command in commands:
        subprocess.run(command, check=True)
    if (root / "venvs" / "smoke").exists():
        raise RuntimeError("smoke environment was not removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
