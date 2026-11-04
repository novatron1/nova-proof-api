"""Run: python demo_v04.py (no paid calls or model required)."""
import json
from nova.engine import CognitiveSystem

nova=CognitiveSystem()
for q in [
 'Zoe received $120 from Amir. Zoe gave Ivy $90. Noor gave $55 to Amir. How much money does Zoe have left from the $120?',
 'She runs the studio.',
 'What is the capital of France?',
]:
    result=nova.answer(q,mode='independent')
    print(json.dumps({'question':q,'state':result['state'],'answer':result['answer'],
                      'lexical':result['package']['lexical']},indent=2))
