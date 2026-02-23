/* RePlexOn - Dashboard Charts (purple/pink theme matching inspo) */

document.addEventListener('DOMContentLoaded', function() {
    var PURPLE = '#7c3aed';
    var PURPLE_LIGHT = 'rgba(124, 58, 237, 0.3)';
    var PINK = '#e879a8';
    var PINK_LIGHT = 'rgba(232, 121, 168, 0.3)';
    var GRAY = '#9196a8';
    var GRAY_LIGHT = '#e5e7ee';
    var TEXT_PRIMARY = '#1a1d2e';
    var TEXT_MUTED = '#9196a8';
    var GRID_COLOR = 'rgba(0, 0, 0, 0.04)';
    var SUCCESS = '#16a34a';
    var WARNING = '#d97706';
    var DANGER = '#dc2626';
    var ORANGE = '#E8751A';
    var TEAL = '#0d9488';

    Chart.defaults.color = TEXT_MUTED;
    Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
    Chart.defaults.font.size = 11;

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

    // Stat card mini charts (colored rings like the inspo)
    if (typeof successRate !== 'undefined') {
        miniDoughnut('successChart', successRate, 100, successRate >= 95 ? SUCCESS : (successRate >= 80 ? WARNING : DANGER));
    }
    if (typeof totalBackups !== 'undefined') {
        miniDoughnut('totalChart', totalBackups, Math.max(totalBackups, 30), PINK);
    }
    miniDoughnut('lastBackupChart', 1, 1, PURPLE);
    miniDoughnut('sizeChart', 0.7, 1, PURPLE);

    // --- Bar chart: Backup Size Over Time (purple/pink gradient bars) ---
    var barCanvas = document.getElementById('sizeBarChart');
    if (barCanvas && typeof dailySizes !== 'undefined' && dailySizes.length > 0) {
        var labels = dailySizes.map(function(d) {
            var parts = d.date.split('-');
            return parts[1] + '/' + parts[2];
        });
        var sizes = dailySizes.map(function(d) {
            return d.size ? (d.size / 1073741824).toFixed(2) : 0;
        });

        // Purple-to-pink gradient like the inspo
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
                    tooltip: {
                        backgroundColor: '#1e1f2b',
                        titleColor: '#ffffff',
                        bodyColor: '#c8cad4',
                        padding: 10,
                        cornerRadius: 8,
                        callbacks: {
                            label: function(ctx) { return ctx.parsed.y.toFixed(2) + ' GB'; }
                        }
                    }
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

    // --- Doughnut chart: By Type ---
    var doughnutCanvas = document.getElementById('typeDoughnut');
    if (doughnutCanvas && typeof typeCounts !== 'undefined') {
        var typeLabels = Object.keys(typeCounts).map(function(k) {
            return k.replace(/_/g, ' ');
        });
        var typeValues = Object.values(typeCounts);
        var typeColors = Object.keys(typeCounts).map(function(k) {
            var colorMap = {
                'daily_mirror': PURPLE,
                'snapshot': '#8b5cf6',
                'cleanup': GRAY,
                'manual': ORANGE,
                'script_backup': TEAL,
            };
            return colorMap[k] || GRAY;
        });

        new Chart(doughnutCanvas, {
            type: 'doughnut',
            data: {
                labels: typeLabels,
                datasets: [{
                    data: typeValues,
                    backgroundColor: typeColors,
                    borderWidth: 0,
                    spacing: 2,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '60%',
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 16,
                            usePointStyle: true,
                            pointStyleWidth: 10,
                            color: TEXT_MUTED,
                        }
                    },
                    tooltip: {
                        backgroundColor: '#1e1f2b',
                        titleColor: '#ffffff',
                        bodyColor: '#c8cad4',
                        padding: 10,
                        cornerRadius: 8,
                    }
                }
            }
        });
    }
});
