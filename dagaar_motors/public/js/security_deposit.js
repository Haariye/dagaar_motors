frappe.ui.form.on("Security Deposit", {
  refresh(frm) {
    if (frm.is_new()) return;

    const required = Number(frm.doc.amount_required || 0);
    const received = Number(frm.doc.amount_received || 0);
    const available = Number(frm.doc.balance || 0);
    const remaining = Math.max(0, required - received);
    const closed = ["Waived", "Cancelled"].includes(frm.doc.status);

    if (!closed && remaining > 0) {
      frm.add_custom_button(
        __("Collect"),
        () => deposit_action(frm, "Collection"),
        __("Transactions")
      );
    }

    if (available > 0) {
      frm.add_custom_button(
        __("Allocate"),
        () => deposit_action(frm, "Allocation"),
        __("Transactions")
      );
      frm.add_custom_button(
        __("Refund"),
        () => deposit_action(frm, "Refund"),
        __("Transactions")
      );
      frm.add_custom_button(
        __("Forfeit"),
        () => deposit_action(frm, "Forfeiture"),
        __("Transactions")
      );
    }

    const approvalRoles = [
      "Dagaar Motors Rental Manager",
      "Dagaar Motors Branch Manager",
      "Dagaar Motors Administrator",
      "System Manager",
    ];
    const canWaive = approvalRoles.some((role) => (frappe.user_roles || []).includes(role));
    if (canWaive && received <= 0 && !closed) {
      frm.add_custom_button(
        __("Approve Waiver"),
        () => deposit_action(frm, "Waiver"),
        __("Transactions")
      );
    }
  },
});

function deposit_action(frm, transactionType) {
  const requestToken =
    window.crypto?.randomUUID?.() ||
    `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
  const isCollection = transactionType === "Collection";
  const isWaiver = transactionType === "Waiver";
  const defaultAmount = isCollection
    ? Math.max(0, Number(frm.doc.amount_required || 0) - Number(frm.doc.amount_received || 0))
    : isWaiver
      ? Number(frm.doc.amount_required || 0)
      : Number(frm.doc.balance || 0);

  const dialog = new frappe.ui.Dialog({
    title: __(`${transactionType} Security Deposit`),
    fields: [
      {
        fieldname: "available",
        label: __("Collected and Available"),
        fieldtype: "Currency",
        default: frm.doc.balance,
        read_only: 1,
      },
      {
        fieldname: "amount",
        label: __("Amount"),
        fieldtype: "Currency",
        reqd: 1,
        default: defaultAmount,
        read_only: isWaiver ? 1 : 0,
      },
      {
        fieldname: "payment_method",
        label: __("Payment Method"),
        fieldtype: "Link",
        options: "Mode of Payment",
        depends_on: `eval:${JSON.stringify(!isWaiver)}`,
      },
      {
        fieldname: "reference_number",
        label: __("Reference Number"),
        fieldtype: "Data",
        depends_on: `eval:${JSON.stringify(!isWaiver)}`,
      },
      {
        fieldname: "sales_invoice",
        label: __("Sales Invoice"),
        fieldtype: "Link",
        options: "Sales Invoice",
        depends_on: `eval:${JSON.stringify(transactionType === "Allocation")}`,
      },
      { fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text", reqd: isWaiver ? 1 : 0 },
    ],
    primary_action_label: __("Post Transaction"),
    async primary_action(values) {
      await dagaar_motors.ui.call("dagaar_motors.api.deposits.transact", {
        security_deposit: frm.doc.name,
        transaction_type: transactionType,
        request_token: requestToken,
        ...values,
      });
      dialog.hide();
      frm.reload_doc();
    },
  });
  dialog.show();
}
