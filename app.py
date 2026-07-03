"""
天气AI预测平台 - Flask 后端

API 端点:
  GET  /api/search?q=北京        — 城市搜索
  GET  /api/weather?lat=..&lon=..&city=北京  — 获取多源天气 + AI 预测
  GET  /api/sources              — 查看已配置的数据源状态
"""

from flask import Flask, request, jsonify, render_template
import config
import weather_sources
import ai_fusion

# 旅行路线天气模块
try:
    import route_weather as rw
    ROUTE_WEATHER_AVAILABLE = True
except Exception as e:
    print(f"[警告] route_weather 模块加载失败: {e}")
    ROUTE_WEATHER_AVAILABLE = False

app = Flask(__name__)

# 确保 JSON 正确编码 Unicode（支持中文等特殊字符）
app.config['JSON_AS_ASCII'] = False


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search")
def search_city():
    """城市搜索 API"""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "请输入城市名"}), 400

    results = weather_sources.geocode(q)
    return jsonify({"cities": results})


@app.route("/api/weather")
def get_weather():
    """获取多源天气 + AI 融合预测"""
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    city = request.args.get("city", "")

    if lat is None or lon is None:
        return jsonify({"error": "缺少经纬度参数"}), 400

    # 1. 多源数据采集
    sources_data = weather_sources.fetch_all_sources(lat, lon)

    # 2. AI 融合预测
    prediction = ai_fusion.fuse_and_predict(sources_data, city)

    return jsonify({
        "city": city,
        "lat": lat,
        "lon": lon,
        "sources": sources_data["sources"],
        "ok_count": sources_data["ok_count"],
        "total_count": sources_data["total_count"],
        "prediction": prediction,
    })


@app.route("/api/sources")
def get_sources_status():
    """查看已配置的数据源状态"""
    sources = [
        # 免费免Key数据源
        {
            "name": "Open-Meteo",
            "enabled": config.OPEN_METEO_ENABLED,
            "needs_key": False,
            "status": "active" if config.OPEN_METEO_ENABLED else "disabled",
            "desc": "最佳匹配模型",
        },
        {
            "name": "Open-Meteo GFS",
            "enabled": config.OPEN_METEO_GFS_ENABLED,
            "needs_key": False,
            "status": "active" if config.OPEN_METEO_GFS_ENABLED else "disabled",
            "desc": "NOAA全球预报模型",
        },
        {
            "name": "Open-Meteo ECMWF",
            "enabled": config.OPEN_METEO_ECMWF_ENABLED,
            "needs_key": False,
            "status": "active" if config.OPEN_METEO_ECMWF_ENABLED else "disabled",
            "desc": "欧洲中期预报模型",
        },
        {
            "name": "7Timer!",
            "enabled": config.SEVENTIMER_ENABLED,
            "needs_key": False,
            "status": "active" if config.SEVENTIMER_ENABLED else "disabled",
            "desc": "GFS/CMC独立服务",
        },
        {
            "name": "wttr.in",
            "enabled": config.WTTR_ENABLED,
            "needs_key": False,
            "status": "active" if config.WTTR_ENABLED else "disabled",
            "desc": "WorldWeatherOnline",
        },
        # 需Key数据源
        {
            "name": "OpenWeatherMap",
            "enabled": bool(config.OPENWEATHER_API_KEY),
            "needs_key": True,
            "status": "active" if config.OPENWEATHER_API_KEY else "needs_key",
            "desc": "需Key",
        },
        {
            "name": "WeatherAPI",
            "enabled": bool(config.WEATHERAPI_KEY),
            "needs_key": True,
            "status": "active" if config.WEATHERAPI_KEY else "needs_key",
            "desc": "需Key",
        },
        {
            "name": "和风天气",
            "enabled": bool(config.QWEATHER_API_KEY),
            "needs_key": True,
            "status": "active" if config.QWEATHER_API_KEY else "needs_key",
            "desc": "需Key",
        },
        {
            "name": "Windy",
            "enabled": bool(config.WINDY_API_KEY),
            "needs_key": True,
            "status": "active" if config.WINDY_API_KEY else "needs_key",
            "desc": "需Key",
        },
    ]

    ai_status = "active" if (config.AI_API_KEY and config.AI_BASE_URL and config.AI_MODEL) else "needs_key"

    return jsonify({
        "weather_sources": sources,
        "ai_mode": "AI大模型" if ai_status == "active" else "统计融合",
        "ai_status": ai_status,
    })


