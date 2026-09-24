# pload

`pload` is a relocatable Python runtime and virtual-environment manager for
Bash, Zsh, Fish, and PowerShell. The tool, downloaded Python runtimes, managed
environments, state, and caches can all be placed in user-selected directories.

pyenv is supported for compatibility, but is not required.

## Recommended installation

Install the small bootstrap package with pip, then run the guided installer:

```console
python -m pip install --user --upgrade pload
python -m pload.installer
```

Using the Tsinghua PyPI mirror for the bootstrap package:

```console
python -m pip install --user --upgrade pload \
  -i https://pypi.tuna.tsinghua.edu.cn/simple
python -m pload.installer --pip-source tsinghua
```

On Windows, `py` can replace `python`:

```powershell
py -m pip install --user --upgrade pload
py -m pload.installer
```

The guided installer explains every directory, then presents colored, numbered
menus for source and shell choices. Press Enter to accept the marked default.
It asks for:

- the pload data directory;
- the stable executable `bin` directory;
- the managed virtual-environment directory;
- the downloaded Python directory;
- the Python runtime download source;
- the Python package index;
- whether to update a shell profile.

Built-in package-index presets are:

1. `official` — `https://pypi.org/simple`
2. `tsinghua` — `https://pypi.tuna.tsinghua.edu.cn/simple`
3. `ustc` — `https://mirrors.ustc.edu.cn/pypi/simple`
4. `aliyun` — `https://mirrors.aliyun.com/pypi/simple`
5. `custom` — any compatible private or public index

The Python-runtime source is selected separately because an ordinary PyPI
mirror cannot host uv's `python-build-standalone` runtime archives.

It then creates a private runtime under `PLOAD_HOME/runtime` and writes a stable
`pload` executable into the selected `bin` directory. The executable does not
depend on a project virtual environment, so deleting or activating an
environment managed by pload cannot remove or shadow the tool itself.

For a fully non-interactive installation:

```console
python -m pload.installer --yes \
  --home /mnt/tools/pload \
  --bin-dir ~/.local/bin \
  --venvs-dir /mnt/venvs \
  --python-dir /mnt/python \
  --source ustc \
  --pip-source tsinghua
```

`--yes` never edits a shell profile unless `--shell` is also supplied.

If `pipx` is already available, `pipx install pload` is the shortest isolated
installation. Run `pload-install` afterward only when you want the guided
directory and Python-source configuration.

## Shell activation

The guided installer can add the initialization block. To configure it
manually:

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

## Python versions without pyenv

pload uses `uv` as its default managed-Python backend. The guided installer
places uv in pload's private runtime, while Python installations and caches go
to the configured pload directories.

```console
pload python install 3.12
pload python list
pload python list --filter uv,conda
pload python path 3.12
pload new --name data --version 3.12
```

`pload python list` discovers usable Python 3 interpreters from the operating
system, PATH, uv, pyenv, Conda, mise, asdf, Homebrew, and the Windows Python
Launcher. Results are deduplicated by resolved executable path:

```text
VERSION  TYPE      PATH
-------  --------  ----
3.9.6    sys       /usr/bin/python3
3.11.10  conda     /opt/miniconda3/envs/data/bin/python
3.12.8   uv        /data/pload/pythons/cpython-3.12.8/bin/python3.12
3.13.3   homebrew  /opt/homebrew/Cellar/python@3.13/.../python3.13
```

Filter one or more source types with commas or spaces:

```console
pload python list --filter uv,conda
pload python list --filter uv conda
```

Available types are `sys`, `pyenv`, `uv`, `conda`, `mise`, `asdf`,
`homebrew`, and `other`. The compatibility aliases `system` and `managed`
map to `sys` and `uv` respectively.

Python itself does not publish one portable binary distribution covering all
supported platforms. uv therefore uses the CPython builds from Astral's
`python-build-standalone` project.

Available runtime source choices:

- `official`: Astral's GitHub releases;
- `ustc`: the documented USTC GitHub-release mirror;
- `custom`: any compatible HTTPS mirror or local `file://` mirror.

Examples:

```console
# USTC runtime mirror
python -m pload.installer --yes --no-runtime-install --source ustc

# Private mirror with uv-compatible directory layout
python -m pload.installer --yes --no-runtime-install \
  --source custom \
  --mirror-url https://mirror.example/python-build-standalone/releases/download

# Fully custom uv download metadata
python -m pload.installer --yes --no-runtime-install \
  --source custom \
  --mirror-url file:///mnt/mirror \
  --downloads-json-url /mnt/mirror/python-downloads.json
```

