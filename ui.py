import math
import tkinter as tk
from pathlib import Path
from time import monotonic

from models import Settings, Task, STATE_LABELS
from windows import clamp_position, get_screens, raise_window, screen_for_rect


BG = "#111B23"
CARD = "#1B2934"
MUTED = "#9AAEBB"
TEXT = "#EDF4F5"
MINT = "#95E3CC"
TRANSPARENT = "#010203"
COLORS = {
    "idle": MINT, "thinking": "#B7AEFA", "running": "#8BCFF1",
    "waiting": "#F8D48A", "completed": MINT, "failed": "#F6A4A4",
    "interrupted": "#D8B8EE", "unknown": MUTED, "offline": MUTED,
}


class PetUI:
    def __init__(self, root, settings: Settings, on_send, on_open, on_save, on_quit):
        self.root = root
        self.settings = settings
        self.on_send = on_send
        self.on_open = on_open
        self.on_save = on_save
        self.on_quit = on_quit
        self.state = "idle"
        self.base_state = "idle"
        self.state_started = monotonic()
        self.message = ""
        self.tasks = []
        self.frame = 0
        self.dragged = False
        self.busy = False
        self.bubble_timer = None
        self.current_tab = "chat"
        self.panel_height = min(690, root.winfo_screenheight() - 70)
        self.last_task_signature = ()
        self.font = ("Microsoft YaHei UI", 10)
        self.screens = get_screens()
        root.title("Orbit · 桌面宠物")
        self.app_icon = tk.PhotoImage(master=root, data=(Path(__file__).parent / "assets" / "orbit.png").read_bytes(), format="png")
        root.iconphoto(True, self.app_icon)
        root.configure(bg=TRANSPARENT)
        root.overrideredirect(True)
        root.attributes("-transparentcolor", TRANSPARENT)
        root.attributes("-topmost", settings.topmost)
        self.canvas = tk.Canvas(root, bg=TRANSPARENT, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        self.canvas.bind("<Button-3>", self._context_menu)
        self.topmost_var = tk.BooleanVar(value=settings.topmost)
        self.quiet_var = tk.BooleanVar(value=settings.quiet)
        self.size_var = tk.IntVar(value=settings.pet_size)
        self.menu = tk.Menu(root, tearoff=False, bg=CARD, fg=TEXT,
                            activebackground="#304657", activeforeground=TEXT, font=self.font)
        self.menu.add_command(label="和 Orbit 聊聊", command=self.show_panel)
        self.menu.add_command(label="查看 Codex 任务", command=lambda: self.show_panel("tasks"))
        self.menu.add_command(label="打开 Codex", command=lambda: on_open(""))
        self.menu.add_separator()
        self.menu.add_checkbutton(label="总在最前", variable=self.topmost_var,
                                  command=self._quick_settings)
        self.menu.add_checkbutton(label="免打扰", variable=self.quiet_var,
                                  command=self._quick_settings)
        size_menu = tk.Menu(self.menu, tearoff=False, bg=CARD, fg=TEXT, font=self.font)
        for label, size in [("小 · 160", 160), ("中 · 200", 200), ("大 · 240", 240)]:
            size_menu.add_radiobutton(label=label, value=size, variable=self.size_var,
                                      command=self._quick_settings)
        self.menu.add_cascade(label="宠物大小", menu=size_menu)
        self.menu.add_command(label="设置", command=lambda: self.show_panel("settings"))
        self.menu.add_separator()
        self.menu.add_command(label="退出 Orbit", command=on_quit)
        self.pet_source = tk.PhotoImage(master=root, data=(Path(__file__).parent / "assets" / "shinchan.png").read_bytes(), format="png")
        self.pet_base = self.pet_source.subsample(max(1, max(self.pet_source.width(), self.pet_source.height()) // 200))
        self.image_size = 0
        self._resize_pet()
        self.panel = tk.Toplevel(root)
        self.panel.withdraw()
        self.panel.title("Orbit · AI 桌面伙伴")
        self.panel.configure(bg=BG)
        self.panel.resizable(False, False)
        self.panel.attributes("-topmost", settings.topmost)
        self.panel.protocol("WM_DELETE_WINDOW", self.panel.withdraw)
        self.panel.bind("<Escape>", lambda event: self.panel.withdraw())
        self.panel.bind("<MouseWheel>", self._scroll_tasks)
        self._build_panel()
        self._build_pet()
        self._animate()
        self.root.after(2000, self._keep_visible)

    def _button(self, parent, text, command, accent=False, **options):
        color = MINT if accent else CARD
        button = tk.Button(parent, text=text, command=command, bg=color,
                           fg=BG if accent else TEXT, activebackground="#B8F1E0" if accent else "#304657",
                           activeforeground=BG if accent else TEXT, relief="flat", bd=0,
                           cursor="hand2", font=self.font, padx=12, pady=7, **options)
        return button

    def _build_panel(self):
        shell = tk.Frame(self.panel, bg=BG, highlightbackground="#34444E", highlightthickness=1)
        shell.pack(fill="both", expand=True)
        header = tk.Frame(shell, bg=BG)
        header.pack(fill="x", padx=22, pady=(19, 10))
        logo = tk.Label(header, text="◉  ORBIT", font=("Segoe UI", 17, "bold"), bg=BG, fg=MINT)
        logo.pack(side="left")
        self._button(header, "×", self.panel.withdraw).pack(side="right")
        for widget in (header, logo):
            widget.bind("<ButtonPress-1>", self._panel_drag_start)
            widget.bind("<B1-Motion>", self._panel_drag_move)
        tk.Label(shell, text="陪你聊天，也陪你等代码完成。", bg=BG, fg=MUTED,
                 font=self.font).pack(anchor="w", padx=24, pady=(0, 15))
        status_row = tk.Frame(shell, bg=CARD)
        status_row.pack(fill="x", padx=22, pady=(0, 17))
        self.status_label = tk.Label(status_row, text="●  空闲", font=self.font, fg=MINT, bg=CARD)
        self.status_label.pack(side="left", padx=12, pady=9)
        self._button(status_row, "打开 Codex ↗", lambda: self.on_open("")).pack(side="right", padx=2)
        tabbar = tk.Frame(shell, bg=BG)
        tabbar.pack(fill="x", padx=22)
        self.tab_buttons = {}
        self.tabs = {}
        for name, label in [("chat", "聊一聊"), ("tasks", "Codex 任务"), ("settings", "设置")]:
            button = self._button(tabbar, label, lambda tab=name: self._select_tab(tab))
            button.pack(side="left", fill="x", expand=True, padx=(0, 5))
            self.tab_buttons[name] = button
            self.tabs[name] = tk.Frame(shell, bg=BG)
        self._build_chat()
        self._build_tasks()
        self._build_settings()
        footer = tk.Frame(shell, bg=BG)
        footer.pack(side="bottom", fill="x", padx=22, pady=(0, 13))
        tk.Label(footer, text="ORBIT  /  DESKTOP COMPANION", font=("Segoe UI", 8),
                 fg="#6D8796", bg=BG).pack(side="left")
        tk.Button(footer, text="找回宠物", command=self.restore_pet, relief="flat", bd=0,
                  bg=BG, fg=MINT, activebackground=CARD, activeforeground=TEXT,
                  font=("Microsoft YaHei UI", 9), cursor="hand2").pack(side="left", padx=12)
        tk.Button(footer, text="退出", command=self.on_quit, relief="flat", bd=0,
                  bg=BG, fg=MUTED, activebackground=CARD, activeforeground=TEXT,
                  font=("Microsoft YaHei UI", 9), cursor="hand2").pack(side="right")
        self._select_tab("chat")

    def _build_chat(self):
        frame = self.tabs["chat"]
        self.chat = tk.Text(frame, bg=BG, fg=TEXT, font=self.font, relief="flat", bd=0,
                            wrap="word", height=1, padx=4, pady=8, cursor="arrow",
                            selectbackground="#355569", spacing1=5, spacing3=6,
                            highlightthickness=0, state="disabled")
        self.chat.pack(fill="both", expand=True)
        self.chat.tag_configure("orbit", foreground=MINT, font=("Segoe UI", 10, "bold"))
        self.chat.tag_configure("you", foreground="#B6CFF5", font=("Microsoft YaHei UI", 10, "bold"))
        self.chat.tag_configure("error", foreground="#F6A4A4")
        self.chat.configure(state="normal")
        self.chat.insert("end", "ORBIT\n", "orbit")
        self.chat.insert("end", "你好，我是你的桌面小伙伴。\n\n先在设置中连接 AI，然后就可以和我聊天了。任务面板会显示本机 Codex 的真实记录。\n")
        self.chat.configure(state="disabled")
        self.include_tasks = tk.BooleanVar(value=False)
        tk.Checkbutton(frame, text="结合当前任务状态", variable=self.include_tasks,
                       font=("Microsoft YaHei UI", 9), bg=BG, fg=MUTED,
                       selectcolor=CARD, activebackground=BG, activeforeground=TEXT,
                       highlightthickness=0, bd=0).pack(anchor="w", pady=(8, 4))
        entry_row = tk.Frame(frame, bg=CARD, highlightbackground="#344C58", highlightthickness=1)
        entry_row.pack(fill="x", pady=(0, 12))
        self.input = tk.Entry(entry_row, font=self.font, bg=CARD, fg=TEXT,
                              insertbackground=MINT, relief="flat", bd=0)
        self.input.pack(side="left", fill="x", expand=True, padx=12, pady=12)
        self.input.bind("<Return>", self._send)
        self.send_button = self._button(entry_row, "发送 ↑", self._send, True)
        self.send_button.pack(side="right", padx=4, pady=4)

    def _build_tasks(self):
        frame = self.tabs["tasks"]
        self.connection_label = tk.Label(frame, text="正在读取本机任务…", bg=BG, fg=MUTED,
                                         font=("Microsoft YaHei UI", 9), anchor="w", wraplength=364)
        self.connection_label.pack(fill="x", pady=(12, 10))
        scroll = tk.Scrollbar(frame, orient="vertical", relief="flat", bd=0)
        self.task_canvas = tk.Canvas(frame, bg=BG, highlightthickness=0, yscrollcommand=scroll.set)
        scroll.configure(command=self.task_canvas.yview)
        scroll.pack(side="right", fill="y")
        self.task_canvas.pack(side="left", fill="both", expand=True)
        self.task_list = tk.Frame(self.task_canvas, bg=BG)
        self.task_window = self.task_canvas.create_window(0, 0, window=self.task_list, anchor="nw")
        self.task_list.bind("<Configure>", lambda event: self.task_canvas.configure(
            scrollregion=self.task_canvas.bbox("all")))
        self.task_canvas.bind("<Configure>", lambda event: self.task_canvas.itemconfigure(
            self.task_window, width=event.width))
        self.empty_tasks = tk.Label(self.task_list, text="暂时没有任务\n在 Codex 中开始一次对话吧。",
                                    bg=BG, fg=MUTED, font=self.font, pady=50)
        self.empty_tasks.pack(fill="x")

    def _build_settings(self):
        frame = self.tabs["settings"]
        tk.Label(frame, text="AI 连接", font=("Microsoft YaHei UI", 11, "bold"),
                 bg=BG, fg=TEXT).pack(anchor="w", pady=(16, 9))
        tk.Label(frame, text="OpenAI API Key · 仅本次运行使用", font=("Microsoft YaHei UI", 9),
                 bg=BG, fg=MUTED).pack(anchor="w")
        self.key_var = tk.StringVar(value=self.settings.api_key)
        tk.Entry(frame, textvariable=self.key_var, show="●", bg=CARD, fg=TEXT,
                 insertbackground=MINT, relief="flat", font=self.font).pack(fill="x", ipady=8, pady=(5, 10))
        tk.Label(frame, text="模型名称 · 填写账户可用的模型", bg=BG, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        self.model_var = tk.StringVar(value=self.settings.model)
        tk.Entry(frame, textvariable=self.model_var, bg=CARD, fg=TEXT,
                 insertbackground=MINT, relief="flat", font=self.font).pack(fill="x", ipady=8, pady=(5, 7))
        tk.Label(frame, text="也可通过 OPENAI_API_KEY / OPENAI_MODEL 设置。",
                 bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 8)).pack(anchor="w")
        tk.Label(frame, text="桌面偏好", font=("Microsoft YaHei UI", 11, "bold"),
                 bg=BG, fg=TEXT).pack(anchor="w", pady=(18, 6))
        toggles = tk.Frame(frame, bg=BG)
        toggles.pack(fill="x")
        for text, variable in [("总在最前", self.topmost_var), ("免打扰", self.quiet_var)]:
            tk.Checkbutton(toggles, text=text, variable=variable, font=self.font,
                           bg=BG, fg=TEXT, selectcolor=CARD, activebackground=BG,
                           activeforeground=TEXT, bd=0, highlightthickness=0).pack(side="left", padx=(0, 14))
        size_row = tk.Frame(frame, bg=BG)
        size_row.pack(fill="x", pady=(5, 8))
        tk.Label(size_row, text="宠物大小", bg=BG, fg=MUTED, font=self.font).pack(side="left")
        tk.Scale(size_row, from_=160, to=260, resolution=20, orient="horizontal",
                 variable=self.size_var, bg=BG, fg=TEXT, troughcolor=CARD,
                 activebackground=MINT, highlightthickness=0, bd=0,
                 font=("Segoe UI", 9), length=230).pack(side="right")
        self._button(frame, "保存设置", self._save_settings, True).pack(fill="x", pady=(5, 8))
        self.settings_note = tk.Label(frame, text="当前形象：你提供的小新。",
                                      font=("Microsoft YaHei UI", 8), fg=MUTED, bg=BG, wraplength=370)
        self.settings_note.pack(anchor="w")

    def _select_tab(self, tab):
        for name, frame in self.tabs.items():
            frame.pack_forget()
            self.tab_buttons[name].configure(bg=MINT if name == tab else CARD,
                                             fg=BG if name == tab else MUTED)
        self.current_tab = tab
        self.tabs[tab].pack(fill="both", expand=True, padx=22, pady=(4, 6))

    def show_panel(self, tab="chat"):
        self.show_pet()
        self._select_tab(tab)
        screen = screen_for_rect(self.root.winfo_x(), self.root.winfo_y(), self.width, self.height, self.screens)
        self.panel_height = min(690, screen.bottom - screen.top - 40)
        x, y = clamp_position(self.root.winfo_x() - 440, self.root.winfo_y() - 340,
                              430, self.panel_height + 40, screen)
        self.panel.geometry(f"430x{self.panel_height}+{x}+{y}")
        self.panel.deiconify()
        self.panel.lift()
        if tab == "chat":
            self.input.focus_set()

    def show_pet(self):
        self.root.update_idletasks()
        screen = screen_for_rect(self.root.winfo_x(), self.root.winfo_y(), self.width, self.height, self.screens)
        x, y = clamp_position(self.root.winfo_x(), self.root.winfo_y(), self.width, self.height, screen)
        if (x, y) != (self.root.winfo_x(), self.root.winfo_y()):
            self.root.geometry(f"+{x}+{y}")
            self._remember_position(x, y, screen)
            self.on_save()
        if not self.root.winfo_ismapped():
            self.root.deiconify()
        self.root.attributes("-topmost", self.settings.topmost)
        raise_window(self.root.winfo_id(), self.settings.topmost)
        if self.panel.state() == "normal":
            raise_window(self.panel.winfo_id(), self.settings.topmost)

    def restore_pet(self):
        self.settings.monitor = ""
        self.settings.x = -1
        self.settings.y = -1
        self._resize_pet()
        self.show_pet()
        self.on_save()

    def _keep_visible(self):
        screens = get_screens()
        if screens != self.screens:
            self.screens = screens
            self._resize_pet()
            self.on_save()
            if self.panel.state() == "normal":
                self.show_panel(self.current_tab)
        screen = screen_for_rect(self.root.winfo_x(), self.root.winfo_y(), self.width, self.height, self.screens)
        if self.settings.topmost and (
            not self.root.winfo_ismapped()
            or not self.root.attributes("-topmost")
            or clamp_position(self.root.winfo_x(), self.root.winfo_y(), self.width, self.height, screen)
            != (self.root.winfo_x(), self.root.winfo_y())
        ):
            self.show_pet()
        self.root.after(2000, self._keep_visible)

    def _send(self, event=None):
        if self.busy or not self.input.get().strip():
            return
        self.on_send(self.input.get().strip(), self.include_tasks.get())

    def start_reply(self, user_text):
        self.busy = True
        self.input.delete(0, "end")
        self.input.configure(state="disabled")
        self.send_button.configure(state="disabled", text="回复中")
        self.chat.configure(state="normal")
        self.chat.insert("end", "\n你\n", "you")
        self.chat.insert("end", user_text + "\n\n")
        self.chat.insert("end", "ORBIT\n", "orbit")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def append_reply(self, text):
        self.chat.configure(state="normal")
        self.chat.insert("end", text)
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def finish_reply(self, error=""):
        self.busy = False
        self.chat.configure(state="normal")
        if error:
            self.chat.insert("end", "\n" + error, "error")
        self.chat.insert("end", "\n")
        self.chat.configure(state="disabled")
        self.input.configure(state="normal")
        self.send_button.configure(state="normal", text="发送 ↑")
        self.chat.see("end")

    def set_tasks(self, tasks: list[Task], connection_message):
        self.tasks = tasks
        self.connection_label.configure(text=connection_message)
        signature = tuple(tasks)
        if signature == self.last_task_signature:
            return
        self.last_task_signature = signature
        for child in self.task_list.winfo_children():
            child.destroy()
        if not tasks:
            tk.Label(self.task_list, text="暂时没有任务\n在 Codex 中开始一次对话吧。",
                     bg=BG, fg=MUTED, font=self.font, pady=50).pack(fill="x")
            return
        for task in tasks[:20]:
            card = tk.Frame(self.task_list, bg=CARD, padx=13, pady=12)
            card.pack(fill="x", pady=(0, 9), padx=(0, 5))
            headline = tk.Frame(card, bg=CARD)
            headline.pack(fill="x")
            tk.Label(headline, text="● " + STATE_LABELS[task.state], bg=CARD,
                     fg=COLORS[task.state], font=("Microsoft YaHei UI", 9)).pack(side="left")
            tk.Button(headline, text="打开 ↗", bg=CARD, fg=MINT, activebackground="#304657",
                      activeforeground=MINT, relief="flat", bd=0, cursor="hand2",
                      font=("Microsoft YaHei UI", 9), command=lambda tid=task.id: self.on_open(tid)).pack(side="right")
            tk.Label(card, text=task.title, bg=CARD, fg=TEXT, font=self.font,
                     wraplength=330, justify="left", anchor="w").pack(fill="x", pady=(7, 4))
            tk.Label(card, text=task.detail, bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9),
                     wraplength=330, justify="left", anchor="w").pack(fill="x")
            tk.Label(card, text=task.updated_at, bg=CARD, fg="#7691A1", font=("Segoe UI", 8),
                     anchor="w").pack(fill="x", pady=(8, 0))

    def set_pet_state(self, state, message=""):
        self.base_state = state
        if message:
            self.notify(message, state)
            return
        if not self.message:
            self._display_state(state)

    def _display_state(self, state):
        if self.state == state:
            return
        self.state = state
        self.state_started = monotonic()
        self.status_label.configure(text="●  " + STATE_LABELS[state], fg=COLORS[state])

    def notify(self, message, state):
        if self.settings.quiet:
            return
        self._display_state(state)
        self.state_started = monotonic()
        self.message = message if len(message) <= 34 else message[:33] + "…"
        if self.bubble_timer is not None:
            self.root.after_cancel(self.bubble_timer)
        self.bubble_timer = self.root.after(7000, self._hide_bubble)

    def _hide_bubble(self):
        self.message = ""
        self.bubble_timer = None
        self._display_state(self.base_state)

    def _save_settings(self):
        self.settings.model = self.model_var.get().strip()
        self.settings.api_key = self.key_var.get().strip()
        self._quick_settings()
        self.settings_note.configure(text="已保存。API Key 仅保留在本次运行的内存中。", fg=MINT)

    def _quick_settings(self):
        self.settings.topmost = self.topmost_var.get()
        self.settings.quiet = self.quiet_var.get()
        self.settings.pet_size = self.size_var.get()
        self.root.attributes("-topmost", self.settings.topmost)
        self.panel.attributes("-topmost", self.settings.topmost)
        self._resize_pet()
        if self.settings.quiet:
            if self.bubble_timer is not None:
                self.root.after_cancel(self.bubble_timer)
            self._hide_bubble()
        self.on_save()

    def _resize_pet(self):
        self.scale = self.settings.pet_size / 200
        if self.image_size != self.settings.pet_size:
            self.pet_image = self.pet_base.zoom(round(self.settings.pet_size / 20)).subsample(
                max(1, round(max(self.pet_base.width(), self.pet_base.height()) / 21)))
            self.image_size = self.settings.pet_size
        self.width = round(260 * self.scale)
        self.height = round(290 * self.scale)
        screen = next((item for item in self.screens if item.name == self.settings.monitor),
                      screen_for_rect(self.settings.x, self.settings.y, self.width, self.height, self.screens))
        saved_position = self.settings.monitor == screen.name or (
            not self.settings.monitor and (self.settings.x, self.settings.y) != (-1, -1))
        x = (self.settings.x + (screen.left - self.settings.monitor_left if self.settings.monitor else 0)
             if saved_position else screen.right - self.width - 35)
        y = (self.settings.y + (screen.top - self.settings.monitor_top if self.settings.monitor else 0)
             if saved_position else screen.bottom - self.height - 20)
        x, y = clamp_position(x, y, self.width, self.height, screen)
        self._remember_position(x, y, screen)
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

    def _remember_position(self, x, y, screen):
        self.settings.x, self.settings.y = x, y
        self.settings.monitor = screen.name
        self.settings.monitor_left, self.settings.monitor_top = screen.left, screen.top

    def _drag_start(self, event):
        self.drag_start = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())
        self.dragged = False

    def _drag_move(self, event):
        if abs(event.x_root - self.drag_start[0]) + abs(event.y_root - self.drag_start[1]) < 5:
            return
        self.dragged = True
        screen = screen_for_rect(event.x_root, event.y_root, 1, 1, self.screens)
        x, y = clamp_position(self.drag_start[2] + event.x_root - self.drag_start[0],
                              self.drag_start[3] + event.y_root - self.drag_start[1],
                              self.width, self.height, screen)
        self.root.geometry(f"+{x}+{y}")

    def _drag_end(self, event):
        if self.dragged:
            self._remember_position(self.root.winfo_x(), self.root.winfo_y(),
                                    screen_for_rect(self.root.winfo_x(), self.root.winfo_y(), self.width, self.height, self.screens))
            self.on_save()
            return
        if self.panel.state() == "normal":
            self.panel.withdraw()
            return
        self.show_panel()

    def _panel_drag_start(self, event):
        self.panel_drag = (event.x_root - self.panel.winfo_x(), event.y_root - self.panel.winfo_y())

    def _panel_drag_move(self, event):
        x, y = clamp_position(event.x_root - self.panel_drag[0], event.y_root - self.panel_drag[1],
                              430, self.panel_height + 40,
                              screen_for_rect(event.x_root, event.y_root, 1, 1, self.screens))
        self.panel.geometry(f"+{x}+{y}")

    def _context_menu(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)

    def _scroll_tasks(self, event):
        if self.current_tab == "tasks":
            self.task_canvas.yview_scroll(-int(event.delta / 120), "units")

    def _build_pet(self):
        canvas = self.canvas
        self.items = {
            "shadow": canvas.create_oval(59, 248, 201, 263, fill="#233A44", outline=""),
            "shadow_inner": canvas.create_oval(76, 251, 184, 260, fill="#2C4D56", outline=""),
            "sprite": canvas.create_image(130, 170, image=self.pet_image),
            "spinner": canvas.create_arc(213, 86, 235, 108, extent=260, style="arc", width=3, tags="accent", state="hidden"),
            "indicator": canvas.create_text(224, 97, font=("Segoe UI", 22, "bold"), tags="accent"),
            "star_right": canvas.create_text(226, 117, text="✦", font=("Segoe UI", 22), tags="accent", state="hidden"),
            "star_left": canvas.create_text(32, 127, text="✧", fill="#F8D48A", font=("Segoe UI", 15), state="hidden"),
            "count_bg": canvas.create_oval(177, 201, 203, 227, outline=BG, width=2, tags="accent", state="hidden"),
            "count": canvas.create_text(190, 214, fill=BG, font=("Segoe UI", 10, "bold")),
            "bubble": canvas.create_polygon(20, 12, 240, 12, 240, 62, 141, 62, 130, 74, 119, 62, 20, 62,
                                             fill=BG, outline="#3F5865", width=1, smooth=True, state="hidden"),
            "message": canvas.create_text(130, 36, width=204, fill=TEXT, font=("Microsoft YaHei UI", 9), justify="center"),
            "status": canvas.create_text(130, 279, text="◉  空闲", fill=MINT, font=("Microsoft YaHei UI", 9), tags="accent"),
        }
        self.draw_scale = self.scale
        self.visual_signature = ()
        canvas.scale("all", 0, 0, self.scale, self.scale)

    def _animate(self):
        if not self.root.winfo_viewable():
            self.animation_timer = self.root.after(500, self._animate)
            return
        self.frame += 1
        elapsed = monotonic() - self.state_started
        active = sum(task.state in ("running", "waiting") for task in self.tasks)
        if (self.state, self.message, active, self.scale) != self.visual_signature:
            self.visual_signature = (self.state, self.message, active, self.scale)
            self.canvas.scale("all", 0, 0, self.scale / self.draw_scale, self.scale / self.draw_scale)
            self.draw_scale = self.scale
            self.canvas.itemconfigure("accent", fill=COLORS[self.state])
            self.canvas.itemconfigure(self.items["spinner"], outline=COLORS[self.state],
                                      state="normal" if self.state == "running" else "hidden")
            self.canvas.itemconfigure(self.items["indicator"], text={
                "thinking": "···", "waiting": "!", "failed": "×", "interrupted": "Ⅱ",
                "unknown": "?", "offline": "·"}.get(self.state, ""))
            for name in ("star_left", "star_right"):
                self.canvas.itemconfigure(self.items[name], state="normal" if self.state == "completed" else "hidden")
            for name in ("count_bg", "count"):
                self.canvas.itemconfigure(self.items[name], state="normal" if active else "hidden")
            self.canvas.itemconfigure(self.items["count"], text=str(active))
            for name in ("bubble", "message"):
                self.canvas.itemconfigure(self.items[name], state="normal" if self.message else "hidden")
            self.canvas.itemconfigure(self.items["message"], text=self.message, width=204 * self.scale)
            self.canvas.itemconfigure(self.items["status"], text="◉  " + STATE_LABELS[self.state])
            self.canvas.itemconfigure(self.items["sprite"], image=self.pet_image)
        sway = 4 * math.sin(elapsed * 2) if self.state == "thinking" else 0
        if self.state == "failed":
            sway = 6 * math.sin(elapsed * 24) * max(0, 1 - elapsed / 1.2)
        bob = math.sin(elapsed * 1.5) * 1.5
        if self.state == "running":
            bob = -3 * abs(math.sin(elapsed * 8))
            self.canvas.itemconfigure(self.items["spinner"], start=(elapsed * 180) % 360)
        if self.state == "completed":
            bob = -12 * max(0, math.sin(elapsed * 6)) if elapsed < 2.4 else 0
        self.canvas.coords(self.items["sprite"], (130 + sway) * self.scale, (170 + bob) * self.scale)
        self.canvas.coords(self.items["star_left"], 32 * self.scale, (127 - bob) * self.scale)
        self.canvas.coords(self.items["star_right"], 226 * self.scale, (117 + bob) * self.scale)
        self.animation_timer = self.root.after(
            80 if self.state in ("running", "thinking", "completed", "failed") else 250, self._animate)
