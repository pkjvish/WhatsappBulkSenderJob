"""
WhatsApp Bulk Sender — Selenium Edition
========================================
Replaces the old pyautogui / image-matching version with real browser
automation. Instead of locating a "+" button on screen by pixel-matching
a screenshot (which breaks the moment your screen resolution, zoom level,
window size, or WhatsApp's theme changes) this version talks directly to
the page's HTML elements through Selenium — the same way the browser
itself sees the page. That removes the two biggest sources of the
breakage you were hitting:

    1. No more screen-coordinate clicking — every click targets a real
       DOM element, found by attribute, not by pixels.
    2. No more OS file-dialog automation — the file is attached by
       sending the path straight to the hidden <input type="file">
       element, which is the standards-backed way Selenium uploads files.

Setup
-----
    pip install -r requirements.txt

    (Requires Google Chrome installed. Selenium 4.6+ auto-downloads the
    matching chromedriver, so you don't need to install one manually.)

Usage
-----
    python whatsapp_selenium_sender.py
    python whatsapp_selenium_sender.py --delay 10
    python whatsapp_selenium_sender.py --no-attachment

First run: a Chrome window opens and shows a WhatsApp Web QR code — scan
it once with your phone. The session is saved in ./whatsapp_chrome_profile
so you won't need to scan it again on future runs.

Input format (numberMessage.csv) — unchanged from before:
    +919702309081,"Hi Pankaj, this is a test message1"
    +918655072885,"Hi Priya, your appointment is confirmed."

A Note on Selectors
--------------------
WhatsApp periodically tweaks its web app's internal HTML/class names.
Each entry in the SEL dictionary below is a *list* of fallback selectors
that are tried in order, so a single UI tweak usually won't break the
whole script. If every fallback for a given element ever stops working,
open web.whatsapp.com in Chrome, right-click the element → Inspect, and
add its current selector to the matching list.
"""

import os
import sys
import csv
import time
import argparse
import pyperclip
from pathlib import Path
from datetime import datetime
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


# ════════════════════════════════════════════════════════════════
# CONFIGURATION  –  edit these values
# ════════════════════════════════════════════════════════════════

INPUT_FILE          = "numberMessage.csv"
ATTACHMENT_FILE     = "resume.pdf"                                   # set to "" to disable
CHROME_PROFILE_DIR  = os.path.abspath("whatsapp_chrome_profile")  # keeps you logged in

DELAY_BETWEEN_MESSAGES = 8     # seconds between recipients (keep generous to avoid WA limits)
ELEMENT_WAIT_TIMEOUT   = 25    # seconds to wait for any single element to appear
QR_SCAN_TIMEOUT         = 120   # seconds allowed for the first-time QR scan
POST_SEND_WAIT          = 3     # pause after the text message is sent, before attaching a file

MAX_SEND_RETRIES = 2
RETRY_DELAY      = 5           # seconds between retries

HEADLESS = False                # keep False — WhatsApp Web is unreliable headless

LOG_DIR = Path("run_logs")
LOG_DIR.mkdir(exist_ok=True)
FAILURES_CSV = LOG_DIR / "failures.csv"


# Fallback selector lists — see "A Note on Selectors" above.
SEL = {
    "logged_in_marker": [
        'div#pane-side',
        'div[aria-label="Chat list"]',
    ],
    "compose_box": [
        'div[contenteditable="true"][data-tab="10"]',
        'div[aria-label="Type a message"]',
        'footer div[contenteditable="true"]',
    ],
    "send_button": [
        'button[aria-label="Send"]',
        'span[data-icon="send"]',
        'span[data-icon="wds-ic-send-filled"]',
    ],
    "attach_button": [
        'div[title="Attach"]',
        'span[data-icon="plus-rounded"]',
        'span[data-icon="attach-menu-plus"]',
        'span[data-icon="clip"]',
    ],
    "doc_menu_item": [
        '//div[@aria-label="Document"]',
        '//li[@aria-label="Document"]',
        '//span[text()="Document"]',
    ],
    "file_input": [
        'input[type="file"]',
    ],
    "invalid_number_dialog_btn": [
        '//div[contains(text(),"Phone number shared via url is invalid")]/ancestor::div[@role="dialog"]//button',
        '//div[@role="dialog"]//button[contains(text(),"OK")]',
    ],
}


# ════════════════════════════════════════════════════════════════
# SELECTOR HELPER  –  tries each fallback in order
# ════════════════════════════════════════════════════════════════

def _by_for(selector: str):
    return By.XPATH if selector.startswith(("//", ".//")) else By.CSS_SELECTOR


def find_first(driver, selectors, timeout=ELEMENT_WAIT_TIMEOUT, clickable=False):
    """Try each selector in the list until one matches; raise the last
    TimeoutException if none do."""
    last_exc = None
    for sel in selectors:
        by = _by_for(sel)
        try:
            cond = (EC.element_to_be_clickable((by, sel)) if clickable
                    else EC.presence_of_element_located((by, sel)))
            return WebDriverWait(driver, timeout).until(cond)
        except TimeoutException as e:
            last_exc = e
    raise last_exc or TimeoutException(f"No selector matched: {selectors}")


