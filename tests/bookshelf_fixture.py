"""A UIA tree modeled on a Chrome page of a book shelf: nav chrome, a table of rows and a numbered pager."""
import hashlib

SERIES = ["Harbor Lights", "The Quiet Orchard", "Salt and Ember", "Paper Kingdoms", "Lantern Row",
          "Winter Atlas", "Copper Sky", "River of Glass", "Northbound", "The Long Dusk"]
URL = "https://kdp.example.com/en_US/bookshelf"


def helper_id(snapshot, number):
    return hashlib.sha256(f"{snapshot}:{number}".encode()).hexdigest()[:16]


class Builder:
    def __init__(self, snapshot):
        self.snapshot, self.items = snapshot, []

    def add(self, parent, control_type, name="", value="", actions=(), **extra):
        ident = helper_id(self.snapshot, len(self.items))
        self.items.append({"id": ident, "parent": parent, "control_type": control_type, "name": name,
                           "value": value, "actions": list(actions), **extra})
        return ident

    def link(self, parent, name, value):
        item = self.add(parent, "ListItem")
        link = self.add(item, "Hyperlink", name, value, ["invoke", "scroll_into_view"])
        self.add(link, "Text", name)


def title(page, row):
    return (f"Book in {SERIES[row]} A Very Long Title Number {page * 10 + row}: the second part of a "
            f"series, with a subtitle that runs well past the old cap and says what the story is about "
            f"in many more words, Kindle eBook, Live")


def bookshelf(page=1, snapshot=None, nodes=425, shifted=False):
    """The page `page` of 3, with ids from a fresh snapshot, padded with footer links to `nodes` elements.

    `shifted` adds a saved-notice banner (an unnamed Group) before the main group and a "Previous" item
    at the start of the pager, as pages after the first do."""
    out = Builder(snapshot if snapshot is not None else page)
    window = out.add(None, "Window", f"Bookshelf - Chrome {page}", actions=["window_close"])
    chrome = out.add(window, "Pane", "Google Chrome")
    for tab in range(3):
        out.add(chrome, "TabItem", f"Tab {tab}", actions=["select"])
    for button in ("Back", "Forward", "Reload", "Extensions", "Profile", "Menu"):
        out.add(chrome, "Button", button, actions=["invoke"])
    out.add(chrome, "Edit", "Address", URL + f"#{page}", ["set_value"])
    document = out.add(window, "Document", "Amazon Kindle Direct Publishing", URL + f"#{page}")
    banner = out.add(document, "Group", "")
    menu = out.add(banner, "List", "Main menu")
    for number, label in enumerate(("Bookshelf", "Reports", "Community", "Marketing", "Help", "Sign out")):
        out.link(menu, label, f"{URL}/{label.lower().replace(' ', '-')}?ref=nav{number}")
    if shifted:
        out.add(out.add(document, "Group", ""), "Text", "Saved")
    main = out.add(document, "Group", "")
    out.add(main, "Text", "Your Bookshelf")
    out.add(main, "Edit", "Search your books", "", ["set_value"])
    table = out.add(main, "Table", "Your books")
    for row in range(10):
        item = out.add(table, "DataItem", title(page, row), actions=["scroll_into_view"])
        out.add(item, "Text", SERIES[row])
        out.add(item, "Text", "Kindle eBook")
        out.add(item, "Text", "Live")
        for label in ("Edit eBook", "Promote and advertise", "Order author copies"):
            button = out.add(item, "Button", label, actions=["invoke", "scroll_into_view"])
            out.add(button, "Text", label)
    pager = out.add(main, "List", "Pagination")
    if shifted:
        out.link(pager, "Previous", f"{URL}#{page - 1}")
    for number in (1, 2, 3):
        out.link(pager, str(number), f"{URL}#{number}")
    footer = out.add(document, "Group", "")
    for number in range(nodes):
        if len(out.items) + 3 > nodes:
            break
        out.link(footer, f"Footer link {number}", f"{URL}/help/{number}2?ref=footer{number}3")
    while len(out.items) < nodes:
        out.add(footer, "Text", "©")
    return out.items
