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


class Settings(BaseModel):
    currency: str = "₹"
    currency_code: str = "INR"
    tax_rate: float = 0.05             # 5%

    shop: ShopConfig = ShopConfig()
    delivery: DeliveryConfig = DeliveryConfig()


class SettingsUpdate(BaseModel):
    currency: str | None = None
    currency_code: str | None = None
    tax_rate: float | None = None

    shop: ShopConfig | None = None
    delivery: DeliveryConfig | None = None