# ════════════════════════════════════════════════════════════════
# FILE READER
# ════════════════════════════════════════════════════════════════

def load_pairs() -> list[tuple[str, str]]:
    """
    Parse numberMessage.csv into a list of (phone_number, message) tuples
    using the csv module, so quoted messages containing commas (e.g.
    "Hi Pankaj, how are you?") are handled correctly.
    """
    if not os.path.exists(INPUT_FILE):
        print(f"❌  File not found: {INPUT_FILE}")
        sys.exit(1)

    pairs, errors = [], []
    with open(INPUT_FILE, newline="", encoding="utf-8") as f:
        for line_no, row in enumerate(csv.reader(f), start=1):
            if not row or not row[0].strip() or row[0].strip().startswith("#"):
                continue
            if len(row) < 2:
                errors.append(f"Line {line_no}: missing message column → {row}")
                continue

            number  = row[0].strip()
            message = ",".join(row[1:]).strip()

            if not (number.startswith("+") and number[1:].isdigit() and 8 <= len(number[1:]) <= 15):
                errors.append(f"Line {line_no}: invalid phone number format: {number}")
                continue
            if not message:
                errors.append(f"Line {line_no}: empty message for {number}")
                continue

            pairs.append((number, message))

    if errors:
        print(f"⚠️   Skipped {len(errors)} invalid row(s) in {INPUT_FILE}:")
        for e in errors:
            print(f"   {e}")
        print()

    if not pairs:
        print(f"❌  No valid entries found in {INPUT_FILE}. Exiting.")
        sys.exit(1)

    return pairs


def validate_attachment(disabled: bool) -> Optional[str]:
    if disabled or not ATTACHMENT_FILE:
        return None
    abs_path = os.path.abspath(ATTACHMENT_FILE)
    if not os.path.exists(abs_path):
        print(f"❌  Attachment not found: {abs_path}")
        sys.exit(1)
    return abs_path


# ════════════════════════════════════════════════════════════════
# BROWSER SETUP
# ════════════════════════════════════════════════════════════════

def build_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    if HEADLESS:
        opts.add_argument("--headless=new")

    # Selenium 4.6+ resolves chromedriver automatically — no manual setup needed.
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(60)
    return driver


def wait_for_login(driver) -> None:
    print("Opening WhatsApp Web …")
    driver.get("https://web.whatsapp.com")

    try:
        find_first(driver, SEL["logged_in_marker"], timeout=5)
        print("✅  Already logged in (saved session).")
        return
    except TimeoutException:
        pass

    print(f"📱  Scan the QR code with your phone (timeout {QR_SCAN_TIMEOUT}s) …")
    try:
        find_first(driver, SEL["logged_in_marker"], timeout=QR_SCAN_TIMEOUT)
        print("✅  Logged in.")
    except TimeoutException:
        print("❌  Login timed out — QR code was not scanned in time.")
        driver.quit()
        sys.exit(1)


# ════════════════════════════════════════════════════════════════
# CORE ACTIONS
# ════════════════════════════════════════════════════════════════

def open_chat(driver, number: str) -> str:
    """Navigate to a recipient's chat. Returns 'ok', 'invalid', or 'fail'."""
    clean = number.lstrip("+")
    driver.get(f"https://web.whatsapp.com/send?phone={clean}&app_absent=0")
    time.sleep(2)

    try:
        btn = find_first(driver, SEL["invalid_number_dialog_btn"], timeout=4)
        btn.click()
        return "invalid"
    except TimeoutException:
        pass

    try:
        find_first(driver, SEL["compose_box"], timeout=ELEMENT_WAIT_TIMEOUT)
        return "ok"
    except TimeoutException:
        return "fail"


def send_text_message(driver, message: str) -> bool:
    """Paste the message via clipboard (handles emoji/multi-line safely,
    unlike character-by-character typing) and press Enter."""
    try:
        box = find_first(driver, SEL["compose_box"], clickable=True)
        box.click()
        pyperclip.copy(message)
        box.send_keys(Keys.CONTROL, "v")
        time.sleep(0.5)
        box.send_keys(Keys.ENTER)
        return True
    except Exception as exc:
        print(f"   ⚠️  send_text_message error: {exc}")
        return False


def send_attachment(driver, abs_path: str) -> bool:
    """Attach a file by sending its path directly to the hidden file
    input — no clicking through an OS file-picker dialog required."""
    try:
        attach_btn = find_first(driver, SEL["attach_button"], clickable=True)
        attach_btn.click()
        time.sleep(1)

        doc_item = find_first(driver, SEL["doc_menu_item"])
        doc_item.click()
        time.sleep(1)

        file_input = find_first(driver, SEL["file_input"])
        file_input.send_keys(abs_path)
        time.sleep(2)   # let WhatsApp render the attachment preview

        send_btn = find_first(driver, SEL["send_button"], clickable=True)
        send_btn.click()
        return True
    except Exception as exc:
        print(f"   ⚠️  send_attachment error: {exc}")
        return False


