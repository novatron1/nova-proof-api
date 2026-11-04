import unittest
from nova.engine import CognitiveSystem
class SafetyV08(unittest.TestCase):
 def setUp(self): self.n=CognitiveSystem()
 def test_supported_refund_counted(self):
  q='Eli received $100 from Sam. Eli gave Noah $30. Noah refunded Eli $10. How much money does Eli have left from the $100?'
  r=self.n.answer(q,mode='independent'); self.assertEqual(r['state'],'VERIFIED'); self.assertEqual(r['answer'],80)
 def test_unknown_extra_amount(self):
  q='Eli received $100 from Sam. Eli gave Noah $30. Eli found $10. How much money does Eli have left from the $100?'
  r=self.n.answer(q,mode='independent'); self.assertEqual(r['state'],'UNSUPPORTED')
 def test_supported_transfer(self):
  q='Zoe received $120 from Amir. Zoe gave Ivy $90. How much money does Zoe have left from the $120?'
  r=self.n.answer(q,mode='independent'); self.assertEqual(r['answer'],30.0)
 def test_unsupported_not_forced_to_model(self):
  prompts=[]
  n=CognitiveSystem(model=lambda prompt:prompts.append(prompt) or 'My own answer')
  n.answer('What is a refund?',mode='full')
  self.assertIn('does NOT mean the answer is unknowable',prompts[0])
 def test_complex_negation_not_certified(self):
  q='Zoe received $120 from Amir. Zoe gave Ivy $90 unless she changed her mind. How much money does Zoe have left from the $120?'
  self.assertEqual(self.n.answer(q,mode='independent')['state'],'UNSUPPORTED')
