import re
import json
import sounddevice as sd
import numpy as np
import speech_recognition as sr
import os
import sys
import winreg
import ctypes
import threading
import time
import tkinter as tk
from tkinter import messagebox
import requests
import uuid
import comtypes.client
import comtypes
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

# System Tray support
try:
    import pystray
    from PIL import Image, ImageDraw
    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False

# Helper function to get resource path for PyInstaller or script
def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

# Windows Registry Auto-Start on PC boot
def set_auto_start(enable=True):
    try:
        key = winreg.HKEY_CURRENT_USER
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(key, key_path, 0, winreg.KEY_ALL_ACCESS) as reg_key:
            if getattr(sys, 'frozen', False):
                app_path = f'"{sys.executable}" --autostart'
            else:
                app_path = f'"{sys.executable}" "{os.path.abspath(__file__)}" --autostart'
            if enable:
                winreg.SetValueEx(reg_key, "VoiceToControl", 0, winreg.REG_SZ, app_path)
            else:
                try:
                    winreg.DeleteValue(reg_key, "VoiceToControl")
                except FileNotFoundError:
                    pass
    except Exception as e:
        print("Auto-start setup error:", e)

# ==========================================
# APP / PUBLISHER INFO
# ==========================================
APP_NAME = "Hackworld Voice Controller"
PUBLISHER_NAME = "Edu Social Hub"
APP_VERSION = "1.0.0"

# ==========================================
# LICENSE VERIFICATION API (Hostinger PHP endpoint)
# ==========================================
VERIFY_API_URL = "https://edusocialhub.in/computer_app/voice_to_control/verify.php"
# ==========================================

try:
    from vosk import Model as VoskModel, KaldiRecognizer
    VOSK_LIB_AVAILABLE = True
except ImportError:
    VOSK_LIB_AVAILABLE = False

recognizer = sr.Recognizer()

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
BLOCK_DURATION = 0.1
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_DURATION)
SILENCE_THRESHOLD = 150 # Increased microphone sensitivity threshold
SILENCE_DURATION = 0.4

VOSK_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vosk-model")
_vosk_model = None
MIC_DEVICE_INDEX = None
_resolved_mic_device = "unset"

WORD_NUMBERS = {
    "one": 1, "won": 1, "two": 2, "to": 2, "too": 2, "three": 3, "four": 4, "for": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "ate": 8, "nine": 9, "ten": 10,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100
}

LETTERS = "abcdefghijklmnopqrstuvwxyz"

SHUTDOWN_WORDS = ["shutdown", "shut down", "turn off computer"]
RESTART_WORDS = ["restart", "reboot"]
HIBERNATE_WORDS = ["hibernate", "sleep mode"]
LOCK_WORDS = ["lock computer", "lock screen", "lock"]
STOP_WORDS = ["stop", "cancel", "wait", "abort"]
CLOSE_YOUTUBE_WORDS = ["close youtube", "close tab", "exit youtube"]
YOUTUBE_WORDS = ["open youtube", "start youtube", "youtube", "launch youtube", "yt", "open yt"]
YOUTUBE_SEARCH_TRIGGERS = ["youtube search", "search on youtube", "search"]
PLAY_TRIGGERS = ["play video", "play"]
BACK_WORDS = ["go back", "back"]
SWIPE_DOWN_WORDS = ["swipe down", "previous video", "go down"]
SWIPE_UP_WORDS = ["swipe up", "swipe", "next video", "go up"]
SCROLL_DOWN_WORDS = ["scroll down", "page down"]
SCROLL_UP_WORDS = ["scroll up", "page up"]
PAUSE_WORDS = ["pause video", "pause", "stop video"]
RESUME_WORDS = ["resume video", "resume", "play paused video"]
VOLUME_WORDS = ["volume", "mute", "unmute", "percent", "sound"]

speak_lock = threading.Lock()
mic_lock = threading.Lock()
driver_lock = threading.Lock()
volume_lock = threading.Lock()

current_video_elements = []
driver = None

ai_thread_running = False
ai_stop_event = threading.Event()

# ==========================================
# SUPER FAST TTS ENGINE (Direct Windows API)
# ==========================================
def speak(text):
    """Speaks instantly in a background thread using direct SAPI5 COM object."""
    def _speak_task():
        with speak_lock:
            try:
                comtypes.CoInitialize()
                engine = comtypes.client.CreateObject("SAPI.SpVoice")
                engine.Speak(text)
                comtypes.CoUninitialize()
            except Exception as e:
                print("TTS Error:", e)
    
    threading.Thread(target=_speak_task, daemon=True).start()

