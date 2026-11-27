"""Export a single-file, offline snapshot of the curated catalogue, not the collector."""
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import json
import re

from database.connection import connect
from services.catalogue import collection_status, detail, filter_options, list_events, parse_filters
from services.showcase import ROOT, load_preview

OFFLINE = r"""
const archiveSnapshot=JSON.parse(document.querySelector('#editorial-snapshot').textContent);
const missingArchiveRoute=()=>{throw new Error('Раздел отсутствует в автономной копии')};
async function get(url){
 const u=new URL(url,'http://offline.invalid'),q=u.searchParams, p=u.pathname;
 if(p==='/api/info')return {visibility:'published_only'};
 if(p==='/api/filters')return archiveSnapshot.filters;
 if(p==='/api/collection-status')return archiveSnapshot.status;
 if(p.startsWith('/api/events/'))return archiveSnapshot.details[decodeURIComponent(p.split('/').pop())]||missingArchiveRoute();
 if(p==='/api/events'){
  const items=offlineRows(q),page=Number(q.get('page')||1),n=Number(q.get('per_page')||20);
  return {items:items.slice((page-1)*n,page*n),total:items.length,page,per_page:n};
 }
 return missingArchiveRoute();
}
function offlineRows(q){
 const terms=(q.get('q')||'').toLocaleLowerCase().match(/[\p{L}\p{N}_]+/gu)||[];
 return archiveSnapshot.rows.filter(row=>{
  const c=archiveSnapshot.details[row.id];
  const haystack=new Set((row.title+' '+row.description).toLocaleLowerCase().match(/[\p{L}\p{N}_]+/gu)||[]);
  return terms.every(t=>haystack.has(t))
   && (!q.has('country')||q.get('country')===row.country_code)
   && (!q.has('year')||Number(q.get('year'))===row.reported_year)
   && (!q.has('tag')||c.tags.some(t=>t.slug===q.get('tag')))
   && (!q.has('has_video')||(q.get('has_video')==='true')===Boolean(row.has_video))
   && (!q.has('has_mechanism')||(q.get('has_mechanism')==='true')===Boolean(row.has_mechanism));
 });
}
document.addEventListener('click',e=>{
 const a=e.target.closest('a[href^="/api/"]');if(!a)return;
 e.preventDefault();
 const u=new URL(a.getAttribute('href'),'http://offline.invalid'),fmt=u.searchParams.get('format')||'json';
 const rows=offlineRows(u.searchParams).map(r=>archiveSnapshot.details[r.id]);
 const cols=['id','title','description','country_code','city','reported_year','source_url'];
 const csv=v=>{let x=String(v??'');if(/^[\s]*[=+@-]/.test(x))x="'"+x;return '"'+x.replaceAll('"','""')+'"'};
 const content=fmt==='csv'?'\ufeff'+cols.join(',')+'\r\n'+rows.map(r=>cols.map(k=>csv(r[k])).join(',')).join('\r\n'):JSON.stringify(rows,null,2);
 const blob=new Blob([content],{type:fmt==='csv'?'text/csv;charset=utf-8':'application/json'});
 const href=URL.createObjectURL(blob),dl=document.createElement('a');dl.href=href;dl.download='immersive-cases.'+fmt;dl.click();setTimeout(()=>URL.revokeObjectURL(href),1000);
});
"""

def export_to(output):
    with TemporaryDirectory() as tmp:
        path=Path(tmp)/'showcase.sqlite3'
        load_preview(path)
        with connect(path) as db:
            rows=list_events(db,parse_filters({}),export=True)['items']
            payload=dict(rows=rows,details={r['id']:detail(db,r['id']) for r in rows},
                         filters=filter_options(db),status=collection_status(db))
    web=ROOT/'web'
    html=(web/'index.html').read_text(encoding='utf-8')
    css=(web/'static/style.css').read_text(encoding='utf-8')
    js=(web/'static/catalogue.js').read_text(encoding='utf-8')
    menu=(web/'static/menu.js').read_text(encoding='utf-8')
    js,n=re.subn(r'^async function get\(url\)\{[^\n]*\}',lambda _:OFFLINE,js,flags=re.M)
    if n!=1:
        raise ValueError('Expected one catalogue data provider')
    # File browsing may disallow history.replaceState on file URLs. Filtering need not change the URL.
    js=js.replace("history.replaceState(null,'',location.pathname", "if(location.protocol!=='file:')history.replaceState(null,'',location.pathname")
    html=re.sub(r'<link[^>]+fonts\.google[^>]+>','',html)
    html=html.replace('href="/"','href="#title"')
    html=html.replace('<link rel="stylesheet" href="/static/style.css">','<style>'+css+'</style>')
    html=html.replace('<script src="/static/menu.js" defer></script>','')
    html=html.replace('<script src="/static/catalogue.js" defer></script>','')
    html=html.replace('Международная подборка','Международная подборка / Автономная копия')
    data=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')
    html=html.replace('</body>','<script type="application/json" id="editorial-snapshot">'+data+
                      '</script>\n<script>'+menu+'\n'+js+'</script>\n</body>')
    Path(output).write_text(html,encoding='utf-8')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('output',type=Path)
    export_to(p.parse_args().output)
