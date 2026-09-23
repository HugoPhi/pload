import subprocess
from pathlib import Path

from pload.errors import PloadError


class PythonManager:
    def __init__(self, config):
        self.config = config

    def install_python(self, version):
        uv = self.config.uv_executable()
        if not uv:
            raise PloadError(
                "uv is required for managed Python downloads. Run pload-install "
                "to create the private runtime, or install uv separately."
            )
        install_dir = Path(self.config.python["install_dir"]).expanduser()
        bin_dir = Path(self.config.python["bin_dir"]).expanduser()
        cache_dir = Path(self.config.python["cache_dir"]).expanduser()
        install_dir.mkdir(parents=True, exist_ok=True)
        bin_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
        command = [
            str(uv), "python", "install", version,
            "--install-dir", str(install_dir),
        ]
        mirror = self.config.python.get("mirror")
        if mirror:
            command += ["--mirror", mirror]
        print(f"[*] Installing managed Python {version} into {install_dir}")
        result = subprocess.run(
            command, env=self.config.uv_environment(), check=False
        )
        if result.returncode != 0:
            raise PloadError(f"failed to install Python {version} with uv")
        python = self.config.find_managed_python(version)
        if not python:
            raise PloadError(
                f"uv completed but Python {version} was not found under {install_dir}"
            )
        print(f"[*] Installed Python {version}: {python}")
        return python

    def get_installed_versions(self):
        versions = set()
        for python in self.config.managed_python_candidates():
            try:
                result = subprocess.run(
                    [str(python), "--version"], capture_output=True, text=True, check=False
                )
            except OSError:
                continue
            output = (result.stdout or result.stderr).strip()
            if result.returncode == 0 and output.startswith("Python "):
                versions.add(output.split(None, 1)[1] + " (managed)")

        root = Path(self.config.pyenv_versions)
        if root.is_dir():
            versions.update(item.name + " (pyenv)" for item in root.iterdir() if item.is_dir())
        return sorted(versions)