def parse_number_from_text(text):
    if not text: return None
    digits = re.search(r"\d+", text)
    if digits: return int(digits.group())
    for word in text.split():
        if word in WORD_NUMBERS: return WORD_NUMBERS[word]
    return None

def is_pure_number(text):
    text = (text or "").strip()
    if not text: return False
    if text.isdigit(): return True
    return text in WORD_NUMBERS

def letter_to_index(letter):
    if not letter: return None
    pos = LETTERS.find(letter)
    return pos + 1 if pos != -1 else None

def contains_any(text, word_list):
    return any(word in text for word in word_list)

def get_driver():
    global driver
    if driver is None:
        try:
            with driver_lock:
                service = Service(ChromeDriverManager().install())
                options = webdriver.ChromeOptions()
                options.add_argument("--start-maximized")
                options.add_experimental_option('excludeSwitches', ['enable-logging'])
                driver = webdriver.Chrome(service=service, options=options)
        except Exception as e:
            print("Could not start Chrome:", e)
            driver = None
    return driver

# ==========================================
# VOLUME CONTROL (FIXED - THREAD LOCAL)
# ------------------------------------------
# ROOT CAUSE OF "volume control failed":
# The voice assistant runs in a NEW background thread every single time
# you press Start (toggle_ai -> threading.Thread(target=run_voice_assistant)).
# The old code cached the pycaw/COM volume interface in a single GLOBAL
# variable, and only called comtypes.CoInitializeEx() the FIRST time it
# was ever created - i.e. only on the FIRST thread that ever asked for it.
#
# The moment you Stop and Start again (or the app auto-restarts the
# assistant), a brand-new OS thread runs the assistant. COM was NEVER
# initialized on that new thread, but the code just handed it back the
# cached interface pointer created on the old (now-dead) thread. Windows
# COM requires every thread that touches an interface to have its own
# CoInitializeEx call - so calls from the new thread failed
# (CO_E_NOTINITIALIZED / silent failures), which is exactly the
# "volume control failed" bug.
#
# FIX: use threading.local() instead of a plain global, so every thread
# gets its OWN CoInitializeEx call and its OWN cached interface pointer.
# ==========================================
_volume_local = threading.local()

def get_volume_interface():
    with volume_lock:
        cached = getattr(_volume_local, "interface", None)
        if cached is not None:
            return cached
        try:
            comtypes.CoInitialize()  # STA apartment - matches pycaw's expected usage
        except OSError:
            # Already initialized on this thread - safe to ignore
            pass
        device = AudioUtilities.GetSpeakers()
        vol_interface = device.EndpointVolume.QueryInterface(IAudioEndpointVolume)
        _volume_local.interface = vol_interface
        return vol_interface

def set_volume(percentage):
    try:
        volume = get_volume_interface()
        scalar = percentage / 100.0
        scalar = max(0.0, min(1.0, scalar))
        volume.SetMasterVolumeLevelScalar(scalar, None)
        speak(f"Volume set to {percentage} percent")
    except Exception as e:
        print("Volume set error:", e)
        speak("Failed to set volume")

def change_volume(delta):
    try:
        volume = get_volume_interface()
        current = volume.GetMasterVolumeLevelScalar()
        new_vol = max(0.0, min(1.0, current + (delta / 100.0)))
        volume.SetMasterVolumeLevelScalar(new_vol, None)
        speak(f"Volume changed to {int(new_vol * 100)} percent")
    except Exception as e:
        print("Volume change error:", e)
        speak("Failed to change volume")

def mute_volume(mute=True):
    try:
        volume = get_volume_interface()
        volume.SetMute(1 if mute else 0, None)
        speak("Computer Muted" if mute else "Computer Unmuted")
    except Exception as e:
        print("Mute error:", e)
        speak("Failed to mute")

def handle_volume_command(text):
    if "unmute" in text:
        mute_volume(False)
        return
    if "mute" in text:
        mute_volume(True)
        return
    
    num = parse_number_from_text(text)
    if "full" in text or "max" in text or "100" in text:
        set_volume(100)
    elif num is not None:
        if "increase" in text or "badhao" in text or "up" in text or "more" in text:
            change_volume(num)
        elif "decrease" in text or "kam" in text or "down" in text or "less" in text:
            change_volume(-num)
        else:
            set_volume(num)
    else:
        # Default increment/decrement if no number is spoken
        if "increase" in text or "up" in text or "badhao" in text:
            change_volume(10)
        elif "decrease" in text or "down" in text or "kam" in text:
            change_volume(-10)
        else:
            speak("Please specify volume percentage")

