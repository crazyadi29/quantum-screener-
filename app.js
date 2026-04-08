let currentTrend = "positive";
const loadedCharts = {};

document.addEventListener("DOMContentLoaded", () => {
    initDashboard();
    
    document.getElementById("refresh-sectors").addEventListener("click", () => {
        initDashboard();
    });
});

async function initDashboard() {
    try {
        // 1. Get Market Trend
        const trendRes = await fetch("/api/market-trend");
        const trendData = await trendRes.json();
        currentTrend = trendData.status; // "positive" or "negative"
        
        const statusContainer = document.getElementById("nifty-status-container");
        
        let html = `
            <div class="nifty-status ${trendData.status}">
                <div class="badge ${trendData.status}">NIFTY ${trendData.status.toUpperCase()}</div>
                <div style="font-size: 1.5rem; font-weight: 700; color: #fff;">${trendData.current_price}</div>
                <div style="font-size: 0.85rem; margin-top: 5px;" class="${trendData.change >= 0 ? 'stat-val up' : 'stat-val down'}">
                    ${trendData.change >= 0 ? '+' : ''}${trendData.change}% 
                </div>
            </div>
        `;
        statusContainer.innerHTML = html;

        // 2. Get Sectors
        const sectorsList = document.getElementById("sectors-list");
        sectorsList.innerHTML = `<div class="loading-overlay"><div class="loader"></div><span>Scanning Sectors...</span></div>`;
        
        const secRes = await fetch("/api/sectors");
        let sectorsData = await secRes.json();
        
        // Render sector logic based on Nifty Status
        // If trend is positive => green, display all. If negative -> highlight most/least negative.
        let sectorsHtml = "";
        sectorsData.forEach((sec, idx) => {
            const isPos = sec.change >= 0;
            sectorsHtml += `
                <div class="sector-item" onclick="loadSector('${sec.sector}')">
                    <span class="name">${sec.sector}</span>
                    <span class="val ${isPos ? 'positive' : 'negative'}">${isPos ? '+' : ''}${sec.change}%</span>
                </div>
            `;
        });
        
        sectorsList.innerHTML = sectorsHtml;
        
        // Auto load top sector
        if (sectorsData.length > 0) {
            loadSector(sectorsData[0].sector);
        }

    } catch (e) {
        console.error("Dashboard init error", e);
    }
}

async function loadSector(sectorName) {
    document.getElementById("active-sector-title").innerText = `${sectorName} Breakout Scanner`;
    const container = document.getElementById("stocks-container");
    const loader = document.getElementById("stocks-loader");
    
    // Clear previous
    Array.from(container.children).forEach(c => {
        if (c.id !== "stocks-loader") c.remove();
    });
    
    loader.style.display = "flex";
    
    try {
        const res = await fetch(`/api/stock-analysis?sector=${encodeURIComponent(sectorName)}&trend=${currentTrend}`);
        const stocks = await res.json();
        
        loader.style.display = "none";
        
        if (stocks.length === 0) {
            container.innerHTML += `<div style="grid-column: 1/-1; padding: 2rem; text-align: center; color: var(--text-sub);">No valid data for this sector.</div>`;
            return;
        }
        
        for (let stock of stocks) {
            renderStockCard(stock, container);
        }
    } catch (e) {
        loader.style.display = "none";
        console.error("Failed to load sector", e);
    }
}

function renderStockCard(stock, container) {
    const card = document.createElement("div");
    card.className = "card stock-card";
    card.id = `stock-${stock.symbol}`;
    
    let signalClass = "none";
    if (stock.signal.includes("CALL")) signalClass = "call";
    if (stock.signal.includes("PUT")) signalClass = "put";
    
    let consensusClass = 'neutral';
    if (stock.analyst_consensus && stock.analyst_consensus.includes("BULLISH")) consensusClass = 'bullish';
    if (stock.analyst_consensus && stock.analyst_consensus.includes("BEARISH")) consensusClass = 'bearish';

    let html = `
        <div class="stock-header">
            <div>
                <div class="stock-symbol">${stock.symbol}</div>
                <div style="font-size: 0.8rem; color: var(--text-sub); margin-top: 4px;">
                    Vol Breakout: ${stock.volume_breakout ? '<span style="color:var(--positive)">YES</span>' : 'NO'} | Res: ${stock.near_resistance ? 'Near' : '-'} | Sup: ${stock.near_support ? 'Near' : '-'}
                </div>
            </div>
            <div class="stock-price">₹${stock.price}</div>
        </div>
        
        <div class="stock-stats">
            <div class="stat">
                <span class="stat-label">9 EMA</span>
                <span class="stat-val ${stock.price > stock.ema9 ? 'up' : 'down'}">${stock.ema9}</span>
            </div>
            <div class="stat">
                <span class="stat-label">15 EMA</span>
                <span class="stat-val ${stock.price > stock.ema15 ? 'up' : 'down'}">${stock.ema15}</span>
            </div>
        </div>
        
        <div class="analyst-badge ${consensusClass}">
            ${stock.analyst_consensus || "No Consensus Data"}
        </div>
        
        <div class="signal-banner ${signalClass}">
            ${stock.signal}
        </div>
        
        <button class="view-chart-btn" onclick="toggleChart('${stock.symbol}')">View Chart</button>
        <div id="chart-wrapper-${stock.symbol}" class="chart-container-wrapper">
             <div id="chart-${stock.symbol}" class="tv-chart"></div>
        </div>
        
        <div id="options-${stock.symbol}" class="options-data" style="display: none;">
             <div style="text-align:center; font-size: 0.8rem; color: var(--text-sub);">Loading Option Chain...</div>
        </div>
    `;
    
    card.innerHTML = html;
    container.appendChild(card);
    
    // If there's a signal, load option chain automatically
    if (signalClass !== "none" || true) { // Let's load for all to show functionality
        loadOptionChain(stock.symbol);
    }
}

