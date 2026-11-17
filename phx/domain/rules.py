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
SALE_UNITS = ("pack", "loose")
MAX_UNITS_PER_PACK = 1000

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


def pack_size(product):
    return max(1, int(product.get("unitsPerPack") or 1))


def unit_price(product, unit):
    """Price of one sale unit: a full pack, or one loose unit (pack price / units per pack)."""
    if unit == "loose":
        return round(product["price"] / pack_size(product), 2)
    return product["price"]


def base_qty(product, unit, qty):
    """Stock is held in base units (e.g. tablets); a pack consumes units_per_pack of them."""
    return qty if unit == "loose" else qty * pack_size(product)


def format_stock(units, per_pack):
    """'4 strips + 3 tabs' style text for a base-unit count; plain number for single-unit packs."""
    per_pack = max(1, int(per_pack or 1))
    if per_pack == 1:
        return str(units)
    packs, loose = divmod(units, per_pack)
    parts = []
    if packs or not loose:
        parts.append(f"{packs} strip{'s' if packs != 1 else ''}")
    if loose:
        parts.append(f"{loose} tab{'s' if loose != 1 else ''}")
    return " + ".join(parts)


def unit_label(unit, per_pack=1):
    """Short unit name for bills: 'tab' for loose, 'strip' for multi-unit packs, blank for single items."""
    if unit == "loose":
        return "tab"
    return "strip" if (per_pack or 1) > 1 else ""


def parse_units_per_pack(value):
    try:
        n = int(value or 1)
    except (TypeError, ValueError):
        raise ValueError("Units per pack must be a whole number.") from None
    if not 1 <= n <= MAX_UNITS_PER_PACK:
        raise ValueError(f"Units per pack must be between 1 and {MAX_UNITS_PER_PACK}.")
    return n


def truthy(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(value)


GS1_GROUP_SEPARATOR = "\x1d"
# GS1 Application Identifiers seen on medicine packs: fixed-length and variable-length (up to max).
GS1_FIXED = {"00": 18, "01": 14, "02": 14, "11": 6, "13": 6, "15": 6, "16": 6, "17": 6}
GS1_VARIABLE = {"10": 20, "21": 20, "22": 20, "30": 8, "240": 30, "241": 30}
MAX_BARCODE = 48


def normalize_barcode(code):
    """Canonical form for storing/matching: numeric EAN-8/UPC-A/EAN-13/GTIN-14 become 14-digit GTINs."""
    code = "".join((code or "").split()).replace(GS1_GROUP_SEPARATOR, "")
    if code.isdigit() and len(code) in (8, 12, 13, 14):
        return code.zfill(14)
    if len(code) > MAX_BARCODE:
        raise ValueError(f"Barcode must be {MAX_BARCODE} characters or fewer.")
    return code.upper()


def _gs1_date(yymmdd):
    """GS1 dates are YYMMDD; day 00 means the last day of that month."""
    import calendar
    try:
        year, month, day = 2000 + int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
        if day == 0:
            day = calendar.monthrange(year, month)[1]
        return date(year, month, day).isoformat()
    except (ValueError, IndexError):
        return ""


def _parse_gs1(text):
    """Element string ('01…17…10…' with GS separators) or human-readable '(01)…(17)…' form -> {ai: value}."""
    fields = {}
    if text.startswith("("):
        for ai, value in re.findall(r"\((\d{2,4})\)([^(]*)", text):
            fields[ai] = value.strip()
        return fields
    i = 0
    while i < len(text):
        if text[i] == GS1_GROUP_SEPARATOR:
            i += 1
            continue
        ai = next((a for a in (text[i:i + 3], text[i:i + 2]) if a in GS1_FIXED or a in GS1_VARIABLE), None)
        if not ai:
            break
        i += len(ai)
        if ai in GS1_FIXED:
            fields[ai] = text[i:i + GS1_FIXED[ai]]
            i += GS1_FIXED[ai]
        else:
            end = text.find(GS1_GROUP_SEPARATOR, i)
            end = len(text) if end < 0 else end
            fields[ai] = text[i:min(end, i + GS1_VARIABLE[ai])]
            i = min(end, i + GS1_VARIABLE[ai])
    return fields


def parse_scan(raw):
    """What a barcode scanner typed -> {"code", "batch", "expiry"} (batch/expiry only from GS1 2D codes).

    Handles plain EAN/UPC/Code-128, GS1 DataMatrix/GS1-128 element strings (with or without the ]d2/]C1
    symbology prefix) and the bracketed human-readable form printed under the code."""
    text = (raw or "").strip().replace("\r", "").replace("\n", "")
    if re.match(r"^\][A-Za-z]\d", text):
        text = text[3:]
    result = {"code": "", "batch": "", "expiry": "", "raw": text}
    if not text:
        return result
    is_gs1 = text.startswith("(01)") or text.startswith("(02)") or (
        text[:2] in ("01", "02") and len(text) >= 16 and text[2:16].isdigit())
    if is_gs1:
        fields = _parse_gs1(text)
        gtin = fields.get("01") or fields.get("02")
        if gtin and gtin.isdigit() and len(gtin) == 14:
            result["code"] = gtin
            result["batch"] = clean_text(fields.get("10", ""), "Batch", 40)
            result["expiry"] = _gs1_date(fields["17"]) if fields.get("17") else ""
            return result
    result["code"] = normalize_barcode(text)
    return result


def validate_prices(price, mrp):
    try:
        price, mrp = float(price), float(mrp)
    except (TypeError, ValueError):
        raise ValueError("Price and MRP must be numbers.") from None
    if price <= 0 or mrp <= 0:
        raise ValueError("Price and MRP must be greater than zero.")
    if price > mrp:
        raise ValueError("Selling price cannot be higher than MRP.")
    return round(price, 2), round(mrp, 2)


def validate_product(data):
    name = clean_text(data.get("name"), "Product name", 120)
    if not name:
        raise ValueError("Enter the product name.")
    units_per_pack = parse_units_per_pack(data.get("unitsPerPack"))
    allow_loose = truthy(data.get("allowLoose")) and units_per_pack > 1
    try:
        price, mrp = float(data.get("price")), float(data.get("mrp"))
        gst = int(data.get("gst"))
        reorder = int(data.get("reorder") or 0)
        stock = int(data.get("stock") or 0)  # opening stock is entered in packs
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
        "unitsPerPack": units_per_pack, "allowLoose": allow_loose,
        "barcode": normalize_barcode(data.get("barcode")),
        "batch": batch, "expiry": expiry, "stock": stock * units_per_pack,
    }


