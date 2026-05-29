"""Base abstractions: model, service, exception, response.

Uses lazy imports to avoid circular dependencies during Django startup.
"""

__all__ = [
    "BaseCustomError",
    "BaseGenericTabularInline",
    "BaseModel",
    "BaseModelAdmin",
    "BaseResponse",
    "BaseService",
    "BaseTabularInline",
    "NamedBaseModel",
]


def __getattr__(name: str):
    if name == "BaseCustomError":
        from core.base.exception import BaseCustomError

        return BaseCustomError
    if name == "BaseModel":
        from core.base.model import BaseModel

        return BaseModel
    if name == "NamedBaseModel":
        from core.base.model import NamedBaseModel

        return NamedBaseModel
    if name == "BaseModelAdmin":
        from core.base.admin import BaseModelAdmin

        return BaseModelAdmin
    if name == "BaseTabularInline":
        from core.base.admin import BaseTabularInline

        return BaseTabularInline
    if name == "BaseGenericTabularInline":
        from core.base.admin import BaseGenericTabularInline

        return BaseGenericTabularInline
    if name == "BaseResponse":
        from core.base.response import BaseResponse

        return BaseResponse
    if name == "BaseService":
        from core.base.service import BaseService

        return BaseService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
