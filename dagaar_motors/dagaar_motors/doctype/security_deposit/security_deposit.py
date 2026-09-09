import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class SecurityDeposit(Document):
    def validate(self):
        if flt(self.amount_required) < 0:
            frappe.throw(_("Required deposit cannot be negative."))
        if flt(self.balance) < 0:
            frappe.throw(_("Security deposit balance cannot be negative."))
        if not self.is_new():
            computed_fields = (
                "amount_received",
                "held_amount",
                "deducted_amount",
                "refund_amount",
                "balance",
                "status",
                "waiver_approved_by",
                "latest_transaction",
            )
            previous = frappe.db.get_value(
                "Security Deposit",
                self.name,
                list(computed_fields),
                as_dict=True,
            )
            if previous:
                for fieldname in computed_fields:
                    current_value = self.get(fieldname)
                    previous_value = previous.get(fieldname)
                    if fieldname in {
                        "amount_received",
                        "held_amount",
                        "deducted_amount",
                        "refund_amount",
                        "balance",
                    }:
                        changed = flt(current_value) != flt(previous_value)
                    else:
                        changed = (current_value or None) != (previous_value or None)
                    if changed:
                        frappe.throw(
                            _("Deposit totals and status are maintained only through Deposit Transactions.")
                        )

    def on_trash(self):
        if frappe.db.exists("Deposit Transaction", {"security_deposit": self.name}):
            frappe.throw(_("A Security Deposit with transaction history cannot be deleted."))
