"""Sectores calientes al estilo Qullamaggie: "I wanna focus on the fast moving stocks in the hot sectors".

En sus directos no mide los sectores con índices sino con sus escáneres: un sector está caliente cuando
muchos de sus valores aparecen a la vez entre los que más suben a 1, 3 y 6 meses ("which sectors had a
lot of 50-100% moves over the past few weeks, boom, that's the leading sector"). Y en un sector caliente
"hasta las peores acciones se mueven más que las mejores de un sector frío".

- Sector: la industria de Yahoo Finance (biotecnología, semiconductores, uranio, solar, transporte
  marítimo...), que es el grano con el que él habla de sectores; si aún no hay perfil, la subindustria GICS.
- Escáner: el 7% del mercado de EE. UU. que más sube a 1, 3 o 6 meses desde el mínimo del periodo
  (su "rank 93" de TC2000), con los mismos umbrales para los internacionales.
- Calor: valores del sector en el escáner × la parte del sector que suponen (n² / tamaño). Solo el número
  favorecería siempre a los sectores enormes (biotecnología o bancos regionales tienen cientos de valores y
  siempre aportan alguno por azar); solo la proporción, a los de tres valores. El producto pide las dos cosas.
- Caliente: al menos 3 valores en el escáner, el doble de su cuota normal (14% del sector con un escáner
  del 7%) y entre los 8 de más calor.
- Valores rápidos: los del escáner con ADR ≥ 5% que siguen en forma (no descartados: ni bajo la SMA50,
  ni con la ruptura fallida, ni lejos del nivel).
- Solo EE. UU., como sus escáneres: es el único mercado con todo el universo líquido; los internacionales
  entran en el radar por ser líderes o ganadores y harían parecer calientes sus sectores.
"""
from __future__ import annotations

import statistics

DEFAULTS = {"us_only": True, "scan_pct": 0.07, "hot_min": 3, "hot_lift": 2.0, "hot_top": 8, "fast_adr": 0.05, "focus_per_group": 15}

