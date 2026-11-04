"""Local development HTTP API; no auth, not for public exposure."""
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from .core import NovaAdapter
from .meta import MetaModelClient

def serve(host='127.0.0.1',port=8765,model=None):
    adapter=NovaAdapter(model=model)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path!='/health':self.send_error(404);return
            self.reply(200,{'status':'ok','model_configured':adapter.model is not None})
        def do_POST(self):
            if self.path!='/process':self.send_error(404);return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=16384:raise ValueError('Request must be 1–16384 bytes')
                request=json.loads(self.rfile.read(length))
                result=adapter.process(request)
                self.reply(200,result)
            except (ValueError,KeyError,TypeError,ZeroDivisionError) as e:self.reply(400,{'error':str(e)})
            except Exception:self.reply(502,{'error':'Processing failed'})
        def reply(self,status,body):
            raw=json.dumps(body).encode()
            self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    ThreadingHTTPServer((host,port),Handler).serve_forever()
if __name__=='__main__':
    import os
    model=MetaModelClient() if os.getenv('NOVA_MODEL_ENDPOINT') else None
    serve(model=model)
