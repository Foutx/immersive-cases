"""Read-only catalogue queries. All user values use SQL parameters."""
import re
from database.connection import connect

ALLOWED={'q','country','year','tag','has_video','has_mechanism','page','per_page'}
MECHANISM = ("EXISTS (SELECT 1 FROM event_claims c JOIN claim_evidence v"
             " ON v.event_id=c.event_id AND v.claim_id=c.id"
             " WHERE c.event_id=e.id AND c.field='immersion_mechanism')")

def parse_filters(params):
    if set(params)-ALLOWED: raise ValueError('Unknown query parameter')
    result={}
    for name in ('page','per_page','year'):
        default={'page':1,'per_page':20,'year':None}[name]
        raw=params.get(name)
        try: value=int(raw) if raw is not None else default
        except (ValueError,TypeError): raise ValueError(f'Invalid {name}') from None
        if value is not None and not ({'page':1,'per_page':1,'year':1800}[name]<=value<={'page':1000000,'per_page':100,'year':2200}[name]):
            raise ValueError(f'Invalid {name}')
        result[name]=value
    country=params.get('country')
    if country and not re.fullmatch('[A-Z]{2}',country): raise ValueError('country must be an uppercase two-letter code')
    result['country']=country
    result['tag']=params.get('tag')
    if result['tag'] and not re.fullmatch('[a-z][a-z0-9_]{0,63}',result['tag']): raise ValueError('Invalid tag')
    video=params.get('has_video')
    if video not in (None,'true','false'): raise ValueError('has_video must be true or false')
    result['has_video']=video
    mechanism=params.get('has_mechanism')
    if mechanism not in (None,'true','false'): raise ValueError('has_mechanism must be true or false')
    result['has_mechanism']=mechanism
    query=params.get('q','').strip()
    if len(query)>300: raise ValueError('Search query is too long')
    result['q']=query
    return result

def where(filters,include_drafts=False):
    clauses=[];values=[]
    if not include_drafts: clauses.append("e.moderation_status='published'")
    for key,column in [('country','country_code'),('year','reported_year')]:
        if filters.get(key) is not None:
            clauses.append(f'e.{column}=?');values.append(filters[key])
    if filters.get('tag'):
        clauses.append('EXISTS (SELECT 1 FROM event_tags et JOIN tags t ON t.id=et.tag_id WHERE et.event_id=e.id AND t.slug=?)');values.append(filters['tag'])
    if filters.get('has_video'):
        clauses.append(('NOT ' if filters['has_video']=='false' else '')+"EXISTS (SELECT 1 FROM event_proofs p WHERE p.event_id=e.id AND p.kind='video')")
    if filters.get('has_mechanism'):
        clauses.append(('NOT ' if filters['has_mechanism']=='false' else '')+MECHANISM)
    if filters.get('q'):
        terms=re.findall(r'\w+',filters['q'],flags=re.UNICODE)
        if not terms: clauses.append('0')
        else:
            clauses.append('e.rowid IN (SELECT rowid FROM events_fts WHERE events_fts MATCH ?)')
            values.append(' AND '.join('"'+t.replace('"','""')+'"' for t in terms))
    return ' AND '.join(clauses) or '1',values

FIELDS='e.id,e.title,e.description,e.country_code,e.city,e.reported_year,e.start_date,e.end_date,e.format_text,e.category,e.moderation_status,e.occurrence,e.score,e.score_method'

def list_events(db,filters,include_drafts=False,export=False):
    clause,values=where(filters,include_drafts)
    total=db.execute('SELECT count(*) FROM events e WHERE '+clause,values).fetchone()[0]
    if export and total>10000: raise OverflowError('Export exceeds 10000 events; narrow filters')
    limit=total if export else filters['per_page'];offset=0 if export else (filters['page']-1)*limit
    rows=db.execute('SELECT '+FIELDS+", EXISTS(SELECT 1 FROM event_proofs p WHERE p.event_id=e.id AND p.kind='video') AS has_video, "+MECHANISM+" AS has_mechanism FROM events e WHERE "+clause+' ORDER BY e.updated_at DESC,e.id LIMIT ? OFFSET ?',(*values,limit,offset)).fetchall()
    return {'items':[dict(row) for row in rows],'total':total,'page':filters['page'],'per_page':filters['per_page']}

def detail(db,event_id,include_drafts=False):
    sql='SELECT * FROM events WHERE id=?'+('' if include_drafts else " AND moderation_status='published'")
    row=db.execute(sql,(event_id,)).fetchone()
    if row is None:return None
    event=dict(row)
    for key in ('reviewed_by',):event.pop(key,None)
    event['proofs']=[dict(r) for r in db.execute('SELECT id,url,kind,title,checked_at,http_status,relevance,reviewed_at FROM event_proofs WHERE event_id=? ORDER BY id',(event_id,))]
    event['tags']=[dict(r) for r in db.execute('SELECT t.kind,t.slug,t.label FROM tags t JOIN event_tags et ON et.tag_id=t.id WHERE et.event_id=? ORDER BY t.kind,t.slug',(event_id,))]
    event['parties']=[dict(r) for r in db.execute('SELECT role,name FROM event_parties WHERE event_id=? ORDER BY role,name',(event_id,))]
    event['claims']=[]
    for claim in db.execute('SELECT id,field,value FROM event_claims WHERE event_id=? ORDER BY id',(event_id,)):
        item=dict(claim)
        item['evidence']=[dict(r) for r in db.execute('SELECT p.url,c.quote FROM claim_evidence c JOIN event_proofs p ON p.id=c.proof_id WHERE c.event_id=? AND c.claim_id=?',(event_id,claim['id']))]
        event['claims'].append(item)
    return event

def filter_options(db,include_drafts=False):
    clause,_=where({},include_drafts)
    return {
      'countries':[r[0] for r in db.execute('SELECT DISTINCT e.country_code FROM events e WHERE '+clause+' AND e.country_code IS NOT NULL ORDER BY 1')],
      'years':[r[0] for r in db.execute('SELECT DISTINCT e.reported_year FROM events e WHERE '+clause+' AND e.reported_year IS NOT NULL ORDER BY 1 DESC')],
      'tags':[dict(r) for r in db.execute('SELECT DISTINCT t.kind,t.slug,t.label FROM tags t JOIN event_tags et ON et.tag_id=t.id JOIN events e ON e.id=et.event_id WHERE '+clause+' ORDER BY t.kind,t.slug')]}

def collection_status(db):
    # Imports are not crawls. Do not label import timestamps as collection dates.
    fields='id,status,started_at,finished_at,added_count,updated_count,rejected_count'
    last=db.execute('SELECT '+fields+' FROM import_runs ORDER BY started_at DESC,id DESC LIMIT 1').fetchone()
    success=db.execute('SELECT '+fields+" FROM import_runs WHERE status='succeeded' ORDER BY finished_at DESC,id DESC LIMIT 1").fetchone()
    return {'last_import':dict(last) if last else None,'last_successful_import':dict(success) if success else None,'last_collection_at':None}
