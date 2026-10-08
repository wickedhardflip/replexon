/* RePlexOn - Global JS */

document.addEventListener('DOMContentLoaded', function() {
    // Auto-dismiss alerts after 5 seconds
    document.querySelectorAll('.alert-success').forEach(function(el) {
        setTimeout(function() {
            el.style.transition = 'opacity 0.3s';
            el.style.opacity = '0';
            setTimeout(function() { el.remove(); }, 300);
        }, 5000);
    });

    // Dark mode toggle
    var toggle = document.getElementById('theme-toggle');
    if (toggle) {
        function updateIcon() {
            var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            toggle.textContent = isDark ? '\u2600' : '\u263E';
        }
        updateIcon();

        toggle.addEventListener('click', function() {
            var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            if (isDark) {
                document.documentElement.removeAttribute('data-theme');
                localStorage.setItem('theme', 'light');
            } else {
                document.documentElement.setAttribute('data-theme', 'dark');
                localStorage.setItem('theme', 'dark');
            }
            updateIcon();
        });
    }

    // Time zone field: pre-fill from the browser in the wizard, live "time there now" preview
    document.querySelectorAll('[data-tz-input]').forEach(function(input) {
        var preview = input.form && input.form.querySelector('[data-tz-preview]');
        if (input.hasAttribute('data-tz-from-browser')) {
            try {
                var browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
                if (browserZone && document.querySelector('#zone-names option[value="' + browserZone + '"]')) {
                    input.value = browserZone;
                }
            } catch (e) {}
        }
        function showTime() {
            if (!preview) return;
            try {
                preview.textContent = new Intl.DateTimeFormat('en-US', {
                    timeZone: input.value.trim(), weekday: 'short', hour: 'numeric', minute: '2-digit',
                }).format(new Date());
                input.setCustomValidity('');
            } catch (e) {
                preview.textContent = 'unknown zone';
                input.setCustomValidity('Unknown time zone. Pick one from the list, e.g. America/New_York.');
            }
        }
        input.addEventListener('input', showTime);
        showTime();
        setInterval(showTime, 30000);
    });

    // Hamburger menu toggle
    var hamburger = document.getElementById('nav-hamburger');
    var navLinks = document.getElementById('nav-links');
    if (hamburger && navLinks) {
        hamburger.addEventListener('click', function() {
            navLinks.classList.toggle('open');
        });
        // Close menu when clicking a link
        navLinks.querySelectorAll('a').forEach(function(link) {
            link.addEventListener('click', function() {
                navLinks.classList.remove('open');
            });
        });
    }
});