def resolve_mic_device():
    global _resolved_mic_device
    if _resolved_mic_device != "unset": return _resolved_mic_device
    try: _resolved_mic_device = sd.default.device[0]
    except Exception: _resolved_mic_device = None
    return _resolved_mic_device

def capture_until_silence(max_wait_seconds=5, max_phrase_seconds=6):
    silence_chunk_limit = max(1, int(SILENCE_DURATION / BLOCK_DURATION))
    max_wait_chunks = max(1, int(max_wait_seconds / BLOCK_DURATION))
    max_phrase_chunks = max(1, int(max_phrase_seconds / BLOCK_DURATION))
    frames = []
    triggered = False
    silence_chunks = 0
    waited_chunks = 0
    try:
        with mic_lock:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16',
                                 blocksize=BLOCK_SIZE, device=resolve_mic_device()) as stream:
                while True:
                    if ai_stop_event.is_set(): return None
                    data, _ = stream.read(BLOCK_SIZE)
                    peak_amplitude = np.abs(data).max()
                    mean_amplitude = np.abs(data).mean()
                    if not triggered:
                        waited_chunks += 1
                        if peak_amplitude > SILENCE_THRESHOLD:
                            triggered = True
                            frames.append(data.copy())
                        elif waited_chunks > max_wait_chunks:
                            return None
                    else:
                        frames.append(data.copy())
                        if mean_amplitude < SILENCE_THRESHOLD:
                            silence_chunks += 1
                        else:
                            silence_chunks = 0
                        if silence_chunks > silence_chunk_limit or len(frames) > max_phrase_chunks:
                            break
    except Exception:
        return None
    if not frames: return None
    return np.concatenate(frames, axis=0)

def get_vosk_model():
    global _vosk_model
    if _vosk_model is None and VOSK_LIB_AVAILABLE and os.path.isdir(VOSK_MODEL_PATH):
        try: _vosk_model = VoskModel(VOSK_MODEL_PATH)
        except Exception: _vosk_model = None
    return _vosk_model

def get_vosk_recognizer():
    global _vosk_recognizer
    model = get_vosk_model()
    if model is None: return None
    if '_vosk_recognizer' not in globals() or _vosk_recognizer is None:
        _vosk_recognizer = KaldiRecognizer(model, SAMPLE_RATE)
    else: _vosk_recognizer.Reset()
    return _vosk_recognizer

def recognize_audio(audio_np):
    if audio_np is None: return ""
    rec = get_vosk_recognizer()
    if rec is not None:
        try:
            rec.AcceptWaveform(audio_np.tobytes())
            result = json.loads(rec.FinalResult())
            return (result.get("text") or "").lower()
        except Exception: pass
    try:
        audio_data = sr.AudioData(audio_np.tobytes(), SAMPLE_RATE, SAMPLE_WIDTH)
        return recognizer.recognize_google(audio_data, language="en-IN").lower()
    except Exception: return ""

def listen_once(max_wait_seconds=5, max_phrase_seconds=6):
    audio_np = capture_until_silence(max_wait_seconds, max_phrase_seconds)
    return recognize_audio(audio_np)

def listen_for_stop(stop_event, cancel_flag, listen_seconds):
    end_time = time.time() + listen_seconds
    while not stop_event.is_set():
        remaining = end_time - time.time()
        if remaining <= 0: break
        heard = listen_once(max_wait_seconds=min(1.2, remaining), max_phrase_seconds=1.5)
        if contains_any(heard, STOP_WORDS):
            cancel_flag["cancelled"] = True
            stop_event.set()

