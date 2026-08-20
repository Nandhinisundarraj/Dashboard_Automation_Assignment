"""
automation.py
--------------
All Selenium logic for driving the OrangeHRM demo site lives here.
The Flask app (app.py) calls run_automation() with the values the
user typed into the dashboard form. Nothing here is hardcoded --
every credential / employee field is passed in as a function argument.
"""

import csv
import logging
import os
import time
from datetime import datetime

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BASE_URL = "https://opensource-demo.orangehrmlive.com"
LOGIN_URL = f"{BASE_URL}/web/index.php/auth/login"

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging: one timestamped log file per automation run, plus console output.
# ---------------------------------------------------------------------------
def get_logger():
    logger = logging.getLogger("orangehrm_automation")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"run_{timestamp}.log")

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger, log_file


def build_driver(headless: bool = True):
    """Create a Chrome WebDriver instance.

    Uses Selenium's built-in Selenium Manager (bundled since Selenium 4.6+)
    instead of webdriver_manager. Selenium Manager automatically detects
    the installed Chrome version and fetches a matching driver, avoiding
    the stale/mismatched-driver crashes that webdriver_manager's cache
    can cause.
    """
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1400,1000")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # No Service(...) / ChromeDriverManager needed - Selenium Manager
    # resolves the correct driver automatically.
    return webdriver.Chrome(options=options)


def safe_click(driver, wait, locator, logger=None):
    """
    Click an element robustly, working around OrangeHRM's loading
    spinner (oxd-form-loader) intermittently covering buttons right
    after a page action, which causes ElementClickInterceptedException.
    """
    # If a loading overlay is present, wait for it to disappear first.
    try:
        WebDriverWait(driver, 10).until(
            EC.invisibility_of_element_located(
                (By.CLASS_NAME, "oxd-form-loader")))
    except TimeoutException:
        pass  # no loader present, or it didn't clear in time - continue anyway

    element = wait.until(EC.element_to_be_clickable(locator))
    try:
        element.click()
    except ElementClickInterceptedException:
        if logger:
            logger.warning(
                "Click intercepted (likely a loading overlay) - "
                "retrying with a JS click")
        driver.execute_script("arguments[0].click();", element)
    return element


