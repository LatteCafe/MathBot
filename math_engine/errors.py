"""Exceptions raised by the math engine. Cogs turn these into friendly messages."""


class MathError(Exception):
    """Base class for all math-engine errors. The message is safe to show to users."""


class InputError(MathError):
    """The user's input was invalid, unsupported, or too large."""


class ComputeTimeout(MathError):
    """The calculation exceeded the time limit and was stopped."""


class ComputeFailed(MathError):
    """The calculation crashed or failed for an unexpected reason."""