def show_countdown_and_confirm(action_label, seconds=10):
    cancel_flag = {"cancelled": False}
    stop_event = threading.Event()
    speak(f"{action_label} in {seconds} seconds. Say stop to cancel.")
    listener_thread = threading.Thread(target=listen_for_stop, args=(stop_event, cancel_flag, seconds), daemon=True)
    listener_thread.start()
    
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    try: root.attributes("-topmost", True)
    except Exception: pass
    root.configure(bg="black")
    
    label = tk.Label(root, text="", font=("Segoe UI", 60, "bold"), fg="white", bg="black")
    label.pack(expand=True)
    sub_label = tk.Label(root, text='Say "STOP" to cancel', font=("Segoe UI", 22), fg="#999999", bg="black")
    sub_label.pack(pady=20)
    
    remaining = {"time": seconds}
    def update_countdown():
        if cancel_flag["cancelled"]:
            label.config(text="Cancelled", fg="#ff4444")
            sub_label.config(text="")
            root.after(1000, root.destroy)
            return
        if remaining["time"] <= 0:
            root.destroy()
            return
        label.config(text=f"{action_label} in {remaining['time']}...")
        remaining["time"] -= 1
        root.after(1000, update_countdown)
        
    update_countdown()
    root.mainloop()
    stop_event.set()
    listener_thread.join(timeout=1)
    
    if cancel_flag["cancelled"]:
        speak("Action Cancelled")
        return False
    return True

def shutdown_pc():
    if show_countdown_and_confirm("Shutting down the computer"):
        speak("Goodbye. Shutting down the computer now.")
        os.system("shutdown /s /t 0")

def restart_pc():
    if show_countdown_and_confirm("Restarting the computer"):
        speak("Restarting the computer now.")
        os.system("shutdown /r /t 0")

def hibernate_pc():
    if show_countdown_and_confirm("Hibernating the computer"):
        speak("Hibernating the computer now.")
        os.system("shutdown /h")

def lock_pc():
    speak("Locking the computer now.")
    ctypes.windll.user32.LockWorkStation()

def label_visible_videos(max_results=20, silent=True):
    global current_video_elements
    d = driver
    if d is None: return
    try:
        with driver_lock:
            elems = [e for e in d.find_elements(By.ID, "video-title") if e.is_displayed()][:max_results]
            current_video_elements = elems
            d.execute_script("document.querySelectorAll('.voice-assistant-badge').forEach(function(b){ b.remove(); });")
            for i, el in enumerate(elems, start=1):
                letter_label = str(i)
                d.execute_script("""
                    var el = arguments[0];
                    var label = arguments[1];
                    var rect = el.getBoundingClientRect();
                    var badge = document.createElement('div');
                    badge.innerText = label;
                    badge.className = 'voice-assistant-badge';
                    badge.style.position = 'absolute';
                    badge.style.zIndex = '999999';
                    badge.style.background = '#ff0000';
                    badge.style.color = '#ffffff';
                    badge.style.fontSize = '20px';
                    badge.style.fontWeight = 'bold';
                    badge.style.padding = '4px 10px';
                    badge.style.borderRadius = '6px';
                    badge.style.fontFamily = 'Arial, sans-serif';
                    badge.style.pointerEvents = 'none';
                    badge.style.left = (rect.left + window.scrollX) + 'px';
                    badge.style.top = (rect.top + window.scrollY - 6) + 'px';
                    document.body.appendChild(badge);
                """, el, letter_label)
    except Exception: pass

def video_label_refresher():
    while not ai_stop_event.is_set():
        time.sleep(3)
        try:
            d = driver
            if d is not None and "youtube.com" in (d.current_url or ""):
                label_visible_videos(silent=True)
        except Exception: pass

def play_labeled_video(index):
    global current_video_elements
    if not current_video_elements or index is None or index > len(current_video_elements):
        speak("Invalid selection on screen.")
        return
    try:
        speak(f"Playing video number {index}")
        with driver_lock: current_video_elements[index - 1].click()
        time.sleep(1.5)
        label_visible_videos()
    except Exception: speak("Could not play video")

def open_youtube_home():
    speak("Opening YouTube now")
    d = get_driver()
    if d:
        with driver_lock: d.get("https://www.youtube.com")
        time.sleep(2)
        label_visible_videos()

def youtube_search(query):
    query = (query or "").strip()
    if not query: return
    speak(f"Searching YouTube for {query}")
    d = get_driver()
    if not d: return
    url = "https://www.youtube.com/results?search_query=" + query.replace(" ", "+")
    with driver_lock: d.get(url)
    time.sleep(2)
    label_visible_videos()

def play_youtube_video(query):
    query = (query or "").strip()
    if not query:
        resume_video()
        return
    speak(f"Finding and Playing {query}")
    d = get_driver()
    if not d: return
    url = "https://www.youtube.com/results?search_query=" + query.replace(" ", "+")
    with driver_lock:
        d.get(url)
        try:
            first_result = WebDriverWait(d, 8).until(EC.presence_of_element_located((By.ID, "video-title")))
            first_result.click()
        except TimeoutException: pass

