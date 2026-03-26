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

    # ── Additional Metals — underserved regions ───────────────────────────────
    ("North American Stainless — Ghent KY", "6870 KY-1275", "Ghent", "KY", 38.7012, -84.9813,
     ["stainless_steel", "coil", "sheet_metal", "plate"], True, "msci"),
    ("Atlantic Stainless — North Attleborough MA", "315 Landry Ave", "North Attleborough", "MA", 41.9760, -71.3302,
     ["stainless_steel", "bar_stock", "rod", "tube"], True, "msci"),
    ("Penn Stainless — Quakertown PA", "754 Fairview Dr", "Quakertown", "PA", 40.4415, -75.3416,
     ["stainless_steel", "aluminum", "bar_stock", "plate", "sheet_metal"], True, "manual"),
    ("SSAB Americas — Muscatine IA", "1900 Grandview Dr", "Muscatine", "IA", 41.4245, -91.0432,
     ["steel", "carbon_steel", "plate", "coil"], True, "msci"),
    ("Commercial Metals Company — Irving TX", "6565 N MacArthur Blvd", "Irving", "TX", 32.8140, -96.9489,
     ["steel", "carbon_steel", "stainless_steel", "aluminum", "rebar", "bar_stock", "angle", "channel"], True, "msci"),
    ("Service Metals — Tulsa OK", "11111 E Pine St", "Tulsa", "OK", 36.1540, -95.9928,
     ["steel", "aluminum", "stainless_steel", "bar_stock", "tube", "plate"], True, "manual"),
    ("Southeast Steel — Jacksonville FL", "7350 Commonwealth Ave", "Jacksonville", "FL", 30.3322, -81.6557,
     ["steel", "aluminum", "stainless_steel", "bar_stock", "tube", "angle"], True, "manual"),
    ("Olympic Steel — Portland OR", "7900 NE 33rd Dr", "Portland", "OR", 45.5612, -122.5897,
     ["steel", "aluminum", "stainless_steel", "plate", "coil"], True, "msci"),
    ("Eastern Stainless — Baltimore MD", "3401 E Biddle St", "Baltimore", "MD", 39.2904, -76.5622,
     ["stainless_steel", "aluminum", "plate", "bar_stock", "sheet_metal"], True, "manual"),
    ("Flatrolled Metals — Nashville TN", "450 Metroplex Dr", "Nashville", "TN", 36.1067, -86.7497,
     ["steel", "carbon_steel", "coil", "sheet_metal", "plate"], True, "manual"),
    ("Metals Inc — Baton Rouge LA", "7975 Jefferson Hwy", "Baton Rouge", "LA", 30.4421, -91.1148,
     ["steel", "aluminum", "stainless_steel", "bar_stock", "angle", "channel"], True, "manual"),
    ("Arizona Iron Supply — Tempe AZ", "1205 W 23rd St", "Tempe", "AZ", 33.3942, -111.9749,
     ["steel", "carbon_steel", "aluminum", "bar_stock", "tube", "angle", "plate"], True, "manual"),

    # ── Wood Suppliers ───────────────────────────────────────────────────────
    ("Baillie Lumber — Hamburg NY", "4900 Lakeshore Rd", "Hamburg", "NY", 42.7173, -78.8317,
     ["oak", "maple", "walnut", "cherry", "hardwood", "lumber"], True, "manual"),
    ("Northwest Hardwoods — Tacoma WA", "2001 Taylor Way", "Tacoma", "WA", 47.2529, -122.4443,
     ["hardwood", "softwood", "oak", "maple", "birch", "walnut", "plywood"], True, "manual"),
    ("Woodworkers Source — Phoenix AZ", "645 W Grant St", "Phoenix", "AZ", 33.4413, -112.0805,
     ["oak", "maple", "walnut", "cherry", "pine", "hardwood", "plywood", "mdf"], True, "manual"),
    ("J. Gibson McIlvain — White Marsh MD", "8507 Milford Mill Rd", "Baltimore", "MD", 39.4058, -76.5251,
     ["hardwood", "oak", "walnut", "cherry", "maple", "birch"], True, "manual"),
    ("Advantage Lumber — Miami FL", "2200 SW 16th Ave", "Miami", "FL", 25.7617, -80.2785,
     ["hardwood", "plywood", "oak", "maple", "pine", "softwood"], True, "manual"),
    ("Bell Forest Products — Ishpeming MI", "130 E Bluff St", "Ishpeming", "MI", 46.4897, -87.6643,
     ["hardwood", "walnut", "maple", "cherry", "birch", "oak"], True, "manual"),
    ("Certainly Wood — East Aurora NY", "13000 Routes 20A and 78", "East Aurora", "NY", 42.7678, -78.6148,
     ["hardwood", "walnut", "cherry", "maple", "oak", "birch"], True, "manual"),
    ("Pacific Coast Lumber — Portland OR", "16000 SW 72nd Ave", "Portland", "OR", 45.4271, -122.6840,
     ["pine", "softwood", "plywood", "hardwood", "oak", "maple"], True, "manual"),
    ("Patriot Timber Products — Greenville SC", "3005 Augusta Rd", "Greenville", "SC", 34.7697, -82.4040,
     ["pine", "hardwood", "softwood", "plywood", "oak", "maple"], True, "manual"),
    ("Hardwood Industries — Nashville TN", "1500 Church St", "Nashville", "TN", 36.1627, -86.7816,
     ["hardwood", "oak", "walnut", "maple", "cherry", "plywood", "mdf"], True, "manual"),
    ("Conifer Forest Products — Bend OR", "61359 S Hwy 97", "Bend", "OR", 43.9615, -121.4144,
     ["pine", "softwood", "plywood", "lumber", "hardwood"], True, "manual"),
    ("Great Lakes Timber — Green Bay WI", "2701 Scheuring Rd", "Green Bay", "WI", 44.5133, -88.0198,
     ["hardwood", "softwood", "oak", "maple", "birch", "pine", "plywood"], True, "manual"),
    ("Rocky Mountain Hardwood — Salt Lake City UT", "600 W 400 N", "Salt Lake City", "UT", 40.7749, -111.9119,
     ["hardwood", "oak", "maple", "walnut", "pine", "plywood", "mdf"], True, "manual"),

    # ── Plastics Suppliers ──────────────────────────────────────────────────
    ("Curbell Plastics — Orchard Park NY", "7 Cobham Dr", "Orchard Park", "NY", 42.7648, -78.7487,
     ["abs", "nylon", "polycarbonate", "acrylic", "hdpe", "pvc", "ptfe", "peek", "delrin", "ultem"], True, "manual"),
    ("Professional Plastics — Fullerton CA", "500 N State College Blvd", "Fullerton", "CA", 33.8737, -117.9249,
     ["abs", "nylon", "polycarbonate", "acrylic", "hdpe", "ldpe", "pvc", "ptfe", "peek", "delrin"], True, "manual"),
    ("Interstate Plastics — Sacramento CA", "3000 Power Inn Rd", "Sacramento", "CA", 38.5316, -121.4344,
     ["abs", "nylon", "polycarbonate", "acrylic", "hdpe", "pvc", "ptfe", "peek"], True, "manual"),
    ("U.S. Plastic Corp — Lima OH", "1390 Neubrecht Rd", "Lima", "OH", 40.7428, -84.1052,
     ["abs", "nylon", "polycarbonate", "acrylic", "hdpe", "ldpe", "pet", "pvc", "ptfe", "delrin"], True, "manual"),
    ("Regal Plastics — Dallas TX", "815 N Central Expressway", "Dallas", "TX", 32.9241, -96.7305,
     ["abs", "nylon", "polycarbonate", "acrylic", "hdpe", "pvc", "ptfe"], True, "manual"),
    ("Port Plastics — Phoenix AZ", "4015 E McDowell Rd", "Phoenix", "AZ", 33.4684, -111.9850,
     ["abs", "nylon", "polycarbonate", "acrylic", "hdpe", "pvc", "ptfe", "peek", "delrin"], True, "manual"),
    ("Westlake Plastics — Lenni PA", "Lenni Road & Manning Blvd", "Lenni", "PA", 39.9176, -75.4782,
     ["nylon", "polycarbonate", "acrylic", "ptfe", "peek", "delrin", "ultem", "pvc"], True, "manual"),
    ("Piedmont Plastics — Charlotte NC", "4030 Westchase Blvd", "Charlotte", "NC", 35.2271, -80.8431,
     ["abs", "nylon", "polycarbonate", "acrylic", "hdpe", "pvc", "peek", "delrin"], True, "manual"),
    ("ePlastics — San Diego CA", "7669 Convoy Ct", "San Diego", "CA", 32.8357, -117.1511,
     ["abs", "nylon", "polycarbonate", "acrylic", "hdpe", "ldpe", "pet", "pvc", "ptfe", "peek", "delrin", "ultem"], True, "manual"),
    ("Cope Plastics — Alton IL", "4441 Industrial Dr", "Alton", "IL", 38.8906, -90.1843,
     ["abs", "nylon", "polycarbonate", "acrylic", "hdpe", "pvc", "ptfe", "delrin"], True, "manual"),
    ("AIN Plastics — Mount Vernon NY", "249 E Sandford Blvd", "Mount Vernon", "NY", 40.9126, -73.8370,
     ["abs", "nylon", "polycarbonate", "acrylic", "hdpe", "pvc", "ptfe", "peek"], True, "manual"),
    ("Polymershapes — Addison IL", "355 W Irving Park Rd", "Addison", "IL", 41.9320, -88.0031,
     ["abs", "nylon", "polycarbonate", "acrylic", "hdpe", "ldpe", "pvc", "ptfe", "peek", "delrin", "ultem"], True, "msci"),

    # ── Composites Suppliers ─────────────────────────────────────────────────
    ("Toray Composites America — Tacoma WA", "19002 50th Ave E", "Tacoma", "WA", 47.1329, -122.3243,
     ["carbon_fiber", "graphite", "composites"], True, "msci"),
    ("Hexcel — Burlington WA", "15062 Chemical Ln", "Burlington", "WA", 48.4758, -122.3262,
     ["carbon_fiber", "fiberglass", "composites"], True, "msci"),
    ("CompositesOne — Schaumburg IL", "1905 E Busse Rd", "Schaumburg", "IL", 42.0334, -88.0834,
     ["carbon_fiber", "fiberglass", "kevlar", "composites"], True, "msci"),
    ("Fibre Glast — Brookville OH", "385 Carr Dr", "Brookville", "OH", 39.8367, -84.4133,
     ["fiberglass", "carbon_fiber", "kevlar", "composites"], True, "manual"),
    ("Rock West Composites — Sandy UT", "250 W 10000 S", "Sandy", "UT", 40.5649, -111.8589,
     ["carbon_fiber", "graphite", "fiberglass", "composites"], True, "manual"),
    ("DragonPlate — Elbridge NY", "2112 Towner Rd", "Elbridge", "NY", 43.0259, -76.5496,
     ["carbon_fiber", "graphite", "composites"], True, "manual"),
    ("Composite Envisions — Wausau WI", "8300 Ridgefield Dr", "Wausau", "WI", 44.9591, -89.6301,
     ["carbon_fiber", "fiberglass", "kevlar", "graphite", "composites"], True, "manual"),
    ("CST The Composites Store — Tehachapi CA", "20128 Irene Dr", "Tehachapi", "CA", 35.1317, -118.4488,
     ["fiberglass", "carbon_fiber", "kevlar", "composites"], True, "manual"),
    ("Applied Composite Technology — Brigham City UT", "1150 S Main St", "Brigham City", "UT", 41.5110, -112.0152,
     ["carbon_fiber", "composites", "graphite"], True, "manual"),
    ("Solvay Composite Materials — Anaheim CA", "1120 W La Palma Ave", "Anaheim", "CA", 33.8611, -117.9167,
     ["carbon_fiber", "fiberglass", "composites", "ceramic_matrix"], True, "msci"),
    ("Vectorply — Scottsdale AZ", "8325 E Hartford Dr", "Scottsdale", "AZ", 33.6219, -111.8912,
     ["fiberglass", "carbon_fiber", "kevlar", "composites"], True, "manual"),
    ("Midwest Composites — Minneapolis MN", "3001 Broadway St NE", "Minneapolis", "MN", 45.0094, -93.2641,
     ["fiberglass", "carbon_fiber", "kevlar", "composites"], True, "manual"),
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
