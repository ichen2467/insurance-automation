import os
import re
import socket
import subprocess
import platform
import logging
from datetime import datetime

import pandas as pd
from playwright.sync_api import sync_playwright
from playwright.sync_api import Error as PlaywrightError

# --------------------------------
# LOGGING SETUP
# --------------------------------
# Logs to both console and a timestamped file so failed runs can be
# audited later without re-running everything.

os.makedirs("logs", exist_ok=True)
log_filename = f"logs/run_{datetime.now():%Y%m%d_%H%M%S}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("foremost")


# --------------------------------
# DEBUG BROWSER LAUNCH
# --------------------------------
# Starts a Chrome instance with remote debugging enabled so we can
# connect_over_cdp to it, instead of requiring the user to start one
# manually beforehand.
#
# Uses a dedicated profile directory (not your normal Chrome profile)
# so it won't collide with a Chrome window you already have open, and
# so you only have to log into Foremost once — the session persists
# across runs as long as this profile directory isn't deleted.

CDP_PORT = 9222
CDP_URL = f"http://localhost:{CDP_PORT}"

CHROME_DEBUG_PROFILE_DIR = r"C:\ChromeAutomation"

# Set this to override auto-detection (e.g. a portable Chrome build,
# or Chrome Beta/Canary).
CHROME_EXECUTABLE_PATH = None


def _is_cdp_available(port=CDP_PORT, timeout=1.0):
    try:
        with socket.create_connection(("localhost", port), timeout=timeout):
            return True
    except OSError:
        return False


def _find_chrome_executable():
    """Looks for a Chrome/Chromium install in the usual spots per OS."""
    system = platform.system()

    if system == "Windows":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
    elif system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
    else:  # Linux
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ]

    for path in candidates:
        if os.path.exists(path):
            return path

    raise FileNotFoundError(
        "Could not find a Chrome/Chromium install in the usual locations. "
        "Set CHROME_EXECUTABLE_PATH manually near the top of the script."
    )


