# pload

`pload` is a small Python virtual-environment manager for Bash, Zsh, Fish, and
PowerShell. It uses the standard library's `venv` module, works without pyenv,
and lets every file it owns live under a directory you choose.

> Version 0.4 is a compatibility-focused beta. The familiar `new`, `init`,
> `rm`, and `list` commands remain available, while installation no longer
> edits shell profile files automatically.

## Install

```console
python -m pip install pload
```

Enable activation in your shell by adding one line to its profile:

```bash
# Bash (~/.bashrc)
eval "$(python_virtual_env_load shell-init bash)"

# Zsh (~/.zshrc)
eval "$(python_virtual_env_load shell-init zsh)"

# Fish (~/.config/fish/config.fish)
python_virtual_env_load shell-init fish | source
```

For PowerShell, add this to `$PROFILE`:

```powershell
Invoke-Expression (& python_virtual_env_load shell-init powershell | Out-String)
```

This explicit setup keeps package installation side-effect free.

## Create and activate environments

```console
pload new --name data                 # current Python
pload new --name web --version 3.12   # pyenv or PATH Python
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

The resulting layout is:

```text
/mnt/workspace/.pload/
├── state/
└── venvs/
    └── tools/
```

Override roots independently with `PLOAD_VENVS_DIR` and `PLOAD_STATE_DIR`, or
use the global `--home`, `--venvs-dir`, and `--state-dir` options.

Existing 0.3 installations are detected automatically: if `~/venvs` contains
the old scripts, state file, or virtual environments and no new path is
configured, pload continues using it. Set `PLOAD_HOME` when you are ready to
move to the isolated layout.

Projects and virtual environments can be placed independently:

```console
pload init \
  --project-dir /mnt/projects/example \
  --venv-dir /mnt/environments/example
```

A relative `--venv-dir` is resolved relative to `--project-dir`:

```console
pload init --project-dir ./example --venv-dir .runtime/python
```

## Other commands

```console
pload list                       # managed environments
pload list --python-versions     # versions installed under PYENV_ROOT
pload path data                  # absolute environment path
pload rm data                    # confirm by typing its name
pload rm data --yes              # non-interactive removal
pload rm --expression '^test-'   # select managed environments with a regex
```

`PYENV_ROOT` and `PYENV_HOME` are respected. If pyenv is on `PATH`, `pload`
can ask it for an interpreter. Installing Python itself remains explicit.

## Development

```console
python -m pip install -e '.[test]'
pytest
```

## License

Apache License 2.0. Copyright 2025 Yunming Hu.
