class LimitReachedError(Exception):
    """Raised when an engine hits quota or credit limits."""

class RobotsDeniedError(PermissionError):
    """Raised when robots.txt disallows the requested URL."""

class AllEnginesFailedError(RuntimeError):
    """Raised when every eligible engine fails."""
