import os
import logging
from datetime import datetime

import pandas as pd

from playwright.sync_api import sync_playwright

from app.automation.foremost import (
    CDP_URL,
    launch_debug_chrome,
    process_customer,
)


# --------------------------------
# LOGGING SETUP
# --------------------------------

os.makedirs(
    "logs",
    exist_ok=True,
)

log_filename = (
    f"logs/run_{datetime.now():%Y%m%d_%H%M%S}.log"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(
            log_filename
        ),
        logging.StreamHandler(),
    ],
)

log = logging.getLogger(
    "foremost"
)


# --------------------------------
# CUSTOMER DATA CONSTANTS
# --------------------------------

REQUIRED_FIELDS = [
    "FirstName",
    "LastName",
    "Address",
    "City",
    "State",
    "ZIP",
    "YearBuilt",
    "SquareFeet",
    "PurchaseDate",
    "TotalAssessment",
    "Phone",
    "Email",
]


STATE_MAP = {
    "MD": "Maryland",
    "VA": "Virginia",
}


DEFAULT_DOB = "01/01/1985"


# --------------------------------
# SPREADSHEET HELPERS
# --------------------------------

def get_optional_field(
    row,
    field,
    default="",
):
    """
    Returns the stripped string value
    of an optional column.

    Returns the default value if the
    column is missing or blank.
    """

    if (
        field in row
        and not pd.isna(row[field])
        and str(row[field]).strip()
    ):
        return str(
            row[field]
        ).strip()

    return default


def validate_row(row):
    """
    Returns a list of problems with
    this row.

    An empty list means the row is
    ready to process.
    """

    problems = []

    # --------------------------------
    # REQUIRED FIELDS
    # --------------------------------

    for field in REQUIRED_FIELDS:

        value = row.get(field)

        if (
            pd.isna(value)
            or str(value).strip() == ""
        ):
            problems.append(
                f"missing '{field}'"
            )

    # If required fields are missing,
    # don't try to validate their types.

    if problems:
        return problems

    # --------------------------------
    # NUMERIC FIELDS
    # --------------------------------

    for field in (
        "ZIP",
        "YearBuilt",
        "SquareFeet",
        "TotalAssessment",
    ):

        try:
            int(row[field])

        except (
            ValueError,
            TypeError,
        ):

            problems.append(
                f"'{field}' is not "
                f"a valid number: "
                f"{row[field]!r}"
            )

    # --------------------------------
    # STATE VALIDATION
    # --------------------------------

    state = str(
        row["State"]
    ).strip().upper()

    if state not in STATE_MAP:

        problems.append(
            f"state '{state}' has no "
            f"entry in STATE_MAP "
            f"(falling back to raw code)"
        )

    return problems


# --------------------------------
# MAIN APPLICATION
# --------------------------------

