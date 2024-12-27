import unittest
from deploy_and_benchmark import read_yaml, main

class TestDeployAndBenchmark(unittest.TestCase):
    def setUp(self):
        import sys
        if len(sys.argv) != 2:
            print("Usage: python test_deploy_and_benchmark.py <path_to_yaml>")
            sys.exit(1)
        
        self.yaml_file = sys.argv[1]

    def test_read_yaml(self):
        config = read_yaml(self.yaml_file)
        print("Read YAML config - deploy:", config['deploy'])
        print("Read YAML config - benchmark:", config['benchmark'])
        self.assertIn('deploy', config)
        self.assertIn('benchmark', config)
        self.assertIsInstance(config['deploy'], dict)
        self.assertIsInstance(config['benchmark'], dict)

    def test_main(self):
        config = main(self.yaml_file)
        print("Main config - deploy:", config['deploy'])
        print("Main config - benchmark:", config['benchmark'])
        self.assertIn('deploy', config)
        self.assertIn('benchmark', config)
        self.assertIsInstance(config['deploy'], dict)
        self.assertIsInstance(config['benchmark'], dict)

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)