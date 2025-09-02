from flask import Flask, request, jsonify
import os, csv, logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# === Config ===
CSV_PATH = os.getenv("VILLAGE_CSV", "villages.csv")
# Optional shared secret to secure webhook (set same header in CX)
SECRET_HEADER = os.getenv("DF_SECRET_HEADER", "X-DF-Secret")
SECRET_TOKEN = os.getenv("DF_SECRET_TOKEN", "")  # leave blank to disable check

FIELD_MAP = {
    "name": "Village Name",
    "state": "State",
    "district": "District",
    "about": "About the Village",
    "attractions": "Places to Visit / Tourist Attractions",
    "activities": "Activities",
    "booking": "Booking Information",
    "handicrafts": "Local Handicrafts / Products",
    "stays": "Places to Stay",
    "food": "Famous Foods / Restaurants",
    "transport": "Transport and Accessibility",
    "unique": "Unique Features",
    "official": "Official Website or Contact Info",
}

def normalize(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "").replace("_", "")

def load_catalog(path: str):
    data = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = normalize(row.get(FIELD_MAP["name"]))
            if key:
                data[key] = row
    app.logger.info(f"Loaded {len(data)} villages from {path}")
    return data

CAT = load_catalog(CSV_PATH)

def pick(row, field_key, default="Information not available."):
    col = FIELD_MAP[field_key]
    val = (row.get(col) or "").strip()
    return val if val else default

def bullets(text):
    items = [x.strip() for x in (text or "").split(";") if x.strip()]
    return "\n".join([f"• {x}" for x in items]) if items else text

def msg(text):
    return {"text": {"text": [text]}}

def filter_activity_line(activities_text, activity_query):
    if not activity_query:
        return activities_text
    lines = [x.strip() for x in (activities_text or "").split(";") if x.strip()]
    q = (activity_query or "").strip().lower()
    hits = [ln for ln in lines if q in ln.lower()]
    return "; ".join(hits) if hits else "Requested activity not found for this place."

def verify_secret(req):
    if not SECRET_TOKEN:
        return True
    return req.headers.get(SECRET_HEADER, "") == SECRET_TOKEN

@app.post("/fulfillment")
def fulfillment():
    if not verify_secret(request):
        return jsonify({"fulfillmentResponse": {"messages": [msg("Unauthorized")]}}), 401

    body = request.get_json(silent=True) or {}
    tag = body.get("fulfillmentInfo", {}).get("tag", "")
    params = body.get("sessionInfo", {}).get("parameters", {})

    # Entities captured in CX
    place_raw = params.get("place") or params.get("cx_entities_place") or ""
    activity_raw = params.get("activity") or params.get("cx_entities_activity") or ""
    state_raw = params.get("state") or params.get("cx_entities_state") or ""
    district_raw = params.get("district") or params.get("cx_entities_district") or ""

    # === getPlaceDetails / getAttractions / getActivities / getFood / getTransport / getStays / getHandicrafts / getOfficial ===
    def by_place_required():
        place_key = normalize(place_raw)
        if not place_key or place_key not in CAT:
            return None, jsonify({"fulfillmentResponse": {"messages": [msg("I couldn't find that place. Try another village or spelling.")]}})
        return CAT[place_key], None

    if tag == "getPlaceDetails":
        row, err = by_place_required()
        if err: return err
        name     = pick(row, "name", place_raw)
        state    = pick(row, "state", "")
        district = pick(row, "district", "")
        about    = pick(row, "about")
        unique   = pick(row, "unique", "")
        header = f"{name} ({district}, {state})".strip(", ")
        text = f"{header}\n\n{about}"
        if unique and unique != "Information not available.":
            text += f"\n\nUnique:\n{bullets(unique)}"
        return jsonify({"fulfillmentResponse": {"messages": [msg(text)]}})

    if tag == "getAttractions":
        row, err = by_place_required()
        if err: return err
        name = pick(row, "name", place_raw)
        attractions = bullets(pick(row, "attractions"))
        return jsonify({"fulfillmentResponse": {"messages": [msg(f"Top attractions in {name}:\n{attractions}") ]}})

    if tag == "getActivities":
        row, err = by_place_required()
        if err: return err
        name = pick(row, "name", place_raw)
        activities = pick(row, "activities")
        filtered = filter_activity_line(activities, activity_raw)
        return jsonify({"fulfillmentResponse": {"messages": [msg(f"Activities in {name}:\n{bullets(filtered)}") ]}})

    if tag == "getFood":
        row, err = by_place_required()
        if err: return err
        name = pick(row, "name", place_raw)
        food = bullets(pick(row, "food"))
        return jsonify({"fulfillmentResponse": {"messages": [msg(f"Food in {name}:\n{food}") ]}})

    if tag == "getTransport":
        row, err = by_place_required()
        if err: return err
        name = pick(row, "name", place_raw)
        tx = bullets(pick(row, "transport"))
        return jsonify({"fulfillmentResponse": {"messages": [msg(f"How to reach {name}:\n{tx}") ]}})

    if tag == "getStays":
        row, err = by_place_required()
        if err: return err
        name = pick(row, "name", place_raw)
        stays = bullets(pick(row, "stays"))
        return jsonify({"fulfillmentResponse": {"messages": [msg(f"Places to stay in/near {name}:\n{stays}") ]}})

    if tag == "getHandicrafts":
        row, err = by_place_required()
        if err: return err
        name = pick(row, "name", place_raw)
        craft = bullets(pick(row, "handicrafts"))
        return jsonify({"fulfillmentResponse": {"messages": [msg(f"Local crafts in {name}:\n{craft}") ]}})

    if tag == "getOfficial":
        row, err = by_place_required()
        if err: return err
        name = pick(row, "name", place_raw)
        url = pick(row, "official")
        return jsonify({"fulfillmentResponse": {"messages": [msg(f"Official info for {name}:\n{url}") ]}})

    # === Recommendations by state/district ===
    if tag == "getRecommendations":
        def list_places_by(col_key, val):
            col = FIELD_MAP[col_key]
            target = normalize(val)
            return [r.get(FIELD_MAP["name"]) for r in CAT.values() if normalize(r.get(col)) == target]

        if district_raw:
            places = list_places_by("district", district_raw)
            scope = district_raw
        elif state_raw:
            places = list_places_by("state", state_raw)
            scope = state_raw
        else:
            return jsonify({"fulfillmentResponse": {"messages": [msg("Tell me a state or district to recommend places.")]}})

        if not places:
            return jsonify({"fulfillmentResponse": {"messages": [msg(f"No places found for {scope}.")]}})
        top = places[:10]
        text = f"Recommended places in {scope}:\n" + "\n".join([f"• {p}" for p in top])
        return jsonify({"fulfillmentResponse": {"messages": [msg(text)]}})

    return jsonify({"fulfillmentResponse": {"messages": [msg("Unhandled webhook tag.")]}})
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
