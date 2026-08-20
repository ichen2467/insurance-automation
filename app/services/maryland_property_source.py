# app/services/maryland_property_source.py

from collections import Counter
from typing import Any, Optional

import requests


class MarylandPropertySource:
    BASE_URL = (
        "https://mdgeodata.md.gov/imap/rest/services/"
        "PlanningCadastre/MD_PropertyData/MapServer/0/query"
    )

    def lookup(
        self,
        street_number: str,
        street_name: str,
        street_type: str,
        city: str,
        zip_code: str,
        unit: Optional[str] = None,
        square_feet: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Look up a Maryland property.

        Behavior:
        - If there is one property at the address, return it.
        - If a unit is provided, try to find that exact unit.
        - If the exact unit is not found and square_feet is provided,
          find units with matching square footage.
        - Use the most common improvement value among those matching units.
        """

        properties = self.lookup_all(
            street_number=street_number,
            street_name=street_name,
            street_type=street_type,
            city=city,
            zip_code=zip_code,
        )

        if not properties:
            return None

        # If no unit was provided, return the property only if there
        # is exactly one result.
        if not unit:
            if len(properties) == 1:
                return properties[0]

            return None

        # ---------------------------------------------------------
        # Try exact unit match first
        # ---------------------------------------------------------

        normalized_unit = self._normalize_unit(unit)

        for property_data in properties:
            api_unit = property_data.get("STRTUNT")

            if not api_unit:
                continue

            if self._normalize_unit(api_unit) == normalized_unit:
                return property_data

        # ---------------------------------------------------------
        # Exact unit not found - use square footage fallback
        # ---------------------------------------------------------

        if square_feet is None:
            return None

        try:
            square_feet = int(square_feet)
        except (TypeError, ValueError):
            return None

        sqft_matches = [
            property_data
            for property_data in properties
            if property_data.get("SQFTSTRC") == square_feet
        ]

        if not sqft_matches:
            return None

        # ---------------------------------------------------------
        # Find the most common improvement value
        # ---------------------------------------------------------

        improvement_values = [
            property_data.get("NFMIMPVL")
            for property_data in sqft_matches
            if property_data.get("NFMIMPVL") is not None
        ]

        if not improvement_values:
            return None

        value_counts = Counter(improvement_values)

        most_common_value, count = value_counts.most_common(1)[0]

        # Use one matching property as the base result.
        result = sqft_matches[0].copy()

        # Override the improvement value with the most common value.
        result["NFMIMPVL"] = most_common_value

        # Metadata showing this was a fallback.
        result["LOOKUP_METHOD"] = "SQUARE_FEET_FALLBACK"
        result["REQUESTED_UNIT"] = unit
        result["MATCHING_SQUARE_FEET"] = square_feet
        result["IMPROVEMENT_VALUE_MATCH_COUNT"] = count
        result["IMPROVEMENT_VALUE_TOTAL_MATCHES"] = len(improvement_values)

        return result

    def lookup_all(
        self,
        street_number: str,
        street_name: str,
        street_type: str,
        city: str,
        zip_code: str,
    ) -> list[dict[str, Any]]:
        """
        Return every property record matching the street address.
        """

        street_number = str(street_number).strip()
        street_name = str(street_name).strip().upper()
        street_type = str(street_type).strip().upper()
        city = str(city).strip().upper()
        zip_code = str(zip_code).strip().split("-")[0]

        where = " AND ".join(
            [
                f"STRTNUM = {int(street_number)}",
                f"STRTNAM = '{self._escape(street_name)}'",
                f"STRTTYP = '{self._escape(street_type)}'",
                f"CITY = '{self._escape(city)}'",
                f"ZIPCODE = '{self._escape(zip_code)}'",
            ]
        )

        params = {
            "where": where,
            "outFields": "*",
            "returnGeometry": "false",
            "f": "json",
        }

        response = requests.get(
            self.BASE_URL,
            params=params,
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()

        if "error" in data:
            raise RuntimeError(
                f"Maryland property API error: {data['error']}"
            )

        return [
            feature["attributes"]
            for feature in data.get("features", [])
        ]

    @staticmethod
    def _normalize_unit(unit: str) -> str:
        """
        Normalize equivalent unit formats.

        Examples:
            10       -> 10
            APT 10   -> 10
            UNIT 10  -> 10
            #10      -> 10
        """

        unit = str(unit).strip().upper()

        prefixes = (
            "APARTMENT ",
            "APT ",
            "UNIT ",
            "#",
        )

        for prefix in prefixes:
            if unit.startswith(prefix):
                unit = unit[len(prefix):]
                break

        return unit.strip()

    @staticmethod
    def _escape(value: str) -> str:
        """Escape single quotes for the ArcGIS SQL query."""

        return value.replace("'", "''")