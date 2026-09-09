frappe.ui.form.on("Vehicle Sale", {
  setup(frm) {
    set_sale_queries(frm);
  },

  refresh(frm) {
    set_sale_queries(frm);
    if (frm.is_new()) return;

    const approvalRoles = ["System Manager", "Dagaar Motors Administrator", "Dagaar Motors Vehicle Sales Manager", "Dagaar Motors Branch Manager"];
    const canApprove = approvalRoles.some((role) => frappe.user.has_role(role));

    if (canApprove && frm.doc.docstatus === 0 && ["Draft", "Qualified", "Reserved", "Awaiting Approval"].includes(frm.doc.status)) {
      frm.add_custom_button(__("Approve"), async () => {
        await dagaar_motors.ui.call("dagaar_motors.api.fleet.approve_sale", { vehicle_sale: frm.doc.name });
        frm.reload_doc();
      }, __("Actions"));
    }

    if (frm.doc.docstatus === 0 && ["Approved", "Qualified", "Reserved"].includes(frm.doc.status)) {
      frm.page.set_primary_action(__("Complete Sale"), async () => {
        await dagaar_motors.ui.call("dagaar_motors.api.fleet.submit_sale", { vehicle_sale: frm.doc.name });
        frm.reload_doc();
      }, "check");
    }

    if (frm.doc.sales_invoice) {
      frm.add_custom_button(__("Open Sales Invoice"), () => frappe.set_route("Form", "Sales Invoice", frm.doc.sales_invoice), __("View"));
    }
  },

  async vehicle(frm) {
    if (!frm.doc.vehicle) return;
    const values = await dagaar_motors.forms.vehicle(frm, "vehicle");
    const mapping = {
      company: "company",
      branch: "branch",
      currency: "currency",
      selling_item: "item",
      asking_price: "asking_price",
      minimum_price: "minimum_price",
      commission_percent: "commission_percent",
    };
    for (const [source, target] of Object.entries(mapping)) {
      if (values?.[source] !== undefined && values[source] !== null && frm.fields_dict[target]) {
        await frm.set_value(target, values[source]);
      }
    }
    if (!frm.doc.sale_price && values?.asking_price) await frm.set_value("sale_price", values.asking_price);
  },
});

function set_sale_queries(frm) {
  frm.set_query("vehicle", () => ({ filters: { sellable: 1, status: ["not in", ["Sold", "Retired"]] } }));
  frm.set_query("branch", () => ({ filters: frm.doc.company ? { company: frm.doc.company, active: 1 } : { active: 1 } }));
}
