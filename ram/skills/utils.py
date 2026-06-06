"""Tiny utility skills."""
from __future__ import annotations

import datetime as dt

from ram.core.config import settings
from ram.core.registry import skill


@skill(name="current_time", description="Return the current local date and time.")
def current_time() -> str:
    return dt.datetime.now().strftime(f"%A, %B %d %Y %I:%M %p ({settings.ram_timezone})")


@skill(name="calculator", description="Evaluate a simple math expression (safe, no names).")
def calculator(expression: str) -> str:
    import ast, operator
    ops = {
        ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow,
        ast.USub: operator.neg, ast.UAdd: operator.pos, ast.FloorDiv: operator.floordiv,
    }
    def ev(n):
        if isinstance(n, ast.Constant): return n.value
        if isinstance(n, ast.BinOp): return ops[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp): return ops[type(n.op)](ev(n.operand))
        raise ValueError("unsafe")
    try:
        return str(ev(ast.parse(expression, mode="eval").body))
    except Exception as e:
        return f"ERROR: {e}"
