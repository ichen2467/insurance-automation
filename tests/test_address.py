from app.services.address_service import normalize_address


def test_normalize_address():
    address = normalize_address(
        "Your Address Here"
    )

    assert address.street == "Street"
    assert address.city == "City"
    assert address.state == "State"
    assert address.zip_code == "Zip Code"