Mirror configuration is stored in `PLOAD_HOME/config.json` and applied only to
pload operations. It does not need to be exported globally from a shell
profile. Use `pload config show` to inspect the effective configuration.

Third-party mirrors are availability and trust choices made by the user. pload
does not disable uv's normal archive metadata and integrity handling.

## Create and activate environments

```console
pload new --name data --description "Data analysis"
pload new --name web --version 3.12 -d "Web development"
pload list
pload v1                              # activate by stable ID
pload data                            # names continue to work

pload init -d "Current project"       # create and register .venv here
pload .                               # activate it
pload init -r pytest requests         # install packages too
```

Every environment created by pload receives a monotonic ID such as `v1`, `v2`,
or `v3`. IDs are not reused after removal. Existing environments under the
managed root are assigned IDs automatically the first time they are listed.
The ID registry is stored under the configurable state directory, so it remains
inside the user's isolated pload layout.

`pload list` uses a Rich table and shows ID, name, Python version, description,
and full path. Color is enabled on terminals and can be disabled with the
standard `NO_COLOR` environment variable. `--version` also accepts an exact
interpreter path.

Environment creation displays a lightweight spinner in an interactive terminal.
When output is redirected, or when running in CI, pload automatically emits
ordinary stable log lines instead.

## Short aliases and help

Common commands have concise aliases:

| Full command | Aliases |
| --- | --- |
| `pload new` | — |
| `pload init` | `pload i` |
| `pload list` | `pload ls` |
| `pload rm` | `pload remove`, `pload del`, `pload delete` |
| `pload python` | `pload py` |
| `pload path` | `pload p` |
| `pload config` | `pload cfg` |
| `pload shell-init` | `pload shell` |

Python subcommands also accept `ls` and `p`; the explicit `install` command has
no alias because it is already short and unambiguous:

```console
pload py ls --filter uv,conda
pload python install 3.12
pload py p 3.12
```

Help has two levels:

```console
pload -h                 # compact colored command guide
pload -h -d              # practical walkthrough with examples and effects
pload new -h             # compact command help
pload new -h -d          # creation examples, output, side effects, and failures
pload py ls -h -d        # discovery examples and what the scan changes
pload-install -h         # compact installer guide
pload-install -h -d      # guided prompts, resulting layout, and shell changes
```

Every brief `-h` view lists all positional arguments and all options with their
short and long spellings. The `-d` form keeps that reference and adds practical
examples, expected output, side effects, and failure behavior.

Environment IDs are stable while an environment exists, and deleted IDs are
reused from the first available number. `pload list` displays environments
newest-first by creation time so the most recently created entry is always at
the top.

Every long option has a short spelling shown in help, for example
`pload new -n data -v 3.12 -d "Data analysis"`. The `-d` option remains the
description shorthand for `new` and `init` when `-h` is not present.
Detailed help is intentionally task-oriented: the related-options table appears
only after copyable commands, expected output, explanations, and on-disk effects.

## Directory isolation

Put all pload-managed data under one root:

```console
export PLOAD_HOME=/mnt/workspace/.pload
pload new --name tools
```

The guided layout is:

```text
PLOAD_HOME/
├── config.json
├── runtime/       # pload and uv only
├── pythons/       # downloaded Python runtimes
├── python-bin/    # links to managed Python executables
├── cache/python/
├── state/
└── venvs/
```

Override roots with `PLOAD_VENVS_DIR` and `PLOAD_STATE_DIR`, or the global
`--home`, `--venvs-dir`, and `--state-dir` options.

Projects and virtual environments can be placed independently:

```console
pload init \
  --project-dir /mnt/projects/example \
  --venv-dir /mnt/environments/example
```

Existing 0.3 installations are detected automatically when a populated
`~/venvs` is present and no explicit path has been configured.

## Discover commands

```console
pload -h
pload new -h -d
pload init -h -d
pload python -h -d
pload-install -h -d
```

Other useful commands:

```console
pload list
pload path v1
pload path data
pload rm v1 --yes
pload rm data
pload rm data --yes
pload rm --expression '^test-'
pload config show
pload cfg set source ustc
pload cfg set pip-source tsinghua
pload cfg set venvs-dir ~/venvs
pload cfg -t
```

`pload cfg set` changes one setting without reinstalling pload or uv. `pload
cfg -t` reopens the colored setup wizard, reuses the current values as
defaults, and updates only configuration plus the selected shell profile.

## Development

```console
python -m pip install -e '.[test]'
pytest
ruff check src tests
```

## License

Apache License 2.0. Copyright 2025 Yunming Hu.
