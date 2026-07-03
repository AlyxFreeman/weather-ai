/* ===== AI天气预测平台 - 前端逻辑 ===== */
/* global L */

// 全局状态
let forecastChart = null;
let travelChart = null;
let searchTimer = null;
let travelMap = null;
let routeControl = null;
let routePoints = [];       // 路线坐标点 [{lat, lng}, ...]
let routeWeatherData = [];  // 沿途天气数据
let routeWaypoints = [];    // 途径点 [{lat, lng, marker}, ...]
let startMarker = null;     // 起点标记
let endMarker = null;       // 终点标记
let selectingPoint = 'start'; // 当前选择：start / end
let addingWaypoint = false; // 是否正在添加途径点
let travelMapInitialized = false;  // 地图是否已初始化

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', () => {
    createParticles();
    loadSourceStatus();
    bindEvents();
    // 地图延迟到用户切换到旅行规划标签页时再初始化
    // 原因：hidden 容器里 Leaflet 无法正确计算尺寸
});

// ===== 背景粒子 =====
function createParticles() {
    const container = document.getElementById('particles');
    for (let i = 0; i < 15; i++) {
        const p = document.createElement('div');
        p.className = 'particle';
        p.style.width = Math.random() * 6 + 4 + 'px';
        p.style.height = p.style.width;
        p.style.left = Math.random() * 100 + '%';
        p.style.top = Math.random() * 100 + '%';
        p.style.animationDelay = Math.random() * 20 + 's';
        p.style.animationDuration = (Math.random() * 10 + 15) + 's';
        container.appendChild(p);
    }
}

// ===== 加载数据源状态 =====
async function loadSourceStatus() {
    try {
        const resp = await fetch('/api/sources');
        const data = await resp.json();
        const container = document.getElementById('sourceBadges');
        container.innerHTML = data.weather_sources.map(s => {
            const isActive = s.status === 'active';
            const title = s.desc ? ` title="${s.name} (${s.desc})"` : '';
            return `<span class="source-badge ${isActive ? 'active' : 'inactive'}"${title}>
                ${isActive ? '✅' : '⚪'} ${s.name}
            </span>`;
        }).join('');
    } catch (e) {
        console.error('加载数据源状态失败:', e);
    }
}

// ===== 事件绑定 =====
function bindEvents() {
    // 标签页切换
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            switchTab(tab);
        });
    });

    const input = document.getElementById('cityInput');

    // 搜索输入（防抖）
    input.addEventListener('input', (e) => {
        clearTimeout(searchTimer);
        const q = e.target.value.trim();
        if (q.length < 1) {
            hideSearchResults();
            return;
        }
        searchTimer = setTimeout(() => searchCities(q), 300);
    });

    // 点击外部关闭搜索结果
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.search-box')) {
            hideSearchResults();
        }
    });

    // 快速城市选择
    document.querySelectorAll('.city-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            const city = chip.dataset.city;
            const lat = parseFloat(chip.dataset.lat);
            const lon = parseFloat(chip.dataset.lon);
            fetchWeather(city, lat, lon);
        });
    });

    // 回车搜索
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const q = input.value.trim();
            if (q) searchCities(q, true);
        }
    });

    // 旅行规划 - 规划路线按钮
    const planBtn = document.getElementById('planRouteBtn');
    if (planBtn) {
        planBtn.addEventListener('click', () => planRoute());
    }

    // 旅行规划 - 清除路线按钮
    const clearBtn = document.getElementById('clearRouteBtn');
    if (clearBtn) {
        clearBtn.addEventListener('click', () => clearRoute());
    }

    // 旅行规划 - 添加途径点按钮
    const addWpBtn = document.getElementById('addWaypointBtn');
    if (addWpBtn) {
        addWpBtn.addEventListener('click', () => addWaypoint());
    }
}

// ===== 标签页切换 =====
function switchTab(tabName) {
    // 更新按钮状态
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelector(`.tab-btn[data-tab="${tabName}"]`).classList.add('active');

    // 更新内容显示
    document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
    const tabEl = document.getElementById(`tab-${tabName}`);
    tabEl.style.display = 'block';

    // 如果是旅行规划标签，初始化地图
    // 关键：必须等浏览器完成 reflow 后容器才有尺寸
    if (tabName === 'travel-plan') {
        if (!travelMapInitialized) {
            // 等两帧，确保浏览器已完成布局计算
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    const mapEl = document.getElementById('travelMap');
                    if (mapEl && mapEl.offsetHeight === 0) {
                        console.warn('地图容器高度为0，延迟初始化...');
                        setTimeout(() => initTravelMap(), 300);
                    } else {
                        initTravelMap();
                    }
                    travelMapInitialized = true;
                });
            });
        } else if (travelMap) {
            travelMap.invalidateSize();
        }
    }
}

