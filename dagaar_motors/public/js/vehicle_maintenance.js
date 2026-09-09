frappe.ui.form.on("Vehicle Maintenance", {
  setup(frm) {
    set_queries(frm);
  },

  async vehicle(frm) {
    if (!frm.doc.vehicle) return;
    const values = await dagaar_motors.forms.vehicle(frm, "vehicle");
    if (!frm.doc.odometer && values?.current_odometer != null) await frm.set_value("odometer", values.current_odometer);
    set_queries(frm);
  },

  async maintenance_rule(frm) {
    if (!frm.doc.maintenance_rule) return;
    const rule = await frappe.db.get_value("Vehicle Maintenance Rule", frm.doc.maintenance_rule, ["maintenance_type", "estimated_cost", "instructions"]);
    const values = rule?.message || {};
    if (values.maintenance_type) await frm.set_value("maintenance_type", values.maintenance_type);
    if (!frm.doc.estimated_cost && values.estimated_cost) await frm.set_value("estimated_cost", values.estimated_cost);
    if (!frm.doc.description && values.instructions) await frm.set_value("description", values.instructions);
  },

  refresh(frm) {
    set_queries(frm);
    if (frm.is_new() || frm.doc.docstatus !== 0) return;
    if (["Planned", "Due"].includes(frm.doc.status)) {
      frm.add_custom_button(__("Schedule"), () => schedule_dialog(frm), __("Actions"));
      frm.add_custom_button(__("Start"), async () => { await dagaar_motors.ui.call("dagaar_motors.api.fleet.start_maintenance_job", { maintenance: frm.doc.name }); frm.reload_doc(); }, __("Actions"));
    }
    if (["Scheduled", "In Progress", "Quality Check", "Due"].includes(frm.doc.status)) {
      frm.page.set_primary_action(__("Complete Maintenance"), async () => {
        await dagaar_motors.ui.call("dagaar_motors.api.fleet.complete_maintenance_job", { maintenance: frm.doc.name, odometer: frm.doc.odometer });
        frm.reload_doc();
      }, "check");
    }
  },
});

function set_queries(frm) {
  frm.set_query("vehicle", () => ({ filters: { status: ["not in", ["Sold", "Retired"]] } }));
  frm.set_query("branch", () => ({ filters: frm.doc.company ? { company: frm.doc.company, active: 1 } : { active: 1 } }));
  frm.set_query("maintenance_rule", () => ({ filters: { active: 1 } }));
}

function schedule_dialog(frm) {
  const dialog = new frappe.ui.Dialog({
    title: __("Schedule Maintenance"),
    fields: [
      { fieldname: "planned_start", label: __("Planned Start"), fieldtype: "Datetime", reqd: 1, default: frm.doc.planned_start || frappe.datetime.now_datetime() },
      { fieldname: "planned_end", label: __("Planned End"), fieldtype: "Datetime", reqd: 1, default: frm.doc.planned_end },
    ],
    primary_action_label: __("Schedule"),
    async primary_action(values) { await dagaar_motors.ui.call("dagaar_motors.api.fleet.schedule", { maintenance: frm.doc.name, ...values }); dialog.hide(); frm.reload_doc(); },
  });
  dialog.show();
}