def launch_debug_chrome():
    """
    Ensures a Chrome instance with remote debugging is available.
    If one is already listening on CDP_PORT, reuses it. Otherwise
    launches a new one and waits for it to come up.
    Returns the subprocess.Popen handle if we launched one, else None.
    """
    if _is_cdp_available():
        log.info(f"Chrome debug port {CDP_PORT} already open — reusing existing browser")
        return None

    chrome_path = CHROME_EXECUTABLE_PATH or _find_chrome_executable()
    os.makedirs(CHROME_DEBUG_PROFILE_DIR, exist_ok=True)

    log.info(f"Launching Chrome ({chrome_path}) with remote debugging on port {CDP_PORT}...")

    process = subprocess.Popen(
        [
            chrome_path,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={CHROME_DEBUG_PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    import time
    for _ in range(60):  # up to ~30s
        if _is_cdp_available():
            log.info("Chrome debug port is ready")
            return process
        time.sleep(0.5)

    process.terminate()
    raise RuntimeError(
        f"Chrome did not open the remote debugging port {CDP_PORT} within 30s."
    )


# --------------------------------
# DROPDOWN HELPERS
# --------------------------------

def click_with_retry(locator, attempts=3, timeout=3000, wait_between=1000, force=False, label="element"):
    """Shared retry helper for flaky dropdown/element clicks."""
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            locator.click(timeout=timeout, force=force)
            return True
        except Exception as e:
            last_error = e
            log.warning(f"Retrying click on {label} ({attempt}/{attempts})")
            locator.page.wait_for_timeout(wait_between)
    log.error(f"Failed to click {label} after {attempts} attempts: {last_error}")
    raise last_error


def select_dropdown(page, selector, option_text, attempts=3):
    """
    Selects a value from an ExtJS autocomplete dropdown and verifies
    that the selection actually changed before returning.
    """
    dropdown = page.locator(selector)

    dropdown.wait_for(state="attached", timeout=10000)
    dropdown.scroll_into_view_if_needed()

    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            # Start fresh each attempt
            click_with_retry(
                dropdown,
                attempts=1,
                label=f"{selector} (attempt {attempt})"
            )

            page.wait_for_timeout(300)

            # Clear any partial text from a previous failed attempt
            dropdown.press("Control+A")
            dropdown.press("Backspace")
            page.wait_for_timeout(100)

            if option_text.lower() == "yes":
                dropdown.press("Y")
            elif option_text.lower() == "no":
                dropdown.press("N")
            else:
                dropdown.fill(option_text)

            page.wait_for_timeout(300)
            dropdown.press("Enter")
            page.wait_for_timeout(500)

            value = dropdown.input_value().strip()

            # Success if placeholder disappeared and we have a value
            if value and value.lower() != "select":
                return

            raise Exception(f"Dropdown still shows placeholder: {value!r}")

        except Exception as e:
            last_error = e
            log.warning(
                f"Retry {attempt}/{attempts} selecting '{option_text}' for {selector}: {e}"
            )
            page.wait_for_timeout(1000)

    raise last_error

def check_checkbox(page, selector, label, attempts=3):
    checkbox = page.locator(selector)

    checkbox.wait_for(state="attached", timeout=10000)
    checkbox.scroll_into_view_if_needed()

    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            if checkbox.is_checked():
                log.info(f"{label} already checked")
                return

            checkbox.check(timeout=3000)

            if checkbox.is_checked():
                log.info(f"{label} checked")
                return

            raise Exception("Checkbox state did not change")

        except Exception as e:
            last_error = e
            log.warning(
                f"Retry {attempt}/{attempts} checking {label}: {e}"
            )
            page.wait_for_timeout(500)

    raise last_error

# --------------------------------
# ROW VALIDATION
# --------------------------------

REQUIRED_FIELDS = [
    "FirstName", "LastName", "Address", "City", "State",
    "ZIP", "YearBuilt", "SquareFeet", "PurchaseDate", "TotalAssessment",
    "Phone", "Email",
]

STATE_MAP = {
    "MD": "Maryland",
    "VA": "Virginia",
}

DEFAULT_DOB = "01/01/1985"


def get_optional_field(row, field, default=""):
    """Returns the stripped string value of an optional column, or `default`
    if the column is missing/blank for this row."""
    if field in row and not pd.isna(row[field]) and str(row[field]).strip():
        return str(row[field]).strip()
    return default


def validate_row(row):
    """Returns a list of problems with this row. Empty list = OK to process."""
    problems = []

    for field in REQUIRED_FIELDS:
        value = row.get(field)
        if pd.isna(value) or str(value).strip() == "":
            problems.append(f"missing '{field}'")

    if problems:
        # Skip numeric checks if fields are already missing
        return problems

    for field in ("ZIP", "YearBuilt", "SquareFeet", "TotalAssessment"):
        try:
            int(row[field])
        except (ValueError, TypeError):
            problems.append(f"'{field}' is not a valid number: {row[field]!r}")

    state = str(row["State"]).strip().upper()
    if state not in STATE_MAP:
        # Not fatal — we fall back to the raw code — but worth flagging
        # since the portal's dropdown almost certainly won't have a
        # matching label for an unmapped state.
        problems.append(f"state '{state}' has no entry in STATE_MAP (falling back to raw code)")

    return problems


# --------------------------------
# PER-CUSTOMER PROCESSING
# --------------------------------

def process_customer(context, row):
    """
    Runs the full quote flow for a single customer row.
    Raises on failure so the caller can log/skip and move on.
    Always closes any tabs it opened, success or failure.
    """
    first_name = str(row["FirstName"]).strip()
    last_name = str(row["LastName"]).strip()
    street_address = str(row["Address"]).strip()
    city = str(row["City"]).strip().upper()
    state = str(row["State"]).strip().upper()
    zip_code = str(int(row["ZIP"]))

    formatted_address = f"{street_address.upper()}, {city}, {state} {zip_code}"
    state_name = STATE_MAP.get(state, state)

    year_built = str(int(row["YearBuilt"]))
    square_feet = str(int(row["SquareFeet"]))
    purchase_date = str(row["PurchaseDate"]).strip()
    assessment = str(int(row["TotalAssessment"]))

    # Prefer a DOB column if present in the sheet; otherwise fall back
    # to the shared default and say so explicitly (this used to be
    # silently applied to every customer regardless of their real DOB).
    if "DOB" in row and not pd.isna(row["DOB"]) and str(row["DOB"]).strip():
        dob = str(row["DOB"]).strip()
    else:
        dob = DEFAULT_DOB
        log.warning(f"No DOB column/value for {first_name} {last_name} — using default {DEFAULT_DOB}")

    # Required columns used later in the flow (validated in validate_row).
    email = str(row["Email"]).strip()
    phone = str(row["Phone"]).strip()

    # Optional columns.
    year_roof_updated = get_optional_field(row, "YearRoofUpdated")
    auto_policy_raw = get_optional_field(row, "AutoPolicy")
    auto_policy_label = "Yes" if auto_policy_raw.lower() == "yes" else "No"

    dwelling_use_raw = get_optional_field(row, "DwellingUse").lower()
    if "landlord" in dwelling_use_raw or "rental" in dwelling_use_raw:
        dwelling_use_label = "Landlord / Rental"
    else:
        dwelling_use_label = "Primary"

    opened_pages = []

    try:
        # --------------------------------
        # START QUOTE
        # --------------------------------
        with context.expect_page() as new_page_info:
            page = [p for p in context.pages if "foremost" in (p.url or "").lower()][-1]
            page.get_by_role("button", name="Start quote").click()
        quote_page = new_page_info.value
        opened_pages.append(quote_page)
        log.info("Clicked Start Quote, switched to quote tab")

        # --------------------------------
        # QUOTE PAGE
        # --------------------------------
        quote_page.locator('[id="StartNewQuoteForm:cmbPropertyStates"]').wait_for(timeout=30000)
        log.info("Quote form loaded")

        try:
            close_window = quote_page.get_by_role("link", name="Close Window")
            if close_window.is_visible():
                log.info("Closing saved transaction popup...")
                close_window.click()
                quote_page.wait_for_timeout(1000)
        except Exception as e:
            log.debug(f"No saved-transaction popup to close: {e}")

        quote_page.locator('[id="StartNewQuoteForm:cmbPropertyStates"]').select_option(label=state_name)
        log.info(f"Selected state: {state_name}")

        quote_page.locator('[id="StartNewQuoteForm:cmbDwellingClassification"]').select_option(
            label="Traditional Site Built Home"
        )
        log.info("Selected dwelling classification")

        quote_page.locator('[id="StartNewQuoteForm:cmbDwellingUse"]').select_option(label=dwelling_use_label)
        log.info(f"Selected dwelling use: {dwelling_use_label}")

        with context.expect_page() as new_page_info:
            quote_page.get_by_role("link", name="Go").click()
        applicant_page = new_page_info.value
        opened_pages.append(applicant_page)
        log.info("Clicked Go, switched to location page")

        # --------------------------------
        # LOCATION PAGE
        # --------------------------------
        applicant_page.locator('input[fieldref="LocationInput.Address"]').first.wait_for(timeout=30000)
        log.info("Location page loaded")

        applicant_page.locator('input[fieldref="LocationInput.Address"]').first.fill(formatted_address)
        applicant_page.get_by_placeholder("YYYY", exact=True).fill(year_built)
        applicant_page.locator('input[fieldref="RiskDwellingInput.TotalSquareFootage"]').fill(square_feet)
        applicant_page.get_by_placeholder("MM/YYYY").fill(purchase_date)
        log.info("Filled address, year built, square footage, purchase date")

        applicant_page.get_by_role("button", name="Continue and Save").click()
        log.info("Clicked Continue and Save (location)")

        # --------------------------------
        # APPLICANT PAGE
        # --------------------------------
        applicant_page.locator('input[fieldref="AccountInput.Name"]').wait_for(timeout=30000)
        log.info("Applicant page loaded")

        applicant_page.locator('input[fieldref="AccountInput.Name"]').fill(first_name)
        applicant_page.locator('input[fieldref="AccountInput.LastName"]').fill(last_name)
        applicant_page.get_by_placeholder("mm/dd/yyyy").fill(dob)
        log.info("Filled name and DOB")

        select_dropdown(applicant_page, 'input[fieldref="AccountInput.IsThereASecondaryApplicant"]', "No")
        log.info("Secondary applicant = No")

        # Landlord / Rental only
        if dwelling_use_label == "Landlord / Rental":
            mailing_checkbox = applicant_page.locator('input[fieldref="AccountMailingAddressInput.SameAsLocation"]')

            mailing_checkbox.wait_for(state="attached", timeout=10000)
            mailing_checkbox.scroll_into_view_if_needed()
            applicant_page.wait_for_timeout(1000)

            if not mailing_checkbox.is_checked():
                mailing_checkbox.check()

            log.info("Mailing address checkbox checked")

        if state == "MD":
            auto_policy_dropdown = applicant_page.locator(
                'input[fieldref="DoesApplicantHaveAutoPolicyThroughYourAgency.Question"]'
            )

            auto_policy_dropdown.wait_for(state="attached", timeout=10000)
            auto_policy_dropdown.scroll_into_view_if_needed()

            # Give the page time to finish populating the mailing address fields.
            applicant_page.wait_for_timeout(1000)

            select_dropdown(
                applicant_page,
                'input[fieldref="DoesApplicantHaveAutoPolicyThroughYourAgency.Question"]',
                auto_policy_label
            )

            log.info(f"Auto policy = {auto_policy_label}")
        else:
            log.info("Auto policy question skipped")

        select_dropdown(applicant_page, 'input[fieldref="IsThePropertyCurrentlyInsured.Question"]', "Yes")
        log.info("Currently insured = Yes")
        applicant_page.wait_for_timeout(1000)

        select_dropdown(applicant_page, 'input[fieldref="AccountInput.CurrentInsuranceCarrier"]', "Other Carrier")
        applicant_page.locator('input[fieldref="AccountInput.CarrierName"]').fill("Other")
        log.info("Carrier = Other Carrier")

        select_dropdown(applicant_page, 'input[fieldref="HasAnyApplicantBeenCanceledDeclinedOrNonRenewed.Question"]', "No")
        log.info("Cancelled history = No")

        select_dropdown(applicant_page, 'input[fieldref="DoesApplicantHaveOtherPersonalLinesPolicy.Question"]', "No")
        log.info("Qualifying policy = No")

        if state == "MD":
            select_dropdown(applicant_page, 'input[fieldref="IsTheApplicantEmployeeOfFarmers.Question"]', "No")
            log.info("Farmers employee = No")
        else:
            log.info("Farmers employee question skipped")

        applicant_page.get_by_role("button", name="Continue and Save").click()
        log.info("Clicked Continue and Save (applicant)")

        # --------------------------------
        # ELIGIBILITY PAGE
        # --------------------------------
        applicant_page.wait_for_timeout(3000)
        log.info("Eligibility page loaded")

        damage_dropdown = applicant_page.locator('input[fieldref="FieldToDescribeDwellingCondition.Question"]')
        damage_dropdown.scroll_into_view_if_needed()
        applicant_page.wait_for_timeout(1000)
        click_with_retry(damage_dropdown, force=True, label="existing damage dropdown")
        applicant_page.wait_for_timeout(500)
        applicant_page.get_by_role("option", name="No").first.click()
        log.info("Existing damage = No")

        select_dropdown(applicant_page, 'input[fieldref="IsDwellingUnderConstruction.Question"]', "No")
        log.info("Construction = No")

        select_dropdown(applicant_page, 'input[fieldref="IsThereAPool.Question"]', "No")
        log.info("Swimming pool = No")

        select_dropdown(applicant_page, 'input[fieldref="IsThereATrampoline.Question"]', "No")
        log.info("Trampoline = No")

        select_dropdown(applicant_page, 'input[fieldref="IsDwellingCurrentlyVacant.Question"]', "No")
        log.info("Vacant = No")

        if state == "VA":
            select_dropdown(applicant_page, 'input[fieldref="DoesApplicantHaveAnAnimal.Question"]', "No")
            log.info("Dogs = No")
        else:
            log.info("Dogs question skipped")

        select_dropdown(applicant_page, 'input[fieldref="DoesApplicantHaveAnExoticAnimal.Question"]', "No")
        log.info("Exotic animals = No")

        # Landlord / Rental only
        if dwelling_use_label == "Landlord / Rental":
            select_dropdown(
                applicant_page,
                'input[fieldref="IsDwellingUsedForStudentHousing.Question"]',
                "No"
            )
            log.info("Student housing = No")

        select_dropdown(applicant_page, 'input[fieldref="IsThereBusinessConductedOnPremises.Question"]', "No")
        log.info("Business/Farm/Ranch = No")

        applicant_page.get_by_role("button", name="Continue and Save").click()
        log.info("Clicked Continue and Save (eligibility)")


        # --------------------------------
        # LOSSES PAGE
        # --------------------------------
        applicant_page.wait_for_timeout(5000)

        try:
            losses_dropdown = applicant_page.locator('input[placeholder="Select"]:visible')
            losses_dropdown.wait_for(timeout=30000)
            log.info("Losses page loaded")

            losses_dropdown.click()
            applicant_page.wait_for_timeout(500)
            applicant_page.get_by_role("option", name="No").first.click()
            log.info("Loss history = No")

            applicant_page.get_by_role("button", name="Continue and Save").click()
            log.info("Clicked Continue and Save (losses)")

        except PlaywrightError as e:
            if "strict mode violation" in str(e):
                log.warning(
                    "Unexpected Losses page encountered. Exiting and saving quote."
                )
                click_with_retry(
                    applicant_page.get_by_role("button", name="Exit and Save")
                )
                return None

            # Re-raise any other Playwright errors
            raise


        # --------------------------------
        # DWELLING PAGE
        # --------------------------------
        applicant_page.wait_for_timeout(3000)
        log.info("Dwelling page loaded")

        residential_dropdown = applicant_page.get_by_role(
            "row", name="Number of residential"
        ).get_by_placeholder("Select")
        residential_dropdown.click()
        applicant_page.wait_for_timeout(500)
        residential_dropdown.press("1")
        applicant_page.wait_for_timeout(300)
        residential_dropdown.press("Enter")
        log.info("Residential dwellings = 1")

        select_dropdown(applicant_page, 'input[fieldref="RiskDwellingInput.PrimaryHeatSource"]',
                         "Furnace (forced air, radiant and central air)")
        log.info("Primary heat source = Furnace")

        select_dropdown(applicant_page, 'input[fieldref="RiskDwellingInput.TypeOfFuelPrimary"]', "Natural Gas")
        log.info("Fuel type = Natural Gas")

        select_dropdown(applicant_page, 'input[fieldref="RiskDwellingInput.IsThereSecondaryHeatSource"]', "No")
        log.info("Secondary heat source = No")

        select_dropdown(applicant_page, 'input[fieldref="IsThereHeatingDeviceInGarageOrOtherStructure.Question"]', "No")
        log.info("Garage heating device = No")

        select_dropdown(applicant_page, 'input[fieldref="IsRowHouseOrTownHouse.Question"]', "No")
        log.info("Townhouse = No") 

        if state == "VA":
            select_dropdown(applicant_page, 'input[fieldref="RiskDwellingInput.HasDwellingsElectricalPlumbingOrHeatingBeenUpgraded"]', "No")
            log.info("Electrical/plumbing/heating updated = No")
        else:
            log.info("Electrical/plumbing/heating question skipped")

        if dwelling_use_label != "Landlord / Rental":
            if year_roof_updated:
                select_dropdown(applicant_page, 'input[fieldref="RiskDwellingInput.HasRoofOfDwellingBeenUpdated"]', "Yes")
                log.info("Roof updated = Yes")
                applicant_page.wait_for_timeout(500)
                applicant_page.get_by_placeholder("YYYY").fill(year_roof_updated)
                log.info(f"Year roof updated = {year_roof_updated}")
            else:
                select_dropdown(applicant_page, 'input[fieldref="RiskDwellingInput.HasRoofOfDwellingBeenUpdated"]', "No")
                log.info("Roof updated = No")
        else:
            log.info("Roof updated question skipped (Landlord / Rental)")

        capped_assessment = assessment
        if int(assessment) > 1_000_000:
            capped_assessment = "1000000"
            log.warning(
                f"Assessment {assessment} exceeds cap for {first_name} {last_name} "
                f"— capped to {capped_assessment}"
            )

        applicant_page.locator('input[fieldref="RiskInput.AmountOfInsurance""]').fill(capped_assessment)
        log.info(f"Amount of insurance = {capped_assessment}")

        applicant_page.locator('input[fieldref="RiskDwellingInput.CurrentMarketValueMinusLandValue"]').fill(capped_assessment)
        log.info(f"Market value = {capped_assessment}")

        replacement_cost = "Yes" if int(capped_assessment) > 750_000 else "No"

        replacement_dropdown = applicant_page.locator(
            'input[fieldref="RiskDwellingInput.DoesApplicantWantReplacementCost"]'
        )

        replacement_dropdown.scroll_into_view_if_needed()

        click_with_retry(
            replacement_dropdown,
            label="replacement cost dropdown"
        )

        option = applicant_page.get_by_role(
            "option",
            name=replacement_cost
        ).first

        option.wait_for(state="visible", timeout=10000)
        option.click()

        log.info(f"Replacement cost = {replacement_cost}")

        # --------------------------------
        # SECURITY DEVICES
        # --------------------------------
        applicant_page.wait_for_timeout(2000)

        check_checkbox(
            applicant_page,
            'input[fieldref="RiskInput.Deadbolt"]',
            "Deadbolt"
        )

        check_checkbox(
            applicant_page,
            'input[fieldref="RiskInput.SmokeDetector"]',
            "Smoke detector"
        )

        check_checkbox(
            applicant_page,
            'input[fieldref="RiskInput.CarbonMonoxideDetector"]',
            "Carbon monoxide detector"
        )

        # Landlord / Rental only
        if dwelling_use_label == "Landlord / Rental":

            # Number of Foremost-insured properties
            applicant_page.locator('input[fieldref="RiskDwellingInput.NumberOfRentalAndVacantSiteBuiltProperties"]').fill("1")
            log.info("Number of Foremost insured properties = 1")

            # Managed by management company
            try:
                select_dropdown(
                    applicant_page,
                    'input[fieldref="RiskDwellingInput.IsPropertyManagedByManagementCompany"]',
                    "No"
                )
                print("Management company = No")
            except Exception:
                print("Management company question not present, skipping")
            
            # Landlord association
            select_dropdown(
                applicant_page,
                'input[fieldref="RiskDwellingInput.DoesTheApplicantBelongToLandlordAssc"]',
                "No"
            )   
            log.info("Landlord association = No")

            # Authorization checkboxes
            check_checkbox(
                applicant_page,
                'input[fieldref="RiskDwellingInput.CreditCheck"]',
                "Credit check"
            )

            check_checkbox(
                applicant_page,
                'input[fieldref="RiskDwellingInput.CriminalBackgroundCheck"]',
                "Criminal background check"
            )

            check_checkbox(
                applicant_page,
                'input[fieldref="RiskDwellingInput.EvictionSearch"]',
                "Eviction search"
            )

        applicant_page.get_by_role("button", name="Continue and Save").click()
        log.info("Clicked Continue and Save (dwelling)")

        # --------------------------------
        # UNDERWRITING POPUP
        # --------------------------------
        applicant_page.wait_for_timeout(2000)
        try:
            popup_frame = applicant_page.locator('iframe[name*="dctPopup"]').content_frame
            close_button = popup_frame.get_by_role("button", name="Close Window")
            if close_button.is_visible():
                log.info("Underwriting popup detected — closing")
                close_button.click()
                applicant_page.wait_for_timeout(1000)
        except Exception as e:
            log.debug(f"No underwriting popup: {e}")

        # --------------------------------
        # EXPORT QUOTE PDF
        # --------------------------------
        log.info("Opening Documents...")
        applicant_page.get_by_role("button", name="Documents").nth(1).click()
        applicant_page.wait_for_timeout(3000)

        frame = applicant_page.locator('iframe[name*="dctPopup"]').content_frame
        applicant_page.wait_for_timeout(2000)

        log.info("Selecting Insurance Estimate...")
        checkbox = frame.get_by_role("checkbox")
        checkbox.check()
        applicant_page.wait_for_timeout(2000)

        os.makedirs("quotes", exist_ok=True)
        safe_name = re.sub(r'[^a-zA-Z0-9]', '_', f"{first_name}_{last_name}")
        safe_address = re.sub(r'[^a-zA-Z0-9]', '_', street_address)
        pdf_path = f"quotes/{safe_name}_{safe_address}.pdf"

        log.info("Downloading PDF...")
        with applicant_page.expect_download() as download_info:
            frame.get_by_role("button", name="Print Selected").click()
        download = download_info.value
        download.save_as(pdf_path)
        log.info(f"Saved PDF: {pdf_path}")

        # --------------------------------
        # CLOSE DOCUMENTS POPUP
        # --------------------------------
        applicant_page.wait_for_timeout(1000)
        try:
            docs_popup_frame = applicant_page.locator('iframe[name*="dctPopup"]').content_frame
            docs_close_button = docs_popup_frame.get_by_role("button", name="Close Window")
            docs_close_button.click()
            log.info("Closed documents popup")
        except Exception as e:
            log.warning(f"Could not close documents popup: {e}")
        applicant_page.wait_for_timeout(1000)

        # --------------------------------
        # CONTINUE AND SAVE (post-documents)
        # --------------------------------
        applicant_page.get_by_role("button", name="Continue and Save").click()
        log.info("Clicked Continue and Save (post-documents)")
        applicant_page.wait_for_timeout(2000)

        # --------------------------------
        # OPTIONAL UNDERWRITING PAGE
        # --------------------------------
        # Sometimes the flow lands on an Underwriting page before
        # Additional Information. If the phone field for Additional
        # Information isn't showing up yet, assume we're on the
        # Underwriting page and click through it.
        phone_locator = applicant_page.locator('input[fieldref="AccountInput.PrimaryPhone"]')
        try:
            phone_locator.wait_for(timeout=5000)
        except Exception:
            log.info("Additional Information page not visible yet — checking for Underwriting page")
            try:
                applicant_page.get_by_role("button", name="Continue and Save").click()
                log.info("Clicked Continue and Save (underwriting)")
                applicant_page.wait_for_timeout(2000)
                phone_locator.wait_for(timeout=15000)
            except Exception as e:
                log.warning(f"Could not confirm Additional Information page loaded: {e}")

        # --------------------------------
        # ADDITIONAL INFORMATION PAGE
        # --------------------------------
        log.info("Additional Information page loaded")

        phone_locator.fill(phone)
        log.info(f"Phone = {phone}")

        applicant_page.locator('input[fieldref="AccountInput.Email"]').fill(email)
        log.info(f"Email = {email}")

        select_dropdown(applicant_page, 'input[fieldref="AccountMailingAddressInput.DoesApplicantHaveTempOrSeasonalAddress"]', "No")
        log.info("Seasonal mailing address = No")

        select_dropdown(applicant_page, 'input[fieldref="RiskInput.IsThereAnAdditionalInterest"]', "No")
        log.info("Additional interest = No")

        applicant_page.get_by_role("button", name="Continue and Save").click()
        log.info("Clicked Continue and Save (additional information) — flow complete")
        applicant_page.wait_for_timeout(2000)

        return pdf_path

    finally:
        pass
        # Always clean up any tabs this customer opened, whether we
        # succeeded or blew up partway through.
        # for p in opened_pages:
        #    try:
        #        if not p.is_closed():
        #            p.close()
        #    except Exception as e:
        #        log.debug(f"Could not close tab: {e}")


# --------------------------------
# LOAD CUSTOMER DATA
# --------------------------------

df = pd.read_excel("customers.xlsx")
df = df.dropna(how="all")

# --------------------------------
# PLAYWRIGHT
# --------------------------------

successes = []
failures = []
skipped = []

chrome_process = launch_debug_chrome()

with sync_playwright() as p:
    log.info("Connecting to browser...")
    browser = p.chromium.connect_over_cdp(CDP_URL)

    log.info("Opening Foremost...")
    context = browser.contexts[0]
    page = context.new_page()
    page.goto("https://www.foremostagent.com/ia/portal/login", timeout=60000)
    page.wait_for_timeout(2000)

    for _ in range(2):
        try:
            continue_button = page.get_by_role("button", name="Continue")
            if continue_button.is_visible():
                log.info("Clicking Continue...")
                continue_button.click()
                page.wait_for_timeout(2000)
        except Exception as e:
            log.debug(f"No Continue button: {e}")
            break

    log.info("Foremost opened. Connected!")

    context = browser.contexts[0]
    page = None
    for tab in context.pages:
        try:
            if "foremost" in (tab.url or "").lower():
                page = tab
                break
        except Exception:
            pass

    if page is None:
        log.error("Foremost tab not found — aborting")
        raise SystemExit(1)

    # --------------------------------
    # PER-CUSTOMER LOOP
    # --------------------------------
    for index, row in df.iterrows():
        customer_label = f"{row.get('FirstName', '?')} {row.get('LastName', '?')} (row {index})"
        log.info(f"--- Starting customer {index + 1} of {len(df)}: {customer_label} ---")

        problems = validate_row(row)
        # Only *missing field* problems are fatal; an unmapped state is
        # a warning (see validate_row) but we still attempt the row.
        fatal_problems = [p for p in problems if "has no entry in STATE_MAP" not in p]
        if fatal_problems:
            log.error(f"Skipping {customer_label} — {'; '.join(fatal_problems)}")
            skipped.append((customer_label, "; ".join(fatal_problems)))
            continue
        for p_msg in problems:
            if "has no entry in STATE_MAP" in p_msg:
                log.warning(f"{customer_label}: {p_msg}")

        try:
            pdf_path = process_customer(context, row)
            successes.append((customer_label, pdf_path))
        except Exception as e:
            log.error(f"Failed on {customer_label}: {e}", exc_info=True)
            failures.append((customer_label, str(e)))
            continue

    # --------------------------------
    # RUN SUMMARY
    # --------------------------------
    log.info("=" * 60)
    log.info(f"RUN COMPLETE: {len(successes)} succeeded, {len(failures)} failed, {len(skipped)} skipped")

    if successes:
        log.info("Succeeded:")
        for name, path in successes:
            log.info(f"  ✓ {name} -> {path}")

    if skipped:
        log.info("Skipped (bad data):")
        for name, reason in skipped:
            log.info(f"  - {name}: {reason}")

    if failures:
        log.info("Failed (needs manual follow-up):")
        for name, reason in failures:
            log.info(f"  X {name}: {reason}")

    log.info(f"Full log written to {log_filename}")
    log.info("Leaving browser windows open for review.")

    # --------------------------------
    # CLOSE ALL WINDOWS
    # --------------------------------
    # Commented out so windows stay open for review after each run.
    # Uncomment this block to have the script close everything when done.
    #
    # log.info("Closing all browser windows...")
    #
    # try:
    #     # Close all Playwright browser contexts/tabs
    #     browser.close()
    #     log.info("Playwright browser closed")
    # except Exception as e:
    #     log.warning(f"Error closing browser: {e}")
    #
    # # If this script launched Chrome, terminate it too
    # if chrome_process:
    #     try:
    #         log.info("Terminating Chrome process...")
    #         chrome_process.terminate()
    #         chrome_process.wait(timeout=10)
    #         log.info("Chrome process terminated")
    #     except Exception as e:
    #         log.warning(f"Could not terminate Chrome process: {e}")
    #         try:
    #             chrome_process.kill()
    #             log.info("Chrome process killed")
    #         except Exception as kill_error:
    #             log.warning(f"Could not kill Chrome process: {kill_error}")