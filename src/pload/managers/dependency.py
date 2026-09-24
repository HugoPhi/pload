import subprocess

from pload.errors import PloadError
from pload.managers.color import Colors


class DependencyManager:
    def __init__(self, config):
        self.config = config

    def install_dependencies(self, venv_path, requirements, channel=None):
        if not requirements:
            return

        command = self.config.get_pip_command(venv_path) + ["install"] + list(requirements)
        wheels = self.config.home / "cache" / "wheels"
        if wheels.is_dir():
            command += ["--find-links", str(wheels)]
        if channel:
            command += ["--index-url", channel]

        print(f"[*] Installing: {' '.join(Colors.green(item) for item in requirements)}")
        process = subprocess.run(command, check=False)
        if process.returncode != 0:
            raise PloadError("dependency installation failed")
