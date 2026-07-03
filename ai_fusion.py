"""
AI 融合预测模块

两种模式：
1. AI 大模型模式（配置了 AI_API_KEY 时）：
   - 将多源天气数据喂给 LLM
   - LLM 分析差异、给出融合预测、不确定性说明、生活建议
   - 支持任何 OpenAI 兼容接口（OpenAI / DeepSeek / 通义千问等）

2. 统计融合模式（未配置 AI Key 时）：
   - 对各源数据做加权平均
   - 异常值检测与剔除
   - 模板生成分析文本
"""

import json
import statistics
import config


def fuse_and_predict(sources_data, city_name=""):
    """
    主入口：接收多源天气数据，输出 AI 融合预测结果。

    参数:
        sources_data: fetch_all_sources() 的返回值
        city_name: 城市名（用于文本生成）

    返回:
        {
            "mode": "ai" | "statistical",
            "summary": "总体天气描述",
            "temperature": {"value": 25.3, "confidence": "high"},
            "feels_like": 26.0,
            "humidity": 65,
            "wind": {"speed": 12.5, "direction": "东北"},
            "precipitation": {"probability": 30, "amount": 0.0},
            "forecast_7day": [...],
            "analysis": "详细分析文本",
            "recommendations": ["建议1", "建议2"],
            "source_comparison": {...},
        }
    """
    ok_sources = [s for s in sources_data["sources"] if s["status"] == "ok"]

    if not ok_sources:
        return {
            "mode": "error",
            "summary": "所有数据源均不可用，请检查 API Key 配置或网络连接。",
            "analysis": "无法获取任何天气数据。请确保至少 Open-Meteo（免费，无需 Key）可用。",
            "recommendations": [],
            "source_comparison": {},
        }

    # 先做统计融合（无论哪种模式都需要）
    fused = _statistical_fusion(ok_sources)

    # 如果配置了 AI Key，用大模型增强
    if config.AI_API_KEY and config.AI_BASE_URL and config.AI_MODEL:
        try:
            ai_result = _ai_analyze(ok_sources, fused, city_name)
            fused["mode"] = "ai"
            fused["ai_analysis"] = ai_result.get("analysis", "")
            fused["ai_recommendations"] = ai_result.get("recommendations", [])
            fused["ai_confidence"] = ai_result.get("confidence", "medium")
            # AI 分析可能会覆盖 summary
            if ai_result.get("summary"):
                fused["summary"] = ai_result["summary"]
        except Exception as e:
            print(f"[AI] 大模型分析失败，回退到统计模式: {e}")
            fused["mode"] = "statistical"
            fused["ai_analysis"] = ""
            fused["ai_recommendations"] = []
    else:
        fused["mode"] = "statistical"
        fused["ai_analysis"] = ""
        fused["ai_recommendations"] = []

    # 生成源对比数据
    fused["source_comparison"] = _build_source_comparison(ok_sources)

    return fused


