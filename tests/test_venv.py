import json

from pload.managers.platform import ConfigManager
from pload.managers.venv import VenvManager


def make_environment(path, version="3.12.8"):
    path.mkdir(parents=True)
    (path / "pyvenv.cfg").write_text(f"version = {version}\n", encoding="utf-8")
    return path


def test_legacy_environments_receive_stable_ids(tmp_path):
    root = tmp_path / "environments"
    make_environment(root / "alpha")
    make_environment(root / "beta", "3.11.9")
    manager = VenvManager(ConfigManager(
        home=tmp_path / "home",
        venvs_dir=root,
        state_dir=tmp_path / "state",
    ))

    first = manager.environments()
    second = manager.environments()

    assert [(item["id"], item["name"]) for item in first] == [
        ("v1", "alpha"),
        ("v2", "beta"),
    ]
    assert first == second
    assert first[1]["python"] == "3.11.9"


def test_environment_ids_are_not_reused_after_removal(tmp_path):
    root = tmp_path / "environments"
    first_path = make_environment(root / "first")
    second_path = make_environment(root / "second")
    manager = VenvManager(ConfigManager(home=tmp_path / "home", venvs_dir=root))
    first = manager.register_environment(first_path)
    second = manager.register_environment(second_path)

    manager.remove_venv(first["id"])
    third_path = make_environment(root / "third")
    third = manager.register_environment(third_path)

    assert second["id"] == "v2"
    assert third["id"] == "v3"
    registry = json.loads(manager.registry_path.read_text(encoding="utf-8"))
    assert registry["next_id"] == 4


def test_description_is_preserved_when_legacy_scan_runs(tmp_path):
    root = tmp_path / "environments"
    environment = make_environment(root / "service")
    manager = VenvManager(ConfigManager(home=tmp_path / "home", venvs_dir=root))
    manager.register_environment(environment, description="Backend service")

    assert manager.environments()[0]["description"] == "Backend service"
