import unittest
from nova.engine import ledger_analysis, CognitiveSystem

class TransactionV11(unittest.TestCase):
    def q(self, story, person='Eli', amount='100'):
        return story + f' How much money does {person} have left from the ${amount}?'
    def test_negated_transfer(self):
        r=ledger_analysis(self.q('Eli received $100 from Sam. Eli did not give Noah $30.'))
        self.assertEqual((r['status'],r['answer']),('VERIFIED',100.0))
        self.assertEqual([e['executed'] for e in r['events']],[True,False])
    def test_negated_didnt(self):
        r=ledger_analysis(self.q("Eli received $100 from Sam. Eli didn't give Noah $30."))
        self.assertEqual((r['status'],r['answer']),('VERIFIED',100.0))
    def test_found_without_dollar_symbol(self):
        r=ledger_analysis(self.q('Eli received $100 from Sam. Eli found 10 dollars.'))
        self.assertEqual(r['status'],'UNSUPPORTED')
    def test_earned_without_dollar_symbol(self):
        r=ledger_analysis(self.q('Eli received $100 from Sam. Eli earned 20 dollars.'))
        self.assertEqual(r['status'],'UNSUPPORTED')
    def test_unmatched_sent_without_symbol(self):
        r=ledger_analysis(self.q('Eli received $100 from Sam. Eli sent 10 dollars to Noah.'))
        self.assertEqual(r['status'],'UNSUPPORTED')
    def test_self_transfer_not_starting_deposit(self):
        r=ledger_analysis(self.q('Eli gave Eli $100. Eli gave Noah $30.'))
        self.assertNotEqual(r['status'],'VERIFIED')
    def test_refund_is_not_spending(self):
        r=ledger_analysis(self.q('Eli received $100 from Sam. Eli gave Noah $30. Noah refunded Eli $10.'))
        self.assertEqual((r['status'],r['answer']),('VERIFIED',80.0))
    def test_unsupported_does_not_force_model_abstention(self):
        r=CognitiveSystem(model=lambda p:'I can answer independently').answer(self.q('Eli received $100 from Sam. Eli found $20.'))
        self.assertEqual(r['answer'],'I can answer independently')
    def test_raw_original_unchanged(self):
        q=self.q('Eli received $100 from Sam. Eli did not give Noah $30.')
        r=CognitiveSystem().answer(q,mode='independent')
        self.assertEqual(r['package']['original_question'],q)
