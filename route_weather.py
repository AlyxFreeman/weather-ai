"""
路线天气分析模块

功能：
1. 调用 OSRM 获取路线
2. 沿路线采样天气点
3. 对各采样点并发查询天气
4. AI 分析沿途天气变化
"""
import math
import requests
from weather_sources import fetch_all_sources
from ai_fusion import fuse_and_predict
import config
from collections import Counter


# OSRM 公共实例（免费，无需 Key）
OSRM_BASE = "https://router.project-osrm.org/route/v1"

# Open-Meteo 高程 API（免费，无需 Key，支持批量）
ELEVATION_API = "https://api.open-meteo.com/v1/elevation"


def get_route(start_lat, start_lng, end_lat, end_lng, waypoints=None, mode="car"):
    """
    调用 OSRM 获取路线。

    参数:
        start_lat, start_lng: 起点经纬度
        end_lat, end_lng: 终点经纬度
        waypoints: 途径点列表 [{"lat": ..., "lng": ...}, ...]
        mode: 出行方式 ("car"/"bike"/"foot")

    返回:
        {
            "geometry": GeoJSON LineString,
            "distance_m": 总距离(米),
            "duration_s": 预计时间(秒),
            "distance_km": 总距离(km),
            "duration_text": 预计时间(可读文本),
        }
    """
    profile_map = {"car": "driving", "bike": "cycling", "foot": "walking"}
    profile = profile_map.get(mode, "driving")

    # 构建坐标字符串（支持途径点）
    coords_parts = [f"{start_lng},{start_lat}"]
    if waypoints:
        for wp in waypoints:
            coords_parts.append(f"{wp['lng']},{wp['lat']}")
    coords_parts.append(f"{end_lng},{end_lat}")
    coords_str = ";".join(coords_parts)

    url = (
        f"{OSRM_BASE}/{profile}/"
        f"{coords_str}"
        f"?overview=full&geometries=geojson&annotations=true"
    )
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError(f"OSRM 路线规划失败: {data.get('message', '未知错误')}")

    route = data["routes"][0]
    distance_m = route["distance"]
    duration_s = route["duration"]

    return {
        "geometry": route["geometry"],
        "distance_m": distance_m,
        "duration_s": duration_s,
        "distance_km": round(distance_m / 1000, 1),
        "duration_text": _format_duration(duration_s),
    }


def sample_route_points(geometry, max_samples=12, min_interval_km=10):
    """
    沿路线几何采样点。

    策略：
    - 短路线（<100km）：至少 3 个采样点（起点、中点、终点）
    - 中等路线（100-500km）：每 50km 一个采样点
    - 长路线（>500km）：每 100km 一个采样点，最多 max_samples 个

    返回:
        [{"lat": ..., "lon": ..., "distance_m": ...}, ...]
    """
    coords = geometry["coordinates"]  # GeoJSON: [lng, lat]
    total_points = len(coords)

    if total_points < 2:
        return []

    # 计算路线总长度（通过坐标点累加）
    total_dist = 0
    distances = [0]  # 每个坐标点距起点的累计距离（米）
    for i in range(1, total_points):
        lng1, lat1 = coords[i - 1]
        lng2, lat2 = coords[i]
        seg_dist = _haversine(lat1, lng1, lat2, lng2)
        total_dist += seg_dist
        distances.append(total_dist)

    total_km = total_dist / 1000

    # 确定采样策略
    if total_km < 50:
        interval_m = total_dist / max(2, min(3, total_km / 10))
    elif total_km < 200:
        interval_m = 50 * 1000
    elif total_km < 500:
        interval_m = 80 * 1000
    else:
        interval_m = min(120 * 1000, total_dist / max_samples)

    # 采样
    samples = []
    sampled_dist = set()

    # 始终包含起点和终点
    samples.append(_interpolate_point(coords, distances, 0))
    sampled_dist.add(0)

    current_dist = interval_m
    while current_dist < total_dist and len(samples) < max_samples:
        pt = _interpolate_point(coords, distances, current_dist)
        rounded = round(current_dist / 1000) * 1000  # 避免重复
        if rounded not in sampled_dist:
            samples.append(pt)
            sampled_dist.add(rounded)
        current_dist += interval_m

    # 添加终点（如果还没加）
    if samples[-1]["distance_m"] < total_dist - 100:
        samples.append(_interpolate_point(coords, distances, total_dist))

    # 按距离排序并添加 km 标签
    samples.sort(key=lambda x: x["distance_m"])
    for pt in samples:
        pt["distance_km"] = round(pt["distance_m"] / 1000, 1)

    return samples


