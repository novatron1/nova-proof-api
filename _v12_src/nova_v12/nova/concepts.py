"""Auditable concept records: no semantic entailment from lexical overlap alone."""
import re
from .language import extract, normalize

NEGATORS={'not','never','no','didnt',"didn't",'doesnt',"doesn't"}

def concept_frame(text):
    base=extract(text)
    words=re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?",text.lower())
    action=base['concept']['action']
    polarity='negative' if any(w in NEGATORS for w in words) else 'positive'
    # Time and source are preserved; lack of evidence is not evidence of absence.
    return {'original':text,'slots':base['frame'],'concept':base['concept'],
            'polarity':polarity,'known_slots':[k for k,v in base['frame'].items() if v is not None],
            'unknown_slots':[k for k,v in base['frame'].items() if v is None],
            'interpretation_status':'candidate' if action else 'insufficient',
            'warnings':base['warnings']+(['Negation detected lexically; scope unverified.'] if polarity=='negative' else [])}

def compare_frames(a,b):
    x,y=concept_frame(a),concept_frame(b)
    c,d=x['concept'],y['concept']
    if not c['action'] or not d['action']:
        return {'relation':'unknown','certified':False,'reason':'missing event parse'}
    if c==d and x['polarity']!=y['polarity']:
        return {'relation':'possible_contradiction','certified':False,'reason':'matching normalized event with opposite surface polarity; negation scope unverified'}
    if c==d and x['polarity']==y['polarity']:
        return {'relation':'candidate_equivalent','certified':False,'reason':'normalized event and polarity match; time, reference, and context may differ'}
    return {'relation':'undetermined','certified':False,'reason':'no safe equivalence or contradiction conclusion'}