# Industrias de Yahoo Finance en español (las que no estén aquí se muestran en inglés).
INDUSTRY_ES = {
    "Advertising Agencies": "Agencias de publicidad", "Aerospace & Defense": "Aeroespacial y defensa",
    "Agricultural Inputs": "Insumos agrícolas", "Airlines": "Aerolíneas", "Airports & Air Services": "Aeropuertos",
    "Aluminum": "Aluminio", "Apparel Manufacturing": "Confección", "Apparel Retail": "Moda (tiendas)",
    "Asset Management": "Gestoras de activos", "Auto Manufacturers": "Fabricantes de automóviles",
    "Auto Parts": "Componentes de automoción", "Auto & Truck Dealerships": "Concesionarios",
    "Banks - Diversified": "Bancos diversificados", "Banks - Regional": "Bancos regionales",
    "Beverages - Brewers": "Cerveceras", "Beverages - Non-Alcoholic": "Bebidas sin alcohol",
    "Beverages - Wineries & Distilleries": "Vinos y destilados", "Biotechnology": "Biotecnología",
    "Broadcasting": "Radio y televisión", "Building Materials": "Materiales de construcción",
    "Building Products & Equipment": "Productos de construcción", "Business Equipment & Supplies": "Equipos de oficina",
    "Capital Markets": "Mercados de capitales", "Chemicals": "Química", "Coking Coal": "Carbón metalúrgico",
    "Communication Equipment": "Equipos de comunicaciones", "Computer Hardware": "Hardware informático",
    "Confectioners": "Confitería", "Conglomerates": "Conglomerados", "Consulting Services": "Consultoría",
    "Consumer Electronics": "Electrónica de consumo", "Copper": "Cobre", "Credit Services": "Crédito al consumo",
    "Department Stores": "Grandes almacenes", "Diagnostics & Research": "Diagnóstico e investigación",
    "Discount Stores": "Tiendas de descuento", "Drug Manufacturers - General": "Farmacéuticas",
    "Drug Manufacturers - Specialty & Generic": "Farmacéuticas especializadas y genéricos",
    "Education & Training Services": "Educación", "Electrical Equipment & Parts": "Equipo eléctrico",
    "Electronic Components": "Componentes electrónicos", "Electronic Gaming & Multimedia": "Videojuegos",
    "Electronics & Computer Distribution": "Distribución de electrónica", "Engineering & Construction": "Ingeniería y construcción",
    "Entertainment": "Entretenimiento", "Farm & Heavy Construction Machinery": "Maquinaria agrícola y pesada",
    "Farm Products": "Productos agrícolas", "Financial Conglomerates": "Conglomerados financieros",
    "Financial Data & Stock Exchanges": "Datos financieros y bolsas", "Food Distribution": "Distribución de alimentos",
    "Footwear & Accessories": "Calzado y complementos", "Furnishings, Fixtures & Appliances": "Muebles y electrodomésticos",
    "Gambling": "Juego", "Gold": "Oro", "Grocery Stores": "Supermercados", "Health Information Services": "Información sanitaria",
    "Healthcare Plans": "Seguros de salud", "Home Improvement Retail": "Bricolaje", "Household & Personal Products": "Hogar e higiene",
    "Industrial Distribution": "Distribución industrial", "Information Technology Services": "Servicios IT",
    "Infrastructure Operations": "Operadores de infraestructuras", "Insurance - Diversified": "Seguros diversificados",
    "Insurance - Life": "Seguros de vida", "Insurance - Property & Casualty": "Seguros de daños",
    "Insurance - Reinsurance": "Reaseguro", "Insurance - Specialty": "Seguros especializados",
    "Insurance Brokers": "Corredurías de seguros", "Integrated Freight & Logistics": "Logística",
    "Internet Content & Information": "Internet: contenidos", "Internet Retail": "Comercio electrónico",
    "Leisure": "Ocio", "Lodging": "Hoteles", "Lumber & Wood Production": "Madera", "Luxury Goods": "Lujo",
    "Marine Shipping": "Transporte marítimo", "Medical Care Facilities": "Centros sanitarios",
    "Medical Devices": "Dispositivos médicos", "Medical Distribution": "Distribución sanitaria",
    "Medical Instruments & Supplies": "Instrumental médico", "Metal Fabrication": "Transformados metálicos",
    "Mortgage Finance": "Financiación hipotecaria", "Oil & Gas Drilling": "Perforación petrolera",
    "Oil & Gas E&P": "Petróleo y gas: exploración", "Oil & Gas Equipment & Services": "Servicios petroleros",
    "Oil & Gas Integrated": "Petroleras integradas", "Oil & Gas Midstream": "Oleoductos y gasoductos",
    "Oil & Gas Refining & Marketing": "Refino", "Other Industrial Metals & Mining": "Minería industrial",
    "Other Precious Metals & Mining": "Metales preciosos", "Packaged Foods": "Alimentación envasada",
    "Packaging & Containers": "Envases", "Paper & Paper Products": "Papel", "Personal Services": "Servicios personales",
    "Pharmaceutical Retailers": "Farmacias", "Pollution & Treatment Controls": "Control de contaminación",
    "Publishing": "Editoriales", "Railroads": "Ferrocarriles", "Real Estate - Development": "Promoción inmobiliaria",
    "Real Estate - Diversified": "Inmobiliarias diversificadas", "Real Estate Services": "Servicios inmobiliarios",
    "Recreational Vehicles": "Vehículos recreativos", "Refiners & Pipelines": "Refino y oleoductos",
    "Rental & Leasing Services": "Alquiler de equipos", "Residential Construction": "Constructoras de viviendas",
    "Resorts & Casinos": "Resorts y casinos", "Restaurants": "Restaurantes", "REIT - Diversified": "REIT diversificados",
    "REIT - Healthcare Facilities": "REIT sanitarios", "REIT - Hotel & Motel": "REIT hoteleros",
    "REIT - Industrial": "REIT industriales", "REIT - Mortgage": "REIT hipotecarios", "REIT - Office": "REIT de oficinas",
    "REIT - Residential": "REIT residenciales", "REIT - Retail": "REIT comerciales", "REIT - Specialty": "REIT especializados",
    "Scientific & Technical Instruments": "Instrumentos científicos", "Security & Protection Services": "Seguridad",
    "Semiconductor Equipment & Materials": "Equipos y materiales para semiconductores", "Semiconductors": "Semiconductores",
    "Shell Companies": "Sociedades instrumentales (SPAC)", "Silver": "Plata", "Software - Application": "Software de aplicaciones",
    "Software - Infrastructure": "Software de infraestructura", "Solar": "Solar", "Specialty Business Services": "Servicios a empresas",
    "Specialty Chemicals": "Química especializada", "Specialty Industrial Machinery": "Maquinaria industrial",
    "Specialty Retail": "Comercio especializado", "Staffing & Employment Services": "Empleo y selección",
    "Steel": "Acero", "Telecom Services": "Telecomunicaciones", "Textile Manufacturing": "Textil",
    "Thermal Coal": "Carbón térmico", "Tobacco": "Tabaco", "Tools & Accessories": "Herramientas",
    "Travel Services": "Viajes", "Trucking": "Transporte por carretera", "Uranium": "Uranio",
    "Utilities - Diversified": "Eléctricas diversificadas", "Utilities - Independent Power Producers": "Productores independientes de electricidad",
    "Utilities - Regulated Electric": "Eléctricas reguladas", "Utilities - Regulated Gas": "Gas regulado",
    "Utilities - Regulated Water": "Agua", "Utilities - Renewable": "Renovables", "Waste Management": "Gestión de residuos",
}


