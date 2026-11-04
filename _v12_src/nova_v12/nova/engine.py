"""NCA v0.4: independent ledger, lexical assistance and capability-aware handoff.

Pure standard-library implementation. Lexicon is intentionally small, extendable,
not a substitute for licensed WordNet ingestion or the cloud implementation.
"""
import re
import json
from pathlib import Path
from decimal import Decimal
from dataclasses import dataclass, asdict
from .core import NovaAdapter
from .concepts import concept_frame
from .lexical_router import lexical_response

LEXICON={
 'run':[
  {'meaning':'move quickly on foot','synonyms':['sprint','jog'],'cues':['track','race','feet','runner']},
  {'meaning':'manage or operate','synonyms':['manage','operate','direct'],'cues':['studio','business','company','shop']},
  {'meaning':'execute software','synonyms':['execute','launch'],'cues':['python','code','script','program']}],
 'charge':[
  {'meaning':'ask for payment','synonyms':['bill','invoice'],'cues':['fee','price','customer','dollars']},
  {'meaning':'replenish electrical energy','synonyms':['recharge','power'],'cues':['battery','phone','electricity']},
  {'meaning':'formally accuse','synonyms':['accuse','indict'],'cues':['court','crime','prosecutor']}],
 'relinquish':[{'meaning':'give up possession or control','synonyms':['surrender','yield','release'],'antonyms':['retain','keep'],'cues':['control','ownership','rights','possession']}],
 'give':[{'meaning':'transfer possession from giver to recipient','synonyms':['hand','transfer'],'antonyms':['receive'],'cues':['money','dollars','cash']}],
 'borrow':[{'meaning':'receive something temporarily with an obligation to return it','synonyms':['take on loan'],'antonyms':['lend'],'cues':['loan','return','repay']}],
}

def load_lexicon(path):
    """Load a user-provided sense dictionary. Never silently invent senses."""
    raw=json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(raw,dict):raise ValueError('Lexicon must be an object')
    for term,senses in raw.items():
        if not isinstance(term,str) or not isinstance(senses,list) or not senses:
            raise ValueError('Invalid term or empty senses')
        for sense in senses:
            if not isinstance(sense,dict) or not isinstance(sense.get('meaning'),str) or not sense['meaning'].strip():
                raise ValueError('Sense must have a meaning')
            for field in ('synonyms','antonyms','cues'):
                if field in sense and (not isinstance(sense[field],list) or not all(isinstance(v,str) for v in sense[field])):
                    raise ValueError('Invalid sense relation')
    return raw

def semantic_graph(lexical):
    """Expose alternative senses separately, never conflate antonyms and synonyms."""
    nodes=[];edges=[]
    for entry in lexical:
        term=entry['word']
        nodes.append({'id':f'word:{term}','kind':'word','label':term})
        for i,sense in enumerate(entry['senses']):
            sid=f'sense:{term}:{i}'
            nodes.append({'id':sid,'kind':'sense','label':sense['meaning'],
                          'context_hits':sense['context_hits']})
            edges.append({'from':f'word:{term}','to':sid,'relation':'has_sense'})
            for relation in ('synonyms','antonyms'):
                for related in sense[relation]:
                    rid=f'word:{related}'
                    if not any(n['id']==rid for n in nodes):
                        nodes.append({'id':rid,'kind':'related_word','label':related})
                    edges.append({'from':sid,'to':rid,'relation':relation[:-1]})
    return {'nodes':nodes,'edges':edges,'note':'Relationships are lexical candidates, not evidence that a sense is true in context.'}

def lexical_analysis(text,lexicon=None):
    lexicon=LEXICON if lexicon is None else lexicon
    words=set(re.findall(r"[a-z]+",text.lower()))
    results=[]
    for word,senses in lexicon.items():
        # basic inflection support, not full lemmatization
        variants={word,word+'s',word+'ed',word+'ing'}
        if word=='run':variants|={'runs','running','ran'}
        if word=='give':variants|={'gave','gives','given'}
        if not words.intersection(variants):continue
        entries=[]
        for s in senses:
            entries.append({'meaning':s['meaning'],'synonyms':s.get('synonyms',[]),
              'antonyms':s.get('antonyms',[]),'context_hits':sorted(words.intersection(s.get('cues',[])))})
        strongest=max((len(e['context_hits']) for e in entries),default=0)
        winners=[e['meaning'] for e in entries if strongest and len(e['context_hits'])==strongest]
        results.append({'word':word,'senses':entries,'contextual_candidates':winners,
                        'ambiguous':len(winners)!=1})
    return results

