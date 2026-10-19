"""Read-only, local completion shared by all supported shells.

The CLI parser supplies command/option structure. Dynamic candidates come from
registries and local directories; Tab never probes interpreters or repositories.
"""

import argparse
import json
import shlex
from pathlib import Path

from pload.managers.platform import ConfigManager
from pload.managers.pyversion import PythonManager

SHELLS = ("bash", "zsh", "fish", "powershell")
CONFIG_KEYS = (
    "home", "bin-dir", "venvs-dir", "state-dir", "python-dir", "source",
    "mirror-url", "downloads-json-url", "pip-source", "pip-index", "shell",
)
DIRECTORY_DESTS = {
    "home", "venvs_dir", "state_dir", "project_dir", "venv_dir", "path",
}


def _records(path, key):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data.get(key, []) if isinstance(data, dict) else []
        return [item for item in records if isinstance(item, dict)]
    except (OSError, ValueError, TypeError):
        return []


def _paths(prefix, directories=False, toml=False):
    typed = Path(prefix).expanduser()
    if prefix.startswith("~") and "/" not in prefix and "\\" not in prefix:
        return [(prefix + "/", "directory")] if typed.is_dir() else []
    directory = typed if prefix.endswith(("/", "\\")) else typed.parent
    stem = "" if prefix.endswith(("/", "\\")) else typed.name
    if not prefix:
        directory, stem = Path("."), ""
    # Keep the user's relative path or ~ rather than inserting absolute paths.
    head = prefix[:len(prefix) - len(stem)] if stem else prefix
    try:
        entries = sorted(directory.iterdir(), key=lambda item: item.name)
        return [
            (head + item.name + ("/" if item.is_dir() else ""),
             "directory" if item.is_dir() else "configuration file" if toml else "file")
            for item in entries
            if item.name.startswith(stem)
            and (not item.name.startswith(".") or stem.startswith("."))
            and (not directories or item.is_dir())
            and (not toml or item.is_dir() or item.suffix == ".toml")
        ]
    except OSError:
        return []


def _environments(config):
    result = [(".", "activate project .venv")]
    for item in _records(config.state_path / "environments.json", "environments"):
        path = Path(item.get("path", "")).expanduser()
        if not item.get("path") or path.is_symlink() or not (path / "pyvenv.cfg").is_file():
            continue
        description = item.get("description") or item.get("name") or str(path)
        result.extend((item[key], str(description)) for key in ("id", "name") if item.get(key))
    if config.venv_path.is_dir():
        for path in config.venv_path.iterdir():
            if not path.is_symlink() and (path / "pyvenv.cfg").is_file():
                result.append((path.name, "environment"))
    return result


def _pythons(config, install=False):
    result = [] if install else [("current", "current Python"), ("system", "current Python")]
    for item in _records(config.state_path / "python-runtimes.json", "runtimes"):
        if not item.get("path") or not Path(item["path"]).is_file():
            continue
        description = f"{item.get('source', 'Python')} {item.get('version', '')}"
        keys = ("version",) if install else ("id", "alias", "version")
        result.extend((item[key], description) for key in keys if item.get(key))
        version = str(item.get("version", ""))
        if version.count(".") >= 2:
            result.append((".".join(version.split(".")[:2]), "Python minor version"))
    return result


def _packages(config, environment):
    from packaging.utils import InvalidWheelFilename, parse_wheel_filename

    result = []
    for path in (config.home / "cache" / "wheels").glob("*.whl"):
        try:
            name, _, _, _ = parse_wheel_filename(path.name)
            result.append((str(name), "cached package"))
        except InvalidWheelFilename:
            continue
    # Inspect metadata directory names only; never import packages or run pip.
    if environment == ".":
        root = Path.cwd() / ".venv"
    else:
        record = next((item for item in _records(
            config.state_path / "environments.json", "environments"
        ) if environment in (item.get("id"), item.get("name"))), None)
        if record and record.get("path"):
            root = Path(record["path"]).expanduser()
        elif "/" in environment or "\\" in environment or Path(environment).is_absolute():
            root = Path(environment).expanduser()
        else:
            root = config.venv_path / environment
    if root.is_symlink() or not (root / "pyvenv.cfg").is_file():
        return result
    for pattern in ("lib/python*/site-packages/*.dist-info", "Lib/site-packages/*.dist-info"):
        for path in root.glob(pattern):
            name = path.name[:-len(".dist-info")].rsplit("-", 1)[0].replace("_", "-")
            result.append((name, "installed package"))
    return result


