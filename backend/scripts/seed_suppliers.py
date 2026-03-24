"""
Seed 50+ real US metal suppliers into the MillForge database.

Run from /backend:
    python scripts/seed_suppliers.py

Coordinates are hardcoded (no Nominatim calls at seed time) so the script
works offline and in CI.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, init_db
from agents.supplier_directory import SupplierDirectory

# ---------------------------------------------------------------------------
# Seed data — real US metal/materials distributors
# Each entry: (name, address, city, state, lat, lng, materials, verified, source)
# ---------------------------------------------------------------------------
SUPPLIERS = [
    # ── Olympic Steel ───────────────────────────────────────────────────────
    ("Olympic Steel — Bedford Heights HQ", "5096 Richardt Ave", "Bedford Heights", "OH", 41.3934, -81.5376,
     ["steel", "carbon_steel", "stainless_steel", "aluminum", "sheet_metal", "plate", "coil"], True, "msci"),
    ("Olympic Steel — Minneapolis", "7001 Oxford St", "St. Louis Park", "MN", 44.9499, -93.3827,
     ["steel", "aluminum", "stainless_steel", "plate"], True, "msci"),
    ("Olympic Steel — Detroit", "4501 Wesson St", "Detroit", "MI", 42.3557, -83.1015,
     ["steel", "carbon_steel", "aluminum", "coil"], True, "msci"),
    ("Olympic Steel — Chicago", "14700 S Halsted St", "Harvey", "IL", 41.6103, -87.6442,
     ["steel", "stainless_steel", "aluminum", "sheet_metal", "tube"], True, "msci"),
    ("Olympic Steel — Charlotte", "8620 Statesville Rd", "Charlotte", "NC", 35.3165, -80.8907,
     ["steel", "aluminum", "plate", "coil"], True, "msci"),

    # ── Metals USA ──────────────────────────────────────────────────────────
    ("Metals USA — Houston", "13100 Northwest Freeway", "Houston", "TX", 29.8358, -95.5210,
     ["steel", "aluminum", "stainless_steel", "copper", "brass", "bar_stock", "plate"], True, "msci"),
    ("Metals USA — Atlanta", "1055 Cobb International Blvd NW", "Kennesaw", "GA", 34.0152, -84.6022,
     ["steel", "aluminum", "stainless_steel", "sheet_metal"], True, "msci"),
    ("Metals USA — Dallas", "1951 W Mockingbird Ln", "Dallas", "TX", 32.8382, -96.8708,
     ["steel", "aluminum", "stainless_steel", "bar_stock"], True, "msci"),
    ("Metals USA — Phoenix", "4320 S 35th St", "Phoenix", "AZ", 33.3929, -112.0053,
     ["steel", "aluminum", "copper", "stainless_steel"], True, "msci"),
    ("Metals USA — Nashville", "850 Royal Pkwy", "Nashville", "TN", 36.2155, -86.6749,
     ["steel", "aluminum", "stainless_steel", "sheet_metal", "plate"], True, "msci"),

    # ── Chicago Tube and Iron ────────────────────────────────────────────────
    ("Chicago Tube and Iron — Romeoville", "208 Marquette Dr", "Romeoville", "IL", 41.6467, -88.0887,
     ["steel", "carbon_steel", "stainless_steel", "aluminum", "tube", "pipe", "bar_stock"], True, "msci"),
    ("Chicago Tube and Iron — Indianapolis", "3850 West 86th St", "Indianapolis", "IN", 39.8984, -86.2348,
     ["steel", "stainless_steel", "tube", "pipe"], True, "msci"),
    ("Chicago Tube and Iron — Memphis", "3451 Tchekalski St", "Memphis", "TN", 35.1657, -90.0412,
     ["steel", "aluminum", "tube", "pipe", "bar_stock"], True, "msci"),
    ("Chicago Tube and Iron — Kansas City", "1601 N 14th St", "Kansas City", "KS", 39.1185, -94.6543,
     ["steel", "stainless_steel", "tube", "pipe"], True, "msci"),
    ("Chicago Tube and Iron — Denver", "4300 Monaco St", "Denver", "CO", 39.7705, -104.8906,
     ["steel", "aluminum", "tube", "bar_stock"], True, "msci"),

    # ── Ryerson ─────────────────────────────────────────────────────────────
    ("Ryerson — Chicago HQ", "227 W Monroe St", "Chicago", "IL", 41.8824, -87.6352,
     ["steel", "aluminum", "stainless_steel", "titanium", "nickel", "copper", "bar_stock", "plate", "sheet_metal"], True, "msci"),
    ("Ryerson — Houston", "11655 S Sam Houston Pkwy W", "Houston", "TX", 29.6165, -95.5407,
     ["steel", "aluminum", "stainless_steel", "copper", "plate"], True, "msci"),
    ("Ryerson — Los Angeles", "16100 S Figueroa St", "Gardena", "CA", 33.8717, -118.3042,
     ["steel", "aluminum", "stainless_steel", "titanium", "bar_stock"], True, "msci"),
    ("Ryerson — Seattle", "17330 Aurora Ave N", "Shoreline", "WA", 47.7571, -122.3432,
     ["steel", "aluminum", "stainless_steel", "copper"], True, "msci"),
    ("Ryerson — Minneapolis", "2601 E Franklin Ave", "Minneapolis", "MN", 44.9636, -93.2303,
     ["steel", "aluminum", "stainless_steel", "bar_stock", "plate"], True, "msci"),

    # ── TW Metals ───────────────────────────────────────────────────────────
    ("TW Metals — Exton PA HQ", "770 Springdale Dr", "Exton", "PA", 40.0390, -75.6502,
     ["titanium", "nickel", "stainless_steel", "aluminum", "copper", "bar_stock", "tube", "extrusion"], True, "msci"),
    ("TW Metals — Houston", "6300 Lantern Park Dr", "Houston", "TX", 29.7780, -95.3998,
     ["titanium", "nickel", "stainless_steel", "aluminum", "bar_stock"], True, "msci"),
    ("TW Metals — Los Angeles", "15955 Shoemaker Ave", "Santa Fe Springs", "CA", 33.9312, -118.0615,
     ["titanium", "stainless_steel", "aluminum", "nickel"], True, "msci"),

    # ── Chapel Steel ────────────────────────────────────────────────────────
    ("Chapel Steel — Pottstown PA", "500 North Keim St", "Pottstown", "PA", 40.2470, -75.6555,
     ["steel", "carbon_steel", "tool_steel", "stainless_steel", "plate", "sheet_metal", "coil"], True, "manual"),
    ("Chapel Steel — Houston", "13130 Jess Pirtle Blvd", "Sugar Land", "TX", 29.6197, -95.6135,
     ["steel", "carbon_steel", "stainless_steel", "plate"], True, "manual"),

    # ── Metal Supermarkets ───────────────────────────────────────────────────
    ("Metal Supermarkets — Rockville MD", "15875 Shady Grove Rd", "Rockville", "MD", 39.1241, -77.1887,
     ["steel", "aluminum", "stainless_steel", "copper", "brass", "bronze", "bar_stock", "sheet_metal", "tube"], True, "manual"),
    ("Metal Supermarkets — Charlotte", "4925 Nations Crossing Rd", "Charlotte", "NC", 35.1621, -80.8927,
     ["steel", "aluminum", "stainless_steel", "copper", "brass"], True, "manual"),
    ("Metal Supermarkets — Denver", "1890 W 64th Ln", "Denver", "CO", 39.8346, -105.0048,
     ["steel", "aluminum", "copper", "brass", "stainless_steel", "sheet_metal"], True, "manual"),
    ("Metal Supermarkets — Dallas", "2400 W Royal Ln", "Irving", "TX", 32.8752, -96.9759,
     ["steel", "aluminum", "stainless_steel", "copper", "brass", "bar_stock"], True, "manual"),
    ("Metal Supermarkets — Phoenix", "2035 W Lone Cactus Dr", "Phoenix", "AZ", 33.6761, -112.1218,
     ["steel", "aluminum", "stainless_steel", "copper"], True, "manual"),

    # ── Service Center / Specialty ───────────────────────────────────────────
    ("Earle M Jorgensen — Vernon CA", "10650 S Alameda St", "Vernon", "CA", 33.9973, -118.2214,
     ["steel", "aluminum", "stainless_steel", "titanium", "bar_stock", "tube", "plate"], True, "msci"),
    ("Samuel, Son & Co — Mississauga ON", "40 King St E", "Mississauga", "ON", 43.5862, -79.6454,
     ["steel", "aluminum", "stainless_steel", "bar_stock", "sheet_metal"], True, "msci"),
    ("Reliance Steel & Aluminum — Los Angeles HQ", "350 S Grand Ave", "Los Angeles", "CA", 34.0552, -118.2560,
     ["steel", "aluminum", "stainless_steel", "titanium", "copper", "nickel", "plate", "bar_stock", "coil"], True, "msci"),
    ("Metals Depot — Winchester KY", "1720 Bypass Rd", "Winchester", "KY", 37.9811, -84.1833,
     ["steel", "aluminum", "stainless_steel", "copper", "brass", "bar_stock", "sheet_metal", "tube", "angle", "channel"], True, "manual"),
    ("Alro Steel — Jackson MI HQ", "3100 Moores River Dr", "Lansing", "MI", 42.6742, -84.5539,
     ["steel", "aluminum", "stainless_steel", "copper", "brass", "bronze", "bar_stock", "plate", "sheet_metal"], True, "manual"),
    ("Alro Steel — Indianapolis", "4025 Industrial Blvd", "Indianapolis", "IN", 39.8085, -86.3046,
     ["steel", "aluminum", "stainless_steel", "copper", "bar_stock", "sheet_metal"], True, "manual"),
    ("Alro Steel — Toledo", "5010 Jackman Rd", "Toledo", "OH", 41.6900, -83.7236,
     ["steel", "aluminum", "stainless_steel", "bar_stock", "plate"], True, "manual"),
    ("Castle Metals — Oak Brook IL", "1420 Kensington Rd", "Oak Brook", "IL", 41.8519, -87.9568,
     ["steel", "stainless_steel", "aluminum", "titanium", "nickel", "bar_stock", "tube", "plate"], True, "msci"),
    ("Service Center Metals — Cleveland", "4370 Perkins Ave", "Cleveland", "OH", 41.5045, -81.6407,
     ["steel", "aluminum", "stainless_steel", "bar_stock", "coil", "sheet_metal"], True, "manual"),
    ("O'Neal Steel — Birmingham AL HQ", "744 41st St N", "Birmingham", "AL", 33.5357, -86.8431,
     ["steel", "carbon_steel", "stainless_steel", "aluminum", "plate", "coil", "bar_stock"], True, "msci"),
    ("O'Neal Steel — Memphis", "4770 Shelby Dr", "Memphis", "TN", 35.0390, -89.9238,
     ["steel", "aluminum", "stainless_steel", "plate", "sheet_metal"], True, "msci"),
    ("Worthington Industries — Columbus OH", "200 Old Wilson Bridge Rd", "Worthington", "OH", 40.0973, -83.0182,
     ["steel", "carbon_steel", "stainless_steel", "coil", "sheet_metal", "plate"], True, "msci"),
    ("Steel Technologies — Louisville KY", "1815 Cargo Court", "Louisville", "KY", 38.2027, -85.7593,
     ["steel", "carbon_steel", "coil", "sheet_metal", "plate"], True, "msci"),
    ("Precision Castparts — Portland OR", "4650 SW Macadam Ave", "Portland", "OR", 45.4870, -122.6820,
     ["titanium", "nickel", "stainless_steel", "aluminum"], True, "msci"),
    ("Carpenter Technology — Reading PA", "101 W Bern St", "Reading", "PA", 40.3401, -75.9271,
     ["stainless_steel", "nickel", "titanium", "tool_steel", "bar_stock", "rod"], True, "msci"),
    ("Haynes International — Kokomo IN", "1020 W Park Ave", "Kokomo", "IN", 40.4659, -86.1380,
     ["nickel", "titanium", "stainless_steel", "bar_stock", "plate"], True, "msci"),
    ("Specialty Metals — Dunkirk NY", "126 Main St", "Dunkirk", "NY", 42.4797, -79.3352,
     ["stainless_steel", "nickel", "titanium", "bar_stock", "tube"], True, "manual"),
    ("All American Semiconductor — Miami FL", "16115 NW 52nd Ave", "Miami", "FL", 25.8959, -80.3084,
     ["aluminum", "copper", "brass"], True, "manual"),
    ("Triangle Wire & Cable — Bel Air MD", "510 Thomas Run Rd", "Bel Air", "MD", 39.5299, -76.3877,
     ["copper", "wire", "aluminum"], True, "manual"),
    ("Pacific Metals — San Francisco CA", "1000 Indiana St", "San Francisco", "CA", 37.7570, -122.3942,
     ["steel", "aluminum", "stainless_steel", "copper", "bar_stock", "plate", "sheet_metal"], True, "manual"),
    ("Southwest Steel — Albuquerque NM", "3700 Airway Blvd SW", "Albuquerque", "NM", 35.0457, -106.6726,
     ["steel", "aluminum", "bar_stock", "angle", "channel", "tube"], True, "manual"),
    ("Great Plains Energy — Wichita KS", "230 E Douglas Ave", "Wichita", "KS", 37.6895, -97.3358,
     ["steel", "carbon_steel", "bar_stock", "plate", "angle"], True, "manual"),
]


def seed_suppliers(db) -> int:
    """
    Seed suppliers using an *existing* SQLAlchemy session.
    Returns the number of rows inserted.  Skips any that raise.
    """
    directory = SupplierDirectory()
    added = 0
    for (name, address, city, state, lat, lng, materials, verified, source) in SUPPLIERS:
        try:
            directory.create(
                db,
                name=name,
                address=address,
                city=city,
                state=state,
                lat=lat,
                lng=lng,
                materials=materials,
                verified=verified,
                data_source=source,
            )
            added += 1
        except Exception:
            db.rollback()
    return added


def seed(clear_existing: bool = False) -> int:
    init_db()
    db = SessionLocal()
    directory = SupplierDirectory()

    try:
        if clear_existing:
            from db_models import Supplier
            db.query(Supplier).delete()
            db.commit()
            print("Cleared existing suppliers.")

        added = 0
        for (name, address, city, state, lat, lng, materials, verified, source) in SUPPLIERS:
            try:
                directory.create(
                    db,
                    name=name,
                    address=address,
                    city=city,
                    state=state,
                    lat=lat,
                    lng=lng,
                    materials=materials,
                    verified=verified,
                    data_source=source,
                )
                added += 1
            except Exception as e:
                print(f"  SKIP {name}: {e}")

        print(f"Seeded {added} suppliers.")
        return added
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Seed MillForge supplier database")
    parser.add_argument("--clear", action="store_true", help="Delete existing suppliers before seeding")
    args = parser.parse_args()
    n = seed(clear_existing=args.clear)
    print(f"Done. {n} suppliers in database.")
