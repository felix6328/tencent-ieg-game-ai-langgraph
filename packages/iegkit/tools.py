"""Tool calls are allowlisted per node. Missing permission fails closed."""

from __future__ import annotations


class ToolPermissionError(PermissionError):
    def __init__(self, name: str):
        self.tool_name = name
        super().__init__(f"tool {name} is not permitted for this node")


class ToolGate:
    def __init__(self, tools: dict):
        self.tools = tools
        self.calls: list[dict] = []

    def call(self, name: str, args: dict | None = None, *, allow: set[str]):
        if name not in allow or name not in self.tools:
            self.calls.append({"name": name, "allowed": False})
            raise ToolPermissionError(name)
        self.calls.append({"name": name, "allowed": True})
        return self.tools[name](**(args or {}))
