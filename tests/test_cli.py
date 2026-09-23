from pload.cli import main, shell_script


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
        assert "python_virtual_env_load" in output


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
