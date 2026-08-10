from pydantic import BaseModel
from typing import Optional


class Property(BaseModel):
    address: str
    city: str
    state: str
    zip_code: str
    county: str

    year_built: Optional[int] = None
    square_feet: Optional[int] = None
    assessment: Optional[int] = None
    purchase_date: Optional[str] = None

    roof_updated: Optional[bool] = None
    roof_year: Optional[int] = None

    latitude: Optional[float] = None
    longitude: Optional[float] = None