def fetch_elevations(samples):
    """
    使用 Open-Meteo 高程 API 批量获取采样点海拔。

    返回: None（直接在 samples 中注入 elevation 字段）
    """
    if not samples:
        return

    # Open-Meteo 批量上限 100 个点，我们的采样点最多 12 个，无需分批
    lats = ",".join(f"{pt['lat']:.6f}" for pt in samples)
    lons = ",".join(f"{pt['lon']:.6f}" for pt in samples)

    try:
        resp = requests.get(
            ELEVATION_API,
            params={"latitude": lats, "longitude": lons},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        elevations = data.get("elevation", [])

        for i, pt in enumerate(samples):
            if i < len(elevations) and elevations[i] is not None:
                pt["elevation"] = int(round(elevations[i]))
            else:
                pt["elevation"] = None

        print(f"[高程] 成功获取 {len(elevations)} 个点海拔")

    except Exception as e:
        print(f"[高程] 获取失败: {e}")
        for pt in samples:
            pt["elevation"] = None


def fetch_weather_along_route(samples, city_name_hint="", departure_time=None):
    """
    对路线上的每个采样点并发查询天气，并做多源融合。

    参数:
        samples: 路线采样点列表
        city_name_hint: 城市名提示（用于日志）
        departure_time: 出发时间（ISO格式字符串，如 "2026-07-04T08:00:00"）

    返回:
        [{"lat": ..., "lon": ..., "distance_km": ..., "weather": {...}}, ...]
    """
    import concurrent.futures
    import statistics
    import math
    import datetime
    import weather_sources

    # 出行方式对应的速度（米/秒）
    SPEED_MAP = {"car": 27.8, "bike": 4.17, "foot": 1.39}

    # 解析出发时间
    departure_dt = None
    if departure_time:
        try:
            departure_dt = datetime.datetime.fromisoformat(departure_time.replace("Z", "+00:00"))
        except Exception:
            departure_dt = None

    def _fuse_weather_data(sources_data):
        """
        对多个数据源的当前天气进行融合。
        返回融合后的天气对象，如果所有源都失败则返回 None。
        """
        ok_sources = [s for s in sources_data["sources"] if s["status"] == "ok" and s.get("current")]

        if not ok_sources:
            return None

        # 收集各源数据
        temps, feels, humidities, wind_speeds, wind_dirs, pressures, weather_texts, weather_emojis = \
            [], [], [], [], [], [], [], []

        for s in ok_sources:
            cur = s["current"]
            if cur:
                temps.append(cur["temperature"])
                feels.append(cur["feels_like"])
                humidities.append(cur["humidity"])
                wind_speeds.append(cur["wind_speed"])
                wind_dirs.append(cur["wind_direction_deg"])
                if cur["pressure"]:
                    pressures.append(cur["pressure"])
                weather_texts.append(cur["weather_text"])
                weather_emojis.append(cur["weather_emoji"])

        # 异常值剔除函数
        def _filter_outliers(values):
            if len(values) <= 2:
                return values
            med = statistics.median(values)
            stdev = statistics.stdev(values) if len(values) > 1 else 0
            if stdev == 0:
                return values
            return [v for v in values if abs(v - med) <= 2 * stdev]

        # 对数值型数据进行异常值剔除后取平均
        temps_f = _filter_outliers(temps)
        feels_f = _filter_outliers(feels)
        humidities_f = _filter_outliers(humidities)
        wind_speeds_f = _filter_outliers(wind_speeds)

        avg_temp = round(statistics.mean(temps_f), 1) if temps_f else 0
        avg_feels = round(statistics.mean(feels_f), 1) if feels_f else 0
        avg_humidity = round(statistics.mean(humidities_f)) if humidities_f else 0
        avg_wind = round(statistics.mean(wind_speeds_f), 1) if wind_speeds_f else 0
        avg_pressure = round(statistics.mean(pressures)) if pressures else 0

        # 风向：向量平均
        if wind_dirs:
            sin_sum = sum(math.sin(math.radians(d)) for d in wind_dirs)
            cos_sum = sum(math.cos(math.radians(d)) for d in wind_dirs)
            avg_wind_deg = int((math.degrees(math.atan2(sin_sum, cos_sum)) + 360) % 360)
            avg_wind_dir = weather_sources._deg_to_dir(avg_wind_deg)
        else:
            avg_wind_deg = 0
            avg_wind_dir = "未知"

        # 天气状况：取众数
        weather_counter = Counter(weather_texts)
        main_weather = weather_counter.most_common(1)[0][0] if weather_texts else "未知"

        emoji_counter = Counter(weather_emojis)
        main_emoji = emoji_counter.most_common(1)[0][0] if weather_emojis else "❓"

        return {
            "temperature": avg_temp,
            "feels_like": avg_feels,
            "humidity": avg_humidity,
            "wind_speed": avg_wind,
            "wind_direction": avg_wind_dir,
            "wind_direction_deg": avg_wind_deg,
            "pressure": avg_pressure,
            "weather_text": main_weather,
            "weather_emoji": main_emoji,
            "is_day": True,
            "source_count": len(ok_sources),
        }

    def _get_forecast_at_time(sources_data, target_dt):
        """
        从多个数据源的预报中，找到与目标时间最接近的日期的预报数据。
        返回融合后的预报天气对象，如果无法获取则返回 None。
        """
        if not target_dt:
            return None

        target_date = target_dt.strftime("%Y-%m-%d")
        forecast_data = []  # 收集所有源在目标日期的预报

        for s in sources_data["sources"]:
            if s["status"] != "ok":
                continue
            for day in s.get("forecast", []):
                if day["date"] == target_date:
                    forecast_data.append({
                        "source": s["source"],
                        "temp_max": day["temp_max"],
                        "temp_min": day["temp_min"],
                        "weather_text": day["weather_text"],
                        "weather_emoji": day["weather_emoji"],
                        "precipitation": day["precipitation"],
                        "precipitation_prob": day["precipitation_prob"],
                        "wind_speed": day["wind_speed"],
                    })

        if not forecast_data:
            return None

        # 融合预报数据
        temps_max = [d["temp_max"] for d in forecast_data]
        temps_min = [d["temp_min"] for d in forecast_data]
        precip = [d["precipitation"] for d in forecast_data]
        precip_prob = [d["precipitation_prob"] for d in forecast_data]
        wind = [d["wind_speed"] for d in forecast_data]
        weather_texts = [d["weather_text"] for d in forecast_data]
        weather_emojis = [d["weather_emoji"] for d in forecast_data]

        avg_temp_max = round(statistics.mean(temps_max), 1) if temps_max else 0
        avg_temp_min = round(statistics.mean(temps_min), 1) if temps_min else 0
        avg_precip = round(statistics.mean(precip), 1) if precip else 0
        avg_precip_prob = round(statistics.mean(precip_prob)) if precip_prob else 0
        avg_wind = round(statistics.mean(wind), 1) if wind else 0

        weather_counter = Counter(weather_texts)
        main_weather = weather_counter.most_common(1)[0][0] if weather_texts else "未知"
        emoji_counter = Counter(weather_emojis)
        main_emoji = emoji_counter.most_common(1)[0][0] if weather_emojis else "❓"

        return {
            "temperature": round((avg_temp_max + avg_temp_min) / 2, 1),
            "weather_text": main_weather,
            "weather_emoji": main_emoji,
            "precipitation": avg_precip,
            "precipitation_prob": avg_precip_prob,
            "wind_speed": avg_wind,
        }

    def fetch_one(pt):
        try:
            # 调用天气数据源获取原始数据
            result = weather_sources.fetch_all_sources(pt["lat"], pt["lon"])

            # 多源融合：获取融合后的当前天气
            weather = _fuse_weather_data(result)

            # 如果提供了出发时间，尝试获取预报数据
            if departure_dt and weather:
                # 计算预计到达时间
                distance_m = pt.get("distance_m", 0)
                # 获取速度（需要根据 mode 确定，这里使用默认值）
                speed = SPEED_MAP.get("car", 27.8)  # 默认使用车速
                travel_time_s = distance_m / speed if speed > 0 else 0
                arrival_dt = departure_dt + datetime.timedelta(seconds=travel_time_s)

                # 如果预计到达时间与当前时间相差不超过 48 小时，则获取预报
                now = datetime.datetime.now()
                time_diff = abs((arrival_dt - now).total_seconds())
                if time_diff <= 48 * 3600:
                    forecast = _get_forecast_at_time(result, arrival_dt)
                    if forecast:
                        # 用预报数据更新融合后的天气对象
                        weather["temperature"] = forecast.get("temperature", weather["temperature"])
                        weather["weather_text"] = forecast.get("weather_text", weather["weather_text"])
                        weather["weather_emoji"] = forecast.get("weather_emoji", weather["weather_emoji"])
                        weather["precipitation"] = forecast.get("precipitation", 0)
                        weather["precipitation_prob"] = forecast.get("precipitation_prob", 0)
                        weather["wind_speed"] = forecast.get("wind_speed", weather["wind_speed"])
                        weather["is_forecast"] = True

            return {**pt, "weather": weather, "raw": result}
        except Exception as e:
            print(f"[路线天气] 采样点 {pt.get('lat')},{pt.get('lon')} 查询失败: {e}")
            import traceback
            traceback.print_exc()
            return {**pt, "weather": None, "raw": None}

    # 先批量获取所有采样点海拔（一次请求，不阻塞天气查询）
    fetch_elevations(samples)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_one, pt): pt for pt in samples}
        results = []
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
        results.sort(key=lambda x: x["distance_m"])
        return results