// ===== 城市搜索 =====
async function searchCities(q, autoSelect = false) {
    try {
        const resp = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
        const data = await resp.json();

        if (autoSelect && data.cities && data.cities.length > 0) {
            const c = data.cities[0];
            fetchWeather(c.name, c.lat, c.lon);
            document.getElementById('cityInput').value = c.name;
            hideSearchResults();
            return;
        }

        showSearchResults(data.cities || []);
    } catch (e) {
        console.error('搜索失败:', e);
    }
}

function showSearchResults(cities) {
    const container = document.getElementById('searchResults');
    if (cities.length === 0) {
        container.innerHTML = '<div class="search-result-item"><span class="city-region">未找到匹配城市</span></div>';
    } else {
        container.innerHTML = cities.map(c => `
            <div class="search-result-item" data-lat="${c.lat}" data-lon="${c.lon}" data-name="${c.name}">
                <span class="city-name">${c.name}</span>
                <span class="city-region">${c.admin || ''} ${c.country || ''}</span>
            </div>
        `).join('');

        container.querySelectorAll('.search-result-item').forEach(item => {
            item.addEventListener('click', () => {
                const name = item.dataset.name;
                const lat = parseFloat(item.dataset.lat);
                const lon = parseFloat(item.dataset.lon);
                document.getElementById('cityInput').value = name;
                hideSearchResults();
                fetchWeather(name, lat, lon);
            });
        });
    }
    container.classList.add('show');
}

function hideSearchResults() {
    document.getElementById('searchResults').classList.remove('show');
}

// ===== 获取天气数据 =====
async function fetchWeather(city, lat, lon) {
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('weatherContent').style.display = 'none';
    document.getElementById('loading').style.display = 'block';

    try {
        const resp = await fetch(`/api/weather?lat=${lat}&lon=${lon}&city=${encodeURIComponent(city)}`);
        const data = await resp.json();

        document.getElementById('loading').style.display = 'none';

        if (data.error) {
            alert(data.error);
            document.getElementById('emptyState').style.display = 'block';
            return;
        }

        renderWeather(data);
        document.getElementById('weatherContent').style.display = 'block';
    } catch (e) {
        document.getElementById('loading').style.display = 'none';
        console.error('获取天气失败:', e);
        alert('获取天气数据失败，请检查网络连接');
        document.getElementById('emptyState').style.display = 'block';
    }
}

// ===== 渲染天气数据 =====
function renderWeather(data) {
    const pred = data.prediction;

    // 模式标签
    const modeBadge = document.getElementById('modeBadge');
    if (pred.mode === 'ai') {
        modeBadge.textContent = '🤖 AI大模型分析';
        modeBadge.classList.add('ai');
    } else {
        modeBadge.textContent = '📊 统计融合';
        modeBadge.classList.remove('ai');
    }

    // 主面板数据
    const weatherEmoji = getWeatherEmoji(pred.weather_text);
    document.getElementById('mainEmoji').textContent = weatherEmoji;
    document.getElementById('mainTemp').textContent = pred.temperature ? pred.temperature.value : '--';
    document.getElementById('mainWeather').textContent = pred.weather_text || '--';
    document.getElementById('feelsLike').textContent = pred.feels_like ?? '--';
    document.getElementById('mainHumidity').textContent = pred.humidity + '%';
    document.getElementById('mainWind').textContent = pred.wind.speed + ' m/s';
    document.getElementById('mainWindDir').textContent = pred.wind.direction;
    document.getElementById('mainPrecip').textContent = pred.precipitation.probability + '%';
    document.getElementById('sourceCount').textContent = `${data.ok_count}/${data.total_count}`;

    // 置信度
    const confidenceMap = { high: '高 ✅', medium: '中 ⚠️', low: '低 ❓' };
    const confVal = pred.ai_confidence || (pred.temperature ? pred.temperature.confidence : 'medium');
    document.getElementById('confidence').textContent = confidenceMap[confVal] || confVal;

    // AI摘要
    document.getElementById('aiSummary').textContent = pred.summary || '';

    // 分析文本
    let analysisText = '';
    if (pred.mode === 'ai' && pred.ai_analysis) {
        analysisText = pred.ai_analysis;
    } else if (pred.analysis) {
        analysisText = pred.analysis;
    }
    document.getElementById('analysisText').textContent = analysisText || '暂无分析数据';

    // 生活建议
    const recs = (pred.mode === 'ai' && pred.ai_recommendations && pred.ai_recommendations.length > 0)
        ? pred.ai_recommendations
        : (pred.recommendations || []);
    const recList = document.getElementById('recList');
    if (recs.length > 0) {
        recList.innerHTML = recs.map(r => `<div class="rec-item">${r}</div>`).join('');
    } else {
        recList.innerHTML = '<div class="rec-item">暂无建议</div>';
    }

    // 7天预报图表
    renderForecastChart(pred.forecast_7day || []);

    // 7天预报卡片
    renderForecastCards(pred.forecast_7day || []);

    // 多源对比
    renderSourcesComparison(data.sources || []);
}

