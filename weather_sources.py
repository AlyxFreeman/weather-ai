"""
多源天气数据采集模块

免费免Key数据源（开箱即用，多源融合）：
1. Open-Meteo BestMatch — Open-Meteo 默认最佳匹配模型
2. Open-Meteo GFS      — NOAA 全球预报系统模型
3. Open-Meteo ECMWF    — 欧洲中期天气预报中心模型
4. 7Timer!             — 基于 GFS/CMC 的免费气象服务
5. wttr.in             — 基于 WorldWeatherOnline 的免费服务

需Key数据源（在 config.py 中配置后自动激活）：
6. OpenWeatherMap
7. WeatherAPI
8. 和风天气 QWeather
9. Windy

所有数据源采集后统一输出标准格式，便于后续 AI 融合。
"""

import requests
import datetime
import config


# ============================================================
#  WMO 天气代码映射（Open-Meteo 使用）
# ============================================================
WMO_CODE_MAP = {
    0: ("晴", "Clear sky", "☀️"),
    1: ("大部晴朗", "Mainly clear", "🌤️"),
    2: ("局部多云", "Partly cloudy", "⛅"),
    3: ("阴", "Overcast", "☁️"),
    45: ("有雾", "Foggy", "🌫️"),
    48: ("雾凇", "Depositing rime fog", "🌫️"),
    51: ("小毛毛雨", "Light drizzle", "🌦️"),
    53: ("毛毛雨", "Moderate drizzle", "🌦️"),
    55: ("大毛毛雨", "Dense drizzle", "🌧️"),
    56: ("冻毛毛雨", "Light freezing drizzle", "🌧️"),
    57: ("冻雨", "Dense freezing drizzle", "🌧️"),
    61: ("小雨", "Slight rain", "🌦️"),
    63: ("中雨", "Moderate rain", "🌧️"),
    65: ("大雨", "Heavy rain", "🌧️"),
    66: ("冻雨", "Light freezing rain", "🌧️"),
    67: ("大冻雨", "Heavy freezing rain", "🌧️"),
    71: ("小雪", "Slight snow", "🌨️"),
    73: ("中雪", "Moderate snow", "❄️"),
    75: ("大雪", "Heavy snow", "❄️"),
    77: ("米雪", "Snow grains", "🌨️"),
    80: ("小阵雨", "Slight rain showers", "🌦️"),
    81: ("阵雨", "Moderate rain showers", "🌧️"),
    82: ("大阵雨", "Violent rain showers", "⛈️"),
    85: ("阵雪", "Slight snow showers", "🌨️"),
    86: ("大阵雪", "Heavy snow showers", "❄️"),
    95: ("雷暴", "Thunderstorm", "⛈️"),
    96: ("雷暴伴小冰雹", "Thunderstorm with slight hail", "⛈️"),
    99: ("雷暴伴大冰雹", "Thunderstorm with heavy hail", "⛈️"),
}


def _wmo_to_text(code):
    """WMO 代码转中文天气描述 + emoji"""
    info = WMO_CODE_MAP.get(code, ("未知", "Unknown", "❓"))
    return info[0], info[2]


def _empty_result(source_name, error_msg):
    """生成空结果（某数据源出错时用）"""
    return {
        "source": source_name,
        "status": "error",
        "error": error_msg,
        "current": None,
        "forecast": [],
    }


def _ok_result(source_name, current, forecast, hourly=None):
    """生成正常结果"""
    return {
        "source": source_name,
        "status": "ok",
        "current": current,
        "forecast": forecast,
        "hourly": hourly,
    }


# ============================================================
#  城市地理编码（Open-Meteo 免费服务）
# ============================================================
def geocode(city_name):
    """
    城市名 → 经纬度
    使用 Open-Meteo 免费地理编码 API，支持中英文城市名。
    返回: [{"name": "北京", "country": "China", "lat": 39.9, "lon": 116.4, "admin": "Beijing"}, ...]
    """
    try:
        resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city_name, "count": 5, "language": "zh", "format": "json"},
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("results", []):
            results.append({
                "name": item.get("name", ""),
                "country": item.get("country", ""),
                "admin": item.get("admin1", ""),
                "lat": item.get("latitude"),
                "lon": item.get("longitude"),
                "timezone": item.get("timezone", ""),
            })
        return results
    except Exception as e:
        print(f"[Geocode] 城市搜索失败: {e}")
        return []


