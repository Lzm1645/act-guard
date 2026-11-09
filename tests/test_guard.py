import unittest

import guard


def run(mandate, intent, context=None):
    return guard.check_intent(mandate, intent, context)


class UnknownConstraintTest(unittest.TestCase):
    def test_unknown_constraint_denied(self):
        r = run({"constraints": [{"foo": "bar"}]}, {"amount_cents": 9_999_999, "currency": "USD", "payee": "any"})
        self.assertEqual(r.decision, guard.DENY)
        self.assertTrue(any("未知约束" in v for v in r.violations))

    def test_empty_constraints_denied(self):
        r = run({"constraints": []}, {"amount_cents": 100, "currency": "USD", "payee": "any"})
        self.assertEqual(r.decision, guard.DENY)


class NegativeAmountTest(unittest.TestCase):
    def test_negative_amount_denied(self):
        r = run({"constraints": [{"type": "payment.amount_range", "max": 10_000}]},
                {"amount_cents": -5_000, "currency": "USD", "payee": "any"})
        self.assertEqual(r.decision, guard.DENY)

    def test_float_amount_denied(self):
        r = run({"constraints": [{"type": "payment.amount_range", "max": 10_000}]},
                {"amount_cents": 10.5, "currency": "USD", "payee": "any"})
        self.assertEqual(r.decision, guard.DENY)


class BudgetTest(unittest.TestCase):
    def test_budget_integer_boundary(self):
        r = run({"constraints": [{"type": "payment.budget", "max": 29}]},
                {"amount_cents": 29, "currency": "USD", "payee": "any"},
                {"total_amount_cents": 0})
        self.assertEqual(r.decision, guard.ALLOW)

    def test_budget_float_rejected(self):
        r = run({"constraints": [{"type": "payment.budget", "max": 0.29}]},
                {"amount_cents": 29, "currency": "USD", "payee": "any"},
                {"total_amount_cents": 0})
        self.assertEqual(r.decision, guard.DENY)

    def test_budget_unresolved_without_context(self):
        r = run({"constraints": [{"type": "payment.budget", "max": 10_000}]},
                {"amount_cents": 100, "currency": "USD", "payee": "any"})
        self.assertEqual(r.decision, guard.UNRESOLVED)

    def test_budget_exceeded(self):
        r = run({"constraints": [{"type": "payment.budget", "max": 10_000}]},
                {"amount_cents": 6_000, "currency": "USD", "payee": "any"},
                {"total_amount_cents": 5_000})
        self.assertEqual(r.decision, guard.DENY)


class CurrencyAndPayeeTest(unittest.TestCase):
    def test_currency_mismatch(self):
        r = run({"constraints": [{"type": "payment.amount_range", "max": 10_000, "currency": "EUR"}]},
                {"amount_cents": 100, "currency": "USD", "payee": "any"})
        self.assertEqual(r.decision, guard.DENY)

    def test_payee_not_allowed(self):
        r = run({"constraints": [{"type": "payment.allowed_payees", "allowed": [{"id": "shop-a"}]}]},
                {"amount_cents": 100, "currency": "USD", "payee": "shop-b"})
        self.assertEqual(r.decision, guard.DENY)

    def test_payee_allowed(self):
        r = run({"constraints": [{"type": "payment.allowed_payees", "allowed": [{"id": "shop-a"}]}]},
                {"amount_cents": 100, "currency": "USD", "payee": "shop-a"})
        self.assertEqual(r.decision, guard.ALLOW)


class TimeTest(unittest.TestCase):
    def test_execution_window(self):
        mandate = {"constraints": [{"type": "payment.execution_date",
                                    "not_before": "2026-01-01T00:00:00Z",
                                    "not_after": "2026-12-31T00:00:00Z"}]}
        r = run(mandate, {"amount_cents": 100, "currency": "USD", "payee": "any",
                          "execution_date": "2026-06-01T00:00:00Z"})
        self.assertEqual(r.decision, guard.ALLOW)
        r = run(mandate, {"amount_cents": 100, "currency": "USD", "payee": "any",
                          "execution_date": "2027-01-01T00:00:00Z"})
        self.assertEqual(r.decision, guard.DENY)


if __name__ == "__main__":
    unittest.main()
