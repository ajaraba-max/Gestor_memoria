"""
Gestor de memoria con interfaz gráfica (Tkinter).

Modelo (sin cambios):
- RAM de 64 MB dividida en 16 marcos de 4 MB.
- Cada proceso se divide en páginas de 4 MB y se coloca en un bloque
  contiguo de marcos usando primer ajuste (partición variable).
- Si hay memoria libre pero dispersa en huecos pequeños, se produce
  fragmentación externa y se puede solucionar compactando.
- El espacio de SWAP (disco) tiene la misma capacidad que la RAM.

Ejecución:  python gestor_memoria.py
"""

import math
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from tkinter import ttk

TOTAL_MB = 64
FRAME_MB = 4
TOTAL_FRAMES = TOTAL_MB // FRAME_MB

# Colores vivos: se leen bien sobre el fondo oscuro y distinguen procesos.
PALETTE = [
    "#38bdf8", "#34d399", "#fbbf24", "#fb7185", "#a78bfa",
    "#f472b6", "#2dd4bf", "#fb923c", "#a3e635", "#818cf8",
    "#e879f9", "#22d3ee", "#facc15", "#4ade80", "#f97316", "#c084fc",
]

# Tema visual. Solo lo usa la interfaz; la lógica no depende de él.
C = {
    "bg": "#0b1020",
    "header": "#10182c",
    "card": "#141c2f",
    "inset": "#0e1526",
    "chip": "#1a2438",
    "line": "#2c3b56",
    "text": "#eef3fb",
    "muted": "#9aadc4",
    "faint": "#73859e",
    "accent": "#38bdf8",
    "accent_soft": "#0c4a6e",
    "good": "#34d399",
    "good_bg": "#064e3b",
    "warn": "#fbbf24",
    "warn_bg": "#451a03",
    "bad": "#fb7185",
    "bad_bg": "#4c0519",
    "violet": "#a78bfa",
    "free": "#1b263b",
    "white": "#f8fafc",
    "ink": "#0b1220",
}


def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(v))) for v in rgb))


