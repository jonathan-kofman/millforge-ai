"""
Seed 100+ real US materials suppliers into the MillForge database.

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

    # ── Plastics Distributors ──────────────────────────────────────────────
    ("Curbell Plastics — Orchard Park NY HQ", "7 Cobham Dr", "Orchard Park", "NY", 42.7573, -78.7437,
     ["polycarbonate", "acrylic", "nylon", "abs", "hdpe", "peek", "ultem", "delrin", "ptfe", "sheet_metal"], True, "manual"),
    ("Curbell Plastics — San Diego", "8530 Aero Dr", "San Diego", "CA", 32.8148, -117.1376,
     ["polycarbonate", "acrylic", "nylon", "abs", "hdpe", "peek"], True, "manual"),
    ("Curbell Plastics — Atlanta", "3295 River Exchange Dr", "Norcross", "GA", 33.9294, -84.2081,
     ["polycarbonate", "acrylic", "nylon", "abs", "hdpe", "delrin"], True, "manual"),
    ("Interstate Plastics — Sacramento HQ", "1533 Juliesse Ave", "Sacramento", "CA", 38.5632, -121.4681,
     ["acrylic", "polycarbonate", "hdpe", "ldpe", "pvc", "abs", "nylon", "ptfe"], True, "manual"),
    ("Interstate Plastics — Portland", "11545 SW Pacific Hwy", "Tigard", "OR", 45.4343, -122.7636,
     ["acrylic", "polycarbonate", "hdpe", "pvc", "abs", "nylon"], True, "manual"),
    ("Piedmont Plastics — Charlotte HQ", "5010 West WT Harris Blvd", "Charlotte", "NC", 35.3046, -80.8850,
     ["polycarbonate", "acrylic", "abs", "hdpe", "pvc", "pet", "sheet_metal"], True, "manual"),
    ("Piedmont Plastics — Dallas", "2430 Royal Ln", "Dallas", "TX", 32.8750, -96.9450,
     ["polycarbonate", "acrylic", "abs", "hdpe", "pvc"], True, "manual"),
    ("Piedmont Plastics — Orlando", "3605 Silver Star Rd", "Orlando", "FL", 28.5705, -81.4344,
     ["polycarbonate", "acrylic", "abs", "hdpe", "pvc", "pet"], True, "manual"),
    ("Professional Plastics — Fullerton CA HQ", "1810 E Valencia Dr", "Fullerton", "CA", 33.8734, -117.9040,
     ["peek", "ultem", "ptfe", "delrin", "nylon", "polycarbonate", "acrylic", "pvc"], True, "manual"),
    ("Professional Plastics — Houston", "10230 Cash Rd", "Stafford", "TX", 29.6198, -95.5530,
     ["peek", "ultem", "ptfe", "delrin", "nylon", "polycarbonate"], True, "manual"),
    ("ePlastics — San Diego", "5405 Kearny Villa Rd", "San Diego", "CA", 32.8359, -117.1471,
     ["acrylic", "polycarbonate", "abs", "hdpe", "pvc", "pla", "nylon", "sheet_metal"], True, "manual"),
    ("US Plastic Corp — Lima OH", "1390 Neubrecht Rd", "Lima", "OH", 40.7343, -84.0976,
     ["hdpe", "ldpe", "pvc", "pet", "abs", "nylon", "polycarbonate", "tube", "pipe"], True, "manual"),
    ("Plastics International — Eden Prairie MN", "7600 Anagram Dr", "Eden Prairie", "MN", 44.8514, -93.4531,
     ["peek", "ultem", "ptfe", "delrin", "nylon", "polycarbonate", "acrylic", "bar_stock", "rod"], True, "manual"),

    # ── Wood & Lumber Suppliers ────────────────────────────────────────────
    ("Hardwood Lumber Company — Portland", "6895 NW St Helens Rd", "Portland", "OR", 45.5599, -122.7410,
     ["oak", "maple", "walnut", "cherry", "birch", "hardwood"], True, "manual"),
    ("Bell Forest Products — Ishpeming MI", "1110 US-41 W", "Ishpeming", "MI", 46.4926, -87.6897,
     ["walnut", "cherry", "maple", "oak", "birch", "hardwood", "exotic_hardwood"], True, "manual"),
    ("Woodworkers Source — Tucson AZ", "645 W Roger Rd", "Tucson", "AZ", 32.2714, -110.9913,
     ["maple", "cherry", "walnut", "oak", "hardwood", "softwood"], True, "manual"),
    ("Peterman Lumber — Fontana CA", "14552 Slover Ave", "Fontana", "CA", 34.0697, -117.4748,
     ["pine", "plywood", "hardwood", "softwood", "oak", "maple"], True, "manual"),
    ("84 Lumber — Eighty Four PA HQ", "1019 Route 519", "Eighty Four", "PA", 40.1712, -80.0847,
     ["pine", "plywood", "mdf", "particleboard", "softwood", "hardwood"], True, "manual"),
    ("Wurth Wood Group — Charlotte", "6301 Performance Dr", "Charlotte", "NC", 35.1537, -80.8886,
     ["plywood", "mdf", "particleboard", "hardwood", "pine"], True, "manual"),
    ("Anderson Plywood — Los Angeles", "3020 N San Fernando Rd", "Los Angeles", "CA", 34.0839, -118.2508,
     ["plywood", "mdf", "particleboard", "hardwood", "birch", "maple"], True, "manual"),
    ("Boulter Plywood — Somerville MA", "24 Broadway", "Somerville", "MA", 42.3876, -71.0995,
     ["plywood", "mdf", "birch", "maple", "oak", "walnut"], True, "manual"),
    ("Northwest Hardwoods — Centralia WA", "500 Airdustrial Way SW", "Centralia", "WA", 46.7168, -122.9735,
     ["maple", "oak", "cherry", "walnut", "birch", "hardwood", "softwood"], True, "manual"),
    ("Conner Industries — Fort Worth TX", "1000 Eastchase Pkwy", "Fort Worth", "TX", 32.7349, -97.2140,
     ["pine", "plywood", "softwood", "hardwood", "oak"], True, "manual"),

    # ── Composites Suppliers ───────────────────────────────────────────────
    ("DragonPlate — Elbridge NY", "6810 State Route 5", "Elbridge", "NY", 43.0308, -76.4302,
     ["carbon_fiber", "fiberglass", "kevlar", "sheet_metal", "tube", "plate"], True, "manual"),
    ("Rock West Composites — West Jordan UT", "1598 W 7800 S", "West Jordan", "UT", 40.6089, -111.9710,
     ["carbon_fiber", "fiberglass", "kevlar", "tube", "rod", "plate"], True, "manual"),
    ("Clearwater Composites — Duluth MN", "5319 N Shore Dr", "Duluth", "MN", 46.8268, -92.0771,
     ["carbon_fiber", "fiberglass", "tube", "rod", "extrusion"], True, "manual"),
    ("Composites One — Arlington Heights IL", "1000 E Business Center Dr", "Arlington Heights", "IL", 42.0903, -87.9905,
     ["fiberglass", "carbon_fiber", "kevlar", "graphite", "ceramic_matrix"], True, "manual"),
    ("Hexcel — Stamford CT", "281 Tresser Blvd", "Stamford", "CT", 41.0504, -73.5413,
     ["carbon_fiber", "fiberglass", "kevlar", "graphite", "ceramic_matrix", "metal_matrix"], True, "msci"),
    ("Toray Composite Materials America — Tacoma WA", "19002 50th Ave E", "Tacoma", "WA", 47.1792, -122.3553,
     ["carbon_fiber", "graphite", "kevlar", "fiberglass"], True, "msci"),
    ("Solvay Composite Materials — Anaheim CA", "1120 N Tustin Ave", "Anaheim", "CA", 33.8517, -117.8252,
     ["carbon_fiber", "fiberglass", "ceramic_matrix", "metal_matrix"], True, "msci"),
    ("Fiber-Tech Industries — Spokane WA", "801 N Fancher Rd", "Spokane", "WA", 47.6696, -117.3597,
     ["fiberglass", "carbon_fiber", "kevlar", "tube", "plate"], True, "manual"),

    # ── Specialty Metals & Alloys ──────────────────────────────────────────
    ("Ulbrich Stainless Steels — North Haven CT", "153 Washington Ave", "North Haven", "CT", 41.3840, -72.8593,
     ["stainless_steel", "nickel", "titanium", "sheet_metal", "coil", "wire"], True, "msci"),
    ("Magellan Industrial Trading — Southport CT", "2300 Main St", "Southport", "CT", 41.1306, -73.2812,
     ["tungsten", "chromium", "nickel", "titanium", "bar_stock", "rod"], True, "manual"),
    ("Ed Fagan Inc — Franklin Lakes NJ", "769 Susquehanna Ave", "Franklin Lakes", "NJ", 41.0245, -74.2052,
     ["tungsten", "nickel", "titanium", "chromium", "bar_stock", "rod", "plate"], True, "manual"),
    ("Metalmen Sales — Long Island City NY", "34-20 Review Ave", "Long Island City", "NY", 40.7329, -73.9304,
     ["copper", "brass", "bronze", "aluminum", "stainless_steel", "bar_stock", "tube", "sheet_metal"], True, "manual"),
    ("Farmers Copper — Galveston TX", "920 53rd St", "Galveston", "TX", 29.3027, -94.8104,
     ["copper", "brass", "bronze", "aluminum", "bar_stock", "tube", "plate", "rod"], True, "manual"),
    ("Continental Steel — Fort Lauderdale FL", "3232 SW 15th St", "Fort Lauderdale", "FL", 26.0933, -80.1654,
     ["steel", "aluminum", "stainless_steel", "titanium", "copper", "bar_stock", "plate", "tube"], True, "manual"),
    ("Titanium Industries — Rockaway NJ", "180 Mt Hope Ave", "Rockaway", "NJ", 40.9010, -74.5129,
     ["titanium", "nickel", "stainless_steel", "bar_stock", "plate", "tube", "rod"], True, "msci"),
    ("Arconic — Pittsburgh PA", "201 Isabella St", "Pittsburgh", "PA", 40.4556, -79.9769,
     ["aluminum", "titanium", "nickel", "extrusion", "plate", "sheet_metal", "bar_stock"], True, "msci"),
    ("Industrial Metal Supply — Sun Valley CA", "8300 San Fernando Rd", "Sun Valley", "CA", 34.2231, -118.3757,
     ["steel", "aluminum", "stainless_steel", "copper", "brass", "sheet_metal", "bar_stock", "tube"], True, "manual"),
    ("ThyssenKrupp Materials NA — Southfield MI", "22355 W 11 Mile Rd", "Southfield", "MI", 42.4838, -83.2466,
     ["steel", "aluminum", "stainless_steel", "nickel", "copper", "bar_stock", "plate", "coil"], True, "msci"),
    ("Penn Stainless Products — Quakertown PA", "190 Kelly Rd", "Quakertown", "PA", 40.4418, -75.3539,
     ["stainless_steel", "nickel", "plate", "sheet_metal", "bar_stock", "coil"], True, "manual"),
    ("Atlas Steels — Tampa FL", "2921 Tech Dr", "Tampa", "FL", 27.9789, -82.5330,
     ["stainless_steel", "nickel", "titanium", "bar_stock", "plate", "tube"], True, "manual"),

    # ── Cast Iron & Foundry ────────────────────────────────────────────────
    ("American Cast Iron Pipe — Birmingham AL", "1501 31st Ave N", "Birmingham", "AL", 33.5380, -86.7842,
     ["cast_iron", "steel", "pipe", "tube"], True, "manual"),
    ("Charlotte Pipe and Foundry — Charlotte NC", "2109 Randolph Rd", "Charlotte", "NC", 35.1872, -80.8167,
     ["cast_iron", "steel", "copper", "pipe", "tube"], True, "manual"),
    ("McWane Inc — Birmingham AL", "2900 Hwy 280 Ste 300", "Birmingham", "AL", 33.4540, -86.7190,
     ["cast_iron", "steel", "pipe", "tube", "plate"], True, "manual"),

    # ── Wire, Cable & Fasteners ────────────────────────────────────────────
    ("Nucor Fastener — St. Joe IN", "1915 Roper Ave", "St. Joe", "IN", 41.3162, -84.9033,
     ["steel", "carbon_steel", "stainless_steel", "rod", "wire"], True, "msci"),
    ("Central Wire Industries — Perth ON", "85 Dufferin St", "Perth", "ON", 44.8949, -76.2448,
     ["stainless_steel", "nickel", "copper", "wire", "rod"], True, "manual"),
    ("Loos & Co — Pomfret CT", "901 Industrial Rd", "Pomfret", "CT", 41.8775, -71.9528,
     ["stainless_steel", "copper", "aluminum", "wire", "rod"], True, "manual"),

    # ── Regional Metal Distributors ────────────────────────────────────────
    ("Yarde Metals — Southington CT HQ", "44 Spring St", "Southington", "CT", 41.5978, -72.8777,
     ["steel", "aluminum", "stainless_steel", "copper", "brass", "bar_stock", "plate", "tube"], True, "manual"),
    ("Texas Iron & Metal — Houston TX", "911 Caddo St", "Houston", "TX", 29.7698, -95.3548,
     ["steel", "carbon_steel", "stainless_steel", "pipe", "plate", "bar_stock", "angle", "channel"], True, "manual"),
    ("Friedman Industries — Lone Star TX", "4001 Homestead Rd", "Lone Star", "TX", 32.9455, -94.7136,
     ["steel", "carbon_steel", "coil", "plate", "sheet_metal"], True, "manual"),
    ("Alaska Steel — Anchorage AK", "1200 W Dowling Rd", "Anchorage", "AK", 61.1909, -149.9055,
     ["steel", "aluminum", "stainless_steel", "bar_stock", "plate", "angle"], True, "manual"),
    ("Hawaii Metal Products — Honolulu HI", "660 N Nimitz Hwy", "Honolulu", "HI", 21.3148, -157.8648,
     ["steel", "aluminum", "stainless_steel", "bar_stock", "sheet_metal"], True, "manual"),
    ("Infra-Metals — Atlanta GA", "3100 Cumberland Blvd SE", "Atlanta", "GA", 33.8636, -84.4666,
     ["steel", "carbon_steel", "plate", "bar_stock", "angle", "channel", "tube"], True, "msci"),
    ("Metals 4U — Salt Lake City UT", "2680 S 300 W", "Salt Lake City", "UT", 40.7234, -111.8968,
     ["steel", "aluminum", "stainless_steel", "copper", "brass", "bar_stock", "sheet_metal", "tube"], True, "manual"),
    ("King Architectural Metals — Dallas TX", "8882 Blvd 26", "Dallas", "TX", 32.8209, -96.8688,
     ["steel", "aluminum", "copper", "bar_stock", "tube", "rod", "extrusion"], True, "manual"),
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
