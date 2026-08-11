import re
import json
import sounddevice as sd
import numpy as np
import speech_recognition as sr
import os
import ctypes
import threading
import time
import tkinter as tk
import pyttsx3
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Vosk = offline speech recognition
try:
    from vosk import Model as VoskModel, KaldiRecognizer
    VOSK_LIB_AVAILABLE = True
except ImportError:
    VOSK_LIB_AVAILABLE = False

recognizer = sr.Recognizer()

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2                # int16 = 2 bytes per sample
BLOCK_DURATION = 0.1            # 100ms chunks
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_DURATION)

SILENCE_THRESHOLD = 300         # Audio amplitude threshold
SILENCE_DURATION = 0.4          # Pause detection threshold

VOSK_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vosk-model")
_vosk_model = None

MIC_DEVICE_INDEX = None
_resolved_mic_device = "unset"


def resolve_mic_device():
    """Resolves and caches default input microphone device."""
    global _resolved_mic_device
    if _resolved_mic_device != "unset":
        return _resolved_mic_device
    if MIC_DEVICE_INDEX is not None:
        _resolved_mic_device = MIC_DEVICE_INDEX
        return _resolved_mic_device
    try:
        _resolved_mic_device = sd.default.device[0]
    except Exception as e:
        print("resolve_mic_device() error, using system default:", e)
        _resolved_mic_device = None
    return _resolved_mic_device


WORD_NUMBERS = {
    "one": 1, "won": 1, "two": 2, "to": 2, "too": 2, "three": 3, "four": 4, "for": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "ate": 8, "nine": 9, "ten": 10,
}


def parse_number_from_text(text):
    if not text:
        return None
    digits = re.search(r"\d+", text)
    if digits:
        return int(digits.group())
    for word in text.split():
        if word in WORD_NUMBERS:
            return WORD_NUMBERS[word]
    return None


def is_pure_number(text):
    text = (text or "").strip()
    if not text:
        return False
    if text.isdigit():
        return True
    return text in WORD_NUMBERS


LETTERS = "abcdefghijklmnopqrstuvwxyz"

LETTER_PHONETICS = {
    'a': ['a'], 'b': ['b', 'be', 'bee'], 'c': ['c', 'see', 'sea'], 'd': ['d', 'dee'],
    'e': ['e'], 'f': ['f', 'ef'], 'g': ['g', 'gee'], 'h': ['h', 'aitch', 'edge'],
    'i': ['i', 'eye'], 'j': ['j', 'jay'], 'k': ['k', 'kay'], 'l': ['l', 'el'],
    'm': ['m', 'em'], 'n': ['n', 'en'], 'o': ['o'], 'p': ['p', 'pee'],
    'q': ['q', 'cue', 'queue'], 'r': ['r', 'are'], 's': ['s', 'es'], 't': ['t', 'tee', 'tea'],
    'u': ['u', 'you'], 'v': ['v', 'vee'], 'w': ['w'], 'x': ['x', 'ex'],
    'y': ['y', 'why'], 'z': ['z', 'zee', 'zed'],
}
WORD_TO_LETTER = {word: letter for letter, words in LETTER_PHONETICS.items() for word in words}


def parse_letter_from_text(text):
    if not text:
        return None
    for word in text.split():
        w = word.strip(".,")
        if len(w) == 1 and w.isalpha():
            return w
        if w in WORD_TO_LETTER:
            return WORD_TO_LETTER[w]
    return None


def is_pure_letter(text):
    text = (text or "").strip()
    if not text:
        return False
    if len(text) == 1 and text.isalpha():
        return True
    return text in WORD_TO_LETTER


def letter_to_index(letter):
    if not letter:
        return None
    pos = LETTERS.find(letter)
    return pos + 1 if pos != -1 else None

