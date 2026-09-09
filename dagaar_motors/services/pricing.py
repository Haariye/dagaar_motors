from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate

from dagaar_motors.services.discounts import validate_discount
from dagaar_motors.services.settings import get_settings_dict, resolve_company, resolve_currency
from dagaar_motors.utils.dates import Duration, calculate_duration
from dagaar_motors.utils.money import percent, quantize


@dataclass
class PricingContext:
    pickup_datetime: Any
    return_datetime: Any
    company: str | None = None
    branch: str | None = None
    currency: str | None = None
    vehicle: str | None = None
    vehicle_category: str | None = None
    rental_type: str | None = None
    customer: str | None = None
    customer_group: str | None = None
    territory: str | None = None
    booking_channel: str | None = None
    promo_code: str | None = None
    pickup_location: str | None = None
    return_location: str | None = None
    one_way: bool = False
    estimated_km: float = 0
    discount_percent: float = 0
    fixed_discount: float = 0
    additional_charges: float = 0
    approved_by: str | None = None
    user: str | None = None
    extras: list[dict] = field(default_factory=list)

    @classmethod
    def from_value(cls, value: dict | str | "PricingContext") -> "PricingContext":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            value = frappe.parse_json(value)
        value = dict(value or {})
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value.get(key) for key in allowed if key in value})


@dataclass
class PricingLine:
    component: str
    description: str
    quantity: float
    rate: float
    amount: float
    rule: str | None = None


@dataclass
class PricingResult:
    currency: str
    pricing_rule: str | None
    rate_basis: str
    billable_units: float
    duration_label: str
    base_rate: float
    base_amount: float
    extras_amount: float
    automatic_discount: float
    user_discount: float
    surcharge_amount: float
    net_amount: float
    tax_template: str | None
    tax_amount: float
    grand_total: float
    included_km: float
    excess_km_rate: float
    deposit_required: float
    approval_required: bool
    lines: list[PricingLine]
    explanation: str

    def as_dict(self) -> dict:
        data = asdict(self)
        data["lines"] = [asdict(line) for line in self.lines]
        data["snapshot"] = json.dumps(data, default=str, sort_keys=True)
        return data


RULE_FIELDS = [
    "name",
    "rule_name",
    "enabled",
    "priority",
    "company",
    "branch",
    "currency",
    "vehicle",
    "vehicle_category",
    "rental_type",
    "customer",
    "customer_group",
    "territory",
    "booking_channel",
    "promo_code",
    "pickup_location",
    "return_location",
    "one_way",
    "valid_from",
    "valid_to",
    "rate_basis",
    "rate",
    "minimum_charge",
    "included_km",
    "excess_km_rate",
    "whole_duration_pricing",
    "tax_template",
    "rates_include_tax",
    "discount_type",
    "discount_value",
    "surcharge_type",
    "surcharge_value",
    "weekend_adjustment_percent",
    "seasonal_pricing_rule",
    "explanation",
]

MATCH_WEIGHTS = {
    "vehicle": 100,
    "customer": 90,
    "customer_group": 80,
    "vehicle_category": 70,
    "rental_type": 60,
    "branch": 50,
    "territory": 40,
    "promo_code": 35,
    "booking_channel": 30,
    "pickup_location": 20,
    "return_location": 20,
    "company": 10,
    "currency": 10,
}


