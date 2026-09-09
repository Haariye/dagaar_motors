frappe.ui.form.on("Rental Extension", {
  async rental_agreement(frm) {
    if (!frm.doc.rental_agreement) return;
    const values = await dagaar_motors.forms.agreement(frm);
    if (values?.expected_return_datetime) await frm.set_value("original_end_datetime", values.expected_return_datetime);
  },

  new_end_datetime(frm) {
    if (frm.doc.original_end_datetime && frm.doc.new_end_datetime) {
      dagaar_motors.forms.previewPricing(frm, "original_end_datetime", "new_end_datetime");
    }
  },

  discount_percent(frm) {
    dagaar_motors.forms.previewPricing(frm, "original_end_datetime", "new_end_datetime");
  },

  refresh(frm) {
    if (frm.doc.pricing_breakdown?.length) frm.add_custom_button(__("Pricing Breakdown"), () => dagaar_motors.ui.show_pricing(frm.doc), __("View"));
    if (!frm.is_new() && frm.doc.docstatus === 0) {
      frm.page.set_primary_action(__("Approve & Submit"), async () => {
        await dagaar_motors.ui.call("dagaar_motors.api.rental.approve_extension", { extension: frm.doc.name });
        frm.reload_doc();
      }, "check");
    }
    if (frm.doc.sales_invoice) frm.add_custom_button(__("Open Extension Invoice"), () => frappe.set_route("Form", "Sales Invoice", frm.doc.sales_invoice), __("View"));
  },
});
