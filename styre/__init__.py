"""styre: an overnight phase orchestrator for the pi coding agent.

Point it at a design document split into phases. It runs one fresh pi process per phase,
serially, unattended. In the morning there is one git commit per phase and logs showing
what happened.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
