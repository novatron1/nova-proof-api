import json
from nova.engine import CognitiveSystem
nova=CognitiveSystem()
questions=[
'What does relinquish mean?',
'What does runs mean in She runs the studio?',
'What does charge mean when charging a phone battery?',
'Zoe received $120 from Amir. Zoe gave Ivy $90. How much money does Zoe have left from the $120?',
'Eli received $100 from Sam. Eli gave Noah $30. Noah refunded Eli $10. How much money does Eli have left from the $100?',
'Eli received $100 from Sam. Eli earned $20. How much money does Eli have left from the $100?',
'Kai received $100 from Ava. Kai did not give Mia $40. How much money does Kai have left from the $100?',
'Mira received $60 from Ava. Mira gave Mira $20. Mira gave Bo $15. How much money does Mira have left from the $60?',
'What is the capital of France?',
'What does run mean in They run it?'
]
with open('raw_v12_demo.json','w',encoding='utf-8') as f:
 json.dump([{'question':q,**nova.answer(q,mode='independent')} for q in questions],f,indent=2,ensure_ascii=False,default=str)
