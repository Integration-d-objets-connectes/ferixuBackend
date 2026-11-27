# @author Félix Lachapelle

from pydantic import BaseModel, ConfigDict, Field


class Configuration(BaseModel):
    """Paramètres modifiables depuis l'application (EF24), validés sur le Pi.

    Args:
        BaseModel (_type_): modèle pydantic
    """

    # strict : refuse les textes et les booléens à la place des nombres
    # allow_inf_nan=False : refuse NaN et l'infini
    model_config = ConfigDict(validate_assignment=True, strict=True, allow_inf_nan=False)

    humidite_min: float = Field(ge=0, le=100)
    lux_min: float = Field(ge=1, le=200000)
    # EF14 et EF16 : jamais plus de 3 secondes
    duree_arrosage: float = Field(ge=0.1, le=3)
    automatique: bool
