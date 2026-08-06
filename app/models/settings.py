from pydantic import BaseModel, Field


class DeliveryConfig(BaseModel):
    # Free delivery threshold
    free_above: float = 0              # order subtotal for free delivery (0 = off)
    
    # Home State Pricing
    home_state: str = "West Bengal"
    home_base_fee: float = 65          # flat fee for up to base_weight_kg
    home_base_weight_kg: float = 1     # usually 1kg
    home_extra_fee_per_kg: float = 0   # charge per extra kg above base weight
    
    # Rest of India Pricing
    rest_base_fee: float = 100         # flat fee for up to base_weight_kg
    rest_base_weight_kg: float = 1
    rest_extra_fee_per_kg: float = 0





class ShopConfig(BaseModel):
    name: str = "Royaall Wool"
    address: str = ""
    phone: str = ""
    email: str = ""          # support email surfaced to customers (chat, help)
    state: str = ""          # seller's state — same-state order = CGST+SGST, else IGST
    lat: float | None = None
    lng: float | None = None


class SocialLink(BaseModel):
    label: str = ""                    # e.g. "Instagram"
    href: str = ""                     # full profile URL


class SupportConfig(BaseModel):
    """
    The support card on the storefront Contact page.

    The number/email/address themselves live in ShopConfig so they stay a single
    source of truth; everything else the card renders is editable here. A blank
    string means "hide that row", so the admin can drop a channel without code.
    """
    title: str = "We're always here to help you."
    note: str = "Reach us on whichever channel suits you."
    hotline_label: str = "Hotline"
    email_label: str = "Email"
    address_label: str = "Studio"
    whatsapp: str = "+91 89107 92214"  # display number; blank hides the row
    whatsapp_label: str = "SMS / WhatsApp"
    whatsapp_message: str = "Hi Royaall Wool, I have a question about your yarns."
    hours: str = "Open 10am – 7pm IST, every day"
    socials: list[SocialLink] = Field(default_factory=lambda: [
        SocialLink(label="Instagram", href="https://www.instagram.com/royaallwool"),
        SocialLink(label="Facebook", href="https://www.facebook.com/share/1SEBGxnKW6/"),
    ])


class Settings(BaseModel):
    currency: str = "₹"
    currency_code: str = "INR"
    tax_rate: float = 0.05             # 5%

    shop: ShopConfig = ShopConfig()
    delivery: DeliveryConfig = DeliveryConfig()
    support: SupportConfig = SupportConfig()
    
    announcements: list[str] = Field(default=[
        "Free delivery on orders above {free_delivery}",
        "{coupon}",
        "Support 10am–7pm IST, all days",
        "Small-batch colour, wound for stitch definition"
    ])


class SettingsUpdate(BaseModel):
    currency: str | None = None
    currency_code: str | None = None
    tax_rate: float | None = None

    shop: ShopConfig | None = None
    delivery: DeliveryConfig | None = None
    support: SupportConfig | None = None
    announcements: list[str] | None = None
