frappe.query_reports["Active Rentals"] = {
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
      fieldname: "vehicle",
      label: "Vehicle",
      fieldtype: "Link",
      options: "Motor Vehicle"
    },
    {
      fieldname: "customer",
      label: "Customer",
      fieldtype: "Link",
      options: "Customer"
    },
  ],
};
