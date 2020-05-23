
import tempfile
import unittest

import sebs

class AWSUnitTest(unittest.TestCase):

    def setUp(self):
        config = {
	    "deployment": {
		"name": "aws",
		"region": "us-east-1"
	    }
  	}
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.cache_client = sebs.Cache(self.tmp_dir.name)
        self.deployment_client = sebs.get_deployment(
            self.cache_client,
            config["deployment"]
        )
        self.assertIsInstance(self.deployment_client, sebs.AWS)

    def test_create

    def tearDown(self):
        pass

def run():
    runner = unittest.TextTestRunner()
    runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(AWSUnitTest))
