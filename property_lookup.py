import re
import pandas as pd
from playwright.sync_api import sync_playwright


# --------------------------------
# HELPERS
# --------------------------------

def safe_text(locator):
    try:
        return locator.inner_text().strip()
    except:
        return ""


def extract_year_built(page):
    try:
        built_locator = page.locator(
            'text=/Built in \\d{4}/'
        ).first

        text = built_locator.inner_text()

        match = re.search(r'Built in (\d{4})', text)

        if match:
            return match.group(1)

    except:
        pass

    return ""


def extract_square_feet(page):
    try:
        sqft_locator = page.locator(
            'text=/[\\d,]+ sqft/'
        ).first

        text = sqft_locator.inner_text()

        match = re.search(
            r'([\d,]+)\s*sqft',
            text
        )

        if match:
            return match.group(1).replace(",", "")

    except:
        pass

    return ""


def extract_purchase_date(page):
    try:
        page.locator(
            'text="Price history"'
        ).scroll_into_view_if_needed()

        page.wait_for_timeout(1500)

        sold_rows = page.locator(
            'tr'
        ).filter(
            has_text="Sold"
        )

        count = sold_rows.count()

        if count > 0:

            row_text = sold_rows.first.inner_text()

            date_match = re.search(
                r'(\d{1,2})/(\d{1,2})/(\d{4})',
                row_text
            )

            if date_match:
                month = date_match.group(1).zfill(2)
                year = date_match.group(3)

                return f"{month}/{year}"

    except:
        pass

    return ""

def extract_tax_assessment(page):
    try:

        body_text = page.locator(
            "body"
        ).inner_text()

        # isolate Public tax history section
        tax_section_match = re.search(
            r'Public tax history(.*?)(Climate risks|Nearby schools|Neighborhood)',
            body_text,
            re.DOTALL | re.IGNORECASE
        )

        if not tax_section_match:
            return ""

        tax_section = (
            tax_section_match.group(1)
        )

        # find year + assessment rows
        matches = re.findall(
            r'(20\d{2}).*?\$([\d,]+)',
            tax_section,
            re.DOTALL
        )

        assessments = []

        for year, amount in matches:

            clean_amount = int(
                amount.replace(",", "")
            )

            if clean_amount > 50000:
                assessments.append(
                    (
                        int(year),
                        clean_amount
                    )
                )

        if assessments:

            newest = max(
                assessments,
                key=lambda x: x[0]
            )

            return str(
                newest[1]
            )

    except:
        pass

    return ""

# --------------------------------
# LOAD EXCEL
# --------------------------------

df = pd.read_excel("customers.xlsx")
df = df.dropna(how="all")

new_columns = [
    "YearBuilt",
    "SquareFeet",
    "PurchaseDate",
    "TotalAssessment",
    "LookupStatus"
]

for col in new_columns:
    if col not in df.columns:
        df[col] = ""


# --------------------------------
# PLAYWRIGHT
# --------------------------------

with sync_playwright() as p:

    print("Connecting to browser...")

    browser = p.chromium.connect_over_cdp(
        "http://localhost:9222"
    )

    print("Connected!")

    context = browser.contexts[0]

    page = None

    for tab in context.pages:
        try:
            if "zillow" in tab.url.lower():
                page = tab
                break
        except:
            pass

    if page is None:
        page = context.new_page()

    # --------------------------------
    # LOOP THROUGH CUSTOMERS
    # --------------------------------

    for index, row in df.iterrows():

        try:

            address = str(
                row["Address"]
            ).strip()

            city = str(
                row["City"]
            ).strip()

            state = str(
                row["State"]
            ).strip()

            zip_code = str(
                row["ZIP"]
            ).strip()

            full_address = (
                f"{address}, "
                f"{city}, "
                f"{state} "
                f"{zip_code}"
            )

            print(
                f"\nLooking up: "
                f"{full_address}"
            )

            search_url = (
                "https://www.zillow.com/"
                "homes/"
                f"{full_address.replace(' ', '-')}"
                "_rb/"
            )

            page.goto(
                search_url,
                timeout=60000
            )

            page.wait_for_timeout(5000)

            year_built = extract_year_built(page)

            square_feet = extract_square_feet(page)

            print("Year Built:", year_built)
            print("Square Feet:", square_feet)

            # --------------------------------
            # SCROLL TO LOAD PRICE/TAX HISTORY
            # --------------------------------

            print("Scrolling Zillow panel...")

            page.mouse.move(
                900,
                500
            )

            for _ in range(8):

                page.mouse.wheel(
                    0,
                    900
                )

                page.wait_for_timeout(
                    1500
                )

            print("Finished scrolling")

            # --------------------------------
            # EXTRACT LOWER PAGE DATA
            # --------------------------------

            purchase_date = (
                extract_purchase_date(page)
            )

            assessment = (
                extract_tax_assessment(page)
            )

            print(
                "Purchase Date:",
                purchase_date
            )

            print(
                "Assessment:",
                assessment
            )

            df.at[
                index,
                "YearBuilt"
            ] = year_built

            df.at[
                index,
                "SquareFeet"
            ] = square_feet

            df.at[
                index,
                "PurchaseDate"
            ] = purchase_date

            df.at[
                index,
                "TotalAssessment"
            ] = assessment

            df.at[
                index,
                "LookupStatus"
            ] = "Zillow"

            print(
                "Year Built:",
                year_built
            )

            print(
                "Square Feet:",
                square_feet
            )

            print(
                "Purchase Date:",
                purchase_date
            )

            print(
                "Assessment:",
                assessment
            )

        except Exception as e:

            print(
                "Failed:",
                str(e)
            )

            df.at[
                index,
                "LookupStatus"
            ] = "Failed"

    # --------------------------------
    # SAVE BACK TO CUSTOMERS.XLSX
    # --------------------------------

    df.to_excel(
        "customers.xlsx",
        index=False
    )

    print(
        "\nUpdated customers.xlsx"
    )