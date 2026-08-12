import os
import sys
import re
import json
import time
import ctypes
import uuid
import hashlib
import platform
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import sounddevice as sd
import numpy as np
import speech_recognition as sr
import pyttsx3

# Optional Pillow import for automated logo generation
try:
    from PIL import Image, ImageDraw, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Optional MySQL driver import for Hostinger database connection
try:
    import mysql.connector
    MYSQL_AVAILABLE = True
except ImportError:
    try:
        import pymysql as mysql
        MYSQL_AVAILABLE = True
    except ImportError:
        MYSQL_AVAILABLE = False

# Selenium imports for YouTube Automation
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

try:
    from vosk import Model as VoskModel, KaldiRecognizer
    VOSK_LIB_AVAILABLE = True
except ImportError:
    VOSK_LIB_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOGO_ICO_PATH = os.path.join(BASE_DIR, "logo.ico")
VOSK_MODEL_PATH = os.path.join(BASE_DIR, "vosk-model")

DEFAULT_CONFIG = {
    "username": "User",
    "product_key": "DEMO-2026-WORLD-KEY",
    "is_premium": True,
    "db_host": "sql.hostinger.com",
    "db_user": "u305219281_voice_control",
    "db_pass": "Voice_control@2008",
    "db_name": "u305219281_voice_control",
    "voice_speed": 220,
    "mic_index": None
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                merged = DEFAULT_CONFIG.copy()
                merged.update(data)
                return merged
        except Exception:
            pass
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        print("Failed to save config:", e)

APP_CONFIG = load_config()

def ensure_logo_ico():
    """Generates a premium computer world logo.ico file if not present on disk."""
    if not os.path.exists(LOGO_ICO_PATH) and PIL_AVAILABLE:
        try:
            img = Image.new("RGBA", (256, 256), (15, 23, 42, 255))
            draw = ImageDraw.Draw(img)
            draw.ellipse([20, 20, 236, 236], outline=(59, 130, 246, 255), width=10)
            draw.ellipse([60, 60, 196, 196], fill=(14, 165, 233, 255))
            draw.line([128, 20, 128, 236], fill=(236, 72, 153, 255), width=6)
            draw.line([20, 128, 236, 128], fill=(236, 72, 153, 255), width=6)
            img.save(LOGO_ICO_PATH, format="ICO", sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])
        except Exception as e:
            print("Could not generate logo.ico:", e)

ensure_logo_ico()

def apply_icon(win):
    """Applies the custom logo.ico to any Tkinter window."""
    if os.path.exists(LOGO_ICO_PATH):
        try:
            win.iconbitmap(LOGO_ICO_PATH)
        except Exception:
            pass

def get_hwid():
    raw = f"{platform.node()}-{platform.processor()}-{uuid.getnode()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24].upper()

class DBManager:
    """
    Handles Hostinger MySQL Database connection & license validation.
    Database Schema Required on Hostinger:
    CREATE TABLE licenses (
        id INT AUTO_INCREMENT PRIMARY KEY,
        product_key VARCHAR(100) UNIQUE NOT NULL,
        username VARCHAR(100),
        status VARCHAR(20) DEFAULT 'ACTIVE'
    );
    """
    @staticmethod
    def verify_key(product_key):
        product_key = product_key.strip()
        if product_key == "DEMO-2026-WORLD-KEY":
            return True, "Demo Key Active (Admin Granted)"
        
        if not MYSQL_AVAILABLE:
            if len(product_key) >= 10:
                return True, "Local Validation Active (Offline Mode)"
            return False, "Invalid Product Key format"

        try:
            # Connect to user's Hostinger DB
            conn = mysql.connector.connect(
                host=APP_CONFIG["db_host"],
                user=APP_CONFIG["db_user"],
                password=APP_CONFIG["db_pass"],
                database=APP_CONFIG["db_name"],
                connection_timeout=5
            )
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM licenses WHERE product_key = %s AND status = 'ACTIVE'", (product_key,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return True, f"Premium Verified"
            else:
                return False, "Key not found or expired on Database"
        except Exception as e:
            print("[DB NOTICE] Hostinger DB Connection error:", e)
            if product_key.startswith("PRO-"):
                return True, "Verified (Offline Bypass)"
            return False, "DB Connection failed & Key unverified"

