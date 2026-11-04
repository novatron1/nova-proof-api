"""Conservative definition and contextual-sense routing; not an open-domain dictionary."""
import re

def lexical_response(question, lexical):
    q=question.strip()
    direct=re.search(r"\b(?:what does|define|meaning of|what is the meaning of)\s+['\"“‘]?([a-z-]+)['\"”’]?\s+(?:mean\b)?",q,re.I)
    if direct:
        target=direct.group(1).lower()
        for record in lexical:
            if target in ({record['word'],record['word']+'s','runs','ran','running'} if record['word']=='run' else {record['word'],record['word']+'s'}):
                senses=record['senses']
                if len(record['contextual_candidates'])==1:
                    return {'status':'LEXICAL','answer':record['contextual_candidates'][0],'source':'local_demo_lexicon','reason':'unique context-cue match; not independently verified'}
                if len(senses)==1:
                    return {'status':'LEXICAL','answer':senses[0]['meaning'],'source':'local_demo_lexicon','reason':'single listed sense; not independently verified'}
                return {'status':'AMBIGUOUS','answer':None,'source':'local_demo_lexicon','reason':'multiple senses without a resolved context'}
    if re.search(r'\bwhat does\b.*\bmean\b',q,re.I):
        for record in lexical:
            if len(record['contextual_candidates'])==1:
                return {'status':'LEXICAL','answer':record['contextual_candidates'][0],'source':'local_demo_lexicon','reason':'unique context-cue match; not independently verified'}
    return None