// ===== 渲染7天预报图表 =====
function renderForecastChart(forecast) {
    const ctx = document.getElementById('forecastChart').getContext('2d');

    if (forecastChart) {
        forecastChart.destroy();
    }

    const labels = forecast.map(f => {
        const d = new Date(f.date);
        return `${d.getMonth() + 1}/${d.getDate()}`;
    });

    const maxTemps = forecast.map(f => f.temp_max);
    const minTemps = forecast.map(f => f.temp_min);
    const precipProb = forecast.map(f => f.precipitation_prob);

    forecastChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    type: 'line',
                    label: '最高温 (°C)',
                    data: maxTemps,
                    borderColor: '#e65100',
                    backgroundColor: 'rgba(230, 81, 0, 0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 5,
                    pointBackgroundColor: '#e65100',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    borderWidth: 3,
                    yAxisID: 'y',
                },
                {
                    type: 'line',
                    label: '最低温 (°C)',
                    data: minTemps,
                    borderColor: '#1565c0',
                    backgroundColor: 'rgba(21, 101, 192, 0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 5,
                    pointBackgroundColor: '#1565c0',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    borderWidth: 3,
                    yAxisID: 'y',
                },
                {
                    type: 'bar',
                    label: '降水概率 (%)',
                    data: precipProb,
                    backgroundColor: 'rgba(79, 124, 254, 0.2)',
                    borderColor: 'rgba(79, 124, 254, 0.5)',
                    borderWidth: 1,
                    borderRadius: 6,
                    yAxisID: 'y1',
                    barThickness: 20,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    position: 'top',
                    labels: { font: { size: 13 }, usePointStyle: true, padding: 16 },
                },
                tooltip: {
                    backgroundColor: 'rgba(26, 26, 46, 0.9)',
                    padding: 12,
                    borderRadius: 8,
                    titleFont: { size: 14 },
                    bodyFont: { size: 13 },
                },
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { font: { size: 12 } },
                },
                y: {
                    type: 'linear',
                    position: 'left',
                    title: { display: true, text: '温度 (°C)', font: { size: 12 } },
                    grid: { color: 'rgba(0,0,0,0.05)' },
                },
                y1: {
                    type: 'linear',
                    position: 'right',
                    title: { display: true, text: '降水概率 (%)', font: { size: 12 } },
                    min: 0, max: 100,
                    grid: { display: false },
                },
            },
        },
    });
}

// ===== 渲染7天预报卡片 =====
function renderForecastCards(forecast) {
    const container = document.getElementById('forecastCards');
    const today = new Date().toISOString().slice(0, 10);

    container.innerHTML = forecast.map(f => {
        const d = new Date(f.date);
        const isToday = f.date === today;
        const dayLabel = isToday ? '今天' :
            ['周日','周一','周二','周三','周四','周五','周六'][d.getDay()];
        const dateLabel = `${d.getMonth() + 1}/${d.getDate()}`;

        return `
            <div class="forecast-card">
                <div class="fc-date">${dayLabel} ${dateLabel}</div>
                <div class="fc-emoji">${getWeatherEmoji(f.weather_text)}</div>
                <div class="fc-weather">${f.weather_text}</div>
                <div class="fc-temps">
                    <span class="fc-max">${f.temp_max}°</span>
                    <span class="fc-min">${f.temp_min}°</span>
                </div>
                ${f.precipitation_prob > 0 ? `<div class="fc-precip">💧${f.precipitation_prob}%</div>` : ''}
            </div>
        `;
    }).join('');
}