TRANSFER=re.compile(r"\b([A-Za-z][\w-]*)\s+(gave|gives|sent|sends|paid|pays)\s+(?:to\s+)?([A-Za-z][\w-]*)\s+\$?(\d+(?:\.\d{1,2})?)\b",re.I)
RECEIVED=re.compile(r"\b([A-Za-z][\w-]*)\s+received\s+\$?(\d+(?:\.\d{1,2})?)\s+from\s+([A-Za-z][\w-]*)\b",re.I)
TRANSFER_TO=re.compile(r"\b([A-Za-z][\w-]*)\s+gave\s+\$?(\d+(?:\.\d{1,2})?)\s+to\s+([A-Za-z][\w-]*)\b",re.I)
REFUNDED=re.compile(r"\b([A-Za-z][\w-]*)\s+(refunded|repaid)\s+([A-Za-z][\w-]*)\s+\$?(\d+(?:\.\d{1,2})?)\b",re.I)
RETURNED_TO=re.compile(r"\b([A-Za-z][\w-]*)\s+returned\s+\$?(\d+(?:\.\d{1,2})?)\s+to\s+([A-Za-z][\w-]*)\b",re.I)
NEGATED_TRANSFER=re.compile(r"\b([A-Za-z][\w-]*)\s+(?:did\s+not|didn't|never)\s+(?:give|send|pay)\s+(?:to\s+)?([A-Za-z][\w-]*)\s+\$?(\d+(?:\.\d{1,2})?)\b",re.I)
SCOPED=re.compile(r"\bhow much(?: money)? does ([A-Za-z][\w-]*) have left from (?:the )?\$?(\d+(?:\.\d{1,2})?)",re.I)