# Subindustria GICS → industria de Yahoo, para que los valores del S&P sin perfil de Yahoo caigan en el
# mismo sector que el resto.
GICS_TO_YAHOO = {
    "Application Software": "Software - Application", "Systems Software": "Software - Infrastructure",
    "Internet Services & Infrastructure": "Software - Infrastructure", "Semiconductors": "Semiconductors",
    "Semiconductor Materials & Equipment": "Semiconductor Equipment & Materials", "Biotechnology": "Biotechnology",
    "Pharmaceuticals": "Drug Manufacturers - Specialty & Generic", "Life Sciences Tools & Services": "Diagnostics & Research",
    "Health Care Equipment": "Medical Devices", "Health Care Supplies": "Medical Instruments & Supplies",
    "Health Care Services": "Medical Care Facilities", "Health Care Facilities": "Medical Care Facilities",
    "Managed Health Care": "Healthcare Plans", "Health Care Technology": "Health Information Services",
    "Health Care Distributors": "Medical Distribution", "Regional Banks": "Banks - Regional",
    "Diversified Banks": "Banks - Diversified", "Asset Management & Custody Banks": "Asset Management",
    "Investment Banking & Brokerage": "Capital Markets", "Financial Exchanges & Data": "Financial Data & Stock Exchanges",
    "Consumer Finance": "Credit Services", "Transaction & Payment Processing Services": "Credit Services",
    "Property & Casualty Insurance": "Insurance - Property & Casualty", "Life & Health Insurance": "Insurance - Life",
    "Insurance Brokers": "Insurance Brokers", "Reinsurance": "Insurance - Reinsurance",
    "Multi-line Insurance": "Insurance - Diversified", "Oil & Gas Exploration & Production": "Oil & Gas E&P",
    "Oil & Gas Equipment & Services": "Oil & Gas Equipment & Services", "Integrated Oil & Gas": "Oil & Gas Integrated",
    "Oil & Gas Refining & Marketing": "Oil & Gas Refining & Marketing", "Oil & Gas Storage & Transportation": "Oil & Gas Midstream",
    "Oil & Gas Drilling": "Oil & Gas Drilling", "Aerospace & Defense": "Aerospace & Defense",
    "Electrical Components & Equipment": "Electrical Equipment & Parts", "Heavy Electrical Equipment": "Specialty Industrial Machinery",
    "Industrial Machinery & Supplies & Components": "Specialty Industrial Machinery",
    "Construction & Engineering": "Engineering & Construction",
    "Construction Machinery & Heavy Transportation Equipment": "Farm & Heavy Construction Machinery",
    "Agricultural & Farm Machinery": "Farm & Heavy Construction Machinery", "Building Products": "Building Products & Equipment",
    "Construction Materials": "Building Materials", "Homebuilding": "Residential Construction",
    "Electronic Components": "Electronic Components", "Electronic Equipment & Instruments": "Scientific & Technical Instruments",
    "Electronic Manufacturing Services": "Electronic Components", "Technology Hardware, Storage & Peripherals": "Computer Hardware",
    "Communications Equipment": "Communication Equipment", "IT Consulting & Other Services": "Information Technology Services",
    "Broadline Retail": "Internet Retail", "Internet & Direct Marketing Retail": "Internet Retail", "Restaurants": "Restaurants",
    "Hotels, Resorts & Cruise Lines": "Travel Services", "Casinos & Gaming": "Resorts & Casinos",
    "Automobile Manufacturers": "Auto Manufacturers", "Automotive Parts & Equipment": "Auto Parts",
    "Apparel, Accessories & Luxury Goods": "Apparel Manufacturing", "Footwear": "Footwear & Accessories",
    "Apparel Retail": "Apparel Retail", "Other Specialty Retail": "Specialty Retail", "Home Improvement Retail": "Home Improvement Retail",
    "Packaged Foods & Meats": "Packaged Foods", "Soft Drinks & Non-alcoholic Beverages": "Beverages - Non-Alcoholic",
    "Household Products": "Household & Personal Products", "Personal Care Products": "Household & Personal Products",
    "Steel": "Steel", "Gold": "Gold", "Copper": "Copper", "Diversified Metals & Mining": "Other Industrial Metals & Mining",
    "Specialty Chemicals": "Specialty Chemicals", "Commodity Chemicals": "Chemicals",
    "Fertilizers & Agricultural Chemicals": "Agricultural Inputs", "Electric Utilities": "Utilities - Regulated Electric",
    "Gas Utilities": "Utilities - Regulated Gas", "Multi-Utilities": "Utilities - Diversified",
    "Water Utilities": "Utilities - Regulated Water",
    "Independent Power Producers & Energy Traders": "Utilities - Independent Power Producers",
    "Renewable Electricity": "Utilities - Renewable", "Airlines": "Airlines", "Air Freight & Logistics": "Integrated Freight & Logistics",
    "Marine Transportation": "Marine Shipping", "Rail Transportation": "Railroads", "Cargo Ground Transportation": "Trucking",
    "Movies & Entertainment": "Entertainment", "Interactive Home Entertainment": "Electronic Gaming & Multimedia",
    "Interactive Media & Services": "Internet Content & Information", "Broadcasting": "Broadcasting",
    "Advertising": "Advertising Agencies", "Integrated Telecommunication Services": "Telecom Services",
    "Wireless Telecommunication Services": "Telecom Services", "Trading Companies & Distributors": "Industrial Distribution",
    "Environmental & Facilities Services": "Waste Management", "Human Resource & Employment Services": "Staffing & Employment Services",
    "Research & Consulting Services": "Consulting Services", "Leisure Products": "Leisure", "Education Services": "Education & Training Services",
}


