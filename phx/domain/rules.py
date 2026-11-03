"""Pure business rules. No I/O, no database, no UI."""
import math
import re
from datetime import date, timedelta

GST_RATES = (0, 5, 12, 18, 28)
PAYMENT_METHODS = ("Cash", "UPI", "Card", "Credit")
ONLINE_METHODS = ("UPI", "Card")
ACCOUNT_TYPES = ("Current", "Savings", "Overdraft", "Cash credit")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
GSTIN_PATTERN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\dZ[A-Z0-9]$")
IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
NEAR_EXPIRY_DAYS = 90

DEFAULT_STORE = {
    "name": "Phoebix Pharmacy", "branch": "Store 01", "address": "", "city": "", "state": "",
    "pincode": "", "phone": "", "gstin": "", "drugLicense": "", "invoicePrefix": "INV",
}
DEFAULT_BANK = {
    "accountHolder": "", "bankName": "", "branch": "", "accountNumber": "", "ifsc": "",
    "accountType": "Current", "upiId": "",
}
DEFAULT_RULES = {
    "earnPer": 100, "pointsPerRupee": 1, "redeemMaxPercent": 20,
    "birthday": True, "wellness": True, "refill": False,
}


def today():
    return date.today().isoformat()


def tier_for(spent):
    return "Gold" if spent >= 10000 else "Silver" if spent >= 5000 else "Member"


def is_expired(expiry, on=None):
    return expiry < (on or today())


def is_near_expiry(expiry, on=None):
    base = date.fromisoformat(on) if on else date.today()
    return expiry <= (base + timedelta(days=NEAR_EXPIRY_DAYS)).isoformat()


def initials_for(name):
    return "".join(part[0] for part in name.split()[:2]).upper() or "?"


def clean_text(value, label, limit):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    value = " ".join(value.split())
    if len(value) > limit:
        raise ValueError(f"{label} must be {limit} characters or fewer.")
    return value


def digits(value):
    return re.sub(r"\D", "", value or "")


def validate_customer(data, existing_phones=()):
    name = clean_text(data.get("name"), "Name", 80)
    if not name:
        raise ValueError("Enter the customer's name.")
    phone = clean_text(data.get("phone"), "Phone", 20)
    phone_digits = digits(phone)
    if not 10 <= len(phone_digits) <= 13:
        raise ValueError("Enter a valid phone number (10-13 digits).")
    if phone_digits[-10:] in {digits(p)[-10:] for p in existing_phones}:
        raise ValueError("A customer with this phone number already exists.")
    gstin = clean_text(data.get("gstin"), "GSTIN", 15).upper()
    if gstin and not GSTIN_PATTERN.match(gstin):
        raise ValueError("Enter a valid 15-character GSTIN or leave it blank.")
    return {
        "name": name, "phone": phone,
        "email": clean_text(data.get("email"), "Email", 120) or "—",
        "address": clean_text(data.get("address"), "Address", 200),
        "state": clean_text(data.get("state"), "State", 60),
        "gstin": gstin,
        "drugLicense": clean_text(data.get("drugLicense"), "Drug license", 40),
        "initials": initials_for(name),
    }


