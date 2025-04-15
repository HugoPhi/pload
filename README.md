# pload

A Minimalist Python Virtual Environment Management Tool, support: 

- powershell
- bash
- zsh
- fishshell
- cmd(TODO)

> [!WARNING]
> This is project is under development yet. You can try it carefully if you are interested in it.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![PyPI Version](https://img.shields.io/pypi/v/pload?color=blue)](https://pypi.org/project/pload/)

## Overview

pload is a command-line utility designed for efficient management of Python virtual environments. It supports both global environment management and local project-specific environments, with regex pattern matching and pyenv integration capabilities.

## Installation

### Installation from sdist(wheel not support.)
```bash
pip install --no-binary :all: pload
```

### Shell Autocompletion (Optional)
> [!NOTE]
> TODO: Manually add complete file for pload.


## Command Reference

### Core Operations

#### 1. Create Global Environment
```bash
pload new --version <python_version> [--message <description>] [--channel <pip_channel>] [--requirements <packages>...]
```
**Example:**
```bash
pload new -v 3.8.10 -m data_analysis -r numpy pandas
# Creates: 3.8.10-data_analysis
```

> [!NOTE]
> TODO: Support pload.toml to manage all packages, env & ...

#### 2. Initialize Local Environment
```bash
pload init --version <python_version> [--channel <pip_channel>] [--requirements <packages>...]
```
**Example:**
```bash
pload init -v 3.9.5  # Creates .venv in current directory
```

#### 3. Environment Management
```bash
# Remove environments
pload rm --envs <env_names>...  # Explicit names
pload rm --expression <regex>   # Pattern matching

# List environments
pload list [--expression <regex>] [--version]
```
> [!WARNING]
> Because of the inner parameter parser for powershell, you should use '--v' for short of '--version'. For example: 
> 
> ```bash
> pload list --v
> ```
> And short for `--envs` is also replaced by `-n` due to this.  

#### 4. Environment Activation
```bash
pload <global_env_name>  # Activate global environment
pload .                 # Activate local .venv
```

> [!NOTE]
> This part is completed by scripts under '$home/venvs/scripts'.

### Advanced Operations

#### Environment Copy (Work in Progress)
```bash
pload cp --from <source_env> --to <target_env>
```

## Feature Details

### Global Environment Management
- Stores environments in `~/.pload/venvs`
- Automatic version-message naming convention
- Supports batch operations using regular expressions

### Local Environment Integration
- Creates `.venv` directories in project folders
- Compatible with existing virtual environments

### Python Version Management
- Requires pyenv for version control
- Lists available Python versions via `pload list --version`

## License

> Apache License 2.0, Copyright 2025 Yunming Hu.
