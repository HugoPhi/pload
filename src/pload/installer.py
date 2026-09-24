import argparse
import os
import shlex
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

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
    parser.add_argument("--home", "-H", help="pload data and private-runtime directory")
    parser.add_argument("--bin-dir", "-b", help="directory for the stable pload executable")
    parser.add_argument("--venvs-dir", "-E", help="directory for managed virtual environments")
    parser.add_argument("--python-dir", "-p", help="directory for downloaded Python runtimes")
    parser.add_argument(
        "--source", "-s", choices=["official", "ustc", "custom"],
        help="managed Python download source",
    )
    parser.add_argument("--mirror-url", "-m", help="base URL or file:// URL for --source custom")
    parser.add_argument(
        "--downloads-json-url", "-j",
        help="advanced uv download metadata URL or local JSON path",
    )
    parser.add_argument(
        "--pip-source", "-P", choices=["official", "tsinghua", "ustc", "aliyun", "custom"],
        help="package index preset used for the private runtime",
    )
    parser.add_argument("--pip-index", "-i", help="package index used to install pload and uv")
    parser.add_argument(
        "--package-spec", "-k", help="pload package requirement or local project path"
    )
    parser.add_argument(
        "--shell", "-S", choices=["bash", "zsh", "fish", "powershell", "none"],
        help="shell profile to configure",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="accept defaults")
    parser.add_argument(
        "--no-runtime-install", "-N", action="store_true",
        help="write configuration only; useful for packaging and tests",
    )
    return parser


def render_help(detailed=False):
    parser = build_parser()
    if detailed:
        console = Console(highlight=False)
        console.print(Markdown(r"""
# Install pload without tying it to a project environment

The guided installer asks where every kind of data should live. Press Enter to
accept a recommended value, or enter a different directory.

## What an interactive run looks like

```console
$ pload-install
pload home [/home/me/.pload]: /mnt/tools/pload
executable bin directory [/home/me/.local/bin]:
managed virtual environment directory [/mnt/tools/pload/venvs]: /mnt/venvs
managed Python directory [/mnt/tools/pload/pythons]: /mnt/python

Choose the Python runtime download source
  1) official (default)
  2) ustc
  3) custom
Enter a number [1]: 2

Choose the Python package index used to install pload and uv
  1) official (default)
  2) tsinghua
  3) ustc
  4) aliyun
  5) custom
Enter a number [1]: 3
```

## Resulting layout

```text
/mnt/tools/pload/
├── config.json       saved choices
├── runtime/          private Python environment containing pload and uv
├── state/            environment IDs and descriptions
├── cache/python/     managed-Python download cache
└── python-bin/       links to managed Python executables

/mnt/python/          downloaded Python runtimes
/mnt/venvs/           managed virtual environments
~/.local/bin/pload    stable launcher
```

The stable launcher always calls the private runtime, so activating or deleting
a project environment cannot remove the `pload` command.

## What the installer changes

- Creates the selected directories and `config.json`.
- Installs pload and uv inside `PLOAD_HOME/runtime`.
- Writes a launcher into the selected bin directory.
- Updates a shell profile only when you choose a shell; the managed block can be
  replaced safely by a later installer run.
- Keeps Python runtime mirrors separate from PyPI package indexes.

## Repeatable non-interactive setup

```console
$ pload-install --yes \
    --home /mnt/tools/pload \
    --bin-dir ~/.local/bin \
    --venvs-dir /mnt/venvs \
    --python-dir /mnt/python \
    --source ustc \
    --pip-source ustc \
    --shell zsh
```

`--yes` reuses explicit values and saved defaults. It does not edit a shell
profile unless `--shell` is supplied or already saved in the configuration.
""".strip()))
        table = Table(
            title="Related options",
            box=box.ROUNDED,
            header_style="bold cyan",
            border_style="blue",
        )
        table.add_column("OPTION", style="bold green", no_wrap=True)
        table.add_column("MEANING")
        for action in parser._actions:
            if action.dest == "help" or not action.option_strings:
                continue
            table.add_row(", ".join(action.option_strings), action.help or "")
        console.print(table)
        return
    console = Console(highlight=False)
    usage = " ".join(parser.format_usage().split())
    usage_text = Text()
    for index, token in enumerate(usage.split()):
        if index:
            usage_text.append(" ")
        if token == "usage:":
            usage_text.append(token, style="dim")
        elif token.startswith("pload-install"):
            usage_text.append(token, style="bold green")
        elif token.startswith("-"):
            usage_text.append(token, style="bold yellow")
        elif token.startswith(("[", "{")):
            usage_text.append(token, style="bold cyan")
        else:
            usage_text.append(token, style="white")
    console.print(usage_text)
    console.print(Panel.fit(
        "Install pload into an isolated private runtime and choose every storage root.",
        title="[bold cyan]pload-install[/]",
        border_style="blue",
    ))
    table = Table(box=box.SIMPLE, header_style="bold cyan", show_edge=False)
    table.add_column("COMMAND", style="bold green", no_wrap=True)
    table.add_column("PURPOSE")
    table.add_row("pload-install", "Start the colored, numbered guided setup")
    table.add_row("pload-install --yes", "Reuse defaults without interactive questions")
    table.add_row(
        "pload-install --yes --home PATH",
        "Install all pload data below a chosen root",
    )
    console.print(table)
    options = Table(
        title="All options", box=box.SIMPLE,
        header_style="bold cyan", show_edge=False,
    )
    options.add_column("OPTION", style="bold green", no_wrap=True)
    options.add_column("PURPOSE")
    for action in parser._actions:
        if action.dest == "help" or not action.option_strings:
            continue
        options.add_row(", ".join(action.option_strings), action.help or "")
    console.print(options)
    console.print("[dim]Detailed help: [bold]pload-install -h -d[/bold][/dim]")


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
        "package_spec": args.package_spec or existing.get("package_spec") or default_package_spec(),
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


