import frappe
from frappe import _
from frappe.utils import cint, flt

from centy_pos.utils.pos_helpers import (
	append_invoice_items,
	append_payments,
	assert_opening_for_profile_user,
	new_pos_invoice_shell,
	require_pos_profile_active,
	run_pos_invoice_totals,
	serialize_pos_invoice_totals,
)


def _require_controlled_prescription(items: list, pharmacy_prescription_data: dict | None):
	for row in items or []:
		item_code = row.get("item_code")
		if not item_code:
			continue
		if frappe.db.get_value("Item", item_code, "centy_pos_is_controlled_drug"):
			if not pharmacy_prescription_data:
				frappe.throw(_("Prescription / patient details required for controlled items."))
			for key in ("patient_name", "patient_id_number", "prescriber_name", "dispensing_pharmacist"):
				if not (pharmacy_prescription_data.get(key) or "").strip():
					frappe.throw(_("{0} is required for controlled drug sales.").format(key))
			return
	return


def _format_submit_response(inv) -> dict:
	row = frappe.db.get_value(
		"POS Profile",
		inv.pos_profile,
		["centy_pos_receipt_via_whatsapp", "centy_pos_receipt_via_sms", "centy_pos_etims_enabled"],
		as_dict=True,
	)
	whatsapp = "skipped"
	if row and cint(row.get("centy_pos_receipt_via_whatsapp")):
		whatsapp = "queued" if (inv.centy_pos_whatsapp_status or "") in ("", "Pending") else inv.centy_pos_whatsapp_status.lower()
	return {
		"pos_invoice": inv.name,
		"grand_total": flt(inv.grand_total),
		"outstanding_amount": flt(inv.outstanding_amount),
		"etims_status": "disabled"
		if not row or not cint(row.get("centy_pos_etims_enabled"))
		else "pending",
		"etims_qr_code": getattr(inv, "centy_pos_etims_qr_code", None),
		"receipt_delivery": {
			"whatsapp": whatsapp,
			"sms": "queued" if row and cint(row.get("centy_pos_receipt_via_sms")) else "skipped",
		},
		"loyalty_points_earned": flt(getattr(inv, "loyalty_points", 0) or 0),
		"changed_due": flt(inv.change_amount or 0),
	}


@frappe.whitelist()
def preview_invoice(
	pos_profile: str,
	customer: str,
	items: list,
	payments: list,
	coupon_code: str | None = None,
):
	"""Dry-run POS Invoice totals (no DB insert)."""
	require_pos_profile_active(pos_profile)
	inv = new_pos_invoice_shell(pos_profile, customer)
	if coupon_code:
		inv.coupon_code = coupon_code
	append_invoice_items(inv, items)
	append_payments(inv, payments)
	run_pos_invoice_totals(inv)
	out = serialize_pos_invoice_totals(inv)
	out["pricing_rule_details"] = [d.as_dict() for d in (inv.get("pricing_rule_details") or [])]
	return out


@frappe.whitelist()
def submit_invoice(
	pos_profile: str,
	pos_opening_entry: str,
	customer: str,
	items: list,
	payments: list,
	client_request_id: str,
	created_offline: bool = False,
	device_id: str | None = None,
	coupon_code: str | None = None,
	loyalty_points_redeemed: float = 0,
	pharmacy_prescription_data: dict | None = None,
):
	"""Submit POS Invoice with idempotency."""
	if not client_request_id:
		frappe.throw(_("client_request_id is required"))

	require_pos_profile_active(pos_profile)
	assert_opening_for_profile_user(pos_opening_entry, pos_profile)

	existing_name = frappe.db.get_value(
		"POS Invoice",
		{"centy_pos_client_request_id": client_request_id, "docstatus": 1},
		"name",
	)
	if existing_name:
		inv = frappe.get_doc("POS Invoice", existing_name)
		return _format_submit_response(inv)

	_require_controlled_prescription(items, pharmacy_prescription_data)

	draft_name = frappe.db.get_value(
		"POS Invoice",
		{"centy_pos_client_request_id": client_request_id, "docstatus": 0},
		"name",
	)
	if draft_name:
		invoice = frappe.get_doc("POS Invoice", draft_name)
		invoice.set("items", [])
		invoice.set("payments", [])
	else:
		invoice = frappe.new_doc("POS Invoice")
		invoice.centy_pos_client_request_id = client_request_id

	profile = frappe.get_cached_doc("POS Profile", pos_profile)
	invoice.company = profile.company
	invoice.pos_profile = pos_profile
	invoice.is_pos = 1
	invoice.update_stock = 1
	invoice.set_warehouse = profile.warehouse
	invoice.customer = customer
	invoice.posting_date = frappe.utils.today()
	invoice.posting_time = frappe.utils.nowtime()
	invoice.centy_pos_created_offline = 1 if created_offline else 0
	if device_id:
		invoice.centy_pos_device_id = device_id
	if coupon_code:
		invoice.coupon_code = coupon_code
	if loyalty_points_redeemed and flt(loyalty_points_redeemed) > 0:
		invoice.redeem_loyalty_points = 1
		invoice.loyalty_points = flt(loyalty_points_redeemed)

	append_invoice_items(invoice, items)
	append_payments(invoice, payments)
	run_pos_invoice_totals(invoice)

	frappe.flags.centy_pos_prescription = pharmacy_prescription_data
	try:
		if draft_name:
			invoice.save()
		else:
			invoice.insert()
		invoice.submit()
	finally:
		frappe.flags.centy_pos_prescription = None

	invoice.reload()
	return _format_submit_response(invoice)
