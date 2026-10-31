"""The agent's tools. Every tool is registered in app.tools.base.

What it is:   The package of agent tools. It imports each tool file, and each tool file
              adds its tool to TOOLS when it is imported.
Why we need:  So TOOLS is full wherever app.tools is imported, and no tool is forgotten.
Used by:      tests: test_step08_tool_base.py, test_step09_resolver.py.
              Planned: Step 14 agent loop (sends the tools to the AI and runs them).
Uses:         app/tools/find.py. The tool files of Steps 10-12 will be added here.
Main parts:   no public names, only the imports of the tool files.
Design:       docs/tools.md "How a tool call works"; docs/implementation-plan.md Step 9.
"""

from app.tools import find  # noqa: F401
