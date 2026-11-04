from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, PrivateAttr


class ScalewayModel(BaseModel):
    """Base of every generated model: unknown fields are kept, not rejected."""

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        serialize_by_alias=True,
        use_enum_values=False,
        protected_namespaces=(),
    )

    _session: Any = PrivateAttr(default=None)
    _key: dict[str, str | None] = PrivateAttr(default_factory=dict)


class Money(ScalewayModel):
    """An amount of money, as `google.type.Money`: whole units plus nanos."""

    currency_code: str = ""
    units: int = 0
    nanos: int = 0

    def to_decimal(self) -> Decimal:
        return Decimal(self.units) + Decimal(self.nanos).scaleb(-9)
