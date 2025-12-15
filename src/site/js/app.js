/**
 * Shaw-Spell Dictionary JavaScript
 * Minimal UI interactions - settings modal and burger menu
 */

// Burger menu
function toggleBurgerMenu() {
    const dropdown = document.getElementById('burgerDropdown');
    dropdown.classList.toggle('show');
}

// Close burger menu when clicking outside
document.addEventListener('click', function(event) {
    const burger = document.querySelector('.burger-menu');
    if (burger && !burger.contains(event.target)) {
        const dropdown = document.getElementById('burgerDropdown');
        if (dropdown) {
            dropdown.classList.remove('show');
        }
    }
});

function closeBurgerMenu() {
    const dropdown = document.getElementById('burgerDropdown');
    if (dropdown) {
        dropdown.classList.remove('show');
    }
}

// Modal functions
async function openAbout() {
    closeBurgerMenu();
    const content = await fetch('templates/about.html').then(r => r.text());
    showModal(content);
}

async function openSettings() {
    closeBurgerMenu();

    const settings = window.SETTINGS || {dialect: 'gb', shavianDefs: 'english'};

    const content = `
<h2>Settings</h2>

<form method="get" action="index.cgi" id="settingsForm">
    <input type="hidden" name="word" value="${document.getElementById('searchInput')?.value || ''}">

    <div class="setting-group">
        <h3>Dialect</h3>
        <p>Select your preferred English dialect:</p>
        <label>
            <input type="radio" name="dialect" value="gb" ${settings.dialect === 'gb' ? 'checked' : ''}>
            British English (GB)
        </label>
        <label>
            <input type="radio" name="dialect" value="us" ${settings.dialect === 'us' ? 'checked' : ''}>
            American English (US)
        </label>
    </div>

    <div class="setting-group">
        <h3>Shavian Definitions</h3>
        <p>When looking up Shavian words, show definitions in:</p>
        <label>
            <input type="radio" name="shavianDefs" value="english" ${settings.shavianDefs === 'english' ? 'checked' : ''}>
            English (with Shavian headword)
        </label>
        <label>
            <input type="radio" name="shavianDefs" value="shavian" ${settings.shavianDefs === 'shavian' ? 'checked' : ''}>
            Shavian only (immersive mode)
        </label>
    </div>

    <div class="setting-actions">
        <button type="submit" class="btn-primary">Save Settings</button>
        <button type="button" onclick="closeModal()" class="btn-secondary">Cancel</button>
    </div>
</form>
    `;

    showModal(content);
}

function showModal(content) {
    const modalContent = document.getElementById('modalContent');
    const modalOverlay = document.getElementById('modalOverlay');

    modalContent.innerHTML = content;
    modalOverlay.classList.add('show');
}

function closeModal() {
    const modalOverlay = document.getElementById('modalOverlay');
    modalOverlay.classList.remove('show');
}

// Close modal when clicking overlay
document.addEventListener('DOMContentLoaded', function() {
    const modalOverlay = document.getElementById('modalOverlay');
    if (modalOverlay) {
        modalOverlay.addEventListener('click', function(event) {
            if (event.target === modalOverlay) {
                closeModal();
            }
        });
    }

    // Make words in dictionary entries clickable
    const entryContainer = document.querySelector('.entry-container');
    if (entryContainer) {
        entryContainer.addEventListener('click', handleWordClick);
    }
});

/**
 * Extract the word at the click position and navigate to it
 */
function handleWordClick(event) {
    // Get the clicked element
    const target = event.target;

    // Don't process clicks on the container itself or welcome sections
    if (target.classList.contains('entry-container') ||
        target.classList.contains('welcome-bottom') ||
        target.classList.contains('no-results')) {
        return;
    }

    // If clicked element is a word span, use its text directly
    let word;
    if (target.classList.contains('w')) {
        word = target.textContent.trim();
    } else {
        // Check if we clicked inside a word span
        const wordSpan = target.closest('span.w');
        if (wordSpan) {
            word = wordSpan.textContent.trim();
        } else {
            // No word span found - might be clicking on non-word content
            return;
        }
    }

    if (!word) {
        return;
    }

    // Navigate to the word, preserving current settings
    const settings = window.SETTINGS || {dialect: 'gb', shavianDefs: 'english'};
    const url = `index.cgi?word=${encodeURIComponent(word)}&dialect=${settings.dialect}&shavianDefs=${settings.shavianDefs}`;
    window.location.href = url;
}
