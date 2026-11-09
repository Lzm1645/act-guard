from ap2.sdk.constraints import check_payment_constraints
from ap2.sdk.generated.open_payment_mandate import OpenPaymentMandate
from ap2.sdk.generated.payment_mandate import PaymentMandate
from ap2.sdk.generated.types.amount import Amount
from ap2.sdk.generated.types.merchant import Merchant
from ap2.sdk.generated.types.payment_instrument import PaymentInstrument
from ap2.sdk.utils import ec_key_to_jwk
from cryptography.hazmat.primitives.asymmetric import ec

cnf = {"jwk": ec_key_to_jwk(ec.generate_private_key(ec.SECP256R1()).public_key()).model_dump(exclude_none=True)}
mandate = OpenPaymentMandate(vct="mandate.payment.open.1", cnf=cnf, constraints=[{"foo": "bar"}])
print("parsed:", type(mandate.constraints[0]).__name__, mandate.constraints[0].model_dump(exclude_none=True))
payment = PaymentMandate(
    transaction_id="tx",
    payee=Merchant(name="AnyShop", id="any"),
    payment_amount=Amount(amount=99_999_999, currency="USD"),
    payment_instrument=PaymentInstrument(id="pi", type="credit"),
)
print("violations for $999,999.99:", check_payment_constraints(mandate, payment))
