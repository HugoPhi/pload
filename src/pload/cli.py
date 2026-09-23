import argparse
import re
import sys
from pathlib import Path

from pload import __version__
from pload.errors import PloadError
from pload.managers.dependency import DependencyManager
from pload.managers.platform import ConfigManager, PythonNotFoundError
from pload.managers.pyversion import PythonManager
from pload.managers.venv import VenvManager


def build_parser():
    parser = argparse.ArgumentParser(
        prog="pload",
        description="Create and activate relocatable Python virtual environments.",
    )
    parser.add_argument("--home", help="data root (or set PLOAD_HOME)")
    parser.add_argument("--venvs-dir", help="managed environment root (or PLOAD_VENVS_DIR)")
    parser.add_argument("--state-dir", help="state root (or PLOAD_STATE_DIR)")
    parser.add_argument("--version", action="version", version=f"pload {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    new = subparsers.add_parser("new", help="create a managed environment")
    new.add_argument("--version", "-v", dest="python_version")
    new.add_argument("--message", "-m", default="normal")
    new.add_argument("--name", help="exact environment name")
    new.add_argument("--path", help="exact destination instead of the managed root")
    add_packages(new)

    init = subparsers.add_parser("init", help="create an environment for a project")
    init.add_argument("--version", "-v", dest="python_version")
    init.add_argument("--project-dir", default=".", help="project directory (default: current)")
    init.add_argument(
        "--venv-dir", default=".venv",
        help="environment path, relative to --project-dir or absolute",
    )
    add_packages(init)

    remove = subparsers.add_parser("rm", aliases=["remove"], help="remove environments")
    remove.add_argument("names", nargs="*")
    remove.add_argument("--envs", "-n", nargs="+", default=[])
    remove.add_argument("--expression", "-e", "-re")
    remove.add_argument("--project-dir", default=".")
    remove.add_argument("--yes", "-y", action="store_true")

    listing = subparsers.add_parser("list", help="list managed environments")
    listing.add_argument("--expression", "-e", "-re", default=".*")
    listing.add_argument("--python-versions", "--version", "-v", action="store_true")

    path = subparsers.add_parser("path", help="print an environment or activation path")
    path.add_argument("name")
    path.add_argument("--project-dir", default=".")
    path.add_argument("--shell", choices=["bash", "zsh", "fish", "powershell"])

    shell_init = subparsers.add_parser(
        "shell-init", help="print shell integration; evaluate it from your profile"
    )
    shell_init.add_argument("shell", choices=["bash", "zsh", "fish", "powershell"])
    return parser


def add_packages(parser):
    parser.add_argument("--channel", "-c", help="Python package index URL")
    parser.add_argument("--requirements", "-r", nargs="+", help="packages to install")


def shell_script(shell):
    if shell in {"bash", "zsh"}:
        return r'''pload() {
    case "${1:-}" in
        new|init|rm|remove|list|path|shell-init|-*)
            command python_virtual_env_load "$@"
            ;;
        *)
            local activate_path
            activate_path="$(command python_virtual_env_load path "${1:-.}" --shell ''' + shell + r''')" || return $?
            source "$activate_path"
            ;;
    esac
}'''
    if shell == "fish":
        return r'''function pload
    switch "$argv[1]"
        case new init rm remove list path shell-init '-*'
            command python_virtual_env_load $argv
        case '*'
            set -l name .
            if test (count $argv) -gt 0
                set name $argv[1]
            end
            set -l activate_path (command python_virtual_env_load path "$name" --shell fish)
            or return $status
            source "$activate_path"
    end
end'''
    return r'''function pload {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PloadArgs)
    $commands = @('new', 'init', 'rm', 'remove', 'list', 'path', 'shell-init', '-h', '--help', '--version')
    if ($PloadArgs.Count -gt 0 -and ($commands -contains $PloadArgs[0] -or $PloadArgs[0].StartsWith('-'))) {
        python_virtual_env_load @PloadArgs
        return
    }
    $name = if ($PloadArgs.Count -eq 0) { '.' } else { $PloadArgs[0] }
    $activatePath = python_virtual_env_load path $name --shell powershell
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
            for name in venvs.get_existing_venvs():
                if pattern.fullmatch(name):
                    print(name)
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

    return 0


def main(argv=None):
    try:
        return run(argv)
    except (PloadError, PythonNotFoundError, re.error) as exc:
        print(f"pload: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
