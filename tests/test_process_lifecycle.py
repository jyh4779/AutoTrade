import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from src.core.observability.processes import Singleton, stop_tree
import psutil


@unittest.skipUnless(os.name=='nt','Windows process lifecycle')
class Lifecycle(unittest.TestCase):
    def test_singleton_blocks_and_releases(self):
        with tempfile.TemporaryDirectory() as root:
            first=Singleton(root,'test');second=Singleton(root,'test')
            try:
                self.assertTrue(first.acquire())
                self.assertFalse(second.acquire())
                first.close()
                self.assertTrue(second.acquire())
            finally:
                first.close();second.close()

    def test_verified_tree_stop_and_wrong_identity_rejected(self):
        p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'],
                           creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            created=psutil.Process(p.pid).create_time()
            self.assertFalse(stop_tree(p.pid,created-10,timeout=1))
            self.assertIsNone(p.poll())
            self.assertTrue(stop_tree(p.pid,created,timeout=1))
            p.wait(timeout=3)
        finally:
            if p.poll() is None:p.kill();p.wait()

    def test_other_process_cannot_take_lock(self):
        with tempfile.TemporaryDirectory() as root:
            guard=Singleton(root,'test')
            self.assertTrue(guard.acquire())
            try:
                script=('import sys; from src.core.observability.processes import Singleton; '
                        "s=Singleton(sys.argv[1],'test'); sys.exit(0 if s.acquire() else 75)")
                result=subprocess.run([sys.executable,'-c',script,root],timeout=10,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(result.returncode,75)
            finally:
                guard.close()