# ============================================================
#  数据源 1-3: Open-Meteo（免费，无需 Key，支持多模型）
# ============================================================
def _fetch_open_meteo_model(lat, lon, model=None, source_name="Open-Meteo"):
    """
    Open-Meteo 通用采集函数，支持指定不同气象模型。
    model=None 表示使用默认的 Best Match（自动选择最优模型）。
    model="gfs_global" 表示使用 NOAA GFS 模型。
    model="ecmwf_ifs025" 表示使用 ECMWF 模型。
    """
    try:
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": [
                "temperature_2m", "relative_humidity_2m", "apparent_temperature",
                "weather_code", "wind_speed_10m", "wind_direction_10m",
                "surface_pressure", "is_day",
            ],
            "daily": [
                "weather_code", "temperature_2m_max", "temperature_2m_min",
                "precipitation_sum", "wind_speed_10m_max", "precipitation_probability_max",
            ],
            "hourly": [
                "temperature_2m", "relative_humidity_2m", "apparent_temperature",
                "weather_code", "wind_speed_10m", "wind_direction_10m",
                "precipitation", "precipitation_probability",
            ],
            "timezone": "auto",
            "forecast_days": 7,
        }
        if model:
            params["models"] = model

        # requests 对 list 参数需要特殊处理
        params_str = {}
        for k, v in params.items():
            if isinstance(v, list):
                params_str[k] = ",".join(v)
            else:
                params_str[k] = v

        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=params_str,
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        cur = data.get("current", {})
        code = cur.get("weather_code", 0)
        weather_text, weather_emoji = _wmo_to_text(code)
        wind_dir = cur.get("wind_direction_10m", 0)

        current = {
            "temperature": round(cur.get("temperature_2m", 0), 1),
            "feels_like": round(cur.get("apparent_temperature", 0), 1),
            "humidity": cur.get("relative_humidity_2m", 0),
            "wind_speed": round(cur.get("wind_speed_10m", 0), 1),
            "wind_direction": _deg_to_dir(wind_dir),
            "wind_direction_deg": wind_dir,
            "pressure": round(cur.get("surface_pressure", 0), 0),
            "weather_code": code,
            "weather_text": weather_text,
            "weather_emoji": weather_emoji,
            "is_day": cur.get("is_day", 1) == 1,
        }

        daily = data.get("daily", {})
        forecast = []
        for i in range(len(daily.get("time", []))):
            d_code = daily["weather_code"][i]
            d_text, d_emoji = _wmo_to_text(d_code)
            forecast.append({
                "date": daily["time"][i],
                "temp_max": round(daily["temperature_2m_max"][i], 1),
                "temp_min": round(daily["temperature_2m_min"][i], 1),
                "weather_text": d_text,
                "weather_emoji": d_emoji,
                "precipitation": round(daily["precipitation_sum"][i], 1),
                "precipitation_prob": daily["precipitation_probability_max"][i] if "precipitation_probability_max" in daily else 0,
                "wind_speed": round(daily["wind_speed_10m_max"][i], 1),
            })

        # 解析逐小时数据（用于路线天气按到达时刻取风速）
        hourly_data = data.get("hourly", {})
        hourly_list = []
        if hourly_data and "time" in hourly_data:
            for i in range(len(hourly_data["time"])):
                h_code = hourly_data["weather_code"][i] if "weather_code" in hourly_data else 0
                h_text, h_emoji = _wmo_to_text(h_code)
                hourly_list.append({
                    "time": hourly_data["time"][i],
                    "temperature": round(hourly_data["temperature_2m"][i], 1) if "temperature_2m" in hourly_data else None,
                    "feels_like": round(hourly_data["apparent_temperature"][i], 1) if "apparent_temperature" in hourly_data else None,
                    "humidity": hourly_data["relative_humidity_2m"][i] if "relative_humidity_2m" in hourly_data else None,
                    "wind_speed": round(hourly_data["wind_speed_10m"][i], 1) if "wind_speed_10m" in hourly_data else None,
                    "wind_direction_deg": hourly_data["wind_direction_10m"][i] if "wind_direction_10m" in hourly_data else 0,
                    "weather_text": h_text,
                    "weather_emoji": h_emoji,
                    "precipitation": round(hourly_data["precipitation"][i], 2) if "precipitation" in hourly_data else 0,
                    "precipitation_prob": hourly_data["precipitation_probability"][i] if "precipitation_probability" in hourly_data else 0,
                })

        return _ok_result(source_name, current, forecast, hourly=hourly_list if hourly_list else None)

    except Exception as e:
        return _empty_result(source_name, str(e))


