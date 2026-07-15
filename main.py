import os
import re
import socket
import subprocess
import platform
import logging
from datetime import datetime

import pandas as pd
from playwright.sync_api import sync_playwright

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


def select_dropdown(page, selector, option_text):
    dropdown = page.locator(selector)
    click_with_retry(dropdown, label=selector)

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
# ROW VALIDATION
# --------------------------------

REQUIRED_FIELDS = [
    "FirstName", "LastName", "Address", "City", "State",
    "ZIP", "YearBuilt", "SquareFeet", "PurchaseDate", "TotalAssessment",
]

STATE_MAP = {
    "MD": "Maryland",
    "VA": "Virginia",
}

DEFAULT_DOB = "01/01/1985"


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

        quote_page.locator('[id="StartNewQuoteForm:cmbDwellingUse"]').select_option(label="Primary")
        log.info("Selected dwelling use")

        with context.expect_page() as new_page_info:
            quote_page.get_by_role("link", name="Go").click()
        applicant_page = new_page_info.value
        opened_pages.append(applicant_page)
        log.info("Clicked Go, switched to location page")

        # --------------------------------
        # LOCATION PAGE
        # --------------------------------
        applicant_page.locator('input[name="string_662|spvalidation"]').wait_for(timeout=30000)
        log.info("Location page loaded")

        applicant_page.locator('input[name="string_662|spvalidation"]').fill(formatted_address)
        applicant_page.get_by_placeholder("YYYY", exact=True).fill(year_built)
        applicant_page.locator('input[name="int_733"]').fill(square_feet)
        applicant_page.get_by_placeholder("MM/YYYY").fill(purchase_date)
        log.info("Filled address, year built, square footage, purchase date")

        applicant_page.get_by_role("button", name="Continue and Save").click()
        log.info("Clicked Continue and Save (location)")

        # --------------------------------
        # APPLICANT PAGE
        # --------------------------------
        applicant_page.locator('input[name="string_1ED8|spvalidation"]').wait_for(timeout=30000)
        log.info("Applicant page loaded")

        applicant_page.locator('input[name="string_1ED8|spvalidation"]').fill(first_name)
        applicant_page.locator('input[name="string_1EE5|spvalidation"]').fill(last_name)
        applicant_page.get_by_placeholder("mm/dd/yyyy").fill(dob)
        log.info("Filled name and DOB")

        select_dropdown(applicant_page, 'input[name*="1F5C_5_1-inputEl"]', "No")
        log.info("Secondary applicant = No")

        if state == "MD":
            select_dropdown(applicant_page, 'input[name*="20EE_5_1-inputEl"]', "No")
            log.info("Auto policy = No")
        else:
            log.info("Auto policy question skipped")

        select_dropdown(applicant_page, 'input[name*="2124_5_1-inputEl"]', "Yes")
        log.info("Currently insured = Yes")
        applicant_page.wait_for_timeout(1000)

        select_dropdown(applicant_page, 'input[name*="2140_5_1-inputEl"]', "Other Carrier")
        applicant_page.locator('input[name*="214A"]').fill("Other")
        log.info("Carrier = Other Carrier")

        select_dropdown(applicant_page, 'input[name*="2153_5_1-inputEl"]', "No")
        log.info("Cancelled history = No")

        select_dropdown(applicant_page, 'input[name*="216E_5_1-inputEl"]', "No")
        log.info("Qualifying policy = No")

        if state == "MD":
            select_dropdown(applicant_page, 'input[name*="2177_5_1-inputEl"]', "No")
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

        damage_dropdown = applicant_page.locator('input[name*="64_5_1-inputEl"]')
        damage_dropdown.scroll_into_view_if_needed()
        applicant_page.wait_for_timeout(1000)
        click_with_retry(damage_dropdown, force=True, label="existing damage dropdown")
        applicant_page.wait_for_timeout(500)
        applicant_page.get_by_role("option", name="No").first.click()
        log.info("Existing damage = No")

        select_dropdown(applicant_page, 'input[name*="B5_5_1-inputEl"]', "No")
        log.info("Construction = No")

        select_dropdown(applicant_page, 'input[name*="36_5_1-inputEl"]', "No")
        log.info("Swimming pool = No")

        select_dropdown(applicant_page, 'input[name*="4A_5_1-inputEl"]', "No")
        log.info("Trampoline = No")

        select_dropdown(applicant_page, 'input[name*="75_5_1-inputEl"]', "No")
        log.info("Vacant = No")

        if state == "VA":
            select_dropdown(applicant_page, 'input[name*="7F_5_1-inputEl"]', "No")
            log.info("Dogs = No")
        else:
            log.info("Dogs question skipped")

        select_dropdown(applicant_page, 'input[name*="DA_5_1-inputEl"]', "No")
        log.info("Exotic animals = No")

        select_dropdown(applicant_page, 'input[name*="6B_5_1-inputEl"]', "No")
        log.info("Business/Farm/Ranch = No")

        applicant_page.get_by_role("button", name="Continue and Save").click()
        log.info("Clicked Continue and Save (eligibility)")

        # --------------------------------
        # LOSSES PAGE
        # --------------------------------
        applicant_page.wait_for_timeout(5000)

        losses_dropdown = applicant_page.locator('input[placeholder="Select"]:visible')
        losses_dropdown.wait_for(timeout=30000)
        log.info("Losses page loaded")

        losses_dropdown.click()
        applicant_page.wait_for_timeout(500)
        applicant_page.get_by_role("option", name="No").first.click()
        log.info("Loss history = No")

        applicant_page.get_by_role("button", name="Continue and Save").click()
        log.info("Clicked Continue and Save (losses)")

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

        select_dropdown(applicant_page, 'input[name*="4C_5_1-inputEl"]',
                         "Furnace (forced air, radiant and central air)")
        log.info("Primary heat source = Furnace")

        select_dropdown(applicant_page, 'input[name*="61_5_1-inputEl"]', "Natural Gas")
        log.info("Fuel type = Natural Gas")

        select_dropdown(applicant_page, 'input[name*="74_5_1-inputEl"]', "No")
        log.info("Secondary heat source = No")

        select_dropdown(applicant_page, 'input[name*="A9_5_1-inputEl"]', "No")
        log.info("Garage heating device = No")

        select_dropdown(applicant_page, 'input[name*="24_5_1-inputEl"]', "No")
        log.info("Townhouse = No")

        if state == "VA":
            select_dropdown(applicant_page, 'input[name*="3E_5_1-inputEl"]', "No")
            log.info("Electrical/plumbing/heating updated = No")
        else:
            log.info("Electrical/plumbing/heating question skipped")

        select_dropdown(applicant_page, 'input[name*="78_5_1-inputEl"]', "No")
        log.info("Roof updated = No")

        capped_assessment = assessment
        if int(assessment) > 1_000_000:
            capped_assessment = "1000000"
            log.warning(
                f"Assessment {assessment} exceeds cap for {first_name} {last_name} "
                f"— capped to {capped_assessment}"
            )

        applicant_page.locator('input[name="int_490"]').fill(capped_assessment)
        log.info(f"Amount of insurance = {capped_assessment}")

        applicant_page.locator('input[name="int_4AE"]').fill(capped_assessment)
        log.info(f"Market value = {capped_assessment}")

        replacement_cost = "Yes" if int(capped_assessment) > 750_000 else "No"

        replacement_dropdown = applicant_page.locator('input[name*="BC_5_1-inputEl"]')
        replacement_dropdown.scroll_into_view_if_needed()
        replacement_dropdown.click()
        applicant_page.wait_for_timeout(1000)
        replacement_dropdown.click()
        applicant_page.wait_for_timeout(500)

        applicant_page.locator(
            '.x-boundlist:not([style*="display: none"]) [role="option"]'
        ).filter(has_text=replacement_cost).first.click()
        log.info(f"Replacement cost = {replacement_cost}")

        # --------------------------------
        # SECURITY DEVICES
        # --------------------------------
        applicant_page.wait_for_timeout(2000)

        for name, label in (
            ("boolean_4EF", "Deadbolt"),
            ("boolean_4F3", "Smoke detector"),
            ("boolean_4FF", "Carbon monoxide detector"),
        ):
            checkbox = applicant_page.locator(f'input[name="{name}"]')
            checkbox.scroll_into_view_if_needed()
            applicant_page.wait_for_timeout(500)
            checkbox.click(force=True)
            log.info(f"{label} checked")

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

        return pdf_path

    finally:
        # Always clean up any tabs this customer opened, whether we
        # succeeded or blew up partway through.
        for p in opened_pages:
            try:
                if not p.is_closed():
                    p.close()
            except Exception as e:
                log.debug(f"Could not close tab: {e}")


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
            log.info(f"  ✗ {name}: {reason}")

    log.info(f"Full log written to {log_filename}")

    # --------------------------------
    # CLOSE ALL WINDOWS
    # --------------------------------
    log.info("Closing all browser windows...")

    try:
        # Close all Playwright browser contexts/tabs
        browser.close()
        log.info("Playwright browser closed")
    except Exception as e:
        log.warning(f"Error closing browser: {e}")

    # If this script launched Chrome, terminate it too
    if chrome_process:
        try:
            log.info("Terminating Chrome process...")
            chrome_process.terminate()
            chrome_process.wait(timeout=10)
            log.info("Chrome process terminated")
        except Exception as e:
            log.warning(f"Could not terminate Chrome process: {e}")
            try:
                chrome_process.kill()
                log.info("Chrome process killed")
            except Exception as kill_error:
                log.warning(f"Could not kill Chrome process: {kill_error}")