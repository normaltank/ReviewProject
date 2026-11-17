"""Shared, dependency-free Tk surfaces for local reading and operation."""
import tkinter as tk
from tkinter import ttk

BACKGROUND = '#101112'
SURFACE = '#191b1d'
TEXT = '#f0f0ed'
MUTED = '#b7b9ba'
LINE = '#393d40'
AMBER = '#edb85c'


def theme(window):
    """Use standard Tk controls, with one restrained palette per interpreter."""
    window.configure(background=BACKGROUND)
    style = ttk.Style(window)
    if getattr(window._root(), '_review_theme', False):
        return
    style.theme_use('clam')
    style.configure('.', background=BACKGROUND, foreground=TEXT, font=('Microsoft YaHei UI', 10))
    style.configure('TFrame', background=BACKGROUND)
    style.configure('TLabel', padding=0)
    style.configure('Title.TLabel', font=('Microsoft YaHei UI', 21, 'bold'))
    style.configure('Heading.TLabel', font=('Microsoft YaHei UI', 13, 'bold'))
    style.configure('Muted.TLabel', foreground=MUTED)
    style.configure('Status.TLabel', foreground=AMBER)
    style.configure('TButton', background=SURFACE, bordercolor=LINE, lightcolor=LINE,
                    darkcolor=LINE, padding=(12, 8), focusthickness=2, focuscolor=TEXT)
    style.map('TButton', background=[('active', '#303438')], foreground=[('disabled', '#777c80')])
    style.configure('Primary.TButton', background=TEXT, foreground=BACKGROUND, bordercolor=TEXT)
    style.map('Primary.TButton', background=[('disabled', '#565b60'), ('active', '#d8d9d6')],
              foreground=[('disabled', '#b7b9ba'), ('active', BACKGROUND)])
    style.configure('TEntry', fieldbackground=SURFACE, insertcolor=TEXT, bordercolor=LINE, padding=6)
    style.configure('TCombobox', fieldbackground=SURFACE, background=SURFACE, arrowcolor=TEXT, padding=5)
    style.map('TCombobox', fieldbackground=[('readonly', SURFACE)], foreground=[('readonly', TEXT)])
    style.configure('TNotebook', background=BACKGROUND, borderwidth=0, bordercolor=LINE,
                    lightcolor=LINE, darkcolor=LINE)
    style.configure('TNotebook.Tab', background=BACKGROUND, padding=(16, 10), borderwidth=0,
                    bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
    style.map('TNotebook.Tab', background=[('selected', SURFACE)], foreground=[('selected', TEXT), ('!selected', MUTED)])
    style.configure('TSeparator', background=LINE)
    style.configure('TScrollbar', background=LINE, troughcolor=BACKGROUND, arrowcolor=MUTED,
                    bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
    style.configure('Horizontal.TProgressbar', background=MUTED, troughcolor=SURFACE, borderwidth=0)
    # tkapp has no Python attributes; mark the root widget, not the Tcl object.
    window._root()._review_theme = True


def wrapped(parent, *, text=None, textvariable=None, style='Muted.TLabel'):
    label = ttk.Label(parent, text=text, textvariable=textvariable, style=style, wraplength=600, justify='left')
    label.bind('<Configure>', lambda event: label.configure(wraplength=max(160, event.width)))
    return label


def text_style(widget):
    widget.configure(background=SURFACE, foreground=TEXT, insertbackground=TEXT,
                     selectbackground='#4b5258', selectforeground=TEXT, relief='flat',
                     highlightthickness=1, highlightbackground=LINE, highlightcolor=TEXT,
                     font=('Microsoft YaHei UI', 11), padx=12, pady=10)


def list_style(widget):
    widget.configure(background=SURFACE, foreground=TEXT, selectbackground='#363c41',
                     selectforeground=TEXT, relief='flat', highlightthickness=1,
                     highlightbackground=LINE, highlightcolor=TEXT,
                     font=('Microsoft YaHei UI', 10), activestyle='dotbox')


class ScrollBody(ttk.Frame):
    """A normal form that stays reachable when optional fields are expanded."""
    def __init__(self, parent, *, padding=0):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, background=BACKGROUND, highlightthickness=0, takefocus=False,
                                width=1, height=1)
        scroll = ttk.Scrollbar(self, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.canvas.pack(fill='both', expand=True)
        self.body = ttk.Frame(self.canvas, padding=padding)
        self.item = self.canvas.create_window((0, 0), window=self.body, anchor='nw')
        self.body.bind('<Configure>', lambda event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(self.item, width=event.width))
        # Bind at the toplevel, then scope the event to this scroll body.
        parent.winfo_toplevel().bind('<MouseWheel>', self._wheel, add='+')
        parent.winfo_toplevel().bind('<FocusIn>', self._focus, add='+')

    def _contains(self, widget):
        return str(widget).startswith(str(self.body) + '.')

    def _wheel(self, event):
        if self.winfo_exists() and self._contains(event.widget):
            self.canvas.yview_scroll(-int(event.delta / 120), 'units')

    def _focus(self, event):
        if not self.winfo_exists() or not self._contains(event.widget):
            return
        self.update_idletasks()
        top = event.widget.winfo_rooty() - self.body.winfo_rooty()
        visible_top = self.canvas.canvasy(0)
        height = self.canvas.winfo_height()
        bottom = top + event.widget.winfo_height()
        total = max(self.body.winfo_height(), 1)
        if top < visible_top:
            self.canvas.yview_moveto(max(0, top - 10) / total)
        elif bottom > visible_top + height:
            self.canvas.yview_moveto(max(0, bottom - height + 10) / total)


def disclosure(parent, label):
    holder = ttk.Frame(parent)
    holder.pack(fill='x', pady=(8, 0))
    ttk.Separator(holder).pack(fill='x')
    body = ttk.Frame(holder, padding=(0, 8))
    button = ttk.Button(holder, text=label + '…')
    button.pack(anchor='w', pady=(6, 0))
    def toggle():
        opened = bool(body.winfo_manager())
        body.pack_forget() if opened else body.pack(fill='x')
        button.configure(text=label + ('…' if opened else ' · 收起'))
    button.configure(command=toggle)
    return body
