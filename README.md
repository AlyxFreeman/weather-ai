# 天气AI预测平台

多源天气数据AI融合预测平台，整合 9 个天气数据源（5 个免费免 Key 开箱即用），通过 AI 大模型分析生成精准预测，并支持旅行路线沿途天气分析。

## 本地运行

```bash
cd weather-ai
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt    # Windows
# .venv/bin/pip install -r requirements.txt       # macOS/Linux
.venv/Scripts/python app.py
# 访问 http://127.0.0.1:5000
```

## 公网访问

### 方式一：内网穿透（即时使用，电脑需保持开机）

```bash
# 终端 1：启动 Flask
.venv/Scripts/python app.py

# 终端 2：启动隧道
.venv/Scripts/python start_tunnel.py
```

会得到一个 `https://xxx.lhr.life` 的公网地址，在任何设备浏览器中打开即可。

### 方式二：云端部署（永久可用，电脑关机也能访问）

推荐使用 [Render](https://render.com)（免费套餐）：

1. 将整个 `weather-ai` 目录推送到 GitHub 仓库
2. 在 Render 创建新的 Web Service，连接该仓库
3. Render 会自动识别 `render.yaml` 配置
4. 部署完成后获得 `https://weather-ai.onrender.com` 类似的永久地址

也可以部署到 [PythonAnywhere](https://www.pythonanywhere.com)、[Railway](https://railway.app) 等平台。

## 配置

编辑 `config.py`：

- 5 个免费数据源默认开启，无需任何配置
- 4 个需 Key 数据源：填入 API Key 后自动激活
- AI 大模型：填入 Key/URL/Model 后从统计模式切换为 AI 分析模式

## 技术栈

- 后端：Python + Flask + Gunicorn
- 前端：原生 HTML/CSS/JS + Chart.js + Leaflet.js
- 数据源：Open-Meteo / 7Timer! / wttr.in / OpenWeatherMap / WeatherAPI / 和风天气 / Windy
- 地图：OpenStreetMap + OSRM 路线规划
- 高程：Open-Meteo Elevation API