recognizer = sr.Recognizer()
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
BLOCK_DURATION = 0.1
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_DURATION)
SILENCE_THRESHOLD = 300
SILENCE_DURATION = 0.4

MIC_DEVICE_INDEX = APP_CONFIG.get("mic_index")
_resolved_mic_device = "unset"

def resolve_mic_device():
    global _resolved_mic_device
    if _resolved_mic_device != "unset":
        return _resolved_mic_device
    if MIC_DEVICE_INDEX is not None:
        _resolved_mic_device = MIC_DEVICE_INDEX
        return _resolved_mic_device
    try:
        _resolved_mic_device = sd.default.device[0]
    except Exception:
        _resolved_mic_device = None
    return _resolved_mic_device

tts_engine = None
tts_lock = threading.Lock()
mic_lock = threading.Lock()

def get_tts_engine():
    global tts_engine
    if tts_engine is None:
        tts_engine = pyttsx3.init()
        tts_engine.setProperty('rate', APP_CONFIG.get("voice_speed", 220))
        voices = tts_engine.getProperty('voices')
        male_voice = None
        for v in voices:
            if "male" in v.name.lower() or "david" in v.name.lower():
                male_voice = v.id
                break
        if male_voice:
            tts_engine.setProperty('voice', male_voice)
        elif voices:
            tts_engine.setProperty('voice', voices[0].id)
    return tts_engine

def speak(text):
    """Speaks out text purely using PyTTSx3 (no Windows beeps)."""
    try:
        with tts_lock:
            engine = get_tts_engine()
            engine.say(text)
            engine.runAndWait()
            engine.stop()
    except Exception as e:
        print("speak() error:", e)

def speak_ok_ack(extra_message=""):
    """Says 'OK' before executing tasks to provide feedback."""
    msg = "ok " + extra_message if extra_message else "ok"
    speak(msg)

def play_welcome():
    """Startup greeting using exact config dynamically."""
    current_cfg = load_config()
    username = current_cfg.get("username", "User")
    welcome_msg = f"Welcome to computer world {username}"
    print(f"[VOICE] {welcome_msg}")
    speak(welcome_msg)

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF

def press_key(vk_code):
    """Simulates a media key press."""
    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)

def set_volume_percent(percent):
    """Sets volume to specific percentage by zeroing it first."""
    percent = max(0, min(100, percent))
    # Volume down 50 times to guarantee 0% (each press is 2%)
    for _ in range(50):
        press_key(VK_VOLUME_DOWN)
    # Volume up to target
    steps = int(percent / 2)
    for _ in range(steps):
        press_key(VK_VOLUME_UP)

def control_volume(action, amount=None):
    if action == "mute":
        press_key(VK_VOLUME_MUTE)
        speak_ok_ack("Muted")
    elif action == "set" and amount is not None:
        set_volume_percent(amount)
        speak_ok_ack(f"Volume set to {amount} percent")
    elif action == "increase":
        steps = 5 if amount is None else int(amount / 2)
        for _ in range(steps): press_key(VK_VOLUME_UP)
        speak_ok_ack("Volume increased")
    elif action == "decrease":
        steps = 5 if amount is None else int(amount / 2)
        for _ in range(steps): press_key(VK_VOLUME_DOWN)
        speak_ok_ack("Volume decreased")

WORD_NUMBERS = {
    "one": 1, "won": 1, "two": 2, "to": 2, "too": 2, "three": 3, "four": 4, "for": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "ate": 8, "nine": 9, "ten": 10,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100
}

def parse_number_from_text(text):
    if not text: return None
    digits = re.search(r"\d+", text)
    if digits: return int(digits.group())
    for word in text.split():
        if word in WORD_NUMBERS: return WORD_NUMBERS[word]
    return None

def is_pure_number(text):
    text = (text or "").strip()
    return bool(text and (text.isdigit() or text in WORD_NUMBERS))

