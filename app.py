import os

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

app = Flask(__name__)

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "").strip()
OPENWEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"


def error_response(message, status_code, details=None):
    payload = {"ok": False, "error": message}
    if details is not None:
        payload["details"] = details
    return jsonify(payload), status_code


def clean_weather_payload(data):
    main = data.get("main", {})
    wind = data.get("wind", {})
    weather = data.get("weather", [{}])[0]

    return {
        "ok": True,
        "city": data.get("name"),
        "country": data.get("sys", {}).get("country"),
        "temperature_c": round(main.get("temp"), 1),
        "feels_like_c": round(main.get("feels_like"), 1),
        "humidity": main.get("humidity"),
        "pressure_hpa": main.get("pressure"),
        "description": weather.get("description", ""),
        "icon": weather.get("icon"),
        "wind_speed_kph": round((wind.get("speed", 0) * 3.6), 1),
        "wind_deg": wind.get("deg"),
        "source": "OpenWeather",
    }


def fetch_weather_from_openweather(params):
    if not OPENWEATHER_API_KEY:
        raise ValueError("OPENWEATHER_API_KEY is not configured")

    try:
        response = requests.get(
            OPENWEATHER_BASE_URL,
            params={"appid": OPENWEATHER_API_KEY, "units": "metric", **params},
            timeout=10,
        )
    except requests.Timeout:
        raise TimeoutError("OpenWeather request timed out")
    except requests.RequestException as exc:
        raise RuntimeError(f"OpenWeather request failed: {exc}")

    if response.status_code == 401:
        raise PermissionError("Invalid OpenWeather API key")

    if response.status_code == 404:
        raise FileNotFoundError("Location not found")

    if response.status_code >= 400:
        raise RuntimeError(f"OpenWeather API error: {response.status_code} {response.text}")

    try:
        return response.json()
    except ValueError as exc:
        raise ValueError("Invalid JSON response from OpenWeather") from exc


@app.get("/health")
def health():
    return jsonify({"ok": True, "status": "healthy"})


@app.get("/")
def index():
    return jsonify({
        "ok": True,
        "message": "Weather API ready",
        "endpoints": [
            "GET /health",
            "GET /weather?city=London",
            "GET /weather?lat=40.71&lon=-74.01",
            "POST /weather/multiple",
        ],
    })


@app.get("/weather")
def get_weather():
    city = request.args.get("city", "").strip()
    lat = request.args.get("lat", "", type=float)
    lon = request.args.get("lon", "", type=float)

    if city:
        params = {"q": city}
    elif lat is not None and lon is not None:
        params = {"lat": lat, "lon": lon}
    else:
        return error_response("Provide either city or both lat and lon", 400)

    try:
        data = fetch_weather_from_openweather(params)
        return jsonify(clean_weather_payload(data))
    except PermissionError as exc:
        return error_response(str(exc), 401)
    except FileNotFoundError as exc:
        return error_response(str(exc), 404)
    except TimeoutError as exc:
        return error_response(str(exc), 408)
    except ValueError as exc:
        return error_response(str(exc), 500)
    except Exception as exc:
        return error_response("Unable to fetch weather data", 502, {"detail": str(exc)})


@app.post("/weather/multiple")
def get_multiple_weather():
    payload = request.get_json(silent=True) or {}
    locations = payload.get("locations")

    if not isinstance(locations, list) or not locations:
        return error_response("'locations' must be a non-empty array", 400)

    results = []
    errors = []

    for index, item in enumerate(locations):
        try:
            if isinstance(item, str):
                city = item.strip()
                if not city:
                    raise ValueError("Empty city name")
                params = {"q": city}
            elif isinstance(item, dict):
                city = (item.get("city") or "").strip()
                lat = item.get("lat")
                lon = item.get("lon")

                if city:
                    params = {"q": city}
                elif lat is not None and lon is not None:
                    params = {"lat": float(lat), "lon": float(lon)}
                else:
                    raise ValueError("Each location must contain city or lat/lon")
            else:
                raise ValueError("Each location must be a string or object")

            data = fetch_weather_from_openweather(params)
            results.append(clean_weather_payload(data))
        except (PermissionError, FileNotFoundError, TimeoutError, ValueError, TypeError) as exc:
            errors.append({"index": index, "error": str(exc)})

    if not results:
        return error_response("No weather results could be retrieved", 400, {"details": errors})

    return jsonify({"ok": True, "count": len(results), "results": results, "errors": errors or None})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