def validate_product(data):
    name = clean_text(data.get("name"), "Product name", 120)
    if not name:
        raise ValueError("Enter the product name.")
    try:
        price, mrp = float(data.get("price")), float(data.get("mrp"))
        gst = int(data.get("gst"))
        reorder = int(data.get("reorder") or 0)
        stock = int(data.get("stock") or 0)
    except (TypeError, ValueError):
        raise ValueError("Price, MRP, GST, reorder level and stock must be numbers.") from None
    if price <= 0 or mrp <= 0:
        raise ValueError("Price and MRP must be greater than zero.")
    if price > mrp:
        raise ValueError("Selling price cannot be higher than MRP.")
    if gst not in GST_RATES:
        raise ValueError("GST must be 0, 5, 12, 18 or 28 percent.")
    if reorder < 0 or stock < 0:
        raise ValueError("Reorder level and stock cannot be negative.")
    batch = clean_text(data.get("batch"), "Batch", 40)
    expiry = clean_text(data.get("expiry"), "Expiry", 10)
    if stock:
        if not batch:
            raise ValueError("Enter a batch number for the opening stock.")
        validate_date(expiry, "Expiry")
        if is_expired(expiry):
            raise ValueError("Expiry date cannot be in the past.")
    return {
        "name": name, "brand": clean_text(data.get("brand"), "Brand", 120),
        "category": clean_text(data.get("category"), "Category", 40) or "Others",
        "hsn": clean_text(data.get("hsn"), "HSN", 12), "price": price, "mrp": mrp, "gst": gst,
        "reorder": reorder, "emoji": "💊", "tone": "thumb-blue",
        "batch": batch, "expiry": expiry, "stock": stock,
    }


def validate_date(value, label):
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a date in YYYY-MM-DD format.") from None


def validate_receive(batch, expiry, quantity, existing_batches):
    batch = clean_text(batch, "Batch", 40)
    if not batch:
        raise ValueError("Enter the batch number.")
    validate_date(expiry, "Expiry")
    if is_expired(expiry):
        raise ValueError("Expiry date cannot be in the past.")
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a whole number.") from None
    if quantity < 1:
        raise ValueError("Quantity must be at least 1.")
    for entry in existing_batches:
        if entry["batch"] == batch and entry["expiry"] != expiry and entry["stock"] > 0:
            raise ValueError("That batch number already exists with a different expiry date.")
    return batch, quantity


