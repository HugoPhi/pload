# Changelog

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