def _values(action, prefix, values, config):
    if action.dest == "sources":
        head, _, fragment = prefix.rpartition(",")
        used = set(head.split(",")) if head else set()
        return [(f"{head}," + value if head else value, "Python source type")
                for value in (*PythonManager.SOURCES, *PythonManager.SOURCE_ALIASES)
                if value not in used and value.startswith(fragment)]
    if action.choices:
        return [(str(value), action.help or "") for value in action.choices]
    dest = action.dest
    if dest == "python_version" or dest == "version":
        return _pythons(config, install=values.get("python_command") == "install") + (
            _paths(prefix) if "/" in prefix or prefix.startswith("~") else []
        )
    if dest in {"names", "envs", "environment"} or (
        dest == "name" and values.get("command") == "path"
    ):
        return _environments(config) + (_paths(prefix, directories=True) if prefix else [])
    if dest == "source":  # describe SOURCE
        return _environments(config) + _paths(prefix)
    if dest == "file":
        return _paths(prefix, toml=True)
    if dest in DIRECTORY_DESTS:
        return _paths(prefix, directories=True)
    if dest == "output":
        return _paths(prefix, toml=True)
    if dest == "location":
        return _paths(prefix, directories=True) if ":" not in prefix else []
    if dest == "repository" or (dest == "name" and values.get("repo_command") == "remove"):
        return [(name, "artifact repository") for name in config.settings.get("repositories", {})]
    if dest == "key" and values.get("action") == "set":
        return [(key, "configuration setting") for key in CONFIG_KEYS]
    if dest == "value" and values.get("action") == "set":
        key = values.get("key")
        choices = {
            "source": ("official", "ustc", "custom"),
            "pip-source": ("official", "tsinghua", "ustc", "aliyun", "custom"),
            "shell": SHELLS + ("none",),
        }
        if key in choices:
            return [(value, "configuration value") for value in choices[key]]
        if key in {"home", "bin-dir", "venvs-dir", "state-dir", "python-dir"}:
            return _paths(prefix, directories=True)
        if key == "downloads-json-url":
            return _paths(prefix)
    if dest in {"requirements", "package"}:
        return _packages(config, values.get("environment", "."))
    return []


def candidates(parser, words, index):
    """Return (value, description) pairs at a zero-based shell word index."""
    if index < 1 or index > len(words):
        return []
    prefix = words[index] if index < len(words) else ""
    values, overrides = {}, {}
    pending = None
    position = 0
    options_done = False
    for word in words[1:index]:
        option = parser._option_string_actions.get(word.split("=", 1)[0])
        if word == "--" and not options_done:
            options_done = True
            pending = None
            continue
        if pending is not None and (option is None or options_done):
            values[pending.dest] = word
            if pending.dest in {"home", "venvs_dir", "state_dir"}:
                overrides[pending.dest] = word
            if pending.nargs not in ("+", "*"):
                pending = None
            continue
        if option is not None and not options_done:
            pending = option if option.nargs != 0 else None
            if "=" in word and pending:
                value = word.split("=", 1)[1]
                values[pending.dest] = value
                if pending.dest in {"home", "venvs_dir", "state_dir"}:
                    overrides[pending.dest] = value
                pending = None
            continue
        positional = [action for action in parser._actions if not action.option_strings]
        if position >= len(positional):
            continue
        action = positional[position]
        if isinstance(action, argparse._SubParsersAction):
            if word in action.choices:
                values[action.dest] = word
                parser = action.choices[word]
                position = 0
        else:
            values[action.dest] = word
            if action.nargs not in ("+", "*"):
                position += 1

    # Share the CLI's canonical names, including all short command aliases.
    from pload.cli import COMMAND_NAMES, PYTHON_COMMAND_NAMES

    values["command"] = COMMAND_NAMES.get(values.get("command"), values.get("command"))
    values["python_command"] = PYTHON_COMMAND_NAMES.get(
        values.get("python_command"), values.get("python_command")
    )
    config = ConfigManager(**overrides)
    attached = ""
    if "=" in prefix and prefix.startswith("--"):
        name, value = prefix.split("=", 1)
        option = parser._option_string_actions.get(name)
        if option and option.nargs != 0:
            pending, attached, prefix = option, name + "=", value

    if pending is not None and (not prefix.startswith("-") or attached):
        result = _values(pending, prefix, values, config)
    elif prefix.startswith("-") and not options_done:
        result = [(flag, action.help or "")
                  for flag, action in parser._option_string_actions.items()]
        if "-h" in words[:index] or "--help" in words[:index]:
            result += [("-d", "detailed help with examples"),
                       ("--detailed", "detailed help with examples")]
    else:
        positional = [action for action in parser._actions if not action.option_strings]
        action = positional[position] if position < len(positional) else None
        if isinstance(action, argparse._SubParsersAction):
            result = [(name, subparser.description or name)
                      for name, subparser in action.choices.items()]
            if action.dest == "command" and index == 1:
                result += _environments(config)
                if "/" in prefix or "\\" in prefix or prefix.startswith("~"):
                    result += _paths(prefix, directories=True)
        elif action:
            result = _values(action, prefix, values, config)
        else:
            result = []
        if not prefix and not options_done:
            result += [(flag, action.help or "")
                       for flag, action in parser._option_string_actions.items()]
    unique = {}
    for value, description in result:
        if not isinstance(value, str) or not value.startswith(prefix):
            continue
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            continue
        unique[attached + value] = " ".join(str(description).split())[:180]
    return list(unique.items())


