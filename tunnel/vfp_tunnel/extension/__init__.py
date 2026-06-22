"""Generic extension API: namespace discovery + an action request channel.

Lets any external client (a CLI, an MCP/LLM controller, or another process)
discover capabilities a servicer has announced and invoke them generically,
without the tunnel knowing the capability in advance. The tunnel is pure
transport here — it never executes an action itself; a registered servicer
(e.g. the in-Virtuoso plugin) pulls the request, runs it under its own gating,
and posts the result back.
"""

from .registry import ActionStore, ExtensionRegistry

__all__ = ["ActionStore", "ExtensionRegistry"]