def mix(a, b, t):
    """Mezcla dos colores hex. t=0 devuelve a, t=1 devuelve b."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return _hex((ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t))


def text_on(bg):
    r, g, b = _rgb(bg)
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return C["ink"] if lum > 0.62 else C["white"]


def round_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    r = min(radius, max(0, (x2 - x1) / 2), max(0, (y2 - y1) / 2))
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


class Process:
    """Proceso con nombre, tamaño, páginas y posición en RAM."""

    def __init__(self, name, size_mb, color):
        self.name = name
        self.size_mb = size_mb
        self.color = color
        self.pages = math.ceil(size_mb / FRAME_MB)
        self.start = None  # primer marco que ocupa en RAM


class MemoryManager:
    """Lógica del gestor: RAM, SWAP, huecos, compactación y páginas."""

    def __init__(self):
        self.frames = [None] * TOTAL_FRAMES  # nombre del proceso o None
        self.ram = {}   # nombre -> Process
        self.swap = {}  # nombre -> Process
        self._color_index = 0

    # ---------- Consultas ----------
    def free_frames(self):
        return self.frames.count(None)

    def holes(self):
        """Devuelve la lista de huecos como tuplas (inicio, longitud)."""
        result, start = [], None
        for i, owner in enumerate(self.frames + ["_"]):
            if owner is None and start is None:
                start = i
            elif owner is not None and start is not None:
                result.append((start, i - start))
                start = None
        return result

    def largest_hole(self):
        return max((length for _, length in self.holes()), default=0)

    def swap_used(self):
        return sum(p.pages for p in self.swap.values())

    def exists(self, name):
        return name in self.ram or name in self.swap

    def swap_slots(self):
        """Distribución del área de SWAP: TOTAL_FRAMES bloques (proceso o None)."""
        slots, index = [None] * TOTAL_FRAMES, 0
        for process in self.swap.values():
            for _ in range(process.pages):
                slots[index] = process
                index += 1
        return slots

    def page_table(self):
        """Filas (proceso, página, ubicación, marco/bloque, MB usados, MB desperdiciados).

        Incluye los procesos en RAM (número de marco) y en SWAP (número de bloque
        del área de swap, el mismo que se dibuja en pantalla).
        """
        placements = [(p, "RAM", p.start)
                      for p in sorted(self.ram.values(), key=lambda x: x.start)]
        swap_block = 0
        for p in self.swap.values():
            placements.append((p, "SWAP", swap_block))
            swap_block += p.pages
        rows = []
        for p, where, first in placements:
            for page in range(p.pages):
                used = min(FRAME_MB, p.size_mb - page * FRAME_MB)
                rows.append((p.name, page, where, first + page, used, FRAME_MB - used))
        return rows

    # ---------- Colocación (primer ajuste) ----------
    def _first_fit(self, pages):
        for start, length in self.holes():
            if length >= pages:
                return start
        return None

    def _place(self, process, start):
        process.start = start
        for i in range(start, start + process.pages):
            self.frames[i] = process.name
        self.ram[process.name] = process

    def _release(self, process):
        for i in range(process.start, process.start + process.pages):
            self.frames[i] = None
        process.start = None
        del self.ram[process.name]

    # ---------- Operaciones del menú ----------
    def create(self, name, size_mb):
        if not name:
            return False, "El nombre del proceso no puede estar vacío."
        if self.exists(name):
            return False, f"Ya existe un proceso llamado {name}."
        process = Process(name, size_mb, PALETTE[self._color_index % len(PALETTE)])
        if process.pages > TOTAL_FRAMES:
            return False, f"{name} ({size_mb} MB) es más grande que toda la RAM."
        start = self._first_fit(process.pages)
        if start is None:
            if self.free_frames() >= process.pages:
                return False, (f"Fragmentación externa: hay {self.free_frames() * FRAME_MB} MB "
                               f"libres pero dispersos. Compacte la memoria.")
            return False, "No hay memoria suficiente. Termine o envíe un proceso a SWAP."
        self._color_index += 1
        self._place(process, start)
        return True, (f"Proceso {name} creado: {size_mb} MB, {process.pages} página(s), "
                      f"marcos {start} a {start + process.pages - 1}.")

    def terminate(self, name):
        if name in self.ram:
            self._release(self.ram[name])
            return True, f"Proceso {name} terminado. Memoria liberada."
        if name in self.swap:
            del self.swap[name]
            return True, f"Proceso {name} terminado (estaba en SWAP)."
        return False, f"Proceso {name} no encontrado."

    def compact(self):
        position, moved = 0, 0
        for process in sorted(self.ram.values(), key=lambda x: x.start):
            if process.start != position:
                for i in range(process.start, process.start + process.pages):
                    self.frames[i] = None
                process.start = position
                for i in range(position, position + process.pages):
                    self.frames[i] = process.name
                moved += 1
            position += process.pages
        if moved == 0:
            return False, "La memoria ya estaba compacta."
        return True, (f"Memoria compactada: {moved} proceso(s) movido(s). "
                      f"Hueco libre contiguo de {self.largest_hole() * FRAME_MB} MB.")

    def send_to_swap(self, name):
        if name not in self.ram:
            return False, f"Proceso {name} no está en RAM."
        process = self.ram[name]
        if self.swap_used() + process.pages > TOTAL_FRAMES:
            return False, "El área de SWAP está llena."
        self._release(process)
        self.swap[name] = process
        return True, f"Proceso {name} enviado a SWAP. Se liberaron {process.pages * FRAME_MB} MB de RAM."

    def recover_from_swap(self, name):
        if name not in self.swap:
            return False, f"Proceso {name} no está en SWAP."
        process = self.swap[name]
        start = self._first_fit(process.pages)
        if start is None:
            if self.free_frames() >= process.pages:
                return False, "Hay memoria libre pero dispersa. Compacte la memoria."
            return False, "No hay espacio en RAM. Libere memoria primero."
        del self.swap[name]
        self._place(process, start)
        return True, f"Proceso {name} recuperado de SWAP en los marcos {start} a {start + process.pages - 1}."


class App:
    """Interfaz gráfica del gestor de memoria."""

    def __init__(self, root):
        self.root = root
        self.manager = MemoryManager()
        self.counter = 1
        self.ram_names, self.swap_names = [], []
        self.selected = None
        self.selected_where = None
        self._updating = False
        self._resize_job = None
        self._pulse_holes = False
        self.font = self._pick_font(("Segoe UI", "Inter", "DejaVu Sans", "Noto Sans", "Arial"))
        self.mono = self._pick_font(("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Liberation Mono"))

        root.title("Gestor de memoria")
        root.configure(bg=C["bg"])
        root.minsize(1180, 700)
        root.geometry("1320x740")
        self._center(root, 1320, 740)
        self._build_ui()
        root.bind("<Configure>", self._on_root_configure)
        self.refresh()
        root.after(60, self.refresh)
        self.log("Gestor iniciado: RAM de 64 MB (16 marcos de 4 MB). SWAP con la misma capacidad.", "info")
        self.log("Cree procesos, deje un hueco en el medio y observe la fragmentación externa.", "muted")

    # ---------- Tipografía y ventana ----------
    def _pick_font(self, candidates):
        families = set(tkfont.families())
        for name in candidates:
            if name in families:
                return name
        return "TkDefaultFont"

    def _center(self, win, w, h):
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")

    def _font(self, size, weight="normal"):
        return (self.font, size, weight)

    # ---------- Construcción ----------
    def _build_ui(self):
        tk.Frame(self.root, bg=C["accent"], height=3).pack(fill="x")
        self._build_header()

        body = tk.Frame(self.root, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=14, pady=(10, 8))

        self.ram_card, ram_inner = self._card(body, C["accent"])
        self.ram_card.pack(fill="x")
        self._section_title(ram_inner, "Memoria RAM", "64 MB  ·  16 marcos contiguos de 4 MB", C["accent"])
        self.ram_canvas = tk.Canvas(ram_inner, height=132, bg=C["card"], highlightthickness=0)
        self.ram_canvas.pack(fill="x", padx=12, pady=(2, 0))
        self.ram_canvas.bind("<Leave>", lambda _e: self._set_detail("ram"))
        self.ram_detail = self._detail_label(ram_inner)
        self.ram_detail_default = ""

        gap = tk.Frame(body, bg=C["bg"], height=8)
        gap.pack(fill="x")

        self.swap_card, swap_inner = self._card(body, C["violet"])
        self.swap_card.pack(fill="x")
        self._section_title(swap_inner, "Área de SWAP", "Disco  ·  misma capacidad que la RAM (64 MB)", C["violet"])
        self.swap_canvas = tk.Canvas(swap_inner, height=118, bg=C["card"], highlightthickness=0)
        self.swap_canvas.pack(fill="x", padx=12, pady=(2, 0))
        self.swap_canvas.bind("<Leave>", lambda _e: self._set_detail("swap"))
        self.swap_detail = self._detail_label(swap_inner)

        bottom = tk.Frame(body, bg=C["bg"])
        bottom.pack(fill="both", expand=True, pady=(8, 0))
        bottom.grid_columnconfigure(0, weight=3)
        bottom.grid_columnconfigure(1, weight=2)
        bottom.grid_rowconfigure(0, weight=1)

        lists_outer, lists = self._card(bottom, C["line"])
        lists_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        lists.grid_columnconfigure(0, weight=1)
        lists.grid_columnconfigure(1, weight=1)
        lists.grid_rowconfigure(1, weight=1)
        self._build_process_list(lists, 0, "En RAM", "ram")
        self._build_process_list(lists, 1, "En SWAP", "swap")

        ops_outer, ops = self._card(bottom, C["line"])
        ops_outer.grid(row=0, column=1, sticky="nsew")
        self._section_title(ops, "Operaciones", "Seleccione un proceso y elija una acción", C["muted"])
        self._build_actions(ops)

        log_wrap = tk.Frame(self.root, bg=C["bg"])
        log_wrap.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        log_head = tk.Frame(log_wrap, bg=C["bg"])
        log_head.pack(fill="x", pady=(0, 4))
        tk.Label(log_head, text="REGISTRO", bg=C["bg"], fg=C["faint"],
                 font=self._font(8, "bold")).pack(side="left")
        self._text_button(log_head, "Limpiar", self._clear_log).pack(side="right")

        self.log_box = tk.Text(
            log_wrap, height=5, bg=C["inset"], fg=C["text"], font=(self.mono, 9),
            relief="flat", highlightthickness=1, highlightbackground=C["line"],
            insertbackground=C["text"], padx=12, pady=8, wrap="word", state="disabled",
        )
        self.log_box.pack(fill="both", expand=True)
        for name, color in (
            ("time", C["faint"]), ("ok", C["good"]), ("err", C["bad"]),
            ("warn", C["warn"]), ("info", C["accent"]), ("muted", C["muted"]),
            ("msg", C["text"]),
        ):
            self.log_box.tag_configure(name, foreground=color)

        self._style_tree()

    def _card(self, parent, accent):
        outer = tk.Frame(parent, bg=accent)
        inner = tk.Frame(outer, bg=C["card"])
        inner.pack(fill="both", expand=True, pady=(3, 0))
        return outer, inner

    def _section_title(self, parent, title, subtitle, color):
        row = tk.Frame(parent, bg=C["card"])
        row.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(row, text=title, bg=C["card"], fg=C["text"],
                 font=self._font(12, "bold")).pack(side="left")
        tk.Label(row, text="   " + subtitle, bg=C["card"], fg=C["faint"],
                 font=self._font(9)).pack(side="left")
        return row

    def _detail_label(self, parent):
        lbl = tk.Label(parent, text="", bg=C["card"], fg=C["muted"],
                       font=self._font(9), anchor="w")
        lbl.pack(fill="x", padx=14, pady=(2, 10))
        return lbl

    def _build_header(self):
        header = tk.Frame(self.root, bg=C["header"], height=64)
        header.pack(fill="x")
        header.pack_propagate(False)

        logo = tk.Canvas(header, width=36, height=36, bg=C["header"], highlightthickness=0)
        logo.pack(side="left", padx=(16, 10), pady=14)
        tiles = ("#38bdf8", "#34d399", "#fbbf24", "#a78bfa")
        for i, color in enumerate(tiles):
            x, y = (i % 2) * 18, (i // 2) * 18
            round_rect(logo, x + 1, y + 1, x + 16, y + 16, 4, fill=color, outline="")

        titles = tk.Frame(header, bg=C["header"])
        titles.pack(side="left", pady=10)
        tk.Label(titles, text="Gestor de memoria", bg=C["header"], fg=C["text"],
                 font=self._font(16, "bold")).pack(anchor="w")
        tk.Label(titles, text="Primer ajuste  ·  partición variable  ·  páginas de 4 MB",
                 bg=C["header"], fg=C["muted"], font=self._font(9)).pack(anchor="w")

        stats = tk.Frame(header, bg=C["header"])
        stats.pack(side="right", padx=16)
        self.ram_stat = self._stat_block(stats, "RAM", C["accent"])
        self.swap_stat = self._stat_block(stats, "SWAP", C["violet"])
        self.hole_stat = self._stat_block(stats, "HUECO MAYOR", C["warn"])
        self.health = tk.Label(stats, text="Sin fragmentar", bg=C["good_bg"], fg=C["good"],
                               font=self._font(9, "bold"), padx=10, pady=6)
        self.health.pack(side="left", padx=(12, 0))

    def _stat_block(self, parent, caption, color):
        box = tk.Frame(parent, bg=C["header"])
        box.pack(side="left", padx=10)
        tk.Label(box, text=caption, bg=C["header"], fg=C["faint"],
                 font=self._font(7, "bold")).pack(anchor="w")
        value = tk.Label(box, text="—", bg=C["header"], fg=C["text"], font=self._font(12, "bold"))
        value.pack(anchor="w")
        bar = tk.Canvas(box, width=108, height=6, bg=C["header"], highlightthickness=0)
        bar.pack(anchor="w", pady=(2, 0))
        return {"value": value, "bar": bar, "color": color}

    def _build_process_list(self, parent, column, title, kind):
        wrap = tk.Frame(parent, bg=C["card"])
        wrap.grid(row=0, column=column, rowspan=2, sticky="nsew", padx=10, pady=(8, 10))
        head = tk.Frame(wrap, bg=C["card"])
        head.pack(fill="x", pady=(0, 6))
        tk.Label(head, text=title.upper(), bg=C["card"], fg=C["faint"],
                 font=self._font(8, "bold")).pack(side="left")
        count = tk.Label(head, text="0", bg=C["card"], fg=C["muted"], font=self._font(8))
        count.pack(side="right")

        holder = tk.Frame(wrap, bg=C["line"])
        holder.pack(fill="both", expand=True)
        inner = tk.Frame(holder, bg=C["inset"])
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        lb = tk.Listbox(
            inner, height=6, bg=C["inset"], fg=C["text"], font=self._font(10),
            relief="flat", highlightthickness=0, activestyle="none",
            selectbackground=C["accent"], selectforeground=C["ink"],
            exportselection=False, bd=0,
        )
        lb.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=4)
        scroll = tk.Scrollbar(inner, command=lb.yview, bg=C["inset"], troughcolor=C["inset"],
                              activebackground=C["line"], relief="flat", bd=0, width=10)
        scroll.pack(side="right", fill="y", pady=4, padx=(0, 2))
        lb.configure(yscrollcommand=scroll.set)
        empty = tk.Label(inner, text="Sin procesos", bg=C["inset"], fg=C["faint"], font=self._font(9))
        empty.place(relx=0.46, rely=0.5, anchor="center")

        if kind == "ram":
            self.ram_list, self.ram_empty, self.ram_count = lb, empty, count
            lb.bind("<<ListboxSelect>>", self._on_ram_select)
        else:
            self.swap_list, self.swap_empty, self.swap_count = lb, empty, count
            lb.bind("<<ListboxSelect>>", self._on_swap_select)

    def _build_actions(self, parent):
        grid = tk.Frame(parent, bg=C["card"])
        grid.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        for col in range(2):
            grid.grid_columnconfigure(col, weight=1)
        for row in range(4):
            grid.grid_rowconfigure(row, weight=1)

        buttons = [
            ("1", "Mostrar memoria", self.show_memory, C["accent"], C["accent_soft"]),
            ("2", "Crear proceso", self.create_process, C["good"], "#064e3b"),
            ("3", "Terminar proceso", self.terminate_process, C["bad"], C["bad_bg"]),
            ("4", "Compactar memoria", self.compact_memory, C["warn"], C["warn_bg"]),
            ("5", "Mostrar páginas", self.show_pages, "#818cf8", "#1e1b4b"),
            ("6", "Enviar a SWAP", self.send_to_swap, C["violet"], "#2e1065"),
            ("7", "Recuperar de SWAP", self.recover_from_swap, "#2dd4bf", "#134e4a"),
            ("8", "Salir", self.root.destroy, C["muted"], C["chip"]),
        ]
        for i, (num, text, command, color, bg) in enumerate(buttons):
            self._action_button(grid, num, text, command, color, bg).grid(
                row=i // 2, column=i % 2, sticky="nsew", padx=4, pady=4,
            )

    def _action_button(self, parent, number, text, command, color, bg):
        wrap = tk.Frame(parent, bg=color)
        btn = tk.Button(
            wrap, text=f"{number}    {text}", command=command, anchor="w",
            bg=bg, fg=C["text"], activebackground=mix(bg, color, 0.35),
            activeforeground=C["white"], relief="flat", bd=0, highlightthickness=0,
            font=self._font(9, "bold"), cursor="hand2", padx=10,
        )
        btn.pack(fill="both", expand=True, padx=(3, 0), pady=0)
        btn.bind("<Enter>", lambda _e, b=btn, c=color: b.configure(bg=mix(bg, c, 0.45)))
        btn.bind("<Leave>", lambda _e, b=btn: b.configure(bg=bg))
        return wrap

    def _text_button(self, parent, text, command):
        return tk.Button(
            parent, text=text, command=command, bg=C["bg"], fg=C["muted"],
            activebackground=C["bg"], activeforeground=C["text"], relief="flat",
            bd=0, highlightthickness=0, font=self._font(8), cursor="hand2",
        )

    def _style_tree(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Pages.Treeview", background=C["inset"], fieldbackground=C["inset"],
            foreground=C["text"], borderwidth=0, relief="flat", rowheight=30,
            font=self._font(10),
        )
        style.layout("Pages.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure(
            "Pages.Treeview.Heading", background=C["chip"], foreground=C["muted"],
            relief="flat", font=self._font(9, "bold"),
        )
        style.map("Pages.Treeview", background=[("selected", C["accent_soft"])],
                  foreground=[("selected", C["white"])])
        style.configure(
            "Dark.Vertical.TScrollbar", background="#334155", troughcolor=C["inset"],
            bordercolor=C["inset"], arrowcolor=C["muted"], gripcount=0,
            lightcolor=C["inset"], darkcolor=C["inset"],
        )

    def _on_root_configure(self, event):
        if event.widget is not self.root:
            return
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(40, self._draw_memory)

    # ---------- Dibujo ----------
    def _canvas_size(self, canvas, fallback_w):
        w = canvas.winfo_width()
        return w if w > 20 else fallback_w

    def _draw_memory(self):
        m = self.manager
        ram_slots = [m.ram.get(name) if name else None for name in m.frames]
        self._draw_strip(self.ram_canvas, ram_slots, "ram", cell_h=108)
        self._draw_strip(self.swap_canvas, m.swap_slots(), "swap", cell_h=90)
        self._set_detail("ram")
        self._set_detail("swap")

    def _draw_strip(self, canvas, slots, kind, cell_h):
        canvas.delete("all")
        width = self._canvas_size(canvas, 1100)
        n = len(slots)
        gap = 6
        cell_w = (width - gap * (n - 1)) / n
        radius = min(12, cell_w / 4, cell_h / 4)
        fragmented = self.manager.free_frames() > self.manager.largest_hole() and kind == "ram"
        y0, y1 = 2, 2 + cell_h

        for i, process in enumerate(slots):
            x0 = i * (cell_w + gap)
            x1 = x0 + cell_w
            tag = f"{kind}-{i}"
            selected = process is not None and process.name == self.selected and self.selected_where == kind
            if process:
                fill = process.color
                fg = text_on(fill)
                sub = mix(fill, fg, 0.45)
                outline = C["white"] if selected else mix(fill, C["ink"], 0.25)
                width_px = 2 if selected else 1
                page = self._page_of(slots, i)
                title = self._fit(process.name, cell_w - 12, self._font(9, "bold"))
                subtitle = f"{page + 1}/{process.pages}"
            else:
                fill = C["free"]
                fg = C["muted"]
                sub = C["faint"]
                hole_hot = fragmented or (self._pulse_holes and kind == "ram")
                outline = C["warn"] if hole_hot else C["line"]
                width_px = 2 if hole_hot else 1
                title = "libre"
                subtitle = ""

            round_rect(canvas, x0, y0, x1, y1, radius, fill=fill, outline=outline, width=width_px, tags=tag)
            if process and self._waste_of(process, self._page_of(slots, i)) > 0:
                canvas.create_oval(x1 - 14, y0 + 6, x1 - 6, y0 + 14, fill=C["ink"], outline="", tags=tag)
            cx = (x0 + x1) / 2
            canvas.create_text(cx, y0 + cell_h * 0.38, text=title, fill=fg,
                               font=self._font(9, "bold"), tags=tag)
            if subtitle:
                canvas.create_text(cx, y0 + cell_h * 0.58, text=subtitle, fill=sub,
                                   font=self._font(8), tags=tag)
            index = f"M{i}" if kind == "ram" else f"B{i}"
            canvas.create_text(cx, y1 - 14, text=index, fill=sub if process else C["faint"],
                               font=self._font(8, "bold"), tags=tag)
            canvas.tag_bind(tag, "<Enter>", lambda _e, i=i, k=kind: self._hover(k, i))
            canvas.tag_bind(tag, "<Button-1>", lambda _e, i=i, k=kind: self._click_slot(k, i))

        scale_y = y1 + 14
        canvas.create_line(0, scale_y, width, scale_y, fill=C["line"])
        for mb in (0, 16, 32, 48, 64):
            x = (mb / TOTAL_MB) * width
            anchor = "w" if mb == 0 else "e" if mb == 64 else "center"
            canvas.create_text(x, scale_y + 8, text=f"{mb}", fill=C["faint"],
                               font=self._font(7), anchor=anchor)
        canvas.configure(scrollregion=(0, 0, width, scale_y + 16))

    def _page_of(self, slots, index):
        process = slots[index]
        page = 0
        j = index - 1
        while j >= 0 and slots[j] is process:
            page += 1
            j -= 1
        return page

    def _waste_of(self, process, page):
        used = min(FRAME_MB, process.size_mb - page * FRAME_MB)
        return FRAME_MB - used

    def _fit(self, text, max_px, font):
        f = tkfont.Font(font=font)
        if f.measure(text) <= max_px:
            return text
        trimmed = text
        while trimmed and f.measure(trimmed + "…") > max_px:
            trimmed = trimmed[:-1]
        return (trimmed + "…") if trimmed else "…"

    def _hover(self, kind, index):
        slots = self._slots(kind)
        process = slots[index]
        prefix = "Marco" if kind == "ram" else "Bloque"
        if process is None:
            text = f"{prefix} {index}   ·   libre   ·   {FRAME_MB} MB disponibles"
        else:
            page = self._page_of(slots, index)
            used = min(FRAME_MB, process.size_mb - page * FRAME_MB)
            waste = FRAME_MB - used
            waste_txt = f"   ·   {waste} MB de fragmentación interna" if waste else ""
            text = (f"{prefix} {index}   ·   {process.name}   ·   página {page + 1} de {process.pages}"
                    f"   ·   {used} MB usados{waste_txt}")
        label = self.ram_detail if kind == "ram" else self.swap_detail
        label.configure(text=text, fg=C["text"])
        self.root.configure(cursor="hand2" if process else "arrow")

    def _set_detail(self, kind):
        self.root.configure(cursor="arrow")
        m = self.manager
        if kind == "ram":
            holes = m.holes()
            text = (f"Usado { (TOTAL_FRAMES - m.free_frames()) * FRAME_MB } MB"
                    f"    ·    Libre {m.free_frames() * FRAME_MB} MB"
                    f"    ·    Mayor hueco {m.largest_hole() * FRAME_MB} MB"
                    f"    ·    {len(holes)} hueco(s)")
            if m.free_frames() > m.largest_hole():
                text += "    ·    hay fragmentación externa"
            self.ram_detail.configure(text=text, fg=C["warn"] if m.free_frames() > m.largest_hole() else C["muted"])
        else:
            used = m.swap_used() * FRAME_MB
            text = (f"Ocupado {used} MB    ·    Libre {(TOTAL_FRAMES - m.swap_used()) * FRAME_MB} MB"
                    f"    ·    {len(m.swap)} proceso(s) en disco")
            self.swap_detail.configure(text=text, fg=C["muted"])

    def _slots(self, kind):
        m = self.manager
        if kind == "ram":
            return [m.ram.get(name) if name else None for name in m.frames]
        return m.swap_slots()

    def _click_slot(self, kind, index):
        process = self._slots(kind)[index]
        if process is None:
            return
        self.selected = process.name
        self.selected_where = kind
        names = self.ram_names if kind == "ram" else self.swap_names
        box = self.ram_list if kind == "ram" else self.swap_list
        other = self.swap_list if kind == "ram" else self.ram_list
        if process.name in names:
            pos = names.index(process.name)
            self._updating = True
            other.selection_clear(0, tk.END)
            box.selection_clear(0, tk.END)
            box.selection_set(pos)
            box.see(pos)
            self._updating = False
        self._draw_memory()

    def _paint_stat(self, block, text, ratio):
        block["value"].configure(text=text)
        bar = block["bar"]
        bar.delete("all")
        w = 108
        round_rect(bar, 0, 0, w, 6, 3, fill="#24344c", outline="")
        if ratio > 0:
            round_rect(bar, 0, 0, max(8, w * min(1, ratio)), 6, 3, fill=block["color"], outline="")

    def refresh(self):
        m = self.manager
        self._draw_memory()
        used_mb = (TOTAL_FRAMES - m.free_frames()) * FRAME_MB
        self._paint_stat(self.ram_stat, f"{used_mb} MB", used_mb / TOTAL_MB)
        swap_mb = m.swap_used() * FRAME_MB
        self._paint_stat(self.swap_stat, f"{swap_mb} MB", swap_mb / TOTAL_MB)
        hole = m.largest_hole() * FRAME_MB
        self._paint_stat(self.hole_stat, f"{hole} MB", hole / TOTAL_MB)

        fragmented = m.free_frames() > m.largest_hole()
        if fragmented:
            self.health.configure(text="Fragmentación externa", bg=C["warn_bg"], fg=C["warn"])
        else:
            self.health.configure(text="Sin fragmentar", bg=C["good_bg"], fg=C["good"])

        self.ram_names = [p.name for p in sorted(m.ram.values(), key=lambda x: x.start)]
        self.swap_names = list(m.swap.keys())
        if self.selected and self.selected not in m.ram and self.selected not in m.swap:
            self.selected = None
            self.selected_where = None
        self._fill_list(self.ram_list, self.ram_empty, self.ram_count, self.ram_names, m.ram, "ram")
        self._fill_list(self.swap_list, self.swap_empty, self.swap_count, self.swap_names, m.swap, "swap")

    def _fill_list(self, box, empty, count, names, table, kind):
        self._updating = True
        box.delete(0, tk.END)
        for name in names:
            p = table[name]
            if kind == "ram":
                a, b = p.start, p.start + p.pages - 1
                span = f"M{a}" if a == b else f"M{a}–M{b}"
                extra = f"{p.pages} pág.  ·  {span}"
            else:
                extra = f"{p.pages} pág.  ·  {p.size_mb} MB en disco"
            box.insert(tk.END, f"   {name}      {p.size_mb} MB      {extra}")
            box.itemconfig(tk.END, bg=mix(C["inset"], p.color, 0.22), fg=C["text"])
        count.configure(text=f"{len(names)} proceso(s)")
        if names:
            empty.place_forget()
        else:
            empty.place(relx=0.46, rely=0.5, anchor="center")
        if self.selected in names and self.selected_where == kind:
            pos = names.index(self.selected)
            box.selection_set(pos)
            box.see(pos)
        self._updating = False

    def _on_ram_select(self, _event=None):
        if self._updating:
            return
        name = self._selected_name(self.ram_list, self.ram_names)
        if not name:
            return
        self._updating = True
        self.swap_list.selection_clear(0, tk.END)
        self._updating = False
        self.selected, self.selected_where = name, "ram"
        self._draw_memory()

    def _on_swap_select(self, _event=None):
        if self._updating:
            return
        name = self._selected_name(self.swap_list, self.swap_names)
        if not name:
            return
        self._updating = True
        self.ram_list.selection_clear(0, tk.END)
        self._updating = False
        self.selected, self.selected_where = name, "swap"
        self._draw_memory()

    def log(self, message, kind="info"):
        self.log_box.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.insert(tk.END, ts + "   ", "time")
        self.log_box.insert(tk.END, message + "\n", kind)
        self.log_box.see(tk.END)
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", tk.END)
        self.log_box.configure(state="disabled")

    # ---------- Utilidades ----------
    def _selected_name(self, listbox, names):
        selection = listbox.curselection()
        if not selection or selection[0] >= len(names):
            return None
        return names[selection[0]]

    def _current_name(self, where):
        if self.selected and self.selected_where == where:
            return self.selected
        if where == "ram":
            return self._selected_name(self.ram_list, self.ram_names)
        return self._selected_name(self.swap_list, self.swap_names)

    def _report(self, result):
        ok, message = result
        self.log(message, "ok" if ok else "err")
        if self.selected and not self.manager.exists(self.selected):
            self.selected = None
            self.selected_where = None
        self.refresh()
        if not ok:
            self.alert("No se pudo completar", message, "warn")
        return ok

    def alert(self, title, message, kind="info"):
        colors = {
            "info": (C["accent"], C["accent_soft"]),
            "warn": (C["warn"], C["warn_bg"]),
            "err": (C["bad"], C["bad_bg"]),
            "ok": (C["good"], C["good_bg"]),
        }
        accent, bg = colors.get(kind, colors["info"])
        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg=C["card"])
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        tk.Frame(win, bg=accent, height=4).pack(fill="x")
        body = tk.Frame(win, bg=C["card"], padx=22, pady=18)
        body.pack(fill="both")
        tk.Label(body, text=title, bg=C["card"], fg=C["text"],
                 font=self._font(13, "bold")).pack(anchor="w")
        tk.Label(body, text=message, bg=C["card"], fg=C["muted"], font=self._font(10),
                 wraplength=380, justify="left").pack(anchor="w", pady=(8, 16))
        tk.Button(
            body, text="Entendido", command=win.destroy, bg=bg, fg=C["text"],
            activebackground=accent, activeforeground=C["ink"], relief="flat", bd=0,
            highlightthickness=0, font=self._font(10, "bold"), padx=16, pady=7, cursor="hand2",
        ).pack(anchor="e")
        win.update_idletasks()
        self._place_over_parent(win)
        win.bind("<Escape>", lambda _e: win.destroy())
        win.bind("<Return>", lambda _e: win.destroy())
        win.wait_window()

    def _place_over_parent(self, win):
        win.update_idletasks()
        w, h = win.winfo_width(), win.winfo_height()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - h) // 2
        win.geometry(f"+{max(0, x)}+{max(0, y)}")

    # ---------- Opciones del menú ----------
    def show_memory(self):
        m = self.manager
        mapa = "  ".join(f"[{owner if owner else 'libre'}]" for owner in m.frames)
        self.log("Mapa de RAM: " + mapa, "info")
        holes = ", ".join(f"marcos {s}-{s + n - 1} ({n * FRAME_MB} MB)" for s, n in m.holes())
        self.log("Huecos libres: " + (holes if holes else "ninguno"), "info")
        self._pulse_holes = True
        self._draw_memory()
        self.root.after(1400, self._end_pulse)
        self.refresh()

    def _end_pulse(self):
        self._pulse_holes = False
        self._draw_memory()

    def create_process(self):
        result = {}

        win = tk.Toplevel(self.root)
        win.title("Crear proceso")
        win.configure(bg=C["card"])
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        tk.Frame(win, bg=C["good"], height=4).pack(fill="x")
        body = tk.Frame(win, bg=C["card"], padx=22, pady=16)
        body.pack(fill="both")

        tk.Label(body, text="Nuevo proceso", bg=C["card"], fg=C["text"],
                 font=self._font(14, "bold")).pack(anchor="w")
        tk.Label(body, text="Se colocará por primer ajuste en el primer hueco que alcance.",
                 bg=C["card"], fg=C["faint"], font=self._font(9)).pack(anchor="w", pady=(2, 12))

        tk.Label(body, text="NOMBRE", bg=C["card"], fg=C["faint"],
                 font=self._font(8, "bold")).pack(anchor="w")
        name_var = tk.StringVar(value=f"P{self.counter}")
        entry = tk.Entry(
            body, textvariable=name_var, bg=C["inset"], fg=C["text"],
            insertbackground=C["text"], relief="flat", highlightthickness=1,
            highlightbackground=C["line"], highlightcolor=C["accent"],
            font=self._font(12), width=28,
        )
        entry.pack(fill="x", ipady=7, pady=(4, 12))
        entry.selection_range(0, tk.END)
        entry.focus_set()

        size_var = tk.IntVar(value=8)
        head = tk.Frame(body, bg=C["card"])
        head.pack(fill="x")
        tk.Label(head, text="TAMAÑO", bg=C["card"], fg=C["faint"],
                 font=self._font(8, "bold")).pack(side="left")
        size_lbl = tk.Label(head, text="8 MB", bg=C["card"], fg=C["text"], font=self._font(12, "bold"))
        size_lbl.pack(side="right")

        scale = tk.Scale(
            body, from_=1, to=TOTAL_MB, orient="horizontal", variable=size_var,
            showvalue=False, bg=C["card"], fg=C["text"], troughcolor=C["inset"],
            activebackground=C["accent"], highlightthickness=0, bd=0,
            sliderrelief="flat", length=420,
        )
        scale.pack(fill="x", pady=(0, 4))

        preview = tk.Canvas(body, height=36, bg=C["card"], highlightthickness=0)
        preview.pack(fill="x", pady=(4, 6))
        hint = tk.Label(body, text="", bg=C["card"], fg=C["muted"], font=self._font(9),
                        wraplength=440, justify="left")
        hint.pack(anchor="w", pady=(0, 8))
        error = tk.Label(body, text="", bg=C["card"], fg=C["bad"], font=self._font(9),
                         wraplength=440, justify="left")
        error.pack(anchor="w")

        next_color = PALETTE[self.manager._color_index % len(PALETTE)]

        def redraw_preview(*_):
            size = int(size_var.get())
            pages = math.ceil(size / FRAME_MB)
            waste = pages * FRAME_MB - size
            size_lbl.configure(text=f"{size} MB")
            preview.delete("all")
            pw = preview.winfo_width()
            if pw < 20:
                pw = 440
            gap, n = 4, TOTAL_FRAMES
            cw = (pw - gap * (n - 1)) / n
            start = self.manager._first_fit(pages)
            owners = list(self.manager.frames)
            for i in range(n):
                x0 = i * (cw + gap)
                if start is not None and start <= i < start + pages:
                    color = next_color
                elif owners[i]:
                    color = self.manager.ram[owners[i]].color
                else:
                    color = C["free"]
                round_rect(preview, x0, 8, x0 + cw, 30, 4, fill=color, outline="")
            paginas = "1 página" if pages == 1 else f"{pages} páginas"
            if pages > TOTAL_FRAMES:
                msg, col = "Este proceso no cabe en la RAM.", C["bad"]
            elif start is not None:
                msg = (f"{paginas} de {FRAME_MB} MB   ·   sobran {waste} MB   ·   "
                       f"marcos {start}–{start + pages - 1}")
                col = C["good"]
            elif self.manager.free_frames() >= pages:
                msg = (f"Hay {self.manager.free_frames() * FRAME_MB} MB libres, pero dispersos. "
                       "Hace falta compactar.")
                col = C["warn"]
            else:
                msg, col = "No hay memoria suficiente. Termine un proceso o envíelo a SWAP.", C["bad"]
            hint.configure(text=msg, fg=col)

        size_var.trace_add("write", redraw_preview)
        preview.bind("<Configure>", redraw_preview)
        win.after(30, redraw_preview)

        def submit(_event=None):
            error.configure(text="")
            ok, message = self.manager.create(name_var.get().strip(), int(size_var.get()))
            self.log(message, "ok" if ok else "err")
            if ok:
                self.counter += 1
                result["ok"] = True
                self.refresh()
                win.destroy()
            else:
                error.configure(text=message)

        def cancel(_event=None):
            win.destroy()

        actions = tk.Frame(body, bg=C["card"])
        actions.pack(fill="x", pady=(12, 0))
        tk.Button(
            actions, text="Cancelar", command=cancel, bg=C["chip"], fg=C["muted"],
            activebackground=C["line"], activeforeground=C["text"], relief="flat", bd=0,
            highlightthickness=0, font=self._font(10), padx=14, pady=7, cursor="hand2",
        ).pack(side="right", padx=(8, 0))
        tk.Button(
            actions, text="Crear proceso", command=submit, bg=C["good"], fg=C["ink"],
            activebackground="#6ee7b7", activeforeground=C["ink"], relief="flat", bd=0,
            highlightthickness=0, font=self._font(10, "bold"), padx=16, pady=7, cursor="hand2",
        ).pack(side="right")

        win.bind("<Escape>", cancel)
        win.bind("<Return>", submit)
        win.update_idletasks()
        self._place_over_parent(win)
        win.wait_window()
        return result.get("ok", False)

    def terminate_process(self):
        name = self._current_name("ram") or self._current_name("swap") or self.selected
        if name is None:
            self.alert("Terminar proceso", "Seleccione un proceso de la lista o haga clic en su marco.", "info")
            return
        self._report(self.manager.terminate(name))

    def compact_memory(self):
        self._report(self.manager.compact())

    def show_pages(self):
        rows = self.manager.page_table()
        if not rows:
            self.alert("Tabla de páginas", "No hay procesos en RAM ni en SWAP.", "info")
            return
        win = tk.Toplevel(self.root)
        win.title("Tabla de páginas")
        win.configure(bg=C["card"])
        win.transient(self.root)
        tk.Frame(win, bg="#818cf8", height=4).pack(fill="x")
        head = tk.Frame(win, bg=C["card"], padx=16, pady=12)
        head.pack(fill="x")
        tk.Label(head, text="Tabla de páginas", bg=C["card"], fg=C["text"],
                 font=self._font(14, "bold")).pack(anchor="w")
        waste = sum(row[5] for row in rows)
        tk.Label(
            head,
            text=f"{len(rows)} páginas   ·   fragmentación interna total {waste} MB",
            bg=C["card"], fg=C["muted"], font=self._font(9),
        ).pack(anchor="w")

        holder = tk.Frame(win, bg=C["card"], padx=12)
        holder.pack(fill="both", expand=True)
        columns = ("Proceso", "Página", "Ubicación", "Marco / bloque", "MB usados", "MB desperdiciados")
        table = ttk.Treeview(holder, columns=columns, show="headings",
                             height=min(len(rows), 14), style="Pages.Treeview")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=table.yview,
                               style="Dark.Vertical.TScrollbar")
        table.configure(yscrollcommand=scroll.set)
        widths = (140, 80, 100, 130, 110, 150)
        for column, width in zip(columns, widths):
            table.heading(column, text=column)
            table.column(column, width=width, anchor="center")
        table.tag_configure("swap", foreground="#ddd6fe")
        table.tag_configure("waste", foreground=C["warn"])
        table.tag_configure("ram", foreground=C["text"])
        tinted = set()
        for row in rows:
            name = row[0]
            if name not in tinted:
                process = self.manager.ram.get(name) or self.manager.swap.get(name)
                if process:
                    table.tag_configure(name, background=mix(C["inset"], process.color, 0.20))
                tinted.add(name)
            tags = [name, "waste" if row[5] else ("swap" if row[2] == "SWAP" else "ram")]
            table.insert("", tk.END, values=row, tags=tuple(tags))
        table.pack(side="left", fill="both", expand=True, pady=(0, 8))
        scroll.pack(side="left", fill="y", pady=(0, 8), padx=(4, 0))
        tk.Label(
            win,
            text="Los MB desperdiciados son la fragmentación interna de esa página.\n"
                 "Las filas en violeta están en SWAP; su bloque es la posición en el disco.",
            bg=C["card"], fg=C["faint"], font=self._font(8), justify="center",
        ).pack(pady=(0, 12))
        self.log("Tabla de páginas mostrada (RAM y SWAP).", "info")
        win.update_idletasks()
        self._place_over_parent(win)

    def send_to_swap(self):
        name = self._current_name("ram")
        if name is None:
            self.alert("Enviar a SWAP", "Seleccione un proceso de la lista de RAM.", "info")
            return
        self._report(self.manager.send_to_swap(name))

    def recover_from_swap(self):
        name = self._current_name("swap")
        if name is None:
            self.alert("Recuperar de SWAP", "Seleccione un proceso de la lista de SWAP.", "info")
            return
        self._report(self.manager.recover_from_swap(name))


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
