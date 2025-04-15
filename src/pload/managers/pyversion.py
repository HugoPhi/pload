import subprocess
from pathlib import Path
from pload.managers.platform import ConfigManager


class PythonManager:
    def __init__(self, config: ConfigManager):
        self.config = config

    def install_python(self, version):
        print(f'[*] Downloading python v{version}')
        process = subprocess.Popen(
            [self.config.pyenv_exe, "install", version],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        for line in iter(process.stdout.readline, ''):
            print(line, end='')
        for line in iter(process.stderr.readline, ''):
            print(line, end='')

    def get_installed_versions(self):
        path = Path(self.config.pyenv_versions)
        return [f.name for f in path.iterdir() if f.is_dir()]
