"""Skill registry — decorator-based plugin system.

A "skill" is just a Python function decorated with @skill. The registry
introspects its signature/docstring into a Claude tool-use schema and exposes
it to the agent. Drop new skills in ram/skills/ and they're auto-discovered.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import typing as t
from dataclasses import dataclass, field

from loguru import logger


@dataclass
class Skill:
    name: str
    description: str
    func: t.Callable
    parameters: dict
    requires: list[str] = field(default_factory=list)  # env var names required
    sensitive: bool = False  # if True, agent must confirm with user before invoking

    def to_anthropic_tool(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


_REGISTRY: dict[str, Skill] = {}


_PY_TO_JSON = {
    str: "string", int: "integer", float: "number", bool: "boolean",
    list: "array", dict: "object",
}


def _build_schema(func: t.Callable) -> dict:
    sig = inspect.signature(func)
    props: dict[str, dict] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if pname in ("self", "cls", "ctx"):
            continue
        ann = param.annotation if param.annotation is not inspect._empty else str
        origin = t.get_origin(ann)
        if origin is list:
            inner = t.get_args(ann)[0] if t.get_args(ann) else str
            props[pname] = {"type": "array", "items": {"type": _PY_TO_JSON.get(inner, "string")}}
        elif ann in _PY_TO_JSON:
            props[pname] = {"type": _PY_TO_JSON[ann]}
        else:
            props[pname] = {"type": "string"}
        if param.default is inspect._empty:
            required.append(pname)
        else:
            props[pname]["default"] = param.default
    return {"type": "object", "properties": props, "required": required}


def skill(
    name: str | None = None,
    description: str = "",
    requires: list[str] | None = None,
    sensitive: bool = False,
    parameters: dict | None = None,
):
    """Register a function as a skill the agent can invoke.
    
    `parameters` can be provided as an explicit JSON schema dict to override
    the auto-inferred schema. If omitted, the schema is built from type hints.
    """
    def deco(func: t.Callable) -> t.Callable:
        sname = name or func.__name__
        desc = description or (inspect.getdoc(func) or "").strip().split("\n")[0]
        if parameters is not None:
            # Caller provided explicit schema — wrap as object schema
            schema: dict
            if "type" in parameters and parameters["type"] == "object":
                schema = parameters
            else:
                # Treat as properties dict
                props = parameters
                required = [k for k, v in props.items() if "default" not in v]
                schema = {"type": "object", "properties": props, "required": required}
        else:
            schema = _build_schema(func)
        _REGISTRY[sname] = Skill(
            name=sname,
            description=desc,
            func=func,
            parameters=schema,
            requires=requires or [],
            sensitive=sensitive,
        )
        logger.debug(f"Registered skill: {sname}")
        return func
    return deco


def get(name: str) -> Skill | None:
    return _REGISTRY.get(name)


def all_skills() -> list[Skill]:
    return list(_REGISTRY.values())


def available_skills() -> list[Skill]:
    """Skills whose required env vars are present."""
    from ram.core.config import settings
    out = []
    for s in _REGISTRY.values():
        if all(getattr(settings, r.lower(), "") for r in s.requires):
            out.append(s)
    return out


def discover(package: str = "ram.skills") -> None:
    """Auto-import every module in ram.skills/ (recursive) so @skill decorators fire."""
    import pkgutil
    pkg = importlib.import_module(package)
    for finder, modname, ispkg in pkgutil.walk_packages(pkg.__path__, prefix=package + "."):
        if ispkg:
            continue
        short = modname.split(".")[-1]
        try:
            importlib.import_module(modname)
        except Exception as e:
            logger.warning(f"Skill module {short} failed to load: {e}")
    logger.info(f"Discovered {len(_REGISTRY)} skills ({len(available_skills())} active)")