def analyze_route_weather(samples, route_info, mode="car"):
    """
    用 AI 分析沿途天气变化。
    如果未配置 AI Key，则生成统计文本。

    返回:
        {
            "ai_analysis": "AI 分析的沿途天气文本",
            "recommendations": ["建议1", ...],
            "temp_spread": 沿途温差,
            "weather_changes": [{"at_km": ..., "change": ...}, ...]
        }
    """
    # 收集有天气数据的采样点
    valid = [s for s in samples if s.get("weather")]
    if not valid:
        return {
            "ai_analysis": "沿途各点天气数据获取失败，无法进行分析。",
            "recommendations": ["建议检查网络连接后重试"],
            "temp_spread": 0,
        }

    # 计算温差
    temps = [s["weather"]["temperature"] for s in valid]
    temp_spread = round(max(temps) - min(temps), 1)

    # 构造 AI 提示
    if config.AI_API_KEY and config.AI_BASE_URL and config.AI_MODEL:
        try:
            return _ai_analyze_route(valid, route_info, temp_spread)
        except Exception as e:
            print(f"[AI路线分析] 失败，回退统计模式: {e}")

    # 统计模式
    return _statistical_route_analysis(valid, route_info, temp_spread)


# ============ 内部工具函数 ============

def _haversine(lat1, lon1, lat2, lon2):
    """计算两点间距离（米）"""
    R = 6371000  # 地球半径（米）
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _interpolate_point(coords, distances, target_dist):
    """
    在路线上插值一个点，使其距起点距离为 target_dist。
    """
    n = len(coords)
    for i in range(1, n):
        if distances[i] >= target_dist:
            # 在 coords[i-1] 和 coords[i] 之间线性插值
            seg_dist = distances[i] - distances[i - 1]
            if seg_dist == 0:
                frac = 0
            else:
                frac = (target_dist - distances[i - 1]) / seg_dist
            lng = coords[i - 1][0] + frac * (coords[i][0] - coords[i - 1][0])
            lat = coords[i - 1][1] + frac * (coords[i][1] - coords[i - 1][1])
            return {"lat": lat, "lon": lng, "distance_m": target_dist}
    # 如果 target_dist 超过最后一个点，返回最后一个点
    return {"lat": coords[-1][1], "lon": coords[-1][0], "distance_m": distances[-1]}