SHUTDOWN_WORDS = ["shutdown", "shut down", "shut that down", "shot down", "shut town", "shatdown"]
RESTART_WORDS = ["restart", "re start", "restart the computer", "restart kar do", "restart kardo",
                  "reboot", "re boot", "restard", "ristart"]
HIBERNATE_WORDS = ["hibernate", "hibernade", "hyber nate", "haibernate", "hai bernate", "hibernet", "high bernate"]
LOCK_WORDS = ["lock", "lock kar do", "lock the computer", "lock kardo"]
STOP_WORDS = ["stop", "cancel", "stop it", "wait", "abort", "ruk jao", "ruko"]

CLOSE_YOUTUBE_WORDS = ["close youtube", "close the tab", "close tab", "youtube band karo",
                        "band karo youtube", "close this tab", "close video"]
YOUTUBE_WORDS = ["youtube", "you tube", "yutub"]
YOUTUBE_SEARCH_TRIGGERS = ["youtube search", "search on youtube", "search youtube", "search"]

PLAY_TRIGGERS = ["play video", "play kar do", "play karo", "video chalao", "chalao", "play"]

BACK_WORDS = ["go back", "browser back", "peeche jao", "wapas jao", "back kar do", "back"]

SWIPE_DOWN_WORDS = ["swipe down", "previous video", "pichla video", "go back video"]
SWIPE_UP_WORDS = ["swipe up", "swipe", "next video", "agla video", "aage jao"]

SCROLL_DOWN_WORDS = ["scroll down", "neeche scroll karo", "scroll neeche", "neeche karo"]
SCROLL_UP_WORDS = ["scroll up", "upar scroll karo", "scroll upar", "upar karo"]

PAUSE_WORDS = ["pause video", "pause the video", "video pause karo", "pause karo", "pause kar do", "pause"]

NUMBER_LABEL_WORDS = ["number lagao", "number dikhao", "show number", "show numbers",
                       "label video", "label videos", "number karo", "video number"]

current_video_elements = []

driver = None
tts_engine = None
tts_lock = threading.Lock()
mic_lock = threading.Lock()


def get_user_name():
    """Reads user name from user_config.json if available."""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                name = data.get("name", "").strip()
                if name:
                    return name
        except Exception as e:
            print("Error reading user_config.json:", e)
    return "User"


def get_tts_engine():
    global tts_engine
    if tts_engine is None:
        tts_engine = pyttsx3.init()
        tts_engine.setProperty('rate', 220)
    return tts_engine


def get_driver():
    global driver
    if driver is None:
        try:
            service = Service(ChromeDriverManager().install())
            options = webdriver.ChromeOptions()
            options.add_argument("--start-maximized")
            driver = webdriver.Chrome(service=service, options=options)
        except Exception as e:
            print("Could not start Chrome:", e)
            driver = None
    return driver


def speak(text, voice_index=None):
    try:
        with tts_lock:
            engine = get_tts_engine()
            if voice_index is not None:
                voices = engine.getProperty('voices')
                if voice_index < len(voices):
                    engine.setProperty('voice', voices[voice_index].id)
            engine.say(text)
            engine.runAndWait()
            engine.stop()
    except Exception as e:
        print("speak() error:", e)


def play_welcome():
    user_name = get_user_name()
    speak(f"Welcome to hacking world {user_name}", voice_index=1)


def contains_any(text, word_list):
    return any(word in text for word in word_list)


# ---------------- Listening ----------------

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
                        if mean_amplitude < SILENCE_THRESHOLD:
                            silence_chunks += 1
                        else:
                            silence_chunks = 0

                        if silence_chunks > silence_chunk_limit or len(frames) > max_phrase_chunks:
                            break
    except Exception as e:
        print("capture_until_silence() mic error:", e)
        return None

    if not frames:
        return None
    return np.concatenate(frames, axis=0)


_vosk_recognizer = None


