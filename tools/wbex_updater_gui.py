# Copyright (c) 2026 Intelligent Efficiency Team
# SPDX-License-Identifier: MIT
#!/usr/bin/env python3
"""Dependency-free desktop front end for the offline ACT WBEX updater."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import json
import math
from pathlib import Path
import queue
import re
import struct
import sys
import threading
import time
import zlib
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from .wbex_updater_version import VERSION, APP_ID
    from .wbex_updater_drop import WindowsFileDrop
    from .wbex_updater_icon import WindowsWindowIcons
    from .wbex_updater_runtime import BuildError, discover_ansys_roots, select_default_ansys_root
    from .update_wbex import update, AnsysProcessesRunning, close_ansys_processes
except ImportError:
    from wbex_updater_version import VERSION, APP_ID
    from wbex_updater_drop import WindowsFileDrop
    from wbex_updater_icon import WindowsWindowIcons
    from wbex_updater_runtime import BuildError, discover_ansys_roots, select_default_ansys_root
    from update_wbex import update, AnsysProcessesRunning, close_ansys_processes


ROOT = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1])

LIGHT_COLORS = {
    "background": "#f5f5f7", "panel": "#ffffff", "field": "#ffffff",
    "border": "#dedee3", "text": "#1d1d1f", "muted": "#636369",
    "accent": "#0071e3", "success": "#237a42", "error": "#b4232d",
    "drop": "#eef6ff", "drop_border": "#78ace0", "drop_text": "#0071e3",
    "button": "#ffffff", "hover": "#f0f0f3", "pressed": "#e7e7eb",
    "disabled": "#ededf0", "disabled_text": "#8b8b91", "selection": "#cce4ff",
    "primary_hover": "#0077ed", "primary_pressed": "#0062c4", "focus": "#003b77",
    "scrollbar": "#ccccd2", "scrollbar_hover": "#aaaab3",
    "toggle": "#e8e8ed", "toggle_selected": "#ffffff",
}
DARK_COLORS = {
    "background": "#161618", "panel": "#232326", "field": "#19191c",
    "border": "#3d3d43", "text": "#f5f5f7", "muted": "#b5b5be",
    "accent": "#0a84ff", "success": "#65d38a", "error": "#ff7b83",
    "drop": "#172a40", "drop_border": "#375d85", "drop_text": "#7dbbff",
    "button": "#303035", "hover": "#3b3b42", "pressed": "#45454d",
    "disabled": "#29292e", "disabled_text": "#898993", "selection": "#184c7e",
    "primary_hover": "#2693ff", "primary_pressed": "#0071e3", "focus": "#8ac6ff",
    "scrollbar": "#55555f", "scrollbar_hover": "#737380",
    "toggle": "#2a2a2f", "toggle_selected": "#50505b",
}
PALETTES = {"dark": DARK_COLORS, "light": LIGHT_COLORS}
COLORS = DARK_COLORS
ROUNDING_SAMPLES = 8


def create_window():
    """Set source-launch DPI awareness before Tk or a common dialog is created.

    Frozen releases declare the same system awareness in their EXE manifest.
    Tk 8.6 uses one interpreter-wide font scale, so avoid claiming per-monitor
    reflow support that the application does not implement.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            pass
    window = tk.Tk()
    initialize_scale(window)
    apply_window_icon(window)
    return window


def apply_window_icon(window):
    if hasattr(window, "_ld_icon_loaded"):
        return
    window._ld_icon_loaded = False
    if sys.platform != "win32":
        return
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        path = Path(sys._MEIPASS) / "updater_assets" / "updater.ico"
    else:
        path = Path(__file__).parent / "assets" / "wbex-updater" / "updater.ico"
    try:
        window.iconbitmap(default=str(path))
        window._ld_window_icons = WindowsWindowIcons(window, path)
        window._ld_icon_loaded = True
    except (OSError, tk.TclError) as error:
        # A cosmetic icon problem must not prevent a plugin update.
        window._ld_icon_error = str(error)


def initialize_scale(window):
    if hasattr(window, "_ld_ui_scale"):
        return
    dpi = window.winfo_fpixels("1i")
    if sys.platform == "win32":
        try:
            import ctypes
            dpi = ctypes.windll.user32.GetDpiForSystem() or dpi
        except (AttributeError, OSError):
            pass
    window._ld_ui_scale = max(0.75, dpi / 96)
    window._ld_dpi = dpi
    window.tk.call("tk", "scaling", dpi / 72)


def px(window, value):
    return round(value * getattr(window._root(), "_ld_ui_scale", 1.0))


def scale_widget_tree(window):
    """Scale pixel geometry once; fonts and text dimensions remain in points/chars."""
    factor = getattr(window._root(), "_ld_ui_scale", 1.0)

    def scaled(value):
        parts = value if isinstance(value, (tuple, list)) else window.tk.splitlist(str(value))
        return tuple(round(float(str(item)) * factor) for item in parts)

    def visit(widget):
        if not getattr(widget, "_ld_pixels_scaled", False):
            keys = widget.keys()
            for option in ("padding", "padx", "pady", "wraplength", "length", "spacing1", "spacing3"):
                if option in keys:
                    value = widget.cget(option)
                    if str(value):
                        converted = scaled(value)
                        widget.configure(**{option: converted if option == "padding" else converted[0]})
            manager = widget.winfo_manager()
            if manager in ("grid", "pack"):
                info = widget.grid_info() if manager == "grid" else widget.pack_info()
                options = {key: scaled(info[key]) for key in ("padx", "pady", "ipadx", "ipady") if key in info}
                if options:
                    (widget.grid_configure if manager == "grid" else widget.pack_configure)(**options)
            widget._ld_pixels_scaled = True
        for child in widget.winfo_children():
            if not isinstance(child, tk.Toplevel):
                visit(child)

    visit(window)


