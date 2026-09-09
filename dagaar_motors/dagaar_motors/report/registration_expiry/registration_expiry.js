frappe.query_reports["Registration Expiry"] = {
  filters: [
    {
      fieldname: "company",
      label: "Company",
      fieldtype: "Link",
      options: "Company",
      reqd: 1,
      default: frappe.defaults.get_user_default("Company")
    },
    {
      fieldname: "branch",
      label: "Branch",
      fieldtype: "Link",
      options: "Motor Branch",
      get_query: () => ({ filters: { company: frappe.query_report.get_filter_value("company") } })
    },
    {
      fieldname: "expiry_days",
      label: "Expiry Window (Days)",
      fieldtype: "Int",
      default: 60
    },
  ],
};
