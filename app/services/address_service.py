import requests

from app.schemas.address import Address


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

HEADERS = {
    "User-Agent": "insurance-automation/1.0"
}


def normalize_address(raw_address: str) -> Address:
    """Convert a user-provided address into a standardized Address object."""

    if not raw_address or not raw_address.strip():
        raise ValueError("Address cannot be empty.")

    params = {
        "q": raw_address,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 1,
        "countrycodes": "us",
    }

    response = requests.get(
        NOMINATIM_URL,
        params=params,
        headers=HEADERS,
        timeout=10,
    )

    response.raise_for_status()

    results = response.json()

    if not results:
        raise ValueError(f"Could not find address: {raw_address}")

    result = results[0]
    address_data = result.get("address", {})

    street_number = address_data.get("house_number", "")
    street_name = address_data.get("road", "")

    street = " ".join(
        part for part in [street_number, street_name]
        if part
    )

    city = (
        address_data.get("city")
        or address_data.get("town")
        or address_data.get("village")
        or ""
    )

    state = address_data.get("state", "")
    zip_code = address_data.get("postcode", "")
    county = address_data.get("county", "")

    if not street:
        raise ValueError("Nominatim did not return a street address.")

    if not city:
        raise ValueError("Nominatim did not return a city.")

    if not state:
        raise ValueError("Nominatim did not return a state.")

    if not zip_code:
        raise ValueError("Nominatim did not return a ZIP code.")

    return Address(
        street=street,
        city=city,
        state=state,
        zip_code=zip_code,
        county=county,
        latitude=float(result["lat"]),
        longitude=float(result["lon"]),
    )