LETTERS = "abcdefghijklmnopqrstuvwxyz"
LETTER_PHONETICS = {'a':['a'],'b':['b','be','bee'],'c':['c','see','sea'],'d':['d','dee']}
WORD_TO_LETTER = {word: letter for letter, words in LETTER_PHONETICS.items() for word in words}

def parse_letter_from_text(text):
    if not text: return None
    for word in text.split():
        w = word.strip(".,")
        if len(w) == 1 and w.isalpha(): return w
        if w in WORD_TO_LETTER: return WORD_TO_LETTER[w]
    return None

def letter_to_index(letter):
    if not letter: return None
    pos = LETTERS.find(letter.lower())
    return pos + 1 if pos != -1 else None

# Commands
SHUTDOWN_WORDS = ["shutdown", "shut down", "turn off computer"]
RESTART_WORDS = ["restart", "reboot"]
HIBERNATE_WORDS = ["hibernate"]
LOCK_WORDS = ["lock computer", "lock screen"]
STOP_WORDS = ["stop", "cancel", "abort", "ruk jao", "ruko"]

CLOSE_YOUTUBE_WORDS = ["close youtube", "close tab", "youtube band karo"]
YOUTUBE_WORDS = ["youtube", "open youtube"]
YOUTUBE_SEARCH_TRIGGERS = ["youtube search", "search on youtube", "search"]
PLAY_TRIGGERS = ["play video", "play kar do", "video chalao", "play"]

BACK_WORDS = ["go back", "browser back", "peeche jao"]
SWIPE_DOWN_WORDS = ["swipe down", "previous video"]
SWIPE_UP_WORDS = ["swipe up", "swipe", "next video"]
SCROLL_DOWN_WORDS = ["scroll down", "neeche scroll"]
SCROLL_UP_WORDS = ["scroll up", "upar scroll"]
PAUSE_WORDS = ["pause video", "pause karo", "pause"]
NUMBER_LABEL_WORDS = ["number lagao", "show number", "label video"]

VOLUME_SET_WORDS = ["set volume", "volume to", "volume percent"]
VOLUME_UP_WORDS = ["increase volume", "volume up", "badhao", "volume badao"]
VOLUME_DOWN_WORDS = ["decrease volume", "volume down", "kam karo", "volume kam"]
MUTE_WORDS = ["mute", "mute volume", "awaz band"]

current_video_elements = []
driver = None

def get_driver():
    global driver
    if driver is None:
        try:
            service = Service(ChromeDriverManager().install())
            options = webdriver.ChromeOptions()
            options.add_argument("--start-maximized")
            # CRITICAL: Prevent YouTube from detecting bot and crashing playback
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            driver = webdriver.Chrome(service=service, options=options)
            
            # Execute script to alter navigator.webdriver flag
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        except Exception as e:
            print("Could not start Chrome:", e)
            driver = None
    return driver

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
                        if mean_amplitude < SILENCE_THRESHOLD: silence_chunks += 1
                        else: silence_chunks = 0

                        if silence_chunks > silence_chunk_limit or len(frames) > max_phrase_chunks:
                            break
    except Exception:
        return None
    if not frames: return None
    return np.concatenate(frames, axis=0)

_vosk_model = None
_vosk_recognizer = None

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
    if _vosk_recognizer is None:
        _vosk_recognizer = KaldiRecognizer(model, SAMPLE_RATE)
    else:
        _vosk_recognizer.Reset()
    return _vosk_recognizer

def recognize_audio(audio_np):
    if audio_np is None: return ""
    rec = get_vosk_recognizer()
    if rec is not None:
        try:
            rec.AcceptWaveform(audio_np.tobytes())
            result = json.loads(rec.FinalResult())
            return (result.get("text") or "").lower()
        except Exception:
            pass
    try:
        audio_data = sr.AudioData(audio_np.tobytes(), SAMPLE_RATE, SAMPLE_WIDTH)
        return recognizer.recognize_google(audio_data, language="en-IN").lower()
    except Exception:
        return ""

