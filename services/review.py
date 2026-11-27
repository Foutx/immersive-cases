"""Local CLI for reviewing imported cases. No moderation routes on the website."""
import argparse
import json
from pathlib import Path
from database.connection import connect
from database.migrate import migrate
from services.catalogue import detail
from services.import_events import now

def decide(path, event_id, decision, reviewer, reason, immersion_level=None):
    reviewer, reason = reviewer.strip(), reason.strip()
    if not 1 <= len(reviewer) <= 100 or not 1 <= len(reason) <= 1000:
        raise ValueError('Укажите имя (до 100 символов) и причину (до 1000)')
    if decision not in ('published','in_review','rejected'):
        raise ValueError('Неизвестное решение')
    if immersion_level is not None and (decision != 'published' or immersion_level not in (1,2,3,4)):
        raise ValueError('Оценка 1–4 применяется только при одобрении')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        event = detail(db,event_id,True)
        if event is None:
            raise ValueError('Карточка не найдена')
        if decision == 'published':
            present = {c['field'] for c in event['claims'] if c['evidence']}
            if not {'occurred','immersion_mechanism'}.issubset(present):
                raise ValueError('Для одобрения нужны цитаты о факте проведения и механизме погружения')
            if not (event['venue'] or event['location_text'] or (event['city'] and event['country_code'])):
                raise ValueError('Для одобрения нужно место проведения')
        stamped=now()
        db.execute('UPDATE events SET moderation_status=?,reviewed_by=?,reviewed_at=?,updated_at=? WHERE id=?',
                   (decision,reviewer,stamped,stamped,event_id))
        if immersion_level is not None:
            db.execute('UPDATE events SET score=?,score_method=? WHERE id=?',
                       (immersion_level*25,'editorial_immersion_v1',event_id))
        db.execute('INSERT INTO event_reviews(event_id,decision,reviewer,reviewed_at,reason) VALUES(?,?,?,?,?)',
                   (event_id,decision,reviewer,stamped,reason))
    return {'id':event_id,'status':decision}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',required=True,type=Path,help='SQLite file, never inferred')
    sub=p.add_subparsers(dest='action',required=True)
    todo=sub.add_parser('list')
    todo.add_argument('--status',choices=['draft','in_review','published','rejected'],default='draft')
    show=sub.add_parser('show')
    show.add_argument('id')
    for name in ('approve','reject','needs-review'):
        edit=sub.add_parser(name)
        edit.add_argument('id')
        edit.add_argument('--by',required=True)
        edit.add_argument('--reason',required=True)
        if name=='approve':
            edit.add_argument('--level',type=int,choices=range(1,5))
    a=p.parse_args()
    if not a.db.is_file():
        p.error('База не найдена; сначала импортируйте данные')
    migrate(a.db)
    try:
        if a.action=='list':
            with connect(a.db) as db:
                result=[dict(r) for r in db.execute(
                    'SELECT id,title,reported_year,source_url FROM events WHERE moderation_status=? ORDER BY updated_at DESC,id',
                    (a.status,))]
        elif a.action=='show':
            with connect(a.db) as db:
                result=detail(db,a.id,True)
                if result is None:
                    raise ValueError('Карточка не найдена')
                result['reviews']=[dict(r) for r in db.execute(
                    'SELECT decision,reviewer,reviewed_at,reason FROM event_reviews WHERE event_id=? ORDER BY id', (a.id,))]
        else:
            decision={'approve':'published','reject':'rejected','needs-review':'in_review'}[a.action]
            result=decide(a.db,a.id,decision,a.by,a.reason,getattr(a,'level',None))
    except ValueError as exc:
        p.exit(1,f'{exc}\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