def get_vosk_model():
    global _vosk_model
    if _vosk_model is None and VOSK_LIB_AVAILABLE and os.path.isdir(VOSK_MODEL_PATH):
        try:
            _vosk_model = VoskModel(VOSK_MODEL_PATH)
        except Exception as e:
            print("get_vosk_model() error, falling back to Google:", e)
            _vosk_model = None
    return _vosk_model


def get_vosk_recognizer():
    global _vosk_recognizer
    model = get_vosk_model()
    if model is None:
        return None
    if _vosk_recognizer is None:
        _vosk_recognizer = KaldiRecognizer(model, SAMPLE_RATE)
    else:
        _vosk_recognizer.Reset()
    return _vosk_recognizer


def recognize_audio(audio_np):
    if audio_np is None:
        return ""

    rec = get_vosk_recognizer()
    if rec is not None:
        try:
            rec.AcceptWaveform(audio_np.tobytes())
            result = json.loads(rec.FinalResult())
            return (result.get("text") or "").lower()
        except Exception as e:
            print("recognize_audio() vosk error, falling back to Google:", e)

    try:
        audio_data = sr.AudioData(audio_np.tobytes(), SAMPLE_RATE, SAMPLE_WIDTH)
        return recognizer.recognize_google(audio_data, language="en-IN").lower()
    except sr.UnknownValueError:
        return ""
    except Exception as e:
        print("recognize_audio() error:", e)
        return ""


def listen_once(max_wait_seconds=5, max_phrase_seconds=6):
    audio_np = capture_until_silence(max_wait_seconds, max_phrase_seconds)
    return recognize_audio(audio_np)


# ---------------- Cancel-listener ----------------

def listen_for_stop(stop_event, cancel_flag, listen_seconds):
    end_time = time.time() + listen_seconds
    while not stop_event.is_set():
        remaining = end_time - time.time()
        if remaining <= 0:
            break
        heard = listen_once(max_wait_seconds=min(1.2, remaining), max_phrase_seconds=1.5)
        if contains_any(heard, STOP_WORDS):
            cancel_flag["cancelled"] = True
            stop_event.set()


# ---------------- Fullscreen countdown ----------------

def show_countdown_and_confirm(action_label, seconds=10):
    cancel_flag = {"cancelled": False}
    stop_event = threading.Event()

    speak(f"{action_label} in {seconds} seconds. Say stop to cancel.")

    listener_thread = threading.Thread(
        target=listen_for_stop, args=(stop_event, cancel_flag, seconds), daemon=True
    )
    listener_thread.start()

    root = tk.Tk()
    root.attributes("-fullscreen", True)
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
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

    return not cancel_flag["cancelled"]


# ---------------- System actions ----------------

def shutdown_pc():
    if show_countdown_and_confirm("Shutting down"):
        speak("Shutting down the computer now")
        os.system("shutdown /s /t 0")
    else:
        speak("Shutdown cancelled")


def restart_pc():
    if show_countdown_and_confirm("Restarting"):
        speak("Restarting the computer now")
        os.system("shutdown /r /t 0")
    else:
        speak("Restart cancelled")


def hibernate_pc():
    if show_countdown_and_confirm("Hibernating"):
        speak("Hibernating the computer now")
        result = os.system("shutdown /h")
        if result != 0:
            speak("Hibernate failed. Please enable hibernate first")
    else:
        speak("Hibernate cancelled")


def lock_pc():
    speak("Locking the computer now")
    ctypes.windll.user32.LockWorkStation()


def label_visible_videos(max_results=20, silent=True):
    global current_video_elements
    d = driver
    if d is None:
        return

    try:
        elems = [e for e in d.find_elements(By.ID, "video-title") if e.is_displayed()][:max_results]
    except Exception as e:
        if not silent:
            print("label_visible_videos() find error:", e)
        return

    current_video_elements = elems
    try:
        d.execute_script(
            "document.querySelectorAll('.voice-assistant-badge').forEach(function(b){ b.remove(); });"
        )
        for i, el in enumerate(elems, start=1):
            letter_label = LETTERS[i - 1].upper() if i - 1 < len(LETTERS) else str(i)
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
    except Exception as e:
        if not silent:
            print("label_visible_videos() badge error:", e)


