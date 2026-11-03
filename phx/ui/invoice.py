"""Invoice preview window with print (via the default browser) and save-as-HTML."""
import html
import os
import tempfile
import tkinter as tk
import webbrowser
from tkinter import filedialog, ttk

from . import theme
from .theme import inr


def invoice_html(inv):
    sale, store, bank, customer = inv["sale"], inv["store"], inv["bank"], inv["customer"]
    esc = html.escape
    rows = "".join(
        f"<tr><td>{esc(l['name'])}<br><small>HSN {esc(l['hsn'])} · Batch {esc(l['batch'])} · Exp {esc(l['expiry'])}</small></td>"
        f"<td class=r>{l['qty']}</td><td class=r>{inr(l['price'])}</td><td class=r>{l['gst']}%</td>"
        f"<td class=r>{inr(l['taxable'])}</td><td class=r>{inr(l['taxable'] + l['tax'])}</td></tr>" for l in inv["lines"])
    tax_rows = (f"<tr><td>CGST</td><td class=r>{inr(sum(l['cgst'] for l in inv['lines']))}</td></tr>"
                f"<tr><td>SGST</td><td class=r>{inr(sum(l['sgst'] for l in inv['lines']))}</td></tr>" if inv["intra"] else
                f"<tr><td>IGST</td><td class=r>{inr(sum(l['igst'] for l in inv['lines']))}</td></tr>")
    t = sale["totals"]
    bank_block = ""
    if inv["hasBank"]:
        bank_block = ("<h4>Pay to</h4><p>" + "<br>".join(esc(x) for x in [
            bank["accountHolder"], f"{bank['bankName']} {bank['branch']}".strip(),
            f"A/c {bank['accountNumber']} ({bank['accountType']})" if bank["accountNumber"] else "",
            f"IFSC {bank['ifsc']}" if bank["ifsc"] else "", f"UPI {bank['upiId']}" if bank["upiId"] else ""] if x) + "</p>")
    who = (sale["soldBy"] or {}).get("name", "")
    return f"""<!doctype html><meta charset=utf-8><title>{esc(sale['id'])}</title>
<style>body{{font:14px Segoe UI,Arial;margin:32px;color:#202b35}}table{{border-collapse:collapse;width:100%}}
td,th{{padding:6px;border-bottom:1px solid #e9edf0;text-align:left}}.r{{text-align:right}}small{{color:#87919c}}
h2{{margin:0}}.tot{{width:300px;margin-left:auto}}</style>
<h2>{esc(store['name'])}</h2><p>{esc(store['address'])} {esc(store['city'])} {esc(store['state'])} {esc(store['pincode'])}<br>
Ph {esc(store['phone'])} · GSTIN {esc(store['gstin'] or '—')} · DL {esc(store['drugLicense'] or '—')}</p>
<h3>{esc(inv['title'])}</h3>
<p><b>{esc(sale['id'])}</b> · {esc(sale['date'])} · {esc(sale['payment'])} ({esc(sale['status'])})<br>
Customer: {esc(sale['customerName'])}{(' · ' + esc(customer['phone'])) if customer else ''}
{(' · GSTIN ' + esc(customer['gstin'])) if customer and customer['gstin'] else ''}<br>Billed by: {esc(who)}</p>
<table><tr><th>Item</th><th class=r>Qty</th><th class=r>Rate</th><th class=r>GST</th><th class=r>Taxable</th><th class=r>Amount</th></tr>{rows}</table>
<table class=tot><tr><td>Subtotal</td><td class=r>{inr(t['subtotal'])}</td></tr><tr><td>Discount</td><td class=r>−{inr(t['discount'])}</td></tr>
{tax_rows}<tr><td>Points redeemed</td><td class=r>−{inr(t['redeem'])}</td></tr>
<tr><td><b>Total</b></td><td class=r><b>{inr(t['total'])}</b></td></tr></table>
<p>Points earned: {sale['earned']}</p>{bank_block}<p><small>Thank you for choosing {esc(store['name'])}.</small></p>"""


class InvoiceWindow(tk.Toplevel):
    def __init__(self, parent, inv):
        super().__init__(parent)
        self.inv = inv
        self.title(f"Invoice {inv['sale']['id']}")
        self.configure(background=theme.CARD)
        self.geometry("560x640")
        text = tk.Text(self, wrap="word", font=("Consolas", 10), background=theme.CARD, relief="flat", padx=16, pady=12)
        text.pack(fill="both", expand=True)
        text.insert("1.0", self.render_text())
        text.configure(state="disabled")
        bar = ttk.Frame(self, padding=10)
        bar.pack(fill="x")
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Save as HTML", command=self.save).pack(side="right", padx=6)
        ttk.Button(bar, text="Print", style="Primary.TButton", command=self.print).pack(side="right")

    def render_text(self):
        inv, sale, store = self.inv, self.inv["sale"], self.inv["store"]
        t, w = sale["totals"], 52
        out = [store["name"].center(w), inv["title"].center(w), "-" * w,
               f"{sale['id']}   {sale['date']}   {sale['payment']} ({sale['status']})",
               f"Customer : {sale['customerName']}", f"Billed by: {(sale['soldBy'] or {}).get('name', '—')}", "-" * w]
        for l in inv["lines"]:
            out.append(f"{l['name'][:30]:<30}{l['qty']:>4} x {l['price']:>8.2f}")
            out.append(f"   batch {l['batch']}  exp {l['expiry']}  GST {l['gst']}%  {l['taxable'] + l['tax']:>10.2f}")
        out += ["-" * w, f"{'Subtotal':<30}{inr(t['subtotal']):>22}", f"{'Discount':<30}{'-' + inr(t['discount']):>22}"]
        if inv["intra"]:
            out += [f"{'CGST':<30}{inr(sum(l['cgst'] for l in inv['lines'])):>22}",
                    f"{'SGST':<30}{inr(sum(l['sgst'] for l in inv['lines'])):>22}"]
        else:
            out.append(f"{'IGST':<30}{inr(sum(l['igst'] for l in inv['lines'])):>22}")
        out += [f"{'Points redeemed':<30}{'-' + inr(t['redeem']):>22}", f"{'TOTAL':<30}{inr(t['total']):>22}", "",
                f"Points earned: {sale['earned']}"]
        bank = inv["bank"]
        if inv["hasBank"]:
            out += ["", "Pay to:", f"  {bank['accountHolder']} — {bank['bankName']}",
                    f"  A/c {bank['accountNumber']}  IFSC {bank['ifsc']}", f"  UPI {bank['upiId']}"]
        return "\n".join(out)

    def print(self):
        handle, path = tempfile.mkstemp(suffix=".html", prefix="phoebix-invoice-")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(invoice_html(self.inv) + "<script>window.onload=()=>window.print()</script>")
        webbrowser.open(f"file:///{path}")

    def save(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".html",
                                            initialfile=f"{self.inv['sale']['id']}.html", filetypes=[("HTML", "*.html")])
        if path:
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(invoice_html(self.inv))
