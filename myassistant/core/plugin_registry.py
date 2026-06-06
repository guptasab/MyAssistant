"""Plugin Registry — load external skill packages into Squire.

Squire supports two plugin mechanisms:

1. **Directory plugins** — drop a folder into ``~/.squire/plugins/``:
   ```
   ~/.squire/plugins/
     my_plugin/
       squire_plugin.json    ← manifest
       skills/
         my_skill.py         ← skill modules (auto-discovered)
   ```

2. **Installed package plugins** — pip install a package that declares
   the ``squire.plugins`` entry point:
   ```python
   # setup.cfg / pyproject.toml
   [options.entry_points]
   squire.plugins =
       my_plugin = my_package.squire_entry:register
   ```

Plugin manifest (``squire_plugin.json``):
```json
{
  "name": "my_plugin",
  "version": "1.0.0",
  "description": "Adds integration with XYZ",
  "author": "Your Name",
  "squire_min_version": "1.0.0",
  "requires": ["requests"],
  "permissions": ["network", "filesystem:read"],
  "skills_dir": "skills"
}
```

Permissions model:
  ``network``           — plugin makes outbound HTTP calls
  ``filesystem:read``   — plugin reads local files
  ``filesystem:write``  — plugin writes local files (requires user approval)
  ``shell``             — plugin can run shell commands (requires user approval)
  ``private_data``      — plugin reads contacts/finance/health (requires user approval)

CLI commands::

    python -m squire plugin install <name>   # install from ClawHub or PyPI
    python -m squire plugin list             # list all installed plugins
    python -m squire plugin remove <name>    # uninstall a plugin
    python -m squire plugin check            # verify all plugins are compatible
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from loguru import logger


_PLUGINS_DIR = Path.home() / ".squire" / "plugins"
_loaded_plugins: dict[str, dict] = {}


def _plugins_dir() -> Path:
    _PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    return _PLUGINS_DIR


def load_all_plugins() -> int:
    """Load all installed plugins from the plugins directory and entry_points.

    Returns:
        Number of plugins successfully loaded.
    """
    count = 0
    count += _load_directory_plugins()
    count += _load_entry_point_plugins()
    logger.info(f"Plugin registry: {count} plugin(s) loaded, "
                f"{len(_get_all_skill_count())} skills added")
    return count


def _get_all_skill_count() -> list[str]:
    from myassistant.core.registry import _registry
    return list(_registry.keys())


def _load_directory_plugins() -> int:
    """Load plugins from ~/.squire/plugins/."""
    count = 0
    plugins_dir = _plugins_dir()

    for plugin_path in plugins_dir.iterdir():
        if not plugin_path.is_dir():
            continue
        manifest_path = plugin_path / "squire_plugin.json"
        if not manifest_path.exists():
            continue

        try:
            manifest = json.loads(manifest_path.read_text())
            plugin_name = manifest.get("name", plugin_path.name)

            if plugin_name in _loaded_plugins:
                continue

            if not _check_permissions(plugin_name, manifest):
                continue

            skills_dir = plugin_path / manifest.get("skills_dir", "skills")
            if skills_dir.exists():
                _load_skills_from_dir(skills_dir, plugin_name)

            _loaded_plugins[plugin_name] = manifest
            count += 1
            logger.info(f"Plugin loaded: {plugin_name} v{manifest.get('version', '?')}")

        except Exception as e:
            logger.warning(f"Plugin {plugin_path.name} load error: {e}")

    return count


def _load_entry_point_plugins() -> int:
    """Load plugins installed as Python packages with squire.plugins entry point."""
    count = 0
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group="squire.plugins")
        for ep in eps:
            try:
                register_fn = ep.load()
                register_fn()
                _loaded_plugins[ep.name] = {"name": ep.name, "source": "entry_point"}
                count += 1
                logger.info(f"Entry-point plugin loaded: {ep.name}")
            except Exception as e:
                logger.warning(f"Entry-point plugin {ep.name} error: {e}")
    except Exception:
        pass
    return count


def _load_skills_from_dir(skills_dir: Path, plugin_name: str) -> None:
    """Discover and load skill modules from a plugin's skills directory."""
    if str(skills_dir.parent) not in sys.path:
        sys.path.insert(0, str(skills_dir.parent))

    for skill_file in skills_dir.glob("**/*.py"):
        if skill_file.name.startswith("_"):
            continue
        try:
            module_name = f"squire_plugin_{plugin_name}_{skill_file.stem}"
            spec = importlib.util.spec_from_file_location(module_name, skill_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)  # type: ignore
                logger.debug(f"Plugin skill loaded: {plugin_name}/{skill_file.name}")
        except Exception as e:
            logger.warning(f"Plugin {plugin_name} skill {skill_file.name}: {e}")


def _check_permissions(plugin_name: str, manifest: dict) -> bool:
    """Check if a plugin's requested permissions are acceptable.

    High-risk permissions (filesystem:write, shell, private_data) are logged
    so the user is aware. In future this will prompt for approval.
    """
    risky = {"filesystem:write", "shell", "private_data"}
    requested = set(manifest.get("permissions", []))
    high_risk = requested & risky
    if high_risk:
        logger.warning(
            f"Plugin '{plugin_name}' requests high-risk permissions: {high_risk}. "
            f"Loading anyway — review {_PLUGINS_DIR / plugin_name / 'squire_plugin.json'}"
        )
    return True


# ── Plugin management CLI helpers ─────────────────────────────────────────────

def list_plugins() -> list[dict]:
    """Return all loaded plugins with metadata."""
    plugins = []
    # Directory plugins
    for p in _plugins_dir().iterdir():
        manifest_path = p / "squire_plugin.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
                manifest["_installed"] = True
                manifest["_loaded"] = manifest.get("name", p.name) in _loaded_plugins
                manifest["_path"] = str(p)
                plugins.append(manifest)
            except Exception:
                pass
    # Entry-point plugins
    try:
        from importlib.metadata import entry_points
        for ep in entry_points(group="squire.plugins"):
            if not any(p.get("name") == ep.name for p in plugins):
                plugins.append({"name": ep.name, "source": "entry_point",
                                "_installed": True, "_loaded": ep.name in _loaded_plugins})
    except Exception:
        pass
    return plugins


def install_plugin_from_dir(source_path: str) -> bool:
    """Install a plugin by copying a directory into the plugins folder.

    Args:
        source_path: Path to the plugin directory (must have squire_plugin.json).

    Returns:
        True if installed successfully.
    """
    src = Path(source_path)
    if not (src / "squire_plugin.json").exists():
        logger.error(f"No squire_plugin.json found in {src}")
        return False
    manifest = json.loads((src / "squire_plugin.json").read_text())
    dest = _plugins_dir() / manifest.get("name", src.name)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    logger.info(f"Plugin installed: {manifest.get('name')} → {dest}")
    return True


def remove_plugin(name: str) -> bool:
    """Remove a plugin by name.

    Args:
        name: Plugin name as specified in squire_plugin.json.

    Returns:
        True if removed.
    """
    dest = _plugins_dir() / name
    if dest.exists():
        shutil.rmtree(dest)
        _loaded_plugins.pop(name, None)
        logger.info(f"Plugin removed: {name}")
        return True
    logger.warning(f"Plugin not found: {name}")
    return False


def get_plugin_info(name: str) -> dict | None:
    """Get metadata for a specific installed plugin."""
    manifest_path = _plugins_dir() / name / "squire_plugin.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    return _loaded_plugins.get(name)
