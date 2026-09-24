# Changelog

## 0.8.2 - 2026-09-24

### Changed

- Add consistent short aliases for every long CLI option, including `new -n`.
- Keep already-clear commands spelled out: `new` and `python install` no longer
  accept command aliases.
- Update practical help examples and alias tables to match the command surface.

## 0.8.1 - 2026-09-24

### Changed

- Replace formal `-h -d` argument summaries with task-oriented guides that
  include copyable examples, expected output, on-disk effects, failure
  behavior, and safety notes for every command.
- Expand `pload-install -h -d` into a walkthrough of the numbered prompts,
  resulting directory layout, shell changes, and non-interactive setup.

## 0.8.0 - 2026-09-24

### Added

- Short command aliases including `ls`, `n`, `i`, `py`, `p`, and `cfg`.
- Compact, colored quick help with `-h` and full Rich-formatted help with
  `-h -d`, for both `pload` and `pload-install`.
- A terminal-aware spinner while virtual environments are being created.

### Changed

- Shell integration recognizes every short and long command alias.
- Spinner animations automatically fall back to stable log lines when output
  is redirected or running in CI.

## 0.7.0 - 2026-09-24

### Added

- Persistent monotonic IDs (`v1`, `v2`, ...) and descriptions for environments.
- Activation, path lookup, and removal by environment ID.
- Rich, colored tables for environment and Python-runtime listings.
- USTC and Alibaba Cloud PyPI presets alongside official PyPI and Tsinghua.
- Detailed, colored, numbered choices in the guided installer.

### Changed

- `pload list` now shows ID, name, Python version, description, and path.
- Existing managed environments are registered automatically on first use.

## 0.6.2 - 2026-09-24

### Fixed

- Make the selected package index override ambient pip index, extra-index, and
  no-index environment variables during private-runtime installation.
- Store the official PyPI URL explicitly when the official source is selected.

## 0.6.1 - 2026-09-24

### Fixed

- Report the version actually installed in the private runtime after an
  in-place upgrade, instead of the older installer process version.

## 0.6.0 - 2026-09-23

### Added

- Cross-platform Python discovery across the operating system, PATH, uv,
  pyenv, Conda, mise, asdf, Homebrew, and the Windows Python Launcher.
- Source and resolved executable columns in `pload python list`.
- `pload python list --filter TYPE...` with comma-separated, space-separated,
  and compatibility alias support.

### Changed

- Version-based environment creation can use any discovered interpreter, not
  only uv, pyenv, or a versioned command already on PATH.
- Requested minor versions are verified instead of falling back to an
  unrelated `python3` executable.

## 0.5.0 - 2026-09-23

### Added

- Guided `pload-install` setup for the data, executable, environment, Python,
  cache, package-index, and shell-integration locations.
- A private pload runtime plus stable `bin/pload` launcher that is independent
  from project virtual environments.
- uv-backed `pload python install`, `list`, and `path` commands.
- Official, USTC, custom HTTPS, local `file://`, and custom-download-metadata
  options for managed Python runtimes.
- Persistent `PLOAD_HOME/config.json` configuration and `pload config show`.
- Expanded top-level and command-specific help with practical examples.

### Changed

- uv-managed Python is preferred over pyenv when a requested version is
  available; pyenv remains a compatible fallback.
- Shell integration calls the stable `pload` launcher directly.

## 0.4.1 - 2026-09-23

### Fixed

- Automatically reuse a populated legacy `~/venvs` root when no explicit path
  is configured, so upgrading from 0.3 does not hide existing environments.

## 0.4.0 - 2026-09-23

### Added

- Fully relocatable data, environment, and state roots through CLI options and
  `PLOAD_HOME`, `PLOAD_VENVS_DIR`, and `PLOAD_STATE_DIR`.
- Independent `--project-dir` and `--venv-dir` options for local environments.
- Explicit-path environment creation and interpreter selection.
- Side-effect-free shell integration for Bash, Zsh, Fish, and PowerShell.
- Automated tests and multi-platform continuous integration.

### Changed

- pyenv is optional; the current interpreter is used when no version is given.
- Packaging uses `pyproject.toml` and builds both wheels and source archives.
- Package installation no longer edits shell profiles.
- Expected failures now return concise messages instead of Python tracebacks.

### Fixed

- Missing color method during dependency installation.
- Crashes when pyenv, state files, or environment directories do not exist.
- Hard-coded Homebrew and home-directory paths.
- Inconsistent project metadata and license declaration.
