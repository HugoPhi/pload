from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

GUIDES = {
    (): r"""
# A practical pload walkthrough

`pload` keeps the manager itself separate from the virtual environments it
creates. You can delete an environment without deleting the `pload` command.

## Create, inspect, and enter an environment

```console
$ pload new -n data --version 3.12 -d "Data analysis"
⠋ Creating data at /home/me/venvs/data
✓ Created data
✓ Assigned v1

$ pload ls
ID   NAME   PYTHON   DESCRIPTION
v1   data   3.12.8   Data analysis

$ pload v1
(data) $
```

The first command chooses a discovered Python 3.12 interpreter, creates the
environment under the configured environment root, and records its description
and stable ID. `pload v1` activates it after shell integration is enabled.

## Install a Python without pyenv

```console
$ pload python install 3.13
$ pload py ls --filter uv
$ pload new -n latest --version 3.13
```

The Python runtime is downloaded into the directory selected during setup. It
does not replace the operating system Python.

## What changes on disk

- `PLOAD_HOME/config.json` stores directory and mirror choices.
- `PLOAD_HOME/runtime` contains pload's private runtime.
- the configured environment root contains virtual environments.
- the configured state root contains environment IDs and descriptions.
- project-local `pload init` environments may live outside the managed root.

Use `pload cfg` to see the exact effective paths before creating anything.
""",
    ("new",): r"""
# Create a managed environment

## Typical example

```console
$ pload new -n web --version 3.12 -d "Web API" -r fastapi uvicorn
⠙ Creating web at /home/me/venvs/web
✓ Created web
✓ Assigned v3
```

This selects the newest discovered Python matching `3.12`, creates `web` below
the managed environment root, stores the description, assigns the next ID, and
then installs `fastapi` and `uvicorn` inside that environment.

## Choose an exact location or interpreter

```console
$ pload new --path /mnt/project-envs/build \
    --version /opt/python/bin/python \
    -d "Release build tools"
```

The environment may live anywhere; its metadata remains in the configured
pload state directory. Use an absolute interpreter path when version discovery
is not appropriate.

## Effects and failure behavior

- Creates one virtual-environment directory and one registry entry.
- Does not modify the system Python or activate the environment automatically.
- If Python cannot create the environment, the incomplete directory is removed.
- If later package installation fails, the valid environment remains so it can
  be inspected or removed with `pload rm`.
""",
    ("init",): r"""
# Create an environment for the current project

```console
$ cd ~/projects/service
$ pload i -d "Service development"
✓ Created .venv
✓ Assigned v4
$ pload .
```

By default this creates `./.venv`, registers it, and lets `pload .` activate it.
The project and environment can also be separated:

```console
$ pload init --project-dir /srv/service \
    --venv-dir /mnt/environments/service \
    --version 3.12 -r pytest
```

Here the project remains in `/srv/service`, while Python packages are stored
under `/mnt/environments/service`. A relative `--venv-dir` is resolved against
`--project-dir`, not against whichever directory the shell happens to use.

## Effects

- Creates the project directory if it does not exist.
- Creates and registers one environment, including its ID and description.
- Never writes the environment into the source tree when an absolute
  `--venv-dir` is supplied.
""",
    ("list",): r"""
# Inspect environments

```console
$ pload ls
ID   NAME      PYTHON   DESCRIPTION          PATH
v1   data      3.12.8   Data analysis       /home/me/venvs/data
v2   service   3.11.9   Backend development /mnt/envs/service
```

The ID is stable and may be used with `pload v1`, `pload p v1`, or
`pload rm v1`. The Python column comes from the environment's `pyvenv.cfg`.

## Filter without changing environments

```console
$ pload ls --expression '^(v1|data)$'
$ pload list --expression '^project-'
```

The expression is matched against both IDs and names. Listing never deletes or
updates an environment. On the first run after upgrading, valid legacy
environments under the managed root receive IDs; that is the only state change.
""",
    ("rm",): r"""
# Remove environments safely

```console
$ pload rm v3
Remove 'v3'? Type its name to confirm: v3
✓ Removed /home/me/venvs/web

$ pload del old-test --yes
```

An ID or name selects the same registered environment. `--yes` skips the typed
confirmation and is useful for scripts.

## Select several environments

```console
$ pload rm test-a test-b --yes
$ pload rm --expression '^temporary-' --yes
```

## Safety effects

- Deletes the selected virtual-environment directory and its registry entry.
- Refuses to delete the currently active environment.
- Refuses to manage a symbolic link as an environment.
- Does not reuse the removed ID; the next environment receives a new ID.
""",
    ("path",): r"""
# Resolve an environment for scripts

```console
$ pload p v1
/home/me/venvs/data

$ pload path data --shell bash
/home/me/venvs/data/bin/activate
```

This command only prints a resolved path. It does not activate or modify the
environment. Shell integration uses the `--shell` form internally, then sources
the returned activation script in the current shell.
""",
    ("shell-init",): r"""
# Enable activation in the current shell

```bash
eval "$(pload shell-init bash)"
eval "$(pload shell-init zsh)"
```

```fish
pload shell-init fish | source
```

After this, `pload v1`, `pload data`, and `pload .` can change the current
shell's active environment. Printing the integration code has no side effect by
itself; a profile changes only when the installer is explicitly asked to update
one or when you add the command manually.
""",
    ("python",): r"""
# Find or install Python runtimes

```console
$ pload py ls
$ pload py ls --filter sys,uv,conda
$ pload python install 3.12
$ pload py p 3.12
```

`list` discovers existing interpreters from the system, uv, pyenv, Conda, mise,
asdf, Homebrew, and PATH. `install` downloads an isolated runtime through uv.
`path` shows which executable a version request will use.

Installed runtimes and download caches stay under the configured pload paths;
the operating system Python is never replaced.
""",
    ("python", "install"): r"""
# Download a managed Python

```console
$ pload python install 3.12
Installing managed Python 3.12 into /home/me/.pload/pythons
Installed Python 3.12: .../python3.12

$ pload new -n data --version 3.12
```

The version may be a minor request such as `3.12` or an exact patch such as
`3.12.8`. uv downloads the runtime using the runtime source chosen during
`pload-install`.

## Effects

- Writes the runtime, executable links, and cache only to configured paths.
- Does not modify `/usr/bin`, Homebrew, pyenv, or an existing Conda setup.
- A domestic PyPI mirror does not control this download; runtime and package
  sources are deliberately configured separately.
""",
    ("python", "list"): r"""
# Discover every usable Python

```console
$ pload py ls
VERSION   TYPE      PATH
3.11.9    conda     /opt/miniforge/envs/data/bin/python
3.12.8    uv        /home/me/.pload/pythons/.../python3.12
3.13.3    homebrew  /opt/homebrew/.../python3.13

$ pload py ls --filter uv,conda
```

Types include `sys`, `pyenv`, `uv`, `conda`, `mise`, `asdf`, `homebrew`, and
`other`. Commas and spaces are both accepted by `--filter`.

Discovery probes candidate executables for their real version and resolves
symbolic links to suppress duplicates. It does not install, remove, or change
any interpreter.
""",
    ("python", "path"): r"""
# See which Python a request selects

```console
$ pload py p 3.12
/home/me/.pload/pythons/cpython-3.12.8/bin/python3.12
```

Minor-version requests select the newest matching patch version. The lookup can
use managed uv runtimes or a discovered interpreter from another supported
source. This command is read-only and is useful before creating an environment.
""",
    ("config",): r"""
# Inspect effective configuration

```console
$ pload cfg
{
  "home": "/home/me/.pload",
  "venvs_dir": "/mnt/venvs",
  "state_dir": "/home/me/.pload/state",
  "pip_source": "ustc"
}
```

The output combines saved configuration, command-line overrides, and relevant
environment variables. It is read-only and is the quickest way to verify where
a new environment, Python runtime, cache, or registry will be written.
""",
}


def render_detailed_help(parser, command_path):
    console = Console(highlight=False)
    content = GUIDES.get(tuple(command_path), GUIDES[()])
    console.print(Markdown(content.strip()))

    rows = []
    for action in parser._actions:
        if action.dest in {"help", "command", "python_command"}:
            continue
        label = ", ".join(action.option_strings) if action.option_strings else action.dest
        rows.append((label, action.help or ""))
    if rows:
        table = Table(
            title="Related options",
            box=box.ROUNDED,
            header_style="bold cyan",
            border_style="blue",
        )
        table.add_column("OPTION", style="bold green", no_wrap=True)
        table.add_column("MEANING")
        for label, help_text in rows:
            table.add_row(label, help_text)
        console.print(table)