def ledger_analysis(text):
    # Conservative guard: unparsed financial events cannot be silently ignored.
    unparsed = [{'term':m.group(), 'span':[m.start(),m.end()]}
                for m in re.finditer(r"\b(refund(?:ed|s|ing)?|reimburs(?:e|ed|ement)|borrow(?:ed|s)?|lend|lent|repay(?:s|ment|ed)?|return(?:ed|s)?|reverse(?:d|s)?|cancel(?:led|ed|s)?)\b", text, re.I)]
    events=[];seen=set()
    for m in NEGATED_TRANSFER.finditer(text):
        events.append({'giver':m[1],'recipient':m[2],'amount':Decimal(m[3]),'executed':False,'kind':'transfer','_position':m.start(),'_end':m.end()})
        seen.update(range(m.start(),m.end()))
    for regex,mapper in ((REFUNDED,lambda m:(m[1],m[3],m[4])),
                         (RETURNED_TO,lambda m:(m[1],m[3],m[2])),
                         (TRANSFER,lambda m:(m[1],m[3],m[4])),
                         (RECEIVED,lambda m:(m[3],m[1],m[2])),
                         (TRANSFER_TO,lambda m:(m[1],m[3],m[2]))):
        for m in regex.finditer(text):
            # avoid double-counting overlapping parsers
            span=set(range(m.start(),m.end()))
            if span & seen:continue
            seen|=span
            giver,recipient,amount=mapper(m)
            kind='refund' if regex in (REFUNDED,RETURNED_TO) else 'transfer'
            prefix=text[max(0,m.start()-45):m.start()].lower()
            if re.search(r"\b(?:did not|didn't|never|does not|doesn't)\s*$",prefix):
                events.append({'giver':giver,'recipient':recipient,'amount':Decimal(amount),'executed':False,'kind':kind,'_position':m.start(),'_end':m.end()})
            else:events.append({'giver':giver,'recipient':recipient,'amount':Decimal(amount),'executed':True,'kind':kind,'_position':m.start(),'_end':m.end()})
    events.sort(key=lambda e:e['_position'])
    # A refund/repaid transfer is valid only if it returns value from a
    # previous outgoing transfer, without exceeding that transfer.
    refund_issues=[]
    for i,e in enumerate(events):
        if e['kind']!='refund' or not e['executed']:continue
        previously_sent=sum((x['amount'] for x in events[:i] if x['executed'] and
                             x['giver'].casefold()==e['recipient'].casefold() and
                             x['recipient'].casefold()==e['giver'].casefold() and x['kind']=='transfer'),Decimal('0'))
        previously_refunded=sum((x['amount'] for x in events[:i] if x['executed'] and
                                 x['giver'].casefold()==e['giver'].casefold() and
                                 x['recipient'].casefold()==e['recipient'].casefold() and x['kind']=='refund'),Decimal('0'))
        if e['amount']>previously_sent-previously_refunded:
            refund_issues.append({'term':'unmatched_refund','span':[e['_position'],e['_end']]})
    # Only suppress unknown-action warnings when an explicit supported refund
    # event covers the corresponding word.
    unparsed=[u for u in unparsed if not any(e['kind']=='refund' and
               e['_position']<=u['span'][0]<e['_end'] for e in events)]
    unparsed.extend(refund_issues)
    balances={};steps=[]
    for e in events:
        if not e['executed']:steps.append('Negated transfer: no movement');continue
        a,b,n=e['giver'],e['recipient'],e['amount']
        if a.casefold()!=b.casefold():
            balances[a]=balances.get(a,Decimal('0'))-n
            balances[b]=balances.get(b,Decimal('0'))+n
        steps.append(f'{a} {e["kind"]} {n:g} to {b}')
    match=SCOPED.search(text)
    # Do not certify a scoped answer if an additional money-changing clause
    # appears outside parsed events. Track coverage of dollar amounts only in
    # the story, excluding the amount repeated in the final question.
    story=text[:match.start()] if match else text
    uncovered=[]
    for amount_match in re.finditer(r"\$\s*\d+(?:\.\d{1,2})?",story):
        if not any(e['_position'] <= amount_match.start() < e['_end'] for e in events):
            uncovered.append({'text':amount_match.group(),'span':[amount_match.start(),amount_match.end()]})
    # An unmatched money-changing clause cannot be certified just because its
    # numeric amount lacks a dollar sign.
    for m in re.finditer(r'\b(?:found|earned|won|lost|spent|donated|stole|stolen|received|gave|sent|paid|refunded|repaid|returned)\b',story,re.I):
        if not any(e['_position']<=m.start()<e['_end'] for e in events):
            unparsed.append({'term':'unparsed_action','text':m.group(),'span':[m.start(),m.end()]})
    # Monetary clauses with no $ sign still need conservative checks.
    # The parser is a narrow ledger engine, not a universal language parser.
    if re.search(r"\b(?:unless|except|instead of|would have|might have|didn't not|not never)\b",story,re.I):
        unparsed.append({'term':'complex_scope','span':[0,len(story)]})
    if uncovered:
        unparsed.extend({'term':'unmatched_amount','span':x['span'],'text':x['text']} for x in uncovered)
    if unparsed:
        return {'status':'UNSUPPORTED','answer':None,'proof':steps,
                'unparsed_events':unparsed,
                'events':[{**e,'amount':str(e['amount'])} for e in events],
                'balances':{k:float(v) for k,v in balances.items()},
                'scope':'Unparsed financial actions may affect the requested balance; no certified answer.'}
    if match:
        name,initial=match.group(1),Decimal(match.group(2))
        # only valid if the requested starting transfer is explicitly in the story
        matching=[e for e in events if e['recipient'].casefold()==name.casefold() and e['giver'].casefold()!=name.casefold() and e['amount']==initial and e['executed'] and e['kind']=='transfer']
        if len(matching)==1:
            start=events.index(matching[0]); spent=sum((e['amount'] for e in events[start+1:] if e['giver'].casefold()==name.casefold() and e['recipient'].casefold()!=name.casefold() and e['executed'] and e['kind']=='transfer'),Decimal('0'))
            returned=sum((e['amount'] for e in events[start+1:] if e['recipient'].casefold()==name.casefold() and e['kind']=='refund' and e['executed']),Decimal('0'))
            return {'status':'VERIFIED','answer':float(initial-spent+returned),'proof':steps,'balances':{k:float(v) for k,v in balances.items()},'scope':'scoped transfer arithmetic under limited parser assumptions','events':[{**e,'amount':str(e['amount'])} for e in events], 'unparsed_events':[]}
    return {'status':'ASSIST' if events else 'UNSUPPORTED','answer':None,'proof':steps,'balances':{k:float(v) for k,v in balances.items()},
            'scope':'No independently verified answer; balances represent observed net transfers, not starting wealth.', 'events':[{**e,'amount':str(e['amount'])} for e in events], 'unparsed_events':[]}

