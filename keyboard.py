"""Types received barcodes into the focused window on this PC."""

import time
import threading

import pyautogui
import pyperclip

_lock = threading.Lock()

pyautogui.PAUSE = 0.02


def type_code(code: str, enter: bool = True, delay: float = 0.5) -> None:
    if delay > 0:
        time.sleep(delay)
    with _lock:
        if code.isascii():
            pyautogui.write(code, interval=0.02)
        else:
            _paste(code)
        if enter:
            pyautogui.press("enter")


def _paste(text: str) -> None:
    previous = None
    try:
        previous = pyperclip.paste()
    except Exception:
        pass
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.15)
    if previous is not None:
        try:
            pyperclip.copy(previous)
        except Exception:
            pass
