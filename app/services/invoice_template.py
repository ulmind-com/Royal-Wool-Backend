"""Premium HTML invoice renderer for Royaall Wool.

Produces a self-contained, email-safe HTML string with fully inlined CSS.
Works in any email client and prints cleanly via the browser.
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
        # Convert UTC → IST (+5:30) for display
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
            f'<img src="{img_url}" width="40" height="40" '
            f'style="width:40px;height:40px;object-fit:cover;border-radius:6px;border:1px solid #e5e5e5;" />'
        ) if img_url else (
            '<div style="width:40px;height:40px;border-radius:6px;background:#f3f0eb;"></div>'
        )
        title = it.get("title", "Product")
        color = it.get("color", "")
        size = it.get("size", "")
        meta_parts = [p for p in [color, size] if p]
        meta = f' · {" · ".join(meta_parts)}' if meta_parts else ""
        qty = it.get("qty", 1)
        unit_price = float(it.get("price", 0))
        line_total = unit_price * qty

        item_rows += f"""
        <tr>
          <td style="padding:12px 0;border-bottom:1px solid #f0ede8;vertical-align:middle;">
            <table cellpadding="0" cellspacing="0" border="0"><tr>
              <td style="width:48px;vertical-align:middle;">{img_cell}</td>
              <td style="padding-left:12px;vertical-align:middle;">
                <div style="font-size:13px;color:#1c1613;font-weight:500;line-height:1.3;">{title}</div>
                {f'<div style="font-size:11px;color:#8c8680;margin-top:2px;">{meta.lstrip(" ·").strip()}</div>' if meta else ''}
              </td>
            </tr></table>
          </td>
          <td style="padding:12px 0;border-bottom:1px solid #f0ede8;text-align:center;font-size:13px;color:#1c1613;">{qty}</td>
          <td style="padding:12px 0;border-bottom:1px solid #f0ede8;text-align:right;font-size:13px;color:#8c8680;">{_fmt_money(unit_price)}</td>
          <td style="padding:12px 0;border-bottom:1px solid #f0ede8;text-align:right;font-size:13px;font-weight:600;color:#1c1613;">{_fmt_money(line_total)}</td>
        </tr>"""

    # ── Bill summary rows ────────────────────────────────────────────
    subtotal = float(order.get("subtotal", 0))
    discount = float(order.get("discount", 0))
    delivery = float(order.get("delivery", 0))
    delivery_free = order.get("delivery_free", False)
    total_tax = float(order.get("tax", 0))
    total = float(order.get("amount", order.get("total", 0)))

    gst = order.get("gst", {})
    cgst = float(gst.get("cgst", 0))
    sgst = float(gst.get("sgst", 0))
    igst = float(gst.get("igst", 0))
    interstate = gst.get("interstate", False)

    def _summary_row(label: str, value: str, bold: bool = False, color: str = "#1c1613", highlight: bool = False) -> str:
        bg = "background:#faf7f2;" if highlight else ""
        fw = "font-weight:700;" if bold else "font-weight:400;"
        fs = "font-size:15px;" if highlight else "font-size:13px;"
        pad = "padding:14px 16px;" if highlight else "padding:6px 0;"
        brd = "border-radius:8px;" if highlight else ""
        return f"""
        <tr>
          <td style="{pad}{bg}{brd}text-align:right;{fw}{fs}color:#8c8680;">{label}</td>
          <td style="{pad}{bg}{brd}text-align:right;{fw}{fs}color:{color};width:120px;">{value}</td>
        </tr>"""

    summary = ""
    summary += _summary_row("Subtotal", _fmt_money(subtotal))
    if discount > 0:
        summary += _summary_row("Discount", f"−{_fmt_money(discount)}", color="#15803d")
    if delivery_free:
        summary += _summary_row("Delivery", "FREE", color="#15803d")
    elif delivery > 0:
        summary += _summary_row("Delivery", _fmt_money(delivery))
    else:
        summary += _summary_row("Delivery", "FREE", color="#15803d")

    if interstate and igst > 0:
        summary += _summary_row("IGST", _fmt_money(igst))
    else:
        if cgst > 0:
            summary += _summary_row("CGST", _fmt_money(cgst))
        if sgst > 0:
            summary += _summary_row("SGST", _fmt_money(sgst))

    summary += _summary_row("Grand Total", _fmt_money(total), bold=True, color="#800000", highlight=True)

    # ── Address ──────────────────────────────────────────────────────
    addr_parts = [addr.get("house"), addr.get("area"), addr.get("city"), addr.get("state"), addr.get("pincode")]
    full_address = ", ".join(p for p in addr_parts if p)
    customer_name = addr.get("name", "Customer")
    customer_phone = addr.get("phone", "")

    # ── Payment info ─────────────────────────────────────────────────
    payment_id = order.get("razorpay_payment_id", "")
    payment_method = "Online · Razorpay" if order.get("payment_method") == "online" else "Cash on Delivery"

    # ── Logo URL (from the live site) ────────────────────────────────
    logo_url = "https://royaallwool.com/logo.jpeg"

    return f"""\
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Invoice #{short_id} — Royaall Wool</title>
  <style>
    @media print {{
      body {{ margin: 0; padding: 0; }}
      .no-print {{ display: none !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background:#f6f4f0;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #eceae7;">

        <!-- Accent bar -->
        <tr><td style="background:linear-gradient(135deg, #800000 0%, #5c0000 100%);height:6px;"></td></tr>

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
                  <div style="font-size:11px;color:#8c8680;margin-top:1px;letter-spacing:0.5px;">PREMIUM YARN & WOOL</div>
                </td>
              </tr></table>
            </td>
            <td style="text-align:right;vertical-align:middle;">
              <div style="font-size:22px;font-weight:700;color:#1c1613;letter-spacing:-0.5px;">INVOICE</div>
              <div style="font-size:12px;color:#8c8680;margin-top:4px;">#{short_id}</div>
              <div style="font-size:12px;color:#8c8680;margin-top:2px;">{_fmt_date(created)}</div>
            </td>
          </tr></table>
        </td></tr>

        <!-- Divider -->
        <tr><td style="padding:0 32px;"><div style="border-top:2px solid #f0ede8;"></div></td></tr>

        <!-- Bill To + Payment -->
        <tr><td style="padding:20px 32px;">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td style="vertical-align:top;width:50%;">
              <div style="font-size:10px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:8px;">Bill To</div>
              <div style="font-size:14px;font-weight:600;color:#1c1613;">{customer_name}</div>
              <div style="font-size:12px;color:#8c8680;margin-top:4px;line-height:1.5;">{full_address}</div>
              {f'<div style="font-size:12px;color:#8c8680;margin-top:2px;">{customer_phone}</div>' if customer_phone else ''}
            </td>
            <td style="vertical-align:top;width:50%;text-align:right;">
              <div style="font-size:10px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:8px;">Payment</div>
              <div style="font-size:13px;color:#1c1613;font-weight:500;">{_fmt_money(total)}</div>
              <div style="font-size:12px;color:#8c8680;margin-top:4px;">{payment_method}</div>
              {f'<div style="font-size:11px;color:#8c8680;margin-top:2px;font-family:monospace;">{payment_id}</div>' if payment_id else ''}
            </td>
          </tr></table>
        </td></tr>

        <!-- Divider -->
        <tr><td style="padding:0 32px;"><div style="border-top:2px solid #f0ede8;"></div></td></tr>

        <!-- Items header -->
        <tr><td style="padding:16px 32px 0;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td style="font-size:10px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;text-transform:uppercase;padding-bottom:10px;">Item</td>
              <td style="font-size:10px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;text-transform:uppercase;padding-bottom:10px;text-align:center;">Qty</td>
              <td style="font-size:10px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;text-transform:uppercase;padding-bottom:10px;text-align:right;">Price</td>
              <td style="font-size:10px;font-weight:700;color:#D4AF37;letter-spacing:1.5px;text-transform:uppercase;padding-bottom:10px;text-align:right;">Total</td>
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

        <!-- Divider -->
        <tr><td style="padding:0 32px;"><div style="border-top:2px solid #f0ede8;"></div></td></tr>

        <!-- Footer -->
        <tr><td style="padding:20px 32px 28px;text-align:center;">
          <div style="font-size:14px;color:#1c1613;font-weight:500;">Thank you for shopping with Royaall Wool! 🧶</div>
          <div style="font-size:11px;color:#b5b5ba;margin-top:8px;">This is a computer generated invoice and does not require a signature.</div>
          <div style="font-size:11px;color:#b5b5ba;margin-top:4px;">Royaall Wool · Premium Yarn & Wool Retailer</div>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""
