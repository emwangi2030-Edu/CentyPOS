import frappe
from frappe import _
from frappe.utils import now_datetime

from centy_pos.utils.pos_helpers import append_invoice_items, require_pos_profile_active, run_pos_invoice_totals


@frappe.whitelist()
def save_hold(
	pos_profile: str,
	pos_opening_entry: str,
	customer: str,
	items: list,
	hold_reason: str,
	client_request_id: str,
):
	"""Persist cart as draft POS Invoice on hold."""
	require_pos_profile_active(pos_profile)
	if not client_request_id:
		frappe.throw(_("client_request_id is required"))

	existing = frappe.db.get_value(
		"POS Invoice",
		{"centy_pos_client_request_id": client_request_id, "docstatus": 0},
		"name",
	)
	if existing:
		inv = frappe.get_doc("POS Invoice", existing)
	else:
		inv = frappe.new_doc("POS Invoice")
		inv.centy_pos_client_request_id = client_request_id

	profile = frappe.get_cached_doc("POS Profile", pos_profile)
	inv.company = profile.company
	inv.pos_profile = pos_profile
	inv.is_pos = 1
	inv.update_stock = 1
	inv.set_warehouse = profile.warehouse
	inv.customer = customer
	inv.posting_date = frappe.utils.today()
	inv.posting_time = frappe.utils.nowtime()
	inv.centy_pos_on_hold = 1
	inv.centy_pos_hold_reason = hold_reason or ""
	inv.centy_pos_hold_saved_at = now_datetime()
	inv.set("items", [])
	append_invoice_items(inv, items)
	run_pos_invoice_totals(inv)
	if inv.name:
		inv.save()
	else:
		inv.insert()
	return inv.name


@frappe.whitelist()
def list_held(pos_opening_entry: str) -> list[dict]:
	opening = frappe.get_doc("POS Opening Entry", pos_opening_entry)
	rows = frappe.get_all(
		"POS Invoice",
		filters={
			"pos_profile": opening.pos_profile,
			"owner": opening.user,
			"docstatus": 0,
			"centy_pos_on_hold": 1,
		},
		fields=["name", "customer", "customer_name", "grand_total", "centy_pos_hold_reason", "centy_pos_hold_saved_at"],
		order_by="modified desc",
	)
	out = []
	for r in rows:
		cnt = frappe.db.count("POS Invoice Item", {"parent": r.name})
		out.append(
			{
				"name": r.name,
				"customer": r.customer,
				"customer_name": r.customer_name,
				"grand_total": float(r.grand_total or 0),
				"hold_reason": r.centy_pos_hold_reason,
				"saved_at": str(r.centy_pos_hold_saved_at) if r.centy_pos_hold_saved_at else None,
				"items_count": cnt,
			}
		)
	return out


@frappe.whitelist()
def resume_hold(pos_invoice: str) -> dict:
	inv = frappe.get_doc("POS Invoice", pos_invoice)
	if not inv.centy_pos_on_hold:
		frappe.throw(_("This invoice is not on hold."))
	items = []
	for d in inv.get("items") or []:
		items.append(
			{
				"item_code": d.item_code,
				"qty": float(d.qty),
				"uom": d.uom,
				"rate": float(d.rate or 0),
				"batch_no": getattr(d, "batch_no", None) or None,
				"discount_percentage": float(d.discount_percentage or 0),
			}
		)
	payments = []
	for d in inv.get("payments") or []:
		payments.append(
			{
				"mode_of_payment": d.mode_of_payment,
				"amount": float(d.amount or 0),
				"reference_no": getattr(d, "reference_no", None) or None,
			}
		)
	return {
		"pos_invoice": inv.name,
		"pos_profile": inv.pos_profile,
		"customer": inv.customer,
		"items": items,
		"payments": payments,
		"grand_total": float(inv.grand_total or 0),
	}


@frappe.whitelist()
def discard_hold(pos_invoice: str, reason: str):
	inv = frappe.get_doc("POS Invoice", pos_invoice)
	if inv.docstatus != 0:
		frappe.throw(_("Only draft invoices can be discarded."))
	if not inv.centy_pos_on_hold:
		frappe.throw(_("Only held drafts can be discarded here."))
	inv.add_comment("Comment", _("Hold discarded: {0}").format(reason or "-"))
	frappe.delete_doc("POS Invoice", pos_invoice, ignore_permissions=True, force=1)
