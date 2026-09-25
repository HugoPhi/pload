import argparse
import json
import re
import sys
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from pload import __version__
from pload.display import print_environment_table, print_python_table
from pload.errors import PloadError
from pload.help_content import render_detailed_help
from pload.managers.dependency import DependencyManager
from pload.managers.platform import ConfigManager, PythonNotFoundError
from pload.managers.pyversion import PythonManager
from pload.managers.venv import VenvManager

COMMAND_ALIASES = {
    "new": (),
    "init": ("i",),
    "rm": ("remove", "del", "delete"),
    "list": ("ls",),
    "path": ("p",),
    "shell-init": ("shell",),
    "python": ("py",),
    "config": ("cfg",),
    "describe": (),
    "plan": (),
    "apply": (),
    "repo": (),
}
PYTHON_ALIASES = {
    "install": (),
    "list": ("ls",),
    "path": ("p",),
}
COMMAND_NAMES = {
    alias: canonical
    for canonical, aliases in COMMAND_ALIASES.items()
    for alias in (canonical,) + aliases
}
PYTHON_COMMAND_NAMES = {
    alias: canonical
    for canonical, aliases in PYTHON_ALIASES.items()
    for alias in (canonical,) + aliases
}
HELP_FLAGS = {"-h", "--help"}
DETAIL_FLAGS = {"-d", "--detailed", "--details"}


