from pathlib import Path


class PythonManager:
    def __init__(self, config):
        self.config = config

    def get_installed_versions(self):
        root = Path(self.config.pyenv_versions)
        if not root.is_dir():
            return []
        return sorted(item.name for item in root.iterdir() if item.is_dir())
