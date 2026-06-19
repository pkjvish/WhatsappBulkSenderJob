# WhatsApp Bulk Sender — Selenium Edition

This replaces the old `pyautogui` + image-matching version. The old approach
broke whenever your screen resolution, browser zoom, window size, or
WhatsApp's theme changed, because it depended on matching a screenshot of
the "+" button and clicking screen pixels. This version drives the browser
directly through Selenium, so every action targets a real page element
instead of a pixel coordinate.

| Old approach | New approach |
|---|---|
| Find "+" button by matching `plus_btn.png` against a screenshot | Find the attach button by its HTML attribute |
| Click screen coordinates | Click the actual DOM element |
| Paste file path into an OS file-picker dialog via clipboard + keystrokes | Send the file path directly to the hidden `<input type="file">` element |
| Breaks if resolution/zoom/theme changes | Unaffected by resolution, zoom, or theme |

`plus_btn.png`, `capture_plus_btn.py`, and `test_plus_btn.py` are no longer
needed — you can delete them.

## 1. Install requirements

You need Google Chrome installed. Then:

```bash
pip install -r requirements.txt
```

Selenium 4.18+ auto-downloads the matching `chromedriver` the first time you
run the script, so there's no separate driver install step.

## 2. Fill in your data

- `numberMessage.csv` — one recipient per line: `+91XXXXXXXXXX,"message text"`
  (the message can safely contain commas as long as it's wrapped in quotes).
- `resume.pdf` — the file that gets sent to every recipient after their message.
  Replace it with any file you want, or disable attachments entirely with
  the `--no-attachment` flag.

## 3. Run it

```bash
python whatsapp_selenium_sender.py
```

**First run only:** a Chrome window opens to WhatsApp Web and shows a QR
code. Scan it with your phone like you normally would. Your session is
saved in `./whatsapp_chrome_profile`, so future runs skip the QR step
entirely.

Useful flags:

```bash
python whatsapp_selenium_sender.py --delay 12        # 12s between recipients
python whatsapp_selenium_sender.py --no-attachment   # text only, no file
```

## 4. Logs and failures

- `run_logs/failures.csv` — every failed send, with a reason.
- `run_logs/screenshot_*.png` — a real browser screenshot taken at the
  moment of failure, useful for diagnosing what WhatsApp's UI was showing.

## If something stops matching (WhatsApp UI changes)

WhatsApp periodically tweaks its internal HTML. At the top of
`whatsapp_selenium_sender.py` there's a `SEL` dictionary where every UI
element (compose box, send button, attach button, etc.) maps to a *list* of
fallback selectors that are tried in order — so a single tweak usually
won't break anything. If every fallback in a list ever stops matching:

1. Open `web.whatsapp.com` in Chrome.
2. Right-click the element in question → **Inspect**.
3. Note its `aria-label`, `data-icon`, or other stable attribute.
4. Add it to the matching list in `SEL`.

## Notes

- Keep `DELAY_BETWEEN_MESSAGES` generous (8s+) to avoid WhatsApp rate-limiting
  or flagging your account for spam-like behavior.
- The script intentionally does **not** run headless — WhatsApp Web behaves
  unreliably without a visible browser window.
- Sending unsolicited bulk messages can violate WhatsApp's Terms of Service
  and risks your number being banned; only message people who've consented
  to receive messages from you.
