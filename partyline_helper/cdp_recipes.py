"""Read-only DOM observations and native select keyboard planning."""
STATE = r"""function() {
 if(!this.getBoundingClientRect) return {};
 const e=this, r=e.getBoundingClientRect();
 const aria=e.closest('[aria-disabled="true"]');
 const inert=e.closest('[inert]');
 const disabled=e.matches(':disabled');
 const password=e.tagName==='INPUT' && e.type==='password';
 const file=e.tagName==='INPUT' && e.type==='file';
 const ariaSelected=e.getAttribute?.('aria-selected');
 const focusable=e.tabIndex>=0||(!disabled&&e.matches(
   'button,input:not([type="hidden"]),select,textarea,a[href],area[href],summary,iframe,audio[controls],video[controls]'))
   ||e.isContentEditable===true;
 return {focusable, tabindex:e.getAttribute?.('tabindex'), role:e.getAttribute?.('role'),
   aria_label:e.getAttribute?.('aria-label')?.slice(0,240),
   title:e.getAttribute?.('title')?.slice(0,240),
   native_disabled:disabled, aria_disabled:!!aria, readonly:!!e.readOnly,
   inert:!!inert, value:password?null:('value' in e?String(e.value).slice(0,600):null),
   password, checked:'checked' in e?e.checked:null,
   selected:'selected' in e?e.selected:(ariaSelected==null?null:ariaSelected==='true'),
   selected_index:e.tagName==='SELECT'?e.selectedIndex:null,
   selected_count:e.tagName==='SELECT'?e.selectedOptions.length:null,
   tag:e.tagName, type:e.type, focused: (()=>{let a=e.ownerDocument.activeElement;
     for(let i=0;a&&a.shadowRoot&&a.shadowRoot.activeElement&&i<32;i++) a=a.shadowRoot.activeElement;
     return a===e;})(),
   files:e.tagName==='INPUT' && e.type==='file'?Array.from(e.files, f=>f.name):null,
   file_count:e.tagName==='INPUT' && e.type==='file'?e.files.length:null,
   ...(file?{hidden:!r.width||!r.height||['hidden','collapse'].includes(
     e.ownerDocument.defaultView.getComputedStyle(e).visibility)}:{}),
   bounds:[r.left,r.top,r.right,r.bottom]};
}"""
# Action-only: never run per node during reads (layout hit tests and text reads on large
# containers per element exhausted renderer memory on big pages).
HIT = r"""function() {
 if(!this.getBoundingClientRect) return {hit:false,reason:'not an element'};
 const e=this, r=e.getBoundingClientRect();
 return (()=>{const x=r.x+r.width/2,y=r.y+r.height/2;
     const composedContains=(ancestor,node)=>{for(let n=node,i=0;n&&i<512;i++){if(n===ancestor)return true;
       n=n.assignedSlot||n.parentNode||(n.host||null);}return false;};
     if(x<0||y<0||x>=innerWidth||y>=innerHeight)
       return {hit:false,reason:'outside viewport'};
     let n=e.ownerDocument.elementFromPoint(x,y);
     for(let i=0;n&&n.shadowRoot&&i<32;i++){const inner=n.shadowRoot.elementFromPoint(x,y);
       if(!inner||inner===n)break;n=inner;}
     if(!n)return {hit:false,reason:'outside viewport'};
     if(n===e||composedContains(e,n))return {hit:true};
     // A hit on a component host that owns the target counts: either the target lives in the
     // host's shadow tree (open or closed; open roots resolve to the host when the component
     // listens there), or the target is slotted into the host. A real click lands on that host.
     let root=e.getRootNode();
     for(let i=0;root&&root.host&&i<32;i++){if(root.host===n)return {hit:true};
       root=root.host.getRootNode();}
     if((n.tagName==='SLOT'||n.shadowRoot)&&composedContains(n,e))return {hit:true};
     const name=(n.getAttribute('aria-label')||n.getAttribute('title')||'').trim().slice(0,120);
     return {hit:false,reason:'covered by '+n.tagName+(name?' "'+name+'"':'')};})();
}"""
SELECT_PLAN = r"""function(value) {
 if(this.tagName!=='SELECT') return {error:'select requires a SELECT'};
 const options=Array.from(this.options);
 const matches=options.filter(o=>o.label===value || o.value===value);
 const enabled=options.filter(o=>!o.matches(':disabled') && !o.hidden
   && getComputedStyle(o).display!=='none');
 if(matches.length!==1 || !enabled.includes(matches[0]))
   return {error:'option missing, disabled or ambiguous'};
 const target=matches[0], index=options.indexOf(target), current=this.selectedIndex;
 const down=index>current;
 const steps=enabled.filter(o=>{const i=options.indexOf(o);
   return down?i>current && i<=index:i>=index && i<current;}).length;
 if(steps>1000) return {error:'select needs more than 1000 keyboard steps'};
 if(index===current && this.multiple && this.selectedOptions.length!==1)
   return {error:'use explicit option actions to replace a multiple selection'};
 return {index,current,label:target.label.slice(0,160),direction:down?'ArrowDown':'ArrowUp',steps,
   popup:!this.multiple && (this.size||1)===1 && current>=0};
}"""
OBSERVER = r"""(()=>{
 if(globalThis.__partylineObserved) return;
 globalThis.__partylineObserved=true;
 const changed=()=>globalThis.__partylineChange('');
 addEventListener('visibilitychange',()=>globalThis.__partylineChange(document.visibilityState),true);
 new MutationObserver(changed).observe(document,
   {subtree:true,childList:true,attributes:true,characterData:true});
 for(const name of ['input','change','scroll','resize']) addEventListener(name,changed,true);
})()"""

