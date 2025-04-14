import os
import shutil
from setuptools import setup, find_packages
from setuptools.command.install import install


class PostInstallCommand(install):
    def run(self):
        install.run(self)

        '''init some env vars'''
        home_dir = os.path.expanduser("~")

        self.script_names = ["pload.sh", "pload.zsh", "pload.ps1", "pload.fish"]
        self.shell_configs = {  # suffix : config file path
            "sh": os.path.join(home_dir, ".bashrc"),
            "zsh": os.path.join(home_dir, ".zshrc"),
            "fish": os.path.join(home_dir, ".config", "fish", "config.fish"),
            "ps1": os.path.join(
                home_dir,
                "Documents",
                "PowerShell",
                "Microsoft.PowerShell_profile.ps1",
            ),
        }

        '''make global venv dir venvs'''
        self.venvs_dir = os.path.join(home_dir, "venvs", "scripts")
        os.makedirs(self.venvs_dir, exist_ok=True)

        self.copy_scripts_to_venvs()
        self.add_to_shell_config()

    def copy_scripts_to_venvs(self):
        install_scripts_dir = self.install_scripts

        for script_name in self.script_names:
            src_path = os.path.join(install_scripts_dir, script_name)
            dst_path = os.path.join(self.venvs_dir, script_name)

            if os.path.exists(src_path):
                print(f">>> Copying {src_path} to {dst_path}")
                shutil.copy(src_path, dst_path)
            else:
                print(f">>> Script {src_path} not found. Skipping.")

    def add_to_shell_config(self):
        for shell, config_path in self.shell_configs.items():
            script_name = f"pload.{shell}"
            script_path = os.path.join(self.venvs_dir, script_name)

            if not os.path.exists(config_path):
                print(f'[!] Can not find config: {config_path}. Skipping')
                continue

            with open(config_path, "r") as f:
                if script_path in f.read():
                    print(f"[!] {script_name} already added to {config_path}. Skipping.")
                    continue

                with open(config_path, "a") as f:
                    if shell == "fish":
                        f.write(f"\nsource {script_path}\n")
                    elif shell == "ps1":
                        f.write(f'\n. "{script_path}"\n')
                    else:
                        f.write(f'\nsource "{script_path}"\n')

                print(f"[*] Added {script_name} to {config_path}")


setup(
    name="pload",
    version="0.2.0",
    description="A simple command line tool for python virtual env management.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Yunming Hu",
    author_email="hugonelsonm3@gmail.com",
    license="MIT",
    python_requires=">=3.8",
    install_requires=[
        "colorama",
        "argcomplete",
    ],
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    entry_points={
        "console_scripts": [
            "python_virtual_env_load = pload.cli:main",
        ],
    },
    scripts=[
        os.path.join("script", "pload.sh"),
        os.path.join("script", "pload.zsh"),
        os.path.join("script", "pload.ps1"),
        os.path.join("script", "pload.fish"),
    ],
    cmdclass={
        "install": PostInstallCommand
    },
)
