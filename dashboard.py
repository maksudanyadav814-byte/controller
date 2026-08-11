import tkinter as tk
from tkinter import messagebox
import json
import os

def get_config_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_config.json")

def load_current_name():
    config_path = get_config_path()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("name", "User")
        except Exception:
            pass
    return "User"

def save_name():
    new_name = name_entry.get().strip()
    if not new_name:
        messagebox.showwarning("Warning", "Name cannot be empty!")
        return
    
    config_path = get_config_path()
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({"name": new_name}, f, indent=4)
        status_label.config(text=f"Saved! Current Name: {new_name}", fg="#00ffcc")
        messagebox.showinfo("Success", f"User name updated to: {new_name}")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to save name: {e}")

root = tk.Tk()
root.title("Hackworld Controller Dashboard")
root.geometry("400x260")
root.configure(bg="#1e1e2e")
root.resizable(False, False)

# Header
header = tk.Label(root, text="Hackworld Settings", font=("Segoe UI", 16, "bold"), fg="#ffffff", bg="#1e1e2e")
header.pack(pady=15)

# Name Label
label = tk.Label(root, text="Enter Owner / User Name:", font=("Segoe UI", 11), fg="#cdd6f4", bg="#1e1e2e")
label.pack(pady=5)

# Entry Box
name_entry = tk.Entry(root, font=("Segoe UI", 12), width=25, bg="#313244", fg="#ffffff", insertbackground="white", relief="flat")
name_entry.insert(0, load_current_name())
name_entry.pack(pady=10)

# Save Button
save_btn = tk.Button(root, text="Save Name", font=("Segoe UI", 11, "bold"), bg="#89b4fa", fg="#11111b", relief="flat", padx=15, pady=4, command=save_name)
save_btn.pack(pady=10)

# Status
status_label = tk.Label(root, text="", font=("Segoe UI", 10), bg="#1e1e2e")
status_label.pack(pady=5)

root.mainloop()