def fetch_open_meteo(lat, lon):
    """Open-Meteo Best Match（自动选择最优模型组合）"""
    return _fetch_open_meteo_model(lat, lon, model=None, source_name="Open-Meteo")


def fetch_open_meteo_gfs(lat, lon):
    """Open-Meteo GFS（NOAA 全球预报系统模型）"""
    return _fetch_open_meteo_model(lat, lon, model="gfs_global", source_name="Open-Meteo GFS")


def fetch_open_meteo_ecmwf(lat, lon):
    """Open-Meteo ECMWF（欧洲中期天气预报中心模型）"""
    return _fetch_open_meteo_model(lat, lon, model="ecmwf_ifs025", source_name="Open-Meteo ECMWF")


# ============================================================
#  数据源 4: 7Timer!（免费，无需 Key）
# ============================================================
# 7Timer 天气代码映射
SEVENTIMER_WEATHER_MAP = {
    "clearday": ("晴", "☀️"),
    "clearnight": ("晴", "🌙"),
    "pclearnight": ("晴间多云", "🌙"),
    "pcloudyday": ("晴间多云", "🌤️"),
    "mcloudydaynight": ("多云", "⛅"),
    "cloudyday": ("阴", "☁️"),
    "cloudynight": ("阴", "☁️"),
    "humidaynight": ("潮湿", "💧"),
    "lushdaynight": ("潮湿", "💧"),
    "lraindaynight": ("小雨", "🌦️"),
    "lrainnight": ("小雨", "🌧️"),
    "raindaynight": ("中雨", "🌧️"),
    "rainnight": ("中雨", "🌧️"),
    "tsdaynight": ("雷暴", "⛈️"),
    "tsnight": ("雷暴", "⛈️"),
    "snowdaynight": ("雪", "🌨️"),
    "snownight": ("雪", "❄️"),
    "rainsnowdaynight": ("雨夹雪", "🌨️"),
    "rainsnownight": ("雨夹雪", "🌨️"),
    "fogdaynight": ("雾", "🌫️"),
    "fognight": ("雾", "🌫️"),
    "windydaynight": ("大风", "💨"),
    "windynight": ("大风", "💨"),
}

# 7Timer 风力等级映射（Beaufort scale → m/s 近似值）
SEVENTIMER_WIND_MAP = {
    1: 0.5, 2: 2.5, 3: 4.5, 4: 7.0, 5: 9.5, 6: 12.5, 7: 15.5, 8: 19.0, 9: 23.0
}


