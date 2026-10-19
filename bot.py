import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
import threading
import time
import json
import os
import ctypes

# Optional dependencies: the GUI can still start if one is missing.
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    Image = ImageTk = None
    PIL_AVAILABLE = False

try:
    from pynput import mouse, keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    mouse = keyboard = None
    PYNPUT_AVAILABLE = False

PRESET_DIR = "smart_task_presets"

# ---------------------------------------------------------------------------
# CONSTANTES API WINDOWS POUR LA GESTION DU CURSEUR
# ---------------------------------------------------------------------------
OCR_NORMAL = 32512
OCR_IBEAM = 32513
OCR_WAIT = 32514
OCR_CROSS = 32515
OCR_HAND = 32529
OCR_APPSTARTING = 32525

CURSOR_TYPES = {
    "Normal": OCR_NORMAL,
    "Busy (Chargement)": OCR_WAIT,
    "App Starting": OCR_APPSTARTING,
    "Viseur (Cross)": OCR_CROSS,
    "Main (Hand)": OCR_HAND,
    "Saisie (IBeam)": OCR_IBEAM,
    "Invisible": "BLANK"
}

FONT_UI = ("Helvetica", 9)
FONT_UI_BOLD = ("Helvetica", 9, "bold")
FONT_UI_SMALL = ("Helvetica", 8)
FONT_UI_SMALL_BOLD = ("Helvetica", 8, "bold")