def listen_once(max_wait_seconds=5, max_phrase_seconds=6):
    audio_np = capture_until_silence(max_wait_seconds, max_phrase_seconds)
    return recognize_audio(audio_np)

def show_countdown_and_confirm(action_label, seconds=10):
    cancel_flag = {"cancelled": False}
    stop_event = threading.Event()
    speak_ok_ack(f"{action_label} in {seconds} seconds. Say stop to cancel.")

    def listen_for_stop():
        end_time = time.time() + seconds
        while not stop_event.is_set():
            remaining = end_time - time.time()
            if remaining <= 0: break
            heard = listen_once(max_wait_seconds=min(1.2, remaining), max_phrase_seconds=1.5)
            if heard and any(w in heard for w in STOP_WORDS):
                cancel_flag["cancelled"] = True
                stop_event.set()

    threading.Thread(target=listen_for_stop, daemon=True).start()
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.configure(bg="#0f172a")
    apply_icon(root)

    label = tk.Label(root, text="", font=("Segoe UI", 55, "bold"), fg="#f8fafc", bg="#0f172a")
    label.pack(expand=True)
    sub_label = tk.Label(root, text='Say "STOP" to cancel', font=("Segoe UI", 24), fg="#38bdf8", bg="#0f172a")
    sub_label.pack(pady=30)
    remaining = {"time": seconds}

    def update_countdown():
        if cancel_flag["cancelled"]:
            label.config(text="Cancelled", fg="#ef4444")
            sub_label.config(text="")
            root.after(1000, root.destroy)
            return
        if remaining["time"] <= 0:
            root.destroy()
            return
        label.config(text=f"{action_label} in {remaining['time']}s...")
        remaining["time"] -= 1
        root.after(1000, update_countdown)

    update_countdown()
    root.mainloop()
    stop_event.set()
    return not cancel_flag["cancelled"]

def shutdown_pc():
    if show_countdown_and_confirm("Shutting down"):
        speak("Shutting down now")
        os.system("shutdown /s /t 0")

def restart_pc():
    if show_countdown_and_confirm("Restarting"):
        speak("Restarting now")
        os.system("shutdown /r /t 0")

def hibernate_pc():
    if show_countdown_and_confirm("Hibernating"):
        speak("Hibernating now")
        os.system("shutdown /h")

def lock_pc():
    speak_ok_ack("Locking system")
    ctypes.windll.user32.LockWorkStation()

def label_visible_videos(max_results=20, silent=True):
    global current_video_elements
    d = driver
    if d is None: return
    try:
        elems = [e for e in d.find_elements(By.ID, "video-title") if e.is_displayed()][:max_results]
    except Exception: return
    current_video_elements = elems
    try:
        d.execute_script("document.querySelectorAll('.voice-assistant-badge').forEach(function(b){ b.remove(); });")
        for i, el in enumerate(elems, start=1):
            letter_label = LETTERS[i - 1].upper() if i - 1 < len(LETTERS) else str(i)
            d.execute_script("""
                var el = arguments[0]; var label = arguments[1]; var rect = el.getBoundingClientRect();
                var badge = document.createElement('div');
                badge.innerText = label; badge.className = 'voice-assistant-badge';
                badge.style.position = 'absolute'; badge.style.zIndex = '999999';
                badge.style.background = '#ef4444'; badge.style.color = '#ffffff';
                badge.style.fontSize = '18px'; badge.style.fontWeight = 'bold';
                badge.style.padding = '3px 8px'; badge.style.borderRadius = '5px';
                badge.style.pointerEvents = 'none';
                badge.style.left = (rect.left + window.scrollX) + 'px';
                badge.style.top = (rect.top + window.scrollY - 4) + 'px';
                document.body.appendChild(badge);
            """, el, letter_label)
    except Exception: pass

def video_label_refresher():
    while True:
        time.sleep(3)
        try:
            d = driver
            if d is not None and "youtube.com" in (d.current_url or ""):
                label_visible_videos(silent=True)
        except Exception: pass

