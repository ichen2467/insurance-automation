from app.services.maryland_property_source import MarylandPropertySource


def test_maryland_property_lookup():
    client = MarylandPropertySource()

    property_data = client.lookup(
        street_number="1307",
        street_name="LOBELIA",
        street_type="LN",
        city="BELCAMP",
        zip_code="21017",
    )

    print("\nResult:")
    print(property_data)

    assert property_data is not None

    print("\n--- Important values ---")
    print(f"Address: {property_data.get('ADDRESS')}")
    print(f"Unit: {property_data.get('STRTUNT')}")
    print(f"City: {property_data.get('CITY')}")
    print(f"ZIP: {property_data.get('ZIPCODE')}")
    print(f"Year Built: {property_data.get('YEARBLT')}")
    print(f"Square Feet: {property_data.get('SQFTSTRC')}")
    print(
        f"Improvement Value: "
        f"${property_data.get('NFMIMPVL', 0):,}"
    )
    print(
        f"Land Value: "
        f"${property_data.get('NFMLNDVL', 0):,}"
    )
    print(
        f"Total Value: "
        f"${property_data.get('NFMTTLVL', 0):,}"
    )
    print(f"Property Type: {property_data.get('DESCLU')}")
    print(f"Style: {property_data.get('DESCSTYL')}")
    print(f"Lookup Method: {property_data.get('LOOKUP_METHOD')}")