class Engine:
    def __init__(self):
        self.events = []
        self.start_time = None
        self.is_recording = False
        self.is_replaying = False
        self.is_paused_by_user = False
        self.is_executing_action = False
        
        self.mouse_ctrl = mouse.Controller() if PYNPUT_AVAILABLE else None
        self.key_ctrl = keyboard.Controller() if PYNPUT_AVAILABLE else None
        
        self.last_user_activity = 0
        self.last_move_time = 0
        self.last_pos = (0, 0)
        
        # SMART CPS TRACKER
        self.click_timestamps = []
        
        # Listeners pynput sécurisés
        self.mouse_listener = None
        self.key_listener = None
        if PYNPUT_AVAILABLE:
            try:
                self.mouse_listener = mouse.Listener(on_move=self.on_move, on_click=self.on_click)
                self.key_listener = keyboard.Listener(
                    on_press=self.on_key_press,
                    on_release=self.on_key_release
                )
                self.mouse_listener.start()
                self.key_listener.start()
            except Exception as e:
                print(f"Erreur d'initialisation des listeners pynput : {e}")
        else:
            print("pynput n'est pas installé : enregistrement/relecture désactivés.")

        if not os.path.exists(PRESET_DIR):
            os.makedirs(PRESET_DIR)

    def shutdown(self):
        self.is_recording = False
        self.is_replaying = False
        try:
            if self.mouse_listener:
                self.mouse_listener.stop()
            if self.key_listener:
                self.key_listener.stop()
        except Exception:
            pass
        self.restore_system_cursor()

    def get_elapsed(self):
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time
        
    def get_cps(self):
        now = time.time()
        self.click_timestamps = [t for t in self.click_timestamps if now - t <= 1.0]
        return len(self.click_timestamps)

    def on_move(self, x, y):
        if self.is_executing_action:
            return

        if self.is_recording:
            current = time.time()
            if current - self.last_move_time > 0.015:
                dx = abs(x - self.last_pos[0])
                dy = abs(y - self.last_pos[1])
                if dx > 2 or dy > 2:
                    self.events.append({"type": "move", "time": self.get_elapsed(), "x": x, "y": y})
                    self.last_move_time = current
                    self.last_pos = (x, y)
        elif self.is_replaying:
            self.is_paused_by_user = True
            self.last_user_activity = time.time()

    def on_click(self, x, y, button, pressed):
        if self.is_executing_action:
            return
            
        if pressed:
            self.click_timestamps.append(time.time())

        if self.is_recording:
            self.events.append({
                "type": "click",
                "time": self.get_elapsed(),
                "x": x,
                "y": y,
                "button": str(button),
                "pressed": pressed
            })
        elif self.is_replaying:
            if button == mouse.Button.right and pressed:
                self.is_paused_by_user = True
                self.last_user_activity = time.time()

    def _parse_key(self, key):
        try:
            return key.char
        except AttributeError:
            return str(key)

    def on_key_press(self, key):
        if self.is_executing_action: return
        if self.is_recording:
            k = self._parse_key(key)
            if k: self.events.append({"type": "key_press", "time": self.get_elapsed(), "key": k})

    def on_key_release(self, key):
        if self.is_executing_action: return
        if self.is_recording:
            k = self._parse_key(key)
            if k: self.events.append({"type": "key_release", "time": self.get_elapsed(), "key": k})

    def start_record(self):
        if not PYNPUT_AVAILABLE:
            return False
        self.events = []
        self.start_time = time.time()
        self.is_recording = True
        return True

    def stop_record(self, preset_name):
        if self.is_recording:
            self.is_recording = False
            filename = os.path.join(PRESET_DIR, f"{preset_name}.json")
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(self.events, f, indent=2)

    def get_presets(self):
        if not os.path.exists(PRESET_DIR): return []
        return [f.replace(".json", "") for f in os.listdir(PRESET_DIR) if f.endswith(".json")]

    def delete_preset(self, preset_name):
        filename = os.path.join(PRESET_DIR, f"{preset_name}.json")
        if os.path.exists(filename):
            os.remove(filename)

    def replay_sequence(self, preset_list, speed_factor=1.0, loop_count=1, callback_done=None, callback_status=None):
        if not PYNPUT_AVAILABLE or self.mouse_ctrl is None or self.key_ctrl is None:
            if callback_status:
                callback_status("pynput requis pour lire une macro.", "#f38ba8")
            if callback_done:
                callback_done()
            return

        try:
            speed_factor = max(0.01, float(speed_factor))
            loop_count = max(1, int(loop_count))
        except (TypeError, ValueError):
            speed_factor = 1.0
            loop_count = 1

        self.is_replaying = True
        self.is_paused_by_user = False

        def run():
            try:
                for loop in range(loop_count):
                    if not self.is_replaying: break
                    for idx, preset_name in enumerate(preset_list):
                        if not self.is_replaying: break
                        filename = os.path.join(PRESET_DIR, f"{preset_name}.json")
                        if not os.path.exists(filename): continue

                        if callback_status: callback_status(f"▶ [{idx+1}/{len(preset_list)}] {preset_name}...", "#89b4fa")

                        with open(filename, "r", encoding="utf-8") as f: events = json.load(f)

                        last_time = 0
                        for event in events:
                            if not self.is_replaying: break
                            
                            while self.is_paused_by_user:
                                if not self.is_replaying: break
                                if callback_status: callback_status("⏸ Pause...", "#f38ba8")
                                if time.time() - self.last_user_activity >= 3.0:
                                    self.is_paused_by_user = False
                                    if callback_status: callback_status(f"▶ Reprise...", "#89b4fa")
                                    break
                                time.sleep(0.05)

                            delay = (event["time"] - last_time) / speed_factor
                            if delay > 0: time.sleep(max(0, delay))
                            if self.is_paused_by_user or not self.is_replaying: continue

                            last_time = event["time"]
                            etype = event["type"]
                            self.is_executing_action = True
                            try:
                                if etype == "move":
                                    self.mouse_ctrl.position = (event["x"], event["y"])
                                elif etype == "click":
                                    btn = mouse.Button.left if "left" in event["button"] else mouse.Button.right
                                    self.mouse_ctrl.position = (event["x"], event["y"])
                                    if event["pressed"]: self.mouse_ctrl.press(btn)
                                    else: self.mouse_ctrl.release(btn)
                                elif etype in ("key", "key_press", "key_release"):
                                    kval = event["key"]
                                    target_key = getattr(keyboard.Key, kval.split(".")[1]) if kval.startswith("Key.") else kval
                                    if etype == "key_release": self.key_ctrl.release(target_key)
                                    else:
                                        self.key_ctrl.press(target_key)
                                        if etype == "key": self.key_ctrl.release(target_key)
                            except Exception as ex:
                                print(f"Erreur lors de l'exécution de l'événement : {ex}")
                            finally:
                                time.sleep(0.001)
                                self.is_executing_action = False
            except Exception as e:
                print(f"Erreur globale de lecture de macro : {e}")
            finally:
                self.is_replaying = False
                self.is_paused_by_user = False
                self.is_executing_action = False
                if callback_done: callback_done()

        threading.Thread(target=run, daemon=True).start()

    def replay(self, preset_name, speed_factor=1.0, loop_count=1, callback_done=None, callback_status=None):
        self.replay_sequence([preset_name], speed_factor, loop_count, callback_done, callback_status)

    def stop_replay(self):
        self.is_replaying = False
        self.is_paused_by_user = False
        self.is_executing_action = False

    def extract_text(self, preset_name):
        filename = os.path.join(PRESET_DIR, f"{preset_name}.json")
        try:
            with open(filename, "r", encoding="utf-8") as f: events = json.load(f)
        except: return ""
        text_chars = []
        for e in events:
            if e["type"] in ("key", "key_press"):
                k = e["key"]
                if len(k) == 1: text_chars.append(k)
                elif k == "Key.space": text_chars.append(" ")
                elif k == "Key.enter": text_chars.append("\n")
        return "".join(text_chars)

    def set_system_cursor(self, cursor_type_key):
        if os.name != 'nt': return
        val = CURSOR_TYPES.get(cursor_type_key, OCR_NORMAL)
        if val == "BLANK":
            and_mask = (ctypes.c_ubyte * 32)(*([0xFF] * 32))
            xor_mask = (ctypes.c_ubyte * 32)(*([0x00] * 32))
            h_cursor = ctypes.windll.user32.CreateCursor(None, 0, 0, 16, 16, and_mask, xor_mask)
        else:
            h_cursor = ctypes.windll.user32.LoadCursorW(None, val)
        ctypes.windll.user32.SetSystemCursor(h_cursor, OCR_NORMAL)

    def restore_system_cursor(self):
        if os.name == 'nt': 
            try:
                ctypes.windll.user32.SystemParametersInfoW(0x0057, 0, None, 0)
            except:
                pass


