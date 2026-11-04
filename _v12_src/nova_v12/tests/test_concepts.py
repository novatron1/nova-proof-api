import unittest
from nova import NovaAdapter
from nova.concepts import concept_frame,compare_frames
class ConceptTests(unittest.TestCase):
 def test_slots(self):
  f=concept_frame('Marcus gave his sister $50 yesterday at the store because she needed groceries.')
  self.assertEqual(f['slots']['who'],'Marcus')
  self.assertIn('how',f['unknown_slots'])
 def test_paraphrase(self):
  r=compare_frames('The kid bought a bicycle.','The child purchased a bike.')
  self.assertEqual(r['relation'],'candidate_equivalent');self.assertFalse(r['certified'])
 def test_negation(self):
  r=compare_frames('John bought a bike.','John did not buy a bike.')
  self.assertFalse(r['certified'])
 def test_unknown(self):
  self.assertEqual(compare_frames('Something happened.','John bought a bike.')['relation'],'unknown')
 def test_adapter(self):
  self.assertEqual(NovaAdapter().process({'task':'concept_frame','text':'John bought a bike.'})['status'],'candidate_interpretation')
 def test_no_false_proof(self):
  self.assertFalse(NovaAdapter().process({'task':'concept_compare','a':'The kid bought a bicycle.','b':'The child purchased a bike.'})['answer']['certified'])
if __name__=='__main__':unittest.main()
