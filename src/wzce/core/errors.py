"""Exception hierarchy for the core layer.

The UI catches ``WzceError`` and shows ``str(error)`` to the user, so messages
should be short and actionable. Every subclass maps to one failure category the
UI may want to handle differently (e.g. offer "close the game" for GameRunningError).
"""


class WzceError(Exception):
    """Base class for all expected (non-bug) errors raised by the core."""


class ParseError(WzceError):
    """The settings file does not follow the expected grammar."""

    def __init__(self, message: str, line_number: int | None = None) -> None:
        # line_number is 1-based to match what a text editor shows.
        self.line_number = line_number
        prefix = f"line {line_number}: " if line_number is not None else ""
        super().__init__(prefix + message)


class ValidationError(WzceError):
    """A value is not acceptable for a setting (wrong type, out of range, unknown option)."""


class UnknownSettingError(WzceError, KeyError):
    """The requested setting id (``Key@Variant``) does not exist in the document."""

    def __str__(self) -> str:  # KeyError would otherwise wrap the message in quotes
        return str(self.args[0]) if self.args else "unknown setting"


class GameRunningError(WzceError):
    """Writing was refused because the game is running and would overwrite our changes."""


class WriteVerificationError(WzceError):
    """A file was written but reading it back did not return the expected bytes."""


class BackupError(WzceError):
    """Creating or restoring a backup failed."""
