import os
import sys
import time
import signal
from pathlib import Path

root = (Path(__file__).parent)
sys.path.append(str(root))

import json
import logging
import asyncio
import unittest
from subprocess import (Popen, 
                        PIPE, 
                        check_output,
                        TimeoutExpired)

logging.basicConfig(level=logging.DEBUG,
                    format='%(process)d-%(levelname)s-%(message)s',
                    stream=sys.stdout)

class ClientTestCase(unittest.TestCase):
    def setUp(self):
        self.subList = {}
        cmd = ["python", "server.py"]
        self.connection_util(cmd, "server")
        time.sleep(2)
        logging.info("server started")

    def tearDown(self):
        for sub in self.subList.keys():
            pid = self.subList[sub].pid
            match sys.platform:
                case "win32":
                    check_output("taskkill /pid %d /F" % pid)
                case "linux":
                    os.kill(pid, signal.SIGTERM)
            self.subList[sub].kill()
        logging.info("server stopped")

    def connection_util(self, cmd, name):
        self.subList[name] = Popen(cmd, shell=True, 
                                        stdin = PIPE, 
                                        stdout = PIPE, 
                                        stderr = PIPE)
    
    def test_send_message(self):
        for i in range(2):
            name = f'test{i}'
            cmd = ["python", "client.py", "--user", f'{name}']
            self.connection_util(cmd, name)
            
        print(self.subList)

        self.subList["test0"].stdin.write(b"Hello")
        time.sleep(1)
        self.subList["server"].kill()
        
        logging.info(self.subList["server"].stdout.read().decode())

if __name__ == '__main__':
    unittest.main()