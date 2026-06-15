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

        section_match = re.search(
            r'Public tax history(.*?)Show more',
            body_text,
            re.DOTALL
        )

        if not section_match:
            return ""

        section_text = (
            section_match.group(1)
        )

        lines = section_text.splitlines()

        newest_year = -1
        newest_assessment = ""

        for line in lines:

            line = line.strip()

            if re.match(
                r'^20\d{2}',
                line
            ):

                year_match = re.match(
                    r'^(20\d{2})',
                    line
                )

                if not year_match:
                    continue

                year = int(
                    year_match.group(1)
                )

                money_values = re.findall(
                    r'\$([\d,]+)',
                    line
                )

                if not money_values:
                    continue

                # Maryland:
                # 2025 -- $846,033
                if len(money_values) == 1:

                    assessment = int(
                        money_values[0]
                        .replace(",", "")
                    )

                # Virginia:
                # 2025 $15,928 $1,377,880
                else:

                    assessment = int(
                        money_values[-1]
                        .replace(",", "")
                    )

                if year > newest_year:

                    newest_year = year
                    newest_assessment = str(
                        assessment
                    )

        return newest_assessment

    except Exception as e:

        print(
            "Assessment error:",
            str(e)
        )

    return ""

# --------------------------------
# LOAD EXCEL
# --------------------------------

df = pd.read_excel("customers.xlsx")
df = df.dropna(how="all")

# force columns to string type
text_columns = [
    "YearBuilt",
    "SquareFeet",
    "PurchaseDate",
    "TotalAssessment",
    "LookupStatus"
]

for col in text_columns:

    if col not in df.columns:
        df[col] = ""

    df[col] = (
        df[col]
        .astype(str)
    )


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

            page.wait_for_timeout(2000)

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