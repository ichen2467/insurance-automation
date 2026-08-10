from app.services.address_service import normalize_address


address = normalize_address(
    "123 Main St, Ellicott City, MD"
)

print(address)