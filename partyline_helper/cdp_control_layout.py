"""Renderer-side table and grid context, shared by the controls in a read."""

LAYOUT = r"""
 const CELL='td,th,[role="cell"],[role="gridcell"],[role="rowheader"],[role="columnheader"]';
 const ROW='tr,[role="row"]';
 const TABLE='table,[role="table"],[role="grid"],[role="treegrid"]';
 const INTERACTIVE='button,input,select,textarea,a[href],[tabindex],[contenteditable],[role="button"]';
 const passive=e=>!e.matches(INTERACTIVE)&&!e.querySelector(INTERACTIVE);
 const tables=new WeakMap(), labels=new WeakMap(), layouts=new WeakMap();
 let geometryBudget=8192;
 const parent=e=>e.assignedSlot||e.parentElement||e.getRootNode().host;
 function ancestor(e, selector) {
   for(let i=0;e&&i<32;i++,e=parent(e)) if(e.matches(selector)) return e;
 }
 function* walk(root, limit) {
   const walker=root.ownerDocument.createTreeWalker(root,1);
   for(let n=walker.nextNode(),i=0;n&&i<limit;n=walker.nextNode(),i++) yield n;
 }
 const rect=e=>e.getBoundingClientRect();
 const centerX=r=>(r.left+r.right)/2, centerY=r=>(r.top+r.bottom)/2;
 function label(e) {
   if(!e) return '';
   if(!labels.has(e)){
     const visible=shown(e), words=visible&&
       (clean(e.getAttribute('aria-label'))||displayed(e)||clean(e.getAttribute('title')));
     labels.set(e,words||'');
   }
   return labels.get(e);
 }
 function rows(table) {
   if(!tables.has(table)){
     const native=table.tagName==='TABLE', byRow=new Map(), columns=[], rowHeaders=[];
     const entries=native?Array.prototype.slice.call(table.rows,0,512):walk(table,8192);
     for(const row of entries){
       if(!native&&(!row.matches(ROW)||ancestor(parent(row),TABLE)!==table)) continue;
       const cells=[], children=native?Array.prototype.slice.call(row.cells,0,128):walk(row,256);
       let index=Number(row.getAttribute('aria-colindex'))||1;
       for(const cell of children){
         if(!native&&(!cell.matches(CELL)||ancestor(parent(cell),ROW)!==row
             ||ancestor(parent(cell),TABLE)!==table)) continue;
         const role=cell.getAttribute('role'), scope=cell.getAttribute('scope');
         const start=Number(cell.getAttribute('aria-colindex'))||index;
         const end=start+(Number(cell.getAttribute('aria-colspan'))||1);
         const rowHeader=role==='rowheader'||scope==='row'||scope==='rowgroup';
         const colHeader=role==='columnheader'||scope==='col'||scope==='colgroup';
         const entry={cell,row,start,end,rowHeader,scope,colHeader,order:byRow.size};
         cells.push(entry);
         if(rowHeader) rowHeaders.push(entry);
         if(!rowHeader&&(colHeader||cell.tagName==='TH')) columns.push(entry);
         index=end;
         if(cells.length===128) break;
       }
       byRow.set(row,cells);
       if(byRow.size===512) break;
     }
     const first=byRow.values().next().value||[];
     // A plain first row can label columns even when its cells are all TDs.
     const implicitColumns=native?
       first.filter(x=>x.cell.tagName==='TD'&&!x.rowHeader&&passive(x.cell)):[];
     tables.set(table,{native,byRow,columns,rowHeaders,implicitColumns});
   }
   return tables.get(table);
 }
 function semantic(e) {
   const cell=ancestor(e,CELL), row=cell&&ancestor(parent(cell),ROW);
   const table=row&&ancestor(parent(row),TABLE);
   if(!table||ancestor(parent(e),TABLE)!==table) return null;
   const {native,byRow,columns,rowHeaders,implicitColumns}=rows(table);
   const cells=byRow.get(row)||[], target=cells.find(x=>x.cell===cell);
   if(!target) return {};
   const box=rect(cell), xCenter=centerX(box);
   const coversColumn=r=>r.left<=xCenter&&xCenter<=r.right;
   const targetIndex=cells.indexOf(target);
   let row_label='', column_header='';
   // HTML IDREFs take precedence when the author assigned the headers directly.
   const ids=(cell.getAttribute('headers')||'').slice(0,1024).split(/\s+/,16);
   for(const id of ids){
     const header=id&&cell.getRootNode().getElementById(id);
     if(!header||!header.matches('th,[role="rowheader"],[role="columnheader"]')
         ||ancestor(header,TABLE)!==table) continue;
     if(header.matches('[scope="row"],[scope="rowgroup"],[role="rowheader"]')||
         (header.tagName==='TH'&&!header.hasAttribute('scope')&&ancestor(header,ROW)===row))
       row_label ||= label(header);
     else column_header ||= label(header);
   }
   if(!row_label){
     const explicit=cells.find((x,i)=>x.cell!==cell&&(x.rowHeader||x.cell.tagName==='TH'&&
       !x.colHeader&&i<targetIndex)&&label(x.cell));
     const spanning=native&&!explicit&&rowHeaders.find(x=>x.order<target.order&&
       ((x.scope==='rowgroup'&&x.row.parentElement===row.parentElement)||
        (rect(x.cell).top<=centerY(box)&&rect(x.cell).bottom>=centerY(box)))&&label(x.cell));
     const first=cells[0];
     row_label=label((explicit||spanning)?.cell)||
       (first&&targetIndex>0&&passive(first.cell)&&label(first.cell))||'';
   }
   if(!column_header){
     let nearest=-1, width=Infinity;
     for(const x of columns){
       if(x.order>=target.order||x.order<nearest) continue;
       const bounds=native&&rect(x.cell);
       const aligned=native?coversColumn(bounds):
         x.start<target.end&&target.start<x.end;
       if(!aligned||!label(x.cell)) continue;
       const span=native?bounds.width:x.end-x.start;
       if(x.order===nearest&&span>=width) continue;
       nearest=x.order;
       width=span;
       column_header=label(x.cell);
     }
   }
   if(!column_header&&target.order>0)
     column_header=label(implicitColumns.find(x=>coversColumn(rect(x.cell)))?.cell);
   return {row_label,column_header};
 }
 function geometry(e) {
   const box=rect(e);
   for(let scope=parent(e),depth=0;scope&&depth<5;scope=parent(scope),depth++){
     if(scope.matches('body,html')&&!['grid','inline-grid'].includes(style(scope).display)) break;
     if(!layouts.has(scope)){
       const candidates=[];
       for(const n of walk(scope,Math.min(1024,geometryBudget))){
         geometryBudget--;
         // A passive text element can label a cell. Text within a control cannot.
         if(!Array.prototype.some.call(Array.prototype.slice.call(n.childNodes,0,16),
             child=>child.nodeType===3&&clean(child.nodeValue))||ancestor(n,INTERACTIVE)||!shown(n)) continue;
         candidates.push([n,rect(n)]);
       }
       layouts.set(scope,candidates);
     }
     let left, above, leftEdge=Infinity, topEdge=Infinity;
     for(const [n,r] of layouts.get(scope)){
       if(n.contains(e)||e.contains(n)) continue;
       if(r.right<=box.left+2&&r.left<leftEdge&&r.top<=centerY(box)&&centerY(box)<=r.bottom){
         left=n;
         leftEdge=r.left;
       }
       const alignedX=(r.left<=centerX(box)&&centerX(box)<=r.right)||
         (box.left<=centerX(r)&&centerX(r)<=box.right);
       if(r.bottom<=box.top+2&&r.top<topEdge&&alignedX){
         above=n;
         topEdge=r.top;
       }
     }
     if(left&&above) return {row_label:label(left),column_header:label(above)};
   }
   return {};
 }
"""
