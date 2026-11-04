import tempfile, os, unittest
from concurrent.futures import ThreadPoolExecutor
from nova.engine import ledger_analysis, CognitiveSystem, lexical_analysis
from nova.core import Knowledge

class V05RegressionTests(unittest.TestCase):
    def test_out_of_order_parser_chronology(self):
        q='Zoe received $120 from Amir. Zoe gave Ivy $90. How much money does Zoe have left from the $120?'
        self.assertEqual(ledger_analysis(q)['answer'],30)
    def test_cents_exact(self):
        q='Zoe received $0.30 from Amir. Zoe gave Ivy $0.20. How much money does Zoe have left from the $0.30?'
        self.assertAlmostEqual(ledger_analysis(q)['answer'],0.10)
    def test_no_multiple_identical_deposits_verification(self):
        q='Zoe received $120 from Amir. Zoe received $120 from Noor. Zoe gave Ivy $90. How much money does Zoe have left from the $120?'
        self.assertNotEqual(ledger_analysis(q)['status'],'VERIFIED')
    def test_self_transfer_not_spending(self):
        q='Zoe received $120 from Amir. Zoe gave Zoe $20. Zoe gave Ivy $90. How much money does Zoe have left from the $120?'
        self.assertEqual(ledger_analysis(q)['answer'],30)
    def test_unknown_is_not_unanswerable(self):
        result=CognitiveSystem(model=lambda prompt:'I can answer independently').answer('What is a quasar?')
        self.assertEqual(result['source'],'model')
        self.assertEqual(result['answer'],'I can answer independently')
        self.assertIn('does NOT mean',result['model_prompt'])
    def test_empty_custom_lexicon(self):
        self.assertEqual(lexical_analysis('She runs the studio',{}),[])
    def test_concepts_does_not_leak_answer(self):
        r=CognitiveSystem(model=lambda prompt:prompt).answer('Zoe received $120 from Amir. Zoe gave Ivy $90. How much money does Zoe have left from the $120?',mode='concepts')
        self.assertIsNone(r['package']['verified_answer'])
        self.assertNotIn('"verified_answer": 30',r['model_prompt'])
    def test_sqlite_threaded_file(self):
        with tempfile.TemporaryDirectory() as td:
            k=Knowledge(os.path.join(td,'lexicon.db'))
            k.add('dictionary','run','move quickly','test')
            with ThreadPoolExecutor(max_workers=4) as ex:
                results=list(ex.map(lambda _:k.lookup('dictionary','run'),range(32)))
            self.assertTrue(all(r and r['meaning']=='move quickly' for r in results))

if __name__=='__main__':unittest.main()
