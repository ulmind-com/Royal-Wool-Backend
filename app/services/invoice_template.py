"""Premium HTML invoice renderer for Royaall Wool.

Produces a self-contained HTML string optimised for xhtml2pdf (pisa).
xhtml2pdf has limited CSS support so we use explicit table widths,
avoid border-radius on td, and keep things simple.
"""

from datetime import datetime, timezone


def _fmt_money(amount: float | int | None) -> str:
    """Format a number as ₹1,234.00."""
    if amount is None:
        return "₹0.00"
    return f"₹{float(amount):,.2f}"


def _fmt_date(dt) -> str:
    """Format a datetime or ISO string as '07 Aug 2026, 10:32 PM'."""
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


def render(order: dict) -> str:
    """Build a complete HTML invoice from an order document."""
    oid = str(order.get("_id", order.get("id", "")))
    short_id = oid[-8:].upper()
    created = order.get("created_at") or order.get("paid_at") or datetime.now(timezone.utc)
    addr = order.get("address", {})
    items = order.get("items", [])

    # ── Item rows ────────────────────────────────────────────────────
    item_rows = ""
    for it in items:
        img_url = it.get("image") or ""
        img_cell = (
            f'<img src="{img_url}" width="36" height="36" />'
        ) if img_url else (
            '<div style="width:36px;height:36px;background:#f3f0eb;">&nbsp;</div>'
        )
        title = it.get("title", "Product")
        color = it.get("color", "")
        size = it.get("size", "")
        meta_parts = [p for p in [color, size] if p]
        meta_line = " | ".join(meta_parts) if meta_parts else ""
        qty = it.get("qty", 1)
        unit_price = float(it.get("price", 0))
        line_total = unit_price * qty

        item_rows += f"""
        <tr>
          <td width="50" style="padding:10px 4px;border-bottom:1px solid #eee;vertical-align:top;">{img_cell}</td>
          <td width="260" style="padding:10px 4px;border-bottom:1px solid #eee;vertical-align:top;font-size:11px;color:#333;">
            {title}
            {f'<br/><span style="font-size:10px;color:#999;">{meta_line}</span>' if meta_line else ''}
          </td>
          <td width="40" style="padding:10px 4px;border-bottom:1px solid #eee;text-align:center;font-size:11px;color:#333;">{qty}</td>
          <td width="80" style="padding:10px 4px;border-bottom:1px solid #eee;text-align:right;font-size:11px;color:#888;">{_fmt_money(unit_price)}</td>
          <td width="90" style="padding:10px 4px;border-bottom:1px solid #eee;text-align:right;font-size:12px;font-weight:bold;color:#333;">{_fmt_money(line_total)}</td>
        </tr>"""

    # ── Bill summary rows ────────────────────────────────────────────
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

    def _srow(label: str, value: str, color: str = "#333", bold: bool = False) -> str:
        fw = "font-weight:bold;" if bold else ""
        return f"""
        <tr>
          <td style="padding:4px 8px;text-align:right;font-size:11px;color:#888;">{label}</td>
          <td width="120" style="padding:4px 8px;text-align:right;font-size:12px;{fw}color:{color};">{value}</td>
        </tr>"""

    summary = ""
    summary += _srow("Subtotal", _fmt_money(subtotal))
    if discount > 0:
        summary += _srow("Discount", f"- {_fmt_money(discount)}", color="#15803d")
    if delivery_free:
        summary += _srow("Delivery", "FREE", color="#15803d")
    elif delivery > 0:
        summary += _srow("Delivery", _fmt_money(delivery))
    else:
        summary += _srow("Delivery", "FREE", color="#15803d")

    if interstate and igst > 0:
        summary += _srow("IGST", _fmt_money(igst))
    else:
        if cgst > 0:
            summary += _srow("CGST", _fmt_money(cgst))
        if sgst > 0:
            summary += _srow("SGST", _fmt_money(sgst))

    # ── Address ──────────────────────────────────────────────────────
    addr_parts = [addr.get("house"), addr.get("area"), addr.get("city"), addr.get("state"), addr.get("pincode")]
    full_address = ", ".join(p for p in addr_parts if p)
    customer_name = addr.get("name", "Customer")
    customer_phone = addr.get("phone", "")

    # ── Payment info ─────────────────────────────────────────────────
    payment_id = order.get("razorpay_payment_id", "")
    payment_method = "Online - Razorpay" if order.get("payment_method") == "online" else "Cash on Delivery"

    # ── Logo URL ─────────────────────────────────────────────────────
    logo_url = "https://royaallwool.com/logo.jpeg"

    return f"""\
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Invoice #{short_id}</title>
  <style>
    @page {{
      size: A4;
      margin: 1.5cm;
    }}
    body {{
      font-family: Helvetica, Arial, sans-serif;
      font-size: 12px;
      color: #333333;
      margin: 0;
      padding: 0;
    }}
  </style>
</head>
<body>

  <!-- ═══ HEADER ═══ -->
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td width="50%" style="vertical-align:top;">
        <table cellpadding="0" cellspacing="0">
          <tr>
            <td style="vertical-align:middle;padding-right:10px;">
              <img src="{logo_url}" width="44" height="44" />
            </td>
            <td style="vertical-align:middle;">
              <span style="font-size:18px;color:#800000;font-weight:bold;">Royaall</span>
              <span style="font-size:18px;color:#D4AF37;font-style:italic;"> Wool</span>
              <br/>
              <span style="font-size:9px;color:#999;letter-spacing:2px;">PREMIUM YARN &amp; WOOL</span>
            </td>
          </tr>
        </table>
      </td>
      <td width="50%" style="text-align:right;vertical-align:top;">
        <span style="font-size:24px;font-weight:bold;color:#1c1613;">INVOICE</span><br/>
        <span style="font-size:11px;color:#888;">#{short_id}</span><br/>
        <span style="font-size:11px;color:#888;">{_fmt_date(created)}</span>
      </td>
    </tr>
  </table>

  <!-- ═══ DIVIDER ═══ -->
  <hr style="border:none;border-top:2px solid #800000;margin:16px 0;" />

  <!-- ═══ BILL TO + PAYMENT ═══ -->
  <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:16px;">
    <tr>
      <td width="50%" style="vertical-align:top;">
        <p style="font-size:9px;font-weight:bold;color:#D4AF37;letter-spacing:2px;margin:0 0 6px;">BILL TO</p>
        <p style="font-size:14px;font-weight:bold;color:#1c1613;margin:0 0 4px;">{customer_name}</p>
        <p style="font-size:11px;color:#888;margin:0;line-height:1.5;">{full_address}</p>
        {f'<p style="font-size:11px;color:#888;margin:2px 0 0;">{customer_phone}</p>' if customer_phone else ''}
      </td>
      <td width="50%" style="text-align:right;vertical-align:top;">
        <p style="font-size:9px;font-weight:bold;color:#D4AF37;letter-spacing:2px;margin:0 0 6px;">PAYMENT</p>
        <p style="font-size:14px;font-weight:bold;color:#1c1613;margin:0 0 4px;">{_fmt_money(total)}</p>
        <p style="font-size:11px;color:#888;margin:0;">{payment_method}</p>
        {f'<p style="font-size:10px;color:#888;margin:2px 0 0;">{payment_id}</p>' if payment_id else ''}
      </td>
    </tr>
  </table>

  <!-- ═══ DIVIDER ═══ -->
  <hr style="border:none;border-top:1px solid #eee;margin:0 0 8px;" />

  <!-- ═══ ITEMS TABLE ═══ -->
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr style="background:#faf7f2;">
      <td width="50" style="padding:8px 4px;font-size:9px;font-weight:bold;color:#D4AF37;letter-spacing:1px;">&nbsp;</td>
      <td width="260" style="padding:8px 4px;font-size:9px;font-weight:bold;color:#D4AF37;letter-spacing:1px;">ITEM</td>
      <td width="40" style="padding:8px 4px;font-size:9px;font-weight:bold;color:#D4AF37;letter-spacing:1px;text-align:center;">QTY</td>
      <td width="80" style="padding:8px 4px;font-size:9px;font-weight:bold;color:#D4AF37;letter-spacing:1px;text-align:right;">PRICE</td>
      <td width="90" style="padding:8px 4px;font-size:9px;font-weight:bold;color:#D4AF37;letter-spacing:1px;text-align:right;">TOTAL</td>
    </tr>
    {item_rows}
  </table>

  <!-- ═══ SUMMARY ═══ -->
  <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;">
    {summary}
    <tr>
      <td colspan="2" style="padding:0;"><hr style="border:none;border-top:1px solid #ddd;margin:6px 0;" /></td>
    </tr>
    <tr>
      <td style="padding:10px 8px;text-align:right;font-size:14px;font-weight:bold;color:#800000;">Grand Total</td>
      <td width="120" style="padding:10px 8px;text-align:right;font-size:16px;font-weight:bold;color:#800000;">{_fmt_money(total)}</td>
    </tr>
  </table>

  <!-- ═══ DIVIDER ═══ -->
  <hr style="border:none;border-top:1px solid #eee;margin:20px 0 16px;" />

  <!-- ═══ FOOTER ═══ -->
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td style="text-align:center;padding:8px 0;">
        <p style="font-size:13px;color:#1c1613;font-weight:bold;margin:0 0 6px;">Thank you for shopping with Royaall Wool!</p>
        <p style="font-size:10px;color:#bbb;margin:0 0 3px;">This is a computer generated invoice and does not require a signature.</p>
        <p style="font-size:10px;color:#bbb;margin:0;">Royaall Wool &middot; Premium Yarn &amp; Wool Retailer</p>
      </td>
    </tr>
  </table>

</body>
</html>"""
