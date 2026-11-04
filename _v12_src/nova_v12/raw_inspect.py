"""Show raw question and NOVA processing with no scoring, model calls, or edits."""
import json
from dataclasses import asdict
from nova.engine import ledger_analysis, CognitiveSystem
questions=[
    'Zoe received $120 from Amir. Zoe gave Ivy $90. How much money does Zoe have left from the $120?',
    'Zoe received $120 from Amir. Zoe gave Ivy $90. Ivy refunded Zoe $20. How much money does Zoe have left from the $120?',
]
for question in questions:
    h=CognitiveSystem().analyze(question)
    print(json.dumps({'original_question':question,'raw_ledger':ledger_analysis(question),
                      'raw_handoff':asdict(h),
                      'model_prompt':CognitiveSystem.build_prompt(h,'full')},indent=2,default=str))
