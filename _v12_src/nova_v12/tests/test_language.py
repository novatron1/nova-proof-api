import unittest
from nova import NovaAdapter
from nova.language import extract,compare
from nova.meta import MetaModelClient
class TestLanguage(unittest.TestCase):
 def test_roles(self):
  x=extract('Marcus gave his sister $50 yesterday at the store because she needed groceries.')
  self.assertEqual(x['frame']['who'],'Marcus')
  self.assertEqual(x['frame']['what'],'give')
  self.assertEqual(x['frame']['when'],'yesterday')
  self.assertEqual(x['frame']['where'],'store')
  self.assertIn('groceries',x['frame']['why'])
 def test_unknown_not_invented(self):
  x=extract('John purchased a bicycle.')
  self.assertIsNone(x['frame']['how']);self.assertIsNone(x['frame']['when'])
 def test_paraphrase_candidate(self):
  self.assertEqual(compare('The kid bought a bicycle.','The child purchased a bike.')['relation'],'candidate_equivalent')
 def test_unknown_sentence(self):self.assertIsNone(extract('What is this?')['frame']['what'])
 def test_adapter(self):self.assertEqual(NovaAdapter().process({'task':'analyze','text':'John bought a bike.'})['status'],'partial_interpretation')
 def test_model_absent(self):self.assertEqual(NovaAdapter().process({'task':'augment','text':'Hello'})['status'],'model_not_configured')
 def test_mock_model(self):
  calls=[]
  def fake(p):calls.append(p);return 'mock answer'
  r=NovaAdapter(model=fake).process({'task':'augment','text':'John bought a bike.'})
  self.assertEqual(r['answer'],'mock answer');self.assertIn('Original user text',calls[0])
 def test_endpoint_guard(self):
  with self.assertRaises(ValueError):MetaModelClient(base_url='http://example.com/api',model='fake')
if __name__=='__main__':unittest.main()