def _format_duration(seconds):
    """将秒数转为可读文本"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h > 0:
        return f"{h}小时{m}分钟"
    return f"{m}分钟"


def _statistical_route_analysis(samples, route_info, temp_spread):
    """统计模式：生成沿途天气分析文本"""
    lines = []
    lines.append(f"【沿途天气分析】路线全长 {route_info['distance_km']} km，共采样 {len(samples)} 个点。")

    # 海拔概况
    elevations = [s.get("elevation") for s in samples if s.get("elevation") is not None]
    if elevations:
        elev_min, elev_max = min(elevations), max(elevations)
        elev_diff = elev_max - elev_min
        lines.append(f"沿途海拔 {elev_min}m ~ {elev_max}m（最大高差 {elev_diff}m）。")
        if elev_diff >= 500:
            lines.append(f"⚠️ 沿途海拔变化显著（{elev_diff}m），高海拔路段气温可能低 "
                         f"{round(elev_diff * 0.006, 1)}°C 以上，需注意结冰和横风风险。")

    # 温差分析
    temps = [s["weather"]["temperature"] for s in samples]
    if temp_spread <= 1:
        lines.append(f"沿途温差极小（仅 {temp_spread}°C），天气条件稳定。")
    elif temp_spread <= 3:
        lines.append(f"沿途温差 {temp_spread}°C，属于正常范围。")
    else:
        lines.append(f"⚠️ 沿途温差较大（{temp_spread}°C），不同路段天气可能明显不同，请注意。")

    # 找出有降水的路段
    rain_sections = []
    for i, s in enumerate(samples):
        w = s["weather"]
        if w and w.get("precipitation_prob", 0) >= 50:
            section = f"距起点 {s['distance_km']}km 处（{w['weather_text']}，降水概率 {w['precipitation_prob']}%）"
            rain_sections.append(section)

    if rain_sections:
        lines.append(f"\n⚠️ 以下路段可能有降水：\n  - " + "\n  - ".join(rain_sections))
    else:
        lines.append("\n沿途无明显降水路段，天气较为干燥。")

    # 风力分析
    windy = [s for s in samples if s["weather"] and s["weather"].get("wind_speed", 0) >= 10]
    if windy:
        lines.append(f"\n💨 以下路段风力较大（≥10m/s），注意行车安全：")
        for s in windy:
            lines.append(f"  - 距起点 {s['distance_km']}km：{s['weather']['wind_speed']}m/s")

    # 生成建议
    recs = _generate_route_recommendations(samples, route_info)

    return {
        "ai_analysis": "\n".join(lines),
        "recommendations": recs,
        "temp_spread": temp_spread,
    }


def _generate_route_recommendations(samples, route_info):
    """生成旅行建议"""
    recs = []
    distance_km = route_info["distance_km"]
    mode = route_info.get("mode", "car")

    # 根据路线长度给出建议
    if mode == "car":
        if distance_km > 300:
            recs.append("🚗 长途自驾，建议每 2 小时休息一次，避免疲劳驾驶。")
        elif distance_km > 100:
            recs.append("🚗 中等距离驾驶，出发前检查轮胎和油量。")
    elif mode == "bike":
        if distance_km > 30:
            recs.append("🚴 长途骑行，请做好防晒，携带足够饮用水。")
        else:
            recs.append("🚴 骑行请注意佩戴头盔，选择自行车道行驶。")
    elif mode == "foot":
        recs.append("🚶 徒步出行，建议穿舒适的运动鞋，携带雨具。")

    # 根据沿途天气给出建议
    for s in samples:
        w = s["weather"]
        if not w:
            continue
        if w.get("precipitation_prob", 0) >= 50:
            recs.append(f"☔ 距起点 {s['distance_km']}km 处降水概率高，建议携带雨具。")
            break
        if w.get("temperature", 0) >= 32:
            recs.append(f"🌡️ 沿途最高温 {w['temperature']}°C，注意防暑降温，多喝水。")
            break

    # 通用建议
    if not recs:
        recs.append("🌤️ 沿途天气状况总体良好，适合出行。")

    return recs[:4]  # 最多 4 条


def _ai_analyze_route(samples, route_info, temp_spread):
    """调用 AI 大模型分析沿途天气"""
    from openai import OpenAI

    client = OpenAI(api_key=config.AI_API_KEY, base_url=config.AI_BASE_URL)

    # 构造采样点摘要
    sample_lines = []
    for i, s in enumerate(samples):
        w = s["weather"]
        if not w:
            continue
        elev = s.get("elevation")
        elev_str = f"，海拔 {elev}m" if elev is not None else ""
        sample_lines.append(
            f"  点{i+1}（距起点 {s['distance_km']}km{elev_str}）："
            f"{w['weather_text']}，{w['temperature']}°C（体感 {w['feels_like']}°C），"
            f"湿度 {w['humidity']}%，风速 {w['wind_speed']}m/s，"
            f"降水概率 {w.get('precipitation_prob', 0)}%"
        )

    # 海拔信息摘要
    elevations = [s.get("elevation") for s in samples if s.get("elevation") is not None]
    elev_summary = ""
    if elevations:
        elev_summary = f"\n- 沿途海拔范围：{min(elevations)}m ~ {max(elevations)}m，最大高差 {max(elevations) - min(elevations)}m"

    prompt = f"""你是一位专业气象分析师和出行顾问。请基于以下路线沿途各采样点的天气数据，进行综合分析并给出准确的出行建议。

