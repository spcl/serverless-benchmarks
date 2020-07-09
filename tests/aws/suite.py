import os
import tempfile
import unittest
import zipfile
from typing import List

import sebs

from .create_function import AWSCreateFunction
from .invoke_function_sdk import AWSInvokeFunctionSDK
from .invoke_function_http import AWSInvokeFunctionHTTP

def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AWSCreateFunction))
    suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AWSInvokeFunctionSDK))
    suite.addTest(unittest.defaultTestLoader.loadTestsFromTestCase(AWSInvokeFunctionHTTP))
    return suite

def run():
    runner = unittest.TextTestRunner()
    runner.run()