// ===== 渲染多源对比 =====
function renderSourcesComparison(sources) {
    const container = document.getElementById('sourcesGrid');

    container.innerHTML = sources.map(s => {
        if (s.status === 'error') {
            return `
                <div class="source-card error">
                    <div class="source-card-header">
                        <span class="source-card-name">${s.source}</span>
                        <span class="source-card-status error">不可用</span>
                    </div>
                    <div class="source-error-msg">⚠️ ${s.error}</div>
                </div>
            `;
        }

        const cur = s.current;
        return `
            <div class="source-card">
                <div class="source-card-header">
                    <span class="source-card-name">${s.source}</span>
                    <span class="source-card-status ok">正常</span>
                </div>
                <div class="scd-emoji">${cur.weather_emoji || getWeatherEmoji(cur.weather_text)}</div>
                <div class="source-card-data">
                    <div class="scd-item">
                        <span class="scd-label">温度</span>
                        <span class="scd-value">${cur.temperature}°C</span>
                    </div>
                    <div class="scd-item">
                        <span class="scd-label">体感</span>
                        <span class="scd-value">${cur.feels_like}°C</span>
                    </div>
                    <div class="scd-item">
                        <span class="scd-label">湿度</span>
                        <span class="scd-value">${cur.humidity}%</span>
                    </div>
                    <div class="scd-item">
                        <span class="scd-label">风速</span>
                        <span class="scd-value">${cur.wind_speed} m/s</span>
                    </div>
                    <div class="scd-item">
                        <span class="scd-label">天气</span>
                        <span class="scd-value">${cur.weather_text}</span>
                    </div>
                    <div class="scd-item">
                        <span class="scd-label">气压</span>
                        <span class="scd-value">${cur.pressure || '--'} hPa</span>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// ===== 天气文本 → emoji =====
function getWeatherEmoji(text) {
    if (!text) return '🌤️';
    if (text.includes('晴')) return '☀️';
    if (text.includes('多云')) return '⛅';
    if (text.includes('阴')) return '☁️';
    if (text.includes('雷')) return '⛈️';
    if (text.includes('大雨') || text.includes('暴雨')) return '🌧️';
    if (text.includes('中雨')) return '🌧️';
    if (text.includes('小雨') || text.includes('阵雨')) return '🌦️';
    if (text.includes('毛毛雨') || text.includes('drizzle')) return '🌦️';
    if (text.includes('雪') || text.includes('Snow') || text.includes('snow')) return '❄️';
    if (text.includes('雾') || text.includes('Fog') || text.includes('fog')) return '🌫️';
    if (text.includes('Clear') || text.includes('clear')) return '☀️';
    if (text.includes('Cloud') || text.includes('cloud')) return '☁️';
    if (text.includes('Rain') || text.includes('rain')) return '🌧️';
    return '🌤️';
}

// ============================================================
// ===== 旅行规划功能 =====
// ============================================================

// ===== 初始化旅行地图 =====
function initTravelMap() {
    const mapEl = document.getElementById('travelMap');
    if (!mapEl) {
        console.error('地图容器 #travelMap 未找到');
        return;
    }

    // 检查容器是否有尺寸（必须在可见容器中初始化）
    const rect = mapEl.getBoundingClientRect();
    if (rect.height === 0 || rect.width === 0) {
        console.warn(`地图容器尺寸为0 (${rect.width}x${rect.height})，延迟重试...`);
        setTimeout(() => initTravelMap(), 200);
        return;
    }

    if (typeof L === 'undefined') {
        console.error('Leaflet 库未加载');
        mapEl.innerHTML = '<div style="display:flex;height:100%;align-items:center;justify-content:center;color:#e53935;font-size:14px;">地图库加载失败，请刷新页面</div>';
        return;
    }

    // 如果已初始化，跳过
    if (travelMap) {
        travelMap.invalidateSize();
        return;
    }

    try {
        console.log(`开始初始化地图，容器尺寸: ${rect.width}x${rect.height}`);
        travelMap = L.map('travelMap', {
            center: [35.86, 104.2],
            zoom: 5,
            zoomControl: true,
        });

        // OpenStreetMap 瓦片图层（免费）
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            maxZoom: 18,
        }).addTo(travelMap);

        console.log('地图瓦片图层已添加');

        // 点击地图选点
        travelMap.on('click', (e) => {
            handleMapClick(e.latlng);
        });

        // 立即触发布局重算
        setTimeout(() => {
            travelMap.invalidateSize();
            console.log('地图初始化完成');
        }, 100);
    } catch (err) {
        console.error('地图初始化失败:', err);
        mapEl.innerHTML = `<div style="display:flex;height:100%;align-items:center;justify-content:center;color:#e53935;font-size:14px;padding:20px;text-align:center;">地图初始化失败: ${err.message}</div>`;
    }
}

// 起点/终点标记
// 已在全局状态区声明：startMarker, endMarker, selectingPoint, addingWaypoint

function handleMapClick(latlng) {
    const { lat, lng } = latlng;

    // 如果正在添加途径点，先处理
    if (addingWaypoint) {
        handleWaypointClick(lat, lng);
        return;
    }

    if (selectingPoint === 'start') {
        // 设置起点
        if (startMarker) travelMap.removeLayer(startMarker);
        startMarker = L.marker([lat, lng], {
            draggable: true,
            title: '起点',
            icon: L.divIcon({
                className: 'route-marker start-marker',
                html: '🟢',
                iconSize: [28, 28],
                iconAnchor: [14, 14],
            }),
        }).addTo(travelMap);
        startMarker.on('dragend', (e) => {
            const pos = e.target.getLatLng();
            document.getElementById('startInput').value = `${pos.lat.toFixed(4)}, ${pos.lng.toFixed(4)}`;
        });
        document.getElementById('startInput').value = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
        selectingPoint = 'end';
        showMapHint('✅ 起点已选择，请在地图上点击选择终点');
    } else {
        // 设置终点
        if (endMarker) travelMap.removeLayer(endMarker);
        endMarker = L.marker([lat, lng], {
            draggable: true,
            title: '终点',
            icon: L.divIcon({
                className: 'route-marker end-marker',
                html: '🔴',
                iconSize: [28, 28],
                iconAnchor: [14, 14],
            }),
        }).addTo(travelMap);
        endMarker.on('dragend', (e) => {
            const pos = e.target.getLatLng();
            document.getElementById('endInput').value = `${pos.lat.toFixed(4)}, ${pos.lng.toFixed(4)}`;
        });
        document.getElementById('endInput').value = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
        selectingPoint = 'start';
        showMapHint('✅ 终点已选择，点击"规划路线"开始分析');
    }
}

function showMapHint(msg) {
    // 在地图控制面板顶部显示提示
    const controls = document.querySelector('.map-controls');
    let hint = document.getElementById('mapHint');
    if (!hint) {
        hint = document.createElement('div');
        hint.id = 'mapHint';
        hint.style.cssText = 'font-size:12px;color:var(--accent);padding:6px 0;line-height:1.4;';
        controls.insertBefore(hint, controls.firstChild);
    }
    hint.textContent = msg;
    setTimeout(() => { if (hint) hint.remove(); }, 5000);
}

// ===== 规划路线 =====
async function planRoute() {
    const startVal = document.getElementById('startInput').value.trim();
    const endVal = document.getElementById('endInput').value.trim();
    const mode = document.getElementById('travelMode').value;

    if (!startVal || !endVal) {
        alert('请在地图上点击选择起点和终点，或手动输入坐标');
        return;
    }

    // 解析坐标
    let startLat, startLng, endLat, endLng;
    const coordRegex = /^(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)$/;

    const startMatch = startVal.match(coordRegex);
    const endMatch = endVal.match(coordRegex);

    if (startMatch) {
        startLat = parseFloat(startMatch[1]);
        startLng = parseFloat(startMatch[2]);
    } else {
        // 尝试地理编码
        const result = await geocode(startVal);
        if (!result) { alert('无法解析起点地址，请点击地图选择'); return; }
        startLat = result.lat;
        startLng = result.lon;
        document.getElementById('startInput').value = `${startLat}, ${startLng}`;
    }

    if (endMatch) {
        endLat = parseFloat(endMatch[1]);
        endLng = parseFloat(endMatch[2]);
    } else {
        const result = await geocode(endVal);
        if (!result) { alert('无法解析终点地址，请点击地图选择'); return; }
        endLat = result.lat;
        endLng = result.lon;
        document.getElementById('endInput').value = `${endLat}, ${endLng}`;
    }

    // 显示加载状态
    document.getElementById('travelEmpty').style.display = 'none';
    document.getElementById('travelContent').style.display = 'none';
    document.getElementById('travelLoading').style.display = 'block';

    try {
        // 获取出发时间
        const departureTime = document.getElementById('departureTime').value;

        // 获取途径点
        const waypoints = routeWaypoints.map(wp => ({ lat: wp.lat, lng: wp.lng }));

        // 调用后端路线规划 API
        const resp = await fetch('/api/route-weather', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                start_lat: startLat,
                start_lng: startLng,
                end_lat: endLat,
                end_lng: endLng,
                mode: mode,
                departure_time: departureTime,
                waypoints: waypoints,
            }),
        });

        const data = await resp.json();

        document.getElementById('travelLoading').style.display = 'none';

        if (data.error) {
            alert(`路线规划失败：${data.error}`);
            document.getElementById('travelEmpty').style.display = 'block';
            return;
        }

        // 渲染结果
        renderRouteResult(data);
        document.getElementById('travelContent').style.display = 'block';

        // 在地图上绘制路线
        drawRouteOnMap(data.route_geometry, data.sample_points);

    } catch (e) {
        document.getElementById('travelLoading').style.display = 'none';
        console.error('路线规划失败:', e);
        alert('路线规划失败，请检查网络连接');
        document.getElementById('travelEmpty').style.display = 'block';
    }
}

// ===== 地理编码（地址 → 坐标）=====
async function geocode(query) {
    try {
        const resp = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=1`);
        const data = await resp.json();
        if (data && data.length > 0) {
            return {
                lat: parseFloat(data[0].lat),
                lon: parseFloat(data[0].lon),
                name: data[0].display_name,
            };
        }
    } catch (e) {
        console.error('地理编码失败:', e);
    }
    return null;
}