def calculate_price(context: dict | str | PricingContext) -> dict:
    ctx = PricingContext.from_value(context)
    ctx.company = resolve_company(ctx.company)
    ctx.currency = resolve_currency(ctx.company, ctx.currency)
    _fill_context_from_links(ctx)

    settings = get_settings_dict()
    try:
        duration = calculate_duration(
            ctx.pickup_datetime,
            ctx.return_datetime,
            rounding_minutes=cint(settings.get("rounding_minutes")),
            grace_minutes=cint(settings.get("grace_period_minutes")),
        )
    except ValueError as exc:
        frappe.throw(_(str(exc)))

    minimum_hours = max(flt(settings.get("minimum_rental_hours")), flt(settings.get("minimum_rental_duration_hours")))
    if minimum_hours and duration.hours < minimum_hours:
        frappe.throw(_("Minimum rental duration is {0} hours.").format(minimum_hours))
    maximum_days = cint(settings.get("maximum_rental_duration_days"))
    if maximum_days and duration.days > maximum_days:
        frappe.throw(_("Maximum rental duration is {0} days.").format(maximum_days))

    rule = resolve_pricing_rule(ctx)
    if rule:
        rule_doc = frappe.get_cached_doc("Rental Pricing Rule", rule.name)
        rate_basis = rule.rate_basis
        base_rate = flt(rule.rate)
        included_km = flt(rule.included_km)
        excess_km_rate = flt(rule.excess_km_rate)
        tax_template = rule.tax_template or settings.get("default_tax_template")
        minimum_charge = flt(rule.minimum_charge)
    else:
        rule_doc = None
        rate_basis, base_rate, included_km, excess_km_rate = _fallback_rate(ctx)
        tax_template = settings.get("default_tax_template")
        minimum_charge = 0

    units, duration_label = _billable_units(rate_basis, duration, ctx.estimated_km)
    base_amount, tier_lines, effective_rate = _calculate_base_amount(rule_doc, rate_basis, units, base_rate)
    base_amount = max(base_amount, minimum_charge)
    lines = [
        PricingLine(
            component="Base Rate",
            description=f"{duration_label} at {effective_rate:g} per {rate_basis.lower()}",
            quantity=units,
            rate=effective_rate,
            amount=base_amount,
            rule=rule.name if rule else None,
        )
    ]
    lines.extend(tier_lines)

    season_amount = _seasonal_adjustment(rule_doc, ctx, base_amount)
    if season_amount:
        lines.append(PricingLine("Seasonal Adjustment", "Configured seasonal rule", 1, season_amount, season_amount, rule.name if rule else None))

    weekend_amount = _weekend_adjustment(rule_doc, ctx, duration, base_rate, base_amount)
    if weekend_amount:
        lines.append(PricingLine("Weekend Adjustment", "Configured weekend pricing", 1, weekend_amount, weekend_amount, rule.name if rule else None))

    automatic_discount = 0.0
    surcharge_amount = 0.0
    if rule:
        if rule.discount_type == "Percentage":
            automatic_discount = percent(base_amount + season_amount + weekend_amount, rule.discount_value, _precision(settings))
        elif rule.discount_type == "Fixed":
            automatic_discount = flt(rule.discount_value)
        if automatic_discount:
            lines.append(PricingLine("Automatic Discount", "Pricing rule discount", 1, -automatic_discount, -automatic_discount, rule.name))

        if rule.surcharge_type == "Percentage":
            surcharge_amount = percent(base_amount, rule.surcharge_value, _precision(settings))
        elif rule.surcharge_type == "Fixed":
            surcharge_amount = flt(rule.surcharge_value)
        if surcharge_amount:
            lines.append(PricingLine("Surcharge", "Pricing rule surcharge", 1, surcharge_amount, surcharge_amount, rule.name))

    extras_amount, extra_lines = _price_extras(ctx.extras, duration, settings)
    lines.extend(extra_lines)

    subtotal_before_user_discount = max(
        0,
        base_amount + season_amount + weekend_amount + surcharge_amount + extras_amount - automatic_discount,
    )
    discount = validate_discount(
        base_amount=subtotal_before_user_discount,
        discount_percent=ctx.discount_percent,
        fixed_discount=ctx.fixed_discount,
        company=ctx.company,
        branch=ctx.branch,
        user=ctx.user,
        approved_by=ctx.approved_by,
    )
    user_discount = min(subtotal_before_user_discount, flt(discount["discount_amount"]))
    if user_discount:
        lines.append(PricingLine("Authorized Discount", "User-entered commercial discount", 1, -user_discount, -user_discount))

    # Manual charges from the Charges table are added after the commercial
    # discount (they are not discountable) but remain part of the taxable base.
    additional_charges = max(0.0, flt(ctx.additional_charges))
    if additional_charges:
        lines.append(PricingLine("Additional Charges", "Charges entered on the agreement", 1, additional_charges, additional_charges))

    net_amount = quantize(subtotal_before_user_discount - user_discount + additional_charges, _precision(settings))
    tax_amount = estimate_taxes(tax_template, net_amount, bool(rule and rule.rates_include_tax) or bool(settings.get("rates_include_tax")))
    grand_total = quantize(net_amount + tax_amount, _precision(settings))

    deposit_required = _resolve_deposit(ctx, duration, grand_total)
    explanation = _build_explanation(lines, ctx.currency, tax_template)

    result = PricingResult(
        currency=ctx.currency,
        pricing_rule=rule.name if rule else None,
        rate_basis=rate_basis,
        billable_units=units,
        duration_label=duration_label,
        base_rate=effective_rate,
        base_amount=quantize(base_amount, _precision(settings)),
        extras_amount=quantize(extras_amount, _precision(settings)),
        automatic_discount=quantize(automatic_discount, _precision(settings)),
        user_discount=quantize(user_discount, _precision(settings)),
        surcharge_amount=quantize(surcharge_amount + season_amount + weekend_amount, _precision(settings)),
        net_amount=net_amount,
        tax_template=tax_template,
        tax_amount=tax_amount,
        grand_total=grand_total,
        included_km=included_km,
        excess_km_rate=excess_km_rate,
        deposit_required=deposit_required,
        approval_required=bool(discount["approval_required"]),
        lines=lines,
        explanation=explanation,
    )
    return result.as_dict()


