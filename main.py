import pandas as pd
from playwright.sync_api import sync_playwright


# --------------------------------
# DROPDOWN HELPER
# --------------------------------

def select_dropdown(page, selector, option_text):
    dropdown = page.locator(selector)

    # try clicking dropdown
    for attempt in range(3):

        try:

            dropdown.click(
                timeout=3000
            )

            break

        except:

            print(
                f"Retrying dropdown "
                f"({attempt + 1}/3)"
            )

            page.wait_for_timeout(
                1000
            )

    page.wait_for_timeout(500)

    if option_text.lower() == "yes":
        dropdown.press("Y")

    elif option_text.lower() == "no":
        dropdown.press("N")

    else:
        dropdown.fill(option_text)

    page.wait_for_timeout(300)

    dropdown.press("Enter")

    page.wait_for_timeout(300)


# --------------------------------
# LOAD CUSTOMER DATA
# --------------------------------

df = pd.read_excel("customers.xlsx")
df = df.dropna(how="all")

row = df.iloc[0]

first_name = str(row["FirstName"]).strip()
last_name = str(row["LastName"]).strip()

street_address = str(row["Address"]).strip()
city = str(row["City"]).strip().upper()
state = str(row["State"]).strip().upper()
zip_code = str(int(row["ZIP"]))

formatted_address = (
    f"{street_address.upper()}, "
    f"{city}, "
    f"{state} "
    f"{zip_code}"
)

state_map = {
    "MD": "Maryland",
    "VA": "Virginia"
}

state_name = state_map.get(state, state)

# --------------------------------
# TEMP DEFAULT DATA
# --------------------------------

year_built = str(
    int(row["YearBuilt"])
)

square_feet = str(
    int(row["SquareFeet"])
)

purchase_date = str(
    row["PurchaseDate"]
).strip()

assessment = str(
    int(row["TotalAssessment"])
)

dob = "01/01/1985"

# --------------------------------
# PLAYWRIGHT
# --------------------------------

