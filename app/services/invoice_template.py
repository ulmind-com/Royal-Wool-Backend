"""Premium HTML invoice renderer for Royaall Wool.

Two render functions:
  render_pdf(order)   → HTML optimised for xhtml2pdf (uses Rs. for the rupee sign)
  render_email(order) → rich HTML for email clients (uses ₹ and modern CSS)
"""

from datetime import datetime, timezone


def _fmt_money_pdf(amount: float | int | None) -> str:
    """Format for PDF: Rs. 1,234.00 (xhtml2pdf can't render ₹)."""
    if amount is None:
        return "Rs. 0.00"
    return f"Rs. {float(amount):,.2f}"


def _fmt_money_email(amount: float | int | None) -> str:
    """Format for email: ₹1,234.00 (browsers render ₹ fine)."""
    if amount is None:
        return "₹0.00"
    return f"₹{float(amount):,.2f}"


def _fmt_date(dt) -> str:
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return dt
    if isinstance(dt, datetime):
        from datetime import timedelta
        ist = dt + timedelta(hours=5, minutes=30)
        return ist.strftime("%d %b %Y, %I:%M %p") + " IST"
    return str(dt)


def _extract(order: dict):
    """Pull common fields from the order document."""
    oid = str(order.get("_id", order.get("id", "")))
    short_id = oid[-8:].upper()
    created = order.get("created_at") or order.get("paid_at") or datetime.now(timezone.utc)
    addr = order.get("address", {})
    items = order.get("items", [])

    addr_parts = [addr.get("house"), addr.get("area"), addr.get("city"),
                  addr.get("state"), addr.get("pincode")]
    full_address = ", ".join(p for p in addr_parts if p)
    customer_name = addr.get("name", "Customer")
    customer_phone = addr.get("phone", "")

    payment_id = order.get("razorpay_payment_id", "")
    payment_method = ("Online - Razorpay" if order.get("payment_method") == "online"
                      else "Cash on Delivery")

    subtotal = float(order.get("subtotal", 0))
    discount = float(order.get("discount", 0))
    delivery = float(order.get("delivery", 0))
    delivery_free = order.get("delivery_free", False)
    total = float(order.get("amount", order.get("total", 0)))
    gst = order.get("gst", {})
    cgst = float(gst.get("cgst", 0))
    sgst = float(gst.get("sgst", 0))
    igst = float(gst.get("igst", 0))
    interstate = gst.get("interstate", False)

    return dict(
        oid=oid, short_id=short_id, created=created, addr=addr,
        items=items, full_address=full_address, customer_name=customer_name,
        customer_phone=customer_phone, payment_id=payment_id,
        payment_method=payment_method, subtotal=subtotal, discount=discount,
        delivery=delivery, delivery_free=delivery_free, total=total,
        cgst=cgst, sgst=sgst, igst=igst, interstate=interstate,
    )


# ═══════════════════════════════════════════════════════════════════
#  PDF INVOICE  (for xhtml2pdf — uses Rs. instead of ₹)
# ═══════════════════════════════════════════════════════════════════