def system_motion_enabled():
    """Honor Windows' animation preference without requiring another library."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        enabled = ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return bool(enabled.value)
    except (AttributeError, OSError):
        pass
    return True


@lru_cache(maxsize=8)
def rounded_coverage(radius):
    """Subpixel coverage for the outer curve and its one-pixel inner border."""
    size = radius * 2 + 4
    samples = ROUNDING_SAMPLES
    offsets = tuple((i + 0.5) / samples for i in range(samples))
    coverage = []
    for y in range(size):
        for x in range(size):
            outer = inner = 0
            for dy in offsets:
                py = y + dy
                cy = max(radius, min(py, size - radius))
                for dx in offsets:
                    px = x + dx
                    cx = max(radius, min(px, size - radius))
                    distance_squared = (px - cx) ** 2 + (py - cy) ** 2
                    outer += distance_squared <= radius ** 2
                    inner += distance_squared <= (radius - 1) ** 2
            coverage.append((outer, inner))
    return tuple(coverage)


@lru_cache(maxsize=128)
def rounded_pixels(fill, outline, radius, outside):
    """Blend edge coverage with the actual parent color before Tk draws it."""
    def rgb(color):
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))

    fill_rgb, border_rgb, background_rgb = map(rgb, (fill, outline, outside))
    size = radius * 2 + 4
    coverage = rounded_coverage(radius)
    sample_count = ROUNDING_SAMPLES ** 2
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            outer, inner = coverage[y * size + x]
            color = tuple(round((f * inner + b * (outer - inner) + bg * (sample_count - outer)) / sample_count)
                          for f, b, bg in zip(fill_rgb, border_rgb, background_rgb))
            row.append("#{:02x}{:02x}{:02x}".format(*color))
        rows.append("{" + " ".join(row) + "}")
    return " ".join(rows)


def rounded_surface(window, fill, outline, radius=10, outside=None, center_size=2):
    """Antialiased nine-slice surface; no external images or imaging runtime."""
    size = radius * 2 + 4
    corners = tk.PhotoImage(master=window, width=size, height=size)
    corners.put(rounded_pixels(fill, outline, radius, outside or COLORS["background"]))
    if center_size <= 2:
        return corners
    # ttk tiles the center instead of stretching it. A 2px tile requires
    # hundreds of thousands of GDI calls to repaint a large panel on Windows.
    # Fill a larger tile in Tcl and copy only the four antialiased corners.
    edge = radius + 1
    expanded = edge * 2 + center_size
    image = tk.PhotoImage(master=window, width=expanded, height=expanded)
    image.put(fill, to=(0, 0, expanded, expanded))
    for box in ((edge, 0, expanded - edge, 1), (edge, expanded - 1, expanded - edge, expanded),
                (0, edge, 1, expanded - edge), (expanded - 1, edge, expanded, expanded - edge)):
        image.put(outline, to=box)
    for right, bottom in ((False, False), (True, False), (False, True), (True, True)):
        sx, sy = (size - edge if right else 0), (size - edge if bottom else 0)
        dx, dy = (expanded - edge if right else 0), (expanded - edge if bottom else 0)
        image.tk.call(str(image), "copy", str(corners), "-from", sx, sy, sx + edge, sy + edge,
                      "-to", dx, dy)
    return image


def spring_step(position, velocity, target, seconds, response=0.3):
    """Exact critically damped step; preserve velocity when the target reverses."""
    omega = 2 * math.pi / response
    offset = position - target
    coefficient = velocity + omega * offset
    decay = math.exp(-omega * seconds)
    return (target + (offset + coefficient * seconds) * decay,
            (velocity - omega * coefficient * seconds) * decay)


def rounded_bitmap(window, width, height, fill, border, radius, outside, transparent_corners=False):
    """Build a fixed-size antialiased surface once, never during animation."""
    corners = rounded_surface(window, fill, border, radius, outside)
    edge, size = radius + 1, radius * 2 + 4
    image = tk.PhotoImage(master=window, width=width, height=height)
    image.put(fill, to=(0, 0, width, height))
    for box in ((edge, 0, width - edge, 1), (edge, height - 1, width - edge, height),
                (0, edge, 1, height - edge), (width - 1, edge, width, height - edge)):
        image.put(border, to=box)
    for right, bottom in ((False, False), (True, False), (False, True), (True, True)):
        sx, sy = (size - edge if right else 0), (size - edge if bottom else 0)
        dx, dy = (width - edge if right else 0), (height - edge if bottom else 0)
        image.tk.call(str(image), "copy", str(corners), "-from", sx, sy, sx + edge, sy + edge,
                      "-to", dx, dy)
        if transparent_corners:
            # A moving thumb overlays the track. Its empty corner pixels must
            # reveal the track/focus curve, rather than paint a square of fill
            # over it. Partial coverage stays blended with the track interior.
            coverage = rounded_coverage(radius)
            for y in range(edge):
                for x in range(edge):
                    if coverage[(sy + y) * size + sx + x][0] == 0:
                        image.transparency_set(dx + x, dy + y, True)
    return image


def blend_color(dark, light, amount):
    return "#{:02x}{:02x}{:02x}".format(*(round(int(dark[i:i + 2], 16) * (1 - amount) +
                                               int(light[i:i + 2], 16) * amount)
                                          for i in (1, 3, 5)))


def _png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)


@lru_cache(maxsize=32)
def indexed_surface_geometry(width, height, radius, transparent=False):
    """Cache shape pixels/compression; a fade frame only replaces a tiny palette."""
    edge, size = radius + 1, radius * 2 + 4
    coverage, weights, indices = rounded_coverage(radius), [], {}
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # PNG filter: none.
        for x in range(width):
            if (x < edge or x >= width - edge) and (y < edge or y >= height - edge):
                sx = x if x < edge else size - (width - x)
                sy = y if y < edge else size - (height - y)
                weight = coverage[sy * size + sx]
            else:
                weight = (64, 0) if x in (0, width - 1) or y in (0, height - 1) else (64, 64)
            if weight not in indices:
                indices[weight] = len(weights)
                weights.append(weight)
            rows.append(indices[weight])
    header = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0))
    alpha = (_png_chunk(b"tRNS", bytes(0 if outer == 0 else 255 for outer, _ in weights))
             if transparent else b"")
    tail = alpha + _png_chunk(b"IDAT", zlib.compress(bytes(rows))) + _png_chunk(b"IEND", b"")
    return header, tuple(weights), tail


def paint_surface(image, radius, fill, outline, outside, transparent=False):
    """Recolor an existing Tk image in place; no new image or geometry per frame."""
    header, weights, tail = indexed_surface_geometry(image.width(), image.height(), radius, transparent)
    colors = [tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) for color in (fill, outline, outside)]
    palette = bytes(round((f * inner + b * (outer - inner) + bg * (64 - outer)) / 64)
                    for outer, inner in weights for f, b, bg in zip(*colors))
    image.configure(data=header + _png_chunk(b"PLTE", palette) + tail, format="png")


class ThemeSwitch(tk.Canvas):
    """Compact segmented control: fixed labels and a single sliding selection."""

    def __init__(self, parent, variable, command, motion_enabled):
        p = lambda value: px(parent, value)
        self.width, self.height, self.inset = p(132), p(34), p(3)
        self.segment_width = (self.width - 2 * self.inset) / 2
        super().__init__(parent, width=self.width, height=self.height, highlightthickness=0,
                         borderwidth=0, takefocus=True, cursor="hand2")
        self.variable, self.command = variable, command
        self.motion_enabled = motion_enabled
        self.position = self.target = float(variable.get() == "light")
        self.velocity = 0.0
        self.timer_id = None
        self.last_time = time.perf_counter()
        self.pressed_mode = None
        self.focused = False
        self.assets = {}
        self.track = self.create_image(0, 0, anchor="nw")
        self.thumb = self.create_image(self.inset, self.inset, anchor="nw")
        self.labels = {mode: self.create_text(self.inset + self.segment_width * (index + 0.5),
                                             self.height / 2, text=label, font=("Segoe UI", 9))
                       for index, (mode, label) in enumerate((("dark", "Dark"), ("light", "Light")))}
        self.set_palette("light" if variable.get() == "dark" else "dark")
        self.set_palette(variable.get())
        self.assets["_fade"] = tuple(image.copy() for image in self.assets["dark"])
        for image, radius, transparent in zip(self.assets["_fade"], (p(11), p(11), p(8)), (False, False, True)):
            indexed_surface_geometry(image.width(), image.height(), radius, transparent)
        self.trace_id = variable.trace_add("write", self._value_changed)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<FocusIn>", lambda event: self._focus(True))
        self.bind("<FocusOut>", lambda event: self._focus(False))
        self.bind("<Left>", lambda event: self._key("dark"))
        self.bind("<Right>", lambda event: self._key("light"))
        self.bind("<Home>", lambda event: self._key("dark"))
        self.bind("<End>", lambda event: self._key("light"))
        self.bind("<space>", lambda event: self._key())
        self.bind("<Return>", lambda event: self._key())
        self.bind("<Destroy>", self._destroy)

    def set_palette(self, mode):
        self.palette = PALETTES[mode]
        c, p = self.palette, lambda value: px(self, value)
        if mode not in self.assets:
            self.assets[mode] = (
                rounded_bitmap(self, self.width, self.height, c["toggle"], c["border"], p(11), c["background"]),
                rounded_bitmap(self, self.width, self.height, c["toggle"], c["accent"], p(11), c["background"]),
                rounded_bitmap(self, round(self.segment_width), self.height - 2 * self.inset,
                               c["toggle_selected"], c["toggle_selected"], p(8), c["toggle"],
                               transparent_corners=True),
            )
        self.mode = mode
        self.configure(background=c["background"])
        self.itemconfigure(self.thumb, image=self.assets[mode][2])
        self._draw_state()
        self._draw_position()

    def _draw_state(self):
        self.itemconfigure(self.track, image=self.assets[self.mode][int(self.focused)])
        selected = self.pressed_mode or self.variable.get()
        for mode, label in self.labels.items():
            self.itemconfigure(label, fill=self.palette["text" if mode == selected else "muted"])

    def set_blended_palette(self, colors):
        self.palette, self.mode = colors, "_fade"
        normal, focused, thumb = self.assets["_fade"]
        paint_surface(normal, px(self, 11), colors["toggle"], colors["border"], colors["background"])
        paint_surface(focused, px(self, 11), colors["toggle"], colors["accent"], colors["background"])
        paint_surface(thumb, px(self, 8), colors["toggle_selected"], colors["toggle_selected"], colors["toggle"], True)
        self.configure(background=colors["background"])
        self.itemconfigure(self.thumb, image=thumb)
        self._draw_state()

    def _draw_position(self):
        self.coords(self.thumb, self.inset + self.position * self.segment_width, self.inset)

    def _focus(self, focused):
        self.focused = focused
        self._draw_state()

    def _press(self, event):
        self.focus_set()
        self.pressed_mode = "dark" if event.x < self.width / 2 else "light"
        self._retarget(float(self.pressed_mode == "light"))
        self._draw_state()
        return "break"

    def _release(self, event):
        if self.pressed_mode is None:
            return "break"
        mode, self.pressed_mode = self.pressed_mode, None
        if 0 <= event.x <= self.width and 0 <= event.y <= self.height:
            self.select(mode)
        else:
            self._retarget(float(self.variable.get() == "light"))
        self._draw_state()
        return "break"

    def _key(self, mode=None):
        self.select(mode or ("light" if self.variable.get() == "dark" else "dark"), animate=False)
        return "break"

    def select(self, mode, animate=True):
        if mode == self.variable.get():
            self._retarget(float(mode == "light"), animate)
            return
        self.variable.set(mode)
        if not animate:
            self._retarget(float(mode == "light"), False)
        self.command(animate=animate)

    def _value_changed(self, *unused):
        self._retarget(float(self.variable.get() == "light"))
        self._draw_state()

    def _retarget(self, target, animate=True):
        self.target = target
        self.last_time = time.perf_counter()
        if not self.motion_enabled or not animate:
            if self.timer_id is not None:
                self.after_cancel(self.timer_id)
                self.timer_id = None
            self.position, self.velocity = target, 0.0
            self._draw_position()
        elif self.timer_id is None and (abs(self.position - target) > 0.001 or abs(self.velocity) > 0.01):
            self.timer_id = self.after(16, self._tick)

    def _tick(self):
        self.timer_id = None
        now = time.perf_counter()
        self.position, self.velocity = spring_step(self.position, self.velocity, self.target,
                                                   min(now - self.last_time, 0.05))
        self.last_time = now
        self.position = max(0.0, min(1.0, self.position))
        if abs(self.position - self.target) < 0.003 and abs(self.velocity) < 0.06:
            self.position, self.velocity = self.target, 0.0
        else:
            self.timer_id = self.after(16, self._tick)
        self._draw_position()

    def _destroy(self, event):
        if event.widget is self:
            if self.timer_id is not None:
                self.after_cancel(self.timer_id)
                self.timer_id = None
            self.variable.trace_remove("write", self.trace_id)


def configure_theme(window, mode="dark", palette=None, logical_mode=None):
    """Cache both themes so switching only changes styles, never UI state."""
    c = palette if palette is not None else PALETTES[mode]
    p = lambda value: px(window, value)
    style = ttk.Style(window)
    name = "WBEX." + mode
    window._ld_theme_mode = logical_mode or mode
    window._ld_palette = c
    if name in style.theme_names():
        style.theme_use(name)
        apply_theme_widgets(window, c)
        return style
    style.theme_create(name, parent="clam")
    style.theme_use(name)
    # Keep PhotoImages alive for the lifetime of this Tcl interpreter.
    if not hasattr(window, "_ld_theme_images"):
        window._ld_theme_images = []
        window._ld_surface_specs = {}
        window.bind_all("<Map>", refresh_titlebar_theme, add="+")

    def surface(fill, outline, radius=10, outside=None):
        image = rounded_surface(window, fill, outline, p(radius), outside or c["background"], center_size=128)
        window._ld_theme_images.append(image)
        window._ld_surface_specs.setdefault(mode, []).append((image, fill, outline, p(radius), outside or c["background"]))
        return image

    style.element_create("LD.Card.surface", "image", surface(c["panel"], c["border"], 12),
                         border=p(12) + 1, width=p(12) * 2 + 4, height=p(12) * 2 + 4,
                         padding=0, sticky="nswe")
    style.layout("Card.LD.TFrame", [("LD.Card.surface", {"sticky": "nswe"})])
    style.element_create("LD.Drop.surface", "image", surface(c["drop"], c["drop_border"], 12),
                         border=p(12) + 1, width=p(12) * 2 + 4, height=p(12) * 2 + 4,
                         padding=0, sticky="nswe")
    style.layout("Drop.LD.TFrame", [("LD.Drop.surface", {"sticky": "nswe"})])
    style.configure("Drop.LD.TFrame", background=c["drop"])
    style.configure("LD.TFrame", background=c["background"])
    style.configure("Card.LD.TFrame", background=c["panel"])
    style.configure("Inner.LD.TFrame", background=c["panel"])
    style.configure("LD.TLabel", background=c["background"], foreground=c["text"],
                    font=("Microsoft YaHei UI", 10))
    style.configure("Muted.LD.TLabel", foreground=c["muted"], font=("Microsoft YaHei UI", 9))
    style.configure("Brand.LD.TLabel", foreground=c["muted"], font=("Segoe UI", 10))
    style.configure("Title.LD.TLabel", font=("Microsoft YaHei UI", 22, "bold"))
    style.configure("Drop.LD.TLabel", background=c["drop"], foreground=c["drop_text"],
                    font=("Microsoft YaHei UI", 14, "bold"))
    style.configure("Icon.Drop.LD.TLabel", font=("Segoe UI", 30))
    style.configure("Card.LD.TLabel", background=c["panel"])
    style.configure("Caption.Card.LD.TLabel", foreground=c["muted"], font=("Microsoft YaHei UI", 9))
    style.configure("Heading.Card.LD.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
    style.configure("Number.Card.LD.TLabel", foreground=c["text"], font=("Microsoft YaHei UI", 10))
    for state, color in (("Ready", c["text"]), ("Busy", c["accent"]),
                         ("Success", c["success"]), ("Error", c["error"])):
        style.configure(state + ".Card.LD.TLabel", foreground=color,
                        font=("Microsoft YaHei UI", 13, "bold"))

    def button(name, fill, hover, pressed, foreground, border, disabled, outside=None):
        element = name + ".surface"
        focus_border = c["focus"] if fill == c["accent"] else c["accent"]
        style.element_create(element, "image", surface(fill, border, outside=outside),
                             ("disabled", surface(disabled, disabled, outside=outside)),
                             ("pressed", surface(pressed, border, outside=outside)),
                             ("active", surface(hover, border, outside=outside)),
                             ("focus", surface(fill, focus_border, outside=outside)), border=p(10) + 1,
                             width=p(10) * 2 + 4, height=p(10) * 2 + 4, padding=0, sticky="nswe")
        style.layout(name, [(element, {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [
                ("Button.label", {"sticky": "nswe"})]})]})])
        style.configure(name, foreground=foreground, padding=(p(18), p(8)),
                        font=("Microsoft YaHei UI", 10), anchor="center")
        style.map(name, foreground=[("disabled", c["disabled_text"])])

    button("LD.TButton", c["button"], c["hover"], c["pressed"], c["text"], c["border"], c["disabled"])
    button("Field.LD.TButton", c["button"], c["hover"], c["pressed"], c["text"], c["border"], c["disabled"], outside=c["panel"])
    button("Primary.LD.TButton", c["accent"], c["primary_hover"], c["primary_pressed"], "#ffffff", c["accent"], c["disabled"])
    button("Quiet.LD.TButton", c["panel"], c["hover"], c["pressed"], c["drop_text"], c["panel"], c["disabled"], outside=c["panel"])
    style.configure("Quiet.LD.TButton", padding=(p(10), p(4)))
    for widget in ("TEntry", "TCombobox"):
        name = "LD." + widget
        style.configure(name, fieldbackground=c["field"], foreground=c["text"],
                        insertcolor=c["text"], bordercolor=c["border"],
                        lightcolor=c["border"], darkcolor=c["border"],
                        arrowcolor=c["muted"], background=c["field"], padding=(p(10), p(9)))
        style.map(name, fieldbackground=[("disabled", c["disabled"])],
                  foreground=[("disabled", c["disabled_text"])],
                  bordercolor=[("focus", c["accent"])],
                  selectbackground=[("!disabled", c["selection"])],
                  selectforeground=[("!disabled", c["text"])])
    style.configure("LD.Horizontal.TProgressbar", background=c["accent"],
                    troughcolor=c["disabled"], bordercolor=c["disabled"],
                    lightcolor=c["accent"], darkcolor=c["accent"], thickness=p(4))
    style.configure("LD.Vertical.TScrollbar", background=c["scrollbar"], troughcolor=c["field"],
                    bordercolor=c["field"], arrowcolor=c["muted"],
                    lightcolor=c["scrollbar"], darkcolor=c["scrollbar"], arrowsize=p(10))
    style.map("LD.Vertical.TScrollbar", background=[("active", c["scrollbar_hover"])])
    window._ld_theme_style = style
    apply_theme_widgets(window, c)
    return style


def refresh_titlebar_theme(event):
    if isinstance(event.widget, (tk.Tk, tk.Toplevel)):
        apply_titlebar_theme(event.widget)


@lru_cache(maxsize=1)
def titlebar_api():
    """Resolve native entry points once, rather than on every fade frame."""
    try:
        import ctypes
        from ctypes import wintypes
        user = ctypes.WinDLL("user32")
        user.GetParent.argtypes = [wintypes.HWND]
        user.GetParent.restype = wintypes.HWND
        dwm = ctypes.WinDLL("dwmapi")
        dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long
        return user, dwm
    except (AttributeError, OSError):
        return None


def colorref(color):
    """Windows COLORREF stores RGB as 0x00BBGGRR."""
    return sum(int(color[i:i + 2], 16) << (8 * index) for index, i in enumerate((1, 3, 5)))


def apply_titlebar_theme(window, colors=None):
    if sys.platform != "win32":
        return
    api = titlebar_api()
    if api is None:
        return
    import ctypes
    from ctypes import wintypes
    user, dwm = api
    c = colors if colors is not None else getattr(window._root(), "_ld_palette", DARK_COLORS)
    hwnd = user.GetParent(window.winfo_id())
    if not hwnd:
        return
    previous = getattr(window, "_ld_titlebar_state", None)
    # Keep caption buttons legible at the current brightness, not the final
    # requested mode. Caption/text colors share the exact client-area palette.
    dark = int(c["background"][1:3], 16) < 128
    state = (hwnd, dark, c["background"], c["text"])
    if previous == state:
        return
    if previous is None or previous[:2] != state[:2]:
        value = wintypes.BOOL(dark)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
    if previous is None or previous[0] != hwnd:
        window._ld_caption_colors_supported = None
    if window._ld_caption_colors_supported is not False:
        results = []
        for attribute, color in ((35, c["background"]), (36, c["text"])):
            value = wintypes.DWORD(colorref(color))
            results.append(dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)))
        # Windows 11 supports caption/text colors. Older systems retain their
        # native dark/light frame without repeated calls to unsupported attrs.
        window._ld_caption_colors_supported = all(result >= 0 for result in results)
    window._ld_titlebar_state = state


def apply_style_colors(style, c):
    """Color-only updates keep fonts, widget sizes and layout stable during fades."""
    for name, color in (("LD.TFrame", c["background"]), ("Card.LD.TFrame", c["panel"]),
                        ("Inner.LD.TFrame", c["panel"]), ("Drop.LD.TFrame", c["drop"])):
        style.configure(name, background=color)
    style.configure("LD.TLabel", background=c["background"], foreground=c["text"])
    style.configure("Muted.LD.TLabel", foreground=c["muted"])
    style.configure("Brand.LD.TLabel", foreground=c["muted"])
    style.configure("Drop.LD.TLabel", background=c["drop"], foreground=c["drop_text"])
    style.configure("Card.LD.TLabel", background=c["panel"])
    style.configure("Caption.Card.LD.TLabel", foreground=c["muted"])
    style.configure("Number.Card.LD.TLabel", foreground=c["text"])
    for state, color in (("Ready", c["text"]), ("Busy", c["accent"]),
                         ("Success", c["success"]), ("Error", c["error"])):
        style.configure(state + ".Card.LD.TLabel", foreground=color)
    for name, color in (("LD.TButton", c["text"]), ("Field.LD.TButton", c["text"]),
                        ("Primary.LD.TButton", "#ffffff"), ("Quiet.LD.TButton", c["drop_text"])):
        style.configure(name, foreground=color)
        style.map(name, foreground=[("disabled", c["disabled_text"])])
    for widget in ("TEntry", "TCombobox"):
        name = "LD." + widget
        style.configure(name, fieldbackground=c["field"], foreground=c["text"],
                        insertcolor=c["text"], bordercolor=c["border"], lightcolor=c["border"],
                        darkcolor=c["border"], arrowcolor=c["muted"], background=c["field"])
        style.map(name, fieldbackground=[("disabled", c["disabled"])],
                  foreground=[("disabled", c["disabled_text"])], bordercolor=[("focus", c["accent"])],
                  selectbackground=[("!disabled", c["selection"])], selectforeground=[("!disabled", c["text"])])
    style.configure("LD.Horizontal.TProgressbar", background=c["accent"], troughcolor=c["disabled"],
                    bordercolor=c["disabled"], lightcolor=c["accent"], darkcolor=c["accent"])
    style.configure("LD.Vertical.TScrollbar", background=c["scrollbar"], troughcolor=c["field"],
                    bordercolor=c["field"], arrowcolor=c["muted"], lightcolor=c["scrollbar"], darkcolor=c["scrollbar"])
    style.map("LD.Vertical.TScrollbar", background=[("active", c["scrollbar_hover"])])


def apply_theme_widgets(window, c, intermediate=False):
    """Restyle native Tk content, including already-created details/dropdown."""
    window.option_add("*TCombobox*Listbox.background", c["field"])
    window.option_add("*TCombobox*Listbox.foreground", c["text"])
    window.option_add("*TCombobox*Listbox.selectBackground", c["selection"])
    window.option_add("*TCombobox*Listbox.selectForeground", c["text"])
    window.option_add("*TCombobox*Listbox.font", ("Microsoft YaHei UI", 10))
    def visit(widget):
        if isinstance(widget, (tk.Tk, tk.Toplevel)):
            widget.configure(background=c["background"])
            apply_titlebar_theme(widget, c)
        elif isinstance(widget, tk.Text):
            widget.configure(background=c["field"], foreground=c["text"],
                             insertbackground=c["text"], selectbackground=c["selection"],
                             selectforeground=c["text"])
        elif isinstance(widget, ThemeSwitch):
            if intermediate:
                widget.set_blended_palette(c)
            else:
                widget.set_palette(window._ld_theme_mode)
        if isinstance(widget, ttk.Combobox):
            popup = str(widget) + ".popdown.f.l"
            if widget.tk.call("winfo", "exists", popup):
                widget.tk.call(popup, "configure", "-background", c["field"], "-foreground", c["text"],
                               "-selectbackground", c["selection"], "-selectforeground", c["text"])
        for child in widget.winfo_children():
            visit(child)
    visit(window)


class ThemeFade:
    """Blend all app colors with one interruptible spring and reusable images."""

    def __init__(self, window):
        self.window = window
        self.alpha = self.target = 0.0
        self.velocity = 0.0
        self.timer_id = None
        self.last_time = time.perf_counter()
        self.style = ttk.Style(window)
        specs = window._ld_surface_specs
        self.surfaces = list(zip(specs["_fade"], specs["dark"], specs["light"]))
        for (image, _, _, radius, _), _, _ in self.surfaces:
            indexed_surface_geometry(image.width(), image.height(), radius)
        window.bind("<Destroy>", self._destroy, add="+")

    def to(self, mode, animate=True):
        self.target = float(mode == "light")
        self.window._ld_theme_mode = mode
        self.last_time = time.perf_counter()
        if not animate:
            self.cancel()
            self.alpha, self.velocity = self.target, 0.0
            configure_theme(self.window, mode)
            return
        # Match the current displayed color before the event loop paints,
        # including on a mid-animation reversal.
        self.render(self.alpha)
        if self.timer_id is None:
            self.timer_id = self.window.after(16, self._tick)

    def render(self, amount):
        self.alpha = amount
        if self.style.theme_use() != "WBEX._fade":
            self.style.theme_use("WBEX._fade")
        c = {key: blend_color(DARK_COLORS[key], LIGHT_COLORS[key], amount) for key in DARK_COLORS}
        self.window._ld_palette = c
        for (image, _, _, radius, _), dark, light in self.surfaces:
            paint_surface(image, radius, *(blend_color(dark[i], light[i], amount) for i in (1, 2, 4)))
        apply_style_colors(self.style, c)
        apply_theme_widgets(self.window, c, intermediate=True)

    def _tick(self):
        self.timer_id = None
        now = time.perf_counter()
        amount, self.velocity = spring_step(self.alpha, self.velocity, self.target,
                                            min(now - self.last_time, 0.05), response=0.4)
        self.last_time = now
        self.render(max(0.0, min(1.0, amount)))
        if abs(self.alpha - self.target) < 0.003 and abs(self.velocity) < 0.06:
            self.alpha, self.velocity = self.target, 0.0
            configure_theme(self.window, "light" if self.target else "dark")
        else:
            self.timer_id = self.window.after(16, self._tick)

    def cancel(self):
        if self.timer_id is not None:
            self.window.after_cancel(self.timer_id)
            self.timer_id = None

    def _destroy(self, event):
        if event.widget is self.window:
            self.cancel()


def text_view(parent, font, height=10):
    c = getattr(parent._root(), "_ld_palette", DARK_COLORS)
    container = ttk.Frame(parent, style="Inner.LD.TFrame")
    container.columnconfigure(0, weight=1)
    container.rowconfigure(0, weight=1)
    text = tk.Text(container, wrap="word", height=height, width=1, font=font,
                   background=c["field"], foreground=c["text"],
                   insertbackground=c["text"], selectbackground=c["selection"],
                   selectforeground=c["text"], relief="flat", borderwidth=0,
                   highlightthickness=0, padx=14, pady=12, spacing1=3, spacing3=5)
    bar = ttk.Scrollbar(container, orient="vertical", style="LD.Vertical.TScrollbar", command=text.yview)
    text.configure(yscrollcommand=bar.set)
    text.grid(row=0, column=0, sticky="nsew")
    bar.grid(row=0, column=1, sticky="ns")
    return container, text


def detect_ansys_installations() -> list[Path]:
    try:
        return discover_ansys_roots()
    except (BuildError, OSError):
        return []


def version_label(path):
    match = re.fullmatch(r"v(\d{2})(\d)", Path(path).name, re.IGNORECASE)
    if match:
        return "Ansys {} R{} ({})".format(
            2000 + int(match.group(1)), int(match.group(2)), match.group(0).lower())
    return ""


def explain_failure(raw):
    """Return a user-facing cause and next step; retain raw text separately."""
    text = str(raw).lower()
    if "rollback needs attention" in text:
        return ("更新失败，且旧版本未能完整恢复。",
                "请保留备份，先不要再次更新；保存日志并联系维护人员协助恢复。")
    if "select an existing .wbex package" in text:
        return ("找不到插件包，或当前路径无法访问。", "请点击“浏览…”重新选择存在的 .wbex 文件。")
    if "same guid" in text and "additional extension" in text:
        return ("检测到同一插件的源码开发版，与安装包冲突。",
                "请在 Ansys 的 Additional Extension Folders 中移除对应开发路径，再重试；无需删除源码。")
    if "cannot close ansys processes" in text:
        return ("无法强制关闭相关 Ansys 进程，更新已停止。",
                "请手动关闭列出的程序；若权限不足，请使用与 Ansys 相同的权限运行更新器后重试。")
    if any(part in text for part in ("close workbench", "workbench is running", "application started during staging")):
        return ("Workbench、Mechanical 或 SpaceClaim 仍在运行。",
                "请保存工作并关闭这些程序，然后重试。")
    if "another update is active" in text:
        return ("另一个更新任务正在运行，或上次中断后留下了锁文件。",
                "请先等待其他更新结束；若上次意外中断，请保存日志并联系维护人员确认后清理锁文件。")
    if "preferences changed during staging" in text:
        return ("更新期间 Ansys 配置被其他程序修改。", "请关闭 Ansys 后重试。")
    if any(part in text for part in ("no ansys workbench installation", "ansys installation must contain", "version directory named")):
        return ("找不到有效的 Ansys 安装目录。", "请浏览选择已安装的版本目录，例如 v241 或 v261。")
    if "cannot uniquely identify" in text or "act preferences" in text or "preferences file must" in text:
        return ("无法读取或确定 Ansys 的用户配置。", "请保存日志并联系维护人员检查配置文件。")
    if any(part in text for part in ("permissionerror", "permission denied", "access is denied", "winerror 5")):
        return ("没有权限访问所需文件，或文件被安全软件拦截。", "请确认当前账户可访问插件包和 Ansys 用户目录，检查拦截记录后重试。")
    if "winerror 32" in text or "used by another process" in text:
        return ("更新所需的文件正被其他程序占用。", "请关闭相关 Ansys 程序及其他更新器后重试。")
    if "no space left" in text or "winerror 112" in text:
        return ("磁盘可用空间不足。", "请释放用户目录所在磁盘的空间后重试。")
    if "cannot identify an installed wbex" in text:
        return ("无法识别已安装的旧插件包，已停止替换。", "请保存日志并联系维护人员检查旧包。")
    if "verification failed" in text or "failed verification" in text:
        return ("安装结果校验未通过。", "请保存日志并联系维护人员检查插件文件及默认加载配置。")
    if "wbex" in text or "resource" in text or "extension guid" in text or "package" in text:
        return ("插件包无法读取、内容不完整或格式不受支持。", "请重新获取完整的 .wbex 发布包后重试；若仍失败，请保存日志联系维护人员。")
    return ("操作未能完成，原因暂时无法自动判断。", "请将弹窗中的错误详情提供给维护人员。")


class UpdaterApp:
    def __init__(self, window: tk.Tk, root: Path = ROOT, package=None, defer_detection=False):
        self.window = window
        initialize_scale(window)
        apply_window_icon(window)
        self.root = root.resolve()
        self._browse_directories = {}
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self.details = []
        self.failure_message = ""
        self.failure_advice = ""
        self.motion_enabled = system_motion_enabled()
        self.details_window = None
        self.details_text = None
        self.drop_target = None
        self.dry_run = False
        self.controls: list[tk.Widget] = []
        self.startup_pending = bool(defer_detection)
        adjacent_packages = [] if defer_detection else sorted(self.root.glob("*.wbex"))
        initial_package = package or (adjacent_packages[0] if len(adjacent_packages) == 1 else "")
        self.package = tk.StringVar(value=str(initial_package))
        self.installations = [] if defer_detection else detect_ansys_installations()
        default_installation = select_default_ansys_root(self.installations)
        self.ansys_root = tk.StringVar(value=str(default_installation) if default_installation else "")
        self.version_hint = tk.StringVar()
        self.status = tk.StringVar(value="请选择 WBEX 插件包，然后检查或更新。")
        self.state_title = tk.StringVar(value="等待操作")
        self.next_step = tk.StringVar(value="检查不会更改任何文件。")
        self.package_hint = tk.StringVar()

        self.log_lines = []
        self.last_result = None
        self.failure_raw = ""
        self.failure_context = []
        window.title("ACT · WBEX 插件更新 v" + VERSION)
        self.theme_mode = tk.StringVar(value="dark")
        # Build the alternate styles before the first paint, so a first click
        # never has to generate rounded surfaces during the sliding animation.
        configure_theme(window, "light")
        configure_theme(window, "_fade", DARK_COLORS, "dark")
        self.style = configure_theme(window, self.theme_mode.get())
        self.theme_fade = ThemeFade(window)
        window.geometry("{}x{}".format(min(px(window, 760), window.winfo_screenwidth() - px(window, 60)),
                                      min(px(window, 500), window.winfo_screenheight() - px(window, 80))))
        window.minsize(px(window, 660), px(window, 460))
        window.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(window, padding=(24, 20), style="LD.TFrame")
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        header = ttk.Frame(frame, style="LD.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="ACT 插件更新", style="Title.LD.TLabel").grid(
            row=0, column=0, sticky="w")
        self.theme_switch = ThemeSwitch(header, self.theme_mode, self.change_theme, self.motion_enabled)
        self.theme_switch.grid(row=0, column=1, sticky="e", padx=(12, 0))

        self.drop_zone = ttk.Frame(frame, padding=(20, 14), style="Drop.LD.TFrame")
        self.drop_zone.grid(row=1, column=0, sticky="nsew", pady=(0, 16))
        self.drop_zone.columnconfigure(0, weight=1)
        self.drop_zone.rowconfigure(0, weight=1)
        self.drop_zone.rowconfigure(1, weight=1)
        self.drop_icon = ttk.Label(self.drop_zone, text="+", style="Icon.Drop.LD.TLabel", cursor="hand2")
        self.drop_icon.grid(row=0, column=0, sticky="s")
        self.drop_title = ttk.Label(self.drop_zone, text="将 .wbex 文件拖到这里",
                                    style="Drop.LD.TLabel", cursor="hand2", wraplength=600)
        self.drop_title.grid(row=1, column=0, sticky="n", pady=(5, 0))
        for widget in (self.drop_zone, self.drop_icon, self.drop_title):
            widget.bind("<Button-1>", self.keyboard_choose_package)
        self.drop_title.bind("<Configure>", self.fit_label)

        settings = ttk.Frame(frame, padding=(18, 12), style="Card.LD.TFrame")
        settings.grid(row=2, column=0, sticky="ew")
        settings.columnconfigure(1, weight=1)
        self.package_entry = self.path_row(settings, 0, "插件包", self.package, self.choose_package)
        self.ansys_selector = self.path_row(
            settings, 1, "Ansys 版本", self.ansys_root, self.choose_ansys,
            choices=[str(path) for path in self.installations])
        self.ansys_root.trace_add("write", self._ansys_path_changed)
        self._ansys_path_changed()

        actions = ttk.Frame(frame, style="LD.TFrame")
        actions.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        actions.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=100,
                                        style="LD.Horizontal.TProgressbar")
        self.progress.grid(row=0, column=0, sticky="w", padx=(0, 16))
        self.progress.grid_remove()
        self.check_button = ttk.Button(actions, text="检查（不更改）", command=lambda: self.start(dry_run=True),
                                       style="LD.TButton")
        self.check_button.grid(row=0, column=1)
        self.update_button = ttk.Button(actions, text="更新并设为默认", command=self.start,
                                        style="Primary.LD.TButton")
        self.update_button.grid(row=0, column=2, padx=(10, 0))
        self.controls.extend((self.check_button, self.update_button))

        self.package.trace_add("write", self._inputs_changed)
        self.ansys_root.trace_add("write", self._inputs_changed)
        self._inputs_changed()
        # Return performs the reversible check; installation stays explicit.
        window.bind("<Return>", self.keyboard_check)
        window.bind("<Control-o>", self.keyboard_choose_package)
        window.bind("<Control-s>", self.keyboard_save_log)
        window.bind("<Control-d>", lambda event: self.show_details())
        self.append("请选择插件包和目标 Ansys 版本。旧版插件及原配置会自动备份。\n")
        if defer_detection:
            self.version_hint.set("正在后台检测 Ansys 版本，也可直接浏览选择安装目录。")
            self.window.after(50, self._begin_startup_detection)
        scale_widget_tree(window)
        window.bind("<Map>", self.refresh_file_drop, add="+")
        window.after_idle(self.enable_file_drop)
        window.after(100, self.drain_events)

    def change_theme(self, animate=True):
        self.theme_fade.to(self.theme_mode.get(), animate=animate and self.motion_enabled)

    def enable_file_drop(self):
        if sys.platform != "win32":
            return
        try:
            if self.drop_target is not None:
                self.drop_target.refresh()
            else:
                self.drop_target = WindowsFileDrop(self.window, self.events, lambda: self.busy,
                                                extra_windows=(self.package_entry, self.drop_zone, self.drop_title, self.drop_icon))
        except (OSError, AttributeError) as error:
            self.details.append("拖放未能启用，可继续使用浏览按钮：{}".format(error))

    def refresh_file_drop(self, event):
        if event.widget is self.window:
            self.window.after_idle(self.enable_file_drop)

    def accept_drop(self, payload):
        if payload.get("busy") or self.busy:
            self.append("操作进行中，未更改安装包。请在操作结束后重新拖入。\n")
            messagebox.showinfo("操作进行中", "本次拖入未更改安装包，请在操作结束后重新拖入。", parent=self.window)
            return
        paths = payload.get("paths", [])
        if payload.get("count") != 1 or len(paths) != 1:
            self.set_state("未选择拖入的文件", "Error")
            self.status.set("一次只能拖入一个插件包。")
            self.next_step.set("请只拖入需要安装的那个 .wbex 文件。")
            messagebox.showwarning("无法选择插件包", self.status.get() + "\n\n" + self.next_step.get(), parent=self.window)
            return
        path = paths[0]
        if Path(path).suffix.lower() != ".wbex":
            self.set_state("无法使用拖入的文件", "Error")
            self.status.set("拖入的文件不是 .wbex 插件包。")
            self.next_step.set("请拖入完整的 .wbex 发布包，或点击“浏览…”重新选择。")
            messagebox.showwarning("无法选择插件包", self.status.get() + "\n\n" + self.next_step.get(), parent=self.window)
            return
        self._browse_directories[path] = str(Path(path).parent)
        self.package.set(path)
        self.package_entry.xview_moveto(1)
        self.package_entry.focus_set()
        self.status.set("已选择拖入的插件包：{}".format(Path(path).name))
        self.next_step.set("点击“检查（不更改）”确认安装条件。")

    def _begin_startup_detection(self):
        threading.Thread(target=self._startup_worker, daemon=True).start()

    def _startup_worker(self):
        started = time.perf_counter()
        try:
            installations = detect_ansys_installations()
            detection_seconds = time.perf_counter() - started
            packages = sorted(self.root.glob("*.wbex"))
            self.events.put(("startup", (installations, packages, detection_seconds,
                                         time.perf_counter() - started)))
        except Exception as error:
            self.events.put(("startup_error", str(error)))

    def record_window_ready(self):
        elapsed = time.perf_counter() - getattr(sys, "_wbex_updater_entry_time", time.perf_counter())
        self.details.append("[启动计时] Python 入口至界面就绪：{:.3f} 秒。".format(elapsed))
        self.details.append("[启动计时] 此计时不包含 EXE 解包及 Python 启动之前的系统安全检查。")
        self.details.append("[显示] DPI：{}；界面缩放：{:.0%}。".format(
            self.window._ld_dpi, self.window._ld_ui_scale))

    def path_row(self, frame, row, label, variable, browse, choices=None):
        ttk.Label(frame, text=label, style="Number.Card.LD.TLabel").grid(
            row=row, column=0, sticky="w", padx=(0, 18), pady=4)
        entry = (ttk.Entry(frame, textvariable=variable, style="LD.TEntry",
                           font=("Microsoft YaHei UI", 10)) if choices is None else
                 ttk.Combobox(frame, textvariable=variable, values=choices, state="normal",
                              style="LD.TCombobox", font=("Microsoft YaHei UI", 10)))
        entry.grid(row=row, column=1, sticky="ew", pady=5)
        button = ttk.Button(frame, text="浏览…", command=browse, style="Field.LD.TButton")
        button.grid(row=row, column=2, padx=(8, 0), pady=5)
        self.controls.extend((entry, button))
        return entry

    def _ansys_path_changed(self, *unused):
        label = version_label(self.ansys_root.get().strip())
        if label:
            self.version_hint.set("目标：{}；可下拉切换或手动选择，仅更新所选版本。".format(label))
        elif self.installations:
            self.version_hint.set("已检测到 {} 个版本，优先 v241，缺少时选择最新版本；也可手动输入目录。".format(
                len(self.installations)))
        else:
            self.version_hint.set("未检测到 Ansys 安装，请浏览选择版本目录；留空时在运行前再次检测。")

    def initial_directory(self, value):
        # Never stat user-entered paths before opening the dialog: a stale
        # network drive can otherwise freeze the UI for seconds.
        value = value.strip()
        if value in self._browse_directories:
            return self._browse_directories[value]
        if value in {str(path) for path in self.installations}:
            return value
        return str(self.root)

    def fit_label(self, event):
        width = max(px(self.window, 100), event.width)
        if int(str(event.widget.cget("wraplength"))) != width:
            event.widget.configure(wraplength=width)

    def choose_package(self):
        selected = filedialog.askopenfilename(
            parent=self.window,
            title="选择 ACT 插件包",
            initialdir=self.initial_directory(self.package.get()),
            filetypes=(("ACT 插件包", "*.wbex"), ("所有文件", "*.*")),
        )
        if selected:
            self._browse_directories[selected] = str(Path(selected).parent)
            self.package.set(selected)

    def choose_ansys(self):
        selected = filedialog.askdirectory(
            parent=self.window,
            title="选择 Ansys 版本安装目录",
            initialdir=self.initial_directory(self.ansys_root.get()),
        )
        if selected:
            self._browse_directories[selected] = selected
            self.ansys_root.set(selected)

    @property
    def log_text(self):
        return "".join(self.log_lines)

    def append(self, text):
        self.log_lines.append(text)

    def _inputs_changed(self, *unused):
        if self.busy:
            return
        value = self.package.get().strip()
        invalid = bool(value) and Path(value).suffix.lower() != ".wbex"
        self.package_hint.set("请选择 .wbex 插件包，不能选择 XML 或 ZIP 文件。" if invalid else "")
        self.set_state("插件包格式不正确" if invalid else "选择插件包" if not value else "准备检查",
                       "Error" if invalid else "Ready")
        self.status.set("请拖入 .wbex 文件，或点击“浏览…”选择。" if not value else
                        "请重新选择 .wbex 插件包。" if invalid else
                        "检查不会更改文件，更新前会自动备份旧版插件和设置。" if self.ansys_root.get().strip() else
                        "请选择 Ansys 安装目录，或等待自动检测。")
        self.next_step.set("点击“检查（不更改）”确认安装条件。" if not invalid else
                           "请使用发布时提供的完整安装包。")

    def keyboard_check(self, event=None):
        focus = self.window.focus_get()
        # Keep standard Return behavior on buttons and in the log/details text.
        if focus is not None and not isinstance(focus, (ttk.Entry, ttk.Combobox)):
            return
        self.start(dry_run=True)
        return "break"

    def keyboard_choose_package(self, event=None):
        if not self.busy:
            self.choose_package()
        return "break"

    def keyboard_save_log(self, event=None):
        self.save_log()
        return "break"

    def set_state(self, title, state="Ready"):
        self.state_title.set(title)

    def start(self, dry_run=False):
        if self.busy:
            return
        if self.startup_pending and not self.ansys_root.get().strip():
            self.status.set("版本检测尚未完成；可等待检测或手动选择 Ansys 安装目录。")
            messagebox.showinfo("正在检测 Ansys", self.status.get(), parent=self.window)
            return
        package_text = self.package.get().strip()
        package = Path(package_text)
        if not package_text or package.suffix.lower() != ".wbex":
            self.set_state("无法开始", "Error")
            self.status.set("未找到可用的插件包。")
            self.next_step.set("请点击“浏览…”选择存在的 .wbex 文件。")
            self.package_hint.set("文件不存在或格式不正确，请重新选择。")
            self.package_entry.focus_set()
            messagebox.showerror("无法开始", self.status.get() + "\n\n" + self.next_step.get(), parent=self.window)
            return
        # The worker's engine resolves and validates this path. UI feedback must
        # be painted before any filesystem work, including exists/resolve.
        options = {"package_path": package_text, "dry_run": bool(dry_run)}
        ansys = self.ansys_root.get().strip()
        if ansys:
            options["ansys_root"] = ansys

        self.busy = True
        self.failure_message = ""
        self.failure_advice = ""
        self.failure_raw = ""
        self.failure_context = []
        self.last_result = None
        self.dry_run = dry_run
        for control in self.controls:
            control.configure(state="disabled")
        action = "检查" if dry_run else "更新"
        (self.check_button if dry_run else self.update_button).configure(text="正在%s…" % action)
        self.set_state("正在%s" % action, "Busy")
        self.status.set("正在读取插件包并检查安装条件。")
        self.next_step.set("本次只检查，不会更改文件。" if dry_run else "旧版插件和设置会自动备份，请稍候。")
        if self.motion_enabled:
            self.progress.grid()
            self.progress.start(12)
        self.append("\n[%s] 开始%s：%s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), action, package))
        self.details.append("开始{}：{}；目标：{}".format(action, package, ansys or "自动检测"))
        self.append("正在读取插件包并检查安装条件，请稍候…\n")
        threading.Thread(target=self.update_worker, args=(options,), daemon=True).start()

    def update_worker(self, options):
        options = dict(options)
        approved = options.pop("_close_processes", ())
        try:
            if approved and not options.get("dry_run", False):
                close_ansys_processes(approved)
                self.events.put(("line", "已关闭用户确认的 Ansys 进程，正在重新检查并更新。\n"))
            # The engine is bundled with the app. Never launch python.exe or
            # look for a neighboring tools directory on the user's machine.
            result = update(**options, notify=lambda text: self.events.put(("line", str(text) + "\n")))
            self.events.put(("result", result))
            self.events.put(("done", 0))
        except AnsysProcessesRunning as exc:
            if options.get("dry_run", False):
                self.events.put(("error", str(exc)))
            else:
                self.events.put(("processes_running", (exc.names, options)))
        except Exception as exc:
            self.events.put(("error", "%s: %s" % (type(exc).__name__, exc)))

    def confirm_close_processes(self, names, options):
        # Dialogs run on the Tk thread; termination and the full retry run on a worker.
        self.progress.stop()
        self.status.set("等待确认是否强制关闭 Ansys 进程。")
        confirmed = messagebox.askyesno(
            "强制关闭 Ansys 并继续更新？",
            "以下进程仍在运行：\n\n" + "\n".join(names) +
            "\n\n强制关闭可能导致未保存的工作或计算结果丢失。\n"
            "选择“是”：强制关闭列出的进程，并继续更新 .wbex。\n"
            "选择“否”：取消本次更新，请保存工作并手动关闭后重试。",
            default=messagebox.NO, icon=messagebox.WARNING, parent=self.window)
        if not confirmed:
            self.finish(2)
            return
        self.details.append("用户同意强制关闭：" + ", ".join(names))
        self.status.set("正在关闭 Ansys 进程，随后继续更新。")
        if self.motion_enabled:
            self.progress.start(12)
        retry = dict(options, _close_processes=tuple(names))
        threading.Thread(target=self.update_worker, args=(retry,), daemon=True).start()

    def drain_events(self):
        for _ in range(200):
            try:
                event, value = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "startup":
                self.startup_pending = False
                installations, packages, detection_seconds, total_seconds = value
                self.installations = installations
                self.ansys_selector.configure(values=[str(path) for path in installations])
                # Preserve anything entered while the background scan ran.
                if not self.ansys_root.get().strip():
                    default = select_default_ansys_root(installations)
                    if default is not None:
                        self.ansys_root.set(str(default))
                if not self.package.get().strip() and len(packages) == 1:
                    self.package.set(str(packages[0]))
                self._ansys_path_changed()
                self.details.append("[启动计时] Ansys 路径检测：{:.3f} 秒；后台检测总计：{:.3f} 秒。".format(
                    detection_seconds, total_seconds))
            elif event == "startup_error":
                self.startup_pending = False
                self.details.append("自动检测失败：{}".format(value))
                self.append("自动检测未完成，请手动选择插件包和 Ansys 安装目录。\n")
                self._ansys_path_changed()
                messagebox.showwarning("自动检测未完成", "请手动选择插件包和 Ansys 安装目录。", parent=self.window)
            elif event == "drop":
                self.accept_drop(value)
            elif event == "drop_error":
                self.details.append("文件拖放失败：{}".format(value))
                if not self.busy:
                    self.set_state("未能读取拖入的文件", "Error")
                    self.status.set("请重新拖入一个 .wbex 文件。")
                    self.next_step.set("也可以点击“浏览…”选择插件包。")
                    messagebox.showerror("文件拖放失败", self.status.get() + "\n\n" + self.next_step.get(), parent=self.window)
            elif event == "line":
                self.details.append(str(value).rstrip())
                self.show_progress(str(value).strip())
            elif event == "processes_running":
                self.confirm_close_processes(*value)
            elif event == "result":
                self.last_result = value
                self.details.append(json.dumps(value, ensure_ascii=False, indent=2))
                if value.get("backup"):
                    self.append("旧版本及配置备份位置：{}\n".format(value["backup"]))
            elif event == "done":
                self.finish(int(value))
            elif event == "error":
                self.details.append(str(value))
                cause, advice = explain_failure(value)
                self.failure_message = cause
                self.failure_advice = advice
                self.failure_raw = str(value)
                self.failure_context = []
                self.append("\n【{}失败】{}\n处理办法：{}\n".format(
                    "检查" if self.dry_run else "更新", cause, advice))
                if "previous installation restored." in str(value):
                    self.append("本次更改已回退，已恢复更新前的安装状态。\n")
                    self.failure_context.append("本次更改已回退，已恢复更新前的安装状态。")
                if "Recovery files: " in str(value):
                    self.append("恢复文件位置：{}\n".format(str(value).split("Recovery files: ", 1)[1]))
                    self.failure_context.append("恢复文件位置：{}".format(str(value).split("Recovery files: ", 1)[1]))
                self.finish(1)
        self.refresh_details()
        self.window.after(100, self.drain_events)

    def show_progress(self, text):
        if text.startswith("Package: "):
            self.append("已识别插件：{}\n".format(text[9:].split(" / ", 1)[0]))
            self.status.set("已识别插件：{}".format(text[9:].split(" / ", 1)[0]))
        elif text.startswith("Target Ansys: "):
            self.append("目标版本：{}\n".format(text[14:].split(" / ", 1)[0]))
        elif text.startswith("Replace "):
            self.status.set("安装条件检查已完成。" if self.dry_run else "正在备份旧版本并安装新插件。")
            self.append("安装条件检查已完成。\n" if self.dry_run else
                        "正在备份旧版本、安装新插件并设置默认加载…\n")
        elif text.startswith("Could not remove the update lock"):
            self.append("提示：更新锁文件未能清理，下次更新前请联系维护人员处理。\n")

    def show_details(self):
        if self.details_window is not None and self.details_window.winfo_exists():
            self.refresh_details()
            self.details_window.deiconify()
            self.details_window.lift()
            return
        dialog = tk.Toplevel(self.window)
        self.details_window = dialog
        dialog.title("技术详情（可保存日志发给维护人员）")
        dialog.geometry("{}x{}".format(px(self.window, 850), px(self.window, 550)))
        dialog.configure(background=self.window._ld_palette["background"])
        container, text = text_view(dialog, ("Consolas", 10))
        self.details_text = text
        container.pack(fill="both", expand=True, padx=16, pady=16)
        dialog.transient(self.window)
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        ttk.Button(dialog, text="关闭", command=dialog.destroy, style="LD.TButton").pack(
            anchor="e", padx=16, pady=(0, 12))
        self._details_count = -1
        scale_widget_tree(dialog)
        self.refresh_details()

    def refresh_details(self):
        if (self.details_window is None or not self.details_window.winfo_exists() or
                getattr(self, "_details_count", -1) == len(self.details)):
            return
        text = self.details_text
        top, bottom = text.yview()
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("end", "\n".join(self.details) or "暂无技术详情。")
        text.configure(state="disabled")
        if bottom >= 0.99:
            text.see("end")
        else:
            text.yview_moveto(top)
        self._details_count = len(self.details)

    def finish(self, returncode):
        self.busy = False
        self.progress.stop()
        self.progress.grid_remove()
        for control in self.controls:
            control.configure(state="normal")
        self.check_button.configure(text="检查（不更改）")
        self.update_button.configure(text="更新并设为默认")
        if returncode == 2:
            self.set_state("更新已取消", "Ready")
            self.status.set("已取消更新，插件和配置未更改。")
            self.next_step.set("请保存工作并手动关闭 Ansys 后重试。")
            self.append("【更新已取消】用户未同意强制关闭进程。\n")
        elif returncode == 0:
            if self.dry_run:
                self.set_state("检查成功", "Success")
                self.status.set("插件包和安装条件检查通过，本次未更改任何文件。")
                self.next_step.set("点击“更新并设为默认”完成安装。")
                self.append("【检查成功】插件包及安装条件检查通过。本次未更改任何文件或配置。\n"
                            "下一步：关闭 Workbench、Mechanical 和 SpaceClaim 后，点击“更新并设为默认”。\n")
            else:
                self.set_state("更新成功", "Success")
                self.status.set("新插件已安装，并已设为默认加载。")
                self.next_step.set("现在可以启动 Ansys，使用新版本插件。")
                self.append("【更新成功】新插件已安装，并已设为默认加载。\n下一步：启动 Ansys 使用新版本插件。\n")
            message = self.status.get() + "\n\n" + self.next_step.get()
            if not self.dry_run and (self.last_result or {}).get("backup"):
                message += "\n\n旧版本及配置备份位置：\n" + self.last_result["backup"]
            messagebox.showinfo("检查成功" if self.dry_run else "更新成功", message, parent=self.window)
        else:
            action = "检查" if self.dry_run else "更新"
            self.set_state("%s失败" % action, "Error")
            self.status.set(self.failure_message or "操作未能完成。")
            self.next_step.set(self.failure_advice or "请保存日志并联系维护人员。")
            message = self.status.get() + "\n\n处理办法：" + self.next_step.get()
            if self.failure_context:
                message += "\n\n" + "\n".join(self.failure_context)
            messagebox.showerror("%s失败" % action, message,
                                 detail=self.failure_raw or None, parent=self.window)

    def save_log(self):
        selected = filedialog.asksaveasfilename(
            parent=self.window,
            title="保存更新日志",
            initialfile="wbex-update-%s.log" % datetime.now().strftime("%Y%m%d-%H%M%S"),
            defaultextension=".log",
            filetypes=(("日志文件", "*.log"), ("文本文件", "*.txt")),
        )
        if not selected:
            return
        try:
            Path(selected).write_text(self.log_text +
                                      "\n\n--- 技术详情 ---\n" + "\n".join(self.details), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("日志保存失败", str(exc), parent=self.window)

    def close(self):
        if self.busy:
            messagebox.showinfo("任务仍在进行", "后台操作正在运行，请等待本次操作结束后关闭窗口。", parent=self.window)
            return
        if self.drop_target is not None:
            self.drop_target.close()
        self.window.destroy()


def main(package=None):
    window = create_window()
    app = UpdaterApp(window, package=package, defer_detection=True)
    window.after_idle(app.record_window_ready)
    window.mainloop()


if __name__ == "__main__":
    main()
