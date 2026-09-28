import subprocess
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename
from questionary import Choice

from pload import ui
from pload.errors import PloadError
from pload.managers.platform import ConfigManager


def _compatible_tags(venv_path):
    """Describe the target runtime, rather than the Python running pload."""
    from pload.declarative import _target_wheel_tags
    from pload.snapshots import probe

    return _target_wheel_tags(probe(ConfigManager.venv_python(venv_path)))


class DependencyManager:
    def __init__(self, config):
        self.config = config

    def install_dependencies(self, venv_path, requirements, channel=None, strategy="auto"):
        if not requirements:
            return
        if strategy not in {"auto", "custom"}:
            raise PloadError(f"unknown package strategy: {strategy}")

        wheel_cache = self.config.home / "cache" / "wheels"
        supported_tags = _compatible_tags(venv_path) if wheel_cache.is_dir() else set()
        index = channel or self.config.settings.get("pip_index")
        failures = []
        installed = []

        for value in requirements:
            try:
                requirement = Requirement(value)
            except InvalidRequirement:
                ui.warning(f"Skipping invalid package requirement: {value}")
                failures.append((value, "invalid requirement"))
                continue

            routes = self._routes(requirement, wheel_cache, supported_tags, index)
            selected = routes[0]
            if strategy == "custom" and len(routes) > 1:
                selected = ui.select(
                    f"Source for {value}",
                    [Choice(route["label"], value=route) for route in routes],
                    default=routes[0],
                )

            ui.info(f"Installing {value} from {selected['summary']}")
            command = self.config.get_pip_command(venv_path) + ["install"]
            if selected["kind"] == "cache":
                command.append(str(selected["path"]))
                command += ["--find-links", str(wheel_cache)]
            else:
                command.append(value)
            if index:
                command += ["--index-url", index]
            try:
                process = subprocess.run(command, check=False)
            except OSError as exc:
                failures.append((value, str(exc)))
                ui.warning(f"Could not install {value}; continuing with the next package")
                continue
            if process.returncode != 0:
                failures.append((value, f"{selected['summary']} failed"))
                ui.warning(f"Could not install {value}; continuing with the next package")
                continue
            installed.append(value)

        if installed:
            ui.success(
                f"Installed {len(installed)} requested package"
                f"{'s' if len(installed) != 1 else ''}",
                detail=", ".join(installed),
            )
        if failures:
            details = "; ".join(f"{name} ({reason})" for name, reason in failures)
            raise PloadError(
                "some packages were not installed; successful packages were kept: " + details
            )

    @staticmethod
    def _routes(requirement, wheel_cache, supported_tags, index):
        matches = []
        # Installing a wheel path would discard URL, marker, or extras semantics.
        # Let pip interpret those requirement forms from the configured index.
        if (wheel_cache.is_dir() and not requirement.url
                and not requirement.marker and not requirement.extras):
            for wheel in wheel_cache.glob("*.whl"):
                try:
                    name, version, _, tags = parse_wheel_filename(wheel.name)
                except InvalidWheelFilename:
                    continue
                if canonicalize_name(name) != canonicalize_name(requirement.name):
                    continue
                if requirement.specifier and not requirement.specifier.contains(
                    version, prereleases=True,
                ):
                    continue
                if not tags.intersection(supported_tags):
                    continue
                matches.append((version, wheel))
        matches.sort(key=lambda item: (item[0], item[1].name), reverse=True)

        routes = [
            {
                "kind": "cache",
                "path": Path(wheel),
                "summary": f"pload cache ({wheel.name})",
                "label": f"Cache     {wheel.name}",
            }
            for _, wheel in matches
        ]
        location = index or "pip/default index"
        routes.append({
            "kind": "index",
            "summary": f"package index ({location})",
            "label": f"Index     {location}",
        })
        return routes
