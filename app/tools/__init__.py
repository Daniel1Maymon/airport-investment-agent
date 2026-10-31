"""The agent's tools. Every tool is registered in app.tools.base.

What it is:   The package of agent tools. It imports each tool file, and each tool file
              adds its tool to TOOLS when it is imported.
Why we need:  So TOOLS is full wherever app.tools is imported, and no tool is forgotten.
Used by:      tests: test_step08_tool_base.py, test_step09_resolver.py,
              test_step10_rank_profile.py, test_step11_trend_routes_delays.py,
              test_step12_unmet_info_live.py.
              app/agent/loop.py (sends the tools to the AI and runs them);
              test_step14_agent_loop.py.
Uses:         app/tools/delays.py, app/tools/find.py, app/tools/info.py,
              app/tools/live.py, app/tools/profile.py, app/tools/rank.py,
              app/tools/routes.py, app/tools/trend.py, app/tools/unmet.py.
Main parts:   no public names, only the imports of the tool files.
Design:       docs/tools.md "How a tool call works"; docs/implementation-plan.md Steps 9-12.
"""

from app.tools import delays  # noqa: F401
from app.tools import find  # noqa: F401
from app.tools import info  # noqa: F401
from app.tools import live  # noqa: F401
from app.tools import profile  # noqa: F401
from app.tools import rank  # noqa: F401
from app.tools import routes  # noqa: F401
from app.tools import trend  # noqa: F401
from app.tools import unmet  # noqa: F401