def render_pdf(order: dict) -> str:
    d = _extract(order)
    fmt = _fmt_money_pdf
    logo_url = "https://royaallwool.com/logo.jpeg"

    item_rows = ""
    for it in d["items"]:
        img_url = it.get("image") or ""
        img_cell = f'<img src="{img_url}" width="36" height="36" />' if img_url else ""
        title = it.get("title", "Product")
        color = it.get("color", "")
        size = it.get("size", "")
        meta = " | ".join(p for p in [color, size] if p)
        qty = it.get("qty", 1)
        price = float(it.get("price", 0))
        line = price * qty

        item_rows += f"""
        <tr>
          <td width="44" style="padding:10px 4px;border-bottom:1px solid #eee;vertical-align:top;">{img_cell}</td>
          <td style="padding:10px 6px;border-bottom:1px solid #eee;vertical-align:top;font-size:11px;color:#333;">
            {title}{f'<br/><span style="font-size:9px;color:#999;">{meta}</span>' if meta else ''}
          </td>
          <td width="35" style="padding:10px 4px;border-bottom:1px solid #eee;text-align:center;font-size:11px;color:#333;">{qty}</td>
          <td width="85" style="padding:10px 4px;border-bottom:1px solid #eee;text-align:right;font-size:11px;color:#666;">{fmt(price)}</td>
          <td width="95" style="padding:10px 4px;border-bottom:1px solid #eee;text-align:right;font-size:11px;font-weight:bold;color:#333;">{fmt(line)}</td>
        </tr>"""

    def _sr(label, value, color="#333", bold=False):
        fw = "font-weight:bold;" if bold else ""
        fs = "font-size:13px;" if bold else "font-size:11px;"
        return f"""<tr>
          <td style="padding:5px 8px;text-align:right;font-size:11px;color:#888;">{label}</td>
          <td width="130" style="padding:5px 8px;text-align:right;{fs}{fw}color:{color};">{value}</td>
        </tr>"""

    summary = _sr("Subtotal", fmt(d["subtotal"]))
    if d["discount"] > 0:
        summary += _sr("Discount", f"- {fmt(d['discount'])}", color="#15803d")
    if d["delivery_free"] or d["delivery"] == 0:
        summary += _sr("Delivery", "FREE", color="#15803d")
    elif d["delivery"] > 0:
        summary += _sr("Delivery", fmt(d["delivery"]))
    if d["interstate"] and d["igst"] > 0:
        summary += _sr("IGST", fmt(d["igst"]))
    else:
        if d["cgst"] > 0:
            summary += _sr("CGST", fmt(d["cgst"]))
        if d["sgst"] > 0:
            summary += _sr("SGST", fmt(d["sgst"]))

    return f"""\
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Invoice #{d["short_id"]}</title>
  <style>
    @page {{ size: A4; margin: 1.8cm 1.5cm; }}
    body {{ font-family: Helvetica, Arial, sans-serif; font-size: 11px; color: #333; margin: 0; padding: 0; }}
  </style>
</head>
<body>

  <!-- HEADER -->
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td style="vertical-align:top;">
        <table cellpadding="0" cellspacing="0"><tr>
          <td style="vertical-align:middle;padding-right:10px;">
            <img src="{logo_url}" width="44" height="44" />
          </td>
          <td style="vertical-align:middle;">
            <span style="font-size:20px;color:#800000;font-weight:bold;">Royaall</span>
            <span style="font-size:20px;color:#D4AF37;font-style:italic;"> Wool</span><br/>
            <span style="font-size:8px;color:#999;letter-spacing:2px;">PREMIUM YARN &amp; WOOL</span>
          </td>
        </tr></table>
      </td>
      <td style="text-align:right;vertical-align:top;">
        <span style="font-size:26px;font-weight:bold;color:#333;">INVOICE</span><br/>
        <span style="font-size:11px;color:#888;">#{d["short_id"]}</span><br/>
        <span style="font-size:10px;color:#888;">{_fmt_date(d["created"])}</span>
      </td>
    </tr>
  </table>

  <hr style="border:none;border-top:2px solid #800000;margin:14px 0;" />

  <!-- BILL TO / PAYMENT -->
  <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;">
    <tr>
      <td width="55%" style="vertical-align:top;">
        <p style="font-size:8px;font-weight:bold;color:#D4AF37;letter-spacing:2px;margin:0 0 5px;">BILL TO</p>
        <p style="font-size:14px;font-weight:bold;color:#333;margin:0 0 3px;">{d["customer_name"]}</p>
        <p style="font-size:10px;color:#888;margin:0;line-height:1.6;">{d["full_address"]}</p>
        {f'<p style="font-size:10px;color:#888;margin:2px 0 0;">{d["customer_phone"]}</p>' if d["customer_phone"] else ""}
      </td>
      <td width="45%" style="text-align:right;vertical-align:top;">
        <p style="font-size:8px;font-weight:bold;color:#D4AF37;letter-spacing:2px;margin:0 0 5px;">PAYMENT</p>
        <p style="font-size:14px;font-weight:bold;color:#333;margin:0 0 3px;">{fmt(d["total"])}</p>
        <p style="font-size:10px;color:#888;margin:0;">{d["payment_method"]}</p>
        {f'<p style="font-size:9px;color:#888;margin:2px 0 0;">{d["payment_id"]}</p>' if d["payment_id"] else ""}
      </td>
    </tr>
  </table>

  <hr style="border:none;border-top:1px solid #e5e5e5;margin:0 0 4px;" />

  <!-- ITEMS TABLE -->
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr style="background:#faf7f2;">
      <td width="44" style="padding:8px 4px;">&nbsp;</td>
      <td style="padding:8px 6px;font-size:8px;font-weight:bold;color:#D4AF37;letter-spacing:1px;">ITEM</td>
      <td width="35" style="padding:8px 4px;font-size:8px;font-weight:bold;color:#D4AF37;letter-spacing:1px;text-align:center;">QTY</td>
      <td width="85" style="padding:8px 4px;font-size:8px;font-weight:bold;color:#D4AF37;letter-spacing:1px;text-align:right;">PRICE</td>
      <td width="95" style="padding:8px 4px;font-size:8px;font-weight:bold;color:#D4AF37;letter-spacing:1px;text-align:right;">TOTAL</td>
    </tr>
    {item_rows}
  </table>

  <!-- SUMMARY -->
  <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:10px;">
    {summary}
    <tr><td colspan="2"><hr style="border:none;border-top:2px solid #800000;margin:8px 0;" /></td></tr>
    <tr>
      <td style="padding:10px 8px;text-align:right;font-size:14px;font-weight:bold;color:#800000;">Grand Total</td>
      <td width="130" style="padding:10px 8px;text-align:right;font-size:18px;font-weight:bold;color:#800000;">{fmt(d["total"])}</td>
    </tr>
  </table>

  <hr style="border:none;border-top:1px solid #e5e5e5;margin:24px 0 14px;" />

  <!-- FOOTER -->
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td style="text-align:center;padding:6px 0;">
      <p style="font-size:12px;color:#333;font-weight:bold;margin:0 0 5px;">Thank you for shopping with Royaall Wool!</p>
      <p style="font-size:9px;color:#bbb;margin:0 0 2px;">This is a computer generated invoice and does not require a signature.</p>
      <p style="font-size:9px;color:#bbb;margin:0;">Royaall Wool &middot; Premium Yarn &amp; Wool Retailer</p>
    </td></tr>
  </table>

</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════
#  EMAIL INVOICE  (premium HTML for email clients — ₹ works fine)
# ═══════════════════════════════════════════════════════════════════

def render_email(order: dict) -> str:
    d = _extract(order)
    fmt = _fmt_money_email
    logo_url = "https://royaallwool.com/logo.jpeg"

    item_rows = ""
    for it in d["items"]:
        img_url = it.get("image") or ""
        img_cell = (
            f'<img src="{img_url}" width="40" height="40" '
            f'style="width:40px;height:40px;object-fit:cover;border-radius:6px;border:1px solid #e5e5e5;" />'
        ) if img_url else (
            '<div style="width:40px;height:40px;border-radius:6px;background:#f3f0eb;"></div>'
        )
        title = it.get("title", "Product")
        color = it.get("color", "")
        size = it.get("size", "")
        meta = " · ".join(p for p in [color, size] if p)
        qty = it.get("qty", 1)
        price = float(it.get("price", 0))
        line = price * qty

        item_rows += f"""
        <tr>
          <td style="padding:12px 0;border-bottom:1px solid #f0ede8;vertical-align:middle;">
            <table cellpadding="0" cellspacing="0" border="0"><tr>
              <td style="width:48px;vertical-align:middle;">{img_cell}</td>
              <td style="padding-left:12px;vertical-align:middle;">
                <div style="font-size:13px;color:#1c1613;font-weight:500;line-height:1.3;">{title}</div>
                {f'<div style="font-size:11px;color:#8c8680;margin-top:2px;">{meta}</div>' if meta else ''}
              </td>
            </tr></table>
          </td>
          <td style="padding:12px 8px;border-bottom:1px solid #f0ede8;text-align:center;font-size:13px;color:#1c1613;width:40px;">{qty}</td>
          <td style="padding:12px 8px;border-bottom:1px solid #f0ede8;text-align:right;font-size:13px;color:#8c8680;width:80px;">{fmt(price)}</td>
          <td style="padding:12px 0;border-bottom:1px solid #f0ede8;text-align:right;font-size:13px;font-weight:600;color:#1c1613;width:90px;">{fmt(line)}</td>
        </tr>"""

    def _sr(label, value, color="#1c1613", bold=False, highlight=False):
        bg = "background:#faf7f2;" if highlight else ""
        fw = "font-weight:700;" if bold else "font-weight:400;"
        fs = "font-size:16px;" if highlight else "font-size:13px;"
        pad = "padding:14px 16px;" if highlight else "padding:6px 0;"
        return f"""<tr>
          <td style="{pad}{bg}text-align:right;{fw}{fs}color:#8c8680;">{label}</td>
          <td style="{pad}{bg}text-align:right;{fw}{fs}color:{color};width:120px;">{value}</td>
        </tr>"""

    summary = _sr("Subtotal", fmt(d["subtotal"]))
    if d["discount"] > 0:
        summary += _sr("Discount", f"−{fmt(d['discount'])}", color="#15803d")
    if d["delivery_free"] or d["delivery"] == 0:
        summary += _sr("Delivery", "FREE", color="#15803d")
    elif d["delivery"] > 0:
        summary += _sr("Delivery", fmt(d["delivery"]))
    if d["interstate"] and d["igst"] > 0:
        summary += _sr("IGST", fmt(d["igst"]))
    else:
        if d["cgst"] > 0:
            summary += _sr("CGST", fmt(d["cgst"]))
        if d["sgst"] > 0:
            summary += _sr("SGST", fmt(d["sgst"]))
    summary += _sr("Grand Total", fmt(d["total"]), bold=True, color="#800000", highlight=True)

    return f"""\
