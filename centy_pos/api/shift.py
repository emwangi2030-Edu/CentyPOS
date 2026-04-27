import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from centy_pos.utils.idempotency import find_or_create
from centy_pos.utils.pos_helpers import get_pos_profile_row, require_pos_profile_active


def on_opening_submit(doc, method=None):
	"""Optional CentyHR clock-in gate — extend when CentyHR link field exists on POS Profile."""
	pass


@frappe.whitelist()
def get_pos_profile_context(pos_profile: str) -> dict:
	"""Payment methods and defaults for Hub POS workspace (opening balances, sale payments)."""
	require_pos_profile_active(pos_profile)
	if not frappe.has_permission("POS Profile", ptype="read", doc=pos_profile):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	prof = frappe.get_cached_doc("POS Profile", pos_profile)
	modes = []
	for p in prof.get("payments") or []:
		mop = getattr(p, "mode_of_payment", None)
		if mop:
			modes.append({"mode_of_payment": mop, "default": cint(getattr(p, "default", 0))})
	if not modes:
		frappe.throw(_("POS Profile has no payment methods configured."))
	row = get_pos_profile_row(pos_profile)
	return {
		"pos_profile": pos_profile,
		"company": row.company,
		"warehouse": row.warehouse,
		"currency": row.currency,
		"default_customer": row.customer,
		"require_customer": cint(row.get("centy_pos_require_customer")),
		"payment_modes": modes,
	}


@frappe.whitelist()
def open_shift(
	pos_profile: str,
	opening_balances: list,
	client_request_id: str,
	device_id: str | None = None,
):
	"""Create and submit POS Opening Entry (idempotent by client_request_id)."""
	require_pos_profile_active(pos_profile)
	if not client_request_id:
		frappe.throw(_("client_request_id is required"))

	submitted = frappe.db.get_value(
		"POS Opening Entry",
		{"centy_pos_client_request_id": client_request_id, "docstatus": 1},
		"name",
	)
	if submitted:
		doc = frappe.get_doc("POS Opening Entry", submitted)
		return {
			"pos_opening_entry": doc.name,
			"status": (doc.status or "open").lower(),
			"started_at": str(doc.period_start_date),
		}

	draft = frappe.db.get_value(
		"POS Opening Entry",
		{"centy_pos_client_request_id": client_request_id, "docstatus": 0},
		"name",
	)
	if draft:
		doc = frappe.get_doc("POS Opening Entry", draft)
		doc.submit()
		doc.reload()
		return {
			"pos_opening_entry": doc.name,
			"status": (doc.status or "open").lower(),
			"started_at": str(doc.period_start_date),
		}

	row = get_pos_profile_row(pos_profile)

	doc = frappe.new_doc("POS Opening Entry")
	doc.company = row.company
	doc.pos_profile = pos_profile
	doc.user = frappe.session.user
	doc.period_start_date = now_datetime()
	doc.posting_date = frappe.utils.today()
	doc.centy_pos_client_request_id = client_request_id
	if device_id:
		doc.centy_pos_device_id = device_id
	for b in opening_balances or []:
		doc.append(
			"balance_details",
			{
				"mode_of_payment": b.get("mode_of_payment"),
				"opening_amount": flt(b.get("opening_amount", 0)),
			},
		)
	doc.insert()
	doc.submit()
	doc.reload()
	return {
		"pos_opening_entry": doc.name,
		"status": (doc.status or "open").lower(),
		"started_at": str(doc.period_start_date),
	}


@frappe.whitelist()
def close_shift(pos_opening_entry: str, closing_balances: list, client_request_id: str):
	"""Create POS Closing Entry from opening and submit."""
	if not client_request_id:
		frappe.throw(_("client_request_id is required"))

	existing = frappe.db.get_value(
		"POS Closing Entry",
		{"centy_pos_client_request_id": client_request_id, "docstatus": 1},
		"name",
	)
	if existing:
		return {"pos_closing_entry": existing, "status": "Submitted", "reused": True}

	from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import make_closing_entry_from_opening

	opening = frappe.get_doc("POS Opening Entry", pos_opening_entry)
	draft_name = frappe.db.get_value(
		"POS Closing Entry",
		{"centy_pos_client_request_id": client_request_id, "docstatus": 0},
		"name",
	)
	if draft_name:
		closing = frappe.get_doc("POS Closing Entry", draft_name)
	else:
		closing = make_closing_entry_from_opening(opening)
		closing.centy_pos_client_request_id = client_request_id

	by_mop = {r.get("mode_of_payment"): flt(r.get("closing_amount")) for r in (closing_balances or [])}
	for row in closing.payment_reconciliation or []:
		if row.mode_of_payment in by_mop:
			row.closing_amount = by_mop[row.mode_of_payment]
		row.difference = flt(row.closing_amount) - flt(row.expected_amount)

	if draft_name:
		closing.save()
	else:
		closing.insert()

	if closing.docstatus == 0:
		closing.submit()

	return {
		"pos_closing_entry": closing.name,
		"status": closing.status,
		"grand_total": flt(closing.grand_total),
		"payment_reconciliation": [r.as_dict() for r in (closing.payment_reconciliation or [])],
	}


