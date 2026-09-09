frappe.ui.form.on("Rental Return", {
  async rental_agreement(frm) {
    if (!frm.doc.rental_agreement) return;
    await dagaar_motors.forms.agreement(frm);
  },

  refresh(frm) {
    if (!frm.is_new() && frm.doc.docstatus === 0) {
      frm.page.set_primary_action(__("Complete Return"), async () => {
        await dagaar_motors.ui.call("dagaar_motors.api.rental.finalize_return", { rental_return: frm.doc.name });
        frm.reload_doc();
      }, "check");
    }
    if (frm.doc.final_sales_invoice) frm.add_custom_button(__("Open Final Invoice"), () => frappe.set_route("Form", "Sales Invoice", frm.doc.final_sales_invoice), __("View"));
    if (frm.doc.security_deposit) frm.add_custom_button(__("Open Security Deposit"), () => frappe.set_route("Form", "Security Deposit", frm.doc.security_deposit), __("View"));
  },
});

frappe.ui.form.on("Rental Return Charge", {
  quantity: return_charge_changed,
  rate: return_charge_changed,
  charge_type(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.quantity) row.quantity = 1;
    return_charge_changed(frm, cdt, cdn);
  },
});

function return_charge_changed(frm, cdt, cdn) {
  const row = locals[cdt][cdn];
  row.amount = (Number(row.quantity || 0)) * (Number(row.rate || 0));
  frm.refresh_field("charges");
  let total = 0;
  (frm.doc.charges || []).forEach((r) => { total += Number(r.amount || 0); });
  frm.set_value("additional_charge_total", total);
}
