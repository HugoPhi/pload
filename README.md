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

The installer asks for:

- the pload data directory;
- the stable executable `bin` directory;
- the managed virtual-environment directory;
- the downloaded Python directory;
- the Python runtime download source;
- the Python package index;
- whether to update a shell profile.

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
pload python path 3.12
pload new --name data --version 3.12
```

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
pload new --name data                 # private-runtime Python
pload new --name web --version 3.12   # managed, PATH, or pyenv Python
pload data                            # activate

pload init                            # create .venv here
pload .                               # activate it
pload init -r pytest requests         # install packages too
```

`--version` also accepts an exact interpreter path.

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
pload new -h
pload init -h
pload python -h
pload-install -h
```

Other useful commands:

```console
pload list
pload path data
pload rm data
pload rm data --yes
pload rm --expression '^test-'
pload config show
```

## Development

```console
python -m pip install -e '.[test]'
pytest
ruff check src tests
```

## License

Apache License 2.0. Copyright 2025 Yunming Hu.