@dataclass
class Handoff:
    state:str
    original_question:str
    lexical:list
    concepts:dict
    proof:list
    verified_answer:object
    warning:str
    trace:dict=None
    semantic_graph:dict=None

class CognitiveSystem:
    def __init__(self,model=None,lexicon=None,lexicon_path=None):
        self.model=model
        self.base=NovaAdapter(model=model)
        if lexicon is not None and lexicon_path is not None:raise ValueError('Choose lexicon or lexicon_path')
        self.lexicon=load_lexicon(lexicon_path) if lexicon_path is not None else (LEXICON if lexicon is None else lexicon)
    def analyze(self,question):
        lexical=lexical_analysis(question,self.lexicon)
        concepts=concept_frame(question)
        ledger=ledger_analysis(question)
        # Ledger event frames take precedence over unreliable heuristic actor slots.
        # Never silently pass the heuristic's invented actor to a model.
        if ledger['events']:
            concepts['slots']={'events':[{'giver':e['giver'],'recipient':e['recipient'],
                'amount':e['amount'],'executed':e['executed']} for e in ledger['events']]}
            concepts['interpretation_status']='event_parser_partial'
            concepts['warnings'].append('Event parser is limited; unmatched clauses may remain.')
        lex=lexical_response(question,lexical) if not ledger['events'] else None
        state=lex['status'] if lex else ledger['status']
        answer=lex['answer'] if lex else ledger['answer']
        trace={'ledger':ledger,'lexical_routing':lex,'answer_origin':'lexical_demo' if lex else 'ledger',
               'coverage':{'unparsed_events':ledger.get('unparsed_events',[]),
                           'parsed_event_count':len(ledger.get('events',[])),
                           'certification_scope':ledger.get('scope')}}
        return Handoff(state,question,lexical,concepts,ledger['proof'],answer,
          'NOVA has no verified result; this does NOT imply the question is unanswerable.' if state not in ('VERIFIED','LEXICAL') else '',trace,semantic_graph(lexical))
    def answer(self,question,mode='assist'):
        if mode not in ('assist','independent','concepts','full'):raise ValueError('Unknown mode')
        h=self.analyze(question)
        if mode=='independent':return {'source':'nova','state':h.state,'answer':h.verified_answer,'package':asdict(h)}
        if mode=='concepts':
            h=Handoff(h.state,h.original_question,h.lexical,h.concepts,[],None,h.warning)
        if self.model is None:return {'source':'none','state':'MODEL_NOT_CONFIGURED','answer':None,'package':asdict(h)}
        prompt=self.build_prompt(h,mode)
        output=self.model(prompt)
        return {'source':'model','state':h.state,'answer':output,'package':asdict(h),'model_prompt':prompt}
    @staticmethod
    def build_prompt(h,mode):
        import json
        data={'original_question':h.original_question,'lexical_senses':h.lexical,
              'concept_frame':h.concepts,'semantic_graph':h.semantic_graph,'verified_proof':h.proof if mode=='full' and h.state=='VERIFIED' else [],
              'verified_answer':h.verified_answer if mode=='full' and h.state=='VERIFIED' else None,
              'lexical_candidate':h.verified_answer if h.state=='LEXICAL' else None,
              'nova_state':h.state,'nova_authority':'limited-domain evidence; not a verdict on answerability'}
        return ('Answer the original question in your own words. NOVA is an optional assistant, not an authority over your knowledge. '
                'A NOVA UNSUPPORTED or ASSIST state means NOVA lacks a proof; it does NOT mean the answer is unknowable. '
                'Use valid definitions and relevant relations, ignore irrelevant senses, preserve negation. '
                'If there is a verified answer, check it against the question before using it. '
                'If the question genuinely lacks required facts, say so. Never invent missing facts.\n'
                +json.dumps(data,ensure_ascii=False)+'\nYour final answer:')