def video_label_refresher():
    while True:
        time.sleep(3)
        try:
            d = driver
            if d is not None and "youtube.com" in (d.current_url or ""):
                label_visible_videos(silent=True)
        except Exception as e:
            print("video_label_refresher() error (ignored):", e)


def play_labeled_video(letter):
    global current_video_elements
    index = letter_to_index(letter)
    if not current_video_elements or index is None or index > len(current_video_elements):
        speak("Didn't get a valid letter")
        return
    try:
        current_video_elements[index - 1].click()
        speak(f"Playing {letter.upper()}")
        time.sleep(1.5)
        label_visible_videos()
    except Exception as e:
        print("play_labeled_video() click error:", e)
        speak("Could not play that video")


# ---------------- YouTube actions ----------------

def open_youtube_home():
    speak("Opening YouTube")
    d = get_driver()
    if d:
        d.get("https://www.youtube.com")
        try:
            WebDriverWait(d, 8).until(EC.presence_of_element_located((By.ID, "video-title")))
        except TimeoutException:
            print("[INFO] Home feed is empty - nothing to label yet.")
        label_visible_videos()


def youtube_search(query):
    query = (query or "").strip()
    if not query:
        speak("What should I search on YouTube")
        return
    speak("Searching YouTube for " + query)
    d = get_driver()
    if not d:
        return
    url = "https://www.youtube.com/results?search_query=" + query.replace(" ", "+")
    d.get(url)

    try:
        WebDriverWait(d, 8).until(EC.presence_of_element_located((By.ID, "video-title")))
    except TimeoutException:
        print("[INFO] youtube_search() no results loaded in time.")
        speak("Could not load search results")
        return

    label_visible_videos()
    if not current_video_elements:
        speak("No results found")


def play_youtube_video(query):
    query = (query or "").strip()
    if not query:
        resume_video()
        return
    speak("Playing " + query)
    d = get_driver()
    if not d:
        return
    url = "https://www.youtube.com/results?search_query=" + query.replace(" ", "+")
    d.get(url)
    try:
        first_result = WebDriverWait(d, 8).until(
            EC.presence_of_element_located((By.ID, "video-title"))
        )
        first_result.click()
    except TimeoutException:
        print("[INFO] play_youtube_video() no results loaded in time.")
        speak("Could not play that video automatically, but here are the search results")


def swipe_next():
    d = get_driver()
    if not d:
        speak("YouTube is not open")
        return
    try:
        d.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_DOWN)
    except Exception as e:
        print("swipe_next() error:", e)
    time.sleep(0.4)
    label_visible_videos()


def swipe_previous():
    d = get_driver()
    if not d:
        speak("YouTube is not open")
        return
    try:
        d.find_element(By.TAG_NAME, "body").send_keys(Keys.ARROW_UP)
    except Exception as e:
        print("swipe_previous() error:", e)
    time.sleep(0.4)
    label_visible_videos()


def scroll_down():
    d = get_driver()
    if not d:
        speak("YouTube is not open")
        return
    try:
        d.execute_script("window.scrollBy(0, Math.round(window.innerHeight * 0.8));")
    except Exception as e:
        print("scroll_down() error:", e)
    time.sleep(0.5)
    label_visible_videos()


def scroll_up():
    d = get_driver()
    if not d:
        speak("YouTube is not open")
        return
    try:
        d.execute_script("window.scrollBy(0, -Math.round(window.innerHeight * 0.8));")
    except Exception as e:
        print("scroll_up() error:", e)
    time.sleep(0.5)
    label_visible_videos()