def swipe_next():
    speak("Swiping to next video")
    d = get_driver()
    if not d: return
    try:
        with driver_lock: d.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_DOWN)
    except Exception: pass
    time.sleep(0.4)
    label_visible_videos()

def swipe_previous():
    speak("Going to previous video")
    d = get_driver()
    if not d: return
    try:
        with driver_lock: d.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_UP)
    except Exception: pass
    time.sleep(0.4)
    label_visible_videos()

def scroll_down():
    speak("Scrolling down")
    d = get_driver()
    if not d: return
    try:
        with driver_lock: d.execute_script("window.scrollBy(0, Math.round(window.innerHeight * 0.8));")
    except Exception: pass
    time.sleep(0.5)
    label_visible_videos()

def scroll_up():
    speak("Scrolling up")
    d = get_driver()
    if not d: return
    try:
        with driver_lock: d.execute_script("window.scrollBy(0, -Math.round(window.innerHeight * 0.8));")
    except Exception: pass
    time.sleep(0.5)
    label_visible_videos()

def pause_video():
    speak("Video paused")
    d = get_driver()
    if not d: return
    try:
        with driver_lock: d.execute_script("var v = document.querySelector('video'); if (v) { v.pause(); }")
    except Exception: pass

def resume_video():
    speak("Resuming video")
    d = get_driver()
    if not d: return
    try:
        with driver_lock: d.execute_script("var v = document.querySelector('video'); if (v) { v.play(); }")
    except Exception: pass

def back_page():
    speak("Going back")
    d = get_driver()
    if not d: return
    try:
        with driver_lock: d.back()
        time.sleep(0.6)
        label_visible_videos()
    except Exception: pass

def close_youtube():
    speak("Closing YouTube")
    global driver
    if driver is None: return
    try:
        with driver_lock:
            driver.close()
            handles = driver.window_handles
            if handles: driver.switch_to.window(handles[-1])
            else:
                driver.quit()
                driver = None
    except Exception:
        try: driver.quit()
        except Exception: pass
        driver = None

def extract_query(text, triggers):
    for trigger in triggers:
        if trigger in text: return text.split(trigger, 1)[1].strip()
    return None

def run_voice_assistant(config, is_premium):
    global ai_thread_running
    ai_thread_running = True
    ai_stop_event.clear()
    
    features = config.get("features", {"youtube": True, "volume": True, "system": True})
    username = config.get("name", "Santosh Kumar")
    
    if get_vosk_model() is not None:
        get_vosk_recognizer()
        
    speak(f"Welcome to computer world {username}")

    threading.Thread(target=video_label_refresher, daemon=True).start()

    while not ai_stop_event.is_set():
        try:
            text = listen_once()
            if not text or text.strip() in ["hello", "hi", "yeah", "the", "ok"]:
                continue

            if contains_any(text, STOP_WORDS):
                speak("I am standing by.")
                continue

            if current_video_elements and is_pure_number(text):
                if features.get("youtube", True): play_labeled_video(parse_number_from_text(text))
            elif contains_any(text, CLOSE_YOUTUBE_WORDS):
                if features.get("youtube", True): close_youtube()
            elif contains_any(text, BACK_WORDS):
                if features.get("youtube", True): back_page()
            elif contains_any(text, PAUSE_WORDS):
                if features.get("youtube", True): pause_video()
            elif contains_any(text, RESUME_WORDS):
                if features.get("youtube", True): resume_video()
            elif contains_any(text, SCROLL_DOWN_WORDS):
                if features.get("youtube", True): scroll_down()
            elif contains_any(text, SCROLL_UP_WORDS):
                if features.get("youtube", True): scroll_up()
            elif contains_any(text, SWIPE_DOWN_WORDS):
                if features.get("youtube", True): swipe_previous()
            elif contains_any(text, SWIPE_UP_WORDS):
                if features.get("youtube", True): swipe_next()
            elif contains_any(text, PLAY_TRIGGERS):
                if features.get("youtube", True): play_youtube_video(extract_query(text, PLAY_TRIGGERS))
            elif contains_any(text, YOUTUBE_SEARCH_TRIGGERS):
                if features.get("youtube", True): youtube_search(extract_query(text, YOUTUBE_SEARCH_TRIGGERS))
            elif contains_any(text, YOUTUBE_WORDS):
                if features.get("youtube", True): open_youtube_home()
            
            elif contains_any(text, VOLUME_WORDS) or ("increase" in text) or ("decrease" in text):
                if not features.get("volume", True): continue
                if not is_premium:
                    speak("Volume control is a premium feature. Please upgrade.")
                    continue
                handle_volume_command(text)
                
            elif contains_any(text, RESTART_WORDS):
                if not features.get("system", True): continue
                if not is_premium:
                    speak("System control is a premium feature.")
                    continue
                restart_pc()
                
            elif contains_any(text, SHUTDOWN_WORDS):
                if not features.get("system", True): continue
                if not is_premium:
                    speak("System control is a premium feature.")
                    continue
                shutdown_pc()
                
            elif contains_any(text, HIBERNATE_WORDS):
                if not features.get("system", True): continue
                if not is_premium:
                    speak("System control is a premium feature.")
                    continue
                hibernate_pc()
                
            elif contains_any(text, LOCK_WORDS):
                if not features.get("system", True): continue
                if not is_premium:
                    speak("System control is a premium feature.")
                    continue
                lock_pc()

        except KeyboardInterrupt:
            break
        except Exception as e:
            print("Listening error:", e)
            pass

    ai_thread_running = False