window.toggleChart = async function(symbol) {
    const wrapper = document.getElementById(`chart-wrapper-${symbol}`);
    if (wrapper.style.display === "block") {
        wrapper.style.display = "none";
        return;
    }
    
    wrapper.style.display = "block";
    
    if (loadedCharts[symbol]) return; // Already loaded

    const chartContainer = document.getElementById(`chart-${symbol}`);
    chartContainer.innerHTML = `<div style="text-align:center; padding-top:100px; color:var(--text-sub);">Loading Chart Data... yfinance takes a moment.</div>`;

    try {
        const res = await fetch(`/api/chart-data/${symbol}`);
        const data = await res.json();
        
        chartContainer.innerHTML = '';
        
        if (data.error) {
            chartContainer.innerHTML = `<div style="text-align:center; padding-top:100px; color:var(--negative);">Data Unavailable</div>`;
            return;
        }
        
        const chart = LightweightCharts.createChart(chartContainer, {
            layout: {
                background: { type: 'solid', color: 'transparent' },
                textColor: '#d1d5db',
            },
            grid: {
                vertLines: { color: 'rgba(255, 255, 255, 0.05)' },
                horzLines: { color: 'rgba(255, 255, 255, 0.05)' },
            },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
            timeScale: { borderColor: 'rgba(255, 255, 255, 0.1)' },
        });

        const candlestickSeries = chart.addCandlestickSeries({
            upColor: '#10B981', downColor: '#EF4444',
            borderVisible: false,
            wickUpColor: '#10B981', wickDownColor: '#EF4444'
        });
        candlestickSeries.setData(data.candles);

        const ema9Series = chart.addLineSeries({ color: '#3B82F6', lineWidth: 1, title: '9 EMA' });
        ema9Series.setData(data.ema9);

        const ema15Series = chart.addLineSeries({ color: '#8B5CF6', lineWidth: 1, title: '15 EMA' });
        ema15Series.setData(data.ema15);

        const resSeries = chart.addLineSeries({ color: '#EF4444', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, title: 'Res' });
        resSeries.setData(data.resistance);
        
        const supSeries = chart.addLineSeries({ color: '#10B981', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, title: 'Sup' });
        supSeries.setData(data.support);

        chart.timeScale().fitContent();
        loadedCharts[symbol] = chart;
        
    } catch (e) {
        console.error("Chart Error:", e);
        chartContainer.innerHTML = `<div style="text-align:center; padding-top:100px; color:var(--negative);">Failed to load chart: ${e.message}</div>`;
    }
}

async function loadOptionChain(symbol) {
    const optContainer = document.getElementById(`options-${symbol}`);
    optContainer.style.display = "block";
    
    try {
        const res = await fetch(`/api/option-chain/${symbol}`);
        const data = await res.json();
        
        if (data.error && !data.mock) {
            optContainer.innerHTML = `<div style="color: var(--negative); font-size: 0.8rem;">Opt Data Error</div>`;
            return;
        }
        
        const total = data.call_oi + data.put_oi;
        const callPct = ((data.call_oi / total) * 100) || 50;
        const putPct = ((data.put_oi / total) * 100) || 50;
        
        let content = `
            <div style="font-size: 0.85rem; font-weight: 500; margin-bottom: 0.5rem; display:flex; justify-content:space-between">
                <span>Highest OI Resistance (CE)</span>
                <span>Highest OI Support (PE)</span>
            </div>
            <div class="oi-visual">
                <div class="call-oi" style="width: ${callPct}%"></div>
                <div class="put-oi" style="width: ${putPct}%"></div>
            </div>
            <div class="oi-bar">
                <span style="color: var(--negative);">${formatNumber(data.call_oi)} OI</span>
                ${data.mock ? '<span title="Mock data due to NSE Block" style="color:orange;">(Mock Data)</span>' : ''}
                <span style="color: var(--positive);">${formatNumber(data.put_oi)} OI</span>
            </div>
        `;
        optContainer.innerHTML = content;
        
    } catch (e) {
        optContainer.innerHTML = `<div style="color: var(--text-sub); font-size: 0.8rem;">Opt Data Unavailable</div>`;
    }
}

function formatNumber(num) {
    if (num >= 100000) {
        return (num / 100000).toFixed(2) + 'L';
    }
    return num.toLocaleString();
}
