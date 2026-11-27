"""Idempotent, additive import. Never merges records based on title similarity."""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from contracts.events import ImportBatch
from database.connection import connect
from database.migrate import migrate

SCALARS = ('title','description','source_url','start_date','end_date','reported_year',
 'country_code','city','venue','location_text','client_name','format_text','category',
 'occurrence','score','score_method')

def utc(value):
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')

def now(): return utc(datetime.now(timezone.utc))

def patch(db, table, row_id, values):
    if values:
        db.execute(f'UPDATE {table} SET '+','.join(f'{k}=?' for k in values)+' WHERE id=?',
                   (*values.values(),row_id))

def save_event(db, event, producer, collected):
    data=event.model_dump(mode='json')
    source=db.execute('SELECT event_id,last_collected_at FROM event_sources WHERE producer=? AND source_record_id=?',
                      (producer,event.source_record_id)).fetchone()
    conflicts=[]
    if source:
        eid=source['event_id']
        if collected < source['last_collected_at']:
            return eid,'stale',conflicts
        stored=db.execute('SELECT * FROM events WHERE id=?',(eid,)).fetchone()
        changes={}
        for field in SCALARS:
            incoming=data[field]
            if incoming is None or (field=='occurrence' and incoming=='unknown'): continue
            if incoming==stored[field]: continue
            if stored[field] is None and stored['reviewed_at'] is None and stored['moderation_status']=='draft':
                changes[field]=incoming
            else:
                conflicts.append(field)
        # An unknown occurrence may be filled only on an unreviewed draft.
        if stored['occurrence']=='unknown' and data['occurrence']!='unknown' and stored['reviewed_at'] is None and stored['moderation_status']=='draft':
            changes['occurrence']=data['occurrence']
            if 'occurrence' in conflicts: conflicts.remove('occurrence')
        # Preserve a consistent date pair when a new endpoint conflicts with an existing one.
        start=changes.get('start_date',stored['start_date']);end=changes.get('end_date',stored['end_date'])
        if start and end and end < start:
            for key in ('start_date','end_date'):
                if key in changes: changes.pop(key);conflicts.append(key)
        before=db.total_changes
        patch(db,'events',eid,changes)
        added=False
    else:
        eid=str(uuid4());before=db.total_changes;added=True
        db.execute('INSERT INTO events(id,'+','.join(SCALARS)+') VALUES('+','.join('?' for _ in range(len(SCALARS)+1))+')',
                   (eid,*(data[k] for k in SCALARS)))
        db.execute('INSERT INTO event_sources VALUES(?,?,?,?)',(producer,event.source_record_id,eid,collected))
    for role, names in [('organizer',event.organizers),('studio',event.studios)]:
        for name in names:
            db.execute('INSERT INTO event_parties VALUES(?,?,?) ON CONFLICT DO NOTHING',(eid,role,name))
    for tag in event.tags:
        db.execute('INSERT INTO tags(kind,slug) VALUES(?,?) ON CONFLICT DO NOTHING',(tag.kind,tag.slug))
        tid=db.execute('SELECT id FROM tags WHERE kind=? AND slug=?',(tag.kind,tag.slug)).fetchone()[0]
        db.execute('INSERT INTO event_tags VALUES(?,?) ON CONFLICT DO NOTHING',(eid,tid))
    proof_ids={}
    for proof in event.proofs:
        url=str(proof.url)
        old=db.execute('SELECT * FROM event_proofs WHERE event_id=? AND url=?',(eid,url)).fetchone()
        values=proof.model_dump(mode='json',exclude={'url'})
        values['checked_at']=utc(proof.checked_at) if proof.checked_at else None
        if old:
            changes={}
            if old['reviewed_at'] is None:
                if old['title'] is None and proof.title: changes['title']=proof.title
                if old['kind']=='other' and proof.kind!='other': changes['kind']=proof.kind
                if old['relevance']=='unreviewed' and proof.relevance=='automatic_match': changes['relevance']=proof.relevance
            if values['checked_at'] and (not old['checked_at'] or values['checked_at']>old['checked_at']):
                changes.update({k:values[k] for k in ('checked_at','http_status','error')})
            patch(db,'event_proofs',old['id'],changes);proof_ids[url]=old['id']
        else:
            proof_ids[url]=db.execute('INSERT INTO event_proofs(event_id,url,'+','.join(values)+') VALUES('+','.join('?' for _ in range(len(values)+2))+')',
                                    (eid,url,*values.values())).lastrowid
    for claim in event.claims:
        db.execute('INSERT INTO event_claims(event_id,field,value) VALUES(?,?,?) ON CONFLICT DO NOTHING',(eid,claim.field,claim.value))
        cid=db.execute('SELECT id FROM event_claims WHERE event_id=? AND field=? AND value=?',(eid,claim.field,claim.value)).fetchone()[0]
        for evidence in claim.evidence:
            db.execute('INSERT INTO claim_evidence VALUES(?,?,?,?) ON CONFLICT DO NOTHING',
                       (eid,cid,proof_ids[str(evidence.url)],evidence.quote))
    outcome='added' if added else ('updated' if db.total_changes>before else 'unchanged')
    if outcome=='updated': patch(db,'events',eid,{'updated_at':now()})
    db.execute('UPDATE event_sources SET last_collected_at=? WHERE producer=? AND source_record_id=?',
               (collected,producer,event.source_record_id))
    return eid,outcome,sorted(set(conflicts))

def import_batch(payload, path=None):
    # Validate the entire batch before any event mutation; revalidate model instances too.
    batch=ImportBatch.model_validate(payload.model_dump() if isinstance(payload,ImportBatch) else payload)
    migrate(path)
    run_id=str(uuid4());collected=utc(batch.collected_at)
    with connect(path) as db:
        db.execute('INSERT INTO import_runs(id,producer,schema_version,started_at) VALUES(?,?,?,?)',
                   (run_id,batch.producer,batch.schema_version,now()))
    counts=dict(added=0,updated=0,unchanged=0,stale=0,conflicts=0)
    try:
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            for event in batch.events:
                eid,outcome,conflicts=save_event(db,event,batch.producer,collected)
                counts[outcome]+=1;counts['conflicts']+=len(conflicts)
                db.execute('INSERT INTO import_records VALUES(?,?,?,?,?,?)',
                           (run_id,event.source_record_id,eid,outcome,event.model_dump_json(),json.dumps(conflicts)))
            db.execute("UPDATE import_runs SET status='succeeded',finished_at=?,added_count=?,updated_count=? WHERE id=?",
                       (now(),counts['added'],counts['updated'],run_id))
    except Exception as exc:
        with connect(path) as db:
            db.execute("UPDATE import_runs SET status='failed',finished_at=?,rejected_count=?,error=? WHERE id=?",
                       (now(),len(batch.events),type(exc).__name__,run_id))
        raise
    return dict(run_id=run_id,**counts)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file',type=Path)
    parser.add_argument('--db',type=Path,help='Alternative SQLite file (e.g. a separate demo database)')
    args=parser.parse_args()
    try:
        result=import_batch(json.loads(args.file.read_text(encoding='utf-8-sig')),args.db)
    except (OSError,ValueError,sqlite3.Error) as exc:
        parser.exit(1,f'Import failed: {exc}\n')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