class HackworldApp:
    def __init__(self, root, autostart=False):
        self.root = root
        self.root.title("Hackworld Controller Dashboard")
        self.root.geometry("700x600")
        self.root.configure(bg="#0f172a")
        self.root.resizable(False, False)
        
        self.set_app_icon()
        set_auto_start(True)
        
        self.config = self.load_config()
        self.features = self.config.get("features", {"youtube": True, "volume": True, "system": True})
        self.features["youtube"] = True 
        self.is_premium = False
        
        self.setup_ui()
        self.setup_tray_icon()
        
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_background)
        
        if autostart:
            self.root.withdraw()
            self.root.after(1000, self.auto_start_ai)
        else:
            self.root.after(1000, self.auto_start_ai)

    def set_app_icon(self):
        icon_path = get_resource_path("logo.ico")
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception as e:
                print("Could not set icon:", e)

    def hide_to_background(self):
        self.root.withdraw()

    def show_dashboard(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def quit_entire_app(self):
        global ai_thread_running
        ai_stop_event.set()
        ai_thread_running = False
        if hasattr(self, 'tray_icon') and self.tray_icon:
            try: self.tray_icon.stop()
            except Exception: pass
        self.root.destroy()
        sys.exit(0)

    def setup_tray_icon(self):
        if not PYSTRAY_AVAILABLE:
            return
        try:
            icon_path = get_resource_path("logo.ico")
            if os.path.exists(icon_path):
                image = Image.open(icon_path)
            else:
                image = Image.new('RGB', (64, 64), color=(14, 165, 233))
                d = ImageDraw.Draw(image)
                d.rectangle([16, 16, 48, 48], fill=(255, 255, 255))

            menu = pystray.Menu(
                pystray.MenuItem("Open Dashboard", lambda: self.root.after(0, self.show_dashboard)),
                pystray.MenuItem("Exit Completely", lambda: self.root.after(0, self.quit_entire_app))
            )
            self.tray_icon = pystray.Icon("VoiceControl", image, "Hackworld Voice Controller", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            print("Tray Icon setup error:", e)

    def auto_start_ai(self):
        self.verify_and_save(silent=True)
        if not ai_thread_running:
            self.toggle_ai()

    def get_config_path(self):
        appdata = os.environ.get('APPDATA')
        config_dir = os.path.join(appdata, "VoiceController")
        if not os.path.exists(config_dir): os.makedirs(config_dir)
        return os.path.join(config_dir, "user_config.json")

    def load_config(self):
        config_path = self.get_config_path()
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    if "features" in cfg:
                        cfg["features"]["youtube"] = True 
                    return cfg
            except Exception: pass
        return {"name": "user", "product_key": "", "features": {"youtube": True, "volume": True, "system": True}}

    def verify_db_key(self, key, username):
        if key == "DEMO-2026-WORLD-KEY":
            return True, "Demo Lifetime Access"

        hwid = str(uuid.getnode())
        try:
            response = requests.post(
                VERIFY_API_URL,
                data={"key": key, "hwid": hwid, "username": username},
                timeout=10
            )
            result = response.json()
            return bool(result.get("status")), result.get("msg", "Unknown response from server")
        except requests.exceptions.RequestException as e:
            return False, f"Connection Failed: {e}"
        except ValueError:
            return False, "Invalid response from license server"
        except Exception as e:
            return False, f"Verification Error: {e}"

    def verify_and_save(self, silent=False):
        new_name = self.name_entry.get().strip()
        new_key = self.key_entry.get().strip()
        
        if not new_name and not silent:
            messagebox.showwarning("Warning", "Username cannot be empty!")
            return
            
        self.status_label.config(text="Verifying Key with Server...", fg="#38bdf8")
        self.root.update()
        
        if not new_key:
            self.is_premium = False
            self.status_label.config(text="Saved in Free Mode (Only YouTube available).", fg="#fbbf24")
        else:
            is_valid, msg = self.verify_db_key(new_key, new_name)
            self.is_premium = is_valid
            if is_valid:
                self.status_label.config(text=f"Success: {msg}", fg="#10b981")
                self.features = {"youtube": True, "volume": True, "system": True}
                self.refresh_toggles()
            else:
                self.status_label.config(text=f"Failed: {msg} (Free Mode Active)", fg="#ef4444")
                self.is_premium = False

        data_to_save = {"name": new_name, "product_key": new_key, "features": self.features}
        try:
            with open(self.get_config_path(), "w", encoding="utf-8") as f:
                json.dump(data_to_save, f, indent=4)
        except Exception: pass
        
        self.config = data_to_save

    def toggle_feature(self, feature_name):
        if not self.is_premium and feature_name != "youtube":
            messagebox.showinfo("Premium Required", "You must verify a Premium Key to enable System or Volume controls.")
            return
            
        self.features[feature_name] = not self.features[feature_name]
        self.refresh_toggles()
        
        self.config["features"] = self.features
        try:
            with open(self.get_config_path(), "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except Exception: pass

    def refresh_toggles(self):
        for f_key, btn in self.toggle_btns.items():
            if self.features.get(f_key, False):
                btn.config(text="✓ ENABLED", bg="#10b981", fg="white", activebackground="#059669")
            else:
                btn.config(text="✗ DISABLED", bg="#ef4444", fg="white", activebackground="#dc2626")

    def toggle_ai(self):
        global ai_thread_running
        if ai_thread_running:
            ai_stop_event.set()
            self.start_btn.config(text="▶ START VOICE ASSISTANT", bg="#0ea5e9", activebackground="#0284c7")
            self.status_label.config(text="Voice Assistant Stopped.", fg="#fbbf24")
        else:
            threading.Thread(target=run_voice_assistant, args=(self.config, self.is_premium), daemon=True).start()
            self.start_btn.config(text="⏹ STOP VOICE ASSISTANT", bg="#ef4444", activebackground="#dc2626")
            self.status_label.config(text="Listening for Voice Commands...", fg="#10b981")

    def setup_ui(self):
        header_frame = tk.Frame(self.root, bg="#1e293b", pady=20)
        header_frame.pack(fill="x")
        
        tk.Label(header_frame, text="HACKWORLD VOICE CONTROLLER", font=("Segoe UI Black", 18), fg="#38bdf8", bg="#1e293b").pack()
        tk.Label(header_frame, text="Manage Permissions & Access Features", font=("Segoe UI", 10), fg="#94a3b8", bg="#1e293b").pack()

        main_frame = tk.Frame(self.root, bg="#0f172a", padx=30, pady=15)
        main_frame.pack(fill="both", expand=True)

        info_frame = tk.LabelFrame(main_frame, text=" License & Profile Verification ", font=("Segoe UI", 12, "bold"), fg="#e2e8f0", bg="#0f172a", bd=2, padx=15, pady=15)
        info_frame.pack(fill="x", pady=(0, 15))

        tk.Label(info_frame, text="Username:", font=("Segoe UI", 11), fg="#cbd5e1", bg="#0f172a").grid(row=0, column=0, sticky="w", pady=5)
        self.name_entry = tk.Entry(info_frame, font=("Segoe UI", 11), width=35, bg="#334155", fg="white", insertbackground="white", relief="flat")
        self.name_entry.insert(0, self.config.get("name", "User"))
        self.name_entry.grid(row=0, column=1, padx=15, pady=5)

        tk.Label(info_frame, text="Product Key:", font=("Segoe UI", 11), fg="#cbd5e1", bg="#0f172a").grid(row=1, column=0, sticky="w", pady=5)
        self.key_entry = tk.Entry(info_frame, font=("Segoe UI", 11), width=35, bg="#334155", fg="white", insertbackground="white", relief="flat")
        self.key_entry.insert(0, self.config.get("product_key", ""))
        self.key_entry.grid(row=1, column=1, padx=15, pady=5)

        verify_btn = tk.Button(info_frame, text="Save & Verify Key", font=("Segoe UI", 9, "bold"), bg="#64748b", fg="white", cursor="hand2", command=self.verify_and_save)
        verify_btn.grid(row=2, column=1, sticky="w", padx=15, pady=5)

        toggles_frame = tk.LabelFrame(main_frame, text=" Voice Features Control ", font=("Segoe UI", 12, "bold"), fg="#e2e8f0", bg="#0f172a", bd=2, padx=15, pady=15)
        toggles_frame.pack(fill="x")

        features_list = [
            ("youtube", "YouTube Navigation (Search, Play, Swipe) [Free]"),
            ("volume", "Volume Control (Mute, % Set) [Premium]"),
            ("system", "System Power (Shutdown, Restart, Lock) [Premium]")
        ]

        self.toggle_btns = {}
        for i, (f_key, f_desc) in enumerate(features_list):
            tk.Label(toggles_frame, text=f_desc, font=("Segoe UI", 11), fg="#cbd5e1", bg="#0f172a").grid(row=i, column=0, sticky="w", pady=8)
            btn = tk.Button(toggles_frame, font=("Segoe UI", 9, "bold"), width=12, relief="flat", cursor="hand2")
            btn.config(command=lambda k=f_key: self.toggle_feature(k))
            self.toggle_btns[f_key] = btn
            btn.grid(row=i, column=1, padx=20, pady=8, sticky="e")
            toggles_frame.grid_columnconfigure(0, weight=1)
            
        self.refresh_toggles()

        footer_frame = tk.Frame(main_frame, bg="#0f172a")
        footer_frame.pack(fill="x", pady=20)

        self.start_btn = tk.Button(footer_frame, text="▶ START VOICE ASSISTANT", font=("Segoe UI", 14, "bold"), bg="#0ea5e9", fg="white", activebackground="#0284c7", activeforeground="white", relief="flat", padx=30, pady=12, cursor="hand2", command=self.toggle_ai)
        self.start_btn.pack(fill="x")

        self.status_label = tk.Label(footer_frame, text="Starting automatic process...", font=("Segoe UI", 11), fg="#94a3b8", bg="#0f172a")
        self.status_label.pack(pady=10)

        publisher_label = tk.Label(footer_frame, text=f"{APP_NAME}  •  v{APP_VERSION}  •  Published by {PUBLISHER_NAME}", font=("Segoe UI", 8), fg="#64748b", bg="#0f172a")
        publisher_label.pack(pady=(6, 0))

if __name__ == "__main__":
    autostart_flag = "--autostart" in sys.argv

    # ==========================================
    # SINGLE INSTANCE CHECK (FIXED)
    # ------------------------------------------
    # BUG: Every time the .exe was opened again (double-click, a stray
    # Startup entry firing again, or the user manually opening it while
    # it was already running quietly in the tray) a WHOLE SECOND process
    # started, which spawned a SECOND run_voice_assistant() thread. Two
    # processes fighting over the same microphone + COM audio interface
    # is what caused random failures (including volume control) and made
    # it look like "the app restarted itself".
    #
    # FIX: use a Windows named Mutex. If one already exists when this
    # process starts, it means another copy is already running - so we
    # tell the user it's already Started and exit, instead of opening a
    # duplicate window / duplicate assistant.
    # ==========================================
    MUTEX_NAME = "Global\\HackworldVoiceControllerSingleInstanceMutex"
    kernel32 = ctypes.windll.kernel32
    _instance_mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    ERROR_ALREADY_EXISTS = 183
    already_running = (kernel32.GetLastError() == ERROR_ALREADY_EXISTS)

    if already_running:
        if not autostart_flag:
            _tmp_root = tk.Tk()
            _tmp_root.withdraw()
            messagebox.showinfo(
                "Hackworld Voice Controller",
                "Started ✅\n\nVoice Assistant is already running in the background.\nCheck the system tray icon."
            )
            _tmp_root.destroy()
        sys.exit(0)
    # ==========================================

    root = tk.Tk()
    icon_path = get_resource_path("logo.ico")
    if os.path.exists(icon_path):
        try:
            root.iconbitmap(icon_path)
        except Exception:
            pass
    app = HackworldApp(root, autostart=autostart_flag)
    root.mainloop()