with sync_playwright() as p:

    print("Connecting to browser...")

    browser = p.chromium.connect_over_cdp(
        "http://localhost:9222"
    )

    print(
        "Opening Foremost..."
    )

    context = browser.contexts[0]

    page = context.new_page()

    page.goto(
        "https://www.foremostagent.com/ia/portal/login",
        timeout=60000
    )

    page.wait_for_timeout(
        2000
    )

    # --------------------------------
    # HANDLE OPTIONAL CONTINUE BUTTONS
    # --------------------------------

    for _ in range(2):

        try:

            continue_button = page.get_by_role(
                "button",
                name="Continue"
            )

            if continue_button.is_visible():

                print(
                    "Clicking Continue..."
                )

                continue_button.click()

                page.wait_for_timeout(
                    2000
                )

        except:

            print(
                "No Continue button"
            )

            break

    print(
        "Foremost opened"
    )

    print("Connected!")

    context = browser.contexts[0]

    page = None

    for tab in context.pages:
        try:
            if "foremost" in tab.url.lower():
                page = tab
                break
        except:
            pass

    if page is None:
        print("Foremost tab not found")
        exit()

    # --------------------------------
    # START QUOTE
    # --------------------------------

    page.get_by_role(
        "button",
        name="Start quote"
    ).click()

    print("Clicked Start Quote")

    page.wait_for_timeout(3000)

    quote_page = context.pages[-1]

    print("Switched to quote tab")

    # --------------------------------
    # QUOTE PAGE
    # --------------------------------

    quote_page.locator(
        '[id="StartNewQuoteForm:cmbPropertyStates"]'
    ).wait_for(timeout=30000)

    print("Quote form loaded")

    print("Using state:", state_name)

    quote_page.locator(
        '[id="StartNewQuoteForm:cmbPropertyStates"]'
    ).select_option(label=state_name)

    print("Selected state")

    quote_page.locator(
        '[id="StartNewQuoteForm:cmbDwellingClassification"]'
    ).select_option(
        label="Traditional Site Built Home"
    )

    print("Selected dwelling classification")

    quote_page.locator(
        '[id="StartNewQuoteForm:cmbDwellingUse"]'
    ).select_option(
        label="Primary"
    )

    print("Selected dwelling use")

    quote_page.get_by_role(
        "link",
        name="Go"
    ).click()

    print("Clicked Go")

    quote_page.wait_for_timeout(3000)

    applicant_page = context.pages[-1]

    print("Switched to location page")

    # --------------------------------
    # LOCATION PAGE
    # --------------------------------

    applicant_page.locator(
        'input[name="string_662|spvalidation"]'
    ).wait_for(timeout=30000)

    print("Location page loaded")

    applicant_page.locator(
        'input[name="string_662|spvalidation"]'
    ).fill(formatted_address)

    print("Filled address")

    applicant_page.get_by_placeholder(
        "YYYY",
        exact=True
    ).fill(year_built)

    print("Filled year built")

    applicant_page.locator(
        'input[name="int_733"]'
    ).fill(square_feet)

    print("Filled square footage")

    applicant_page.get_by_placeholder(
        "MM/YYYY"
    ).fill(purchase_date)

    print("Filled purchase date")

    applicant_page.get_by_role(
        "button",
        name="Continue and Save"
    ).click()

    print("Clicked Continue and Save")

    # --------------------------------
    # APPLICANT PAGE
    # --------------------------------

    applicant_page.locator(
        'input[name="string_1ED8|spvalidation"]'
    ).wait_for(timeout=30000)

    print("Applicant page loaded")

    applicant_page.locator(
        'input[name="string_1ED8|spvalidation"]'
    ).fill(first_name)

    print("Filled first name")

    applicant_page.locator(
        'input[name="string_1EE5|spvalidation"]'
    ).fill(last_name)

    print("Filled last name")

    applicant_page.get_by_placeholder(
        "mm/dd/yyyy"
    ).fill(dob)

    print("Filled DOB")

    # Secondary applicant
    select_dropdown(
        applicant_page,
        'input[name*="1F5C_5_1-inputEl"]',
        "No"
    )

    print("Secondary applicant = No")

    # Auto policy (MD only)

    if state == "MD":

        select_dropdown(
            applicant_page,
            'input[name*="20EE_5_1-inputEl"]',
            "No"
        )

        print(
            "Auto policy = No"
        )

    else:

        print(
            "Auto policy question skipped"
        )

    # Currently insured
    select_dropdown(
        applicant_page,
        'input[name*="2124_5_1-inputEl"]',
        "Yes"
    )

    print("Currently insured = Yes")

    applicant_page.wait_for_timeout(1000)

    # Insurance carrier
    select_dropdown(
        applicant_page,
        'input[name*="2140_5_1-inputEl"]',
        "Other Carrier"
    )

    print("Carrier = Other Carrier")

    applicant_page.locator(
        'input[name*="214A"]'
    ).fill("Other")

    print("Filled carrier textbox")

    # Cancelled history
    select_dropdown(
        applicant_page,
        'input[name*="2153_5_1-inputEl"]',
        "No"
    )

    print("Cancelled history = No")

    # Qualifying policy
    
    select_dropdown(
        applicant_page,
        'input[name*="216E_5_1-inputEl"]',
        "No"
    )

    print("Qualifying policy = No")


    # Farmers employee (MD only)
    
    if state == "MD":
        select_dropdown(
            applicant_page,
            'input[name*="2177_5_1-inputEl"]',
            "No"
        )

        print("Farmers employee = No")
    else:
        print("Skipped Farmers employee question")

    applicant_page.get_by_role(
        "button",
        name="Continue and Save"
    ).click()

    print("Clicked Continue and Save")

    # --------------------------------
    # ELIGIBILITY PAGE
    # --------------------------------

    applicant_page.wait_for_timeout(3000)

    print("Eligibility page loaded")


    # Existing damage (special case)
    damage_dropdown = applicant_page.locator(
        'input[name*="64_5_1-inputEl"]'
    )

    damage_dropdown.click()

    applicant_page.wait_for_timeout(500)

    applicant_page.get_by_role(
        "option",
        name="No"
    ).first.click()

    print("Existing damage = No")

    # Remaining dropdowns
    select_dropdown(
        applicant_page,
        'input[name*="B5_5_1-inputEl"]',
        "No"
    )

    print("Construction = No")

    select_dropdown(
        applicant_page,
        'input[name*="36_5_1-inputEl"]',
        "No"
    )

    print("Swimming pool = No")

    select_dropdown(
        applicant_page,
        'input[name*="4A_5_1-inputEl"]',
        "No"
    )

    print("Trampoline = No")

    select_dropdown(
        applicant_page,
        'input[name*="75_5_1-inputEl"]',
        "No"
    )

    print("Vacant = No")

    if state == "VA":
        select_dropdown(
            applicant_page,
            'input[name*="7F_5_1-inputEl"]',
            "No"
        )

        print("Dogs = No")
    else:
        print("Dogs question skipped")

    select_dropdown(
        applicant_page,
        'input[name*="DA_5_1-inputEl"]',
        "No"
    )

    print("Exotic animals = No")

    select_dropdown(
        applicant_page,
        'input[name*="6B_5_1-inputEl"]',
        "No"
    )

    print("Business/Farm/Ranch = No")

    applicant_page.get_by_role(
        "button",
        name="Continue and Save"
    ).click()

    print("Clicked Continue and Save")

    # --------------------------------
    # LOSSES PAGE
    # --------------------------------

    # wait until eligibility page is gone
    applicant_page.wait_for_timeout(
        5000
    )

    # get only visible Select dropdown
    losses_dropdown = applicant_page.locator(
        'input[placeholder="Select"]:visible'
    )

    losses_dropdown.wait_for(
        timeout=30000
    )

    print("Losses page loaded")

    losses_dropdown.click()

    applicant_page.wait_for_timeout(
        500
    )

    applicant_page.get_by_role(
        "option",
        name="No"
    ).first.click()

    print("Loss history = No")

    applicant_page.get_by_role(
        "button",
        name="Continue and Save"
    ).click()

    print("Clicked Continue and Save")

    # --------------------------------
    # DWELLING PAGE
    # --------------------------------

    applicant_page.wait_for_timeout(3000)

    print("Dwelling page loaded")

    # --------------------------------
    # Number of residential dwellings
    # --------------------------------

    residential_dropdown = applicant_page.get_by_role(
        "row",
        name="Number of residential"
    ).get_by_placeholder("Select")

    residential_dropdown.click()

    applicant_page.wait_for_timeout(500)

    residential_dropdown.press("1")

    applicant_page.wait_for_timeout(300)

    residential_dropdown.press("Enter")

    print("Residential dwellings = 1")

    # --------------------------------
    # Primary heat source
    # --------------------------------

    select_dropdown(
        applicant_page,
        'input[name*="4C_5_1-inputEl"]',
        "Furnace (forced air, radiant and central air)"
    )

    print("Primary heat source = Furnace (forced air, radiant and central air)")

    # --------------------------------
    # Fuel type
    # --------------------------------

    select_dropdown(
        applicant_page,
        'input[name*="61_5_1-inputEl"]',
        "Natural Gas"
    )

    print("Fuel type = Natural Gas")

    # --------------------------------
    # Secondary heat source
    # --------------------------------

    select_dropdown(
        applicant_page,
        'input[name*="74_5_1-inputEl"]',
        "No"
    )

    print("Secondary heat source = No")

    # --------------------------------
    # Garage heating device
    # --------------------------------

    select_dropdown(
        applicant_page,
        'input[name*="A9_5_1-inputEl"]',
        "No"
    )

    print("Garage heating device = No")

    # --------------------------------
    # Rowhouse / townhouse
    # --------------------------------

    select_dropdown(
        applicant_page,
        'input[name*="24_5_1-inputEl"]',
        "No"
    )

    print("Townhouse = No")

    # --------------------------------
    # Electrical, plumbing, heating updated
    # --------------------------------

    if state == "VA":
        select_dropdown(
            applicant_page,
            'input[name*="3E_5_1-inputEl"]',
            "No"
        )

        print("Electrial, plumbing, heating updated = No")
    else:
        print("Electrical, plumbing, heating question skipped")

    # --------------------------------
    # Roof updated
    # --------------------------------

    select_dropdown(
        applicant_page,
        'input[name*="78_5_1-inputEl"]',
        "No"
    )

    print("Roof updated = No")

    # --------------------------------
    # Amount of insurance
    # --------------------------------

    if int(assessment) > 1000000:
        assessment = "1000000"

    applicant_page.locator(
        'input[name="int_490"]'
    ).fill(assessment)

    print("Amount of insurance = " + assessment)

    # --------------------------------
    # Market value minus land
    # --------------------------------

    applicant_page.locator(
        'input[name="int_4AE"]'
    ).fill(assessment)

    print("Market value = " + assessment)

    # --------------------------------
    # Replacement cost wanted
    # --------------------------------

    replacement_cost = (
        "Yes"
        if int(assessment) > 750000
        else "No"
    )

    replacement_dropdown = applicant_page.locator(
        'input[name*="BC_5_1-inputEl"]'
    )

    replacement_dropdown.click()

    applicant_page.wait_for_timeout(1000)

    # click visible "No" option from active dropdown
    applicant_page.locator(
        '.x-boundlist:not([style*="display: none"]) [role="option"]'
    ).filter(
        has_text=replacement_cost
    ).first.click()

    print("Replacement cost = " + replacement_cost)

    # --------------------------------
    # SECURITY DEVICES
    # --------------------------------

    applicant_page.wait_for_timeout(2000)

    # Deadbolt
    deadbolt = applicant_page.locator(
        'input[name="boolean_4EF"]'
    )

    deadbolt.scroll_into_view_if_needed()

    applicant_page.wait_for_timeout(500)

    deadbolt.click(force=True)

    print("Deadbolt checked")


    # Smoke detector
    smoke_detector = applicant_page.locator(
        'input[name="boolean_4F3"]'
    )

    smoke_detector.scroll_into_view_if_needed()

    applicant_page.wait_for_timeout(500)

    smoke_detector.click(force=True)

    print("Smoke detector checked")


    # Carbon monoxide detector
    co_detector = applicant_page.locator(
        'input[name="boolean_4FF"]'
    )

    co_detector.scroll_into_view_if_needed()

    applicant_page.wait_for_timeout(500)

    co_detector.click(force=True)

    print("Carbon monoxide detector checked")

    # --------------------------------
    # CONTINUE
    # --------------------------------

    applicant_page.get_by_role(
        "button",
        name="Continue and Save"
    ).click()

    print("Clicked Continue and Save")

    # --------------------------------
    # HANDLE UNDERWRITING POPUP
    # --------------------------------

    applicant_page.wait_for_timeout(
        2000
    )

    try:

        popup_frame = applicant_page.locator(
            'iframe[name*="dctPopup"]'
        ).content_frame

        close_button = popup_frame.get_by_role(
            "button",
            name="Close Window"
        )

        if close_button.is_visible():

            print(
                "Underwriting popup detected"
            )

            close_button.click()

            applicant_page.wait_for_timeout(
                1000
            )

            print(
                "Closed popup"
            )

    except:

        print(
            "No underwriting popup"
        )

    # --------------------------------
    # EXPORT QUOTE PDF
    # --------------------------------

    import os
    import re

    print("Opening Documents...")

    # open documents modal
    applicant_page.get_by_role(
        "button",
        name="Documents"
    ).nth(1).click()

    applicant_page.wait_for_timeout(
        3000
    )

    print("Accessing iframe...")

    frame = applicant_page.locator(
        'iframe[name*="dctPopup"]'
    ).content_frame

    applicant_page.wait_for_timeout(
        2000
    )

    print(
        "Selecting Insurance Estimate..."
    )

    # check insurance estimate
    checkbox = frame.get_by_role(
        "checkbox"
    )

    checkbox.check()

    applicant_page.wait_for_timeout(
        2000
    )

    # create folder
    os.makedirs(
        "quotes",
        exist_ok=True
    )

    safe_name = re.sub(
        r'[^a-zA-Z0-9]',
        '_',
        f"{first_name}_{last_name}"
    )

    safe_address = re.sub(
        r'[^a-zA-Z0-9]',
        '_',
        street_address
    )

    pdf_path = (
        f"quotes/"
        f"{safe_name}_"
        f"{safe_address}.pdf"
    )

    print("Downloading PDF...")

    with applicant_page.expect_download() as download_info:

        frame.get_by_role(
            "button",
            name="Print Selected"
        ).click()

    download = download_info.value

    download.save_as(
        pdf_path
    )

    print(
        f"Saved PDF: "
        f"{pdf_path}"
    )