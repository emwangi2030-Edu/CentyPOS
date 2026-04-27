"""Smoke import — run on bench: bench --site <site> run-tests --app centy_pos"""


def test_api_modules_importable():
	import centy_pos.api.cart as cart
	import centy_pos.api.checkout as checkout
	import centy_pos.api.etims as etims
	import centy_pos.api.hold as hold
	import centy_pos.api.receipt as receipt
	import centy_pos.api.returns as returns
	import centy_pos.api.shift as shift

	for m in (cart, checkout, etims, hold, receipt, returns, shift):
		assert m.__name__.startswith("centy_pos.api.")

	assert hasattr(receipt, "get_receipt_delivery_status")
