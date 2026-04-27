import frappe


def after_install():
	"""Ensure Centy POS roles exist even if fixture import was skipped."""
	roles = (
		"Centy POS Cashier",
		"Centy POS Supervisor",
		"Centy POS Manager",
		"Centy POS Pharmacist",
	)
	for role_name in roles:
		if frappe.db.exists("Role", role_name):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 1,
			}
		)
		doc.insert(ignore_permissions=True)
	frappe.db.commit()
