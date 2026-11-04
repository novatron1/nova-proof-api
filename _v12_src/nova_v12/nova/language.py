"""Conservative, auditable 5W1H extraction; not a general natural-language parser."""
import re
from dataclasses import dataclass, asdict

VERBS={'gave':'give','gives':'give','give':'give','bought':'purchase','purchased':'purchase','buy':'purchase','buys':'purchase','sent':'send','sends':'send','paid':'pay','pays':'pay','approached':'approach','approaches':'approach','left':'leave','visited':'visit','visits':'visit','carried':'carry','carries':'carry'}
ALIASES={'kid':'child','kids':'child','bicycle':'bike','bicycles':'bike','automobile':'car','vehicle':'car','purchased':'purchase','bought':'purchase','buy':'purchase','buys':'purchase','scared':'afraid','frightened':'afraid'}
MONTHS='January February March April May June July August September October November December'.split()
DATE=r'\b(?:yesterday|today|tomorrow|last night|this morning|on (?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|on (?:'+ '|'.join(MONTHS)+r')\s+\d{1,2})\b'
PLACE=r'\b(?:at|in|inside|near)\s+(?:the\s+)?([\w-]+(?:\s+[\w-]+){0,3})'
STOP={'the','a','an','his','her','their'}

def normalize(token):
    t=token.lower().strip('.,!?;:')
    return ALIASES.get(t,t)

def extract(text):
    original=text.strip()
    # Preserve original text and unknowns; do not invent missing causal/method details.
    sentence=re.sub(r'\s+',' ',original)
    tm=re.search(DATE,sentence,re.I)
    cause=re.search(r'\b(?:because|since)\s+(.+?)(?:[.!?]|$)',sentence,re.I)
    method=re.search(r'\b(?:by|using)\s+(.+?)(?:\s+(?:because|at|in|on)\b|[.!?]|$)',sentence,re.I)
    loc=re.search(PLACE,sentence,re.I)
    # Require recognizable event verb and an overt preceding subject.
    words=list(re.finditer(r"\b[\w'-]+\b",sentence))
    vi=next((i for i,w in enumerate(words) if w.group().lower() in VERBS),None)
    who=what=whom=None
    if vi is not None and vi>0:
        prefix=[w.group() for w in words[:vi]]
        prefix=[w for w in prefix if w.lower() not in STOP and not re.fullmatch(DATE,w,re.I)]
        who=prefix[-1] if prefix else None
        what=VERBS[words[vi].group().lower()]
        tail=sentence[words[vi].end():]
        tail=re.split(r'\b(?:because|since|yesterday|today|tomorrow|at|in|on|using|by)\b',tail,maxsplit=1,flags=re.I)[0].strip(' .,!?')
        whom=tail or None
    frame={'who':who,'what':what,'to_whom_or_object':whom,'when':tm.group() if tm else None,
           'where':re.split(r'\b(?:because|since|when|while|yesterday|today|tomorrow)\b',loc.group(1),maxsplit=1,flags=re.I)[0].strip() if loc else None,'why':cause.group(1).strip() if cause else None,
           'how':method.group(1).strip() if method else None}
    # Ambiguous surface strings are deliberately not certified as exact semantics.
    return {'original':original,'frame':frame,'concept':{'actor':normalize(who) if who else None,
            'action':what,'patient_tokens':[normalize(x) for x in re.findall(r"\b[\w'-]+\b",whom or '')]},
            'coverage':sum(v is not None for v in frame.values()),'status':'partial_interpretation',
            'warnings':['Heuristic extraction; roles, word senses and causal links require independent validation.']}

def compare(a,b):
    x,y=extract(a)['concept'],extract(b)['concept']
    if not x['action'] or not y['action']: return {'relation':'unknown','reason':'event extraction incomplete'}
    if x==y:return {'relation':'candidate_equivalent','reason':'normalized surface concepts match; not a semantic proof'}
    return {'relation':'undetermined','reason':'concepts differ; not necessarily contradictory'}