# ════════════════════════════════════════════════════════════════
# LOGGING HELPERS
# ════════════════════════════════════════════════════════════════

def log_failure(number: str, reason: str, index: int, screenshot: str = "") -> None:
    header = ["timestamp", "index", "number", "reason", "screenshot"]
    write_header = not FAILURES_CSV.exists()
    try:
        with open(FAILURES_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(header)
            w.writerow([datetime.utcnow().isoformat(), index, number, reason, screenshot])
    except Exception:
        pass


def capture_screenshot(driver, index: int, number: str) -> str:
    fname = LOG_DIR / f"screenshot_{index}_{number.lstrip('+')}.png"
    try:
        driver.save_screenshot(str(fname))
        return str(fname)
    except Exception:
        return ""


# ════════════════════════════════════════════════════════════════
# MAIN SENDER
# ════════════════════════════════════════════════════════════════

def send_bulk(delay_override: Optional[int] = None, disable_attachment: bool = False) -> None:
    pairs       = load_pairs()
    total       = len(pairs)
    attach_path = validate_attachment(disable_attachment)
    delay       = delay_override or DELAY_BETWEEN_MESSAGES

    print("=" * 50)
    print("  📱  WhatsApp Bulk Sender — Selenium Edition")
    print("=" * 50)
    print(f"  Recipients : {total}")
    print(f"  Attachment : {attach_path or 'disabled'}")
    print(f"  Delay      : {delay}s between recipients")
    print("=" * 50)
    print("⚠️   Don't close the Chrome window while the script runs.\n")

    driver = build_driver()
    wait_for_login(driver)

    successful_msg, successful_file, failed = [], [], []

    for index, (number, message) in enumerate(pairs, start=1):
        print(f"\n[{index}/{total}] ➜  {number}")
        print(f"   Message    : {message[:70]}{'…' if len(message) > 70 else ''}")
        if attach_path:
            print(f"   Attachment : {os.path.basename(attach_path)}")

        # ── Step A: open the chat ─────────────────────────────────────
        status = "fail"
        for attempt in range(1, MAX_SEND_RETRIES + 1):
            status = open_chat(driver, number)
            if status in ("ok", "invalid"):
                break
            print(f"   ⚠️  Chat failed to load (attempt {attempt}/{MAX_SEND_RETRIES})")
            time.sleep(RETRY_DELAY)

        if status == "invalid":
            print("   ❌ Invalid WhatsApp number")
            failed.append((number, "invalid_number"))
            log_failure(number, "invalid_number", index)
            time.sleep(delay)
            continue

        if status != "ok":
            shot = capture_screenshot(driver, index, number)
            failed.append((number, "chat_open_failed"))
            log_failure(number, "chat_open_failed", index, shot)
            time.sleep(delay)
            continue

        # ── Step B: send the text message ─────────────────────────────
        msg_ok = False
        for attempt in range(1, MAX_SEND_RETRIES + 1):
            if send_text_message(driver, message):
                msg_ok = True
                successful_msg.append(number)
                print("   ✅ Message sent")
                break
            print(f"   ❌ Message failed (attempt {attempt}/{MAX_SEND_RETRIES})")
            time.sleep(RETRY_DELAY)

        if not msg_ok:
            shot = capture_screenshot(driver, index, number)
            failed.append((number, "message_send_failed"))
            log_failure(number, "message_send_failed", index, shot)

        time.sleep(POST_SEND_WAIT)

        # ── Step C: send the attachment ───────────────────────────────
        if msg_ok and attach_path:
            print("   📎 Sending attachment …")
            if send_attachment(driver, attach_path):
                print("   ✅ File sent")
                successful_file.append(number)
            else:
                shot = capture_screenshot(driver, index, number)
                failed.append((number, "attachment_failed"))
                log_failure(number, "attachment_failed", index, shot)

        if index < total:
            print(f"⏳ Waiting {delay}s before next recipient …")
            time.sleep(delay)

    # ── Summary ──────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("📊  SUMMARY")
    print(f"    Total recipients : {total}")
    print(f"    ✅ Messages sent : {len(successful_msg)}")
    if attach_path:
        print(f"    ✅ Files sent    : {len(successful_file)}")
    print(f"    ❌ Failures      : {len(failed)}")
    if failed:
        print("\n  Failures:")
        for num, reason in failed:
            print(f"    {num}  –  {reason}")
    print("=" * 50)

    driver.quit()
    print("🎉  Done!")


# ════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WhatsApp Bulk Sender (Selenium Edition)")
    parser.add_argument("--delay", type=int, dest="delay",
                        help="Seconds to wait between recipients (overrides DELAY_BETWEEN_MESSAGES)")
    parser.add_argument("--no-attachment", action="store_true",
                        help="Disable the file attachment step for this run")
    args = parser.parse_args()

    send_bulk(delay_override=args.delay, disable_attachment=args.no_attachment)