def group_of(info: dict, profile: dict | None) -> str | None:
    """Sector fino del valor: industria de Yahoo; si aún no hay perfil, su subindustria GICS traducida a la
    industria de Yahoo equivalente."""
    ind = (profile or {}).get("industry")
    if ind:
        return ind
    sub = info.get("gics_sub")
    return GICS_TO_YAHOO.get(sub, sub) if sub else None


def name_es(group: str) -> str:
    return INDUSTRY_ES.get(group, group)


def scan_hits(m, cut: dict) -> list[str]:
    """Plazos (1, 3, 6 meses) en los que el valor entra en el escáner."""
    out = []
    for lab, k in (("1 m", "mom1"), ("3 m", "mom3"), ("6 m", "mom6")):
        v, c = getattr(m, k), cut.get(k)
        if v is not None and c is not None and v >= c:
            out.append(lab)
    return out


def hot_groups(rows: list[dict], cfg: dict | None = None, prev: dict | None = None) -> list[dict]:
    """Ranking de sectores por calor (valores en el escáner × proporción del sector). `rows`: filas del radar con
    `group`, `scan` (plazos), `m` (métricas) y `sym`. `prev`: {sector: valores en el escáner} de la sesión
    anterior, para ver si se calienta o se enfría."""
    q = {**DEFAULTS, **(cfg or {})}
    by: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("group"):
            by.setdefault(r["group"], []).append(r)
    out = []
    for g, mem in by.items():
        sc = [r for r in mem if r.get("scan")]
        if not sc:
            continue
        fast = [r for r in sc if r["m"].adr_pct >= q["fast_adr"]]
        m3 = [r["m"].mom3 for r in sc if r["m"].mom3 is not None]
        m1 = [r["m"].mom1 for r in sc if r["m"].mom1 is not None]
        top = sorted(sc, key=lambda r: -(r["m"].mom3 or 0))
        out.append({
            "group": g, "name": name_es(g), "n": len(mem), "scan_n": len(sc), "fast_n": len(fast),
            "share": len(sc) / len(mem), "heat": len(sc) ** 2 / len(mem),
            "med_mom1": statistics.median(m1) if m1 else None,
            "med_mom3": statistics.median(m3) if m3 else None,
            "top": [r["sym"] for r in top[:8]],
            "prev_scan_n": (prev or {}).get(g),
        })
    out.sort(key=lambda x: (-x["heat"], -x["scan_n"], -(x["med_mom3"] or 0)))
    lift = q["hot_lift"] * q["scan_pct"]
    for i, x in enumerate(out):
        x["rank"] = i + 1
        x["hot"] = x["scan_n"] >= q["hot_min"] and x["share"] >= lift and i < q["hot_top"]
    return out
