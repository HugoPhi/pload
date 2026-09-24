from pload.cli import build_parser, main, shell_script


def test_init_can_place_project_and_environment_independently(tmp_path):
    project = tmp_path / "project"
    environment = tmp_path / "isolated" / "python"

    result = main([
        "--home", str(tmp_path / "pload-data"),
        "init",
        "--project-dir", str(project),
        "--venv-dir", str(environment),
    ])

    assert result == 0
    assert project.is_dir()
    assert (environment / "pyvenv.cfg").is_file()


def test_path_prints_activation_script(tmp_path, capsys):
    environment = tmp_path / "environments" / "demo"
    environment.mkdir(parents=True)
    (environment / "pyvenv.cfg").write_text("home = test\n", encoding="utf-8")
    activate = environment / "bin" / "activate"
    activate.parent.mkdir()
    activate.touch()

    result = main([
        "--state-dir", str(tmp_path / "state"),
        "--venvs-dir", str(tmp_path / "environments"),
        "path", "demo", "--shell", "bash",
    ])

    assert result == 0
    assert capsys.readouterr().out.strip() == str(activate)


def test_shell_init_supports_all_documented_shells():
    for shell in ("bash", "zsh", "fish", "powershell"):
        output = shell_script(shell)
        assert "function" in output or "pload()" in output
        assert "pload" in output


def test_shell_init_recognizes_short_command_aliases():
    for shell in ("bash", "zsh", "fish", "powershell"):
        output = shell_script(shell)
        for alias in ("ls", "n", "i", "py", "p", "cfg"):
            assert alias in output


def test_remove_refuses_environment_symlink(tmp_path, capsys):
    target = tmp_path / "target"
    target.mkdir()
    (target / "pyvenv.cfg").touch()
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "linked").symlink_to(target, target_is_directory=True)

    result = main([
        "--state-dir", str(tmp_path / "state"),
        "--venvs-dir", str(managed), "rm", "linked", "--yes",
    ])

    assert result == 1
    assert target.is_dir()
    assert "symlink" in capsys.readouterr().err


def test_help_describes_python_and_isolation_workflows(capsys):
    parser = build_parser()
    parser.print_help()
    output = capsys.readouterr().out

    assert "pload python install 3.12" in output
    assert "PLOAD_HOME" in output
    assert "--project-dir" in output


def test_python_list_filter_accepts_comma_or_space_separated_types():
    parser = build_parser()

    comma = parser.parse_args(["python", "list", "--filter", "uv,conda"])
    spaces = parser.parse_args(["python", "list", "--filter", "uv", "conda"])

    assert comma.sources == ["uv,conda"]
    assert spaces.sources == ["uv", "conda"]


def test_short_command_aliases_parse_to_supported_commands():
    parser = build_parser()

    assert parser.parse_args(["ls"]).command == "ls"
    assert parser.parse_args(["n", "--name", "demo"]).command == "n"
    assert parser.parse_args(["py", "ls"]).python_command == "ls"
    assert parser.parse_args(["cfg"]).command == "cfg"


def test_description_short_option_does_not_conflict_with_detailed_help():
    args = build_parser().parse_args(["new", "-d", "Data tools"])

    assert args.description == "Data tools"


def test_brief_and_detailed_help_are_distinct(capsys):
    assert main(["-h"]) == 0
    brief = capsys.readouterr().out

    assert "Quick start" in brief
    assert "Detailed help: pload -h -d" in brief
    assert "Isolation:" not in brief

    assert main(["-h", "-d"]) == 0
    detailed = capsys.readouterr().out

    assert "A practical pload walkthrough" in detailed
    assert "$ pload n --name data" in detailed
    assert "What changes on disk" in detailed
    assert "PLOAD_HOME/runtime" in detailed
    assert "Related options" in detailed


def test_command_specific_detailed_help_uses_d_flag(capsys):
    assert main(["new", "-h"]) == 0
    brief = capsys.readouterr().out
    assert "Key options" in brief
    assert "pload new -h -d" in brief

    assert main(["new", "-h", "-d"]) == 0
    detailed = capsys.readouterr().out
    assert "Typical example" in detailed
    assert "$ pload n --name web" in detailed
    assert "Assigned v3" in detailed
    assert "Effects and failure behavior" in detailed
    assert "incomplete directory is removed" in detailed


def test_detailed_help_explains_command_effects(capsys):
    expectations = [
        (["list", "-h", "-d"], "Listing never deletes", "legacy environments"),
        (["rm", "-h", "-d"], "Safety effects", "Refuses to delete"),
        (["py", "i", "-h", "-d"], "Does not modify /usr/bin", "runtime source"),
        (["py", "ls", "-h", "-d"], "Discovery probes", "does not install"),
        (["cfg", "-h", "-d"], "read-only", "where a new environment"),
    ]

    for argv, explanation, effect in expectations:
        assert main(argv) == 0
        output = capsys.readouterr().out
        normalized = " ".join(output.split())
        assert explanation in normalized
        assert effect in normalized


def test_help_finds_command_after_global_path_option(tmp_path, capsys):
    assert main(["--home", str(tmp_path / "home"), "ls", "-h"]) == 0

    output = capsys.readouterr().out
    assert "pload ls" in output
    assert "--expression" in output


def test_list_alias_runs_against_isolated_state(tmp_path, capsys):
    result = main([
        "--home", str(tmp_path / "home"),
        "--venvs-dir", str(tmp_path / "environments"),
        "--state-dir", str(tmp_path / "state"),
        "ls",
    ])

    assert result == 0
    assert "DESCRIPTION" in capsys.readouterr().out


def test_list_assigns_id_and_shows_description(tmp_path, capsys):
    home = tmp_path / "home"
    environment = tmp_path / "environments" / "data"
    environment.mkdir(parents=True)
    (environment / "pyvenv.cfg").write_text("version = 3.12.8\n", encoding="utf-8")

    from pload.managers.platform import ConfigManager
    from pload.managers.venv import VenvManager

    manager = VenvManager(ConfigManager(home=home, venvs_dir=environment.parent))
    manager.register_environment(environment, name="data", description="Data analysis")

    result = main([
        "--home", str(home),
        "--venvs-dir", str(environment.parent),
        "list",
    ])

    output = capsys.readouterr().out
    assert result == 0
    assert "v1" in output
    assert "data" in output
    assert "3.12.8" in output
    assert "Data analysis" in output


def test_path_resolves_environment_id(tmp_path, capsys):
    home = tmp_path / "home"
    environment = tmp_path / "environments" / "demo"
    environment.mkdir(parents=True)
    (environment / "pyvenv.cfg").touch()

    from pload.managers.platform import ConfigManager
    from pload.managers.venv import VenvManager

    manager = VenvManager(ConfigManager(home=home, venvs_dir=environment.parent))
    entry = manager.register_environment(environment, name="demo")

    result = main([
        "--home", str(home),
        "--venvs-dir", str(environment.parent),
        "path", entry["id"],
    ])

    assert result == 0
    assert capsys.readouterr().out.strip() == str(environment.resolve())