def interactive_configure(home=None):
    """Run the guided configuration wizard without reinstalling pload or uv."""
    print_welcome()
    args = Namespace(
        home=str(home) if home else None,
        bin_dir=None,
        venvs_dir=None,
        python_dir=None,
        source=None,
        mirror_url=None,
        downloads_json_url=None,
        pip_source=None,
        pip_index=None,
        package_spec=None,
        shell=None,
        yes=False,
    )
    settings = collect_settings(args)
    path = save_settings(settings["home"], settings)
    profile = configure_shell(settings)
    print(f"[*] Wrote configuration: {path}")
    if profile:
        print(f"[*] Updated shell profile: {profile}")
    else:
        print(f"[!] Add {settings['bin_dir']} to PATH, then run: pload shell-init <shell>")
    return path


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


def print_welcome_screen(version, launcher, settings, profile=None):
    """Show a friendly post-install landing screen with copyable next steps."""
    print()
    print(Colors.cyan("   ____  _                 _ "))
    print(Colors.cyan("  |  _ \\| | ___   __ _  __| |"))
    print(Colors.cyan("  | |_) | |/ _ \\ / _` |/ _` |"))
    print(Colors.cyan("  |  __/| | (_) | (_| | (_| |"))
    print(Colors.cyan("  |_|   |_|\\___/ \\__,_|\\__,_|"))
    print(Colors.bold(f"\n  pload {version} is ready"))
    print("  Your private runtime and launcher are installed.")
    print()
    print(Colors.bold("  Next steps"))
    print(f"  {Colors.green('1')}  Check configuration:  pload cfg")
    print(f"  {Colors.green('2')}  Find Python versions:  pload python list")
    print(f"  {Colors.green('3')}  Create an environment: pload new -n data -v 3.12")
    print(f"  {Colors.green('4')}  Read the walkthrough:  pload -h -d")
    print()
    print(Colors.bold("  Installed paths"))
    print(f"  launcher   {launcher}")
    print(f"  data       {settings['home']}")
    print(f"  environments {settings['venvs_dir']}")
    if profile:
        print(f"  shell      updated {profile}")
    else:
        print(f"  shell      add {settings['bin_dir']} to PATH, then start a new shell")
    print()


def run(argv=None):
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if any(item in {"-h", "--help"} for item in raw_args):
        render_help(any(item in {"-d", "--detailed", "--details"} for item in raw_args))
        return 0
    args = build_parser().parse_args(raw_args)
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
    print_welcome_screen(installed_version, launcher, settings, profile)
    return 0


def main(argv=None):
    try:
        return run(argv)
    except (PloadError, OSError) as exc:
        print(f"pload-install: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
