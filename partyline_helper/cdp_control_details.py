"""Batch observations for role-less interactive DOM elements."""
from .cdp_control_layout import LAYOUT
from .cdp_recipes import value
from .cdp_transport import CDPError

# Rendered strings are serialized as quoted CSS strings, optionally with alternative text
# after a slash. Image, counter and quote tokens do not provide a literal displayed string.
CONTROL_DETAILS = r"""function(...others) {
 const style=(e,pseudo)=>e.ownerDocument.defaultView.getComputedStyle(e,pseudo);
 const clean=(s,max=240)=>(s||'').slice(0,1024).replace(/\s+/g,' ').trim().slice(0,max);
 const visible=(s,checkOpacity=true)=>s.display!=='none'&&s.visibility==='visible'&&
   (!checkOpacity||s.opacity!=='0')&&
   s.contentVisibility!=='hidden';
 // Match DOM discovery: a transparent control can still be focusable and actionable.
 function has_control_box(e) {
   const r=e.getBoundingClientRect();
   return r.width>0&&r.height>0&&!['hidden','collapse'].includes(style(e).visibility);
 }
 function shown(e) {
   const r=e.getBoundingClientRect();
   return r.width>0&&r.height>0&&e.checkVisibility({opacityProperty:true,visibilityProperty:true});
 }
 function generated(e,pseudo) {
   const s=style(e,pseudo);
   if(!visible(s)) return '';
   const literal=s.content.slice(0,1024).match(/^(?:"(?:[^"\\]|\\.)*"\s*)+/s)?.[0];
   if(!literal) return '';
   return Array.from(literal.matchAll(/"((?:[^"\\]|\\.)*)"/gs), m=>
     m[1].replace(/\\([0-9a-f]{1,6})(?:\r\n|[\t\n\f\r ])?|\\(.)/gis,(_,hex,char)=>{
       const n=parseInt(hex,16);
       return hex?String.fromCodePoint(n>0&&n<=0x10ffff?n:0xfffd):char;
     })).join('');
 }
 function displayed(e) {
   const parts=[], stack=[e];
   let hint='', size=0, budget=32;
   const append=text=>{if(text){parts.push(text);size+=text.length;}};
   while(stack.length&&budget--&&size<240){
     const n=stack.pop();
     if(n.nodeType===3){append(clean(n.nodeValue));continue;}
     if(Array.isArray(n)){append(generated(n[0],'::after'));continue;}
     if(n.nodeType!==1||['SCRIPT','STYLE','TEMPLATE'].includes(n.tagName)||!visible(style(n),n!==e)) continue;
     if(!hint) hint=clean(n.getAttribute('placeholder'))||clean(n.getAttribute('title'));
     append(generated(n,'::before'));
     stack.push([n]);
     const assigned=n.tagName==='SLOT'?n.assignedNodes():[];
     const children=assigned.length?assigned:(n.shadowRoot||n).childNodes;
     for(let i=Math.min(children.length,budget)-1;i>=0;i--) stack.push(children[i]);
   }
   return clean(parts.join(' '))||hint;
 }
 function popup(e) {
   const types=['menu','listbox','tree','grid','dialog'];
   const declared=e.getAttribute('aria-haspopup');
   if(declared==='true') return 'menu';
   if(types.includes(declared)) return declared;
   if(declared==='false') return '';
   const root=e.getRootNode();
   for(const attr of ['aria-controls','aria-owns']){
     for(const id of (e.getAttribute(attr)||'').slice(0,1024).split(/\s+/,16)){
       const target=id&&root.getElementById(id), role=target&&target.getAttribute('role');
       if(types.includes(role)) return role;
       if(target&&target.hasAttribute('popover')) return 'popover';
       if(target&&(target.tagName==='DIALOG'||role==='alertdialog')) return 'dialog';
     }
   }
   return '';
 }
""" + LAYOUT + r"""
 return [this,...others].map(e=>has_control_box(e)?{hidden:false,short_text:displayed(e),
   ...(semantic(e)??geometry(e)),popup_hint:popup(e)}:{hidden:true});
}"""


def may_need_details(node):
    return not value(node.get("name")) and value(node.get("role")) in (None, "", "generic", "none")


def needs_details(node, dom):
    return (dom.get("document_identity") and may_need_details(node)
            and not (dom.get("role") or dom.get("aria_label") or dom.get("title"))
            and (node.get("dom_discovered") or node.get("dom_interactive") or dom.get("focusable")))


async def read_controls(page, objects):
    result = await page.call("Runtime.callFunctionOn", {
        "objectId": objects[0], "arguments": [{"objectId": obj} for obj in objects[1:]],
        "functionDeclaration": CONTROL_DETAILS, "returnByValue": True,
    })
    details = result.get("result", {}).get("value")
    if (result.get("exceptionDetails") or not isinstance(details, list) or len(details) != len(objects)
            or any(not isinstance(detail, dict) for detail in details)):
        raise CDPError("DOM control observation failed")
    return details
