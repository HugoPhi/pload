import argparse
import json
import re
import sys
from pathlib import Path

from pload import __version__
from pload.display import print_environment_table, print_python_table
from pload.errors import PloadError
from pload.managers.dependency import DependencyManager
from pload.managers.platform import ConfigManager, PythonNotFoundError
from pload.managers.pyversion import PythonManager
from pload.managers.venv import VenvManager


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
  pload new --name data -v 3.12 -d "Data analysis"
                                   Create a described environment with an ID
  pload v1                         Activate it by ID (after shell initialization)
  pload init                       Create .venv for the current project
  pload .                          Activate the project environment

Isolation:
  PLOAD_HOME=/mnt/pload pload list
  pload --venvs-dir /mnt/venvs new --name tools
  pload init --project-dir ./app --venv-dir /mnt/venvs/app

Run `pload <command> -h` for command-specific examples.""",
    )
    parser.add_argument("--home", help="data root (or set PLOAD_HOME)")
    parser.add_argument("--venvs-dir", help="managed environment root (or PLOAD_VENVS_DIR)")
    parser.add_argument("--state-dir", help="state root (or PLOAD_STATE_DIR)")
    parser.add_argument("--version", action="version", version=f"pload {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    new = subparsers.add_parser(
        "new", help="create a managed environment",
        description=(
            "Create a virtual environment under the configured managed root, or at an "
            "explicit --path. The current Python is used when --version is omitted."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  pload new --name tools
  pload new --name data --version 3.12 -d "Data analysis" -r numpy pandas
  pload new --path /mnt/venvs/build --version /opt/python/bin/python""",
    )
    new.add_argument("--version", "-v", dest="python_version")
    new.add_argument("--message", "-m", default="normal")
    new.add_argument("--name", help="exact environment name")
    new.add_argument("--path", help="exact destination instead of the managed root")
    new.add_argument("--description", "-d", help="human-readable purpose shown by pload list")
    add_packages(new)

    init = subparsers.add_parser(
        "init", help="create an environment for a project",
        description=(
            "Create a project environment. A relative --venv-dir is resolved against "
            "--project-dir, so the command behaves consistently from any directory."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  pload init
  pload init --project-dir ./service --venv-dir .runtime/python -d "Service tools"
  pload init --project-dir /srv/app --venv-dir /mnt/venvs/app -v 3.12""",
    )
    init.add_argument("--version", "-v", dest="python_version")
    init.add_argument("--project-dir", default=".", help="project directory (default: current)")
    init.add_argument(
        "--venv-dir", default=".venv",
        help="environment path, relative to --project-dir or absolute",
    )
    init.add_argument("--description", "-d", help="human-readable purpose shown by pload list")
    add_packages(init)

    remove = subparsers.add_parser(
        "rm", aliases=["remove"], help="remove environments",
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
    remove.add_argument("names", nargs="*")
    remove.add_argument("--envs", "-n", nargs="+", default=[])
    remove.add_argument("--expression", "-e", "-re")
    remove.add_argument("--project-dir", default=".")
    remove.add_argument("--yes", "-y", action="store_true")

    listing = subparsers.add_parser(
        "list", help="list managed environments",
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
    listing.add_argument("--expression", "-e", "-re", default=".*")
    listing.add_argument("--python-versions", "--version", "-v", action="store_true")

    path = subparsers.add_parser(
        "path", help="print an environment or activation path by ID, name, or path"
    )
    path.add_argument("name")
    path.add_argument("--project-dir", default=".")
    path.add_argument("--shell", choices=["bash", "zsh", "fish", "powershell"])

    shell_init = subparsers.add_parser(
        "shell-init", help="print shell integration; evaluate it from your profile"
    )
    shell_init.add_argument("shell", choices=["bash", "zsh", "fish", "powershell"])

    python = subparsers.add_parser(
        "python", help="install and inspect Python runtimes",
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
        "install", help="download a Python runtime with the configured source"
    )
    python_install.add_argument("version", help="version request, for example 3.12 or 3.12.8")
    python_list = python_commands.add_parser(
        "list",
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
    python_path = python_commands.add_parser("path", help="resolve an installed interpreter")
    python_path.add_argument("version")

    config = subparsers.add_parser("config", help="inspect effective configuration")
    config.add_argument("action", nargs="?", choices=["show"], default="show")
    return parser


def add_packages(parser):
    parser.add_argument("--channel", "-c", help="Python package index URL")
    parser.add_argument("--requirements", "-r", nargs="+", help="packages to install")


def shell_script(shell):
    if shell in {"bash", "zsh"}:
        return r'''pload() {
    case "${1:-}" in
        new|init|rm|remove|list|path|shell-init|python|config|-*)
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
        case new init rm remove list path shell-init python config '-*'
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
    $commands = @('new', 'init', 'rm', 'remove', 'list', 'path', 'shell-init', 'python', 'config', '-h', '--help', '--version')
    $backend = Get-Command -Name @('pload.exe', 'pload.cmd') -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $backend) { throw 'pload executable not found on PATH' }
    if ($PloadArgs.Count -gt 0 -and ($commands -contains $PloadArgs[0] -or $PloadArgs[0].StartsWith('-'))) {
        & $backend.Source @PloadArgs
        return
    }
    $name = if ($PloadArgs.Count -eq 0) { '.' } else { $PloadArgs[0] }
    $activatePath = & $backend.Source path $name --shell powershell
    if ($LASTEXITCODE -eq 0) { . $activatePath }
}'''


def run(argv=None):
    args = build_parser().parse_args(argv)
    config = ConfigManager(args.home, args.venvs_dir, args.state_dir)
    venvs = VenvManager(config)
    dependencies = DependencyManager(config)

    if args.command == "new":
        path = venvs.create_venv(
            version=args.python_version,
            message=args.message,
            target=args.path,
            name=args.name,
            description=args.description,
        )
        dependencies.install_dependencies(path, args.requirements, args.channel)
        return 0

    if args.command == "init":
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

    if args.command in {"rm", "remove"}:
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

    if args.command == "list":
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

    if args.command == "path":
        if args.shell:
            print(venvs.activation_script(
                args.name, shell=args.shell, project_dir=args.project_dir
            ))
        else:
            print(venvs.resolve_existing(args.name, project_dir=args.project_dir))
        return 0

    if args.command == "shell-init":
        print(shell_script(args.shell))
        return 0

    if args.command == "python":
        manager = PythonManager(config)
        if args.python_command == "install":
            manager.install_python(args.version)
        elif args.python_command == "list":
            print_python_table(manager.discover(args.sources))
        elif args.python_command == "path":
            print(config.get_python_path(args.version))
        return 0

    if args.command == "config":
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
    except (PloadError, PythonNotFoundError, re.error) as exc:
        print(f"pload: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
