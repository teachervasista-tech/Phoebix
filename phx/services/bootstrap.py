"""First-run seeding: default accounts, store settings and sample data."""
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ..domain import rules
from ..domain.security import hash_password


def resolve_date(value, today=None):
    match = re.fullmatch(r"@offset:(-?\d+)", value or "")
    if not match:
        return value
    return ((today or date.today()) + timedelta(days=int(match.group(1)))).isoformat()


def seed_users(repos):
    if repos.users.count():
        return
    now = datetime.now(timezone.utc).isoformat()
    admin_password = os.environ.get("PHOEBIX_ADMIN_PASSWORD")
    repos.users.add("admin", "Arjun Sharma", "admin", hash_password(admin_password or "admin123"),
                    not admin_password, now)
    repos.users.add("cashier", "Priya Nair", "staff", hash_password("cashier123"), True, now)


def seed_sample_data(repos, sample_path):
    if repos.settings.has("seeded"):
        return
    repos.settings.put("seeded", {"at": datetime.now(timezone.utc).isoformat()})
    sample = json.loads(Path(sample_path).read_text(encoding="utf-8"))
    repos.settings.put("store", {**rules.DEFAULT_STORE, **sample["store"], "name": "Phoebix Pharmacy"})
    repos.settings.put("rules", {**rules.DEFAULT_RULES, **sample["rules"]})
    repos.settings.put("bank", rules.DEFAULT_BANK)
    for p in sample["products"]:
        repos.products.add({k: p.get(k, "") for k in ("id", "name", "brand", "category", "hsn", "reorder",
                                                       "price", "mrp", "gst", "emoji", "tone")})
        batches = p.get("batches") or [{"id": f"{p['id']}-batch-1", "batch": p.get("batch", ""),
                                        "expiry": p.get("expiry", ""), "stock": p.get("stock", 0)}]
        for b in batches:
            repos.products.add_batch(b["id"], p["id"], b["batch"], resolve_date(b["expiry"]), b["stock"])
    for c in sample["customers"]:
        repos.customers.add({"address": "", "state": "", "gstin": "", "drugLicense": "", **c})
    for o in sample.get("offers", []):
        repos.offers.add(o["id"], o["name"], o["discount"], o["type"], resolve_date(o["end"]))
    for t in reversed(sample["transactions"]):
        seq = int(re.search(r"(\d+)$", t["id"]).group(1))
        repos.sales.add({**t, "seq": seq, "date": resolve_date(t["date"]), "soldBy": None})


def bootstrap(db, sample_path):
    with db.unit_of_work(write=True) as repos:
        seed_users(repos)
        seed_sample_data(repos, sample_path)
