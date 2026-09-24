# pload

![pload welcome screen on macOS](docs/images/pload-welcome-macos.png)

`pload` is a relocatable Python runtime and virtual-environment manager for
Bash, Zsh, Fish, and PowerShell. Its private runtime, downloaded Python
versions, virtual environments, registry, and caches can all live under
directories you choose. pyenv is supported for discovery, but is not required.

Running `pload` without arguments opens a small welcome screen. Use `-h` for a
complete parameter reference and `-h -d` for practical examples and effects.

## Contents

- [Install](#install)
- [First run](#first-run)
- [Configure later](#configure-later)
- [Shell activation](#shell-activation)
- [Discover and install Python](#discover-and-install-python)
- [Create and activate environments](#create-and-activate-environments)
- [Help and aliases](#help-and-aliases)
- [Isolation and directory layout](#isolation-and-directory-layout)
- [Command reference](#command-reference)
- [Development](#development)

## Install

Install the small bootstrap package, then start the guided installer:

```console
python -m pip install --user --upgrade pload
python -m pload.installer
```

If your distribution enforces PEP 668, use pipx or a dedicated bootstrap
virtual environment:

```console
python3 -m venv ~/.pload-bootstrap
~/.pload-bootstrap/bin/python -m pip install --upgrade pload
~/.pload-bootstrap/bin/python -m pload.installer
```

On Windows, replace `python` with `py` when appropriate. If pipx is already
available:

```console
pipx install pload
pload-install
```

The installer uses colored numbered choices for the pload data directory,
launcher directory, virtual-environment directory, Python directory, runtime
source, pip index, and optional shell integration. Press Enter to accept a
marked default.

After installation it prints an ASCII welcome screen with copyable next steps.
The same screen is shown whenever you run bare `pload` (see the screenshot at
the top of this page).

For a non-interactive setup:

```console
python -m pload.installer --yes \
  --home /mnt/tools/pload \
  --bin-dir ~/.local/bin \
  --venvs-dir /mnt/venvs \
  --python-dir /mnt/python \
  --source ustc \
  --pip-source tsinghua
```

`--yes` accepts explicit values and saved defaults. It only changes a shell
profile when `--shell` is supplied or already configured.

## First run

```console
pload
```

The no-argument screen gives the shortest useful tour:

```console
pload cfg                         # show effective paths and sources
pload python list                 # discover usable Python interpreters
pload new -n data -v 3.12         # create an environment
pload list                        # list IDs, descriptions, and paths
pload v1                          # activate an environment by ID
```

Run `pload new` without options to start the guided creator. It lists detected
Python runtimes, then asks for the interpreter, environment name, description,
and optional packages. Press Enter to accept the suggested value at each step.

## Configure later

Inspect the effective configuration:

```console
pload cfg
pload config show
```

Change one value without reinstalling pload or uv:

```console
pload cfg set source ustc
pload cfg set pip-source tsinghua
pload cfg set venvs-dir ~/venvs
pload cfg set python-dir ~/.pload/pythons
pload cfg set shell zsh
```

Reopen the complete setup wizard at any time:

```console
pload cfg -t
```

The wizard reuses current values as defaults and updates configuration plus the
selected shell profile. It does not reinstall pload, uv, or existing
environments. Configuration is stored in `PLOAD_HOME/config.json`.

## Shell activation

The installer can update a shell profile. To configure it manually:

```bash
# Bash
eval "$(pload shell-init bash)"

# Zsh
eval "$(pload shell-init zsh)"

# Fish
pload shell-init fish | source
```

PowerShell:

```powershell
Invoke-Expression (& pload shell-init powershell | Out-String)
```

Then `pload v1`, `pload data`, and `pload .` can activate environments in the
current shell.

## Discover and install Python

`pload python list` scans usable interpreters from the operating system, PATH,
uv, pyenv, Conda, mise, asdf, Homebrew, and the Windows Python Launcher.
Duplicate executable paths are collapsed:

```console
pload python list
pload python list --filter uv,conda
pload python list --filter uv conda
pload python path 3.12
```

Each distinct executable receives a stable Python ID and readable alias:

```text
ID   ALIAS          VERSION  TYPE    PATH
py1  uv-v3.12.8     3.12.8   uv      ~/.pload/pythons/.../python3.12
py2  conda-v3.11.9  3.11.9   conda   ~/miniforge3/envs/data/bin/python
```

The ID and alias are separate columns in the real output:

![Python runtime discovery on macOS](docs/images/pload-python-list-macos.png)

Use any of these forms when selecting an interpreter:

```console
pload new -n data --version py1
pload new -n data --version uv-v3.12.8
pload new -n data --version py1:uv-v3.12.8
pload python path py1
```

Types include `sys`, `pyenv`, `uv`, `conda`, `mise`, `asdf`, `homebrew`, and
`other`. Compatibility names `system` and `managed` map to `sys` and `uv`.

Install a managed Python without pyenv:

```console
pload python install 3.12
pload python install 3.13.3
```

Managed runtimes are stored under the configured Python directory and do not
replace `/usr/bin/python`, Homebrew, pyenv, or Conda installations.

Runtime downloads and Python package downloads are configured separately:

- runtime source: `official`, `ustc`, or `custom`;
- pip source: `official`, `tsinghua`, `ustc`, `aliyun`, or `custom`.

The runtime source controls uv's `python-build-standalone` archives. A normal
PyPI mirror does not host those archives.

## Create and activate environments

Create a named environment with a description:

```console
pload new                     # guided creation
pload new -n data -v 3.12 -m "Data analysis"
pload new -n web -v 3.12 -r fastapi uvicorn -m "Web API"
pload new -v 3.12 --message "Temporary data tools"  # auto-named safely
pload list
pload v1
```

Create a project-local environment:

```console
pload init -m "Current project"
pload .
pload init -r pytest requests
```

Use an explicit interpreter or destination when needed:

```console
pload new -p /mnt/venvs/build -v /opt/python/bin/python
pload init -P /mnt/projects/app -e /mnt/venvs/app
```

Every managed environment receives an ID such as `v1`, `v2`, or `v3`, plus a
description and creation timestamp. Deleted IDs are reused from the first
available number. `pload list` displays environments newest-first:

![Environment list on macOS](docs/images/pload-list-macos.png)

The table includes ID, name, Python version, description, and full path. A
spinner is shown in interactive terminals; redirected and CI output uses stable
ordinary log lines.

## Help and aliases

Brief help is a complete reference. It starts with an emphasized `USAGE` panel,
then lists every positional argument, long option, short alias, and description:

```console
pload config -h
pload cfg -h
pload new -h
pload py install -h
pload py ls -h
pload-install -h
```

The root help keeps global storage options together, while command-specific
help shows only that command's arguments:

![Root help on macOS](docs/images/pload-help-macos.png)

Detailed help adds examples, expected output, disk effects, and failure behavior:

```console
pload -h -d
pload new -h -d
pload cfg -h -d
pload py ls -h -d
pload-install -h -d
```

Command aliases:

| Command | Alias |
| --- | --- |
| `new` | none; already short and explicit |
| `init` | `i` |
| `list` | `ls` |
| `rm` | `remove`, `del`, `delete` |
| `python` | `py` |
| `path` | `p` |
| `config` | `cfg` |
| `shell-init` | `shell` |

Python subcommands use `ls` and `p`; the explicit `install` command has no alias:

```console
pload py ls --filter uv,conda
pload python install 3.12
pload py p 3.12
```

## Isolation and directory layout

Put all pload-managed data under one root:

```console
export PLOAD_HOME=/mnt/workspace/.pload
pload new -n tools
```

The default layout is:

```text
PLOAD_HOME/
├── config.json       saved choices
├── runtime/          pload and uv private runtime
├── pythons/          downloaded Python runtimes
├── python-bin/       managed Python executable links
├── cache/python/     Python download cache
├── state/            environment IDs and Python runtime IDs
└── venvs/            managed virtual environments
```

Override individual roots with `PLOAD_VENVS_DIR`, `PLOAD_STATE_DIR`, or the
global `--home`, `--venvs-dir`, and `--state-dir` options. Project-local
environments can live elsewhere with `init --project-dir` and `--venv-dir`.

## Command reference

```console
pload new -h -d
pload init -h -d
pload list -h -d
pload rm -h -d
pload path -h -d
pload python -h -d
pload python install -h -d
pload python list -h -d
pload config -h -d
pload-install -h -d
```

Other useful commands:

```console
pload path v1
pload rm v1 --yes
pload rm --expression '^test-' --yes
pload cfg set source ustc
pload cfg -t
```

## Development

```console
python -m pip install -e '.[test]'
pytest
ruff check src tests
```

## License

Apache License 2.0. Copyright 2025 Yunming Hu.
