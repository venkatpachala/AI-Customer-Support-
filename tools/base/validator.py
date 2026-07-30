from typing import Type, TypeVar
from pydantic import BaseModel, ValidationError as PydanticValidationError
from tools.base.exceptions import ValidationError

T = TypeVar("T", bound=BaseModel)


def validate_request(model: Type[T], payload: dict) -> T:
    try:
        return model(**(payload or {}))
    except PydanticValidationError as e:
        raise ValidationError(str(e)) from e