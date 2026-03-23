"""
Source-tree compatibility alias.

The project uses a hyphenated directory name `mcp-servers/` on disk, but the
Python import path is `mcp_servers.*`.

When running from source without installing the package via setuptools'
`package_dir`, this alias makes `import mcp_servers.storage...` work by
pointing the package search path to the underlying `mcp-servers/` directory.
"""

from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve()
_ROOT = _HERE.parent.parent
_MCP_DIR = _ROOT / "mcp-servers"

# Let Python discover subpackages (storage/, monitor/, deploy/) from mcp-servers/
__path__ = [str(_MCP_DIR)]  # type: ignore[name-defined]

