from pydantic import BaseModel, Field, ConfigDict


class FiberContent(BaseModel):
    """Schema for yarn fiber composition, e.g., 80% Merino Wool."""
    fiber: str
    percentage: int = Field(ge=1, le=100)


class DyeLotStock(BaseModel):
    """Replaces SizeStock. Inventory is now tracked per dye lot."""
    dye_lot: str                       # e.g. "Lot-104A"
    price: float | None = None         # per-dye-lot selling price (falls back to colour/base)
    mrp: float | None = None           # per-dye-lot MRP (falls back to colour/base)
    discount_pct: float | None = None  # per-dye-lot extra discount % (falls back to colour/base)
    discount_on: str | None = None     # "price" | "mrp" (falls back to colour/base)
    stock: int = 0                     # inventory for this colour + dye lot


class ColorVariant(BaseModel):
    """Color variant now nests DyeLotStock instead of SizeStock."""
    color_family: str | None = None    # e.g. "Red", "Blue", "Multi"
    name: str                          # e.g. "Orange"
    hex: str = "#000000"               # swatch colour fallback
    swatch_image: str | None = None    # image URL for the swatch (yarn texture)
    images: list[str] = []             # images shown when this colour is picked
    price: float | None = None         # per-colour selling price (falls back to base)
    mrp: float | None = None           # per-colour MRP (falls back to base)
    discount_pct: float | None = None  # per-colour extra discount % (falls back to base)
    discount_on: str | None = None     # "price" | "mrp" (falls back to base)
    stock: int = 0                     # inventory for this colour (when it has no per-dye-lot rows)
    dye_lots: list[DyeLotStock] = Field(default_factory=list)  # per-dye-lot price + stock


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=160)
    description: str = ""
    short_description: str | None = None
    tags: list[str] = Field(default_factory=list)
    brand: str | None = None
    product_line: str | None = None
    category_id: str | None = None

    sku: str | None = None
    shipping_weight: float | None = None
    country_of_origin: str | None = None

    mrp: float = Field(ge=0)                    # actual price (struck through)
    price: float = Field(ge=0)                  # needed / selling price
    discount_pct: float = Field(default=0, ge=0, le=95)  # admin extra discount
    discount_on: str = "price"                  # "mrp" | "price"

    cgst: float | None = None                   # CGST % (same-state orders)
    sgst: float | None = None                   # SGST % (same-state orders)
    igst: float | None = None                   # IGST % (inter-state orders)

    primary_color_name: str | None = None       # e.g., "Azure Blue"
    primary_color_hex: str | None = None        # e.g., "#007FFF"
    primary_color_family: str | None = None     # e.g., "Blue"

    images: list[str] = []                      # general gallery (no colour)
    colors: list[ColorVariant] = []             # colour-wise images + stock
    
    # --- YARN SPECIFIC SPECS ---
    yarn_weight: str | None = None              # e.g., "DK", "Worsted"
    fiber_content: list[FiberContent] = Field(default_factory=list)
    yardage: int | None = Field(default=None, description="Yardage/Meterage per skein")
    skein_weight: int | None = Field(default=None, description="Weight in grams per skein")
    gauge_info: str | None = None               # e.g., "22 sts = 4 inches on 4mm needles"
    hook_size: str | None = None                # e.g., "5.0 mm (H)"
    certifications: str | None = None           # e.g., "Oeko-Tex Standard 100"
    care_instructions: str | None = None        # e.g., "Hand wash only"

    stock: int = 0                              # used when there are no colour variants
    low_stock_threshold: int = 5

    rating: float = Field(default=0, ge=0, le=5)
    review_count: int = 0
    sold_count: int = 0

    is_active: bool = True
    is_featured: bool = False


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    description: str | None = None
    short_description: str | None = None
    tags: list[str] | None = None
    brand: str | None = None
    product_line: str | None = None
    category_id: str | None = None
    sku: str | None = None
    shipping_weight: float | None = None
    country_of_origin: str | None = None
    mrp: float | None = None
    price: float | None = None
    discount_pct: float | None = None
    discount_on: str | None = None
    cgst: float | None = None
    sgst: float | None = None
    igst: float | None = None
    
    primary_color_name: str | None = None
    primary_color_hex: str | None = None
    primary_color_family: str | None = None

    images: list[str] | None = None
    colors: list[ColorVariant] | None = None
    
    # --- YARN SPECIFIC SPECS ---
    yarn_weight: str | None = None
    fiber_content: list[FiberContent] | None = None
    yardage: int | None = None
    skein_weight: int | None = None
    gauge_info: str | None = None
    hook_size: str | None = None
    certifications: str | None = None
    care_instructions: str | None = None

    stock: int | None = None
    low_stock_threshold: int | None = None
    rating: float | None = None
    review_count: int | None = None
    sold_count: int | None = None
    is_active: bool | None = None
    is_featured: bool | None = None
