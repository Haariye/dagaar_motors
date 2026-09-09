frappe.query_reports["Vehicle Cost"] = {
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
      fieldname: "from_date",
      label: "From Date",
      fieldtype: "Date",
      reqd: 1,
      default: frappe.datetime.add_months(frappe.datetime.get_today(), -12)
    },
    {
      fieldname: "to_date",
      label: "To Date",
      fieldtype: "Date",
      reqd: 1,
      default: frappe.datetime.get_today()
    },
    {
      fieldname: "expense_type",
      label: "Expense Type",
      fieldtype: "Select",
      options: "\nRepair\nMaintenance\nInsurance\nRegistration\nFuel\nWashing\nTires\nParking\nTolls\nFine\nInspection\nGPS\nLicensing\nFinance Charge\nOther"
    },
  ],
};
