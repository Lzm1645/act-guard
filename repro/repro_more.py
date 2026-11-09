from ap2.sdk.constraints import check_payment_constraints, MandateContext
from ap2.sdk.generated.open_payment_mandate import OpenPaymentMandate
from ap2.sdk.generated.payment_mandate import PaymentMandate
from ap2.sdk.generated.types.amount import Amount
from ap2.sdk.generated.types.merchant import Merchant
from ap2.sdk.generated.types.payment_instrument import PaymentInstrument
from ap2.sdk.utils import ec_key_to_jwk
from cryptography.hazmat.primitives.asymmetric import ec

cnf = {"jwk": ec_key_to_jwk(ec.generate_private_key(ec.SECP256R1()).public_key()).model_dump(exclude_none=True)}

def payment(amount_cents, currency="USD", tx="tx"):
    return PaymentMandate(
        transaction_id=tx,
        payee=Merchant(name="AnyShop", id="any"),
        payment_amount=Amount(amount=amount_cents, currency=currency),
        payment_instrument=PaymentInstrument(id="pi", type="credit"),
    )

def mandate(constraints):
    return OpenPaymentMandate(vct="mandate.payment.open.1", cnf=cnf, constraints=constraints)

print("== #391 negative amount, amount_range without min ==")
m = mandate([{"type": "payment.amount_range", "max": 10000, "currency": "USD"}])
print("violations:", check_payment_constraints(m, payment(-5000)))

print("== #391 negative amount, budget ==")
m = mandate([{"type": "payment.budget", "max": 100.0, "currency": "USD"}])
print("violations:", check_payment_constraints(m, payment(-5000), mandate_context=MandateContext(total_amount=5000)))

print("== #388 budget float truncation: max=0.29 USD, pay 29 cents ==")
m = mandate([{"type": "payment.budget", "max": 0.29, "currency": "USD"}])
print("violations:", check_payment_constraints(m, payment(29), mandate_context=MandateContext(total_amount=0)))

print("== #389 amount_range unit: schema requires integer cents; docs show 100.50 dollars ==")
try:
    m = mandate([{"type": "payment.amount_range", "max": 100.50, "currency": "USD"}])
    print("parsed; violations:", check_payment_constraints(m, payment(10050)))
except Exception as e:
    print("parse rejected (docs example cannot be represented):", type(e).__name__, str(e)[:120])
m = mandate([{"type": "payment.amount_range", "max": 10050, "currency": "USD"}])
print("integer cents max=10050 vs 10050: violations:", check_payment_constraints(m, payment(10050)))

print("== #389 budget unit: max=250 (budget spec says dollars?) vs 19900 cents ==")
m = mandate([{"type": "payment.budget", "max": 250, "currency": "USD"}])
print("violations:", check_payment_constraints(m, payment(19900), mandate_context=MandateContext(total_amount=0)))
