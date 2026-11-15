class ServiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details: dict | list | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details


class NotFound(ServiceError):
    def __init__(self, what: str):
        super().__init__("not_found", f"{what} nicht gefunden.", 404)
