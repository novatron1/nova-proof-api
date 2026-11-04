import unittest
from nova.engine import CognitiveSystem, lexical_analysis, ledger_analysis

class EngineTests(unittest.TestCase):
 def test_polysemy(self):
  x=lexical_analysis('She runs the studio')
  self.assertEqual(x[0]['contextual_candidates'],['manage or operate'])
 def test_ambiguity(self):
  self.assertTrue(lexical_analysis('They run it')[0]['ambiguous'])
 def test_ledger(self):
  q='Zoe received $120 from Amir. Zoe gave Ivy $90. Noor gave $55 to Amir. How much money does Zoe have left from the $120?'
  self.assertEqual(ledger_analysis(q)['answer'],30)
 def test_self_transfer(self):
  self.assertEqual(ledger_analysis('Zoe received $120 from Amir. Zoe gave Zoe $90. How much money does Zoe have left from the $120?')['answer'],120)
 def test_unknown_does_not_override_model(self):
  model=lambda prompt:'The model can answer this independently.'
  out=CognitiveSystem(model=model).answer('What is the capital of France?')
  self.assertEqual(out['source'],'model')
  self.assertEqual(out['state'],'UNSUPPORTED')
  self.assertIn('does NOT mean',out['model_prompt'])
 def test_model_is_final_voice(self):
  out=CognitiveSystem(model=lambda p:'Zoe has thirty dollars.').answer('Zoe received $120 from Amir. Zoe gave Ivy $90. How much money does Zoe have left from the $120?',mode='full')
  self.assertEqual(out['source'],'model')
  self.assertEqual(out['answer'],'Zoe has thirty dollars.')
 def test_concepts_no_answer_leak(self):
  out=CognitiveSystem(model=lambda p:'response').answer('Zoe received $120 from Amir. Zoe gave Ivy $90. How much money does Zoe have left from the $120?',mode='concepts')
  self.assertIsNone(out['package']['verified_answer'])
  self.assertEqual(out['package']['proof'],[])
 def test_no_model_no_faked_response(self):
  self.assertEqual(CognitiveSystem().answer('Hello')['state'],'MODEL_NOT_CONFIGURED')

if __name__=='__main__':unittest.main()
