import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class CentyPOSCashMovement(Document):
	def validate(self):
		self._validate_opening_entry_open()
		self._validate_amount_positive()
		self._validate_supervisor_approval()

	def _validate_opening_entry_open(self):
		if not self.pos_opening_entry:
			return
		closing = frappe.db.get_value("POS Opening Entry", self.pos_opening_entry, "pos_closing_entry")
		if closing:
			frappe.throw(_("This POS shift is already closed. Choose an open POS Opening Entry."))

	def _validate_amount_positive(self):
		if flt(self.amount) <= 0:
			frappe.throw(_("Amount must be greater than zero."))

	def _validate_supervisor_approval(self):
		threshold = 5000.0
		if self.pos_profile:
			threshold = flt(
				frappe.db.get_value("POS Profile", self.pos_profile, "centy_pos_cash_movement_approval_threshold")
				or 5000.0
			)
		if flt(self.amount) > threshold and not self.approved_by:
			frappe.throw(
				_("Amount exceeds supervisor approval threshold ({0}). Set Approved By.").format(threshold)
			)

	def on_submit(self):
		"""GL handled at POS Closing Entry variance; no GL posting here."""
		pass
