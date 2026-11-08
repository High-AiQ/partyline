"""Second local consent step: choose exactly one attached process, grouped by line."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def public_selection(process):
    return {key: process[key] for key in ("attachment_id", "name", "preset", "line_id", "line_name")
            if key in process}


def public_lines(lines):
    return [{"line_id": line["line_id"], "line_name": line["line_name"],
             "processes": [public_selection(process) for process in line["processes"]]} for line in lines]


def select_target(lines, run=subprocess.run):
    if not lines:
        return None
    with tempfile.TemporaryDirectory(prefix="partyline-target-") as directory:
        path = Path(directory) / "selection.json"
        path.write_text(json.dumps({"lines": public_lines(lines)}), encoding="utf-8")
        command = ([sys.executable, "window-target-picker", str(path)] if getattr(sys, "frozen", False) else
                   [sys.executable, "-m", "partyline_helper.window_target_picker", str(path)])
        try:
            flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
            run(command, timeout=65, check=True, **flags)
            selected = json.loads(path.read_text(encoding="utf-8")).get("selected")
            return public_selection(selected) if selected else None
        except (OSError, ValueError, subprocess.SubprocessError):
            return None


def dialog(root, lines, accept):  # pragma: no cover - native picker, verified with a real capture
    import tkinter as tk
    from tkinter import ttk
    root.title("Share this window with which process?")
    root.minsize(540, 340)
    tk.Label(root, text="Choose one attached process. It may read and act on this window.\n"
                       "Other processes will not have access. Nothing is selected by default.",
             wraplength=550, justify="left").pack(padx=16, pady=12, anchor="w")
    tree = ttk.Treeview(root, show="tree", selectmode="browse", height=12)
    options = {}
    for i, line in enumerate(lines):
        parent = tree.insert("", "end", iid=f"line-{i}", text=f"«{line['line_name']}»", open=True)
        for j, process in enumerate(line["processes"]):
            ident = f"process-{i}-{j}"
            tree.insert(parent, "end", iid=ident, text=f"@{process['name']} ({process['preset']})")
            options[ident] = {**process, "line_id": line["line_id"], "line_name": line["line_name"]}
    tree.pack(fill="both", expand=True, padx=16)
    buttons = tk.Frame(root)
    buttons.pack(fill="x", padx=16, pady=12)

    def grant():
        selected = tree.selection()
        if selected and selected[0] in options:
            accept(options[selected[0]])
            root.destroy()

    button = ttk.Button(buttons, text="Share with selected process", command=grant, state="disabled")
    button.pack(side="left")
    tree.bind("<<TreeviewSelect>>", lambda _: button.configure(
        state="normal" if tree.selection() and tree.selection()[0] in options else "disabled"))
    ttk.Button(buttons, text="Cancel", command=root.destroy).pack(side="right")
    root.after(60000, root.destroy)
    return tree


def main(path):  # pragma: no cover - native picker subprocess
    import tkinter as tk
    path = Path(path)
    lines = json.loads(path.read_text(encoding="utf-8"))["lines"]
    path.write_text("{}", encoding="utf-8")
    root = tk.Tk()
    dialog(root, lines, lambda selected: path.write_text(
        json.dumps({"selected": selected}), encoding="utf-8"))
    root.mainloop()


if __name__ == "__main__":
    main(sys.argv[1])
