"""
WhatsApp Bulk Messenger (Message + File Attachment)
---------------------------------------------------
Reads recipients from  numberMessage.txt  in the format:
    +919702309081,Hi Pankaj How are you ?
    +919876543210,Hello Rahul your order is ready!
    +14155552671,Hi John welcome aboard!

Each line = one phone number + one personal message, separated by the
FIRST comma. The message itself may contain commas freely.

Also sends a single attachment file (e.g. resume.pdf) to every recipient
right after the text message.

Requirements:
    pip install pywhatkit pyautogui pillow

Usage:
    1. Fill in numberMessage.csv  (number,message  — one per line).
    2. Place your attachment file in the same folder.
    3. Log into WhatsApp Web in your default browser.
    4. Run:  python whatsapp_bulk_sender.py
    5. Do NOT touch the mouse/keyboard while the script runs.
"""

import os
import sys
import time
import pyperclip
import pywhatkit as pwk
import pyautogui
from pathlib import Path
import csv
from datetime import datetime
import urllib.parse
import argparse
import webbrowser


# ──────────────────────────────────────────────
# CONFIGURATION  –  edit these values
# ──────────────────────────────────────────────

INPUT_FILE      = "numberMessage.csv"  # combined number + message file
ATTACHMENT_FILE = "resume.pdf"            # file to attach; set None to disable

# Seconds to wait between each recipient (keep ≥ 20 to avoid WA blocks)
DELAY_BETWEEN_MESSAGES = 5

# Seconds for WhatsApp Web to fully load before file-attachment automation
PAGE_LOAD_WAIT = 1

# Seconds pywhatkit holds the tab open (must be enough for the page to load)
TAB_OPEN_WAIT = 15

# Retry behaviour for sending text messages
MAX_SEND_RETRIES = 2
SEND_RETRY_DELAY = 5  # seconds between retries

# Logging
LOG_DIR = Path("run_logs")
LOG_DIR.mkdir(exist_ok=True)
FAILURES_CSV = LOG_DIR / "failures.csv"

# Keep WhatsApp tab open until all recipients are processed
CLOSE_TAB_AT_END = True

# Wait after send button is pressed (seconds)
POST_SEND_WAIT = 5


# ──────────────────────────────────────────────
# FILE READER
# ──────────────────────────────────────────────

def load_pairs() -> list[tuple[str, str]]:
    """
    Parse numberMessage.txt into a list of (phone_number, message) tuples.

    Format per line:
        +919702309081,Hi Pankaj How are you ?

    • Lines starting with # are treated as comments and skipped.
    • Blank lines are skipped.
    • The split is on the FIRST comma only, so messages can contain commas.
    """
    if not os.path.exists(INPUT_FILE):
        print(f"❌  File not found: {INPUT_FILE}")
        sys.exit(1)

    pairs   = []
    errors  = []

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()

            # Skip blank lines and comments
            if not line or line.startswith("#"):
                continue

            # Split on the first comma only
            if "," not in line:
                errors.append(f"  Line {line_no}: missing comma  →  {line!r}")
                continue

            number, message = line.split(",", 1)
            number  = number.strip()
            message = message.strip()

            if not number:
                errors.append(f"  Line {line_no}: empty phone number")
                continue
            if not message:
                errors.append(f"  Line {line_no}: empty message for {number}")
                continue
            # Basic phone number validation: starts with + and digits
            if not (number.startswith("+") and number[1:].isdigit() and 8 <= len(number[1:]) <= 15):
                errors.append(f"  Line {line_no}: invalid phone number format: {number}")
                continue

            pairs.append((number, message))

    if errors:
        print(f"⚠️   Skipped {len(errors)} invalid line(s) in {INPUT_FILE}:")
        for e in errors:
            print(e)
        print()

    if not pairs:
        print(f"❌  No valid entries found in {INPUT_FILE}. Exiting.")
        sys.exit(1)

    return pairs


