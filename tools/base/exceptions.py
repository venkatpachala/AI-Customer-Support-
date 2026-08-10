class ToolError(Exception):
    def __init__(self, message: str, code: str = "tool_error", retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable


class ValidationError(ToolError):
    def __init__(self, message: str):
        super().__init__(message, code="validation_error", retryable=False)


class AuthenticationError(ToolError):
    def __init__(self, message: str):
        super().__init__(message, code="authentication_error", retryable=False)


class AuthorizationError(ToolError):
    def __init__(self, message: str):
        super().__init__(message, code="authorization_error", retryable=False)


class RateLimitError(ToolError):
    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message, code="rate_limit_error", retryable=True)


class TimeoutError(ToolError):
    def __init__(self, message: str = "Request timed out"):
        super().__init__(message, code="timeout_error", retryable=True)


class ProviderUnavailableError(ToolError):
    def __init__(self, message: str = "Provider unavailable"):
        super().__init__(message, code="provider_unavailable", retryable=True)


class ResourceNotFoundError(ToolError):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, code="resource_not_found", retryable=False)


class BusinessRuleError(ToolError):
    def __init__(self, message: str):
        super().__init__(message, code="business_rule_error", retryable=False)