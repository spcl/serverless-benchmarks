import os
import tempfile
import unittest
import zipfile
from typing import List

import sebs

from .create_function import AWSCreateFunction
from .invoke_function_sdk import AWSInvokeFunctionSDK

def run():
    runner = unittest.TextTestRunner()
    runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(AWSCreateFunction))
    runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(AWSInvokeFunctionSDK))
