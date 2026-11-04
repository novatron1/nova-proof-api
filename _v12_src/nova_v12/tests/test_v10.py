import unittest
from nova.engine import ledger_analysis, CognitiveSystem

class TransactionV10(unittest.TestCase):
    def q(self, story):
        return story+' How much money does Eli have left from the $100?'
    def test_refund(self):
        r=ledger_analysis(self.q('Eli received $100 from Sam. Eli gave Noah $30. Noah refunded Eli $10.'))
        self.assertEqual((r['status'],r['answer']),('VERIFIED',80.0))
    def test_returned_to(self):
        r=ledger_analysis(self.q('Eli received $100 from Sam. Eli gave Noah $30. Noah returned $10 to Eli.'))
        self.assertEqual((r['status'],r['answer']),('VERIFIED',80.0))
    def test_repaid(self):
        r=ledger_analysis(self.q('Eli received $100 from Sam. Eli gave Noah $30. Noah repaid Eli $10.'))
        self.assertEqual((r['status'],r['answer']),('VERIFIED',80.0))
    def test_over_refund_abstains(self):
        r=ledger_analysis(self.q('Eli received $100 from Sam. Eli gave Noah $30. Noah refunded Eli $40.'))
        self.assertEqual(r['status'],'UNSUPPORTED')
    def test_duplicate_refund_abstains(self):
        r=ledger_analysis(self.q('Eli received $100 from Sam. Eli gave Noah $30. Noah refunded Eli $20. Noah refunded Eli $20.'))
        self.assertEqual(r['status'],'UNSUPPORTED')
    def test_found_money_abstains(self):
        r=ledger_analysis(self.q('Eli received $100 from Sam. Eli gave Noah $30. Eli found $10.'))
        self.assertEqual(r['status'],'UNSUPPORTED')
    def test_borrowing_abstains(self):
        r=ledger_analysis(self.q('Eli received $100 from Sam. Eli gave Noah $30. Eli borrowed $10.'))
        self.assertEqual(r['status'],'UNSUPPORTED')
    def test_unknown_does_not_force_model(self):
        r=CognitiveSystem(model=lambda p:'MODEL ANSWER').answer(self.q('Eli received $100 from Sam. Eli borrowed $10.'))
        self.assertEqual(r['answer'],'MODEL ANSWER')
        self.assertIn('does NOT mean the answer is unknowable',r['model_prompt'])
