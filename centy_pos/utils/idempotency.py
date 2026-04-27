import frappe


def _idempotency_fieldname(doctype: str) -> str:
	meta = frappe.get_meta(doctype)
	if meta.get_field("centy_pos_client_request_id"):
		return "centy_pos_client_request_id"
	if meta.get_field("client_request_id"):
		return "client_request_id"
	frappe.throw(
		f"DocType {doctype} needs Custom Field centy_pos_client_request_id or client_request_id for idempotency"
	)


def find_or_create(doctype: str, client_request_id: str, filters: dict, builder):
	"""
	Resolve a document by idempotency key or create it via builder (no insert inside builder).

	The builder must return a new, unsaved document with fields set; this function sets
	the idempotency field and inserts when no matching row exists.
	"""
	field = _idempotency_fieldname(doctype)
	combined = {field: client_request_id, **filters}
	existing = frappe.db.get_value(doctype, combined, "name")
	if existing:
		return frappe.get_doc(doctype, existing)
	doc = builder()
	setattr(doc, field, client_request_id)
	doc.insert()
	return doc
