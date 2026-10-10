"""Mail metnine değişken ({{Firma}} vb.) eklemek için yan panel ve sağ tık menüsü."""
import tkinter as tk

import customtkinter as ctk

MENU_FONT = ("Segoe UI", 10)


def _short(text, limit=28):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def placeholder(name):
    return "{{" + name + "}}"


def insert_variable(ctk_widget, name, index=None):
    """Değişkeni verilen konuma (yoksa imlece) ekler; o konumda seçili metin varsa onun yerine yazar."""
    text = placeholder(name)
    inner = getattr(ctk_widget, "_textbox", None) or getattr(ctk_widget, "_entry", None)
    if isinstance(inner, tk.Text):
        index = index or inner.index("insert")
        try:
            first, last = inner.index("sel.first"), inner.index("sel.last")
            if inner.compare(first, "<=", index) and inner.compare(index, "<=", last):
                inner.delete(first, last)
                index = first
        except tk.TclError:
            pass
        ctk_widget.insert(index, text)
        inner.mark_set("insert", f"{index}+{len(text)}c")
    else:
        if getattr(ctk_widget, "_placeholder_text_active", False):
            index = 0  # gri örnek yazı görünüyorsa kutu aslında boş
        elif index is None:
            index = inner.index("insert")
        if inner.selection_present():
            first, last = inner.index("sel.first"), inner.index("sel.last")
            if first <= index <= last:
                inner.delete(first, last)
                index = first
        ctk_widget.insert(index, text)
        inner.icursor(index + len(text))
    inner.focus_set()


def attach_variable_menu(ctk_widget, get_variables, after_insert=None):
    """Sağ tıkta 'Değişken ekle ▸' menüsü; seçilen değişken tıklanan yere yazılır.

    get_variables(): [(ad, örnek değer)] döner.
    """
    inner = getattr(ctk_widget, "_textbox", None) or getattr(ctk_widget, "_entry", None)
    is_text = isinstance(inner, tk.Text)

    def popup(event):
        index = inner.index(f"@{event.x},{event.y}") if is_text else inner.index(f"@{event.x}")
        menu = tk.Menu(inner, tearoff=0, font=MENU_FONT)
        variables_menu = tk.Menu(menu, tearoff=0, font=MENU_FONT)
        variables = get_variables()
        for name, sample in variables:
            label = placeholder(name) + (f"      ({_short(sample)})" if sample else "")
            variables_menu.add_command(label=label, command=lambda n=name: _insert(n, index))
        if not variables:
            variables_menu.add_command(label="(önce firma listesi yükleyin)", state="disabled")
        menu.add_cascade(label="Değişken ekle", menu=variables_menu)
        menu.add_separator()
        menu.add_command(label="Kes", command=lambda: inner.event_generate("<<Cut>>"))
        menu.add_command(label="Kopyala", command=lambda: inner.event_generate("<<Copy>>"))
        menu.add_command(label="Yapıştır", command=lambda: inner.event_generate("<<Paste>>"))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _insert(name, index):
        insert_variable(ctk_widget, name, index)
        if after_insert:
            after_insert()

    inner.bind("<Button-3>", popup, add="+")


class VariablePanel(ctk.CTkFrame):
    """Metnin yanında duran değişken listesi. Tıklanınca on_pick(ad) çağrılır."""

    def __init__(self, master, get_variables, on_pick, width=190):
        super().__init__(master, fg_color=("gray94", "gray20"), corner_radius=8)
        self.get_variables = get_variables
        self.on_pick = on_pick
        ctk.CTkLabel(self, text="Değişkenler", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=10, pady=(8, 0))
        ctk.CTkLabel(self, text="Tıkla ya da metinde\nsağ tık → Değişken ekle", text_color="gray40",
                     justify="left", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=10, pady=(0, 4))
        self.items = ctk.CTkScrollableFrame(self, width=width, fg_color="transparent")
        self.items.pack(fill="both", expand=True, padx=2, pady=(0, 6))

    def refresh(self):
        for child in self.items.winfo_children():
            child.destroy()
        for name, sample in self.get_variables():
            ctk.CTkButton(
                self.items, text=placeholder(name), anchor="w", height=26,
                fg_color=("#e3e9f1", "gray30"), text_color=("#1a3c6e", "white"), hover_color=("#cfd9e6", "gray40"),
                command=lambda n=name: self.on_pick(n),
            ).pack(fill="x", pady=(4, 0))
            if sample:
                ctk.CTkLabel(self.items, text=_short(sample, 26), text_color="gray45", anchor="w",
                             font=ctk.CTkFont(size=11)).pack(fill="x", padx=6)