def validate_date(value, label):
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a date in YYYY-MM-DD format.") from None


def validate_receive(batch, expiry, quantity, existing_batches, units_per_pack=1, loose=0):
    """quantity is in packs, loose in base units; returns (batch, total base units)."""
    batch = clean_text(batch, "Batch", 40)
    if not batch:
        raise ValueError("Enter the batch number.")
    validate_date(expiry, "Expiry")
    if is_expired(expiry):
        raise ValueError("Expiry date cannot be in the past.")
    try:
        quantity = int(quantity or 0)
        loose = int(loose or 0)
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a whole number.") from None
    if quantity < 0 or loose < 0:
        raise ValueError("Quantity cannot be negative.")
    total = quantity * max(1, units_per_pack) + loose
    if total < 1:
        raise ValueError("Quantity must be at least 1.")
    for entry in existing_batches:
        if entry["batch"] == batch and entry["expiry"] != expiry and entry["stock"] > 0:
            raise ValueError("That batch number already exists with a different expiry date.")
    return batch, total


def is_low_stock(product):
    """Reorder level is set in packs; stock is held in base units."""
    return product["stock"] <= product["reorder"] * pack_size(product)


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


def available_batch(product, reserved, on=None, need=1):
    """Earliest-expiry unexpired batch with at least `need` base units beyond what the cart already holds."""
    for batch in sorted(product["batches"], key=lambda b: b["expiry"]):
        if batch["stock"] - reserved.get(batch["id"], 0) >= need and not is_expired(batch["expiry"], on):
            return batch
    return None


def allocate(product, reserved, unit, count, on=None):
    """Split `count` packs or loose units across unexpired batches, earliest expiry first.

    A pack must come whole from one batch. Returns [(batch, qty)] or None if stock is short.
    `reserved` (base units already in the cart, per batch id) is not modified."""
    need_each = base_qty(product, unit, 1)
    left, plan = count, []
    for batch in sorted(product["batches"], key=lambda b: (b["expiry"], b["batch"])):
        if left <= 0:
            break
        if is_expired(batch["expiry"], on):
            continue
        take = min(left, (batch["stock"] - reserved.get(batch["id"], 0)) // need_each)
        if take > 0:
            plan.append((batch, take))
            left -= take
    return plan if left <= 0 else None


def free_units(product, reserved, on=None):
    """Base units still sellable (unexpired, not already in the cart), and whole packs obtainable from them."""
    per_pack = pack_size(product)
    units = packs = 0
    for batch in product["batches"]:
        if is_expired(batch["expiry"], on):
            continue
        free = max(0, batch["stock"] - reserved.get(batch["id"], 0))
        units += free
        packs += free // per_pack
    return units, packs


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