@app.route("/api/route-weather", methods=["POST"])
def get_route_weather():
    """获取路线沿途天气分析"""
    if not ROUTE_WEATHER_AVAILABLE:
        return jsonify({"error": "路线天气模块未加载，请检查 route_weather.py 是否存在"}), 500

    data = request.get_json(force=True, silent=True) or {}
    start_lat = data.get("start_lat")
    start_lng = data.get("start_lng")
    end_lat = data.get("end_lat")
    end_lng = data.get("end_lng")
    mode = data.get("mode", "car")  # car / bike / foot
    departure_time = data.get("departure_time", "")  # 出发时间（ISO格式）
    waypoints = data.get("waypoints", [])  # 途径点列表[{"lat":..., "lng":...}, ...]

    if not all(v is not None for v in [start_lat, start_lng, end_lat, end_lng]):
        return jsonify({"error": "缺少起点或终点坐标"}), 400

    try:
        # 1. 获取路线（支持途径点）
        route_info = rw.get_route(start_lat, start_lng, end_lat, end_lng, waypoints, mode)
        route_info["mode"] = mode

        # 2. 沿路线采样点
        samples = rw.sample_route_points(route_info["geometry"])

        # 3. 并发查询各采样点天气（支持出发时间）
        samples_with_weather = rw.fetch_weather_along_route(samples, departure_time=departure_time)

        # 4. AI 分析沿途天气
        analysis = rw.analyze_route_weather(samples_with_weather, route_info, mode)

        return jsonify({
            "distance_km": route_info["distance_km"],
            "duration_text": route_info["duration_text"],
            "route_info": {
                "distance_km": route_info["distance_km"],
                "duration_text": route_info["duration_text"],
            },
            "route_geometry": route_info["geometry"],
            "sample_count": len(samples_with_weather),
            "temp_spread": analysis.get("temp_spread", 0),
            "sample_points": samples_with_weather,
            "ai_analysis": analysis.get("ai_analysis", ""),
            "recommendations": analysis.get("recommendations", []),
            "risk_sections": analysis.get("risk_sections", []),
        })

    except Exception as e:
        print(f"[路线天气] 处理失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"路线规划失败: {str(e)}"}), 500


if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"  天气AI预测平台")
    print(f"  访问: http://{config.FLASK_HOST}:{config.FLASK_PORT}")
    print(f"  AI模式: {'大模型分析' if config.AI_API_KEY else '统计融合（未配置AI Key）'}")
    print(f"  数据源: ", end="")
    active = []
    if config.OPEN_METEO_ENABLED: active.append("Open-Meteo")
    if config.OPEN_METEO_GFS_ENABLED: active.append("Open-Meteo GFS")
    if config.OPEN_METEO_ECMWF_ENABLED: active.append("Open-Meteo ECMWF")
    if config.SEVENTIMER_ENABLED: active.append("7Timer!")
    if config.WTTR_ENABLED: active.append("wttr.in")
    if config.OPENWEATHER_API_KEY: active.append("OpenWeatherMap")
    if config.WEATHERAPI_KEY: active.append("WeatherAPI")
    if config.QWEATHER_API_KEY: active.append("和风天气")
    if config.WINDY_API_KEY: active.append("Windy")
    print(", ".join(active) if active else "无")
    print(f"  免费源: {sum([config.OPEN_METEO_ENABLED, config.OPEN_METEO_GFS_ENABLED, config.OPEN_METEO_ECMWF_ENABLED, config.SEVENTIMER_ENABLED, config.WTTR_ENABLED])} 个")
    print(f"  需Key源: {sum([bool(config.OPENWEATHER_API_KEY), bool(config.WEATHERAPI_KEY), bool(config.QWEATHER_API_KEY), bool(config.WINDY_API_KEY)])} 个")
    print(f"{'='*50}\n")

    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
    )
