import unittest
from transient_verification import run_verification


class TransientTests(unittest.TestCase):
    def test_independent_equilibrium_and_first_order_convergence(self):
        result=run_verification()
        self.assertEqual(result["status"],"PASS_NUMERICAL_TRANSIENT_ONLY")
        self.assertFalse(result["physical_acceptance"])
        self.assertEqual(result,run_verification())


if __name__=="__main__":unittest.main()
