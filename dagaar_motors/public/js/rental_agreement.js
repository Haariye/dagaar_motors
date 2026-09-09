frappe.ui.form.on("Rental Agreement", {
  setup(frm) {
    set_queries(frm);
  },

  async onload(frm) {
    if (frm.doc.customer) await dagaar_motors.forms.customer(frm, { suggestDriver: true });
    if (frm.doc.branch) await dagaar_motors.forms.branch(frm);
  },

  refresh(frm) {
    set_queries(frm);
    if (frm.doc.pricing_breakdown?.length) {
      frm.add_custom_button(__("Pricing Breakdown"), () => dagaar_motors.ui.show_pricing(frm.doc), __("View"));
    }
    if (frm.is_new()) return;

    if (frm.doc.docstatus === 0 && ["Ready for Pickup", "Reserved", "Awaiting Approval", "Draft"].includes(frm.doc.status)) {
      frm.page.set_primary_action(__("Check Out Vehicle"), async () => {
        await dagaar_motors.ui.call("dagaar_motors.api.rental.checkout", { agreement: frm.doc.name });
        frm.reload_doc();
      }, "play");
    }
    if (frm.doc.docstatus === 1 && ["Active", "Extended", "Overdue"].includes(frm.doc.status)) {
      frm.add_custom_button(__("Extend Rental"), () => frappe.new_doc("Rental Extension", { rental_agreement: frm.doc.name }), __("Actions"));
      frm.add_custom_button(__("Process Return"), () => frappe.new_doc("Rental Return", { rental_agreement: frm.doc.name }), __("Actions"));
    }
    if (frm.doc.current_invoice) {
      frm.add_custom_button(__("Open Rental Invoice"), () => frappe.set_route("Form", "Sales Invoice", frm.doc.current_invoice), __("View"));
    }
  },

  async customer(frm) {
    await dagaar_motors.forms.customer(frm, { suggestDriver: true, force: true });
    preview(frm);
  },

  async branch(frm) {
    await dagaar_motors.forms.branch(frm, { force: true });
    set_queries(frm);
    preview(frm);
  },

  async vehicle(frm) {
    if (!frm.doc.vehicle) return;
    await dagaar_motors.forms.vehicle(frm, "vehicle");
    set_queries(frm);
    preview(frm);
  },

  pickup_datetime: preview,
  expected_return_datetime: preview,
  rental_type: preview,
  vehicle_category: preview,
  discount_percent(frm) {
    // A percentage overrides any manual amount; clear it so intent is clear.
    if (Number(frm.doc.discount_percent || 0)) frm.set_value("discount_amount", 0);
    preview(frm);
  },
  discount_amount(frm) {
    // Typing an amount clears the percentage so the amount is used as-is.
    if (Number(frm.doc.discount_amount || 0) && Number(frm.doc.discount_percent || 0)) {
      frm.set_value("discount_percent", 0);
    }
    preview(frm);
  },
  pickup_location: preview,
  return_location: preview,
  one_way: preview,
  tax_template: preview,
});

frappe.ui.form.on("Rental Agreement Charge", {
  quantity: charge_row_changed,
  rate: charge_row_changed,
  charge_type(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.quantity) row.quantity = 1;
    charge_row_changed(frm, cdt, cdn);
  },
  charges_remove: preview,
});

function charge_row_changed(frm, cdt, cdn) {
  const row = locals[cdt][cdn];
  row.amount = (Number(row.quantity || 0)) * (Number(row.rate || 0));
  frm.refresh_field("charges");
  preview(frm);
}

frappe.ui.form.on("Rental Agreement Driver", {
  drivers_add(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if ((frm.doc.drivers || []).length === 1) row.primary_driver = 1;
    frm.refresh_field("drivers");
  },

  primary_driver(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.primary_driver) return;
    (frm.doc.drivers || []).forEach((driver) => {
      if (driver.name !== row.name) driver.primary_driver = 0;
    });
    frm.refresh_field("drivers");
  },
});

frappe.ui.form.on("Rental Agreement Extra", {
  rental_extra: preview,
  quantity: preview,
  rate: preview,
  extras_remove: preview,
});

function preview(frm) {
  dagaar_motors.forms.previewPricing(frm, "pickup_datetime", "expected_return_datetime");
}

function set_queries(frm) {
  frm.set_query("branch", () => ({ filters: frm.doc.company ? { company: frm.doc.company, active: 1 } : { active: 1 } }));
  frm.set_query("vehicle", () => ({
    filters: {
      company: frm.doc.company,
      branch: frm.doc.branch,
      category: frm.doc.vehicle_category,
      rentable: 1,
      status: ["in", ["Available", "Reserved", "Rented"]],
    },
  }));
  if (frm.fields_dict.contact) {
    frm.set_query("contact", () => ({
      query: "frappe.contacts.doctype.contact.contact.contact_query",
      filters: { link_doctype: "Customer", link_name: frm.doc.customer },
    }));
  }
}
