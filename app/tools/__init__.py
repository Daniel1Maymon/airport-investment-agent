"""The agent's tools. Every tool is registered in app.tools.base.

What it is:   The package of agent tools. It imports each tool file, and each tool file
              adds its tool to TOOLS when it is imported.
Why we need:  So TOOLS is full wherever app.tools is imported, and no tool is forgotten.
Used by:      tests: test_step08_tool_base.py, test_step09_resolver.py,
              test_step10_rank_profile.py, test_step11_trend_routes_delays.py.
              Planned: Step 14 agent loop (sends the tools to the AI and runs them).
Uses:         app/tools/delays.py, app/tools/find.py, app/tools/profile.py,
              app/tools/rank.py, app/tools/routes.py, app/tools/trend.py. The tool files
              of Step 12 will be added here.
Main parts:   no public names, only the imports of the tool files.
Design:       docs/tools.md "How a tool call works"; docs/implementation-plan.md Steps 9-11.
"""

from app.tools import delays  # noqa: F401
from app.tools import find  # noqa: F401
from app.tools import profile  # noqa: F401
from app.tools import rank  # noqa: F401
from app.tools import routes  # noqa: F401
from app.tools import trend  # noqa: F401