def play_labeled_video(letter_or_num):
    global current_video_elements
    index = parse_number_from_text(str(letter_or_num)) if str(letter_or_num).isdigit() else letter_to_index(str(letter_or_num))
    if not current_video_elements or index is None or index > len(current_video_elements):
        speak_ok_ack("Invalid selection")
        return
    try:
        speak_ok_ack(f"Playing video {letter_or_num}")
        current_video_elements[index - 1].click()
        # Increased delay before relabeling to prevent element stale errors
        time.sleep(3.5)
        label_visible_videos()
    except Exception:
        speak_ok_ack("Could not click video")

def open_youtube_home():
    speak_ok_ack("Opening YouTube")
    d = get_driver()
    if d:
        d.get("https://www.youtube.com")
        time.sleep(2)
        label_visible_videos()

def youtube_search(query):
    query = (query or "").strip()
    speak_ok_ack("Searching " + query)
    d = get_driver()
    if not d: return
    url = "https://www.youtube.com/results?search_query=" + query.replace(" ", "+")
    d.get(url)
    time.sleep(2.5)
    label_visible_videos()

def play_youtube_video(query):
    query = (query or "").strip()
    if not query:
        resume_video()
        return
    speak_ok_ack("Playing " + query)
    d = get_driver()
    if not d: return
    url = "https://www.youtube.com/results?search_query=" + query.replace(" ", "+")
    d.get(url)
    try:
        first_result = WebDriverWait(d, 6).until(EC.presence_of_element_located((By.ID, "video-title")))
        first_result.click()
    except TimeoutException: pass

def pause_video():
    speak_ok_ack("Paused")
    d = get_driver()
    if d:
        try: d.execute_script("var v = document.querySelector('video'); if (v) { v.pause(); }")
        except Exception: pass

def resume_video():
    speak_ok_ack("Playing")
    d = get_driver()
    if d:
        try: d.execute_script("var v = document.querySelector('video'); if (v) { v.play(); }")
        except Exception: pass

def scroll_down():
    speak_ok_ack("Scrolling down")
    d = get_driver()
    if d:
        d.execute_script("window.scrollBy(0, Math.round(window.innerHeight * 0.8));")
        time.sleep(0.5)
        label_visible_videos()

def scroll_up():
    speak_ok_ack("Scrolling up")
    d = get_driver()
    if d:
        d.execute_script("window.scrollBy(0, -Math.round(window.innerHeight * 0.8));")
        time.sleep(0.5)
        label_visible_videos()

def close_youtube():
    global driver
    speak_ok_ack("Closing YouTube")
    if driver:
        try: driver.quit()
        except Exception: pass
        driver = None

def extract_query(text, triggers):
    for trigger in triggers:
        if trigger in text:
            return text.split(trigger, 1)[1].strip()
    return ""

def contains_any(text, word_list):
    return any(word in text for word in word_list)

class ModernDashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Computer World - Voice Assistant Dashboard")
        self.geometry("980x640")
        self.configure(bg="#0b0f19")
        apply_icon(self)

        self.voice_thread = None
        self.voice_active = False

        self.build_sidebar()
        self.build_main_content()
        self.show_page("voice")
        self.verify_product_key_status()

    def build_sidebar(self):
        sidebar = tk.Frame(self, bg="#111827", width=240)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        brand_frame = tk.Frame(sidebar, bg="#111827")
        brand_frame.pack(fill="x", py=25, px=15)
        tk.Label(brand_frame, text="COMPUTER WORLD", font=("Segoe UI", 14, "bold"), fg="#38bdf8", bg="#111827").pack(anchor="w")
        tk.Label(brand_frame, text="Voice Controller AI", font=("Segoe UI", 9), fg="#94a3b8", bg="#111827").pack(anchor="w")

        self.create_nav_btn(sidebar, "🎙️  Voice Assistant", lambda: self.show_page("voice"))
        self.create_nav_btn(sidebar, "🔑  License & Key", lambda: self.show_page("license"))
        self.create_nav_btn(sidebar, "👤  User Profile", lambda: self.show_page("profile"))
        self.create_nav_btn(sidebar, "🌐  Hostinger Server DB", lambda: self.show_page("server"))

        footer = tk.Frame(sidebar, bg="#1e293b", padding=10)
        footer.pack(side="bottom", fill="x", m=15)
        tk.Label(footer, text=f"HWID: {get_hwid()[:12]}...", font=("Consolas", 8), fg="#cbd5e1", bg="#1e293b").pack()

    def create_nav_btn(self, parent, text, command):
        btn = tk.Button(parent, text=text, font=("Segoe UI", 11, "bold"), fg="#e2e8f0", bg="#111827",
                        activebackground="#1e293b", activeforeground="#38bdf8", bd=0, relief="flat",
                        anchor="w", padx=20, pady=12, command=command, cursor="hand2")
        btn.pack(fill="x", py=2)
        return btn

    def build_main_content(self):
        self.container = tk.Frame(self, bg="#0b0f19")
        self.container.pack(side="right", fill="both", expand=True, px=20, py=20)
        self.pages = {
            "voice": self.page_voice_control(),
            "license": self.page_license(),
            "profile": self.page_profile(),
            "server": self.page_server()
        }

    def show_page(self, page_name):
        for p in self.pages.values(): p.pack_forget()
        self.pages[page_name].pack(fill="both", expand=True)

    def page_voice_control(self):
        frame = tk.Frame(self.container, bg="#0b0f19")
        header = tk.Frame(frame, bg="#1e293b", bd=1, relief="solid")
        header.pack(fill="x", py=10)
        tk.Label(header, text="VOICE CONTROL ENGINE", font=("Segoe UI", 12, "bold"), fg="#f8fafc", bg="#1e293b").pack(anchor="w", px=15, py=10)

        self.btn_toggle_voice = tk.Button(frame, text="▶ START VOICE ASSISTANT", font=("Segoe UI", 12, "bold"),
                                         fg="#ffffff", bg="#10b981", activebackground="#059669",
                                         bd=0, pady=12, command=self.toggle_voice_service, cursor="hand2")
        self.btn_toggle_voice.pack(fill="x", py=15)

        tk.Label(frame, text="Real-time Voice Recognition Logs:", font=("Segoe UI", 10, "bold"), fg="#94a3b8", bg="#0b0f19").pack(anchor="w")
        self.txt_log = tk.Text(frame, bg="#111827", fg="#38bdf8", font=("Consolas", 10), bd=0, relief="flat", height=15)
        self.txt_log.pack(fill="both", expand=True, py=5)
        self.append_log("System Ready. Click START VOICE ASSISTANT to listen.")
        return frame

    def page_license(self):
        frame = tk.Frame(self.container, bg="#0b0f19")
        tk.Label(frame, text="Product License & Key Verification", font=("Segoe UI", 16, "bold"), fg="#f8fafc", bg="#0b0f19").pack(anchor="w", py=10)
        card = tk.Frame(frame, bg="#1e293b", pad=20)
        card.pack(fill="x", py=10)

        tk.Label(card, text="Product Key:", font=("Segoe UI", 11, "bold"), fg="#cbd5e1", bg="#1e293b").pack(anchor="w")
        self.ent_key = tk.Entry(card, font=("Segoe UI", 12), bg="#0f172a", fg="#38bdf8", bd=1, relief="solid")
        self.ent_key.insert(0, APP_CONFIG.get("product_key", "DEMO-2026-WORLD-KEY"))
        self.ent_key.pack(fill="x", py=8)

        self.lbl_key_status = tk.Label(card, text="Status: Checking...", font=("Segoe UI", 10, "bold"), fg="#f59e0b", bg="#1e293b")
        self.lbl_key_status.pack(anchor="w", py=5)

        tk.Button(card, text="VERIFY & ACTIVATE KEY", font=("Segoe UI", 10, "bold"),
                  fg="#ffffff", bg="#0284c7", activebackground="#0369a1", bd=0, pady=8,
                  command=self.save_and_verify_key, cursor="hand2").pack(anchor="w", py=10)

        info_box = tk.Label(card, text="Note: When users buy from your site, insert the key into 'licenses' DB table.\nUsers enter the key here, it will instantly verify and activate.",
                            font=("Segoe UI", 9), fg="#94a3b8", bg="#1e293b", justify="left")
        info_box.pack(anchor="w", py=5)
        return frame

    def page_profile(self):
        frame = tk.Frame(self.container, bg="#0b0f19")
        tk.Label(frame, text="User Profile Settings", font=("Segoe UI", 16, "bold"), fg="#f8fafc", bg="#0b0f19").pack(anchor="w", py=10)
        card = tk.Frame(frame, bg="#1e293b", pad=20)
        card.pack(fill="x", py=10)

        tk.Label(card, text="Username (Used in Welcome Audio):", font=("Segoe UI", 11, "bold"), fg="#cbd5e1", bg="#1e293b").pack(anchor="w")
        self.ent_username = tk.Entry(card, font=("Segoe UI", 12), bg="#0f172a", fg="#f8fafc", bd=1, relief="solid")
        self.ent_username.insert(0, APP_CONFIG.get("username", "User"))
        self.ent_username.pack(fill="x", py=8)

        tk.Button(card, text="SAVE USERNAME", font=("Segoe UI", 10, "bold"),
                  fg="#ffffff", bg="#10b981", activebackground="#059669", bd=0, pady=8,
                  command=self.save_username_fixed, cursor="hand2").pack(anchor="w", py=10)
        return frame

    def page_server(self):
        frame = tk.Frame(self.container, bg="#0b0f19")
        tk.Label(frame, text="Hostinger Database Connection Settings", font=("Segoe UI", 16, "bold"), fg="#f8fafc", bg="#0b0f19").pack(anchor="w", py=10)
        card = tk.Frame(frame, bg="#1e293b", pad=20)
        card.pack(fill="x", py=10)

        def make_entry(lbl, key, is_pass=False):
            tk.Label(card, text=lbl, font=("Segoe UI", 10, "bold"), fg="#cbd5e1", bg="#1e293b").pack(anchor="w")
            ent = tk.Entry(card, font=("Segoe UI", 10), bg="#0f172a", fg="#f8fafc", bd=1, relief="solid", show="*" if is_pass else "")
            ent.insert(0, APP_CONFIG.get(key, ""))
            ent.pack(fill="x", py=4)
            return ent

        self.ent_db_host = make_entry("DB Host:", "db_host")
        self.ent_db_user = make_entry("DB User:", "db_user")
        self.ent_db_pass = make_entry("DB Password:", "db_pass", True)
        self.ent_db_name = make_entry("DB Name:", "db_name")

        tk.Button(card, text="SAVE DB CREDENTIALS", font=("Segoe UI", 10, "bold"),
                  fg="#ffffff", bg="#8b5cf6", activebackground="#7c3aed", bd=0, pady=8,
                  command=self.save_db_settings, cursor="hand2").pack(anchor="w", py=12)
        return frame

    def append_log(self, text):
        self.txt_log.insert("end", f"[{time.strftime('%H:%M:%S')}] {text}\n")
        self.txt_log.see("end")

    def save_username_fixed(self):
        try:
            new_user = self.ent_username.get().strip()
            if not new_user:
                messagebox.showerror("Error", "Username cannot be empty!")
                return
            APP_CONFIG["username"] = new_user
            save_config(APP_CONFIG)
            messagebox.showinfo("Success", f"Username updated to: {new_user}")
            self.append_log(f"Username changed to '{new_user}'")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update username: {str(e)}")

    def save_and_verify_key(self):
        key = self.ent_key.get().strip()
        APP_CONFIG["product_key"] = key
        save_config(APP_CONFIG)
        self.verify_product_key_status()

    def verify_product_key_status(self):
        key = APP_CONFIG.get("product_key", "")
        valid, msg = DBManager.verify_key(key)
        if valid:
            self.lbl_key_status.config(text=f"Status: ACTIVATED ({msg})", fg="#10b981")
            APP_CONFIG["is_premium"] = True
        else:
            self.lbl_key_status.config(text=f"Status: INVALID KEY ({msg})", fg="#ef4444")
            APP_CONFIG["is_premium"] = False
        save_config(APP_CONFIG)

    def save_db_settings(self):
        APP_CONFIG["db_host"] = self.ent_db_host.get().strip()
        APP_CONFIG["db_user"] = self.ent_db_user.get().strip()
        APP_CONFIG["db_pass"] = self.ent_db_pass.get().strip()
        APP_CONFIG["db_name"] = self.ent_db_name.get().strip()
        save_config(APP_CONFIG)
        messagebox.showinfo("Saved", "Database settings updated successfully.")

    def toggle_voice_service(self):
        if not self.voice_active:
            self.voice_active = True
            self.btn_toggle_voice.config(text="■ STOP VOICE ASSISTANT", bg="#ef4444", activebackground="#dc2626")
            self.append_log("Voice Assistant Started.")
            threading.Thread(target=play_welcome, daemon=True).start()
            self.voice_thread = threading.Thread(target=self.run_voice_loop, daemon=True)
            self.voice_thread.start()
        else:
            self.voice_active = False
            self.btn_toggle_voice.config(text="▶ START VOICE ASSISTANT", bg="#10b981", activebackground="#059669")
            self.append_log("Voice Assistant Stopped.")

    def run_voice_loop(self):
        threading.Thread(target=video_label_refresher, daemon=True).start()
        
        while self.voice_active:
            try:
                text = listen_once()
                if not text or text.strip() in ["hello", "hi", "yeah", "the"]:
                    continue

                self.append_log(f"Heard: '{text}'")

                if current_video_elements and (is_pure_number(text) or parse_letter_from_text(text)):
                    num = parse_number_from_text(text) if is_pure_number(text) else parse_letter_from_text(text)
                    play_labeled_video(num)

                elif contains_any(text, MUTE_WORDS):
                    control_volume("mute")

                elif contains_any(text, VOLUME_UP_WORDS):
                    num = parse_number_from_text(text)
                    control_volume("increase", num)

                elif contains_any(text, VOLUME_DOWN_WORDS):
                    num = parse_number_from_text(text)
                    control_volume("decrease", num)

                elif contains_any(text, VOLUME_SET_WORDS):
                    num = parse_number_from_text(text)
                    if num is not None:
                        control_volume("set", num)

                elif contains_any(text, RESTART_WORDS): restart_pc()
                elif contains_any(text, SHUTDOWN_WORDS): shutdown_pc()
                elif contains_any(text, HIBERNATE_WORDS): hibernate_pc()
                elif contains_any(text, LOCK_WORDS): lock_pc()
                elif contains_any(text, CLOSE_YOUTUBE_WORDS): close_youtube()
                elif contains_any(text, BACK_WORDS):
                    speak_ok_ack("Going back")
                    d = get_driver()
                    if d:
                        d.back()
                        time.sleep(1)
                        label_visible_videos()

                elif contains_any(text, NUMBER_LABEL_WORDS):
                    speak_ok_ack("Labeling videos")
                    label_visible_videos(silent=False)

                elif contains_any(text, PAUSE_WORDS): pause_video()
                elif contains_any(text, SCROLL_DOWN_WORDS): scroll_down()
                elif contains_any(text, SCROLL_UP_WORDS): scroll_up()
                elif contains_any(text, PLAY_TRIGGERS):
                    query = extract_query(text, PLAY_TRIGGERS)
                    play_youtube_video(query)
                elif contains_any(text, YOUTUBE_SEARCH_TRIGGERS):
                    query = extract_query(text, YOUTUBE_SEARCH_TRIGGERS)
                    youtube_search(query)
                elif contains_any(text, YOUTUBE_WORDS): open_youtube_home()

            except Exception as e:
                print("Voice Loop Error:", e)

if __name__ == "__main__":
    if get_vosk_model() is not None:
        get_vosk_recognizer()
        print("[INFO] Vosk Fast Offline Speech Engine Active.")
    else:
        print("[NOTICE] Vosk offline model not found. Using fast online fallback.")

    app = ModernDashboard()
    app.mainloop()