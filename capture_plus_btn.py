"""
Run this script, then hover your mouse over the + button in WhatsApp Web
and press Ctrl+S to save a cropped screenshot of it as plus_btn.png
"""
import pyautogui
import keyboard
import time
from PIL import ImageGrab

print("Hover your mouse over the + button in WhatsApp Web, then press Ctrl+S ...")

keyboard.wait("ctrl+s")

x, y = pyautogui.position()
print(f"Captured position: ({x}, {y})")

# Crop a 40x40 box around the cursor
box = (x - 20, y - 20, x + 20, y + 20)
img = ImageGrab.grab(bbox=box)
img.save("plus_btn.png")
print(f"Saved plus_btn.png  (40x40 px around {x},{y})")
