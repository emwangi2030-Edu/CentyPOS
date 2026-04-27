import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from centy_pos.utils.pos_helpers import (
	append_invoice_items,
	append_payments,
	batch_suggestions,
	get_pos_profile_row,
	item_stock_qty,
	new_pos_invoice_shell,
	require_pos_profile_active,
	resolve_item_code_from_barcode,
	run_pos_invoice_totals,
	serialize_pos_invoice_totals,
)


@frappe.whitelist()
def search_items(pos_profile: str, query: str, limit: int = 20) -> list[dict]:
	"""Minimal item search for POS autocomplete."""
	require_pos_profile_active(pos_profile)
	row = get_pos_profile_row(pos_profile)
	warehouse = row.warehouse
	company = row.company
	limit = min(max(int(limit or 20), 1), 100)
	raw = (query or "").strip().replace("%", "").replace("_", "")
	search = f"%{raw}%"

	items = frappe.db.sql(
		"""
		SELECT DISTINCT i.name AS item_code, i.item_name, i.stock_uom
		FROM `tabItem` i
		INNER JOIN `tabItem Default` id ON id.parent = i.name AND id.company = %(company)s
		WHERE i.disabled = 0
			AND (i.name LIKE %(q)s OR i.item_name LIKE %(q)s
				OR EXISTS (
					SELECT 1 FROM `tabItem Barcode` ib
					WHERE ib.parent = i.name AND ib.barcode LIKE %(q)s
				))
		ORDER BY i.modified DESC
		LIMIT %(limit)s
		""",
		{"company": company, "q": search, "limit": limit},
		as_dict=True,
	)

	out = []
	for r in items or []:
		stock = item_stock_qty(r.item_code, warehouse)
		out.append(
			{
				"item_code": r.item_code,
				"item_name": r.item_name,
				"uom": r.stock_uom,
				"stock_qty": stock,
			}
		)
	return out


@frappe.whitelist()
def get_item_for_cart(
	pos_profile: str,
	item_code: str | None = None,
	barcode: str | None = None,
	customer: str | None = None,
	qty: float = 1,
) -> dict:
	"""Resolve item, pricing, stock flags for one cart line."""
	require_pos_profile_active(pos_profile)
	row = get_pos_profile_row(pos_profile)
	company = row.company
	warehouse = row.warehouse

	if barcode and not item_code:
		item_code = resolve_item_code_from_barcode(barcode)
	if not item_code:
		frappe.throw(_("item_code or barcode is required"))

	if not frappe.db.exists("Item", item_code):
		frappe.throw(_("Item {0} not found.").format(item_code))

	item = frappe.get_cached_doc("Item", item_code)
	if item.disabled:
		frappe.throw(_("Item {0} is inactive.").format(item_code))

	# Item must have default for company (same rule as search)
	if not frappe.db.exists("Item Default", {"parent": item_code, "company": company}):
		frappe.throw(_("Item {0} is not available for this company.").format(item_code))

	cust = customer or row.customer
	ctx = frappe._dict(
		{
			"item_code": item_code,
			"warehouse": warehouse,
			"customer": cust,
			"conversion_rate": 1.0,
			"selling_price_list": row.selling_price_list,
			"price_list_currency": frappe.db.get_value("Price List", row.selling_price_list, "currency"),
			"plc_conversion_rate": 1.0,
			"company": company,
			"doctype": "POS Invoice",
			"name": None,
			"transaction_date": nowdate(),
			"ignore_pricing_rule": cint(row.ignore_pricing_rule),
			"is_pos": 1,
			"qty": flt(qty),
		}
	)

	from erpnext.stock.get_item_details import get_item_details

	details = get_item_details(ctx)
	price_list_rate = flt(details.price_list_rate)
	rate = flt(details.rate or details.price_list_rate)
	stock_qty = item_stock_qty(item_code, warehouse)

	return {
		"item_code": item_code,
		"item_name": item.item_name,
		"uom": details.stock_uom or item.stock_uom,
		"rate": rate,
		"price_list_rate": price_list_rate,
		"discount_percentage": flt(details.discount_percentage),
		"batch_suggestions": batch_suggestions(item_code, warehouse),
		"requires_batch": cint(item.has_batch_no),
		"requires_prescription": cint(getattr(item, "centy_pos_requires_prescription", 0)),
		"is_controlled_drug": cint(getattr(item, "centy_pos_is_controlled_drug", 0)),
		"stock_qty_available": stock_qty,
		"applied_pricing_rules": details.get("pricing_rules") or [],
	}


@frappe.whitelist()
def price_cart(
	pos_profile: str,
	customer: str,
	items: list,
	coupon_code: str | None = None,
) -> dict:
	"""Price cart using in-memory POS Invoice (ERPNext tax + pricing engine)."""
	row = require_pos_profile_active(pos_profile)
	if row.get("centy_pos_require_customer") and not customer:
		frappe.throw(_("Customer is required for this POS Profile."))

	inv = new_pos_invoice_shell(pos_profile, customer)
	if coupon_code:
		inv.coupon_code = coupon_code
	append_invoice_items(inv, items)
	run_pos_invoice_totals(inv)
	data = serialize_pos_invoice_totals(inv)
	data["pricing_rule_details"] = [d.as_dict() for d in (inv.get("pricing_rule_details") or [])]
	return data


@frappe.whitelist()
def validate_coupon(pos_profile: str, coupon_code: str, customer: str, grand_total: float) -> dict:
	"""Validate Coupon Code against ERPNext Coupon Code."""
	require_pos_profile_active(pos_profile)
	if not coupon_code:
		return {"valid": False, "discount_amount": 0.0, "discount_percentage": 0.0, "message": _("No coupon code")}

	coupon_name = frappe.db.get_value("Coupon Code", {"coupon_code": coupon_code.strip()}, "name")
	if not coupon_name:
		return {"valid": False, "discount_amount": 0.0, "discount_percentage": 0.0, "message": _("Unknown coupon")}

	doc = frappe.get_doc("Coupon Code", coupon_name)
	from frappe.utils import getdate

	today = getdate()
	if doc.valid_from and getdate(doc.valid_from) > today:
		return {"valid": False, "discount_amount": 0.0, "discount_percentage": 0.0, "message": _("Coupon not yet valid")}
	if doc.valid_upto and getdate(doc.valid_upto) < today:
		return {"valid": False, "discount_amount": 0.0, "discount_percentage": 0.0, "message": _("Coupon expired")}
	if doc.customer and doc.customer != customer:
		return {"valid": False, "discount_amount": 0.0, "discount_percentage": 0.0, "message": _("Coupon not for this customer")}
	if doc.maximum_use and cint(doc.used) >= cint(doc.maximum_use):
		return {"valid": False, "discount_amount": 0.0, "discount_percentage": 0.0, "message": _("Coupon fully used")}

	discount_amount = 0.0
	discount_percentage = 0.0
	if doc.pricing_rule:
		pr = frappe.get_doc("Pricing Rule", doc.pricing_rule)
		if getattr(pr, "price_discount_slabs", None):
			return {"valid": True, "discount_amount": 0.0, "discount_percentage": 0.0, "message": _("Pricing rule applies")}
		if pr.rate_or_discount == "Discount Percentage":
			discount_percentage = flt(pr.discount_percentage)
		elif pr.rate_or_discount == "Discount Amount":
			discount_amount = flt(pr.discount_amount)

	return {
		"valid": True,
		"discount_amount": discount_amount,
		"discount_percentage": discount_percentage,
		"message": _("OK"),
	}