def _statistical_fusion(ok_sources):
    """统计融合：加权平均 + 异常值剔除"""
    # 收集各源当前天气数据
    temps = []
    feels = []
    humidities = []
    wind_speeds = []
    wind_dirs = []
    pressures = []
    weather_texts = []

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

    # 异常值剔除：偏离中位数超过 2 个标准差的视为异常
    def _filter_outliers(values):
        if len(values) <= 2:
            return values
        med = statistics.median(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0
        if stdev == 0:
            return values
        return [v for v in values if abs(v - med) <= 2 * stdev]

    temps_f = _filter_outliers(temps)
    feels_f = _filter_outliers(feels)
    humidities_f = _filter_outliers(humidities)
    wind_speeds_f = _filter_outliers(wind_speeds)

    # 加权平均（各源等权，可扩展为按源可靠性加权）
    avg_temp = round(statistics.mean(temps_f), 1) if temps_f else 0
    avg_feels = round(statistics.mean(feels_f), 1) if feels_f else 0
    avg_humidity = round(statistics.mean(humidities_f)) if humidities_f else 0
    avg_wind = round(statistics.mean(wind_speeds_f), 1) if wind_speeds_f else 0
    avg_pressure = round(statistics.mean(pressures)) if pressures else 0

    # 风向：取各源角度的均值
    import math
    if wind_dirs:
        sin_sum = sum(math.sin(math.radians(d) % 360) for d in wind_dirs)
        cos_sum = sum(math.cos(math.radians(d) % 360) for d in wind_dirs)
        avg_wind_deg = int((math.degrees(math.atan2(sin_sum, cos_sum)) + 360) % 360)
        from weather_sources import _deg_to_dir
        avg_wind_dir = _deg_to_dir(avg_wind_deg)
    else:
        avg_wind_deg = 0
        avg_wind_dir = "未知"

    # 天气状况：取出现次数最多的
    from collections import Counter
    weather_counter = Counter(weather_texts)
    main_weather = weather_counter.most_common(1)[0][0] if weather_texts else "未知"

    # 预报融合：按日期聚合各源预报
    forecast_by_date = {}
    for s in ok_sources:
        for day in s["forecast"]:
            date = day["date"]
            if date not in forecast_by_date:
                forecast_by_date[date] = {
                    "temp_max": [], "temp_min": [],
                    "precip": [], "precip_prob": [],
                    "wind": [], "weather_texts": []
                }
            forecast_by_date[date]["temp_max"].append(day["temp_max"])
            forecast_by_date[date]["temp_min"].append(day["temp_min"])
            forecast_by_date[date]["precip"].append(day["precipitation"])
            forecast_by_date[date]["precip_prob"].append(day["precipitation_prob"])
            forecast_by_date[date]["wind"].append(day["wind_speed"])
            forecast_by_date[date]["weather_texts"].append(day["weather_text"])

    fused_forecast = []
    for date in sorted(forecast_by_date.keys())[:7]:
        d = forecast_by_date[date]
        day_weather = Counter(d["weather_texts"]).most_common(1)[0][0] if d["weather_texts"] else "未知"
        fused_forecast.append({
            "date": date,
            "temp_max": round(statistics.mean(d["temp_max"]), 1) if d["temp_max"] else 0,
            "temp_min": round(statistics.mean(d["temp_min"]), 1) if d["temp_min"] else 0,
            "weather_text": day_weather,
            "precipitation": round(statistics.mean(d["precip"]), 1) if d["precip"] else 0,
            "precipitation_prob": round(statistics.mean(d["precip_prob"])) if d["precip_prob"] else 0,
            "wind_speed": round(statistics.mean(d["wind"]), 1) if d["wind"] else 0,
        })

    # 计算置信度
    if len(ok_sources) >= 3:
        confidence = "high"
    elif len(ok_sources) >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    # 计算源间差异
    temp_spread = round(max(temps) - min(temps), 1) if temps else 0

    # 生成统计模式的分析文本
    analysis = _generate_statistical_analysis(
        main_weather, avg_temp, avg_feels, avg_humidity, avg_wind,
        avg_wind_dir, len(ok_sources), temp_spread, fused_forecast
    )

    recommendations = _generate_recommendations(
        main_weather, avg_temp, avg_feels, avg_humidity, avg_wind, fused_forecast
    )

    return {
        "summary": f"{main_weather}，气温 {avg_temp}°C（体感 {avg_feels}°C），湿度 {avg_humidity}%，{avg_wind_dir}风 {avg_wind}m/s",
        "temperature": {"value": avg_temp, "confidence": confidence},
        "feels_like": avg_feels,
        "humidity": avg_humidity,
        "wind": {"speed": avg_wind, "direction": avg_wind_dir, "deg": avg_wind_deg},
        "pressure": avg_pressure,
        "precipitation": {
            "probability": fused_forecast[0]["precipitation_prob"] if fused_forecast else 0,
            "amount": fused_forecast[0]["precipitation"] if fused_forecast else 0,
        },
        "weather_text": main_weather,
        "forecast_7day": fused_forecast,
        "source_count": len(ok_sources),
        "temp_spread": temp_spread,
        "analysis": analysis,
        "recommendations": recommendations,
    }


def _generate_statistical_analysis(weather, temp, feels, humidity, wind, wind_dir,
                                    source_count, temp_spread, forecast):
    """统计模式下生成分析文本"""
    lines = []
    lines.append(f"【多源数据融合分析】共 {source_count} 个数据源成功返回数据。")

    if temp_spread <= 1:
        lines.append(f"各源温度一致性高（差异仅 {temp_spread}°C），预测可信度高。")
    elif temp_spread <= 3:
        lines.append(f"各源温度存在轻微差异（{temp_spread}°C），属正常范围。")
    else:
        lines.append(f"各源温度差异较大（{temp_spread}°C），建议关注后续变化。")

    # 温度趋势分析
    if len(forecast) >= 3:
        temps = [f["temp_max"] for f in forecast[:3]]
        if temps[-1] > temps[0] + 2:
            lines.append("未来3天气温呈上升趋势，注意防暑降温。")
        elif temps[-1] < temps[0] - 2:
            lines.append("未来3天气温呈下降趋势，注意添衣保暖。")
        else:
            lines.append("未来3天气温相对平稳。")

    # 降水分析
    rain_days = [f for f in forecast if f["precipitation_prob"] >= 50]
    if rain_days:
        dates = ", ".join(f["date"][5:] for f in rain_days)
        lines.append(f"未来7天中 {len(rain_days)} 天降水概率较高（{dates}），建议备伞。")
    else:
        lines.append("未来7天无明显降水，天气较为干燥。")

    # 湿度分析
    if humidity >= 80:
        lines.append(f"当前湿度较高（{humidity}%），体感可能偏闷热。")
    elif humidity <= 30:
        lines.append(f"当前湿度较低（{humidity}%），注意补水保湿。")

    # 风力分析
    if wind >= 10:
        lines.append(f"当前风力较大（{wind}m/s，{wind_dir}风），户外活动需注意。")

    return "\n".join(lines)


def _generate_recommendations(weather, temp, feels, humidity, wind, forecast):
    """生成生活建议"""
    recs = []

    # 穿衣建议
    if feels >= 30:
        recs.append("🌡️ 天气炎热，建议穿轻薄透气衣物，注意防暑。")
    elif feels >= 22:
        recs.append("👕 气温适宜，短袖单衣即可。")
    elif feels >= 15:
        recs.append("🧥 微凉，建议薄外套或长袖。")
    elif feels >= 5:
        recs.append("🧣 较冷，建议穿厚外套或毛衣。")
    else:
        recs.append("🧤 寒冷，需穿羽绒服等保暖衣物。")

    # 雨具建议
    rain_prob = forecast[0]["precipitation_prob"] if forecast else 0
    if rain_prob >= 50:
        recs.append("☔ 降水概率高，外出请带伞。")
    elif rain_prob >= 30:
        recs.append("🌂 有一定降水可能，建议备伞。")

    # 紫外线/户外
    if "晴" in weather and temp >= 20:
        recs.append("🧴 天气晴好，户外注意防晒。")

    # 运动
    if wind < 5 and "雨" not in weather and "雪" not in weather and 10 <= temp <= 28:
        recs.append("🏃 天气适合户外运动。")

    # 通风
    if humidity >= 70 and temp >= 25:
        recs.append("💨 湿度偏高，建议开窗通风或使用除湿。")

    if not recs:
        recs.append("🌤️ 天气状况良好，适合日常出行。")

    return recs


def _build_source_comparison(ok_sources):
    """构建各源数据对比"""
    comparison = {}
    for s in ok_sources:
        cur = s["current"]
        if cur:
            comparison[s["source"]] = {
                "temperature": cur["temperature"],
                "feels_like": cur["feels_like"],
                "humidity": cur["humidity"],
                "wind_speed": cur["wind_speed"],
                "weather_text": cur["weather_text"],
            }
    return comparison


def _ai_analyze(ok_sources, fused, city_name):
    """调用 AI 大模型分析多源天气数据"""
    from openai import OpenAI

    client = OpenAI(api_key=config.AI_API_KEY, base_url=config.AI_BASE_URL)

    # 构建各源数据摘要
    sources_summary = []
    for s in ok_sources:
        cur = s["current"]
        if cur:
            sources_summary.append(
                f"- {s['source']}: {cur['weather_text']}, "
                f"气温 {cur['temperature']}°C (体感 {cur['feels_like']}°C), "
                f"湿度 {cur['humidity']}%, "
                f"风速 {cur['wind_speed']}m/s ({cur['wind_direction']}), "
                f"气压 {cur['pressure']}hPa"
            )

    # 构建预报摘要
    forecast_summary = []
    for day in fused["forecast_7day"][:7]:
        forecast_summary.append(
            f"- {day['date']}: {day['weather_text']}, "
            f"{day['temp_min']}~{day['temp_max']}°C, "
            f"降水概率 {day['precipitation_prob']}%, "
            f"降水量 {day['precipitation']}mm"
        )

    prompt = f"""你是一位专业气象分析师。请基于以下来自多个天气平台的实时数据，进行综合分析并给出准确的天气预测。

## 城市信息
城市: {city_name or "未知"}
数据源数量: {len(ok_sources)}

## 各数据源当前天气
{chr(10).join(sources_summary)}

## 统计融合结果（仅供参考）
{fused['summary']}
各源温度差异: {fused['temp_spread']}°C

## 未来7天融合预报
{chr(10).join(forecast_summary)}

## 任务
请分析各数据源的异同，给出融合预测，并回答以下内容。严格按照 JSON 格式输出，不要输出其他内容。

{{
    "summary": "一句话概括当前和近期天气状况（50字以内）",
    "analysis": "详细分析：包括各源数据一致性评估、温度趋势、降水预测、需要注意的天气变化等（200-400字）",
    "recommendations": ["生活建议1", "生活建议2", "生活建议3"],
    "confidence": "high/medium/low - 预测置信度评估"
}}

注意：
- analysis 中要指出各数据源的差异和可能原因
- recommendations 要具体实用，包含穿衣、出行、健康等
- 如果各源数据差异大，confidence 应为 medium 或 low
"""

    response = client.chat.completions.create(
        model=config.AI_MODEL,
        messages=[
            {"role": "system", "content": "你是一位专业气象分析师，擅长多源气象数据融合分析。请只输出 JSON 格式的内容。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=1000,
    )

    content = response.choices[0].message.content.strip()

    # 尝试解析 JSON
    # 移除可能的 markdown 代码块标记
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content
        content = content.rsplit("```", 1)[0] if "```" in content else content
        content = content.strip()

    try:
        result = json.loads(content)
        return result
    except json.JSONDecodeError:
        # 如果 JSON 解析失败，返回原始文本作为分析
        return {
            "summary": fused["summary"],
            "analysis": content,
            "recommendations": [],
            "confidence": "medium",
        }
