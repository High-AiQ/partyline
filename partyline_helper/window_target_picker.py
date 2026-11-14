"""Second local consent step: choose exactly one line to share the window with."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def public_selection(line):
    return {key: line[key] for key in ("line_id", "line_name") if key in line}


def public_lines(lines):
    return [{"line_id": line["line_id"], "line_name": line["line_name"],
             "processes": len(line.get("processes", ()))} for line in lines]


def select_target(lines, run=subprocess.run):
    """The one line the person chose, or None; lines may have no process attached yet."""
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


def line_text(line):
    count = line["processes"]
    return f"«{line['line_name']}» — " + (f"{count} attached process{'es' if count != 1 else ''}"
                                           if count else "no process attached yet")


def dialog(root, lines, accept):  # pragma: no cover - native picker, verified with a real capture
    import tkinter as tk
    from tkinter import ttk
    root.title("Share this window with which line?")
    root.minsize(540, 340)
    tk.Label(root, text="Choose one line. Every process attached to it, now or later, may read and act "
                       "on this window until you stop sharing.\nNothing is selected by default.",
             wraplength=550, justify="left").pack(padx=16, pady=12, anchor="w")
    tree = ttk.Treeview(root, show="tree", selectmode="browse", height=12)
    options = {}
    for i, line in enumerate(lines):
        ident = f"line-{i}"
        tree.insert("", "end", iid=ident, text=line_text(line))
        options[ident] = public_selection(line)
    tree.pack(fill="both", expand=True, padx=16)
    buttons = tk.Frame(root)
    buttons.pack(fill="x", padx=16, pady=12)

    def grant():
        selected = tree.selection()
        if selected and selected[0] in options:
            accept(options[selected[0]])
            root.destroy()

    button = ttk.Button(buttons, text="Share with selected line", command=grant, state="disabled")
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