<!doctype html>
<html>
<head><meta charset="utf-8" /><title>Invoice #{d["short_id"]}</title></head>
<body style="margin:0;padding:0;background:#f6f4f0;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #eceae7;">

        <!-- Accent bar -->
        <tr><td style="background:#800000;height:6px;"></td></tr>

        <!-- Header -->
        <tr><td style="padding:28px 32px 20px;">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td style="vertical-align:middle;">
              <table cellpadding="0" cellspacing="0"><tr>
                <td style="vertical-align:middle;">
                  <img src="{logo_url}" width="44" height="44"
                       style="width:44px;height:44px;border-radius:50%;object-fit:cover;border:2px solid #D4AF37;" />
                </td>
                <td style="padding-left:12px;vertical-align:middle;">
                  <div style="font-size:20px;letter-spacing:-0.5px;">
                    <span style="color:#800000;font-weight:700;">Royaall</span>
                    <span style="color:#D4AF37;font-weight:500;font-style:italic;"> Wool</span>
                  </div>
                  <div style="font-size:11px;color:#8c8680;margin-top:1px;letter-spacing:0.5px;">PREMIUM YARN &amp; WOOL</div>
                </td>
              </tr></table>
            </td>
            <td style="text-align:right;vertical-align:middle;">
              <div style="font-size:22px;font-weight:700;color:#1c1613;">INVOICE</div>
              <div style="font-size:12px;color:#8c8680;margin-top:4px;">#{d["short_id"]}</div>
              <div style="font-size:12px;color:#8c8680;margin-top:2px;">{_fmt_date(d["created"])}</div>
            </td>
          </tr></table>
        </td></tr>

        <tr><td style="padding:0 32px;"><div style="border-top:2px solid #f0ede8;"></div></td></tr>

        <!-- Bill To + Payment -->
        <tr><td style="padding:20px 32px;">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td style="vertical-align:top;width:50%;">
              <div style="font-size:10px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;margin-bottom:8px;">BILL TO</div>
              <div style="font-size:14px;font-weight:600;color:#1c1613;">{d["customer_name"]}</div>
              <div style="font-size:12px;color:#8c8680;margin-top:4px;line-height:1.5;">{d["full_address"]}</div>
              {f'<div style="font-size:12px;color:#8c8680;margin-top:2px;">{d["customer_phone"]}</div>' if d["customer_phone"] else ''}
            </td>
            <td style="vertical-align:top;width:50%;text-align:right;">
              <div style="font-size:10px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;margin-bottom:8px;">PAYMENT</div>
              <div style="font-size:13px;color:#1c1613;font-weight:500;">{fmt(d["total"])}</div>
              <div style="font-size:12px;color:#8c8680;margin-top:4px;">{d["payment_method"]}</div>
              {f'<div style="font-size:11px;color:#8c8680;margin-top:2px;font-family:monospace;">{d["payment_id"]}</div>' if d["payment_id"] else ''}
            </td>
          </tr></table>
        </td></tr>

        <tr><td style="padding:0 32px;"><div style="border-top:2px solid #f0ede8;"></div></td></tr>

        <!-- Items -->
        <tr><td style="padding:16px 32px 0;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td style="font-size:10px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;padding-bottom:10px;">Item</td>
              <td style="font-size:10px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;padding-bottom:10px;text-align:center;width:40px;">Qty</td>
              <td style="font-size:10px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;padding-bottom:10px;text-align:right;width:80px;">Price</td>
              <td style="font-size:10px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;padding-bottom:10px;text-align:right;width:90px;">Total</td>
            </tr>
            {item_rows}
          </table>
        </td></tr>

        <!-- Summary -->
        <tr><td style="padding:16px 32px 24px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td colspan="2" style="height:8px;"></td></tr>
            {summary}
          </table>
        </td></tr>

        <tr><td style="padding:0 32px;"><div style="border-top:2px solid #f0ede8;"></div></td></tr>

        <!-- Footer -->
        <tr><td style="padding:20px 32px 28px;text-align:center;">
          <div style="font-size:14px;color:#1c1613;font-weight:500;">Thank you for shopping with Royaall Wool!</div>
          <div style="font-size:11px;color:#b5b5ba;margin-top:8px;">This is a computer generated invoice and does not require a signature.</div>
          <div style="font-size:11px;color:#b5b5ba;margin-top:4px;">Royaall Wool &middot; Premium Yarn &amp; Wool Retailer</div>
        </td></tr>

      </table>
      <p style="margin:16px 0 0;color:#b5b5ba;font-size:11px;text-align:center;">The PDF invoice is attached to this email.</p>
    </td></tr>
  </table>
</body>
</html>"""


# Backward compat: keep `render` pointing to the PDF version
render = render_pdf
