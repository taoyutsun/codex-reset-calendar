"""Safe error codes: never expose raw credential-aware backend diagnostics."""


class ToolError(Exception):
    def __init__(self, code, message=None):
        self.code = code
        super().__init__(code)


def fail(code, message=None):
    raise ToolError(code)
