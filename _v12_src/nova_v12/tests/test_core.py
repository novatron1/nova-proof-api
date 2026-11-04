import unittest
from nova import NovaAdapter,Knowledge,calculate
class TestCore(unittest.TestCase):
 def test_math(self):self.assertEqual(calculate('15*120*8'),14400)
 def test_reject_code(self):
  with self.assertRaises(ValueError):calculate('__import__("os").system("echo hi")')
 def test_dictionary(self):
  k=Knowledge();k.add('dictionary','purchase','obtain in exchange for payment','local-test')
  self.assertEqual(NovaAdapter(knowledge=k).process({'task':'dictionary','term':'purchase'})['answer']['meaning'],'obtain in exchange for payment')
 def test_reason(self):
  r=NovaAdapter().process({'task':'prove','facts':['human(socrates)'],'rules':[[['human(socrates)'],'mortal(socrates)']],'goal':'mortal(socrates)'})
  self.assertEqual(r['answer']['verdict'],'yes')
 def test_unknown(self):
  r=NovaAdapter().process({'task':'prove','facts':[],'rules':[],'goal':'x'})
  self.assertEqual(r['answer']['verdict'],'unknown')
 def test_no_model(self):self.assertEqual(NovaAdapter().process({'task':'language','text':'hello'})['status'],'model_not_configured')
if __name__=='__main__':unittest.main()
