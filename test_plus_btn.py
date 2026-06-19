import pyautogui

for confidence in (0.8, 0.7, 0.6, 0.5):
    loc = pyautogui.locateOnScreen("plus_btn.png", confidence=confidence)
    if loc:
        print(f"Found at {loc} with confidence={confidence}")
        break
else:
    print("NOT FOUND at any confidence level")