def validate_attachment() -> str | None:
    """Return the absolute path of the attachment, or None if disabled."""
    if not ATTACHMENT_FILE:
        return None
    abs_path = os.path.abspath(ATTACHMENT_FILE)
    if not os.path.exists(abs_path):
        print(f"❌  Attachment not found: {abs_path}")
        sys.exit(1)
    return abs_path

# ──────────────────────────────────────────────
# ATTACHMENT SENDER  (pyautogui image + clipboard)
# ──────────────────────────────────────────────

PLUS_BTN_IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plus_btn.png")

def send_attachment_via_automation(abs_path: str) -> bool:
    """
    Attach a file using WhatsApp Web's + button.
    Locates the + button via image recognition, clicks it, picks Document,
    and pastes the file path via clipboard.
    """
    try:
        time.sleep(2)

        # ── 1. Find and click the + button ───────────────────────────
        plus_location = None
        for confidence in (0.8, 0.7, 0.6, 0.5):
            plus_location = pyautogui.locateOnScreen(PLUS_BTN_IMG, confidence=confidence, grayscale=True)
            if plus_location:
                break
        if plus_location is None:
            print("         ⚠️  Could not find + button on screen")
            return False
        pyautogui.click(pyautogui.center(plus_location))
        time.sleep(1)

        # ── 2. Choose "Document" from the popup menu ─────────────────
        # Try the normal tab/enter sequence first, then fall back to an
        # extra attempt if the file picker doesn't appear.
        pyautogui.press("tab", presses=2, interval=0.2)
        pyautogui.press("enter")
        time.sleep(2)

        # ── 3. Paste file path into OS file-picker ───────────────────
        pyperclip.copy(abs_path)

        # Primary attempt: paste directly (works when filename field is focused)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.5)
        pyautogui.press("enter")     # confirm path / open
        time.sleep(1)

        # Secondary fallback: focus address bar (Alt+D), paste path, Enter
        # (helps when the dialog focus is elsewhere)
        pyautogui.hotkey("alt", "d")
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.2)
        pyautogui.press("enter")
        time.sleep(1)

        # ── 4. Confirm & send the file ───────────────────────────────
        time.sleep(2)
        pyautogui.press("enter")
        time.sleep(1)

        return True

    except Exception as exc:
        print(f"         ⚠️  Attachment automation error: {exc}")
        return False

# ──────────────────────────────────────────────
# MAIN SENDER
# ──────────────────────────────────────────────