@frappe.whitelist()
def get_shift_summary(pos_opening_entry: str) -> dict:
	opening = frappe.get_doc("POS Opening Entry", pos_opening_entry)
	if opening.docstatus != 1:
		frappe.throw(_("POS Opening Entry must be submitted."))

	end = now_datetime()
	# ERPNext builds differ on helper exports in pos_closing_entry.py.
	# Query directly so this API remains compatible across v14/v15 patch levels.
	invoices = frappe.db.sql(
		"""
		SELECT name, is_return, grand_total
		FROM `tabPOS Invoice`
		WHERE pos_profile = %(pos_profile)s
			AND owner = %(owner)s
			AND docstatus = 1
			AND creation >= %(start)s
			AND creation <= %(end)s
		ORDER BY creation ASC
		""",
		{
			"pos_profile": opening.pos_profile,
			"owner": opening.user,
			"start": opening.period_start_date,
			"end": end,
		},
		as_dict=True,
	)

	gross = 0.0
	ret = 0.0
	for inv in invoices:
		amt = flt(inv.grand_total)
		if inv.get("is_return"):
			ret += abs(amt)
		else:
			gross += amt

	# Payment child table names vary across ERPNext versions.
	# Read payments from each invoice doc for stable cross-version behavior.
	payments_by_mode: dict[str, float] = {}
	for inv_row in invoices or []:
		inv_doc = frappe.get_doc("POS Invoice", inv_row.name)
		for pay in inv_doc.get("payments") or []:
			mode = str(getattr(pay, "mode_of_payment", "") or "").strip()
			if not mode:
				continue
			payments_by_mode[mode] = flt(payments_by_mode.get(mode)) + flt(getattr(pay, "amount", 0))
	by_mode = [{"mode": mode, "expected": flt(amount)} for mode, amount in sorted(payments_by_mode.items())]

	movements = frappe.get_all(
		"Centy POS Cash Movement",
		filters={"pos_opening_entry": pos_opening_entry, "docstatus": 1},
		fields=["movement_type", "amount"],
	)
	cash_movements = [{"type": m.movement_type, "amount": flt(m.amount)} for m in movements]

	cash_delta = sum(
		(flt(m.amount) if m.movement_type == "Pay In" else -flt(m.amount)) for m in movements
	)
	for p in by_mode:
		if str(p.get("mode") or "").lower() == "cash":
			p["expected"] = flt(p["expected"]) + cash_delta
			break

	return {
		"invoices_count": len(invoices),
		"gross_sales": gross,
		"returns": ret,
		"net_sales": gross - ret,
		"by_mode_of_payment": by_mode,
		"cash_movements": cash_movements,
		"cash_expected": cash_delta,
	}


@frappe.whitelist()
def record_cash_movement(
	pos_opening_entry: str,
	movement_type: str,
	amount: float,
	reason: str,
	client_request_id: str,
	approved_by: str | None = None,
	mode_of_payment: str | None = None,
):
	"""Create and submit Centy POS Cash Movement (idempotent)."""
	if not client_request_id:
		frappe.throw(_("client_request_id is required"))

	existing = frappe.db.get_value(
		"Centy POS Cash Movement",
		{"client_request_id": client_request_id, "docstatus": 1},
		"name",
	)
	if existing:
		return existing

	frappe.get_doc("POS Opening Entry", pos_opening_entry)  # validate exists

	def _build():
		d = frappe.new_doc("Centy POS Cash Movement")
		d.pos_opening_entry = pos_opening_entry
		d.movement_type = movement_type
		d.amount = flt(amount)
		d.reason = reason or "-"
		d.mode_of_payment = mode_of_payment or "Cash"
		if approved_by:
			d.approved_by = approved_by
		return d

	doc = find_or_create(
		"Centy POS Cash Movement",
		client_request_id,
		{},
		_build,
	)
	if doc.docstatus == 0:
		doc.submit()
	return doc.name