// ===== 在地图上绘制路线 =====
function drawRouteOnMap(geometry, samplePoints) {
    // 清除旧路线
    if (routeControl) {
        travelMap.removeControl(routeControl);
        routeControl = null;
    }

    // 绘制路线（使用 Leaflet Routing Machine 或直接绘制 Polyline）
    if (geometry && geometry.coordinates) {
        // OSRM 返回的是 GeoJSON LineString
        const coords = geometry.coordinates.map(c => [c[1], c[0]]);  // 转 [lat, lng]
        const polyline = L.polyline(coords, {
            color: '#4f7cfe',
            weight: 5,
            opacity: 0.8,
        }).addTo(travelMap);

        // 调整地图视野
        travelMap.fitBounds(polyline.getBounds(), { padding: [50, 50] });

        // 保存路线点
        routePoints = coords;
    }

    // 绘制采样点
    if (samplePoints && samplePoints.length > 0) {
        samplePoints.forEach((pt, idx) => {
            const marker = L.marker([pt.lat, pt.lon], {
                icon: L.divIcon({
                    className: 'sample-marker',
                    html: `<div style="background:white;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;border:2px solid #4f7cfe;font-size:11px;font-weight:600;color:#4f7cfe;">${idx + 1}</div>`,
                    iconSize: [28, 28],
                    iconAnchor: [14, 14],
                }),
            }).addTo(travelMap);

            // 弹出天气信息
            if (pt.weather) {
                const w = pt.weather;
                const elevStr = pt.elevation != null ? ` | ⛰️${pt.elevation}m` : '';
                marker.bindPopup(`
                    <div class="weather-popup">
                        <div class="wp-emoji">${getWeatherEmoji(w.weather_text)}</div>
                        <div class="wp-temp">${w.temperature}°C</div>
                        <div class="wp-weather">${w.weather_text}</div>
                        <div class="wp-details">💧${w.humidity}% | 💨${w.wind_speed}m/s${elevStr}</div>
                    </div>
                `);
            }
        });
    }
}

