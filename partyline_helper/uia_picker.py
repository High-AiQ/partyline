"""Locally initiated window picker; result is returned only after explicit consent."""
import json
import os
import sys


def main(path):  # pragma: no cover - native Windows dialog, exercised by Windows CI
    import tkinter as tk
    from .uia_window_list import windows
    from .uia_window_identity import mark, unmark
    options = windows(exclude=(os.getppid(),)) or []
    root = tk.Tk()
    root.title("Partyline window access")
    tk.Label(root, text="Choose a window to let agents read. With separate agent control consent, "
                       "they can also act on its elements. No window is selected by default.",
             wraplength=500).pack()
    listing = tk.Listbox(root, width=80, height=min(20, max(3, len(options))))
    for item in options:
        listing.insert("end", f"{item['title']} ({item['process']})")
    listing.pack(padx=12, pady=12)
    detail = tk.StringVar(value="Select a window to review the grant.")
    tk.Label(root, textvariable=detail, wraplength=500).pack()

    def selected(_event=None):
        choice = listing.curselection()
        if choice:
            item = options[choice[0]]
            detail.set(f"Let agents read {item['title']} ({item['process']}); "
                       "separate agent control consent also permits element actions.")

    def grant():
        choice = listing.curselection()
        if choice:
            selected = dict(options[choice[0]])
            selected["marker"] = mark(selected["hwnd"])
            if selected["marker"]:
                try:
                    with open(path, "w", encoding="utf-8") as stream:
                        json.dump(selected, stream)
                except OSError:
                    unmark(selected)
        root.destroy()

    listing.bind("<<ListboxSelect>>", selected)
    tk.Button(root, text="Allow selected window", command=grant).pack(side="left", padx=12, pady=12)
    tk.Button(root, text="Cancel", command=root.destroy).pack(side="right", padx=12, pady=12)
    root.after(60000, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main(sys.argv[1])