def validate_rules(data):
    try:
        points, earn, cap = int(data["pointsPerRupee"]), int(data["earnPer"]), int(data["redeemMaxPercent"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Reward values must be whole numbers.") from None
    if not 1 <= points <= 10:
        raise ValueError("Points per step must be between 1 and 10.")
    if earn < 1:
        raise ValueError("Spend per step must be at least ₹1.")
    if not 1 <= cap <= 100:
        raise ValueError("Maximum redemption must be between 1% and 100%.")
    return {"pointsPerRupee": points, "earnPer": earn, "redeemMaxPercent": cap}


def validate_offer(name, discount, kind, end):
    name = clean_text(name, "Offer name", 60)
    if not name:
        raise ValueError("Enter the offer name.")
    try:
        discount = float(discount)
    except (TypeError, ValueError):
        raise ValueError("Discount must be a number.") from None
    if kind not in ("percent", "fixed"):
        raise ValueError("Offer type must be percent or fixed.")
    if discount <= 0 or (kind == "percent" and discount > 100) or discount > 100000:
        raise ValueError("Enter a valid discount amount.")
    return name, discount, kind, validate_date(end, "End date")


def validate_store(data):
    store = dict(DEFAULT_STORE)
    for key, limit in (("name", 80), ("branch", 40), ("address", 200), ("city", 60), ("state", 60),
                       ("pincode", 10), ("phone", 20), ("drugLicense", 40), ("invoicePrefix", 10)):
        store[key] = clean_text(data.get(key, store[key]), key, limit)
    if not store["name"] or not store["invoicePrefix"]:
        raise ValueError("Store name and invoice prefix are required.")
    gstin = clean_text(data.get("gstin"), "GSTIN", 15).upper()
    if gstin and not GSTIN_PATTERN.match(gstin):
        raise ValueError("Enter a valid 15-character GSTIN or leave it blank.")
    store["gstin"] = gstin
    return store


def validate_bank(data):
    bank = {key: clean_text(data.get(key), key, 80) for key in DEFAULT_BANK}
    bank["ifsc"] = bank["ifsc"].upper().replace(" ", "")
    bank["accountNumber"] = bank["accountNumber"].replace(" ", "")
    bank["upiId"] = bank["upiId"].replace(" ", "")
    if not bank["accountType"]:
        bank["accountType"] = "Current"
    if bank["accountType"] not in ACCOUNT_TYPES:
        raise ValueError("Choose a valid account type.")
    if bank["accountNumber"] and not re.fullmatch(r"\d{9,18}", bank["accountNumber"]):
        raise ValueError("Account number must be 9-18 digits.")
    if bank["ifsc"] and not IFSC_PATTERN.match(bank["ifsc"]):
        raise ValueError("Enter a valid 11-character IFSC (for example HDFC0001234).")
    if bank["upiId"] and not re.fullmatch(r"[\w.\-]{2,64}@[A-Za-z][A-Za-z0-9]{1,31}", bank["upiId"]):
        raise ValueError("Enter a valid UPI ID such as store@bank.")
    if any(bank[key] for key in ("accountNumber", "ifsc", "bankName")) and not (
        bank["accountHolder"] and bank["bankName"] and bank["accountNumber"] and bank["ifsc"]
    ):
        raise ValueError("Enter account holder, bank, account number and IFSC together.")
    return bank


def validate_password(password):
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise ValueError("Password must be 8-128 characters.")
    return password


def available_batch(product, reserved, on=None):
    """Earliest-expiry unexpired batch with stock beyond what the cart already holds."""
    for batch in sorted(product["batches"], key=lambda b: b["expiry"]):
        if batch["stock"] > reserved.get(batch["id"], 0) and not is_expired(batch["expiry"], on):
            return batch
    return None


def active_offer(offers, offer_id, on=None):
    on = on or today()
    return next((o for o in offers if o["id"] == offer_id and o["enabled"] and o["end"] >= on), None)


def cart_totals(lines, rules, customer=None, offer=None, manual=None, redeem_input=0):
    """manual = (kind, value) with kind in percent/fixed; an offer overrides it."""
    subtotal = sum(l["qty"] * l["price"] for l in lines)
    if offer:
        kind, value = offer["type"], offer["discount"]
    elif manual:
        kind, value = manual
    else:
        kind, value = "fixed", 0
    raw = subtotal * value / 100 if kind == "percent" else value
    discount = min(max(raw, 0), subtotal)
    taxable = subtotal - discount
    ratio = taxable / subtotal if subtotal else 0
    tax = sum(l["qty"] * l["price"] * ratio * l["gst"] / 100 for l in lines)
    gross = taxable + tax
    max_redeem = min(customer["points"], math.floor(gross * rules["redeemMaxPercent"] / 100)) if customer else 0
    redeem = max(0, min(max_redeem, int(redeem_input or 0)))
    return {
        "subtotal": round(subtotal, 2), "discount": round(discount, 2), "taxable": round(taxable, 2),
        "tax": round(tax, 2), "gross": round(gross, 2), "maxRedeem": max_redeem, "redeem": redeem,
        "total": round(max(0.0, gross - redeem), 2),
    }


def points_earned(totals, rules, customer):
    if not customer:
        return 0
    return math.floor((totals["subtotal"] - totals["discount"]) / rules["earnPer"]) * rules["pointsPerRupee"]


def is_intra_state(store, customer):
    state = (customer or {}).get("state", "")
    return not state or state.strip().lower() == store.get("state", "").strip().lower()


def invoice_lines(lines, totals, intra):
    """Per-line GST breakup used by the invoice."""
    subtotal = totals["subtotal"] or 1
    ratio = totals["taxable"] / subtotal
    result = []
    for line in lines:
        gross = line["qty"] * line["price"]
        taxable = gross * ratio
        tax = taxable * line["gst"] / 100
        result.append({**line, "amount": gross, "taxable": round(taxable, 2), "tax": round(tax, 2),
                       "cgst": round(tax / 2, 2) if intra else 0, "sgst": round(tax / 2, 2) if intra else 0,
                       "igst": 0 if intra else round(tax, 2)})
    return result
