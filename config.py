"""
天气AI预测平台 - 配置文件

所有天气数据源的 API Key 在此配置。
Open-Meteo 无需 Key，开箱即用。
其余数据源请填入你自己的 Key（留空则自动跳过该源）。
"""

import os

# ============ 天气数据源 API Keys ============

# --- 免费免Key数据源（开箱即用，多源融合） ---

# Open-Meteo BestMatch（完全免费，无需注册，自动选择最优模型组合）
# 文档: https://open-meteo.com/en/docs
OPEN_METEO_ENABLED = True

# Open-Meteo GFS（使用 NOAA 全球预报系统模型，与 BestMatch 使用不同模型）
OPEN_METEO_GFS_ENABLED = True

# Open-Meteo ECMWF（使用欧洲中期天气预报中心模型，精度通常最高）
OPEN_METEO_ECMWF_ENABLED = True

# 7Timer!（免费免Key，基于 GFS/CMC 模型的独立气象服务）
# 文档: http://www.7timer.info/
SEVENTIMER_ENABLED = True

# wttr.in（免费免Key，基于 WorldWeatherOnline 数据）
# 文档: https://github.com/chubin/wttr.in
WTTR_ENABLED = True

# --- 需Key数据源（填入Key后自动激活，进一步提升多源覆盖） ---

# OpenWeatherMap（免费额度: 1000次/天）
# 注册: https://home.openweathermap.org/api_keys
OPENWEATHER_API_KEY = ""  # 填入你的 Key

# WeatherAPI（免费额度: 100万次/月）
# 注册: https://www.weatherapi.com/signup.aspx
WEATHERAPI_KEY = ""  # 填入你的 Key

# 和风天气 QWeather（免费额度: 1000次/天）
# 注册: https://dev.qweather.com/
QWEATHER_API_KEY = ""  # 填入你的 Key

# Windy（免费额度有限）
# 注册: https://api.windy.com/apiKeys
WINDY_API_KEY = ""  # 填入你的 Key

# ============ AI 大模型配置 ============

# 使用 OpenAI 兼容接口（支持 OpenAI / DeepSeek / 通义千问等）
# 留空则回退到统计融合模式（不需要任何 AI 服务）
AI_API_KEY = os.environ.get("AI_API_KEY", "sk-f6d47897744048ad8bc5f4d6fd429715")  # DeepSeek API Key
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.deepseek.com/v1")  # DeepSeek 接口地址
AI_MODEL = os.environ.get("AI_MODEL", "deepseek-chat")  # DeepSeek 模型

# ============ 高德地图配置 ============

# 高德开放平台注册: https://lbs.amap.com/
# 1. 创建「Web端(JS API)」应用 → 获取 JS API Key 和安全密钥
# 2. 创建「Web服务」应用 → 获取 Web 服务 Key
AMAP_JS_KEY = os.environ.get("AMAP_JS_KEY", "c866ea6b48195fef40b60c0df53b321b")        # JS API Key（前端地图用）
AMAP_SECURITY_CODE = os.environ.get("AMAP_SECURITY_CODE", "af40c61a9d2221624e6bbe75087c8cf6")  # JS API 安全密钥
AMAP_WEB_KEY = os.environ.get("AMAP_WEB_KEY", "72ffc2b363aedc2c480f1cc5a5372b55")      # Web 服务 Key（后端路径规划/地理编码用）

# ============ 应用配置 ============

# 云端部署时通过环境变量指定端口和主机
FLASK_HOST = os.environ.get("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.environ.get("PORT", 5000))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "False") == "True"

# 请求超时（秒）
REQUEST_TIMEOUT = 10

# ============ 后台管理配置 ============

# 访问后台的密码（只有你知道）
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "weather2026")
