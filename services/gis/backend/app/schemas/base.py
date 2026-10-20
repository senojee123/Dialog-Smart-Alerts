"""Shared Pydantic configuration: camelCase on the wire (e.g. ``distanceM``), snake_case in Python."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True, extra="forbid")
