frappe.ui.form.on("Vehicle Expense", {
  async vehicle(frm) {
    if (!frm.doc.vehicle) return;
    const values = await dagaar_motors.forms.vehicle(frm, "vehicle");
    if (values?.project && !frm.doc.project) await frm.set_value("project", values.project);
  },
});

frappe.ui.form.on("Vehicle Transfer", {
  async vehicle(frm) {
    if (!frm.doc.vehicle) return;
    const values = await dagaar_motors.forms.vehicle(frm, "vehicle");
    if (values?.branch) await frm.set_value("source_branch", values.branch);
    if (values?.current_odometer != null && !frm.doc.departure_odometer) await frm.set_value("departure_odometer", values.current_odometer);
    if (values?.fuel_level && !frm.doc.departure_fuel) await frm.set_value("departure_fuel", values.fuel_level);
  },
});

frappe.ui.form.on("Vehicle Damage Report", {
  async vehicle(frm) { if (frm.doc.vehicle) await dagaar_motors.forms.vehicle(frm, "vehicle"); },
  async rental_agreement(frm) {
    if (!frm.doc.rental_agreement) return;
    const values = await dagaar_motors.forms.agreement(frm);
    if (values?.customer && !frm.doc.customer) await frm.set_value("customer", values.customer);
  },
});

frappe.ui.form.on("Traffic Fine", {
  async vehicle(frm) { if (frm.doc.vehicle) await dagaar_motors.forms.vehicle(frm, "vehicle"); },
  async rental_agreement(frm) {
    if (!frm.doc.rental_agreement) return;
    const values = await dagaar_motors.forms.agreement(frm);
    if (values?.customer && !frm.doc.customer) await frm.set_value("customer", values.customer);
  },
});

frappe.ui.form.on("Vehicle Accident", {
  async vehicle(frm) { if (frm.doc.vehicle) await dagaar_motors.forms.vehicle(frm, "vehicle"); },
  async rental_agreement(frm) {
    if (!frm.doc.rental_agreement) return;
    const values = await dagaar_motors.forms.agreement(frm);
    if (values?.customer && frm.fields_dict.customer && !frm.doc.customer) await frm.set_value("customer", values.customer);
  },
});
