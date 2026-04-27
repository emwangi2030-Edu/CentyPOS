import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def get_returnable_items(original_pos_invoice: str) -> list[dict]:
	orig = frappe.get_doc("POS Invoice", original_pos_invoice)
	if orig.docstatus != 1 or not orig.is_pos:
		frappe.throw(_("Original must be a submitted POS Invoice."))

	return_rows = frappe.db.sql(
		"""
		SELECT pos_invoice_item, SUM(ABS(qty)) AS qty
		FROM `tabPOS Invoice Item`
		WHERE parent IN (
			SELECT name FROM `tabPOS Invoice`
			WHERE return_against=%s AND docstatus=1 AND is_return=1
		) AND IFNULL(pos_invoice_item,'') != ''
		GROUP BY pos_invoice_item
		""",
		(original_pos_invoice,),
		as_dict=True,
	)
	returned_qty = {r.pos_invoice_item: flt(r.qty) for r in return_rows or []}

	out = []
	for line in orig.items:
		qty_orig = flt(line.qty)
		qty_ret = flt(returned_qty.get(line.name, 0))
		remaining = qty_orig - qty_ret
		if remaining > 0:
			out.append(
				{
					"pos_invoice_item_row": line.name,
					"item_code": line.item_code,
					"qty_sold": qty_orig,
					"qty_returned": qty_ret,
					"qty_returnable": remaining,
					"rate": flt(line.rate),
					"uom": line.uom,
				}
			)
	return out


@frappe.whitelist()
def create_return(
	original_pos_invoice: str,
	pos_opening_entry: str,
	return_items: list,
	refund_payments: list,
	reason: str,
	client_request_id: str,
):
	if not client_request_id:
		frappe.throw(_("client_request_id is required"))

	existing = frappe.db.get_value(
		"POS Invoice",
		{"centy_pos_client_request_id": client_request_id, "docstatus": 1},
		"name",
	)
	if existing:
		return {"return_invoice": existing, "refund_amount": 0, "etims_credit_note_status": "skipped", "reused": True}

	orig = frappe.get_doc("POS Invoice", original_pos_invoice)
	if orig.docstatus != 1:
		frappe.throw(_("Original invoice is not submitted."))

	opening = frappe.get_doc("POS Opening Entry", pos_opening_entry)
	if opening.status != "Open":
		frappe.throw(_("POS shift is not open."))

	returnable = {r["pos_invoice_item_row"]: r for r in get_returnable_items(original_pos_invoice)}

	ret_doc = frappe.new_doc("POS Invoice")
	ret_doc.is_return = 1
	ret_doc.return_against = orig.name
	ret_doc.company = orig.company
	ret_doc.pos_profile = orig.pos_profile
	ret_doc.customer = orig.customer
	ret_doc.is_pos = 1
	ret_doc.update_stock = 1
	ret_doc.set_warehouse = orig.set_warehouse
	ret_doc.posting_date = frappe.utils.today()
	ret_doc.posting_time = frappe.utils.nowtime()
	ret_doc.centy_pos_client_request_id = client_request_id
	ret_doc.centy_pos_on_hold = 0
	if reason:
		ret_doc.remarks = reason

	for row in return_items or []:
		line_name = row.get("pos_invoice_item_row")
		qty = flt(row.get("qty_to_return"))
		if not line_name or qty <= 0:
			continue
		info = returnable.get(line_name)
		if not info or qty > info["qty_returnable"]:
			frappe.throw(_("Invalid return quantity for line {0}.").format(line_name))
		orig_line = next((x for x in orig.items if x.name == line_name), None)
		if not orig_line:
			continue
		ret_doc.append(
			"items",
			{
				"item_code": orig_line.item_code,
				"qty": -1 * qty,
				"uom": orig_line.uom,
				"rate": orig_line.rate,
				"pos_invoice_item": line_name,
				"batch_no": getattr(orig_line, "batch_no", None),
			},
		)

	for p in refund_payments or []:
		ret_doc.append(
			"payments",
			{
				"mode_of_payment": p.get("mode_of_payment"),
				"amount": -1 * flt(p.get("amount", 0)),
			},
		)

	ret_doc.run_method("set_missing_values")
	ret_doc.run_method("calculate_taxes_and_totals")
	# ERPNext validate_change_amount uses paid_amount minus grand_total; keep paid_amount in sync with payment rows.
	pay_total = sum(flt(p.amount) for p in ret_doc.get("payments") or [])
	if ret_doc.paid_amount in (None, 0) and pay_total:
		ret_doc.paid_amount = pay_total
	ret_doc.insert()
	ret_doc.submit()

	refund = sum(flt(p.get("amount", 0)) for p in refund_payments or [])
	return {
		"return_invoice": ret_doc.name,
		"refund_amount": refund,
		"etims_credit_note_status": "pending",
	}