// ===== 渲染路线分析结果 =====
function renderRouteResult(data) {
    // 路线基本信息
    document.getElementById('routeInfo').style.display = 'block';
    document.getElementById('routeDistance').textContent = `${data.distance_km} km`;
    document.getElementById('routeDuration').textContent = data.duration_text;
    document.getElementById('routeSampleCount').textContent = `${data.sample_count} 个`;

    const tempSpread = data.temp_spread || 0;
    document.getElementById('routeTempSpread').textContent = tempSpread > 0 ? `±${tempSpread}°C` : '--';

    // AI 沿途分析
    if (data.ai_analysis) {
        document.getElementById('travelAnalysisPanel').style.display = 'block';
        document.getElementById('travelAnalysisText').textContent = data.ai_analysis;
    } else {
        document.getElementById('travelAnalysisPanel').style.display = 'none';
    }

    // 旅行建议
    const recs = data.recommendations || [];
    const recContainer = document.getElementById('travelRecs');
    if (recs.length > 0) {
        recContainer.innerHTML = recs.map(r => `<div class="travel-rec-item">${r}</div>`).join('');
    }

    // 采样点卡片
    if (data.sample_points && data.sample_points.length > 0) {
        document.getElementById('travelSamplesSection').style.display = 'block';
        renderSampleCards(data.sample_points);
    }

    // 沿途天气趋势图
    if (data.sample_points && data.sample_points.length > 1) {
        document.getElementById('travelChartSection').style.display = 'block';
        renderTravelChart(data.sample_points);
    }
}

