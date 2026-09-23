import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

from pload import __version__
from pload.errors import PloadError
from pload.managers.color import Colors
from pload.settings import (
    USTC_PYTHON_MIRROR,
    default_bin_dir,
    load_settings,
    save_settings,
)

PYPI_OFFICIAL_INDEX = "https://pypi.org/simple"
PYPI_TSINGHUA_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
PYPI_USTC_INDEX = "https://mirrors.ustc.edu.cn/pypi/simple"
PYPI_ALIYUN_INDEX = "https://mirrors.aliyun.com/pypi/simple"

PYTHON_SOURCE_CHOICES = [
    ("official", "Astral's official python-build-standalone releases; newest and canonical"),
    ("ustc", "USTC mirror in China; often faster on mainland networks"),
    ("custom", "Your own HTTPS or file:// mirror; advanced users only"),
]

PIP_SOURCE_CHOICES = [
    ("official", "Official PyPI; canonical and usually the first to receive new releases"),
    ("tsinghua", "Tsinghua University PyPI mirror in China"),
    ("ustc", "University of Science and Technology of China PyPI mirror"),
    ("aliyun", "Alibaba Cloud PyPI mirror in China"),
    ("custom", "A private or other compatible package index URL"),
]


def build_parser():
    parser = argparse.ArgumentParser(
        prog="pload-install",
        description=(
            "Install pload into its own private runtime, create a stable executable in a "
            "user-selected bin directory, and configure managed Python downloads."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  pload-install
      Start the interactive installer.

  pload-install --yes --home /opt/pload --bin-dir ~/.local/bin
      Install non-interactively with official Python downloads.

  pload-install --yes --source ustc
      Use the documented USTC mirror for managed Python downloads.

  pload-install --yes --pip-source aliyun
      Install pload and uv through the Alibaba Cloud PyPI mirror.

The installer never modifies a shell profile unless --shell is supplied or the
interactive user explicitly chooses it. Interactive source selection uses a
numbered menu with an explanation for every option.""",
    )
    parser.add_argument("--home", help="pload data and private-runtime directory")
    parser.add_argument("--bin-dir", help="directory for the stable pload executable")
    parser.add_argument("--venvs-dir", help="directory for managed virtual environments")
    parser.add_argument("--python-dir", help="directory for downloaded Python runtimes")
    parser.add_argument(
        "--source", choices=["official", "ustc", "custom"],
        help="managed Python download source",
    )
    parser.add_argument("--mirror-url", help="base URL or file:// URL for --source custom")
    parser.add_argument(
        "--downloads-json-url",
        help="advanced uv download metadata URL or local JSON path",
    )
    parser.add_argument(
        "--pip-source", choices=["official", "tsinghua", "ustc", "aliyun", "custom"],
        help="package index preset used for the private runtime",
    )
    parser.add_argument("--pip-index", help="package index used to install pload and uv")
    parser.add_argument(
        "--package-spec", help="pload package requirement or local project path"
    )
    parser.add_argument(
        "--shell", choices=["bash", "zsh", "fish", "powershell", "none"],
        help="shell profile to configure",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="accept defaults")
    parser.add_argument(
        "--no-runtime-install", action="store_true",
        help="write configuration only; useful for packaging and tests",
    )
    return parser


def ask(prompt, default, non_interactive=False):
    if non_interactive:
        return str(default)
    answer = input(f"{Colors.cyan(prompt)} [{Colors.green(default)}]: ").strip()
    return answer or str(default)


def ask_choice(prompt, choices, default, non_interactive=False):
    if non_interactive:
        return default
    items = [item if isinstance(item, tuple) else (item, "") for item in choices]
    keys = [item[0] for item in items]
    default_index = keys.index(default) if default in keys else 0
    while True:
        print(f"\n{Colors.bold(prompt)}")
        for index, (key, description) in enumerate(items, 1):
            marker = Colors.green(" (default)") if index - 1 == default_index else ""
            print(f"  {Colors.cyan(index)}) {Colors.bold(key)}{marker}")
            if description:
                print(f"     {description}")
        answer = input(
            f"{Colors.cyan('Enter a number')} [{Colors.green(default_index + 1)}]: "
        ).strip().lower()
        if not answer:
            return keys[default_index]
        if answer.isdigit() and 1 <= int(answer) <= len(items):
            return keys[int(answer) - 1]
        if answer in keys:
            return answer
        print(Colors.yellow(f"Please enter 1-{len(items)}."))


def print_welcome():
    print(Colors.bold("\npload guided setup"))
    print(
        "This installer keeps pload itself, downloaded Python runtimes, and virtual "
        "environments independent. Press Enter to accept any recommended default."
    )
    print(Colors.cyan("\nDirectory layout"))
    print("  pload home       configuration, private runtime, state, and caches")
    print("  executable bin   stable `pload` command; add this directory to PATH")
    print("  environments     every managed project environment")
    print("  Python runtimes  Python versions downloaded through uv")


def collect_settings(args):
    home = Path(ask("pload home", args.home or Path.home() / ".pload", args.yes)).expanduser().resolve()
    existing = load_settings(home)
    bin_dir = Path(
        ask(
            "executable bin directory",
            args.bin_dir or existing.get("bin_dir") or default_bin_dir(),
            args.yes,
        )
    ).expanduser().resolve()
    venvs_dir = Path(
        ask(
            "managed virtual environment directory",
            args.venvs_dir or existing.get("venvs_dir") or home / "venvs",
            args.yes,
        )
    ).expanduser().resolve()
    existing_python = existing.get("python", {})
    python_dir = Path(
        ask(
            "managed Python directory",
            args.python_dir or existing_python.get("install_dir") or home / "pythons",
            args.yes,
        )
    ).expanduser().resolve()
    default_source = existing_python.get("source", "official")
    source = args.source or ask_choice(
        "Choose the Python runtime download source",
        PYTHON_SOURCE_CHOICES,
        default_source,
        args.yes,
    )
    mirror = None
    if source == "ustc":
        mirror = USTC_PYTHON_MIRROR
    elif source == "custom":
        mirror = args.mirror_url or existing_python.get("mirror")
        if not mirror and not args.yes:
            mirror = ask("custom mirror base URL", "file:///path/to/mirror", False)
        if args.yes and not mirror:
            raise PloadError("--source custom requires --mirror-url in non-interactive mode")

    shell = args.shell
    if shell is None:
        if args.yes:
            shell = existing.get("shell", "none")
        else:
            detected = detect_shell()
            shell = ask_choice(
                "Choose a shell profile to configure",
                [
                    (detected, f"Update the detected {detected} profile automatically"),
                    ("none", "Do not change a shell profile; print manual instructions"),
                ],
                detected,
                False,
            )

    default_pip_source = existing.get("pip_source", "official")
    pip_source = args.pip_source or ask_choice(
        "Choose the Python package index used to install pload and uv",
        PIP_SOURCE_CHOICES,
        default_pip_source,
        args.yes,
    )
    pip_index = args.pip_index
    if pip_index:
        pass
    elif pip_source == "official":
        pip_index = PYPI_OFFICIAL_INDEX
    elif pip_source == "tsinghua":
        pip_index = PYPI_TSINGHUA_INDEX
    elif pip_source == "ustc":
        pip_index = PYPI_USTC_INDEX
    elif pip_source == "aliyun":
        pip_index = PYPI_ALIYUN_INDEX
    elif pip_source == "custom":
        pip_index = existing.get("pip_index")
    if pip_source == "custom" and not pip_index:
        if args.yes:
            raise PloadError("--pip-source custom requires --pip-index")
        pip_index = ask("custom Python package index URL", "https://example.com/simple", False)

    return {
        "home": str(home),
        "bin_dir": str(bin_dir),
        "venvs_dir": str(venvs_dir),
        "state_dir": str(home / "state"),
        "pip_source": pip_source,
        "pip_index": pip_index,
        "package_spec": args.package_spec or default_package_spec(),
        "python": {
            "provider": "uv",
            "install_dir": str(python_dir),
            "bin_dir": existing_python.get("bin_dir", str(home / "python-bin")),
            "cache_dir": existing_python.get("cache_dir", str(home / "cache" / "python")),
            "source": source,
            "mirror": mirror,
            "downloads_json_url": (
                args.downloads_json_url or existing_python.get("downloads_json_url")
            ),
        },
        "shell": shell,
    }


def detect_shell():
    if sys.platform == "win32":
        return "powershell"
    name = Path(os.environ.get("SHELL", "")).name
    return name if name in {"bash", "zsh", "fish"} else "bash"


def default_package_spec():
    project = Path(__file__).resolve().parents[2]
    if (project / "pyproject.toml").is_file():
        return str(project)
    return f"pload=={__version__}"


def runtime_python(runtime):
    if sys.platform == "win32":
        return runtime / "Scripts" / "python.exe"
    return runtime / "bin" / "python"


def install_private_runtime(settings):
    home = Path(settings["home"])
    runtime = home / "runtime"
    python = runtime_python(runtime)
    if not python.is_file():
        result = subprocess.run(
            [sys.executable, "-m", "venv", str(runtime)], check=False
        )
        if result.returncode != 0:
            raise PloadError(f"failed to create private runtime: {runtime}")

    command = [str(python), "-m", "pip", "install", "--upgrade"]
    if settings.get("pip_index"):
        command += ["--index-url", settings["pip_index"]]
    command += [settings["package_spec"], "uv"]
    env = os.environ.copy()
    for variable in ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_NO_INDEX"):
        env.pop(variable, None)
    result = subprocess.run(command, check=False, env=env)
    if result.returncode != 0:
        raise PloadError("failed to install pload and uv into the private runtime")
    return python


def write_launcher(settings, python):
    bin_dir = Path(settings["bin_dir"])
    bin_dir.mkdir(parents=True, exist_ok=True)
    home = settings["home"]
    if sys.platform == "win32":
        launcher = bin_dir / "pload.cmd"
        launcher.write_text(
            f'@echo off\r\nset "PLOAD_HOME={home}"\r\n'
            f'"{python}" -m pload.cli %*\r\n',
            encoding="utf-8",
        )
    else:
        launcher = bin_dir / "pload"
        launcher.write_text(
            "#!/bin/sh\n"
            f"export PLOAD_HOME={shlex.quote(home)}\n"
            f"exec {shlex.quote(str(python))} -m pload.cli \"$@\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
    return launcher


def installed_pload_version(python):
    """Read the version from the private runtime after installation completes."""
    try:
        result = subprocess.run(
            [str(python), "-c", "import pload; print(pload.__version__)"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return __version__
    version = result.stdout.strip()
    return version if result.returncode == 0 and version else __version__


def profile_path(shell):
    if shell == "bash":
        return Path.home() / ".bashrc"
    if shell == "zsh":
        return Path.home() / ".zshrc"
    if shell == "fish":
        return Path.home() / ".config" / "fish" / "config.fish"
    if shell == "powershell":
        documents = Path.home() / "Documents" / "PowerShell"
        return documents / "Microsoft.PowerShell_profile.ps1"
    return None


def configure_shell(settings):
    shell = settings["shell"]
    if shell == "none":
        return None
    profile = profile_path(shell)
    profile.parent.mkdir(parents=True, exist_ok=True)
    existing = profile.read_text(encoding="utf-8") if profile.is_file() else ""
    start = "# >>> pload initialize >>>"
    end = "# <<< pload initialize <<<"
    bin_dir = settings["bin_dir"]
    if shell == "fish":
        body = f'set -gx PATH "{bin_dir}" $PATH\npload shell-init fish | source'
    elif shell == "powershell":
        body = (
            f'$env:Path = "{bin_dir};$env:Path"\n'
            "Invoke-Expression (& pload shell-init powershell | Out-String)"
        )
    else:
        body = f'export PATH={shlex.quote(bin_dir)}:"$PATH"\neval "$(pload shell-init {shell})"'
    block = f"{start}\n{body}\n{end}"
    if start in existing and end in existing:
        before, remainder = existing.split(start, 1)
        _, after = remainder.split(end, 1)
        content = before.rstrip() + "\n\n" + block + after
    else:
        content = existing.rstrip() + "\n\n" + block + "\n"
    profile.write_text(content, encoding="utf-8")
    return profile


def run(argv=None):
    args = build_parser().parse_args(argv)
    if not args.yes:
        print_welcome()
    settings = collect_settings(args)
    path = save_settings(settings["home"], settings)
    if args.no_runtime_install:
        print(f"[*] Wrote configuration: {path}")
        return 0
    python = install_private_runtime(settings)
    launcher = write_launcher(settings, python)
    profile = configure_shell(settings)
    installed_version = installed_pload_version(python)
    print(f"[*] Installed pload {installed_version}: {launcher}")
    print(f"[*] Configuration: {path}")
    if profile:
        print(f"[*] Updated shell profile: {profile}")
    else:
        print(f"[!] Add {settings['bin_dir']} to PATH, then run: pload shell-init <shell>")
    return 0


def main(argv=None):
    try:
        return run(argv)
    except (PloadError, OSError) as exc:
        print(f"pload-install: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
