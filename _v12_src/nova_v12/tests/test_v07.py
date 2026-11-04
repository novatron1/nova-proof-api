import unittest
from nova.engine import CognitiveSystem
class LexicalRouting(unittest.TestCase):
    def setUp(self): self.n=CognitiveSystem()
    def test_relinquish(self):
        r=self.n.answer('What does relinquish mean?',mode='independent')
        self.assertEqual((r['state'],r['answer']),('LEXICAL','give up possession or control'))
    def test_runs_context(self):
        r=self.n.answer('What does runs mean in “She runs the studio”?',mode='independent')
        self.assertEqual((r['state'],r['answer']),('LEXICAL','manage or operate'))
    def test_ambiguous_run(self):
        r=self.n.answer('What does run mean?',mode='independent')
        self.assertEqual(r['state'],'AMBIGUOUS')
    def test_ledger_frame_no_fake_actor(self):
        r=self.n.answer('Zoe received $120 from Amir. Zoe gave Ivy $90. How much money does Zoe have left from the $120?',mode='independent')
        self.assertEqual(r['package']['concepts']['slots']['events'][0]['giver'],'Amir')
    def test_lexical_not_certified_as_proof(self):
        r=self.n.answer('What does relinquish mean?',mode='independent')
        self.assertNotEqual(r['state'],'VERIFIED')
