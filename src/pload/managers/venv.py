import os
import shutil
import subprocess
import sys

from pload.managers.color import Colors
from pload.managers.platform import ConfigManager


class VenvManager:
    def __init__(self, config: ConfigManager):
        self.config = config

    def create_venv(self, version, message='normal', is_local=False):
        try:
            target_path, display_name = self.config.resolve_venv_path(
                version, message, is_local
            )
        except ValueError as e:
            print(f"[!] {str(e)}")
            sys.exit(1)

        if os.path.exists(target_path):
            print(f"[!] Venv {Colors.yellow(display_name)} already exsit.")
            sys.exit(1)

        python_exe = self.config.get_python_path(version)

        print(f'[*] Creating env: {Colors.green(display_name)} -> {Colors.green(target_path)}')
        create_cmd = [python_exe, '-m', 'venv', target_path]
        process = subprocess.run(
            create_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if process.returncode != 0:
            print(f'[!] Failed to create venv: {Colors.red(display_name)} -> {Colors.red(target_path)}\n[!] Error Message: {process.stderr}')
            sys.exit(1)

        print(f'[*] Successfully created {Colors.green(display_name)}. 🌟')
        return target_path

    def get_existing_venvs(self):
        if not os.path.exists(self.config.venv_path):
            return []

        venvs = []
        for name in os.listdir(self.config.venv_path):
            full_path = os.path.join(self.config.venv_path, name)
            if os.path.isdir(full_path):
                if name == 'scripts':
                    continue
                venvs.append(name)
        return venvs

    def remove_venv(self, venv_name):
        current_env = self.config.rdvenv('CUR')
        if venv_name == current_env or venv_name == current_env[0]:
            print(f'[!] Can not remove {Colors.red(current_env)}, beacause it is under using.')
            sys.exit(1)

        is_local = venv_name == '.'

        if is_local:
            target_path = os.path.join(os.getcwd(), '.venv')
            if not os.path.exists(target_path):
                print('[!] Local venv do not exsits.')
                sys.exit(1)
        else:
            target_path = os.path.join(self.config.venv_path, venv_name)
            if venv_name not in self.get_existing_venvs():
                print(f'[!] Global venv "{venv_name}" do not exsits.')
                sys.exit(1)

        try:
            shutil.rmtree(target_path)
            print(f'[*] Removed {Colors.green(os.path.basename(target_path))}.')
        except Exception as e:
            print(f'[!] Failed to remove venv. {str(e)}')
            sys.exit(1)

    def set_current_venv(self, venv_name):
        is_local = venv_name == '.'

        if is_local:
            target_path = os.path.join(os.getcwd(), '.venv')
            if not os.path.exists(target_path):
                print(f'[!] Local venv {Colors.green(".venv")} is not created.')
                sys.exit(1)
            display_name = f'.venv -> {target_path}'
        else:
            if venv_name not in self.get_existing_venvs():
                print(f'[!] Global venv "{venv_name}" is not created.')
                sys.exit(1)
            display_name = venv_name
            target_path = os.path.join(self.config.venv_path, venv_name)

        if not os.path.exists(os.path.join(target_path, 'pyvenv.cfg')):
            print(f'[!] Invalid venv: {Colors.red(target_path)}, beacause not exsit: {os.path.join(target_path, "pyvenv.cfg")}')
            sys.exit(1)

        self.config.wrvenv('CUR', display_name)