def emit(parser, argv):
    """Internal protocol: index, words (including pload); TSV suggestions only."""
    try:
        unquote = bool(argv and argv[0] == "--unquote")
        if unquote:
            argv = argv[1:]
        index = int(argv[0])
        words = [_unquote(word) for word in argv[1:]] if unquote else argv[1:]
        for value, description in candidates(parser, words, index):
            print(value + "\t" + description)
    except (OSError, ValueError, TypeError, IndexError):
        return 0
    return 0


def _unquote(word):
    # COMP_WORDS may contain shell quoting. Parse it as data, never with eval.
    # A token at the cursor can have an opening quote without its closing one.
    for ending in ("", '"', "'"):
        try:
            parsed = shlex.split(word + ending, comments=False)
            if len(parsed) == 1:
                return parsed[0]
        except ValueError:
            continue
    return word


def shell_completion(shell):
    if shell == "bash":
        return r'''
_pload_complete() {
    local value description part fragment trim logical i last trim_length
    local -a tokens
    tokens=()
    # Bash versions differ in how COMP_WORDS splits = and :. Readline replaces
    # only the fragment after these separators, so normalize and trim locally.
    for ((i=0; i<=COMP_CWORD; i++)); do
        part=${COMP_WORDS[i]}
        last=$((${#tokens[@]} - 1))
        if ((last >= 0)) && { [[ "$part" == '=' || "$part" == ':' ]] ||
                [[ "${tokens[last]}" == *= || "${tokens[last]}" == *: ]]; }; then
            tokens[last]+=$part
        else
            tokens+=("$part")
        fi
    done
    last=$((${#tokens[@]} - 1))
    logical=${tokens[last]}
    fragment=${COMP_WORDS[COMP_CWORD]}
    [[ "$COMP_WORDBREAKS" == *'='* ]] && fragment=${fragment##*=}
    [[ "$COMP_WORDBREAKS" == *':'* ]] && fragment=${fragment##*:}
    trim_length=$((${#logical} - ${#fragment}))
    trim=${logical:0:trim_length}
    COMPREPLY=()
    while IFS=$'\t' read -r value description; do
        value=${value#"$trim"}
        COMPREPLY+=("$value")
    done < <(command pload __complete --unquote "$last" "${tokens[@]}" 2>/dev/null)
}
complete -o filenames -F _pload_complete pload
'''
    if shell == "zsh":
        return r'''
_pload_complete() {
    local value description
    local -a candidates descriptions directories
    while IFS=$'\t' read -r value description; do
        if [[ "$value" == */ ]]; then
            directories+=("$value")
        else
            candidates+=("$value")
            descriptions+=("$value -- $description")
        fi
    done < <(command pload __complete --unquote "$((CURRENT - 1))" "${words[@]}" 2>/dev/null)
    (( ${#directories} )) && compadd -S '' -- "${directories[@]}"
    (( ${#candidates} )) && compadd -d descriptions -- "${candidates[@]}"
    return 0
}
if ! (( $+functions[compdef] )); then
    autoload -Uz compinit
    compinit -i
fi
compdef _pload_complete pload
'''
    if shell == "fish":
        return r'''
function __pload_complete
    set -l tokens (commandline -opc)
    set -l current (commandline -ct)
    set -l unescaped (string unescape -- "$current" 2>/dev/null)
    if test $status -eq 0
        set current "$unescaped"
    else if string match -qr "^[\"']" -- "$current"
        set current (string sub -s 2 -- "$current")
    end
    command pload __complete (count $tokens) $tokens "$current" 2>/dev/null
end
complete -c pload -e
complete -c pload -f -a '(__pload_complete)'
'''
    return r'''
function __pload_completion_results {
    param($wordToComplete, $commandAst, $cursorPosition)
    if (-not $cursorPosition) { $cursorPosition = $commandAst.Extent.EndOffset }
    $words = @($commandAst.CommandElements | Where-Object {
        $_.Extent.StartOffset -lt $cursorPosition
    } | ForEach-Object {
        if ($_ -is [System.Management.Automation.Language.StringConstantExpressionAst]) {
            $_.Value
        } else { $_.Extent.Text }
    })
    $index = $words.Count
    if ($wordToComplete) {
        $index--
        $words[$index] = $wordToComplete
    }
    $backend = Get-Command -Name pload -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $backend) { return }
    & $backend.Source __complete $index @words 2>$null | ForEach-Object {
        $parts = $_ -split "`t", 2
        $value = $parts[0]
        $text = $value
        if ($value -match '[^a-zA-Z0-9_./:\\-]') { $text = "'" + $value.Replace("'", "''") + "'" }
        [System.Management.Automation.CompletionResult]::new(
            $text, $value, 'ParameterValue', $parts[1])
    }
}
Register-ArgumentCompleter -CommandName pload -ParameterName PloadArgs -ScriptBlock {
    param($commandName, $parameterName, $wordToComplete, $commandAst, $fakeBoundParameters)
    __pload_completion_results $wordToComplete $commandAst 0
}
Register-ArgumentCompleter -Native -CommandName pload -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    __pload_completion_results $wordToComplete $commandAst $cursorPosition
}
'''
