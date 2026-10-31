"use strict";
const packet = JSON.parse(document.getElementById("library-data").textContent);
const original = JSON.stringify(packet.proposal);
let proposal = JSON.parse(original), edits = [], page = 0, selected = null;
const $ = (id) => document.getElementById(id);
const node = (tag, text, cls) => { const el = document.createElement(tag); if(text !== undefined) el.textContent=text; if(cls) el.className=cls; return el; };
const measured = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0;
function size(bytes) {
  if (!measured(bytes)) return "unknown size";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const unit = bytes ? Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1) : 0;
  return `${unit ? (bytes / (1024 ** unit)).toFixed(1) : bytes} ${units[unit]}`;
}
function duration(seconds) {
  if (!measured(seconds)) return "unknown duration";
  if (seconds < 60) return `${Number(seconds.toFixed(2))} s`;
  const rounded = Math.round(seconds), hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60), remainder = String(rounded % 60).padStart(2, "0");
  return hours ? `${hours}h ${String(minutes).padStart(2, "0")}m ${remainder}s` : `${minutes}m ${remainder}s`;
}
$("context").textContent = `${packet.context.root} / Provider: ${packet.context.provider}`;
$("revision").textContent = `${proposal.revision} / ${packet.context.generatedAt}`;
$("import-command").textContent = "Import the exported request with organize propose --request <file> --request-sha256 <reviewed file hash>. Native validation creates a new proposal revision.";
function filtered(){const q=$("query").value.toLocaleLowerCase(), f=$("filter").value;return proposal.actions.filter(a=>(f==="all"||a.status===f)&&`${a.from} ${a.to}`.toLocaleLowerCase().includes(q));}
function choose(a){selected=a.recordingId;render();}
function fileButton(a,current){const b=node("button",current?a.from.split("/").pop():a.to.split("/").pop(),"file");b.type="button";b.setAttribute("aria-pressed",String(selected===a.recordingId));b.append(node("span",a.status,`badge ${a.status}`));b.addEventListener("click",()=>choose(a));return b;}
function folderMetrics(items) {
  const sizes = items.map(a => a.sizeBytes).filter(measured);
  const durations = items.map(a => a.durationSeconds).filter(measured);
  const knownSize = sizes.length ? size(sizes.reduce((total, value) => total + value, 0)) : "unknown size";
  const unknownSizes = sizes.length < items.length ? ` · ${items.length - sizes.length} unknown sizes` : "";
  const knownDuration = durations.length ? `${duration(durations.reduce((total, value) => total + value, 0))} known` : "no known duration";
  const unknownDurations = durations.length < items.length ? ` · ${items.length - durations.length} unknown durations` : "";
  return `${items.length} shown · ${knownSize}${unknownSizes} · ${knownDuration}${unknownDurations}`;
}
function branch(folder, current, depth) {
  const details = node("details", undefined, "folder"), summary = node("summary");
  details.open = true;
  details.dataset.path = folder.path;
  details.style.setProperty("--depth", String(Math.min(depth, 4)));
  summary.append(node("span", `${folder.name}/`, "folder-name"), node("span", folderMetrics(folder.items), "folder-meta"));
  const children = node("div", undefined, "folder-children");
  folder.files.forEach(action => {
    const button = fileButton(action, current);
    button.style.setProperty("--depth", String(Math.min(depth + 1, 4)));
    children.append(button);
  });
  folder.children.forEach(child => children.append(branch(child, current, depth + 1)));
  details.append(summary, children);
  return details;
}
function tree(id, rows, current) {
  const pane = $(id), root = {name: "base-folder", path: "", children: new Map(), files: [], items: []};
  pane.replaceChildren();
  rows.forEach(action => {
    const parts = (current ? action.from : action.to).split("/");
    parts.pop();
    let folder = root;
    folder.items.push(action);
    parts.forEach(name => {
      const path = folder.path ? `${folder.path}/${name}` : name;
      if (!folder.children.has(name)) folder.children.set(name, {name, path, children: new Map(), files: [], items: []});
      folder = folder.children.get(name);
      folder.items.push(action);
    });
    folder.files.push(action);
  });
  if (rows.length) pane.append(branch(root, current, 0));
  else pane.append(node("p", "No recordings match these filters."));
}
function change(edit){edits.push(edit);const a=proposal.actions.find(x=>x.recordingId===edit.recordingId),g=proposal.groups.find(x=>x.id===edit.groupId);if(edit.type==="rename-group"){g.label=edit.label;g.path=edit.label;proposal.actions.filter(x=>x.groupId===g.id&&!['keep','exclude'].includes(x.status)).forEach(x=>{x.to=`${g.path}/${x.from.split('/').pop()}`;x.status='move';});}else if(edit.type==="assign-recording"){a.groupId=g.id;a.to=`${g.path}/${a.from.split('/').pop()}`;a.status='move';}else{a.status=edit.type==='keep-recording'?'keep':'exclude';a.to=a.from;}$("notice").textContent=`${edits.length} unsaved requested changes. Export and import to validate; no files have moved.`;render();}
function inspect(){const box=$("inspector");box.replaceChildren(node("h2","Recording details"));const a=proposal.actions.find(x=>x.recordingId===selected);if(!a){box.append(node("p","Select a recording to inspect exact paths and grouping evidence."));return;}const group=proposal.groups.find(x=>x.id===a.groupId);const dl=node("dl");[['Original path',a.from],['Proposed path',a.to],['Status',a.status],['Evidence',a.reason],['Recording ID',a.recordingId],['Size',size(a.sizeBytes)],['Duration',duration(a.durationSeconds)]].forEach(([k,v])=>{dl.append(node('dt',k),node('dd',v));});box.append(dl);const label=node('label','Assign to folder'),select=node('select');proposal.groups.forEach(g=>{const option=node('option',g.label);option.value=g.id;option.selected=g.id===a.groupId;select.append(option);});label.append(select);box.append(label);const assign=node('button','Assign recording');assign.onclick=()=>change({type:'assign-recording',recordingId:a.recordingId,groupId:select.value});box.append(assign);const rename=node('label','Rename selected group'),input=node('input');input.value=group.label;rename.append(input);const apply=node('button','Request group rename');apply.onclick=()=>change({type:'rename-group',groupId:group.id,label:input.value});box.append(rename,apply);['keep','exclude'].forEach(kind=>{const b=node('button',kind==='keep'?'Keep current location':'Exclude from moves');b.onclick=()=>change({type:`${kind}-recording`,recordingId:a.recordingId});box.append(b);});}
function render(){const rows=filtered(),last=Math.max(0,Math.ceil(rows.length/100)-1);page=Math.min(page,last);const slice=rows.slice(page*100,(page+1)*100);tree('current-tree',slice,true);tree('proposed-tree',slice,false);$('page').textContent=`${slice.length} of ${rows.length} matching recordings shown / Page ${page+1} of ${last+1}`;$('previous').disabled=page===0;$('next').disabled=page===last;const summary=$('summary');summary.replaceChildren();[['Recordings',proposal.actions.length],['Proposed moves',proposal.actions.filter(a=>a.status==='move').length],['Needs review',proposal.actions.filter(a=>['blocked','unresolved'].includes(a.status)).length],['Overwrites allowed',0]].forEach(([label,value])=>{const card=node('div',undefined,'metric');card.append(node('strong',String(value)),node('span',label));summary.append(card);});inspect();}
['query','filter'].forEach(id=>$(id).addEventListener('input',()=>{page=0;render();}));$('previous').onclick=()=>{page--;render();};$('next').onclick=()=>{page++;render();};$('undo').onclick=()=>{proposal=JSON.parse(original);edits=[];$('notice').textContent='Unsaved edits cleared. No source files changed.';render();};
$('export').onclick=()=>{const request={schemaVersion:1,kind:'edits',requestId:crypto.randomUUID(),libraryId:packet.context.libraryId,expectedHeadHash:packet.context.headHash,baseProposalId:proposal.proposalId,baseRevision:proposal.revision,baseProposalHash:packet.context.proposalRef.sha256,edits};const url=URL.createObjectURL(new Blob([JSON.stringify(request,null,2)],{type:'application/json'}));const a=node('a');a.href=url;a.download='library-requested-changes.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};render();