// ===== 渲染采样点卡片 =====
function renderSampleCards(samples) {
    const container = document.getElementById('travelSamplesGrid');
    container.innerHTML = samples.map((pt, idx) => {
        const w = pt.weather;
        if (!w) return '';
        const isWarning = w.weather_text && (
            w.weather_text.includes('雨') ||
            w.weather_text.includes('雪') ||
            w.weather_text.includes('雷') ||
            w.wind_speed > 15
        );
        const isForecast = w.is_forecast || false;
        const elev = pt.elevation;
        const elevStr = elev != null ? ` | ⛰️${elev}m` : '';
        return `
            <div class="travel-sample-card ${isWarning ? 'highlight' : ''}" data-idx="${idx}">
                <div class="tsc-distance">距起点 ${pt.distance_km} km${isForecast ? ' <span style="color:#4f7cfe;font-size:11px;">(预报)</span>' : ''}</div>
                <div class="tsc-emoji">${getWeatherEmoji(w.weather_text)}</div>
                <div class="tsc-weather">${w.weather_text}</div>
                <div class="tsc-temp">${w.temperature}°C</div>
                <div class="tsc-details">
                    💧${w.humidity}% | 💨${w.wind_speed}m/s<br>
                    降水${w.precipitation_prob}%${elevStr}
                </div>
            </div>
        `;
    }).join('');

    // 点击卡片高亮对应地图点
    container.querySelectorAll('.travel-sample-card').forEach(card => {
        card.addEventListener('click', () => {
            const idx = parseInt(card.dataset.idx);
            // 可以扩展：pan to marker, open popup
        });
    });
}

// ===== 渲染沿途天气趋势图 =====
function renderTravelChart(samples) {
    const ctx = document.getElementById('travelChart').getContext('2d');

    if (travelChart) {
        travelChart.destroy();
    }

    const labels = samples.map((pt, idx) => `${pt.distance_km}km`);
    const temps = samples.map(pt => pt.weather ? pt.weather.temperature : null);
    const precipProb = samples.map(pt => pt.weather ? pt.weather.precipitation_prob : null);
    const elevations = samples.map(pt => pt.elevation != null ? pt.elevation : null);

    // 判断是否有有效海拔数据
    const hasElevation = elevations.some(v => v !== null);

    const datasets = [
        {
            label: '温度 (°C)',
            data: temps,
            borderColor: '#e65100',
            backgroundColor: 'rgba(230, 81, 0, 0.1)',
            fill: true,
            tension: 0.3,
            pointRadius: 5,
            pointBackgroundColor: '#e65100',
            pointBorderColor: '#fff',
            pointBorderWidth: 2,
            borderWidth: 3,
            yAxisID: 'y',
        },
        {
            type: 'bar',
            label: '降水概率 (%)',
            data: precipProb,
            backgroundColor: 'rgba(79, 124, 254, 0.2)',
            borderColor: 'rgba(79, 124, 254, 0.5)',
            borderWidth: 1,
            borderRadius: 6,
            yAxisID: 'y1',
            barThickness: 16,
        },
    ];

    if (hasElevation) {
        datasets.push({
            label: '海拔 (m)',
            data: elevations,
            borderColor: '#2e7d32',
            backgroundColor: 'rgba(46, 125, 50, 0.08)',
            fill: false,
            tension: 0.3,
            pointRadius: 4,
            pointBackgroundColor: '#2e7d32',
            pointBorderColor: '#fff',
            pointBorderWidth: 1,
            borderWidth: 2,
            borderDash: [6, 4],
            yAxisID: 'y2',
        });
    }

    travelChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: datasets,
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    position: 'top',
                    labels: { font: { size: 13 }, usePointStyle: true, padding: 16 },
                },
                tooltip: {
                    backgroundColor: 'rgba(26, 26, 46, 0.9)',
                    padding: 12,
                    borderRadius: 8,
                    titleFont: { size: 14 },
                    bodyFont: { size: 13 },
                    callbacks: {
                        title: (items) => {
                            const idx = items[0].dataIndex;
                            const elevStr = samples[idx].elevation != null ? `（海拔 ${samples[idx].elevation}m）` : '';
                            return `距起点 ${samples[idx].distance_km} km${elevStr}`;
                        },
                    },
                },
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { font: { size: 11 } },
                    title: { display: true, text: '距起点距离', font: { size: 12 } },
                },
                y: {
                    type: 'linear',
                    position: 'left',
                    title: { display: true, text: '温度 (°C)', font: { size: 12 } },
                    grid: { color: 'rgba(0,0,0,0.05)' },
                },
                y1: {
                    type: 'linear',
                    position: 'right',
                    title: { display: true, text: '降水概率 (%)', font: { size: 12 } },
                    min: 0, max: 100,
                    grid: { display: false },
                },
                ...(hasElevation ? {
                    y2: {
                        type: 'linear',
                        position: 'right',
                        title: { display: true, text: '海拔 (m)', font: { size: 12 } },
                        grid: { display: false },
                        offset: true,
                    },
                } : {}),
            },
        },
    });
}