## 路线信息
- 全长：{route_info['distance_km']} km
- 预计用时：{route_info['duration_text']}
- 出行方式：{route_info.get('mode', 'car')}
- 沿途温差：{temp_spread}°C{elev_summary}

## 沿途各点天气数据
{chr(10).join(sample_lines) if sample_lines else '（无有效天气数据）'}

## 任务
请分析沿途天气变化趋势和潜在风险，给出融合预测和出行建议。严格按照 JSON 格式输出：

{{
    "analysis": "详细分析沿途天气变化（200-400字）：包括温度变化趋势、降水路段、风力变化、需要特别注意的路段等。如果沿途有较大海拔变化，需结合海拔分析温度递减效应和高海拔路段的结冰/大风风险",
    "recommendations": ["具体出行建议1", "具体出行建议2", "具体出行建议3", "具体出行建议4"],
    "risk_sections": ["风险路段描述1", ...],
    "confidence": "high/medium/low - 分析置信度"
}}

注意：
- analysis 要分段描述沿途天气变化，指出具体在多少公里处有什么天气变化
- 结合海拔变化分析：海拔每升高100m气温约下降0.6°C，高海拔路段需关注结冰、横风、能见度等风险
- recommendations 要具体实用，包含穿衣、行车、时间安排等
- 如果沿途天气差异大，confidence 应为 medium 或 low
"""

    response = client.chat.completions.create(
        model=config.AI_MODEL,
        messages=[
            {"role": "system", "content": "你是一位专业气象分析师和出行顾问，擅长分析路线沿途天气变化。请只输出 JSON 格式的内容。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=1000,
    )

    content = response.choices[0].message.content.strip()

    # 尝试解析 JSON
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0] if "```" in content else content
        content = content.strip()

    try:
        result = __import__("json").loads(content)
        return {
            "ai_analysis": result.get("analysis", ""),
            "recommendations": result.get("recommendations", []),
            "temp_spread": temp_spread,
            "risk_sections": result.get("risk_sections", []),
            "confidence": result.get("confidence", "medium"),
        }
    except Exception:
        return {
            "ai_analysis": content,
            "recommendations": _generate_route_recommendations(samples, route_info),
            "temp_spread": temp_spread,
        }