def build_parser():
    parser = argparse.ArgumentParser(
        prog="pload",
        description=(
            "Create, activate, and remove Python virtual environments without tying "
            "pload itself to any project environment."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Typical workflow:
  pload python install 3.12        Download a managed Python when needed
  pload new -n data -v 3.12 -m "Data analysis"
                                   Create a described environment with an ID
  pload v1                         Activate it by ID (after shell initialization)
  pload init                       Create .venv for the current project
  pload .                          Activate the project environment

Isolation:
  PLOAD_HOME=/mnt/pload pload list
  pload --venvs-dir /mnt/venvs new --name tools
  pload init -P ./app -e /mnt/venvs/app

Run `pload <command> -h -d` for complete command-specific examples.""",
    )
    parser.add_argument("--home", "-H", help="data root (or set PLOAD_HOME)")
    parser.add_argument("--venvs-dir", "-E", help="managed environment root (or PLOAD_VENVS_DIR)")
    parser.add_argument("--state-dir", "-S", help="state root (or PLOAD_STATE_DIR)")
    parser.add_argument("--version", "-V", action="version", version=f"pload {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    new = subparsers.add_parser(
        "new", aliases=COMMAND_ALIASES["new"], help="create a managed environment",
        description=(
            "Create a virtual environment under the configured managed root, or at an "
            "explicit --path. Run without options to open guided creation. The current "
            "Python is used when --version is omitted."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  pload new -n tools
  pload new -n data --version 3.12 -m "Data analysis" -r numpy pandas
  pload new -p /mnt/venvs/build --version /opt/python/bin/python""",
    )
    new.add_argument(
        "--version", "-v", dest="python_version",
        help="Python version request or exact interpreter path",
    )
    new.add_argument("--name", "-n", help="exact environment name")
    new.add_argument("--path", "-p", help="exact destination instead of the managed root")
    new.add_argument(
        "--message", "-m", dest="description",
        help="human-readable purpose shown by pload list",
    )
    add_packages(new)

    init = subparsers.add_parser(
        "init", aliases=COMMAND_ALIASES["init"], help="create an environment for a project",
        description=(
            "Create a project environment. A relative --venv-dir is resolved against "
            "--project-dir, so the command behaves consistently from any directory."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  pload init
  pload init --project-dir ./service --venv-dir .runtime/python -m "Service tools"
  pload init --project-dir /srv/app --venv-dir /mnt/venvs/app -v 3.12""",
    )
    init.add_argument(
        "--version", "-v", dest="python_version",
        help="Python version request or exact interpreter path",
    )
    init.add_argument("--project-dir", "-P", default=".", help="project directory (default: current)")
    init.add_argument(
        "--venv-dir", "-e", default=".venv",
        help="environment path, relative to --project-dir or absolute",
    )
    init.add_argument(
        "--message", "-m", dest="description",
        help="human-readable purpose shown by pload list",
    )
    add_packages(init)

    remove = subparsers.add_parser(
        "rm", aliases=COMMAND_ALIASES["rm"], help="remove environments",
        description=(
            "Remove environments by stable ID or name, or select managed environments with a regular "
            "expression. Active environments and symbolic links are never removed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  pload rm v1
  pload rm data
  pload rm data test --yes
  pload rm --expression '^temporary-' --yes
  pload rm . --project-dir /srv/app""",
    )
    remove.add_argument("names", nargs="*", help="environment IDs or names")
    remove.add_argument(
        "--envs", "-n", nargs="+", default=[],
        help="additional environment IDs or names",
    )
    remove.add_argument(
        "--expression", "-e", "-re",
        help="select managed environment names with a regular expression",
    )
    remove.add_argument(
        "--project-dir", "-P", default=".",
        help="project containing .venv when removing '.'",
    )
    remove.add_argument(
        "--yes", "-y", action="store_true",
        help="skip the typed-name confirmation",
    )

    listing = subparsers.add_parser(
        "list", aliases=COMMAND_ALIASES["list"], help="list managed environments",
        description=(
            "List registered environments in a readable table. Legacy environments under "
            "the managed root are assigned stable IDs automatically."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  pload list
  pload list --expression '^(v1|data)$'
  pload list --expression '^3\\.12-'
  pload list --python-versions""",
    )
    listing.add_argument(
        "--expression", "-e", "-re", default=".*",
        help="filter environment IDs or names with a regular expression",
    )
    listing.add_argument(
        "--python-versions", "--version", "-v", action="store_true",
        help="show managed Python versions instead of environments",
    )

    path = subparsers.add_parser(
        "path", aliases=COMMAND_ALIASES["path"],
        help="print an environment or activation path by ID, name, or path",
    )
    path.add_argument("name", help="environment ID, name, '.', or explicit path")
    path.add_argument(
        "--project-dir", "-P", default=".", help="project directory used when name is '.'"
    )
    path.add_argument(
        "--shell", "-s", choices=["bash", "zsh", "fish", "powershell"],
        help="print this shell's activation script instead of the environment root",
    )

    shell_init = subparsers.add_parser(
        "shell-init", aliases=COMMAND_ALIASES["shell-init"],
        help="print shell integration; evaluate it from your profile",
    )
    shell_init.add_argument(
        "shell", choices=["bash", "zsh", "fish", "powershell"],
        help="shell syntax to generate",
    )

    python = subparsers.add_parser(
        "python", aliases=COMMAND_ALIASES["python"],
        help="install and inspect Python runtimes",
        description=(
            "Manage isolated Python runtimes through uv. Downloads are stored under "
            "PLOAD_HOME by default and respect the mirror selected by pload-install."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  pload python install 3.12
  pload python install 3.12.8
  pload python list
  pload python list --filter uv,conda
  pload python path 3.12

The list command discovers interpreters from the operating system, PATH, uv,
pyenv, Conda, mise, asdf, Homebrew, and the Windows Python Launcher. Duplicate
paths are collapsed after resolving symbolic links.

Run `pload config show` to inspect the download source and install directory.""",
    )
    python_commands = python.add_subparsers(dest="python_command", required=True)
    python_install = python_commands.add_parser(
        "install", aliases=PYTHON_ALIASES["install"],
        help="download a Python runtime with the configured source",
    )
    python_install.add_argument("version", help="version request, for example 3.12 or 3.12.8")
    python_list = python_commands.add_parser(
        "list", aliases=PYTHON_ALIASES["list"],
        help="discover all usable Python interpreters",
        description=(
            "Discover usable Python 3 interpreters and show their version, source type, "
            "and resolved executable path."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  pload python list
  pload python list --filter uv,conda
  pload python list --filter uv conda

Types: sys, pyenv, uv, conda, mise, asdf, homebrew, other
Aliases: system=sys, managed=uv""",
    )
    python_list.add_argument(
        "--filter",
        "-f",
        dest="sources",
        nargs="+",
        metavar="TYPE",
        help="source types, separated by commas or spaces",
    )
    python_path = python_commands.add_parser(
        "path", aliases=PYTHON_ALIASES["path"],
        help="resolve an installed interpreter",
    )
    python_path.add_argument("version", help="version request or exact interpreter path")

    config = subparsers.add_parser(
        "config", aliases=COMMAND_ALIASES["config"],
        help="inspect or change configuration",
    )
    config.add_argument(
        "-t", "--interactive", "--tui", action="store_true",
        help="reopen the guided configuration wizard without reinstalling pload",
    )
    config.add_argument(
        "action", nargs="?", choices=["show", "set"], default="show",
        help="show configuration or set one value (default: show)",
    )
    config.add_argument("key", nargs="?", help="setting name for `config set`")
    config.add_argument("value", nargs="?", help="new value for `config set`")
    describe = subparsers.add_parser(
        "describe", description="Describe an existing environment as one portable configuration.",
        help="create pload.toml from an existing environment",
    )
    describe.add_argument("source", help="environment ID, name, path, or Python executable")
    describe.add_argument("--output", "-o", default="pload.toml",
                          help="configuration file to write (default: pload.toml)")
    describe.add_argument("--name", "-n", help="logical environment name")
    describe.add_argument("--mode", "-m", choices=["exact", "compatible"], default="exact",
                          help="lock exact artifacts or permit re-resolution (default: exact)")
    describe.add_argument("--repository", "-r",
                          help="artifact repository; defaults to the first configured local/SSH repo")
    describe.add_argument(
        "--source", "-s", dest="package_sources", action="append", default=[],
        metavar="PACKAGE=URL",
        help="package-specific index; repeat for packages such as CUDA-enabled torch",
    )
    plan = subparsers.add_parser(
        "plan", description="Compare a declarative environment with all available resources.",
        help="explain how pload would satisfy a configuration",
    )
    plan.add_argument("file", nargs="?", default="pload.toml",
                      help="environment configuration (default: pload.toml)")
    plan.add_argument("--offline", "-o", action="store_true",
                      help="plan using only resources available without the internet")
    plan.add_argument("--json", "-j", action="store_true", help="emit machine-readable JSON")
    apply = subparsers.add_parser(
        "apply", description="Materialize the desired environment from available resources.",
        help="create or verify an environment from pload.toml",
    )
    apply.add_argument("file", nargs="?", default="pload.toml",
                       help="environment configuration (default: pload.toml)")
    apply.add_argument("--name", "-n", help="override the materialized environment name")
    apply.add_argument("--offline", "-o", action="store_true",
                       help="forbid internet access; configured local/SSH repositories remain usable")
    repo = subparsers.add_parser("repo", help="manage resource providers",
                                 description="Manage local and SSH artifact providers.")
    actions = repo.add_subparsers(dest="repo_command", required=True)
    add = actions.add_parser("add", description="Save a repository location; no credentials stored.")
    add.add_argument("name", help="repository nickname")
    add.add_argument("location", help="directory or HOST:/absolute/path")
    add.add_argument("--type", "-t", choices=["local", "ssh"], default="local",
                     help="transport (default: local)")
    actions.add_parser("list", aliases=["ls"], description="Show configured repositories.")
    remove = actions.add_parser("remove", description="Remove configuration, keeping all remote files.")
    remove.add_argument("name", help="repository nickname")
    return parser


def add_packages(parser):
    parser.add_argument("--channel", "-c", help="Python package index URL")
    parser.add_argument("--requirements", "-r", nargs="+", help="packages to install")


def _set_config_value(config, key, value):
    """Update one user-facing setting while preserving the rest of config.json."""
    from pload.settings import save_settings

    aliases = {
        "home": "home",
        "bin-dir": "bin_dir",
        "bin_dir": "bin_dir",
        "venvs-dir": "venvs_dir",
        "venvs_dir": "venvs_dir",
        "state-dir": "state_dir",
        "state_dir": "state_dir",
        "python-dir": "python.install_dir",
        "python_dir": "python.install_dir",
        "source": "python.source",
        "mirror-url": "python.mirror",
        "mirror": "python.mirror",
        "downloads-json-url": "python.downloads_json_url",
        "pip-source": "pip_source",
        "pip-index": "pip_index",
        "shell": "shell",
    }
    normalized = aliases.get(key)
    if normalized is None:
        choices = ", ".join(sorted(aliases))
        raise PloadError(f"unknown setting {key!r}; choose one of: {choices}")
    if normalized == "python.source" and value not in {"official", "ustc", "custom"}:
        raise PloadError("source must be official, ustc, or custom")
    if normalized == "pip_source" and value not in {"official", "tsinghua", "ustc", "aliyun", "custom"}:
        raise PloadError("pip-source must be official, tsinghua, ustc, aliyun, or custom")
    if normalized == "shell" and value not in {"bash", "zsh", "fish", "powershell", "none"}:
        raise PloadError("shell must be bash, zsh, fish, powershell, or none")
    settings = dict(config.settings)
    if normalized == "home":
        raise PloadError("home is selected with -H/--home; use `pload cfg -t` to change it")
    if "." in normalized:
        section, field = normalized.split(".", 1)
        settings.setdefault(section, {})[field] = value
    else:
        settings[normalized] = value
    if normalized == "python.source":
        from pload.settings import USTC_PYTHON_MIRROR

        settings.setdefault("python", {})["mirror"] = (
            USTC_PYTHON_MIRROR if value == "ustc" else None
        )
    elif normalized == "pip_source":
        from pload.installer import (
            PYPI_ALIYUN_INDEX,
            PYPI_OFFICIAL_INDEX,
            PYPI_TSINGHUA_INDEX,
            PYPI_USTC_INDEX,
        )

        indexes = {
            "official": PYPI_OFFICIAL_INDEX,
            "tsinghua": PYPI_TSINGHUA_INDEX,
            "ustc": PYPI_USTC_INDEX,
            "aliyun": PYPI_ALIYUN_INDEX,
        }
        if value in indexes:
            settings["pip_index"] = indexes[value]
    path = save_settings(config.home, settings)
    return path


def _subparser_choices(parser):
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            return choices
    return {}


def _help_parser(parser, argv):
    """Resolve the deepest command named before a help flag."""
    selected = parser
    command_path = []
    tokens = [item for item in argv if item not in HELP_FLAGS | DETAIL_FLAGS]
    command_found = False
    for token in tokens:
        if token.startswith("-"):
            continue
        choices = _subparser_choices(selected)
        if token not in choices:
            if command_found:
                break
            continue
        selected = choices[token]
        command_path.append(token)
        command_found = True
    return selected, command_path


def _global_options_table(root_parser):
    table = Table(
        box=box.SIMPLE,
        header_style="bold cyan",
        show_edge=False,
    )
    table.add_column("OPTION", style="bold green", no_wrap=True)
    table.add_column("PURPOSE")
    for action in root_parser._actions:
        if action.dest in {"help", "command"} or not action.option_strings:
            continue
        table.add_row(", ".join(action.option_strings), action.help or "")
    return table


def print_declarative_plan(plan):
    console = Console(highlight=False)
    python = plan["python"]
    console.print(Panel.fit(
        f"[bold]{plan['name']}[/]\nPython: [cyan]{python['method']}[/] · "
        f"{python['location']} · [bold]{python['status']}[/]",
        title="[bold cyan]Environment plan[/]",
        border_style="blue",
    ))
    table = Table(box=box.ROUNDED, header_style="bold cyan", border_style="blue")
    table.add_column("PACKAGE", style="bold green", no_wrap=True)
    table.add_column("VERSION", style="yellow", no_wrap=True)
    table.add_column("METHOD", style="cyan", no_wrap=True)
    table.add_column("STATUS", no_wrap=True)
    table.add_column("RESOURCE")
    for package in plan["packages"]:
        selected = package["selected"]
        if selected:
            table.add_row(package["name"], package["version"], selected["method"],
                          selected["status"], selected["location"])
        else:
            rejected = package.get("rejections", [])
            if rejected:
                table.add_row(package["name"], package["version"], "—", "incompatible",
                              rejected[0]["artifact"])
            else:
                table.add_row(package["name"], package["version"], "—", "unavailable",
                              "No resource satisfies the configuration")
    console.print(table)


def _print_spaced_section(console, renderable):
    """Give a standalone section consistent visual breathing room."""
    console.print()
    console.print()
    console.print(renderable)
    console.print()


def _print_arrow_table(console, title, table):
    """Print a left-aligned arrow heading with readable space around its table."""
    console.print()
    console.print()
    console.print(Text(f"▶ {title}", style="bold cyan"))
    console.print()
    console.print(table)
    console.print()


def _brief_help(parser, command_path, root_parser=None):
    console = Console(highlight=False)
    title = f"pload {__version__}" if not command_path else "pload " + " ".join(command_path)
    description = parser.description or "Command-line help"
    usage = " ".join(parser.format_usage().split())
    if command_path and usage.startswith(f"usage: {parser.prog}"):
        usage = usage.replace(
            f"usage: {parser.prog}",
            f"usage: {' '.join(['pload', *command_path])}",
            1,
        )
    usage_text = Text()
    usage_tokens = usage.split()
    if usage_tokens and usage_tokens[0] == "usage:":
        usage_tokens = usage_tokens[1:]
    for index, token in enumerate(usage_tokens):
        if index:
            usage_text.append(" ")
        if token.startswith("pload"):
            usage_text.append(token, style="bold green")
        elif token.startswith("-"):
            usage_text.append(token, style="bold yellow")
        elif token.startswith(("[", "{")):
            usage_text.append(token, style="bold cyan")
        else:
            usage_text.append(token, style="white")
    console.print(Panel.fit(
        Text(description, style="white"),
        title=f"[bold cyan]{title}[/]",
        border_style="blue",
    ))
    _print_spaced_section(console, Panel.fit(
        usage_text,
        title="[bold yellow]USAGE[/]",
        title_align="center",
        border_style="yellow",
    ))

    if not command_path:
        table = Table(box=box.SIMPLE, header_style="bold cyan", show_edge=False)
        table.add_column("COMMAND", style="bold green", no_wrap=True)
        table.add_column("ALIASES", style="yellow", no_wrap=True)
        table.add_column("PURPOSE")
        summaries = {
            "new": "Create a managed virtual environment",
            "init": "Create a project-local environment",
            "list": "List environments and their stable IDs",
            "rm": "Remove an environment by ID or name",
            "python": "Discover or install Python runtimes",
            "path": "Print an environment path",
            "config": "Show effective configuration",
            "shell-init": "Print shell activation integration",
            "describe": "Write one portable configuration for an existing environment",
            "plan": "Compare a configuration with available resources",
            "apply": "Materialize the environment declared by pload.toml",
            "repo": "Manage local and SSH artifact providers",
        }
        for command, summary in summaries.items():
            aliases = COMMAND_ALIASES[command]
            table.add_row(command, ", ".join(aliases) if aliases else "—", summary)
        console.print(table)
        console.print("[bold cyan]Quick start[/]")
        console.print("  [green]pload new[/]  [dim]# guided creation[/]")
        console.print("  [green]pload new -n data -m \"Data analysis\"[/]")
        console.print("  [green]pload ls[/]")
        console.print("  [green]pload v1[/]  [dim]# activate after shell initialization[/]")
        _print_arrow_table(console, "Global options", _global_options_table(root_parser or parser))
    else:
        choices = _subparser_choices(parser)
        if choices:
            table = Table(box=box.SIMPLE, header_style="bold cyan", show_edge=False)
            table.add_column("SUBCOMMAND", style="bold green")
            table.add_column("PURPOSE")
            seen = set()
            for name, child in choices.items():
                canonical = PYTHON_COMMAND_NAMES.get(name, name)
                if canonical in seen:
                    continue
                seen.add(canonical)
                aliases = PYTHON_ALIASES.get(canonical, ())
                label = canonical + (f" ({', '.join(aliases)})" if aliases else "")
                table.add_row(label, child.description or "See detailed help")
            console.print(table)
        else:
            table = Table(box=box.SIMPLE, header_style="bold cyan", show_edge=False)
            table.add_column("ARGUMENT / OPTION", style="bold green", no_wrap=True)
            table.add_column("PURPOSE")
            for action in parser._actions:
                if action.dest in {"help", "command", "python_command"}:
                    continue
                label = ", ".join(action.option_strings) if action.option_strings else action.dest
                if action.nargs in {"+", "*"}:
                    label += " ..."
                table.add_row(label, action.help or "")
            _print_arrow_table(console, "Arguments and options", table)

    detail_command = " ".join(command_path)
    detail = f"pload {detail_command} -h -d" if detail_command else "pload -h -d"
    console.print(f"[dim]Detailed help: [bold]{detail}[/bold][/dim]")


def render_help(argv):
    parser = build_parser()
    selected, command_path = _help_parser(parser, argv)
    if any(item in DETAIL_FLAGS for item in argv):
        canonical_path = []
        for index, item in enumerate(command_path):
            if index == 0:
                canonical_path.append(COMMAND_NAMES.get(item, item))
            else:
                canonical_path.append(PYTHON_COMMAND_NAMES.get(item, item))
        render_detailed_help(selected, canonical_path)
    else:
        _brief_help(selected, command_path, root_parser=parser)


def render_landing():
    """Show the no-argument welcome screen and the smallest useful command tour."""
    console = Console(highlight=False)
    art = Text(
        """   ____  _                 _
  |  _ \\| | ___   __ _  __| |
  | |_) | |/ _ \\ / _` |/ _` |
  |  __/| | (_) | (_| | (_| |
  |_|   |_|\\___/ \\__,_|\\__,_|""",
        style="bold cyan",
    )
    console.print(art)
    console.print(f"[bold white]pload {__version__}[/]  [dim]Python environments, kept simple.[/]")
    table = Table(box=box.SIMPLE, header_style="bold cyan", show_edge=False)
    table.add_column("COMMAND", style="bold green", no_wrap=True)
    table.add_column("WHAT IT DOES")
    table.add_row("pload cfg", "Show where pload stores its data")
    table.add_row("pload python list", "Find every usable Python interpreter")
    table.add_row("pload describe v1", "Describe an environment in pload.toml")
    table.add_row("pload apply", "Create exactly what pload.toml declares")
    table.add_row("pload new", "Open guided environment creation")
    table.add_row("pload new -n data -v 3.12", "Create a named virtual environment")
    table.add_row("pload list", "List environments, IDs, and descriptions")
    table.add_row("pload v1", "Activate an environment by ID")
    _print_arrow_table(console, "Simple usage", table)
    _print_arrow_table(console, "Global options", _global_options_table(build_parser()))
    console.print("[dim]More help: [bold]pload -h[/bold]  ·  examples: [bold]pload -h -d[/bold][/dim]")


def shell_script(shell):
    if shell in {"bash", "zsh"}:
        return r'''pload() {
    case "${1:-}" in
        ""|new|init|i|rm|remove|del|delete|list|ls|path|p|shell-init|shell|python|py|config|cfg|describe|plan|apply|repo|-*)
            command pload "$@"
            ;;
        *)
            local activate_path
            activate_path="$(command pload path "${1:-.}" --shell ''' + shell + r''')" || return $?
            source "$activate_path"
            ;;
    esac
}'''
    if shell == "fish":
        return r'''function pload
    switch "$argv[1]"
        case '' new init i rm remove del delete list ls path p shell-init shell python py config cfg describe plan apply repo '-*'
            command pload $argv
        case '*'
            set -l name .
            if test (count $argv) -gt 0
                set name $argv[1]
            end
            set -l activate_path (command pload path "$name" --shell fish)
            or return $status
            source "$activate_path"
    end
end'''
    return r'''function pload {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PloadArgs)
    $commands = @('new', 'init', 'i', 'rm', 'remove', 'del', 'delete', 'list', 'ls', 'path', 'p', 'shell-init', 'shell', 'python', 'py', 'config', 'cfg', 'describe', 'plan', 'apply', 'repo', '-h', '--help', '--version')
    $backend = Get-Command -Name @('pload.exe', 'pload.cmd') -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $backend) { throw 'pload executable not found on PATH' }
    if ($PloadArgs.Count -eq 0) {
        & $backend.Source
        return
    }
    if ($PloadArgs.Count -gt 0 -and ($commands -contains $PloadArgs[0] -or $PloadArgs[0].StartsWith('-'))) {
        & $backend.Source @PloadArgs
        return
    }
    $name = if ($PloadArgs.Count -eq 0) { '.' } else { $PloadArgs[0] }
    $activatePath = & $backend.Source path $name --shell powershell
    if ($LASTEXITCODE -eq 0) { . $activatePath }
}'''


def _guided_new(config):
    """Collect useful creation choices when ``pload new`` is run by itself."""
    console = Console(highlight=False)
    console.print(Panel.fit(
        "Choose an interpreter and an optional name. Press Enter to accept defaults.",
        title="[bold cyan]Guided environment creation[/]",
        border_style="blue",
    ))
    runtimes = PythonManager(config).discover()
    if runtimes:
        console.print("[dim]Use a Python ID, alias, version, or interpreter path:[/]")
        print_python_table(runtimes)
    else:
        console.print("[yellow]No Python was discovered; the current Python is the default.[/]")

    def ask(label, default=""):
        suffix = f" [{default}]" if default else ""
        value = input(f"{label}{suffix}: ").strip()
        return value or default

    version = ask("Python ID, alias, version, or path", "current")
    _, suggested_name = config.resolve_venv_path(version=version)
    name = ask("Environment name (blank generates one)")
    if not name:
        console.print(f"[dim]Generated name: [bold]{suggested_name}[/][/dim]")
    description = ask("Description (optional)")
    packages = ask("Packages, separated by spaces (optional)")
    return {
        "python_version": version,
        "name": name or None,
        "description": description or None,
        "requirements": packages.split() or None,
    }


def run(argv=None):
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if not raw_args:
        render_landing()
        return 0
    if any(item in HELP_FLAGS for item in raw_args):
        render_help(raw_args)
        return 0
    args = build_parser().parse_args(raw_args)
    command = COMMAND_NAMES.get(args.command, args.command)
    config = ConfigManager(args.home, args.venvs_dir, args.state_dir)
    venvs = VenvManager(config)
    dependencies = DependencyManager(config)

    if command in {"describe", "plan", "apply", "repo"}:
        if command == "repo":
            from pload.snapshots import RepositoryManager

            repositories = RepositoryManager(config)
            if args.repo_command == "add":
                repositories.add(args.name, args.location, args.type)
            elif args.repo_command == "remove":
                repositories.remove(args.name)
            else:
                print(json.dumps(repositories.repositories(), indent=2))
            return 0
        from pload.declarative import DeclarativeEnvironmentManager

        manager = DeclarativeEnvironmentManager(config)
        if command == "describe":
            progress_console = Console(highlight=False)
            print(manager.describe(
                args.source, args.output, args.name, args.mode, args.repository,
                args.package_sources,
                progress=lambda message: progress_console.print(
                    Text("• " + message, style="cyan")
                ),
            ))
        elif command == "plan":
            plan = manager.plan(args.file, args.offline)
            if args.json:
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            else:
                print_declarative_plan(plan)
        else:
            progress_console = Console(highlight=False)
            print(manager.apply(
                args.file, args.name, args.offline,
                progress=lambda message: progress_console.print(
                    Text("• " + message, style="cyan")
                ),
            ))
        return 0

    if command == "new":
        if not any((args.python_version, args.name, args.path, args.description, args.requirements, args.channel)):
            guided = _guided_new(config)
            args.python_version = guided["python_version"]
            args.name = guided["name"]
            args.description = guided["description"]
            args.requirements = guided["requirements"]
        path = venvs.create_venv(
            version=args.python_version,
            target=args.path,
            name=args.name,
            description=args.description,
        )
        dependencies.install_dependencies(path, args.requirements, args.channel)
        return 0

    if command == "init":
        project = Path(args.project_dir).expanduser().resolve()
        project.mkdir(parents=True, exist_ok=True)
        path = venvs.create_venv(
            version=args.python_version,
            is_local=True,
            project_dir=project,
            target=args.venv_dir,
            description=args.description,
        )
        dependencies.install_dependencies(path, args.requirements, args.channel)
        return 0

    if command == "rm":
        names = list(dict.fromkeys(args.names + args.envs))
        if args.expression:
            pattern = re.compile(args.expression)
            names.extend(name for name in venvs.get_existing_venvs() if pattern.fullmatch(name))
            names = list(dict.fromkeys(names))
        if not names:
            raise PloadError("no environments selected")
        for name in names:
            if not args.yes:
                confirmation = input(f"Remove {name!r}? Type its name to confirm: ")
                if confirmation != name:
                    raise PloadError("removal cancelled")
            venvs.remove_venv(name, project_dir=args.project_dir)
        return 0

    if command == "list":
        pattern = re.compile(args.expression)
        if args.python_versions:
            for version in PythonManager(config).get_installed_versions():
                if pattern.fullmatch(version):
                    print(version)
        else:
            environments = [
                item for item in venvs.environments()
                if pattern.fullmatch(item.get("name", ""))
                or pattern.fullmatch(item.get("id", ""))
            ]
            print_environment_table(environments)
        return 0

    if command == "path":
        if args.shell:
            print(venvs.activation_script(
                args.name, shell=args.shell, project_dir=args.project_dir
            ))
        else:
            print(venvs.resolve_existing(args.name, project_dir=args.project_dir))
        return 0

    if command == "shell-init":
        print(shell_script(args.shell))
        return 0

    if command == "python":
        manager = PythonManager(config)
        python_command = PYTHON_COMMAND_NAMES.get(args.python_command, args.python_command)
        if python_command == "install":
            manager.install_python(args.version)
        elif python_command == "list":
            print_python_table(manager.discover(args.sources))
        elif python_command == "path":
            print(config.get_python_path(args.version))
        return 0

    if command == "config":
        if args.interactive:
            from pload.installer import interactive_configure

            interactive_configure(config.home)
            return 0
        if args.action == "set":
            if not args.key or args.value is None:
                raise PloadError("usage: pload cfg set SETTING VALUE")
            path = _set_config_value(config, args.key, args.value)
            print(f"[*] Updated configuration: {path}")
            return 0
        effective = dict(config.settings)
        effective.update({
            "home": str(config.home),
            "venvs_dir": str(config.venv_path),
            "state_dir": str(config.state_path),
            "python": config.python,
        })
        print(json.dumps(effective, ensure_ascii=False, indent=2))
        return 0

    return 0


def main(argv=None):
    try:
        return run(argv)
    except (PloadError, PythonNotFoundError, re.error, OSError) as exc:
        print(f"pload: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
