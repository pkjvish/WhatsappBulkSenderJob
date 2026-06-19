"""
WhatsApp Bulk Messenger (Message + File Attachment)
---------------------------------------------------
Reads recipients from  numberMessage.txt  in the format:
    +919702309081,Hi Pankaj How are you ?
    +919876543210,Hello Rahul your order is ready!
    +14155552671,Hi John welcome aboard!

Each line = one phone number + one personal message, separated by the
FIRST comma. The message itself may contain commas freely.

Also sends a single attachment file (e.g. abc.txt) to every recipient
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
from datetime import datetime, timedelta

# ──────────────────────────────────────────────
# CONFIGURATION  –  edit these values
# ──────────────────────────────────────────────

INPUT_FILE      = "numberMessage.csv"  # combined number + message file
ATTACHMENT_FILE = "abc.txt"            # file to attach; set None to disable

# Seconds to wait between each recipient (keep ≥ 20 to avoid WA blocks)
DELAY_BETWEEN_MESSAGES = 5

# Seconds for WhatsApp Web to fully load before file-attachment automation
PAGE_LOAD_WAIT = 1

# Seconds pywhatkit holds the tab open (must be enough for the page to load)
TAB_OPEN_WAIT = 2

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
            plus_location = pyautogui.locateOnScreen(PLUS_BTN_IMG, confidence=confidence)
            if plus_location:
                break
        if plus_location is None:
            print("         ⚠️  Could not find + button on screen")
            return False
        pyautogui.click(pyautogui.center(plus_location))
        time.sleep(1)

        # ── 2. Choose "Document" from the popup menu ─────────────────
        pyautogui.press("tab", presses=2, interval=0.2)
        pyautogui.press("enter")
        time.sleep(2)

        # ── 3. Paste file path into OS file-picker ───────────────────
        pyperclip.copy(abs_path)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.5)
        pyautogui.press("enter")     # confirm path
        time.sleep(1)
        pyautogui.press("enter")     # click Open button
        time.sleep(1)

        # ── 4. Send the file ─────────────────────────────────────────
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

    for index, (number, msg) in enumerate(pairs, start=1):

        print(f"[{index}/{total}] ➜  {number}")
        print(f"         Message   : {msg[:70]}{'…' if len(msg) > 70 else ''}")
        if attach_path:
            print(f"         Attachment: {os.path.basename(attach_path)}")

        # ── Step A: Send text message ────────────────────────────────
        send_time    = datetime.now() + timedelta(minutes=2)
        hour, minute = send_time.hour, send_time.minute
        print(f"         Scheduled : {hour:02d}:{minute:02d}")

        msg_ok = False
        try:
            pwk.sendwhatmsg(
                phone_no=number,
                message=msg,
                time_hour=hour,
                time_min=minute,
                wait_time=TAB_OPEN_WAIT,
                tab_close=False,           # keep tab open for file attachment
                close_time=3,
            )
            print(f"         ✅ Message sent!")
            successful_msg.append(number)
            msg_ok = True
        except Exception as exc:
            print(f"         ❌ Message failed: {exc}")
            failed.append((number, f"msg: {exc}"))

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
                failed.append((number, "file: automation error"))

        # Close the browser tab before moving to the next recipient
        time.sleep(2)
        pyautogui.hotkey("ctrl", "w")
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
    print("🎉  Done!")


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────

if __name__ == "__main__":
    send_bulk()
