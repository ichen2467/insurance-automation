import re

from app.schemas.address import Address


SUPPORTED_STATES = {
    "MD": "MD",
    "MARYLAND": "MD",
    "VA": "VA",
    "VIRGINIA": "VA",
}


def normalize_address(raw_address: str) -> Address:
    """Validate and normalize a user-provided MD or VA address."""

    if not raw_address or not raw_address.strip():
        raise ValueError("Address cannot be empty.")

    parts = [part.strip() for part in raw_address.split(",")]

    if len(parts) < 3:
        raise ValueError(
            "Address must include street, city, and state/ZIP."
        )

    street = parts[0]
    city = parts[1]

    state_zip = " ".join(parts[2].split())

    match = re.fullmatch(
        r"([A-Za-z]+)(?:\s+(\d{5}(?:-\d{4})?))?",
        state_zip,
    )

    if not match:
        raise ValueError("Invalid state or ZIP code format.")

    state_input = match.group(1).upper()
    zip_code = match.group(2)

    state = SUPPORTED_STATES.get(state_input)

    if not state:
        raise ValueError(
            "Only Maryland (MD) and Virginia (VA) are supported."
        )

    if not zip_code:
        raise ValueError("ZIP code is required.")

    return Address(
        street=street,
        city=city,
        state=state,
        zip_code=zip_code,
    )