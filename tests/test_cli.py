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


def test_remove_refuses_environment_symlink(tmp_path, capsys):
    target = tmp_path / "target"
    target.mkdir()
    (target / "pyvenv.cfg").touch()
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "linked").symlink_to(target, target_is_directory=True)

    result = main([
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