def resolve_pricing_rule(ctx: PricingContext):
    values = frappe.db.sql(
        """
        select {fields}
        from `tabRental Pricing Rule`
        where enabled = 1
          and (company is null or company = '' or company = %(company)s)
          and (branch is null or branch = '' or branch = %(branch)s)
          and (currency is null or currency = '' or currency = %(currency)s)
          and (valid_from is null or valid_from <= %(pickup_date)s)
          and (valid_to is null or valid_to >= %(pickup_date)s)
        order by priority desc, modified desc
        """.format(fields=", ".join(f"`{field}`" for field in RULE_FIELDS)),
        {
            "company": ctx.company,
            "branch": ctx.branch or "",
            "currency": ctx.currency,
            "pickup_date": getdate(ctx.pickup_datetime),
        },
        as_dict=True,
    )

    matches = []
    for rule in values:
        score = _match_score(rule, ctx)
        if score is not None:
            matches.append((cint(rule.priority), score, rule))
    if not matches:
        return None
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    top = matches[0]
    conflicts = [item for item in matches[1:] if item[0] == top[0] and item[1] == top[1]]
    for conflict in conflicts:
        other = conflict[2]
        if (other.rate_basis, flt(other.rate)) != (top[2].rate_basis, flt(top[2].rate)):
            frappe.throw(
                _("Ambiguous pricing rules {0} and {1} have equal priority and specificity.").format(
                    top[2].name, other.name
                )
            )
    return top[2]


def _match_score(rule, ctx: PricingContext) -> int | None:
    score = 0
    for fieldname, weight in MATCH_WEIGHTS.items():
        expected = rule.get(fieldname)
        actual = getattr(ctx, fieldname, None)
        if expected not in (None, ""):
            if str(expected) != str(actual or ""):
                return None
            score += weight
    if cint(rule.one_way) and not ctx.one_way:
        return None
    if cint(rule.one_way):
        score += 15
    return score


def _fill_context_from_links(ctx: PricingContext):
    if ctx.vehicle:
        vehicle = frappe.get_cached_doc("Motor Vehicle", ctx.vehicle)
        ctx.vehicle_category = ctx.vehicle_category or vehicle.category or vehicle.rental_category
        ctx.branch = ctx.branch or vehicle.branch
        ctx.company = ctx.company or vehicle.company
    if ctx.customer:
        ctx.customer_group = ctx.customer_group or frappe.get_cached_value("Customer", ctx.customer, "customer_group")
        ctx.territory = ctx.territory or frappe.get_cached_value("Customer", ctx.customer, "territory")


def _fallback_rate(ctx: PricingContext):
    settings = get_settings_dict()
    vehicle = frappe.get_cached_doc("Motor Vehicle", ctx.vehicle) if ctx.vehicle else None
    category_name = ctx.vehicle_category or (vehicle.category if vehicle else None)
    category = frappe.get_cached_doc("Vehicle Category", category_name) if category_name else None
    rental_type = frappe.get_cached_doc("Rental Type", ctx.rental_type) if ctx.rental_type else None
    rate_basis = (rental_type.billing_method if rental_type else None) or "Daily"
    base_rate = flt(vehicle.base_daily_rate if vehicle else 0) or flt(category.base_daily_rate if category else 0)
    if not base_rate:
        frappe.throw(_("No valid pricing rule or fallback rate was found for this rental."))
    included_km = (
        flt(vehicle.included_km_per_day if vehicle else 0)
        or flt(category.included_km_per_day if category else 0)
        or flt(settings.get("default_included_km_per_day"))
    )
    excess_rate = (
        flt(vehicle.excess_km_rate if vehicle else 0)
        or flt(category.excess_km_rate if category else 0)
        or flt(settings.get("default_excess_km_rate"))
    )
    return rate_basis, base_rate, included_km, excess_rate


