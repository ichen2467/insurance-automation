from app.services.address_service import normalize_address


def test_normalize_address():
    address = normalize_address(
        "3422 Rollingview Court, Ellicott City, MD 21042"
    )

    assert address.street == "3422 Rollingview Court"
    assert address.city == "Ellicott City"
    assert address.state == "MD"
    assert address.zip_code == "21042"