import unittest
from nova.engine import ledger_analysis, CognitiveSystem
class SafetyV06(unittest.TestCase):
    def test_supported_refund_is_counted(self):
        q='Zoe received $120 from Amir. Zoe gave Ivy $90. Ivy refunded Zoe $20. How much money does Zoe have left from the $120?'
        r=ledger_analysis(q)
        self.assertEqual(r['status'],'VERIFIED')
        self.assertEqual(r['answer'],50)
        self.assertFalse(r['unparsed_events'])
    def test_standard_transaction_still_certified(self):
        q='Zoe received $120 from Amir. Zoe gave Ivy $90. How much money does Zoe have left from the $120?'
        r=ledger_analysis(q)
        self.assertEqual(r['status'],'VERIFIED')
        self.assertEqual(r['answer'],30)
        self.assertEqual(len(r['events']),2)
    def test_unverified_not_forced_into_model(self):
        q='Zoe received $120 from Amir. Zoe gave Ivy $90. Ivy refunded Zoe $20. How much money does Zoe have left from the $120?'
        model=lambda prompt:'MODEL_INDEPENDENT_ANSWER'
        r=CognitiveSystem(model=model).answer(q)
        self.assertEqual(r['answer'],'MODEL_INDEPENDENT_ANSWER')
        self.assertNotIn('verified_answer": 30',r['model_prompt'])
if __name__=='__main__':unittest.main()
