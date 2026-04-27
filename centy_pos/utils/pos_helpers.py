import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate, nowtime


def get_pos_profile_row(pos_profile: str) -> dict:
	if not frappe.db.exists("POS Profile", pos_profile):
		frappe.throw(_("POS Profile {0} not found.").format(pos_profile))
	return frappe.db.get_value(
		"POS Profile",
		pos_profile,
		[
			"name",
			"company",
			"warehouse",
			"selling_price_list",
			"currency",
			"customer",
			"ignore_pricing_rule",
			"disabled",
			"centy_pos_require_customer",
			"centy_pos_sector",
		],
		as_dict=True,
	)


def require_pos_profile_active(pos_profile: str):
	row = get_pos_profile_row(pos_profile)
	if row.get("disabled"):
		frappe.throw(_("POS Profile {0} is disabled.").format(pos_profile))
	return row


def assert_opening_for_profile_user(pos_opening_entry: str, pos_profile: str, user: str | None = None):
	user = user or frappe.session.user
	pe = frappe.db.get_value(
		"POS Opening Entry",
		pos_opening_entry,
		["name", "status", "pos_profile", "user", "docstatus"],
		as_dict=True,
	)
	if not pe or pe.docstatus != 1:
		frappe.throw(_("POS Opening Entry {0} is not submitted.").format(pos_opening_entry))
	if pe.status != "Open":
		frappe.throw(_("POS Opening Entry {0} is not open.").format(pos_opening_entry))
	if pe.pos_profile != pos_profile:
		frappe.throw(_("POS Opening Entry does not match this POS Profile."))
	if pe.user != user:
		frappe.throw(_("POS Opening Entry belongs to a different cashier."))


def new_pos_invoice_shell(pos_profile: str, customer: str | None = None) -> "frappe.model.document.Document":
	row = require_pos_profile_active(pos_profile)
	inv = frappe.new_doc("POS Invoice")
	inv.company = row.company
	inv.pos_profile = pos_profile
	inv.is_pos = 1
	inv.update_stock = 1
	inv.set_warehouse = row.warehouse
	inv.currency = row.currency
	inv.selling_price_list = row.selling_price_list
	inv.posting_date = nowdate()
	inv.posting_time = nowtime()
	if customer:
		inv.customer = customer
	elif row.customer:
		inv.customer = row.customer
	if row.ignore_pricing_rule is not None:
		inv.ignore_pricing_rule = cint(row.ignore_pricing_rule)
	return inv


def append_invoice_items(inv, items: list):
	for row in items or []:
		item_code = row.get("item_code")
		if not item_code:
			continue
		line = {
			"item_code": item_code,
			"qty": flt(row.get("qty", 1)),
			"uom": row.get("uom"),
			"rate": flt(row.get("rate")) if row.get("rate") is not None else None,
			"discount_percentage": flt(row.get("discount_percentage") or 0),
			"batch_no": row.get("batch_no"),
			"serial_no": row.get("serial_no"),
		}
		inv.append("items", line)


def append_payments(inv, payments: list):
	for row in payments or []:
		if not row.get("mode_of_payment"):
			continue
		inv.append(
			"payments",
			{
				"mode_of_payment": row.get("mode_of_payment"),
				"amount": flt(row.get("amount", 0)),
				"reference_no": row.get("reference_no"),
			},
		)


def run_pos_invoice_totals(inv):
	inv.run_method("set_missing_values")
	inv.run_method("calculate_taxes_and_totals")


def item_stock_qty(item_code: str, warehouse: str | None) -> float:
	if not warehouse:
		return 0.0
	qty = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "sum(actual_qty)")
	return flt(qty)


def resolve_item_code_from_barcode(barcode: str) -> str | None:
	if not barcode:
		return None
	ic = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")
	return ic


def serialize_pos_invoice_totals(inv) -> dict:
	return {
		"grand_total": flt(inv.grand_total),
		"net_total": flt(inv.net_total),
		"base_grand_total": flt(inv.base_grand_total),
		"total_taxes_and_charges": flt(inv.total_taxes_and_charges),
		"outstanding_amount": flt(inv.outstanding_amount),
		"total": flt(inv.total),
		"discount_amount": flt(inv.discount_amount),
		"items": [
			{
				"item_code": d.item_code,
				"qty": flt(d.qty),
				"uom": d.uom,
				"rate": flt(d.rate),
				"amount": flt(d.amount),
				"name": d.name,
				"batch_no": getattr(d, "batch_no", None),
				"discount_percentage": flt(d.discount_percentage),
			}
			for d in inv.get("items") or []
		],
		"payments": [
			{
				"mode_of_payment": d.mode_of_payment,
				"amount": flt(d.amount),
			}
			for d in inv.get("payments") or []
		],
		"taxes": [
			{
				"account_head": d.account_head,
				"tax_amount": flt(d.tax_amount),
			}
			for d in inv.get("taxes") or []
		],
	}


def batch_suggestions(item_code: str, warehouse: str | None, limit: int = 8) -> list[dict]:
	if not warehouse or not frappe.get_cached_value("Item", item_code, "has_batch_no"):
		return []
	try:
		rows = frappe.db.sql(
			"""
			SELECT batch_no, SUM(actual_qty) AS qty
			FROM `tabBin`
			WHERE item_code=%s AND warehouse=%s AND IFNULL(batch_no,'')!='' AND actual_qty > 0
			GROUP BY batch_no
			ORDER BY qty DESC
			LIMIT %s
			""",
			(item_code, warehouse, int(limit)),
			as_dict=True,
		)
	except Exception:
		return []
	out = []
	for r in rows or []:
		exp = frappe.db.get_value("Batch", r.batch_no, "expiry_date")
		out.append({"batch_no": r.batch_no, "expiry_date": str(exp) if exp else None, "qty_available": flt(r.qty)})
	return out
