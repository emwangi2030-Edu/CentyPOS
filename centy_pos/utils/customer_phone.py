import frappe


def resolve_customer_mobile(customer: str | None, override: str | None = None) -> str | None:
	if override:
		return override.strip() or None
	if not customer:
		return None
	mobile = frappe.db.get_value("Customer", customer, "mobile_no")
	if mobile:
		return mobile.strip() or None
	# Primary contact mobile (common ERPNext pattern)
	rows = frappe.db.sql(
		"""
		SELECT c.mobile_no
		FROM `tabDynamic Link` dl
		INNER JOIN `tabContact` c ON c.name = dl.parent
		WHERE dl.link_doctype = 'Customer' AND dl.link_name = %s
		ORDER BY IFNULL(c.is_primary_contact,0) DESC, c.modified DESC
		LIMIT 1
		""",
		(customer,),
	)
	if rows and rows[0][0]:
		return (rows[0][0] or "").strip() or None
	return None