def run_automation(username: str, password: str, first_name: str,
                    last_name: str, employee_id: str, headless: bool = True):
    """
    Runs the full OrangeHRM flow:
      login -> PIM -> Add Employee -> verify -> extract list -> logout

    Returns a dict the Flask route can hand straight to the template:
      {
        "success": bool,
        "message": str,
        "employee_added": {...} or None,
        "employee_table": [...] ,
        "log_file": str,
        "csv_file": str or None,
      }
    """
    logger, log_file = get_logger()
    result = {
        "success": False,
        "message": "",
        "employee_added": None,
        "employee_table": [],
        "log_file": os.path.basename(log_file),
        "csv_file": None,
    }

    driver = None
    try:
        logger.info("Starting automation run")
        driver = build_driver(headless=headless)
        wait = WebDriverWait(driver, 20)  # balances reliability vs. speed

        # ---------------- Step 1: Open site ----------------
        logger.info("Opening OrangeHRM login page")
        driver.get(LOGIN_URL)

        # ---------------- Step 2: Login ----------------
        logger.info("Logging in as user '%s'", username)

        def attempt_login():
            driver.get(LOGIN_URL)
            u = wait.until(EC.presence_of_element_located((By.NAME, "username")))
            p = wait.until(EC.presence_of_element_located((By.NAME, "password")))
            u.clear()
            u.send_keys(username)
            p.clear()
            p.send_keys(password)
            safe_click(driver, wait, (By.XPATH, "//button[@type='submit']"), logger)
            time.sleep(2)  # let the post-login redirect settle

        attempt_login()

        # Confirm login succeeded. Check the URL first - if we've
        # already navigated to /dashboard/, login genuinely worked even
        # if the heading element is slow to render (its widgets load
        # asynchronously and can lag well behind the URL change). Only
        # fall back to retrying the form submission if we're still
        # stuck on the login page itself, to avoid resubmitting the
        # form while a real navigation is already in flight.
        login_ok = False
        for attempt in (1, 2):
            try:
                wait.until(EC.presence_of_element_located(
                    (By.XPATH, "//h6[text()='Dashboard']")))
                logger.info("Login successful")
                login_ok = True
                break
            except TimeoutException:
                if "dashboard" in driver.current_url.lower():
                    logger.info(
                        "Dashboard heading was slow to render, but the "
                        "URL confirms login succeeded - continuing.")
                    login_ok = True
                    break

                error_text = None
                try:
                    error_el = driver.find_element(
                        By.XPATH,
                        "//p[contains(@class,'oxd-alert-content-text')]")
                    error_text = error_el.text.strip()
                except NoSuchElementException:
                    pass

                if error_text:
                    # A real "Invalid credentials" style message - no
                    # point retrying, the credentials themselves are wrong.
                    screenshot_path = os.path.join(LOG_DIR, "login_failure.png")
                    try:
                        time.sleep(1)
                        driver.save_screenshot(screenshot_path)
                    except WebDriverException:
                        pass
                    raise RuntimeError(f"Login failed - site said: '{error_text}'")

                if attempt == 1:
                    logger.warning(
                        "Still on the login page after waiting (attempt "
                        "1) - site may be slow. Retrying login once...")
                    attempt_login()
                else:
                    screenshot_path = os.path.join(LOG_DIR, "login_failure.png")
                    try:
                        time.sleep(1)
                        driver.save_screenshot(screenshot_path)
                        logger.info("Saved failure screenshot to %s", screenshot_path)
                    except WebDriverException:
                        pass
                    raise RuntimeError(
                        "Login failed after two attempts - still stuck on "
                        "the login page with no error banner either time. "
                        "The demo site may be slow/overloaded right now, "
                        f"or its page markup has changed. See "
                        f"login_failure.png in {LOG_DIR}."
                    )

        # ---------------- Step 3: Navigate to PIM ----------------
        logger.info("Navigating to PIM module")
        driver.get(f"{BASE_URL}/web/index.php/pim/viewEmployeeList")
        try:
            # Wait for the employee table itself rather than a specific
            # heading tag - the heading's markup (h6 vs div/span) has
            # changed between demo site versions, but the results table
            # is a stable signal that the page has fully rendered.
            wait.until(EC.presence_of_element_located(
                (By.CLASS_NAME, "oxd-table-body")))
            logger.info("PIM page loaded")
        except TimeoutException:
            screenshot_path = os.path.join(LOG_DIR, "pim_failure.png")
            try:
                time.sleep(1)  # avoid a transient blank compositor frame
                driver.save_screenshot(screenshot_path)
                logger.info("Saved failure screenshot to %s", screenshot_path)
            except WebDriverException:
                pass
            logger.error("Current URL at failure: %s", driver.current_url)
            raise RuntimeError(
                "Could not load PIM / Employee list page in time. "
                f"See pim_failure.png in {LOG_DIR}. Current URL was: "
                f"{driver.current_url}"
            )

        # ---------------- Step 4: Add Employee ----------------
        logger.info("Opening Add Employee form")
        safe_click(driver, wait, (By.XPATH, "//button[contains(.,'Add')]"), logger)

        first_name_field = wait.until(EC.presence_of_element_located(
            (By.NAME, "firstName")))
        last_name_field = driver.find_element(By.NAME, "lastName")

        first_name_field.clear()
        first_name_field.send_keys(first_name)
        last_name_field.clear()
        last_name_field.send_keys(last_name)

        if employee_id:
            try:
                emp_id_field = driver.find_element(
                    By.XPATH, "//label[text()='Employee Id']/../..//input")
                emp_id_field.clear()
                emp_id_field.send_keys(employee_id)
            except NoSuchElementException:
                logger.warning("Employee ID field not found, using auto-generated ID")

        logger.info("Submitting new employee: %s %s (ID: %s)",
                    first_name, last_name, employee_id)
        safe_click(driver, wait, (By.XPATH, "//button[@type='submit']"), logger)

        # ---------------- Step 5: Verify creation ----------------
        try:
            wait.until(EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(),'Personal Details')]")))
            logger.info("Employee creation verified successfully")
            result["success"] = True
            result["message"] = "Employee created successfully"
            result["employee_added"] = {
                "first_name": first_name,
                "last_name": last_name,
                "employee_id": employee_id,
            }
        except TimeoutException:
            # Check for a validation error first - a common cause here
            # is a duplicate Employee ID, since this demo database is
            # shared and already has 150+ existing employee records.
            validation_error = None
            try:
                err_el = driver.find_element(
                    By.XPATH,
                    "//span[contains(@class,'oxd-input-field-error-message')]")
                validation_error = err_el.text.strip()
            except NoSuchElementException:
                pass

            time.sleep(1)  # avoid capturing a transient blank compositor frame
            screenshot_path = os.path.join(LOG_DIR, "add_employee_failure.png")
            try:
                driver.save_screenshot(screenshot_path)
                logger.info("Saved failure screenshot to %s", screenshot_path)
            except WebDriverException:
                pass
            logger.error("Current URL at failure: %s", driver.current_url)

            if validation_error:
                raise RuntimeError(
                    f"Could not create employee - form validation error: "
                    f"'{validation_error}'. If you supplied an Employee ID, "
                    "try a different one - this demo database already has "
                    "many existing records and IDs must be unique."
                )
            raise RuntimeError(
                "Could not verify employee creation. "
                f"See add_employee_failure.png in {LOG_DIR}."
            )

        # ---------------- Step 6: Extract employee list ----------------
        # From here on, wrap each remaining step in its own try/except.
        # If extraction or logout fails, we do NOT want to overwrite the
        # success result set above - the employee was already created,
        # so the dashboard should still show that clearly even if this
        # bonus step has trouble.
        try:
            logger.info("Extracting employee list data")
            driver.get(f"{BASE_URL}/web/index.php/pim/viewEmployeeList")
            wait.until(EC.presence_of_element_located(
                (By.CLASS_NAME, "oxd-table-body")))
            time.sleep(1)

            def read_headers():
                try:
                    header_cells = driver.find_elements(
                        By.XPATH,
                        "//div[contains(@class,'oxd-table-header')]"
                        "//div[contains(@class,'oxd-table-cell')]")
                    return [h.text.strip() for h in header_cells]
                except NoSuchElementException:
                    return []

            def read_rows(limit=20):
                rows = driver.find_elements(
                    By.XPATH, "//div[@class='oxd-table-body']/div")
                data = []
                for row in rows[:limit]:
                    cells = row.find_elements(By.CLASS_NAME, "oxd-table-cell")
                    # Keep empty cells in place - filtering them out
                    # shifts every later column left whenever a field
                    # is blank.
                    values = [c.text.strip() for c in cells]
                    if any(values):
                        data.append(values)
                return data

            headers = read_headers()
            table_data = read_rows(limit=20)

            # If the employee we just added isn't among the rows shown
            # (the default list has 100+ records and isn't sorted by
            # most recently added), look it up specifically and append
            # it, so the extracted list always includes the new hire.
            already_present = any(
                first_name.lower() in [v.lower() for v in row]
                and last_name.lower() in [v.lower() for v in row]
                for row in table_data
            )
            if not already_present:
                try:
                    if employee_id:
                        id_field = driver.find_element(
                            By.XPATH,
                            "//label[text()='Employee Id']/../..//input")
                        id_field.clear()
                        id_field.send_keys(employee_id)
                    else:
                        name_field = driver.find_element(
                            By.XPATH,
                            "//label[text()='Employee Name']/../..//input")
                        name_field.clear()
                        name_field.send_keys(f"{first_name} {last_name}")
                        time.sleep(1)
                        name_field.send_keys(u'\ue00c')  # Keys.ESCAPE

                    safe_click(driver, wait,
                               (By.XPATH, "//button[@type='submit']"), logger)
                    wait.until(EC.presence_of_element_located(
                        (By.CLASS_NAME, "oxd-table-body")))
                    time.sleep(1)

                    new_row = read_rows(limit=5)
                    if new_row:
                        table_data.extend(new_row)
                        logger.info(
                            "New employee wasn't in the default page "
                            "view - looked it up and appended to results")
                except (NoSuchElementException, TimeoutException):
                    logger.warning(
                        "Could not look up newly added employee separately")

            if headers and table_data:
                width = len(table_data[0])
                if len(headers) < width:
                    headers += [""] * (width - len(headers))
                elif len(headers) > width:
                    headers = headers[:width]
                table_data.insert(0, headers)

            result["employee_table"] = table_data
            logger.info("Extracted %d employee rows", len(table_data))

            # Save to CSV
            if table_data:
                csv_name = (
                    f"employees_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
                csv_path = os.path.join(OUTPUT_DIR, csv_name)
                with open(csv_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerows(table_data)
                result["csv_file"] = csv_name
                logger.info("Saved extracted data to %s", csv_name)

        except Exception as e:
            # Employee creation already succeeded above - just log this
            # as a partial issue instead of marking the whole run failed.
            logger.warning("Employee list extraction had a problem: %s", str(e))
            if result["success"]:
                result["message"] += " (list extraction had an issue - see log)"

        # ---------------- Step 7: Logout ----------------
        try:
            logger.info("Logging out")
            driver.get(f"{BASE_URL}/web/index.php/dashboard/index")
            safe_click(driver, wait, (By.CLASS_NAME, "oxd-userdropdown-tab"), logger)
            safe_click(driver, wait, (By.LINK_TEXT, "Logout"), logger)
            logger.info("Logout successful. Automation run complete.")
        except Exception as e:
            logger.warning("Logout had a problem: %s", str(e))

    except Exception as e:
        # Generic safety net: any failure that wasn't already caught and
        # given a clean message by a step-specific handler lands here.
        # Grab a screenshot and the current URL so it's always possible
        # to diagnose what happened, instead of just seeing a raw
        # Selenium/chromedriver stacktrace.
        current_url = None
        screenshot_saved = False
        if driver:
            try:
                current_url = driver.current_url
            except WebDriverException:
                pass
            try:
                time.sleep(1)  # avoid a transient blank compositor frame
                screenshot_path = os.path.join(LOG_DIR, "unexpected_failure.png")
                driver.save_screenshot(screenshot_path)
                screenshot_saved = True
            except WebDriverException:
                pass

        logger.error("Automation failed: %s", str(e))
        if current_url:
            logger.error("Current URL at failure: %s", current_url)

        short_reason = str(e).split("Stacktrace:")[0].strip() or type(e).__name__
        message = f"Automation failed: {short_reason}"
        if screenshot_saved:
            message += f" (see unexpected_failure.png in {LOG_DIR})"
        if current_url:
            message += f" [page was: {current_url}]"

        result["success"] = False
        result["message"] = message

    finally:
        if driver:
            driver.quit()

    return result