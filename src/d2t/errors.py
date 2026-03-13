"""Custom exceptions with semantic exit codes."""


class D2tError(Exception):
    """Base exception for d2t. All d2t exceptions carry an exit_code."""

    exit_code: int = 1

    def __init__(self, message: str):
        super().__init__(message)


class InputNotFoundError(D2tError):
    exit_code = 10


class InputParseError(D2tError):
    exit_code = 11


class UnknownStrategyError(D2tError):
    exit_code = 20

    def __init__(self, name: str, available: list[str] | None = None):
        available_str = ", ".join(available) if available else "(none)"
        super().__init__(
            f"Unknown strategy: '{name}'. Available: {available_str}"
        )


class StrategyProcessingError(D2tError):
    exit_code = 21


class UnknownTemplateError(D2tError):
    exit_code = 30

    def __init__(self, name: str, available: list[str] | None = None):
        available_str = ", ".join(available) if available else "(none)"
        super().__init__(
            f"Unknown template: '{name}'. Available: {available_str}"
        )


class TemplateRenderError(D2tError):
    exit_code = 31


class UnknownRecipeError(D2tError):
    exit_code = 40

    def __init__(self, name: str, available: list[str] | None = None):
        available_str = ", ".join(available) if available else "(none)"
        super().__init__(
            f"Unknown recipe: '{name}'. Available: {available_str}"
        )


class RecipeConfigError(D2tError):
    exit_code = 41


def format_error(err: D2tError) -> str:
    """Format an error for stderr output."""
    return f"d2t: error[{err.exit_code}]: {err}"