def _billable_units(rate_basis: str, duration: Duration, estimated_km: float):
    if rate_basis == "Hourly":
        units = max(1, math.ceil(duration.hours))
        return float(units), f"{units:g} hour(s)"
    if rate_basis == "Weekly":
        units = max(1, math.ceil(duration.weeks))
        return float(units), f"{units:g} week(s)"
    if rate_basis == "Monthly":
        units = max(1, math.ceil(duration.months))
        return float(units), f"{units:g} month(s)"
    if rate_basis == "Fixed Trip":
        return 1.0, "Fixed trip"
    if rate_basis == "Kilometer":
        if flt(estimated_km) <= 0:
            frappe.throw(_("Estimated kilometers are required for kilometer-based pricing."))
        return flt(estimated_km), f"{flt(estimated_km):g} km"
    units = max(1, math.ceil(duration.days))
    return float(units), f"{units:g} day(s)"


def _calculate_base_amount(rule_doc, rate_basis: str, units: float, base_rate: float):
    if not rule_doc or not rule_doc.get("duration_tiers"):
        return units * base_rate, [], base_rate

    tiers = sorted(rule_doc.duration_tiers, key=lambda row: flt(row.from_units))
    if cint(rule_doc.whole_duration_pricing):
        selected = None
        for tier in tiers:
            if units >= flt(tier.from_units) and (not flt(tier.to_units) or units <= flt(tier.to_units)):
                selected = tier
        if selected:
            rate = flt(selected.rate) or base_rate
            amount = units * rate
            line = PricingLine(
                component="Duration Tier",
                description=selected.label or f"Tier from {selected.from_units} units",
                quantity=units,
                rate=rate,
                amount=0,
                rule=rule_doc.name,
            )
            return amount, [line], rate
        return units * base_rate, [], base_rate

    remaining = units
    amount = 0.0
    lines = []
    for tier in tiers:
        if remaining <= 0:
            break
        start = max(1, flt(tier.from_units))
        end = flt(tier.to_units) or units
        tier_capacity = max(0, end - start + 1)
        if units < start:
            continue
        tier_units = min(remaining, tier_capacity)
        rate = flt(tier.rate) or base_rate
        tier_amount = tier_units * rate
        amount += tier_amount
        remaining -= tier_units
        lines.append(PricingLine("Duration Tier", tier.label or f"Units {start:g}-{end:g}", tier_units, rate, tier_amount, rule_doc.name))
    if remaining > 0:
        amount += remaining * base_rate
        lines.append(PricingLine("Base Remainder", "Units outside configured tiers", remaining, base_rate, remaining * base_rate, rule_doc.name))
    effective_rate = amount / units if units else base_rate
    return amount, lines, effective_rate


def _seasonal_adjustment(rule_doc, ctx: PricingContext, amount: float) -> float:
    if not rule_doc or not rule_doc.seasonal_pricing_rule:
        return 0.0
    season = frappe.get_cached_doc("Seasonal Pricing Rule", rule_doc.seasonal_pricing_rule)
    if not season.enabled or not _season_applies(season, getdate(ctx.pickup_datetime)):
        return 0.0
    if season.adjustment_type == "Percentage":
        return amount * flt(season.adjustment_value) / 100
    return flt(season.adjustment_value)


def _season_applies(season, date_value) -> bool:
    start = getdate(season.start_date)
    end = getdate(season.end_date)
    if cint(season.recurring_annually):
        candidate = (date_value.month, date_value.day)
        start_pair = (start.month, start.day)
        end_pair = (end.month, end.day)
        applies = start_pair <= candidate <= end_pair if start_pair <= end_pair else candidate >= start_pair or candidate <= end_pair
    else:
        applies = start <= date_value <= end
    if not applies:
        return False
    weekdays = {day.strip().lower() for day in (season.weekdays or "").split(",") if day.strip()}
    return not weekdays or date_value.strftime("%A").lower() in weekdays


def _weekend_adjustment(rule_doc, ctx: PricingContext, duration: Duration, rate: float, amount: float) -> float:
    if not rule_doc or not flt(rule_doc.weekend_adjustment_percent):
        return 0.0
    weekend_names = {
        day.strip().lower()
        for day in (get_settings_dict().get("weekend_days") or "Saturday,Sunday").split(",")
        if day.strip()
    }
    days = max(1, math.ceil(duration.days))
    start = get_datetime(ctx.pickup_datetime).date()
    weekend_count = sum((start + timedelta(days=index)).strftime("%A").lower() in weekend_names for index in range(days))
    if not weekend_count:
        return 0.0
    if rule_doc.rate_basis == "Daily":
        return rate * weekend_count * flt(rule_doc.weekend_adjustment_percent) / 100
    return amount * flt(rule_doc.weekend_adjustment_percent) / 100