def send_bulk() -> None:
    pairs       = load_pairs()
    total       = len(pairs)
    attach_path = validate_attachment()

    print("=" * 6)
    print("  📱  WhatsApp Bulk Sender  (Message + File)")
    print("=" * 6)
    print(f"  Input file  : {INPUT_FILE}  ({total} recipient(s))")
    print(f"  Attachment  : {attach_path or 'None (disabled)'}")
    print(f"  Delay       : {DELAY_BETWEEN_MESSAGES}s between recipients")
    print("=" * 6)
    print("ℹ️   Make sure WhatsApp Web is already logged in.\n")
    print("⚠️   Do NOT move your mouse while the script is running!\n")

    successful_msg  = []
    successful_file = []
    failed          = []

    def log_failure(number: str, reason: str, index: int, screenshot_path: str | None = None) -> None:
        """Append a failure row to the CSV log and print concise info."""
        header = ["timestamp", "index", "number", "reason", "screenshot"]
        row = [datetime.utcnow().isoformat(), index, number, reason, screenshot_path or ""]
        write_header = not FAILURES_CSV.exists()
        try:
            with open(FAILURES_CSV, "a", newline='', encoding="utf-8") as csvf:
                writer = csv.writer(csvf)
                if write_header:
                    writer.writerow(header)
                writer.writerow(row)
        except Exception:
            pass

    def capture_screenshot(index: int, number: str) -> str:
        """Capture a full-screen screenshot and return the saved path."""
        fname = LOG_DIR / f"screenshot_{index}_{number.replace('+','')}.png"
        try:
            img = pyautogui.screenshot()
            img.save(fname)
            return str(fname)
        except Exception:
            return ""

    # Determine send mode from globals (may be overridden by CLI)
    mode = globals().get("SEND_MODE", "auto")

    for index, (number, msg) in enumerate(pairs, start=1):

        print(f"[{index}/{total}] ➜  {number}")
        print(f"         Message   : {msg[:70]}{'…' if len(msg) > 70 else ''}")
        if attach_path:
            print(f"         Attachment: {os.path.basename(attach_path)}")

        # ── Step A: Send text message ────────────────────────────────

        # Send message according to selected mode: open WhatsApp tab once, then reuse the same tab
        msg_ok = False
        last_exc = None
        # Track whether we've opened a WhatsApp tab already in this run
        if index == 1:
            whatsapp_tab_open = False

        for attempt in range(1, MAX_SEND_RETRIES + 1):
            try:
                if mode == "url":
                    if index == 1 and not whatsapp_tab_open:
                        if MAX_SEND_RETRIES > 1:
                            print(f"         Sending (attempt {attempt}/{MAX_SEND_RETRIES})...")
                        pwk.sendwhatmsg_instantly(
                            phone_no=number,
                            message=msg,
                            wait_time=TAB_OPEN_WAIT,
                            tab_close=False,           # keep tab open for file attachment
                            close_time=3,
                        )
                        whatsapp_tab_open = True
                    else:
                        quoted = urllib.parse.quote_plus(msg)
                        send_url = f"https://web.whatsapp.com/send?phone={number}&text={quoted}&app_absent=0"
                        pyautogui.hotkey("alt", "d")
                        time.sleep(0.2)
                        pyperclip.copy(send_url)
                        pyautogui.hotkey("ctrl", "v")
                        time.sleep(0.1)
                        pyautogui.press("enter")
                        time.sleep(TAB_OPEN_WAIT)
                        pyautogui.press("enter")

                elif mode == "gui":
                    # Ensure WhatsApp Web is open once
                    if index == 1 and not whatsapp_tab_open:
                        webbrowser.open_new_tab("https://web.whatsapp.com")
                        time.sleep(TAB_OPEN_WAIT)
                        whatsapp_tab_open = True

                    # GUI flow: open chat search, paste number, open chat, paste message
                    pyautogui.hotkey("ctrl", "k")
                    time.sleep(0.3)
                    pyperclip.copy(number)
                    pyautogui.hotkey("ctrl", "v")
                    time.sleep(0.2)
                    pyautogui.press("enter")
                    time.sleep(TAB_OPEN_WAIT)
                    pyperclip.copy(msg)
                    pyautogui.hotkey("ctrl", "v")
                    time.sleep(0.2)
                    pyautogui.press("enter")

                else:  # auto: try url first, fallback to gui
                    try:
                        if index == 1 and not whatsapp_tab_open:
                            pwk.sendwhatmsg_instantly(
                                phone_no=number,
                                message=msg,
                                wait_time=TAB_OPEN_WAIT,
                                tab_close=False,
                                close_time=3,
                            )
                            whatsapp_tab_open = True
                        else:
                            quoted = urllib.parse.quote_plus(msg)
                            send_url = f"https://web.whatsapp.com/send?phone={number}&text={quoted}&app_absent=0"
                            pyautogui.hotkey("alt", "d")
                            time.sleep(0.2)
                            pyperclip.copy(send_url)
                            pyautogui.hotkey("ctrl", "v")
                            time.sleep(0.1)
                            pyautogui.press("enter")
                            time.sleep(TAB_OPEN_WAIT)
                            pyautogui.press("enter")
                    except Exception:
                        # fallback to gui
                        webbrowser.open_new_tab("https://web.whatsapp.com")
                        time.sleep(TAB_OPEN_WAIT)
                        pyautogui.hotkey("ctrl", "k")
                        time.sleep(0.3)
                        pyperclip.copy(number)
                        pyautogui.hotkey("ctrl", "v")
                        time.sleep(0.2)
                        pyautogui.press("enter")
                        time.sleep(TAB_OPEN_WAIT)
                        pyperclip.copy(msg)
                        pyautogui.hotkey("ctrl", "v")
                        time.sleep(0.2)
                        pyautogui.press("enter")

                print(f"         ✅ Message sent!")
                successful_msg.append(number)
                msg_ok = True
                break
            except Exception as exc:
                last_exc = exc
                print(f"         ❌ Message failed (attempt {attempt}): {exc}")
                if attempt < MAX_SEND_RETRIES:
                    print(f"         Retrying in {SEND_RETRY_DELAY}s...")
                    time.sleep(SEND_RETRY_DELAY)
        if not msg_ok:
            # capture screenshot for debugging and log failure
            shot = capture_screenshot(index, number)
            failed.append((number, f"msg: {last_exc}"))
            log_failure(number, f"msg: {last_exc}", index, shot)

        # Wait a short period after the send button is pressed
        if msg_ok:
            print(f"         Waiting {POST_SEND_WAIT}s after send…")
            time.sleep(POST_SEND_WAIT)

        # ── Step B: Send attachment ──────────────────────────────────
        if msg_ok and attach_path:
            print(f"         📎 Sending attachment …")
            time.sleep(PAGE_LOAD_WAIT)
            file_ok = send_attachment_via_automation(attach_path)
            if file_ok:
                print(f"         ✅ File sent!")
                successful_file.append(number)
            else:
                print(f"         ❌ File attachment failed.")
                shot = capture_screenshot(index, number)
                failed.append((number, "file: automation error"))
                log_failure(number, "file: automation error", index, shot)

        # keep the tab open — do not close per recipient
        print()

        # ── Wait before next recipient ───────────────────────────────
        if index < total:
            print(f"⏳ Waiting {DELAY_BETWEEN_MESSAGES}s …\n")
            time.sleep(DELAY_BETWEEN_MESSAGES)

    # ── Summary ──────────────────────────────────────────────────────
    print("=" * 6)
    print("📊  SUMMARY")
    print(f"    Total recipients  : {total}")
    print(f"    ✅ Messages sent  : {len(successful_msg)}")
    if attach_path:
        print(f"    ✅ Files sent     : {len(successful_file)}")
    print(f"    ❌ Failures       : {len(failed)}")

    if failed:
        print("\n  Failures:")
        for num, reason in failed:
            print(f"    {num}  –  {reason}")

    print("=" * 6)
    # Close WhatsApp tab once after all recipients are processed (optional)
    if CLOSE_TAB_AT_END:
        try:
            print("Closing WhatsApp tab...")
            time.sleep(1)
            pyautogui.hotkey("ctrl", "w")
        except Exception as exc:
            print(f"Could not close tab automatically: {exc}")

    print("🎉  Done!")


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WhatsApp Bulk Sender options")
    parser.add_argument("--mode", choices=["auto", "url", "gui"], default="auto",
                        help="Send mode: auto (try url then gui), url (use web URL), gui (use UI search)")
    parser.add_argument("--tab-wait", type=int, dest="tab_wait",
                        help="Override TAB_OPEN_WAIT (seconds)")
    parser.add_argument("--post-send-wait", type=int, dest="post_send_wait",
                        help="Override POST_SEND_WAIT (seconds)")
    parser.add_argument("--delay", type=int, dest="delay_between",
                        help="Override DELAY_BETWEEN_MESSAGES (seconds)")
    parser.add_argument("--keep-open", action="store_true",
                        help="Keep WhatsApp tab open at the end (do not close)")

    args = parser.parse_args()

    # Apply CLI overrides
    globals()["SEND_MODE"] = args.mode
    if args.tab_wait is not None:
        globals()["TAB_OPEN_WAIT"] = args.tab_wait
    if args.post_send_wait is not None:
        globals()["POST_SEND_WAIT"] = args.post_send_wait
    if args.delay_between is not None:
        globals()["DELAY_BETWEEN_MESSAGES"] = args.delay_between
    if args.keep_open:
        globals()["CLOSE_TAB_AT_END"] = False

    send_bulk()
