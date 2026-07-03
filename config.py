"""
天气AI预测平台 - 配置文件

所有天气数据源的 API Key 在此配置。
Open-Meteo 无需 Key，开箱即用。
其余数据源请填入你自己的 Key（留空则自动跳过该源）。
"""

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
AI_API_KEY = ""        # AI 服务的 API Key
AI_BASE_URL = ""       # 如 "https://api.deepseek.com/v1" 或 "https://api.openai.com/v1"
AI_MODEL = ""          # 如 "deepseek-chat" 或 "gpt-4o-mini"

# ============ 应用配置 ============

import os

# 云端部署时通过环境变量指定端口和主机
FLASK_HOST = os.environ.get("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.environ.get("PORT", 5000))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "True") == "True"

# 请求超时（秒）
REQUEST_TIMEOUT = 10
