import frappe
from frappe import _
from frappe.utils import flt


def validate(doc, method=None):
	"""Enforce max cashier discount from POS Profile."""
	if doc.doctype != "POS Invoice":
		return
	if not doc.pos_profile or doc.is_return:
		return
	max_pct = frappe.db.get_value("POS Profile", doc.pos_profile, "centy_pos_max_cashier_discount_pct")
	if max_pct is None:
		return
	max_pct = flt(max_pct)
	roles = frappe.get_roles(frappe.session.user)
	if "Centy POS Supervisor" in roles or "Centy POS Manager" in roles or "System Manager" in roles:
		return
	if "Centy POS Cashier" not in roles:
		return
	if flt(doc.additional_discount_percentage) > max_pct + 0.0001:
		frappe.throw(_("Discount exceeds maximum allowed for cashiers ({0}%).").format(max_pct))


def on_submit(doc, method=None):
	if doc.doctype != "POS Invoice" or doc.is_return:
		return
	_create_controlled_drug_registers(doc)
	from centy_pos.api.receipt import queue_receipt_on_submit

	queue_receipt_on_submit(doc)


def on_cancel(doc, method=None):
	if doc.doctype != "POS Invoice":
		return
	# Controlled drug register entries remain for audit; reversals are Phase 3+.


def _create_controlled_drug_registers(doc):
	rx = frappe.flags.get("centy_pos_prescription") or {}
	needs_rx = False
	for line in doc.items or []:
		if line.item_code and frappe.db.get_value("Item", line.item_code, "centy_pos_is_controlled_drug"):
			needs_rx = True
			break
	if needs_rx and not rx:
		frappe.throw(
			_("Controlled items require prescription data. Submit via Centy POS checkout or capture prescription fields.")
		)
	for line in doc.items or []:
		if not line.item_code:
			continue
		if not frappe.db.get_value("Item", line.item_code, "centy_pos_is_controlled_drug"):
			continue
		if frappe.db.exists(
			"Centy POS Controlled Drug Register",
			{"pos_invoice": doc.name, "pos_invoice_item": line.name, "docstatus": 1},
		):
			continue
		cdr = frappe.new_doc("Centy POS Controlled Drug Register")
		cdr.pos_invoice = doc.name
		cdr.pos_invoice_item = line.name
		cdr.item = line.item_code
		if not line.batch_no:
			frappe.throw(_("Batch is required for controlled drug {0}.").format(line.item_code))
		cdr.batch_no = line.batch_no
		cdr.quantity_dispensed = abs(flt(line.qty))
		cdr.customer = doc.customer
		cdr.patient_name = rx.get("patient_name") or frappe.throw(_("patient_name required"))
		cdr.patient_id_type = rx.get("patient_id_type") or "National ID"
		cdr.patient_id_number = rx.get("patient_id_number") or frappe.throw(_("patient_id_number required"))
		cdr.prescriber_name = rx.get("prescriber_name") or frappe.throw(_("prescriber_name required"))
		cdr.prescriber_reg_number = rx.get("prescriber_reg_number")
		cdr.prescription_number = rx.get("prescription_number")
		cdr.dispensing_pharmacist = rx.get("dispensing_pharmacist") or frappe.throw(_("dispensing_pharmacist required"))
		cdr.pos_profile = doc.pos_profile
		cdr.notes = rx.get("notes")
		cdr.insert(ignore_permissions=True)
		cdr.submit()
