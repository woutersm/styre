"""styre: an overnight phase orchestrator for the pi coding agent.

Point it at a design document split into phases. It runs one fresh pi process per phase,
serially, unattended. In the morning there is one git commit per phase and logs showing
what happened.
"""

# Bump this whenever behaviour changes. uv caches a built wheel per source path *and*
# version, so `uv tool install --force` silently reuses a stale wheel when the version has
# not moved — that is how the 2026-09-20 gateway run went out with the old prompt builder.
# The version is recorded in every run's timeline, so a stale install is visible afterwards.
__version__ = "0.18.0"

__all__ = ["__version__"]
