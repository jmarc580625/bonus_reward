from __future__ import annotations

import logging
import os
import socket
import subprocess
import time
from datetime import datetime
import argparse
import re

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# ---------- Logging setup ----------

logging.basicConfig(
    level=logging.INFO,  # set to logging.DEBUG for more verbose logs
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",  # no milliseconds
)

class DailyBonusClient:
    def __init__(
            self,
            debug_port: int = 9222,
            chrome_path: str = r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            base_url: str = "https://video.a2e.ai/",
            force_restart: bool = False,
            stop_chrome_on_exit: bool = False,
            ):

        module_name = os.path.splitext(os.path.basename(__file__))[0]
        self.logger = logging.getLogger(module_name)

        self.debug_port = debug_port

        self.chrome_path = chrome_path

        script_dir = os.path.dirname(os.path.abspath(__file__))

        # Store chrome user data under chrome_user_data folder next to this script.
        self.user_data_dir = os.path.join(script_dir, "chrome_user_data")

        self.chrome_pid: int | None = None

        # PID file to track the Chrome instance used by this script
        self.pid_file_path = os.path.join(self.user_data_dir, "chrome.pid")

        self.driver_path = os.path.join(script_dir, "drivers/chromedriver-win64/chromedriver.exe")

        self.base_url = base_url

        self.force_restart = force_restart

        self.stop_chrome_on_exit = stop_chrome_on_exit

        self.driver: webdriver.Chrome | None = None
        self.wait: WebDriverWait | None = None
        
        # Compiled date time pattern

        self.DATETIME_PATTERN = re.compile(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})")

    # ---------- Chrome process / driver setup ----------

    def _verify_debug_port(self) -> bool:
        """Check if Chrome is running with remote debugging."""
        s = socket.socket()
        try:
            s.connect(("127.0.0.1", self.debug_port))
            return True
        except Exception:
            return False
        finally:
            s.close()

    def _kill_existing_chrome(self) -> bool:
        """Attempt to close only the Chrome instance associated with this script.

        Returns True if either nothing needed to be killed or a Chrome process was
        successfully terminated; returns False if we detected a candidate process
        but could not terminate it.
        """
        self.logger.info("Attempting to close Chrome associated with this script...")

        # 1) Try using the PID stored in chrome.pid
        if self.chrome_pid is None:
            self._load_chrome_pid_from_file()

        if self.chrome_pid is not None:
            self.logger.info("Attempting to terminate Chrome by PID from pid file: %s", self.chrome_pid)
            try:
                result = subprocess.run(
                    ["taskkill", "/F", "/PID", str(self.chrome_pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                if result.returncode == 0:
                    time.sleep(2)
                    return True
                else:
                    self.logger.warning(
                        "taskkill for PID %s exited with code %s; will try fallback by port",
                        self.chrome_pid,
                        result.returncode,
                    )
            except Exception:
                self.logger.exception("Error while stopping Chrome process with PID %s", self.chrome_pid)

        # 2) Fallback: find the process listening on the debug port and kill it
        self.logger.info(
            "PID from pid file not usable. Trying to find Chrome by debug port %s...",
            self.debug_port,
        )
        try:
            # netstat -ano to list connections and owning PIDs, filter by debug port
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=False,
            )
            pid_from_port: int | None = None
            for line in result.stdout.splitlines():
                if f":{self.debug_port} " in line and "LISTENING" in line.upper():
                    parts = line.split()
                    if parts:
                        try:
                            pid_from_port = int(parts[-1])
                        except ValueError:
                            continue
                    if pid_from_port is not None:
                        self.chrome_pid = pid_from_port
                        self._write_chrome_pid_to_file(pid_from_port)
                        break

            if pid_from_port is not None:
                self.logger.info(
                    "Attempting to terminate Chrome listening on port %s (PID %s)",
                    self.debug_port,
                    pid_from_port,
                )
                result = subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid_from_port)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                if result.returncode == 0:
                    time.sleep(2)
                    return True
                else:
                    self.logger.error(
                        "taskkill for port-listening PID %s exited with code %s",
                        pid_from_port,
                        result.returncode,
                    )
                    return False
            else:
                self.logger.info(
                    "No process found listening on port %s; nothing to terminate.",
                    self.debug_port,
                )
                return True
        except Exception:
            self.logger.exception(
                "Error while trying to locate and stop Chrome process by debug port %s",
                self.debug_port,
            )
            return False

    def _start_chrome(self) -> bool:
        """Start Chrome with remote debugging enabled (does not kill existing)."""
        self.logger.info("Starting Chrome with remote debugging on port %s", self.debug_port)
        proc = subprocess.Popen(
            [
                self.chrome_path,
                f"--remote-debugging-port={self.debug_port}",
                f"--user-data-dir={self.user_data_dir}",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Record the PID of the Chrome process we started so we can
        # selectively terminate it later without affecting other Chrome instances.
        self._write_chrome_pid_to_file(proc.pid)

        # Wait for Chrome to start
        for _ in range(10):
            if self._verify_debug_port():
                self.logger.info("Chrome started successfully")
                return True
            time.sleep(1)
        self.logger.error("Chrome did not start within timeout")
        return False

    def _stop_chrome(self) -> None:
        """Stop the Chrome instance started by this script if possible.

        First try a graceful shutdown via Selenium / DevTools (Browser.close),
        then fall back to killing by PID from the pid file.
        """
        # 1) Try to close via Selenium / DevTools
        closed_via_selenium = False
        if self.driver is not None:
            try:
                self.logger.info("Trying to close Chrome via DevTools Browser.close")
                self.driver.execute_cdp_cmd("Browser.close", {})
                closed_via_selenium = True
            except Exception:
                self.logger.exception("Error while closing Chrome via DevTools")

        # 2) If Selenium close failed, fall back to PID kill as before
        if not closed_via_selenium:
            if self.chrome_pid is None:
                self._load_chrome_pid_from_file()
            if self.chrome_pid is None:
                self.logger.warning("No Chrome PID known; skipping PID-based stop")
                return
            try:
                self.logger.info(f"Stopping Chrome started by the script using PID: {self.chrome_pid}")
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(self.chrome_pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                self.logger.exception("Error while stopping Chrome process by PID")

    def _load_chrome_pid_from_file(self) -> int | None:
        """Load Chrome PID from pid file into self.chrome_pid."""
        try:
            if os.path.exists(self.pid_file_path):
                with open(self.pid_file_path, "r", encoding="utf-8") as f:
                    pid_str = f.read().strip()
                if pid_str:
                    self.chrome_pid = int(pid_str)
                    return self.chrome_pid
        except Exception:
            self.logger.exception("Failed to read Chrome PID from %s", self.pid_file_path)
        return self.chrome_pid

    def _write_chrome_pid_to_file(self, pid: int) -> None:
        """Persist Chrome PID to pid file and cache it on the instance."""
        self.chrome_pid = pid
        try:
            os.makedirs(os.path.dirname(self.pid_file_path), exist_ok=True)
            with open(self.pid_file_path, "w", encoding="utf-8") as f:
                f.write(str(pid))
        except Exception:
            self.logger.exception("Failed to write Chrome PID file at %s", self.pid_file_path)
    
    def _setup_driver(self) -> None:
        """Create Selenium WebDriver attached to the existing Chrome."""
        service = Service(executable_path=self.driver_path)
        opts = Options()
        opts.add_experimental_option(
            "debuggerAddress", f"127.0.0.1:{self.debug_port}"
        )
        self.driver = webdriver.Chrome(service=service, options=opts)
        self.wait = WebDriverWait(self.driver, 10)
        self.logger.info("WebDriver attached to Chrome on port %s", self.debug_port)

    # ---------- Page helpers ----------

    def _check_login_required(self) -> bool:
        """Check if login is required by looking for the login button with a short wait."""
        assert self.driver is not None
        try:
            WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located((By.CLASS_NAME, "loginButton___KvHTz"))
            )
            self.logger.info("Login button detected; login is required")
            return True
        except TimeoutException:
            # No login button visible after a short wait; assume already logged in
            self.logger.debug("No login button detected; assuming user is already logged in")
            return False

    def _wait_for_manual_login(self) -> bool:
        """Wait for user to complete manual login."""
        assert self.driver is not None
        self.logger.info("Login required, exiting script.")
        # Leaving chrome open to give user a chance to log in
        self.stop_chrome_on_exit = False
        self.logger.info("Please log in manually in the Chrome window before retrying bonus claim.")
        return False

    # ---------- Daily bonus logic ----------

    def _get_claim_dialog_if_visible(self):
        """Return visible claim dialog if already open, else None."""
        assert self.driver is not None
        try:
            self.logger.debug("Checking if claim dialog is visible")
            dialog = WebDriverWait(self.driver, 1).until(
                EC.visibility_of_element_located(
                    (
                        By.XPATH,
                        "//div[@role='dialog' and contains(@class,'modal-checkIn')]",
                    )
                )
            )
            self.logger.info("Claim dialog is already visible")
            return dialog
        except TimeoutException:
            self.logger.debug("Claim dialog is not visible yet")
            return None

    def _open_claim_dialog_via_trigger(self):
        """Click the bonus trigger to open the claim dialog and return it."""
        assert self.driver is not None and self.wait is not None

        self.logger.info("Looking for bonus trigger")
        right_section = self.wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "right___xiLco"))
        )

        try:
            bonus_trigger = right_section.find_element(
                By.XPATH,
                ".//div[contains(@class, 'inviteReward___HHLBu')]"
                "/following-sibling::div[contains(@style, 'display: flex')]",
            )
        except NoSuchElementException:
            # Log a snippet of the right section HTML so we can inspect the DOM
            try:
                html = right_section.get_attribute("outerHTML")
                self.logger.warning(
                    "Bonus trigger element not found. right_section HTML snippet: %s",
                    html[:1000],
                )
            except Exception:
                self.logger.exception("Failed to capture right_section HTML when trigger was missing")
            return None

        self.logger.debug("Moving mouse to bonus trigger")
        actions = ActionChains(self.driver)
        actions.move_to_element(bonus_trigger).pause(0.5).perform()

        self.logger.info("Clicking bonus trigger")
        actions.click(bonus_trigger).perform()

        try:
            # decide timeout based on whether we’re reusing Chrome
            timeout = 5
            if not self.force_restart:
                timeout = 15  # background / reused instance is more likely here

            self.logger.info("Waiting for claim dialog to open")
            dialog = WebDriverWait(self.driver, timeout).until(
                EC.visibility_of_element_located(
                    (
                        By.XPATH,
                        "//div[@role='dialog' and contains(@class,'modal-checkIn')]"
                    )
                )
            )
            self.logger.info("Claim dialog is open")
            return dialog
        except TimeoutException:
            self.logger.warning(f"Claim dialog did not show up within {timeout} seconds")
            try:
                html = self.driver.page_source
                self.logger.debug("Page HTML snippet after click:\n%s", html[:2000])
            except Exception:
                self.logger.exception("Failed to capture page HTML after bonus click")
            return None

    def _parse_dialog_message(self, dialog) -> str:
        """Return the claim dialog message text (possibly empty)."""
        self.logger.debug("Looking for claim dialog message")
        try:
            dialog_message = dialog.find_element(
                By.XPATH, ".//div[contains(@class,'content__')]"
            ).text
        except Exception:
            dialog_message = ""

        self.logger.debug("Claim dialog message:\n%s\n", dialog_message)
        return dialog_message.strip()

    def _handle_cooldown_if_any(self, dialog_message: str) -> bool:
        """Return True if in cooldown and handled (should stop), else False."""

        if not dialog_message:
            return False

        first_line = dialog_message.splitlines()[0]

        m = self.DATETIME_PATTERN.search(first_line)
        if not m:
            self.logger.info("No next availibility time message")
            return False

        date_part, time_part = m.group(1), m.group(2)
        next_time_claim_text = f"{date_part} {time_part}"

        try:
            next_time_claim = datetime.strptime(next_time_claim_text, "%m/%d/%Y %H:%M")
            self.logger.warning("Daily cannot be claimed before %s", next_time_claim)
        except ValueError:
            self.logger.warning("Could not parse next claim time: %r", next_time_claim_text)

        return True

    def _click_claim_button(self, dialog) -> bool:
        """Click the 'Claim Now' button in the dialog."""
        assert self.driver is not None
        self.logger.info("Looking for claim button")
        try:
            claim_btn = dialog.find_element(
                By.XPATH,
                ".//button[contains(@class,'aae-ant-btn-primary')]"
            )
            self.logger.debug("Claim button text: %r", claim_btn.text)

            self.logger.info("Clicking claim button via JavaScript")
            # Click via JS to avoid mouse-move closing the dialog
            self.driver.execute_script("arguments[0].click();", claim_btn)

            self.logger.info("Successfully clicked claim button")
            return True
        except Exception:
            self.logger.exception("Error when trying to click claim button")
            return False

    def claim_daily_bonus(self) -> bool:
        """Public method: claim the daily bonus if available."""
        assert self.driver is not None and self.wait is not None
        try:
            dialog = self._get_claim_dialog_if_visible()

            if dialog is None:
                self.logger.info("Claim dialog is not visible; opening via trigger")
                dialog = self._open_claim_dialog_via_trigger()
                if dialog is None:
                    return False

            dialog_message = self._parse_dialog_message(dialog)

            # Cooldown case
            if self._handle_cooldown_if_any(dialog_message):
                return False

            # Claim case
            return self._click_claim_button(dialog)

        except Exception:
            self.logger.exception("Unexpected error during bonus claim")
            return False

    # ---------- High-level orchestration ----------

    def run(self) -> None:
        """Main orchestration: start/reuse Chrome, attach driver, log in, claim bonus."""
        try:
            # Decide how to handle Chrome based on force_restart
            if self.force_restart:
                self.logger.info("Option force_restart=True")
                if not self._kill_existing_chrome():
                    self.logger.error(
                        "Failed to stop existing Chrome instance; aborting."
                    )
                    return
                if not self._start_chrome():
                    self.logger.error(
                        "Failed to start Chrome. Please check if Chrome is installed."
                    )
                    return
                self.logger.info("Restarting Chrome with remote debugging on port %s", self.debug_port)
            else:
                self.logger.info("Option force_restart=False")
                if self._verify_debug_port():
                    self.logger.info(
                        "Port %s is open; Reusing existing Chrome instance through this debug port",
                        self.debug_port,
                    )
                else:
                    self.logger.info(
                        "Port %s is not open; starting a new Chrome instance",
                        self.debug_port,
                    )
                    if not self._start_chrome():
                        self.logger.error(
                            "Failed to start Chrome. Please check if Chrome is installed."
                        )
                        return

            self._setup_driver()
            assert self.driver is not None

            self.driver.get(self.base_url)
            self.logger.info("Navigated to %s", self.base_url)

            # Login if required
            if self._check_login_required():
                self.logger.info("Login required")
                if not self._wait_for_manual_login():
                    self.logger.warning("Login in manually before restarting the script")
                    return

            # Attempt to claim bonus
            if self.claim_daily_bonus():
                self.logger.info("Daily bonus claim sequence completed successfully")
            else:
                self.logger.info("Failed to complete bonus claim sequence")

        finally:
            # Stop Chrome if requested
            self.logger.info(f"Option stop_chrome_on_exit={self.stop_chrome_on_exit}")
            if self.stop_chrome_on_exit:
                self._stop_chrome()

            # Always quit webdriver
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    self.logger.exception("Error while quitting WebDriver")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force-restart",
        action="store_true",
        help="Start a fresh Chrome instance (i.e kill any running one)",
    )
    parser.add_argument(
        "--reuse-chrome",
        action="store_false",
        dest="force_restart",
        help="Attach to running Chrome instance if any",
    )
    parser.add_argument(
        "--stop-chrome-on-exit",
        action="store_true",
        help="Stop used Chrome instance when exiting",
    )
    args = parser.parse_args()

    client = DailyBonusClient(
        force_restart=args.force_restart,
        stop_chrome_on_exit=args.stop_chrome_on_exit,
    )
    client.run()

if __name__ == "__main__":
    main()