// ===== 途径点管理 =====
// 已在全局状态区声明：addingWaypoint

function addWaypoint() {
    if (!travelMap) {
        alert('请先初始化地图');
        return;
    }
    addingWaypoint = true;
    showMapHint('请在地图上点击选择途径点位置');
}

function handleWaypointClick(lat, lng) {
    if (!addingWaypoint) return;

    // 添加途径点
    routeWaypoints.push({ lat: lat, lng: lng, marker: null });

    // 在地图上标记途径点
    const marker = L.marker([lat, lng], {
        draggable: true,
        icon: L.divIcon({
            className: 'route-marker waypoint-marker',
            html: `🟡`,
            iconSize: [28, 28],
            iconAnchor: [14, 14],
        }),
    }).addTo(travelMap);

    // 双击删除途径点
    marker.on('dblclick', () => {
        const idx = routeWaypoints.findIndex(wp => wp.marker === marker);
        if (idx >= 0) {
            travelMap.removeLayer(marker);
            routeWaypoints.splice(idx, 1);
            updateWaypointsList();
        }
    });

    routeWaypoints[routeWaypoints.length - 1].marker = marker;

    // 更新途径点列表
    updateWaypointsList();

    addingWaypoint = false;
    showMapHint(`✅ 途径点已添加（共 ${routeWaypoints.length} 个），继续点击"添加途径点"可添加更多，双击标记可删除`);
}

function updateWaypointsList() {
    const container = document.getElementById('waypointsContainer');
    const list = document.getElementById('waypointsList');

    if (!container || !list) return;

    if (routeWaypoints.length === 0) {
        list.style.display = 'none';
        container.innerHTML = '';
        return;
    }

    list.style.display = 'block';
    container.innerHTML = routeWaypoints.map((wp, i) => `
        <div class="waypoint-item" style="display:flex;align-items:center;gap:8px;padding:6px 0;font-size:13px;">
            <span>🟡 途径点${i+1}: ${wp.lat.toFixed(4)}, ${wp.lng.toFixed(4)}</span>
            <button onclick="removeWaypoint(${i})" style="background:none;border:none;color:var(--red);cursor:pointer;font-size:16px;">✕</button>
        </div>
    `).join('');
}

window.removeWaypoint = function(idx) {
    if (routeWaypoints[idx] && routeWaypoints[idx].marker) {
        travelMap.removeLayer(routeWaypoints[idx].marker);
    }
    routeWaypoints.splice(idx, 1);
    updateWaypointsList();
};

// 修改 handleMapClick 函数，支持途径点选择
const originalHandleMapClick = handleMapClick;
handleMapClick = function(latLng) {
    if (addingWaypoint) {
        handleWaypointClick(latLng.lat, latLng.lng);
        return;
    }
    if (originalHandleMapClick) originalHandleMapClick(latLng);
};

// ===== 清除路线 =====
function clearRoute() {
    // 清除地图上所有图层（保留瓦片）
    travelMap.eachLayer(layer => {
        if (layer instanceof L.Marker || layer instanceof L.Polyline) {
            travelMap.removeLayer(layer);
        }
    });

    startMarker = null;
    endMarker = null;
    routePoints = [];
    routeWeatherData = [];

    document.getElementById('startInput').value = '';
    document.getElementById('endInput').value = '';
    document.getElementById('travelContent').style.display = 'none';
    document.getElementById('travelEmpty').style.display = 'block';

    // 重置地图视图
    travelMap.setView([35.86, 104.2], 5);
}
