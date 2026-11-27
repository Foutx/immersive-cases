"""WSGI API. Run locally: python -m api.app (no third-party packages)."""
import argparse
import csv
import io
import json
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server
from database.connection import connect
from database.migrate import migrate
from services.catalogue import parse_filters,list_events,detail,filter_options,collection_status


def create_app(db_path=None,include_drafts=False):
    def application(environ,start_response):
        assets = {'/': ('index.html', 'text/html'), '/static/style.css': ('static/style.css', 'text/css'),
                  '/static/menu.js': ('static/menu.js', 'text/javascript'),
                  '/static/catalogue.js': ('static/catalogue.js', 'text/javascript')}
        route = environ.get('PATH_INFO', '/')
        if environ.get('REQUEST_METHOD') == 'GET' and route in assets:
            file, mime = assets[route]
            try:
                body = (Path(__file__).resolve().parents[1] / 'web' / file).read_bytes()
            except OSError:
                start_response('503 Service Unavailable', [('Content-Type', 'text/plain')])
                return [b'Website assets unavailable']
            start_response('200 OK', [('Content-Type', mime + '; charset=utf-8'),
                ('Content-Length', str(len(body))), ('X-Content-Type-Options', 'nosniff'),
                ('Cache-Control', 'no-store')])
            return [body]
        headers=[('Content-Type','application/json; charset=utf-8'),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')]
        status='200 OK'
        try:
            if environ.get('REQUEST_METHOD')!='GET':
                status='405 Method Not Allowed';headers.append(('Allow','GET'));payload={'error':'Read-only API: use GET'}
            else:
                pairs=parse_qs(environ.get('QUERY_STRING',''),keep_blank_values=True,max_num_fields=20)
                if any(len(v)!=1 for v in pairs.values()):raise ValueError('Repeated parameters are not supported')
                params={k:v[0] for k,v in pairs.items()}
                path=environ.get('PATH_INFO','/')
                with connect(db_path) as db:
                    db.execute('PRAGMA query_only=ON')
                    db.execute('BEGIN')
                    if path=='/api/info':
                        payload={'name':'Immersive Cases API','visibility':'local_preview_all_statuses' if include_drafts else 'published_only',
                                 'routes':['/api/events','/api/events/{id}','/api/filters','/api/collection-status','/api/export?format=json']}
                    elif path=='/api/events':payload=list_events(db,parse_filters(params),include_drafts)
                    elif path.startswith('/api/events/'):
                        if params:raise ValueError('No parameters supported for event details')
                        payload=detail(db,path[len('/api/events/'):],include_drafts)
                        if payload is None:status='404 Not Found';payload={'error':'Event not found'}
                    elif path=='/api/filters':
                        if params:raise ValueError('No parameters supported for filters')
                        payload=filter_options(db,include_drafts)
                    elif path=='/api/collection-status':
                        if params:raise ValueError('No parameters supported for status')
                        payload=collection_status(db)
                    elif path=='/api/export':
                        fmt=params.pop('format','json')
                        if fmt not in ('json','csv'):raise ValueError('format must be json or csv')
                        if 'page' in params or 'per_page' in params:raise ValueError('Export uses filters, not pagination')
                        records=list_events(db,parse_filters(params),include_drafts,export=True)['items']
                        records=[detail(db,r['id'],include_drafts) for r in records]
                        headers.append(('Content-Disposition',f'attachment; filename="events.{fmt}"'))
                        if fmt=='json':payload=records
                        else:
                            stream=io.StringIO(newline='');cols=['id','title','description','country_code','city','reported_year','source_url']
                            writer=csv.DictWriter(stream,fieldnames=cols);writer.writeheader()
                            for row in records:
                                # Prevent spreadsheet formula execution on untrusted source text.
                                writer.writerow({k:("'"+str(row[k]) if str(row.get(k) or '').lstrip().startswith(('=','+','-','@')) else row.get(k)) for k in cols})
                            payload=stream.getvalue();headers[0]=('Content-Type','text/csv; charset=utf-8')
                    else:status='404 Not Found';payload={'error':'Route not found'}
        except ValueError as exc:status='400 Bad Request';payload={'error':str(exc)}
        except OverflowError as exc:status='413 Content Too Large';payload={'error':str(exc)}
        except (sqlite3.Error,OSError):status='503 Service Unavailable';payload={'error':'Database unavailable. Apply migrations and retry.'}
        body=(payload if isinstance(payload,str) else json.dumps(payload,ensure_ascii=False)).encode('utf-8')
        headers.append(('Content-Length',str(len(body))))
        start_response(status,headers)
        return [body]
    return application


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',help='Alternative SQLite file')
    parser.add_argument('--port',type=int,default=5000)
    parser.add_argument('--include-drafts',action='store_true',help='Local preview of all moderation statuses; never use for public hosting')
    args=parser.parse_args()
    migrate(args.db)
    with make_server('127.0.0.1',args.port,create_app(args.db,args.include_drafts)) as server:
        print(f'API: http://127.0.0.1:{args.port}/ (draft preview: {args.include_drafts})',flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass

if __name__=='__main__':main()
