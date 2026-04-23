/* RePlexOn - Dashboard Charts (purple/pink theme matching inspo) */

document.addEventListener('DOMContentLoaded', function() {
    var dataEl = document.getElementById('dashboard-data');
    var dailySizes = dataEl ? JSON.parse(dataEl.dataset.dailySizes) : [];
    var dailyDurations = dataEl ? JSON.parse(dataEl.dataset.dailyDurations) : [];
    var successRate = dataEl ? parseFloat(dataEl.dataset.successRate) : 0;
    var totalBackups = dataEl ? parseInt(dataEl.dataset.totalBackups, 10) : 0;

    var PURPLE = '#7c3aed';
    var PINK = '#e879a8';
    var GRAY_LIGHT = '#e5e7ee';
    var TEXT_MUTED = '#9196a8';
    var GRID_COLOR = 'rgba(0, 0, 0, 0.04)';
    var SUCCESS = '#16a34a';
    var WARNING = '#d97706';
    var DANGER = '#dc2626';
    var TEAL = '#0d9488';

    Chart.defaults.color = TEXT_MUTED;
    Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
    Chart.defaults.font.size = 11;

    var TOOLTIP_STYLE = {
        backgroundColor: '#1e1f2b',
        titleColor: '#ffffff',
        bodyColor: '#c8cad4',
        padding: 10,
        cornerRadius: 8,
    };

    // --- Mini doughnut for stat cards ---
    function miniDoughnut(canvasId, value, maxVal, color) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;
        var pct = maxVal > 0 ? Math.min(value / maxVal, 1) : 0;
        new Chart(canvas, {
            type: 'doughnut',
            data: {
                datasets: [{
                    data: [pct * 100, (1 - pct) * 100],
                    backgroundColor: [color, GRAY_LIGHT],
                    borderWidth: 0,
                }]
            },
            options: {
                cutout: '72%',
                responsive: false,
                plugins: { legend: { display: false }, tooltip: { enabled: false } },
                animation: { animateRotate: true, duration: 800 },
            }
        });
    }

    miniDoughnut('successChart', successRate, 100, successRate >= 95 ? SUCCESS : (successRate >= 80 ? WARNING : DANGER));
    miniDoughnut('totalChart', totalBackups, Math.max(totalBackups, 30), PINK);
    miniDoughnut('lastBackupChart', 1, 1, PURPLE);
    miniDoughnut('sizeChart', 0.7, 1, PURPLE);

    // --- Bar chart: Backup Size Over Time ---
    var barCanvas = document.getElementById('sizeBarChart');
    if (barCanvas && dailySizes.length > 0) {
        var labels = dailySizes.map(function(d) {
            var parts = d.date.split('-');
            return parts[1] + '/' + parts[2];
        });
        var sizes = dailySizes.map(function(d) {
            return d.size ? (d.size / 1073741824).toFixed(2) : 0;
        });

        var ctx = barCanvas.getContext('2d');
        var gradient = ctx.createLinearGradient(0, 0, 0, 220);
        gradient.addColorStop(0, PINK);
        gradient.addColorStop(1, PURPLE);

        new Chart(barCanvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Size (GB)',
                    data: sizes,
                    backgroundColor: gradient,
                    borderRadius: 4,
                    borderSkipped: false,
                    maxBarThickness: 24,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: Object.assign({}, TOOLTIP_STYLE, {
                        callbacks: {
                            label: function(c) { return c.parsed.y.toFixed(2) + ' GB'; }
                        }
                    })
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 15, color: TEXT_MUTED },
                    },
                    y: {
                        grid: { color: GRID_COLOR },
                        ticks: {
                            callback: function(v) { return v + ' GB'; },
                            color: TEXT_MUTED,
                        },
                        beginAtZero: true,
                    }
                }
            }
        });
    }

    // --- Bar chart: Duration Trend ---
    var durCanvas = document.getElementById('durationChart');
    if (durCanvas && dailyDurations.length > 0) {
        var durLabels = dailyDurations.map(function(d) {
            var parts = d.date.split('-');
            return parts[1] + '/' + parts[2];
        });
        var durValues = dailyDurations.map(function(d) { return d.minutes; });

        var durCtx = durCanvas.getContext('2d');
        var durGradient = durCtx.createLinearGradient(0, 0, 0, 220);
        durGradient.addColorStop(0, TEAL);
        durGradient.addColorStop(1, '#065f5b');

        new Chart(durCanvas, {
            type: 'bar',
            data: {
                labels: durLabels,
                datasets: [{
                    label: 'Duration (min)',
                    data: durValues,
                    backgroundColor: durGradient,
                    borderRadius: 4,
                    borderSkipped: false,
                    maxBarThickness: 24,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: Object.assign({}, TOOLTIP_STYLE, {
                        callbacks: {
                            label: function(c) { return c.parsed.y.toFixed(1) + ' min'; }
                        }
                    })
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 15, color: TEXT_MUTED },
                    },
                    y: {
                        grid: { color: GRID_COLOR },
                        ticks: {
                            callback: function(v) { return v + 'm'; },
                            color: TEXT_MUTED,
                        },
                        beginAtZero: true,
                    }
                }
            }
        });
    }

    // --- Next Backup Countdown ---
    var countdownEl = document.getElementById('countdown');
    if (countdownEl && countdownEl.dataset.target) {
        var target = new Date(countdownEl.dataset.target).getTime();

        function updateCountdown() {
            var now = Date.now();
            var diff = target - now;
            if (diff <= 0) {
                countdownEl.textContent = 'Due now';
                return;
            }
            var h = Math.floor(diff / 3600000);
            var m = Math.floor((diff % 3600000) / 60000);
            var s = Math.floor((diff % 60000) / 1000);
            countdownEl.textContent = 'Next backup in ' + h + 'h ' + m + 'm ' + s + 's';
        }

        updateCountdown();
        setInterval(updateCountdown, 1000);
    }
});
