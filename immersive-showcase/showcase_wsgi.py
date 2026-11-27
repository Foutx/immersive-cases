from pathlib import Path

PAGE = (Path.home() / 'immersive-showcase' / 'index.html').read_bytes()

def application(environ, start_response):
    method = environ.get('REQUEST_METHOD', 'GET')
    path = environ.get('PATH_INFO', '/')
    if method not in ('GET', 'HEAD'):
        start_response('405 Method Not Allowed', [('Allow', 'GET, HEAD')])
        return []
    if path not in ('/', '/index.html'):
        start_response('404 Not Found', [('Content-Type', 'text/plain')])
        return [] if method == 'HEAD' else [b'Not found']
    start_response('200 OK', [('Content-Type', 'text/html; charset=utf-8'), ('Content-Length', str(len(PAGE))), ('Cache-Control', 'no-cache')])
    return [] if method == 'HEAD' else [PAGE]
