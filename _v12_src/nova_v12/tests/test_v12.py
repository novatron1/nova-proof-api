import json
import tempfile
import unittest
from pathlib import Path
from nova.engine import CognitiveSystem, lexical_analysis, semantic_graph, load_lexicon

class V12Tests(unittest.TestCase):
    def test_graph_keeps_antonym_separate(self):
        g=semantic_graph(lexical_analysis('What does relinquish mean?'))
        self.assertTrue(any(e['relation']=='antonym' and e['to']=='word:retain' for e in g['edges']))
        self.assertTrue(any(e['relation']=='synonym' and e['to']=='word:surrender' for e in g['edges']))
    def test_model_receives_graph_without_answer(self):
        r=CognitiveSystem(model=lambda p:'model speaks').answer('What does relinquish mean?',mode='concepts')
        self.assertEqual(r['answer'],'model speaks')
        self.assertIsNone(r['package']['verified_answer'])
        self.assertIn('semantic_graph',r['model_prompt'])
        self.assertIn('nova_authority',r['model_prompt'])
    def test_custom_lexicon(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'words.json'
            p.write_text(json.dumps({'bright':[{'meaning':'giving off light','synonyms':['luminous'],'antonyms':['dim'],'cues':['lamp']}]}))
            n=CognitiveSystem(lexicon_path=p)
            r=n.answer('What does bright mean?',mode='independent')
            self.assertEqual(r['answer'],'giving off light')
    def test_invalid_lexicon_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.json';p.write_text('{"foo":[{"synonyms":["bar"]}]}')
            with self.assertRaises(ValueError):load_lexicon(p)
    def test_unknown_does_not_force_abstain(self):
        r=CognitiveSystem(model=lambda p:'Paris').answer('What is the capital of France?')
        self.assertEqual(r['answer'],'Paris')
        self.assertEqual(r['state'],'UNSUPPORTED')
    def test_unsupported_money_action_visible(self):
        r=CognitiveSystem().answer('Eli received $100 from Sam. Eli earned $20. How much money does Eli have left from the $100?',mode='independent')
        self.assertEqual(r['state'],'UNSUPPORTED')
        self.assertTrue(r['package']['trace']['coverage']['unparsed_events'])