def _price_extras(extras: list[dict] | None, duration: Duration, settings: dict):
    total = 0.0
    lines = []
    for requested in extras or []:
        extra_name = requested.get("rental_extra") or requested.get("name")
        if not extra_name:
            continue
        extra = frappe.get_cached_doc("Rental Extra", extra_name)
        if not extra.active:
            frappe.throw(_("Rental Extra {0} is disabled.").format(extra_name))
        quantity = max(0, flt(requested.get("quantity") or 1))
        basis_units = _extra_units(extra.price_basis, duration)
        rate = flt(requested.get("rate")) or flt(extra.rate)
        amount = quantity * basis_units * rate
        total += amount
        lines.append(
            PricingLine(
                component="Extra",
                description=extra.extra_name,
                quantity=quantity * basis_units,
                rate=rate,
                amount=quantize(amount, _precision(settings)),
                rule=extra.name,
            )
        )
    return quantize(total, _precision(settings)), lines


def _extra_units(price_basis: str, duration: Duration) -> float:
    return {
        "Fixed": 1,
        "Hourly": max(1, math.ceil(duration.hours)),
        "Daily": max(1, math.ceil(duration.days)),
        "Weekly": max(1, math.ceil(duration.weeks)),
        "Monthly": max(1, math.ceil(duration.months)),
        "Quantity": 1,
    }.get(price_basis, 1)


def estimate_taxes(tax_template: str | None, net_amount: float, rates_include_tax: bool = False) -> float:
    if not tax_template:
        return 0.0
    template = frappe.get_cached_doc("Sales Taxes and Charges Template", tax_template)
    running_total = flt(net_amount)
    row_amounts: dict[int, float] = {}
    total_tax = 0.0
    for row in template.taxes:
        amount = 0.0
        if row.charge_type == "Actual":
            amount = flt(row.tax_amount)
        elif row.charge_type == "On Net Total":
            amount = running_total * flt(row.rate) / 100
        elif row.charge_type == "On Previous Row Total":
            amount = (running_total + total_tax) * flt(row.rate) / 100
        elif row.charge_type == "On Previous Row Amount":
            amount = row_amounts.get(cint(row.row_id), 0) * flt(row.rate) / 100
        row_amounts[cint(row.idx)] = amount
        total_tax += amount
    if rates_include_tax and total_tax:
        # Preserve the quoted gross amount while exposing the estimated embedded tax.
        effective_rate = total_tax / max(net_amount, 1)
        return quantize(net_amount - (net_amount / (1 + effective_rate)), _precision(get_settings_dict()))
    return quantize(total_tax, _precision(get_settings_dict()))


def _resolve_deposit(ctx: PricingContext, duration: Duration, total: float) -> float:
    from dagaar_motors.services.deposits import resolve_required_deposit

    return resolve_required_deposit(
        {
            "company": ctx.company,
            "branch": ctx.branch,
            "vehicle": ctx.vehicle,
            "vehicle_category": ctx.vehicle_category,
            "rental_type": ctx.rental_type,
            "customer": ctx.customer,
            "duration_days": max(1, math.ceil(duration.days)),
            "rental_total": total,
        }
    )["amount"]


def _build_explanation(lines: list[PricingLine], currency: str, tax_template: str | None) -> str:
    parts = [f"{line.component}: {line.amount:,.2f} {currency}" for line in lines]
    if tax_template:
        parts.append(f"Taxes: {tax_template}")
    return " | ".join(parts)


def _precision(settings: dict) -> int:
    return max(0, cint(settings.get("currency_precision") or 2))


def apply_result_to_document(doc, result: dict):
    mapping = {
        "currency": "currency",
        "pricing_rule": "pricing_rule",
        "base_rate": "base_rate",
        "base_amount": "base_amount",
        "extras_amount": "extras_amount",
        "user_discount": "discount_amount",
        "net_amount": "net_amount",
        "tax_template": "tax_template",
        "tax_amount": "tax_amount",
        "grand_total": "grand_total",
        "deposit_required": "deposit_required",
        "duration_label": "duration_label",
        "billable_units": "duration_units",
        "snapshot": "pricing_snapshot",
    }
    for source, target in mapping.items():
        if doc.meta.has_field(target):
            doc.set(target, result.get(source))
    if doc.meta.has_field("pricing_breakdown"):
        doc.set("pricing_breakdown", [])
        for index, line in enumerate(result.get("lines") or [], start=1):
            doc.append(
                "pricing_breakdown",
                {
                    "sequence": index,
                    "component": line.get("component"),
                    "description": line.get("description"),
                    "quantity": line.get("quantity"),
                    "rate": line.get("rate"),
                    "amount": line.get("amount"),
                    "rule": line.get("rule"),
                },
            )
    return doc