def main():

    # --------------------------------
    # LOAD CUSTOMER DATA
    # --------------------------------

    log.info(
        "Loading customers.xlsx..."
    )

    df = pd.read_excel(
        "customers.xlsx"
    )

    df = df.dropna(
        how="all"
    )

    log.info(
        f"Loaded {len(df)} customer row(s)"
    )

    # --------------------------------
    # RUN RESULTS
    # --------------------------------

    successes = []

    failures = []

    skipped = []

    # --------------------------------
    # LAUNCH / CONNECT TO CHROME
    # --------------------------------

    chrome_process = (
        launch_debug_chrome()
    )

    # --------------------------------
    # PLAYWRIGHT
    # --------------------------------

    with sync_playwright() as p:

        log.info(
            "Connecting to browser..."
        )

        browser = (
            p.chromium.connect_over_cdp(
                CDP_URL
            )
        )

        log.info(
            "Opening Foremost..."
        )

        context = (
            browser.contexts[0]
        )

        page = context.new_page()

        page.goto(
            "https://www.foremostagent.com/ia/portal/login",
            timeout=60000,
        )

        page.wait_for_timeout(
            2000
        )

        # --------------------------------
        # CONTINUE BUTTON
        # --------------------------------

        for _ in range(2):

            try:

                continue_button = (
                    page.get_by_role(
                        "button",
                        name="Continue",
                    )
                )

                if (
                    continue_button.is_visible()
                ):

                    log.info(
                        "Clicking Continue..."
                    )

                    continue_button.click()

                    page.wait_for_timeout(
                        2000
                    )

            except Exception as e:

                log.debug(
                    f"No Continue button: {e}"
                )

                break

        log.info(
            "Foremost opened. Connected!"
        )

        # --------------------------------
        # FIND FOREMOST TAB
        # --------------------------------

        page = None

        for tab in context.pages:

            try:

                if (
                    "foremost"
                    in (tab.url or "").lower()
                ):

                    page = tab

                    break

            except Exception:
                pass

        if page is None:

            log.error(
                "Foremost tab not found "
                "— aborting"
            )

            raise SystemExit(1)

        # --------------------------------
        # PER-CUSTOMER LOOP
        # --------------------------------

        for index, row in df.iterrows():

            customer_label = (
                f"{row.get('FirstName', '?')} "
                f"{row.get('LastName', '?')} "
                f"(row {index})"
            )

            log.info(
                f"--- Starting customer "
                f"{index + 1} of {len(df)}: "
                f"{customer_label} ---"
            )

            problems = (
                validate_row(row)
            )

            # An unmapped state is only
            # a warning, not a fatal error.

            fatal_problems = [
                problem
                for problem in problems
                if (
                    "has no entry in STATE_MAP"
                    not in problem
                )
            ]

            if fatal_problems:

                log.error(
                    f"Skipping {customer_label} "
                    f"— "
                    f"{'; '.join(fatal_problems)}"
                )

                skipped.append(
                    (
                        customer_label,
                        "; ".join(
                            fatal_problems
                        ),
                    )
                )

                continue

            # Log state warnings but
            # continue processing.

            for problem in problems:

                if (
                    "has no entry in STATE_MAP"
                    in problem
                ):

                    log.warning(
                        f"{customer_label}: "
                        f"{problem}"
                    )

            # --------------------------------
            # PROCESS CUSTOMER
            # --------------------------------

            try:

                pdf_path = (
                    process_customer(
                        context=context,
                        row=row,
                        state_map=STATE_MAP,
                        default_dob=DEFAULT_DOB,
                        get_optional_field=get_optional_field,
                    )
                )

                successes.append(
                    (
                        customer_label,
                        pdf_path,
                    )
                )

            except Exception as e:

                log.error(
                    f"Failed on "
                    f"{customer_label}: {e}",
                    exc_info=True,
                )

                failures.append(
                    (
                        customer_label,
                        str(e),
                    )
                )

                continue

        # --------------------------------
        # RUN SUMMARY
        # --------------------------------

        log.info(
            "=" * 60
        )

        log.info(
            f"RUN COMPLETE: "
            f"{len(successes)} succeeded, "
            f"{len(failures)} failed, "
            f"{len(skipped)} skipped"
        )

        # --------------------------------
        # SUCCEEDED
        # --------------------------------

        if successes:

            log.info(
                "Succeeded:"
            )

            for name, path in successes:

                log.info(
                    f"  OK: {name} -> {path}"
                )

        # --------------------------------
        # SKIPPED
        # --------------------------------

        if skipped:

            log.info(
                "Skipped (bad data):"
            )

            for name, reason in skipped:

                log.info(
                    f"  - {name}: {reason}"
                )

        # --------------------------------
        # FAILED
        # --------------------------------

        if failures:

            log.info(
                "Failed "
                "(needs manual follow-up):"
            )

            for name, reason in failures:

                log.info(
                    f"  X {name}: {reason}"
                )

        log.info(
            f"Full log written to "
            f"{log_filename}"
        )

        log.info(
            "Leaving browser windows "
            "open for review."
        )

        # --------------------------------
        # OPTIONAL BROWSER CLEANUP
        # --------------------------------

        # Leave this commented out for now
        # so you can inspect the browser
        # after a run.

        #
        # log.info(
        #     "Closing all browser windows..."
        # )
        #
        # try:
        #
        #     browser.close()
        #
        #     log.info(
        #         "Playwright browser closed"
        #     )
        #
        # except Exception as e:
        #
        #     log.warning(
        #         f"Error closing browser: {e}"
        #     )
        #
        #
        # if chrome_process:
        #
        #     try:
        #
        #         log.info(
        #             "Terminating Chrome process..."
        #         )
        #
        #         chrome_process.terminate()
        #
        #         chrome_process.wait(
        #             timeout=10
        #         )
        #
        #         log.info(
        #             "Chrome process terminated"
        #         )
        #
        #     except Exception as e:
        #
        #         log.warning(
        #             f"Could not terminate "
        #             f"Chrome process: {e}"
        #         )
        #
        #         try:
        #
        #             chrome_process.kill()
        #
        #             log.info(
        #                 "Chrome process killed"
        #             )
        #
        #         except Exception as kill_error:
        #
        #             log.warning(
        #                 f"Could not kill "
        #                 f"Chrome process: "
        #                 f"{kill_error}"
        #             )


if __name__ == "__main__":
    main()