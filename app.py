"""
天气AI预测平台 - Flask 后端

API 端点:
  GET  /api/search?q=北京        — 城市搜索
  GET  /api/weather?lat=..&lon=..&city=北京  — 获取多源天气 + AI 预测
  GET  /api/sources              — 查看已配置的数据源状态
"""

from flask import Flask, request, jsonify, render_template, session, redirect, url_for
import config
import weather_sources
import ai_fusion
import sqlite3
import os
from datetime import datetime
from functools import wraps

# 旅行路线天气模块
try:
    import route_weather as rw
    ROUTE_WEATHER_AVAILABLE = True
except Exception as e:
    print(f"[警告] route_weather 模块加载失败: {e}")
    ROUTE_WEATHER_AVAILABLE = False

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "weather-ai-secret-2026")

# 确保 JSON 正确编码 Unicode（支持中文等特殊字符）
app.config['JSON_AS_ASCII'] = False

# ===== IP 访问记录 SQLite =====
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "visitors.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            path TEXT NOT NULL,
            user_agent TEXT,
            visited_at TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS visit_summary (
            ip TEXT PRIMARY KEY,
            visit_count INTEGER DEFAULT 0,
            first_visit TEXT,
            last_visit TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_client_ip():
    # 获取真实 IP（支持反向代理）
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP').strip()
    return request.remote_addr or "unknown"

def record_visit():
    """记录一次访问"""
    ip = get_client_ip()
    path = request.path
    ua = request.headers.get('User-Agent', '')[:500]
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # 记录明细
        c.execute("INSERT INTO visits (ip, path, user_agent, visited_at) VALUES (?, ?, ?, ?)",
                  (ip, path, ua, now))
        # 更新汇总
        c.execute("""
            INSERT INTO visit_summary (ip, visit_count, first_visit, last_visit)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(ip) DO UPDATE SET
                visit_count = visit_count + 1,
                last_visit = ?
        """, (ip, now, now, now))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[访问记录] 写入失败: {e}")

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

init_db()

# ===== 请求钩子：记录所有访问 =====
@app.before_request
def before_request():
    # 不记录静态资源
    if not request.path.startswith('/static/'):
        record_visit()


@app.route("/")
def index():
    return render_template("index.html", amap_key=config.AMAP_JS_KEY, amap_security=config.AMAP_SECURITY_CODE)


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
        # 免费免Key数据源（仅展示实际启用的源）
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
            "name": "wttr.in",
            "enabled": config.WTTR_ENABLED,
            "needs_key": False,
            "status": "active" if config.WTTR_ENABLED else "disabled",
            "desc": "WorldWeatherOnline",
        },
    ]

    ai_status = "active" if (config.AI_API_KEY and config.AI_BASE_URL and config.AI_MODEL) else "needs_key"

    return jsonify({
        "weather_sources": sources,
        "ai_mode": "AI大模型" if ai_status == "active" else "统计融合",
        "ai_status": ai_status,
    })


# ===== 后台管理系统 =====
@app.route("/admin/login")
def admin_login():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))
    return render_template("admin_login.html")


@app.route("/admin/login", methods=["POST"])
def admin_login_post():
    password = request.form.get("password", "")
    if password == config.ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        return redirect(url_for('admin_dashboard'))
    return render_template("admin_login.html", error="密码错误")


@app.route("/admin/logout")
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))


@app.route("/admin")
@admin_required
def admin_dashboard():
    """后台管理面板：展示访问统计"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 总访问量
    c.execute("SELECT COUNT(*) FROM visits")
    total_visits = c.fetchone()[0]

    # 独立IP数
    c.execute("SELECT COUNT(*) FROM visit_summary")
    unique_ips = c.fetchone()[0]

    # 今日访问量
    today = datetime.now().strftime('%Y-%m-%d')
    c.execute("SELECT COUNT(*) FROM visits WHERE visited_at LIKE ?", (f"{today}%",))
    today_visits = c.fetchone()[0]

    # 各IP访问统计（按访问次数降序）
    c.execute("""
        SELECT ip, visit_count, first_visit, last_visit
        FROM visit_summary
        ORDER BY visit_count DESC
        LIMIT 100
    """)
    ip_stats = c.fetchall()

    # 最近50条访问记录
    c.execute("""
        SELECT ip, path, user_agent, visited_at
        FROM visits
        ORDER BY id DESC
        LIMIT 50
    """)
    recent_visits = c.fetchall()

    # 各路径访问统计
    c.execute("""
        SELECT path, COUNT(*) as cnt
        FROM visits
        GROUP BY path
        ORDER BY cnt DESC
        LIMIT 20
    """)
    path_stats = c.fetchall()

    conn.close()

    return render_template("admin_dashboard.html",
                           total_visits=total_visits,
                           unique_ips=unique_ips,
                           today_visits=today_visits,
                           ip_stats=ip_stats,
                           recent_visits=recent_visits,
                           path_stats=path_stats)


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
    sample_interval = data.get("sample_interval")  # 采样间隔（km），None 表示自适应

    if not all(v is not None for v in [start_lat, start_lng, end_lat, end_lng]):
        return jsonify({"error": "缺少起点或终点坐标"}), 400

    # 校验采样间隔范围
    if sample_interval is not None:
        try:
            sample_interval = float(sample_interval)
            sample_interval = max(50, min(500, sample_interval))  # 限制 50-500km
        except (TypeError, ValueError):
            sample_interval = None

    try:
        # 1. 获取路线（支持途径点）
        route_info = rw.get_route(start_lat, start_lng, end_lat, end_lng, waypoints, mode)
        route_info["mode"] = mode

        # 2. 沿路线采样点（支持用户指定间隔）
        samples = rw.sample_route_points(route_info["geometry"], interval_km=sample_interval)

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
    if config.WTTR_ENABLED: active.append("wttr.in")
    print(", ".join(active) if active else "无")
    print(f"  免费源: {sum([config.OPEN_METEO_ENABLED, config.OPEN_METEO_GFS_ENABLED, config.OPEN_METEO_ECMWF_ENABLED, config.WTTR_ENABLED])} 个")
    print(f"  地图引擎: {'高德地图' if config.AMAP_JS_KEY else '未配置（需设置 AMAP_JS_KEY）'}")
    print(f"{'='*50}\n")

    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
    )
