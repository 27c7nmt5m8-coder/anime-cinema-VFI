class VFIError(Exception):
    """Actionable error that may be displayed to the user."""


class Cancelled(VFIError):
    pass


class ProcessError(VFIError):
    pass


class OutOfMemoryError(VFIError):
    pass