class GameBarGUI(tk.Tk):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.current_preset = ""

        self.logo_clicks = 0
        self.last_logo_click_time = 0
        self.cursor_menu_open = False
        self.cursor_index = 0

        self.is_collapsed = False
        self.sandbox_visible = False

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        
        self.TRANS_COLOR = "#000001"
        self.configure(bg=self.TRANS_COLOR)
        if os.name == 'nt':
            self.wm_attributes("-transparentcolor", self.TRANS_COLOR)

        self.geometry("520x150+200+200")

        self._offset_x = 0
        self._offset_y = 0

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.build_ui()
        self.update_cps_display()

    def build_ui(self):
        self.main_container = tk.Frame(self, bg="#1e1e2e", bd=0)
        self.main_container.pack(fill="both", expand=True)

        self.header = tk.Frame(self.main_container, bg="#11111b", height=34)
        self.header.pack(fill="x", side="top")

        self.logo_img = None
        if PIL_AVAILABLE and os.path.exists("logo.png"):
            try:
                raw_img = Image.open("logo.png")
                h_target = 22
                w_target = int(raw_img.width * (h_target / raw_img.height))
                raw_img = raw_img.resize((w_target, h_target), Image.Resampling.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(raw_img)
            except Exception as e:
                print("Erreur de chargement du logo :", e)

        if self.logo_img:
            self.title_lbl = tk.Label(self.header, image=self.logo_img, bg="#11111b", cursor="hand2")
        else:
            self.title_lbl = tk.Frame(self.header, bg="#11111b", cursor="hand2")
            tk.Label(self.title_lbl, text="❖ SMART ", fg="#89b4fa", bg="#11111b", font=FONT_UI_BOLD).pack(side="left")
            tk.Label(self.title_lbl, text="TASK", fg="#cdd6f4", bg="#11111b", font=FONT_UI_BOLD).pack(side="left")

        self.title_lbl.pack(side="left", padx=10)
        self.title_lbl.bind("<Button-1>", self.on_logo_click)

        self.btn_sandbox_toggle = tk.Button(self.header, text="📦 Sandbox ▾", fg="#89b4fa", bg="#11111b", bd=0,
                                            activebackground="#313244", activeforeground="#89b4fa",
                                            command=self.toggle_sandbox, font=FONT_UI_SMALL_BOLD)
        self.btn_sandbox_toggle.pack(side="left", padx=2)

        self.btn_chevron = tk.Button(self.header, text="▲", fg="#a6adc8", bg="#11111b", bd=0,
                                     activebackground="#313244", activeforeground="#cdd6f4",
                                     command=self.toggle_collapse, font=FONT_UI_SMALL_BOLD, width=2)
        self.btn_chevron.pack(side="left", padx=2)

        self.hdr_quick_frame = tk.Frame(self.header, bg="#11111b")
        
        self.hdr_btn_rec = tk.Button(self.hdr_quick_frame, text="🔴", bg="#11111b", fg="#a6e3a1", bd=0,
                                     font=FONT_UI_BOLD, command=self.toggle_rec)
        self.hdr_btn_rec.pack(side="left", padx=2)

        self.hdr_btn_play = tk.Button(self.hdr_quick_frame, text="▶", bg="#11111b", fg="#89b4fa", bd=0,
                                    font=FONT_UI_BOLD, command=self.toggle_play)
        self.hdr_btn_play.pack(side="left", padx=2)

        self.hdr_speed_var = tk.StringVar(value="1.0x")
        self.hdr_speed_menu = ttk.Combobox(self.hdr_quick_frame, textvariable=self.hdr_speed_var,
                                           values=["0.5x", "1.0x", "1.5x", "2.0x", "5.0x"], width=4, state="readonly", font=FONT_UI_SMALL)
        self.hdr_speed_menu.pack(side="left", padx=2)

        close_btn = tk.Button(self.header, text="✕", fg="#a6adc8", bg="#11111b", bd=0, activebackground="#f38ba8",
                              activeforeground="#11111b", command=self.on_close, font=FONT_UI)
        close_btn.pack(side="right", padx=8)

        self.cps_lbl = tk.Label(self.header, text="0 CPS", fg="#a6e3a1", bg="#11111b", font=FONT_UI_BOLD)
        self.cps_lbl.pack(side="right", padx=6)

        self.header.bind("<Button-1>", self.start_move)
        self.header.bind("<B1-Motion>", self.do_move)

        self.body = tk.Frame(self.main_container, bg="#1e1e2e")
        self.body.pack(fill="both", expand=True, padx=10, pady=6)

        preset_frame = tk.Frame(self.body, bg="#1e1e2e")
        preset_frame.pack(fill="x", pady=2)

        tk.Label(preset_frame, text="Macro:", fg="#a6adc8", bg="#1e1e2e", font=FONT_UI_SMALL).pack(side="left")
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(preset_frame, textvariable=self.preset_var, values=self.engine.get_presets(), width=10, state="readonly", font=FONT_UI_SMALL)
        self.preset_combo.pack(side="left", padx=3)
        if self.preset_combo['values']: self.preset_combo.current(0)

        self.btn_del = tk.Button(preset_frame, text="🗑", bg="#313244", fg="#f38ba8", bd=0, width=3, font=FONT_UI_SMALL_BOLD, command=self.action_delete)
        self.btn_del.pack(side="left", padx=2)

        self.btn_rec = tk.Button(preset_frame, text="🔴 Rec", bg="#313244", fg="#a6e3a1", bd=0, width=6, font=FONT_UI_SMALL_BOLD, command=self.toggle_rec)
        self.btn_rec.pack(side="left", padx=3)

        self.btn_play = tk.Button(preset_frame, text="▶ Jouer", bg="#313244", fg="#89b4fa", bd=0, width=6, font=FONT_UI_SMALL_BOLD, command=self.toggle_play)
        self.btn_play.pack(side="left", padx=3)

        opt_frame = tk.Frame(self.body, bg="#1e1e2e")
        opt_frame.pack(fill="x", pady=2)

        tk.Label(opt_frame, text="Vit:", fg="#a6adc8", bg="#1e1e2e", font=FONT_UI_SMALL).pack(side="left")
        self.speed_var = tk.StringVar(value="1.0x")
        speed_menu = ttk.Combobox(opt_frame, textvariable=self.speed_var, values=["0.5x", "1.0x", "1.5x", "2.0x", "5.0x"], width=4, state="readonly", font=FONT_UI_SMALL)
        speed_menu.pack(side="left", padx=3)

        tk.Label(opt_frame, text="Boucle:", fg="#a6adc8", bg="#1e1e2e", font=FONT_UI_SMALL).pack(side="left", padx=(6, 0))
        self.loop_var = tk.IntVar(value=1)
        loop_spin = tk.Spinbox(opt_frame, from_=1, to=999, textvariable=self.loop_var, width=3, bg="#313244", fg="#cdd6f4", bd=0, font=FONT_UI_SMALL)
        loop_spin.pack(side="left", padx=3)

        self.btn_copy = tk.Button(opt_frame, text="📋 Copier", bg="#313244", fg="#fab387", bd=0, font=FONT_UI_SMALL_BOLD, command=self.action_copy)
        self.btn_copy.pack(side="left", padx=4)

        self.btn_paste = tk.Button(opt_frame, text="📂 Win+V", bg="#313244", fg="#f9e2af", bd=0, font=FONT_UI_SMALL_BOLD, command=self.action_paste_menu)
        self.btn_paste.pack(side="left", padx=2)

        self.status_lbl = tk.Label(self.body, text="Prêt", fg="#6c7086", bg="#1e1e2e", font=("Helvetica", 8, "italic"))
        self.status_lbl.pack(side="left", pady=2)

        # Sandbox
        self.sandbox_frame = tk.Frame(self.main_container, bg="#181825")
        sb_controls = tk.Frame(self.sandbox_frame, bg="#181825")
        sb_controls.pack(fill="x", padx=10, pady=4)

        tk.Label(sb_controls, text="Orchestrateur :", fg="#cdd6f4", bg="#181825", font=FONT_UI_SMALL_BOLD).pack(side="left")

        self.sb_add_btn = tk.Button(sb_controls, text="➕", bg="#313244", fg="#a6e3a1", bd=0, font=FONT_UI_SMALL, command=self.sandbox_add_macro)
        self.sb_add_btn.pack(side="left", padx=2)
        
        self.sb_del_btn = tk.Button(sb_controls, text="➖", bg="#313244", fg="#f38ba8", bd=0, font=FONT_UI_SMALL, command=self.sandbox_remove_macro)
        self.sb_del_btn.pack(side="left", padx=2)

        self.sb_reset_btn = tk.Button(sb_controls, text="🧹 Vider", bg="#313244", fg="#f9e2af", bd=0, font=FONT_UI_SMALL_BOLD, command=self.sandbox_clear)
        self.sb_reset_btn.pack(side="left", padx=4)
        
        self.sb_up_btn = tk.Button(sb_controls, text="↑", bg="#313244", fg="#89b4fa", bd=0, font=FONT_UI_SMALL_BOLD, width=2, command=self.sandbox_move_up)
        self.sb_up_btn.pack(side="left", padx=2)
        
        self.sb_down_btn = tk.Button(sb_controls, text="↓", bg="#313244", fg="#89b4fa", bd=0, font=FONT_UI_SMALL_BOLD, width=2, command=self.sandbox_move_down)
        self.sb_down_btn.pack(side="left", padx=2)

        self.sb_run_btn = tk.Button(sb_controls, text="🚀 Lancer Séquence", bg="#89b4fa", fg="#11111b", bd=0, font=FONT_UI_SMALL_BOLD, command=self.sandbox_run)
        self.sb_run_btn.pack(side="right", padx=2)

        self.sandbox_listbox = tk.Listbox(self.sandbox_frame, bg="#1e1e2e", fg="#cdd6f4", selectbackground="#45475a", bd=0, height=4, font=FONT_UI_SMALL)
        self.sandbox_listbox.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # Easter Egg Curseur
        self.cursor_frame = tk.Frame(self.main_container, bg="#11111b")
        tk.Label(self.cursor_frame, text="⚡ MODDING CURSEUR ⚡", fg="#f9e2af", bg="#11111b", font=FONT_UI_SMALL_BOLD).pack(pady=(2,0))
        c_nav_frame = tk.Frame(self.cursor_frame, bg="#11111b")
        c_nav_frame.pack(fill="x", pady=2)
        tk.Button(c_nav_frame, text="◄", fg="#cdd6f4", bg="#313244", bd=0, command=self.cursor_prev).pack(side="left", padx=10)
        self.cursor_lbl = tk.Label(c_nav_frame, text="Normal", fg="#89b4fa", bg="#11111b", font=FONT_UI_BOLD, width=18)
        self.cursor_lbl.pack(side="left", expand=True)
        tk.Button(c_nav_frame, text="►", fg="#cdd6f4", bg="#313244", bd=0, command=self.cursor_next).pack(side="right", padx=10)
        tk.Button(self.cursor_frame, text="Restauration Origine", fg="#11111b", bg="#f38ba8", bd=0, font=("Helvetica", 7, "bold"), command=self.cursor_reset).pack(pady=(0,4))

    def toggle_collapse(self):
        if not self.is_collapsed:
            self.body.pack_forget()
            if self.sandbox_visible: self.sandbox_frame.pack_forget()
            if self.cursor_menu_open: self.cursor_frame.pack_forget()
            
            self.hdr_quick_frame.pack(side="left", padx=8)
            self.btn_chevron.config(text="▼")
            self.geometry(f"520x36+{self.winfo_x()}+{self.winfo_y()}")
            self.is_collapsed = True
        else:
            self.hdr_quick_frame.pack_forget()
            self.body.pack(fill="both", expand=True, padx=10, pady=6)
            if self.sandbox_visible: self.sandbox_frame.pack(fill="both", expand=True, side="bottom")
            if self.cursor_menu_open: self.cursor_frame.pack(fill="x", side="bottom")
            
            self.btn_chevron.config(text="▲")
            self.recalc_geometry()
            self.is_collapsed = False

    def recalc_geometry(self):
        h = 150
        if self.sandbox_visible: h += 110
        if self.cursor_menu_open: h += 65
        self.geometry(f"520x{h}+{self.winfo_x()}+{self.winfo_y()}")

    def update_cps_display(self):
        try:
            cps = self.engine.get_cps()
            color = "#f38ba8" if cps > 6 else "#f9e2af" if cps > 3 else "#a6e3a1"
            self.cps_lbl.config(text=f"{cps} CPS", fg=color)
        except:
            pass
        self.after(100, self.update_cps_display)

    def on_logo_click(self, event):
        now = time.time()
        if now - self.last_logo_click_time < 0.5: self.logo_clicks += 1
        else: self.logo_clicks = 1
        self.last_logo_click_time = now

        if self.logo_clicks >= 5:
            self.logo_clicks = 0
            self.toggle_cursor_menu()

    def toggle_cursor_menu(self):
        if self.is_collapsed: return
        if not self.cursor_menu_open:
            self.cursor_frame.pack(fill="x", side="bottom")
            self.cursor_menu_open = True
            self.recalc_geometry()
            self.update_status("Menu Secret Débloqué !", "#f9e2af")
        else:
            self.cursor_frame.pack_forget()
            self.cursor_menu_open = False
            self.recalc_geometry()

    def update_cursor_display(self):
        keys = list(CURSOR_TYPES.keys())
        selected_key = keys[self.cursor_index]
        self.cursor_lbl.config(text=selected_key)
        self.engine.set_system_cursor(selected_key)

    def cursor_prev(self):
        if not self.cursor_menu_open: return
        keys = list(CURSOR_TYPES.keys())
        self.cursor_index = (self.cursor_index - 1) % len(keys)
        self.update_cursor_display()

    def cursor_next(self):
        if not self.cursor_menu_open: return
        keys = list(CURSOR_TYPES.keys())
        self.cursor_index = (self.cursor_index + 1) % len(keys)
        self.update_cursor_display()

    def cursor_reset(self):
        self.cursor_index = 0
        self.cursor_lbl.config(text="Normal")
        self.engine.restore_system_cursor()

    def toggle_sandbox(self):
        if self.is_collapsed: self.toggle_collapse()
        if not self.sandbox_visible:
            self.sandbox_frame.pack(fill="both", expand=True, side="bottom")
            self.btn_sandbox_toggle.config(text="📦 Sandbox ▴")
            self.sandbox_visible = True
        else:
            self.sandbox_frame.pack_forget()
            self.btn_sandbox_toggle.config(text="📦 Sandbox ▾")
            self.sandbox_visible = False
        self.recalc_geometry()

    def sandbox_add_macro(self):
        preset = self.preset_var.get()
        if preset: self.sandbox_listbox.insert(tk.END, preset)

    def sandbox_remove_macro(self):
        sel = self.sandbox_listbox.curselection()
        if sel: self.sandbox_listbox.delete(sel[0])

    def sandbox_clear(self):
        self.sandbox_listbox.delete(0, tk.END)
        
    def sandbox_move_up(self):
        sel = self.sandbox_listbox.curselection()
        if not sel: return
        idx = sel[0]
        if idx > 0:
            val = self.sandbox_listbox.get(idx)
            self.sandbox_listbox.delete(idx)
            self.sandbox_listbox.insert(idx - 1, val)
            self.sandbox_listbox.selection_set(idx - 1)

    def sandbox_move_down(self):
        sel = self.sandbox_listbox.curselection()
        if not sel: return
        idx = sel[0]
        if idx < self.sandbox_listbox.size() - 1:
            val = self.sandbox_listbox.get(idx)
            self.sandbox_listbox.delete(idx)
            self.sandbox_listbox.insert(idx + 1, val)
            self.sandbox_listbox.selection_set(idx + 1)

    def sandbox_run(self):
        items = self.sandbox_listbox.get(0, tk.END)
        if not items: return
        try:
            sp_val = float(
                (self.hdr_speed_var.get() if self.is_collapsed else self.speed_var.get())
                .replace("x", "")
            )
            sp_val = max(0.01, sp_val)
            loops = max(1, int(self.loop_var.get()))
        except (ValueError, TypeError, tk.TclError):
            sp_val = 1.0
            loops = 1
        self.btn_play.config(text="⏹ Stop", fg="#f38ba8")
        self.hdr_btn_play.config(text="⏹", fg="#f38ba8")
        self.btn_rec.config(state="disabled")
        self.engine.replay_sequence(list(items), sp_val, loops, self.on_play_done, self.update_status)

    def start_move(self, event):
        self._offset_x, self._offset_y = event.x, event.y

    def do_move(self, event):
        self.geometry(f"+{self.winfo_x() + (event.x - self._offset_x)}+{self.winfo_y() + (event.y - self._offset_y)}")

    def update_status(self, text, color):
        self.after(0, lambda: self.status_lbl.config(text=text, fg=color))

    def action_delete(self):
        preset = self.preset_var.get()
        if preset and messagebox.askyesno("Confirmation", f"Supprimer '{preset}' ?"):
            self.engine.delete_preset(preset)
            self.preset_combo['values'] = self.engine.get_presets()
            if self.preset_combo['values']: self.preset_combo.current(0)
            else: self.preset_var.set("")

    def toggle_rec(self):
        if not self.engine.is_recording:
            name = simpledialog.askstring("Macro", "Nom :", parent=self)
            if not name: return
            self.current_preset = name
            if not self.engine.start_record():
                self.status_lbl.config(
                    text="pynput requis pour enregistrer",
                    fg="#f38ba8"
                )
                return

            self.btn_rec.config(text="⏹ Stop", fg="#f38ba8")
            self.hdr_btn_rec.config(text="⏹", fg="#f38ba8")
            self.btn_play.config(state="disabled")
            self.status_lbl.config(text="REC EN COURS...", fg="#f38ba8")
        else:
            self.engine.stop_record(self.current_preset)
            
            self.btn_rec.config(text="🔴 Rec", fg="#a6e3a1")
            self.hdr_btn_rec.config(text="🔴", fg="#a6e3a1")
            self.btn_play.config(state="normal")

            self.status_lbl.config(text="Sauvegardé !", fg="#a6e3a1")
            self.preset_combo['values'] = self.engine.get_presets()
            self.preset_var.set(self.current_preset)

    def toggle_play(self):
        if not self.engine.is_replaying:
            preset = self.preset_var.get()
            if not preset: return
            try:
                sp_val = float(
                    (self.hdr_speed_var.get() if self.is_collapsed else self.speed_var.get())
                    .replace("x", "")
                )
                sp_val = max(0.01, sp_val)
                loops = max(1, int(self.loop_var.get()))
            except (ValueError, TypeError, tk.TclError):
                sp_val = 1.0
                loops = 1
            self.btn_play.config(text="⏹ Stop", fg="#f38ba8")
            self.hdr_btn_play.config(text="⏹", fg="#f38ba8")
            self.btn_rec.config(state="disabled")
            self.engine.replay(preset, sp_val, loops, self.on_play_done, self.update_status)
        else:
            self.engine.stop_replay()
            self.on_play_done()

    def on_play_done(self):
        self.after(0, lambda: [
            self.btn_play.config(text="▶ Jouer", fg="#89b4fa"),
            self.hdr_btn_play.config(text="▶", fg="#89b4fa"),
            self.btn_rec.config(state="normal"),
            self.status_lbl.config(text="Terminé", fg="#6c7086")
        ])

    def action_copy(self):
        preset = self.preset_var.get()
        text = self.engine.extract_text(preset)
        if text:
            try:
                self.clipboard_clear()
                self.clipboard_append(text)
            except:
                pass

    def action_paste_menu(self, event=None):
        count = simpledialog.askinteger("Répétition", "Combien de fois ?", initialvalue=1, minvalue=1, parent=self)
        if not count: return
        if not PYNPUT_AVAILABLE or self.engine.key_ctrl is None:
            self.status_lbl.config(text="pynput requis pour Win+V", fg="#f38ba8")
            return

        def paste_task():
            for _ in range(count):
                try:
                    self.engine.is_executing_action = True
                    self.engine.key_ctrl.press(keyboard.Key.cmd)
                    self.engine.key_ctrl.tap('v')
                    self.engine.key_ctrl.release(keyboard.Key.cmd)
                except Exception as e:
                    print(f"Erreur Win+V : {e}")
                finally:
                    self.engine.is_executing_action = False
                time.sleep(0.4)

        threading.Thread(target=paste_task, daemon=True).start()

    def on_close(self):
        self.engine.shutdown()
        self.destroy()

if __name__ == "__main__":
    try:
        bot_engine = Engine()
        app = GameBarGUI(bot_engine)
        app.mainloop()
    except Exception as e:
        print(f"Erreur au démarrage : {e}")
        raise