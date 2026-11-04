import gc
import os
import tempfile
import unittest
import warnings
from concurrent.futures import ThreadPoolExecutor
from nova.core import Knowledge

class LifecycleTests(unittest.TestCase):
    def test_context_manager_closes_connection(self):
        with tempfile.TemporaryDirectory() as td:
            with Knowledge(os.path.join(td, 'dictionary.sqlite')) as db:
                db.add('dictionary','run','operate')
                self.assertEqual(db.lookup('dictionary','run')['meaning'],'operate')
            with self.assertRaises(RuntimeError):
                db.lookup('dictionary','run')

    def test_concurrent_file_backed_connections_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            with Knowledge(os.path.join(td,'dictionary.sqlite')) as db:
                db.add('dictionary','relinquish','give up')
                with ThreadPoolExecutor(max_workers=4) as pool:
                    values=list(pool.map(lambda _:db.lookup('dictionary','relinquish')['meaning'],range(100)))
                self.assertEqual(values,['give up']*100)
            gc.collect()

    def test_no_sqlite_resource_warnings(self):
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter('always',ResourceWarning)
            with tempfile.TemporaryDirectory() as td:
                db=Knowledge(os.path.join(td,'test.sqlite'))
                db.add('dictionary','x','y')
                db.close()
                del db
                gc.collect()
            self.assertFalse([w for w in captured if issubclass(w.category,ResourceWarning)])
