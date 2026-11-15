"""Read-only DOM observations and native select keyboard planning."""
STATE = r"""function() {
 if(!this.getBoundingClientRect) return {};
 const e=this, r=e.getBoundingClientRect();
 const aria=e.closest('[aria-disabled="true"]');
 const inert=e.closest('[inert]');
 const disabled=e.matches(':disabled');
 const password=e.tagName==='INPUT' && e.type==='password';
 const pointHit=(()=>{const x=r.x+r.width/2,y=r.y+r.height/2;
     const composedContains=(ancestor,node)=>{for(let n=node;n;){if(n===ancestor)return true;
       n=n.assignedSlot||n.parentNode||(n.host||null);}return false;};
     if(x<0||y<0||x>=innerWidth||y>=innerHeight)
       return {hit:false,reason:'outside viewport'};
     let n=e.ownerDocument.elementFromPoint(x,y);
     while(n&&n.shadowRoot){const inner=n.shadowRoot.elementFromPoint(x,y);
       if(!inner||inner===n)break;n=inner;}
     if(!n)return {hit:false,reason:'outside viewport'};
     if(n===e||composedContains(e,n))return {hit:true};
     let root=e.getRootNode();
     while(root&&root.host){if(root.mode==='closed'&&root.host===n)return {hit:true};
       root=root.host.getRootNode();}
     if(n.tagName==='SLOT'&&composedContains(n,e))return {hit:true};
     const name=(n.getAttribute('aria-label')||n.getAttribute('title')||n.innerText||n.textContent||'')
       .trim().slice(0,120);
     return {hit:false,reason:'covered by '+n.tagName+(name?' "'+name+'"':'')};})();
 return {native_disabled:disabled, aria_disabled:!!aria, readonly:!!e.readOnly,
   inert:!!inert, value:password?null:('value' in e?String(e.value).slice(0,600):null),
   password, checked:'checked' in e?e.checked:null, selected:'selected' in e?e.selected:null,
   selected_index:e.tagName==='SELECT'?e.selectedIndex:null,
   selected_count:e.tagName==='SELECT'?e.selectedOptions.length:null,
   tag:e.tagName, type:e.type, focused: (()=>{let a=e.ownerDocument.activeElement;
     while(a&&a.shadowRoot&&a.shadowRoot.activeElement) a=a.shadowRoot.activeElement;
     return a===e;})(),
   files:e.tagName==='INPUT' && e.type==='file'?Array.from(e.files, f=>f.name):null,
   file_count:e.tagName==='INPUT' && e.type==='file'?e.files.length:null,
   bounds:[r.left,r.top,r.right,r.bottom],
   hit:pointHit.hit, hit_reason:pointHit.reason};
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
         "tab": "TabItem", "tablist": "Tab", "menu": "Menu", "menuitem": "MenuItem"}


def value(item):
    return item.get("value") if isinstance(item, dict) else item


def normalize(node, ident, parent, dom=None):
    dom = dom or {}
    props = {p["name"]: value(p.get("value")) for p in node.get("properties", [])}
    role = ROLES.get(value(node.get("role")), "Group")
    evidence = [name for name in ("native_disabled", "aria_disabled", "inert") if dom.get(name)]
    if props.get("disabled"):
        evidence.append("AX.disabled")
    item = {"id": ident, "provider_identity": ident, "source": "cdp", "parent": parent,
            "control_type": role, "name": str(value(node.get("name")) or "")[:1000],
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
        if role in ("Hyperlink", "Button", "MenuItem", "TabItem", "RadioButton", "ListItem"):
            actions.append("invoke")
        if dom.get("tag") == "INPUT" and dom.get("type") == "file":
            actions.append("set_files")
        if (role in ("Edit", "ComboBox") and not dom.get("readonly") and not dom.get("password")
                and dom.get("tag") != "SELECT"):
            actions.append("set_value")
        if role == "CheckBox":
            actions.append("toggle")
        if role in ("ComboBox", "ListItem"):
            actions.append("select")
    item["actions"] = actions
    return item