ROLES = {"RootWebArea": "Document", "WebArea": "Document", "link": "Hyperlink", "button": "Button",
         "textbox": "Edit", "searchbox": "Edit", "checkbox": "CheckBox", "radio": "RadioButton",
         "combobox": "ComboBox", "listbox": "List", "option": "ListItem", "heading": "Text",
         "StaticText": "Text", "InlineTextBox": "Text", "generic": "Group", "slider": "Slider",
         "tab": "TabItem", "tablist": "Tab", "menu": "Menu", "menuitem": "MenuItem",
         "menuitemradio": "MenuItem", "menuitemcheckbox": "MenuItem", "switch": "CheckBox",
         "tree": "Tree", "treeitem": "TreeItem", "grid": "DataGrid", "gridcell": "DataItem"}
WIDGET_ROLES = {"option", "menuitem", "menuitemradio", "menuitemcheckbox", "switch", "treeitem"}


def value(item):
    return item.get("value") if isinstance(item, dict) else item


def normalize(node, ident, parent, dom=None):
    dom = dom or {}
    props = {p["name"]: value(p.get("value")) for p in node.get("properties", [])}
    aria_role = value(node.get("role"))
    if aria_role in (None, "generic", "none"):
        aria_role = dom.get("role") or aria_role
    role = ROLES.get(aria_role, "Group")
    widget = aria_role in WIDGET_ROLES or aria_role == "gridcell" and (
        dom.get("focusable") or dom.get("tabindex") is not None
        or props.get("focusable") or "selected" in props or dom.get("selected") is not None)
    name = (value(node.get("name")) or dom.get("aria_label") or dom.get("title")
            or dom.get("short_text") or "")
    evidence = [name for name in ("native_disabled", "aria_disabled", "inert") if dom.get(name)]
    if props.get("disabled"):
        evidence.append("AX.disabled")
    item = {"id": ident, "provider_identity": ident, "source": "cdp", "parent": parent,
            "control_type": role, "name": str(name)[:1000],
            "enabled": not evidence, "disabled_provenance": evidence, "focused": dom.get("focused", False),
            "readonly": dom.get("readonly", False), "inert": dom.get("inert", False),
            "aria_properties": "disabled=true" if dom.get("aria_disabled") else "",
            "viewport_bounds": dom.get("bounds"), "dom": dom}
    if not dom.get("password"):
        text = dom.get("value") if dom.get("value") is not None else value(node.get("value"))
        if text is not None:
            item["value"] = str(text)[:600]
    checked = dom.get("checked") if dom.get("checked") is not None else props.get("checked")
    if checked is not None:
        item["toggle"] = 2 if checked == "mixed" else int(checked in (True, "true"))
    selected = dom.get("selected") if dom.get("selected") is not None else props.get("selected")
    if selected is not None:
        item["selected"] = selected
    actions = []
    if node.get("backendDOMNodeId") and dom.get("tag"):
        actions = ["scroll_into_view", "press"]
        if (role in ("Hyperlink", "Button", "MenuItem", "TabItem", "RadioButton", "ListItem")
                or dom.get("focusable") or widget):
            actions.append("invoke")
        if dom.get("tag") == "INPUT" and dom.get("type") == "file":
            actions.append("set_files")
        if (role in ("Edit", "ComboBox") and not dom.get("readonly") and not dom.get("password")
                and dom.get("tag") != "SELECT"):
            actions.append("set_value")
        if role == "CheckBox":
            actions.append("toggle")
        if role in ("ComboBox", "ListItem") or widget:
            actions.append("select")
    item["actions"] = actions
    if node.get("file_input_discovered"):
        item.update(control_type="FileInput", hidden=bool(dom.get("hidden")), actions=["set_files"])
    return item