def fetch_7timer(lat, lon):
    """7Timer! 免费气象服务，基于 GFS/CMC 模型"""
    source_name = "7Timer!"
    try:
        # 使用 civil 产品（每日预报，7天）
        resp = requests.get(
            "http://www.7timer.info/bin/api.pl",
            params={
                "lon": round(lon, 2),
                "lat": round(lat, 2),
                "product": "civil",
                "output": "json",
            },
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        dataseries = data.get("dataseries", [])
        if not dataseries:
            return _empty_result(source_name, "无数据返回")

        forecast = []
        today = datetime.date.today()

        for i, item in enumerate(dataseries[:7]):
            date = (today + datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            weather_code = item.get("weather", "clearday")
            weather_text, weather_emoji = SEVENTIMER_WEATHER_MAP.get(
                weather_code, ("未知", "❓")
            )
            wind_level = item.get("wind10m_max", 1)
            if isinstance(wind_level, str):
                wind_level = int(wind_level)
            wind_speed = SEVENTIMER_WIND_MAP.get(wind_level, 0)

            precip_val = item.get("prec_amount", 0)
            if isinstance(precip_val, str):
                try:
                    precip_val = float(precip_val)
                except ValueError:
                    precip_val = 0

            forecast.append({
                "date": date,
                "temp_max": float(item.get("temp2m_max", 0)),
                "temp_min": float(item.get("temp2m_min", 0)),
                "weather_text": weather_text,
                "weather_emoji": weather_emoji,
                "precipitation": precip_val,
                "precipitation_prob": 0,
                "wind_speed": wind_speed,
            })

        # 7Timer 没有单独的"当前"天气，用今天的预报数据构造
        today_data = dataseries[0]
        today_weather = today_data.get("weather", "clearday")
        today_text, today_emoji = SEVENTIMER_WEATHER_MAP.get(today_weather, ("未知", "❓"))
        today_temp = (float(today_data.get("temp2m_max", 20)) + float(today_data.get("temp2m_min", 10))) / 2
        today_humidity = int(str(today_data.get("rh2m", 50)).replace("%", ""))
        today_wind_level = today_data.get("wind10m_max", 1)
        if isinstance(today_wind_level, str):
            today_wind_level = int(today_wind_level)
        today_wind_speed = SEVENTIMER_WIND_MAP.get(today_wind_level, 0)

        current = {
            "temperature": round(today_temp, 1),
            "feels_like": round(today_temp, 1),
            "humidity": today_humidity,
            "wind_speed": today_wind_speed,
            "wind_direction": "未知",
            "wind_direction_deg": 0,
            "pressure": 0,
            "weather_code": 0,
            "weather_text": today_text,
            "weather_emoji": today_emoji,
            "is_day": True,
        }

        return _ok_result(source_name, current, forecast)

    except Exception as e:
        return _empty_result(source_name, str(e))


# ============================================================
#  数据源 5: wttr.in（免费，无需 Key）
# ============================================================
# wttr.in weatherCode 映射
WTTR_CODE_MAP = {
    "113": ("晴", "☀️"),
    "116": ("局部多云", "⛅"),
    "119": ("多云", "☁️"),
    "122": ("阴", "☁️"),
    "143": ("有雾", "🌫️"),
    "176": ("小雨", "🌦️"),
    "179": ("雨夹雪", "🌨️"),
    "182": ("雨夹雪", "🌨️"),
    "185": ("雨夹雪", "🌨️"),
    "200": ("雷暴", "⛈️"),
    "227": ("小雪", "🌨️"),
    "230": ("大雪", "❄️"),
    "248": ("有雾", "🌫️"),
    "260": ("有雾", "🌫️"),
    "263": ("小毛毛雨", "🌦️"),
    "266": ("毛毛雨", "🌦️"),
    "281": ("冻雨", "🌧️"),
    "284": ("冻雨", "🌧️"),
    "293": ("小雨", "🌦️"),
    "296": ("小雨", "🌦️"),
    "299": ("中雨", "🌧️"),
    "302": ("中雨", "🌧️"),
    "305": ("大雨", "🌧️"),
    "308": ("大雨", "🌧️"),
    "311": ("暴雨", "🌧️"),
    "314": ("暴雨", "🌧️"),
    "317": ("大暴雨", "🌧️"),
    "320": ("小雪", "🌨️"),
    "323": ("小雪", "🌨️"),
    "326": ("中雪", "❄️"),
    "329": ("大雪", "❄️"),
    "332": ("大雪", "❄️"),
    "335": ("暴雪", "❄️"),
    "338": ("暴雪", "❄️"),
    "350": ("冻雨", "🌧️"),
    "353": ("小阵雨", "🌦️"),
    "356": ("阵雨", "🌧️"),
    "359": ("大阵雨", "⛈️"),
    "362": ("阵雪", "🌨️"),
    "365": ("阵雪", "❄️"),
    "368": ("小雪", "🌨️"),
    "371": ("中雪", "❄️"),
    "374": ("冻雨", "🌧️"),
    "377": ("冻雨", "🌧️"),
    "386": ("雷阵雨", "⛈️"),
    "389": ("雷暴", "⛈️"),
    "392": ("雷阵雪", "⛈️"),
    "395": ("雷暴伴雪", "⛈️"),
}


def _wttr_code_to_text(code):
    """wttr.in weatherCode → 中文描述 + emoji"""
    info = WTTR_CODE_MAP.get(str(code), ("未知", "❓"))
    return info[0], info[1]


def fetch_wttr(lat, lon):
    """wttr.in 免费天气服务，基于 WorldWeatherOnline 数据"""
    source_name = "wttr.in"
    try:
        resp = requests.get(
            f"https://wttr.in/{lat},{lon}",
            params={"format": "j1"},
            timeout=config.REQUEST_TIMEOUT,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

        # 当前天气
        cur_arr = data.get("current_condition", [])
        if not cur_arr:
            return _empty_result(source_name, "无当前天气数据")
        cur = cur_arr[0]

        weather_code = cur.get("weatherCode", "113")
        weather_text, weather_emoji = _wttr_code_to_text(weather_code)

        # wttr.in 风向用16方位英文缩写
        wind_dir_en = cur.get("winddir16Point", "N")
        wind_dir_map = {
            "N": "北", "NNE": "东北偏北", "NE": "东北", "ENE": "东北偏东",
            "E": "东", "ESE": "东南偏东", "SE": "东南", "SSE": "东南偏南",
            "S": "南", "SSW": "西南偏南", "SW": "西南", "WSW": "西南偏西",
            "W": "西", "WNW": "西北偏西", "NW": "西北", "NNW": "西北偏北",
        }

        current = {
            "temperature": float(cur.get("temp_C", 0)),
            "feels_like": float(cur.get("FeelsLikeC", 0)),
            "humidity": int(cur.get("humidity", 0)),
            "wind_speed": round(int(cur.get("windspeedKmph", 0)) / 3.6, 1),
            "wind_direction": wind_dir_map.get(wind_dir_en, "未知"),
            "wind_direction_deg": int(cur.get("winddirDegree", 0)),
            "pressure": int(cur.get("pressure", 0)),
            "weather_code": int(weather_code),
            "weather_text": weather_text,
            "weather_emoji": weather_emoji,
            "is_day": cur.get("uvIndex", "1") != "0",
        }

        # 预报
        forecast = []
        for day in data.get("weather", [])[:7]:
            date = day.get("date", "")
            # wttr.in 日期格式: YYYY-MM-DD
            # 取白天时段（12:00）的天气状况
            hourly = day.get("hourly", [])
            mid_hour = hourly[4] if len(hourly) > 4 else (hourly[0] if hourly else {})

            mid_code = mid_hour.get("weatherCode", "113")
            mid_text, mid_emoji = _wttr_code_to_text(mid_code)

            # 降水概率
            precip_prob = int(mid_hour.get("chanceofrain", 0))

            forecast.append({
                "date": date,
                "temp_max": float(day.get("maxtempC", 0)),
                "temp_min": float(day.get("mintempC", 0)),
                "weather_text": mid_text,
                "weather_emoji": mid_emoji,
                "precipitation": float(mid_hour.get("precipMM", 0)),
                "precipitation_prob": precip_prob,
                "wind_speed": round(int(mid_hour.get("windspeedKmph", 0)) / 3.6, 1),
            })

        return _ok_result(source_name, current, forecast)

    except Exception as e:
        return _empty_result(source_name, str(e))


# ============================================================
#  数据源 6: OpenWeatherMap
# ============================================================
def fetch_openweathermap(lat, lon):
    source_name = "OpenWeatherMap"
    if not config.OPENWEATHER_API_KEY:
        return _empty_result(source_name, "未配置 API Key")

    try:
        # 当前天气
        resp = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"lat": lat, "lon": lon, "appid": config.OPENWEATHER_API_KEY, "units": "metric", "lang": "zh_cn"},
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        current = {
            "temperature": round(data["main"]["temp"], 1),
            "feels_like": round(data["main"]["feels_like"], 1),
            "humidity": data["main"]["humidity"],
            "wind_speed": round(data["wind"]["speed"], 1),
            "wind_direction": _deg_to_dir(data["wind"].get("deg", 0)),
            "wind_direction_deg": data["wind"].get("deg", 0),
            "pressure": data["main"].get("pressure", 0),
            "weather_code": data["weather"][0]["id"],
            "weather_text": data["weather"][0]["description"],
            "weather_emoji": _owm_emoji(data["weather"][0]["id"]),
            "is_day": "d" in data.get("sys", {}).get("pod", "d"),
        }

        # 预报
        resp2 = requests.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={"lat": lat, "lon": lon, "appid": config.OPENWEATHER_API_KEY, "units": "metric", "lang": "zh_cn"},
            timeout=config.REQUEST_TIMEOUT,
        )
        resp2.raise_for_status()
        forecast_data = resp2.json()

        # 按天聚合
        daily_map = {}
        for item in forecast_data["list"]:
            date = item["dt_txt"][:10]
            if date not in daily_map:
                daily_map[date] = {
                    "temps": [], "codes": [], "precip": 0, "wind": []
                }
            daily_map[date]["temps"].append(item["main"]["temp"])
            daily_map[date]["codes"].append(item["weather"][0]["id"])
            daily_map[date]["precip"] += item.get("rain", {}).get("3h", 0)
            daily_map[date]["wind"].append(item["wind"]["speed"])

        forecast = []
        for date in sorted(daily_map.keys())[:7]:
            d = daily_map[date]
            # 取白天时段的天气代码（12:00）
            mid_code = d["codes"][4] if len(d["codes"]) > 4 else d["codes"][0]
            forecast.append({
                "date": date,
                "temp_max": round(max(d["temps"]), 1),
                "temp_min": round(min(d["temps"]), 1),
                "weather_text": _owm_text(mid_code),
                "weather_emoji": _owm_emoji(mid_code),
                "precipitation": round(d["precip"], 1),
                "precipitation_prob": 0,
                "wind_speed": round(max(d["wind"]), 1),
            })

        return _ok_result(source_name, current, forecast)

    except Exception as e:
        return _empty_result(source_name, str(e))


def _owm_emoji(code):
    if code < 300: return "⛈️"
    if code < 400: return "🌦️"
    if code < 600: return "🌧️"
    if code < 700: return "❄️"
    if code < 800: return "🌫️"
    if code == 800: return "☀️"
    if code < 900: return "☁️"
    return "🌤️"


def _owm_text(code):
    if code < 300: return "雷暴"
    if code < 400: return "小雨"
    if code < 600: return "雨"
    if code < 700: return "雪"
    if code < 800: return "雾"
    if code == 800: return "晴"
    if code < 900: return "阴"
    return "多云"


# ============================================================
#  数据源 7: WeatherAPI
# ============================================================
def fetch_weatherapi(lat, lon):
    source_name = "WeatherAPI"
    if not config.WEATHERAPI_KEY:
        return _empty_result(source_name, "未配置 API Key")

    try:
        resp = requests.get(
            "https://api.weatherapi.com/v1/forecast.json",
            params={
                "key": config.WEATHERAPI_KEY,
                "q": f"{lat},{lon}",
                "days": 7,
                "aqi": "no",
                "alerts": "no",
                "lang": "zh",
            },
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        cur = data["current"]
        current = {
            "temperature": round(cur["temp_c"], 1),
            "feels_like": round(cur["feelslike_c"], 1),
            "humidity": cur["humidity"],
            "wind_speed": round(cur["wind_kph"] / 3.6, 1),
            "wind_direction": cur["wind_dir"],
            "wind_direction_deg": cur["wind_degree"],
            "pressure": cur["pressure_mb"],
            "weather_code": cur["condition"]["code"],
            "weather_text": cur["condition"]["text"],
            "weather_emoji": _weatherapi_emoji(cur["condition"]["code"]),
            "is_day": cur["is_day"] == 1,
        }

        forecast = []
        for day in data["forecast"]["forecastday"]:
            cond = day["day"]["condition"]
            forecast.append({
                "date": day["date"],
                "temp_max": round(day["day"]["maxtemp_c"], 1),
                "temp_min": round(day["day"]["mintemp_c"], 1),
                "weather_text": cond["text"],
                "weather_emoji": _weatherapi_emoji(cond["code"]),
                "precipitation": round(day["day"]["totalprecip_mm"], 1),
                "precipitation_prob": day["day"]["daily_chance_of_rain"],
                "wind_speed": round(day["day"]["maxwind_kph"] / 3.6, 1),
            })

        return _ok_result(source_name, current, forecast)

    except Exception as e:
        return _empty_result(source_name, str(e))


def _weatherapi_emoji(code):
    if code == 1000: return "☀️"
    if code == 1003: return "⛅"
    if code in (1006, 1009): return "☁️"
    if code in (1030, 1135, 1147): return "🌫️"
    if code in (1063, 1180, 1183, 1186, 1189, 1192, 1195, 1240, 1243, 1246): return "🌧️"
    if code in (1066, 1069, 1072, 1168, 1171, 1198, 1201, 1204, 1207, 1210, 1213, 1216, 1219, 1222, 1225, 1237, 1249, 1252, 1255, 1258, 1261, 1264): return "❄️"
    if code in (1087, 1273, 1276, 1279, 1282): return "⛈️"
    return "🌤️"


# ============================================================
#  数据源 8: 和风天气 QWeather
# ============================================================
def fetch_qweather(lat, lon):
    source_name = "和风天气"
    if not config.QWEATHER_API_KEY:
        return _empty_result(source_name, "未配置 API Key")

    try:
        location = f"{lon:.2f},{lat:.2f}"  # 和风天气格式: 经度,纬度

        # 当前天气
        resp = requests.get(
            "https://devapi.qweather.com/v7/weather/now",
            params={"location": location, "key": config.QWEATHER_API_KEY, "lang": "zh"},
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "200":
            return _empty_result(source_name, f"API返回错误码: {data.get('code')}")

        cur = data["now"]
        current = {
            "temperature": float(cur["temp"]),
            "feels_like": float(cur["feels"]),
            "humidity": int(cur["humidity"]),
            "wind_speed": round(int(cur["windSpeed"]) / 3.6, 1),  # km/h → m/s
            "wind_direction": cur["windDir"],
            "wind_direction_deg": int(cur["wind360"]),
            "pressure": int(cur["pressure"]),
            "weather_code": int(cur["icon"]),
            "weather_text": cur["text"],
            "weather_emoji": _qweather_emoji(int(cur["icon"])),
            "is_day": cur.get("isDay", "1") == "1",
        }

        # 7天预报
        resp2 = requests.get(
            "https://devapi.qweather.com/v7/weather/7d",
            params={"location": location, "key": config.QWEATHER_API_KEY, "lang": "zh"},
            timeout=config.REQUEST_TIMEOUT,
        )
        resp2.raise_for_status()
        forecast_data = resp2.json()
        if forecast_data.get("code") != "200":
            return _ok_result(source_name, current, [])

        forecast = []
        for day in forecast_data.get("daily", []):
            forecast.append({
                "date": day["fxDate"],
                "temp_max": float(day["tempMax"]),
                "temp_min": float(day["tempMin"]),
                "weather_text": day["textDay"],
                "weather_emoji": _qweather_emoji(int(day["iconDay"])),
                "precipitation": float(day.get("precip", 0)),
                "precipitation_prob": int(day.get("pop", 0)),
                "wind_speed": round(int(day.get("windSpeedDay", "0")) / 3.6, 1),
            })

        return _ok_result(source_name, current, forecast)

    except Exception as e:
        return _empty_result(source_name, str(e))


def _qweather_emoji(icon):
    if icon in (100, 150): return "☀️"
    if icon in (101, 151): return "🌤️"
    if icon in (102, 152): return "⛅"
    if icon in (103, 153): return "☁️"
    if icon in (104, 154): return "☁️"
    if icon in (300, 301): return "🌫️"
    if icon in (302, 303): return "⛈️"
    if icon in (304, 305, 306, 307, 308, 309, 310, 311, 312, 313, 314, 315, 316, 317, 318, 399): return "🌧️"
    if icon in (400, 401, 402, 403, 404, 405, 406, 407, 408, 409, 410, 499): return "❄️"
    if icon in (500, 501, 502, 503, 504, 507, 508, 509, 510, 511, 512, 513, 514, 515): return "🌫️"
    return "🌤️"


# ============================================================
#  数据源 9: Windy
# ============================================================
def fetch_windy(lat, lon):
    source_name = "Windy"
    if not config.WINDY_API_KEY:
        return _empty_result(source_name, "未配置 API Key")

    try:
        resp = requests.get(
            "https://api.windy.com/api/point-forecast/v2",
            json={
                "lat": lat,
                "lon": lon,
                "model": "gfs",
                "parameters": ["temp", "rh", "wind_u", "wind_v", "precip"],
                "key": config.WINDY_API_KEY,
            },
            headers={"Content-Type": "application/json"},
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        temps = data.get("temp", [])
        rhs = data.get("rh", [])
        wind_u = data.get("wind_u", [])
        wind_v = data.get("wind_v", [])

        if not temps:
            return _empty_result(source_name, "无数据返回")

        temp_c = temps[0] - 273.15  # K → C
        humidity = rhs[0] if rhs else 0
        u = wind_u[0] if wind_u else 0
        v = wind_v[0] if wind_v else 0
        wind_speed = round((u**2 + v**2) ** 0.5, 1)
        wind_deg = int((270 - (180 / 3.14159) * 1.5707963 * (1 if v == 0 else 0)) % 360)

        current = {
            "temperature": round(temp_c, 1),
            "feels_like": round(temp_c, 1),
            "humidity": int(humidity),
            "wind_speed": wind_speed,
            "wind_direction": _deg_to_dir(wind_deg),
            "wind_direction_deg": wind_deg,
            "pressure": 0,
            "weather_code": 0,
            "weather_text": "数据获取成功",
            "weather_emoji": "🌍",
            "is_day": True,
        }

        forecast = []
        ts = data.get("ts", [])
        if ts:
            daily_map = {}
            for i, t in enumerate(ts):
                date = _timestamp_to_date(t)
                if date not in daily_map:
                    daily_map[date] = {"temps": [], "precip": 0}
                if i < len(temps):
                    daily_map[date]["temps"].append(temps[i] - 273.15)

            for date in sorted(daily_map.keys())[:7]:
                d = daily_map[date]
                if d["temps"]:
                    forecast.append({
                        "date": date,
                        "temp_max": round(max(d["temps"]), 1),
                        "temp_min": round(min(d["temps"]), 1),
                        "weather_text": "数据可用",
                        "weather_emoji": "🌍",
                        "precipitation": 0,
                        "precipitation_prob": 0,
                        "wind_speed": 0,
                    })

        return _ok_result(source_name, current, forecast)

    except Exception as e:
        return _empty_result(source_name, str(e))


def _timestamp_to_date(ts_ms):
    """毫秒时间戳 → YYYY-MM-DD"""
    return datetime.datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")


# ============================================================
#  工具函数
# ============================================================
def _deg_to_dir(deg):
    """风向角度 → 中文方向"""
    dirs = ["北", "东北偏北", "东北", "东北偏东", "东", "东南偏东", "东南", "东南偏南",
            "南", "西南偏南", "西南", "西南偏西", "西", "西北偏西", "西北", "西北偏北"]
    index = int((deg % 360) / 22.5)
    return dirs[index]


# ============================================================
#  统一采集入口
# ============================================================
def fetch_all_sources(lat, lon):
    """
    从所有已配置的数据源并行采集天气数据。
    免费5源 + 需Key最多4源 = 最多9个数据源。
    返回: {"sources": [...], "ok_count": N, "total_count": M}
    """
    import concurrent.futures

    fetchers = []

    # 免费免Key数据源（始终启用）
    if config.OPEN_METEO_ENABLED:
        fetchers.append(("Open-Meteo", fetch_open_meteo))
    if config.OPEN_METEO_GFS_ENABLED:
        fetchers.append(("Open-Meteo GFS", fetch_open_meteo_gfs))
    if config.OPEN_METEO_ECMWF_ENABLED:
        fetchers.append(("Open-Meteo ECMWF", fetch_open_meteo_ecmwf))
    if config.SEVENTIMER_ENABLED:
        fetchers.append(("7Timer!", fetch_7timer))
    if config.WTTR_ENABLED:
        fetchers.append(("wttr.in", fetch_wttr))

    # 需Key数据源
    if config.OPENWEATHER_API_KEY:
        fetchers.append(("OpenWeatherMap", fetch_openweathermap))
    if config.WEATHERAPI_KEY:
        fetchers.append(("WeatherAPI", fetch_weatherapi))
    if config.QWEATHER_API_KEY:
        fetchers.append(("和风天气", fetch_qweather))
    if config.WINDY_API_KEY:
        fetchers.append(("Windy", fetch_windy))

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=9) as executor:
        future_map = {
            executor.submit(fn, lat, lon): name
            for name, fn in fetchers
        }
        for future in concurrent.futures.as_completed(future_map):
            name = future_map[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                results.append(_empty_result(name, str(e)))

    # 按预设顺序排列
    order = {
        "Open-Meteo": 0, "Open-Meteo GFS": 1, "Open-Meteo ECMWF": 2,
        "7Timer!": 3, "wttr.in": 4,
        "OpenWeatherMap": 5, "WeatherAPI": 6, "和风天气": 7, "Windy": 8,
    }
    results.sort(key=lambda x: order.get(x["source"], 99))

    ok_count = sum(1 for r in results if r["status"] == "ok")
    return {
        "sources": results,
        "ok_count": ok_count,
        "total_count": len(results),
    }