def pause_video():
    d = get_driver()
    if not d:
        speak("YouTube is not open")
        return
    try:
        d.execute_script("var v = document.querySelector('video'); if (v) { v.pause(); }")
        speak("Paused")
    except Exception as e:
        print("pause_video() error:", e)


def resume_video():
    d = get_driver()
    if not d:
        speak("YouTube is not open")
        return
    try:
        d.execute_script("var v = document.querySelector('video'); if (v) { v.play(); }")
        speak("Playing")
    except Exception as e:
        print("resume_video() error:", e)


def back_page():
    d = get_driver()
    if not d:
        speak("YouTube is not open")
        return
    try:
        d.back()
        speak("Going back")
        time.sleep(0.6)
        label_visible_videos()
    except Exception as e:
        print("back_page() error:", e)


def label_and_choose_videos():
    d = get_driver()
    if not d:
        speak("YouTube is not open")
        return

    label_visible_videos(silent=False)
    if not current_video_elements:
        speak("No videos visible on screen")
        return

    speak("Say the number to play")
    choice_text = listen_once(max_wait_seconds=5, max_phrase_seconds=4)

    if not choice_text or contains_any(choice_text, STOP_WORDS):
        speak("Okay, cancelled")
        return

    play_labeled_video(parse_number_from_text(choice_text))


def close_youtube():
    global driver
    if driver is None:
        speak("YouTube is not open")
        return
    try:
        driver.close()
        handles = driver.window_handles
        if handles:
            driver.switch_to.window(handles[-1])
        else:
            driver.quit()
            driver = None
        speak("Closed the YouTube tab")
    except Exception:
        try:
            driver.quit()
        except Exception:
            pass
        driver = None
        speak("Closed the YouTube tab")


def extract_query(text, triggers):
    for trigger in triggers:
        if trigger in text:
            return text.split(trigger, 1)[1].strip()
    return None


# ---- Startup ----
if get_vosk_model() is not None:
    get_vosk_recognizer()
    print("[INFO] Fast offline recognition (Vosk) ACTIVE.")
else:
    print("[WARNING] Vosk not set up - falling back to online Google recognition.")

play_welcome()

threading.Thread(target=video_label_refresher, daemon=True).start()

while True:
    try:
        text = listen_once()

        if not text or text.strip() in ["hello", "hi", "yeah", "the"]:
            continue

        if current_video_elements and is_pure_number(text):
            play_labeled_video(parse_number_from_text(text))

        elif contains_any(text, RESTART_WORDS):
            restart_pc()

        elif contains_any(text, SHUTDOWN_WORDS):
            shutdown_pc()

        elif contains_any(text, HIBERNATE_WORDS):
            hibernate_pc()

        elif contains_any(text, LOCK_WORDS):
            lock_pc()

        elif contains_any(text, CLOSE_YOUTUBE_WORDS):
            close_youtube()

        elif contains_any(text, BACK_WORDS):
            back_page()

        elif contains_any(text, NUMBER_LABEL_WORDS):
            label_and_choose_videos()

        elif contains_any(text, PAUSE_WORDS):
            pause_video()

        elif contains_any(text, SCROLL_DOWN_WORDS):
            scroll_down()

        elif contains_any(text, SCROLL_UP_WORDS):
            scroll_up()

        elif contains_any(text, SWIPE_DOWN_WORDS):
            swipe_previous()

        elif contains_any(text, SWIPE_UP_WORDS):
            swipe_next()

        elif contains_any(text, PLAY_TRIGGERS):
            query = extract_query(text, PLAY_TRIGGERS)
            play_youtube_video(query)

        elif contains_any(text, YOUTUBE_SEARCH_TRIGGERS):
            query = extract_query(text, YOUTUBE_SEARCH_TRIGGERS)
            youtube_search(query)

        elif contains_any(text, YOUTUBE_WORDS):
            open_youtube_home()

    except KeyboardInterrupt:
        break
    except Exception as e:
        print("Loop error (ignored, continuing):", e)