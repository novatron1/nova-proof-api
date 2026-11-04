import ast, operator, re, sqlite3, threading
from dataclasses import dataclass, asdict

OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.FloorDiv:operator.floordiv,ast.Mod:operator.mod,ast.Pow:operator.pow}

def calculate(expression):
    def walk(node,depth=0):
        if depth>15: raise ValueError('Expression too deep')
        if isinstance(node,ast.Expression):return walk(node.body,depth+1)
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):return node.value
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            v=walk(node.operand,depth+1);return v if isinstance(node.op,ast.UAdd) else -v
        if isinstance(node,ast.BinOp) and type(node.op) in OPS:
            a,b=walk(node.left,depth+1),walk(node.right,depth+1)
            if type(node.op)==ast.Pow and (abs(b)>10 or abs(a)>1e6):raise ValueError('Exponent too large')
            result=OPS[type(node.op)](a,b)
            if abs(result)>1e15:raise ValueError('Result too large')
            return result
        raise ValueError('Unsupported calculation')
    if len(expression)>120:raise ValueError('Expression too long')
    return walk(ast.parse(expression,mode='eval'))

@dataclass
class Evidence:
    source:str
    statement:str
    kind:str

class _OwnedConnection:
    """Connection owned by exactly one thread; close at thread teardown."""
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute('CREATE TABLE IF NOT EXISTS entries (kind TEXT, term TEXT, meaning TEXT, source TEXT, PRIMARY KEY(kind,term))')
    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
    def __del__(self):
        self.close()

class Knowledge:
    """File-backed, thread-local SQLite dictionary with explicit lifecycle.

    Note: :memory: is per thread and therefore intentionally not shared.
    Use a file-backed database for cross-thread lookups.
    """
    def __init__(self, path=':memory:'):
        self._path = str(path)
        self._local = threading.local()
        self._closed = False
        self._connection()

    def _connection(self):
        if self._closed:
            raise RuntimeError('Knowledge database is closed')
        owner = getattr(self._local, 'owner', None)
        if owner is None:
            owner = _OwnedConnection(self._path)
            self._local.owner = owner
        return owner.db

    @property
    def db(self):
        return self._connection()

    def close(self):
        """Close this thread's connection and prevent future access.

        Worker-thread connections close automatically when their thread exits.
        Close only after worker tasks have completed.
        """
        if not self._closed:
            self._closed = True
            owner = getattr(self._local, 'owner', None)
            if owner is not None:
                owner.close()
                del self._local.owner

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def add(self, kind, term, meaning, source='user-supplied'):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO entries VALUES (?,?,?,?)',
                            (kind, term.lower(), meaning, source))

    def lookup(self, kind, term):
        row = self.db.execute('SELECT meaning,source FROM entries WHERE kind=? AND term=?',
                              (kind, term.lower())).fetchone()
        return {'term':term, 'meaning':row[0], 'source':row[1]} if row else None

class Reasoner:
    def prove(self,facts,rules,goal,max_steps=100):
        known=set(facts);trace=[]
        for _ in range(max_steps):
            changed=False
            for premises,conclusion in rules:
                if all(p in known for p in premises) and conclusion not in known:
                    known.add(conclusion);trace.append({'premises':premises,'conclusion':conclusion});changed=True
            if not changed:
                opposite=('not '+goal) if not goal.startswith('not ') else goal[4:]
                yes,no=goal in known,opposite in known
                verdict='both' if yes and no else 'yes' if yes else 'no' if no else 'unknown'
                return {'verdict':verdict,'complete':True,'trace':trace}
        return {'verdict':'unknown','complete':False,'trace':trace}

class NovaAdapter:
    def __init__(self,model=None,knowledge=None):
        self.model=model;self.knowledge=knowledge or Knowledge();self.reasoner=Reasoner()
    def process(self,request):
        kind=request.get('task');evidence=[]
        if kind=='calculate':
            value=calculate(request['expression']);evidence.append(asdict(Evidence('local-calculator',request['expression'],'computation')))
            return {'status':'verified','answer':value,'evidence':evidence}
        if kind in ('dictionary','encyclopedia'):
            hit=self.knowledge.lookup(kind,request['term'])
            return {'status':'retrieved' if hit else 'unknown','answer':hit,'evidence':[asdict(Evidence(hit['source'],hit['meaning'],'retrieval'))] if hit else []}
        if kind=='prove':
            result=self.reasoner.prove(request.get('facts',[]),request.get('rules',[]),request['goal'])
            return {'status':'verified_logic' if result['complete'] else 'incomplete','answer':result,'evidence':[asdict(Evidence('supplied-premises',str(request.get('facts',[])),'premise'))]}
        if kind=='concept_frame':
            from .concepts import concept_frame
            return {'status':'candidate_interpretation','answer':concept_frame(request['text']),'evidence':[]}
        if kind=='concept_compare':
            from .concepts import compare_frames
            return {'status':'heuristic_comparison','answer':compare_frames(request['a'],request['b']),'evidence':[]}
        if kind=='analyze':
            from .language import extract
            return {'status':'partial_interpretation','answer':extract(request['text']),'evidence':[]}
        if kind=='compare_concepts':
            from .language import compare
            return {'status':'heuristic_comparison','answer':compare(request['a'],request['b']),'evidence':[]}
        if kind=='augment':
            from .language import extract
            parsed=extract(request['text'])
            if self.model is None:return {'status':'model_not_configured','answer':None,'analysis':parsed,'evidence':[]}
            prompt=('Answer the user question carefully. The following is a fallible heuristic analysis, not verified facts. '
                +str(parsed['frame'])+'\nOriginal user text: '+request['text']
                +'\nDo not invent missing roles or causal relationships.')
            return {'status':'unverified_model_output','answer':self.model(prompt),'analysis':parsed,'evidence':[]}
        if kind=='language':
            if self.model is None:return {'status':'model_not_configured','answer':None,'evidence':[]}
            return {'status':'unverified_model_output','answer':self.model(request['text']),'evidence':[]}
        raise ValueError('Unknown task')
