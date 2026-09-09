frappe.query_reports["Deposit Liability"] = {
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
      fieldname: "status",
      label: "Status",
      fieldtype: "Select",
      options: "\nRequired\nPending\nPartially Collected\nHeld\nPartially Used\nRefund Pending"
    },
  ],
};
