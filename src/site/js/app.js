/**
 * Shaw-Spell Dictionary JavaScript
 * Minimal UI interactions - settings modal and burger menu
 */

// Shavian UI strings for immersive mode
const STRINGS = {
    latin: {
        settings_title: 'Settings',
        dialect_heading: 'Dialect',
        dialect_prompt: 'Select your preferred English dialect:',
        dialect_gb: 'British English (GB)',
        dialect_us: 'American English (US)',
        shavian_defs_heading: 'Shavian Definitions',
        shavian_defs_prompt: 'When looking up Shavian words, show definitions in:',
        shavian_defs_english: 'English (with Shavian headword)',
        shavian_defs_shavian: 'Shavian only (immersive mode)',
        save_button: 'Save Settings',
        cancel_button: 'Cancel',
        menu_about: 'About…',
        menu_settings: 'Settings…',
        menu_show_keyboard: 'Show keyboard',
        menu_keyboard_layout: 'Keyboard layout…'
    },
    shavian: {
        settings_title: '𐑕𐑧𐑑𐑦𐑙𐑟',
        dialect_heading: '𐑛𐑲𐑩𐑤𐑧𐑒𐑑',
        dialect_prompt: '𐑕𐑩𐑤𐑧𐑒𐑑 𐑘𐑹 𐑐𐑮𐑦𐑓𐑻𐑛 𐑦𐑙𐑜𐑤𐑦𐑖 𐑛𐑲𐑩𐑤𐑧𐑒𐑑:',
        dialect_gb: '𐑚𐑮𐑦𐑑𐑦𐑖 𐑦𐑙𐑜𐑤𐑦𐑖 (GB)',
        dialect_us: '𐑧𐑥𐑧𐑮𐑦𐑒𐑩𐑯 𐑦𐑙𐑜𐑤𐑦𐑖 (US)',
        shavian_defs_heading: '𐑖𐑱𐑚𐑾𐑯 𐑛𐑧𐑓𐑦𐑯𐑦𐑖𐑩𐑯𐑟',
        shavian_defs_prompt: '𐑢𐑧𐑯 𐑤𐑫𐑒𐑦𐑙 𐑳𐑐 ·𐑖𐑱𐑝𐑾𐑯 𐑢𐑻𐑛𐑟, 𐑖𐑴 𐑛𐑧𐑓𐑦𐑯𐑦𐑖𐑩𐑯𐑟 𐑦𐑯:',
        shavian_defs_english: '𐑦𐑙𐑜𐑤𐑦𐑖 (𐑢𐑦𐑞 ·𐑖𐑱𐑝𐑾𐑯 𐑣𐑧𐑛𐑢𐑻𐑛)',
        shavian_defs_shavian: '𐑖𐑱𐑝𐑾𐑯 𐑴𐑯𐑤𐑦 (𐑦𐑥𐑻𐑕𐑦𐑝 𐑥𐑴𐑛)',
        save_button: '𐑕𐑱𐑝 𐑕𐑧𐑑𐑦𐑙𐑟',
        cancel_button: '𐑒𐑨𐑯𐑕𐑩𐑤',
        // Shavian from the shave G2P — owner to confirm 𐑒𐑰𐑚𐑹𐑛/𐑤𐑱𐑬𐑑 spellings
        menu_about: '𐑩𐑚𐑬𐑑…',
        menu_settings: '𐑕𐑧𐑑𐑦𐑙𐑟…',
        menu_show_keyboard: '𐑖𐑴 𐑒𐑰𐑚𐑹𐑛',
        menu_keyboard_layout: '𐑒𐑰𐑚𐑹𐑛 𐑤𐑱𐑬𐑑…'
    }
};

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
    const settings = window.SETTINGS || {dialect: 'gb', shavianDefs: 'english'};
    const immersive = settings.shavianDefs === 'shavian';
    const templateFile = immersive ? 'templates/about-shavian.html' : 'templates/about.html';
    const content = await fetch(templateFile).then(r => r.text());
    showModal(content);
}

async function openSettings() {
    closeBurgerMenu();

    const settings = window.SETTINGS || {dialect: 'gb', shavianDefs: 'english'};
    const lang = settings.shavianDefs === 'shavian' ? 'shavian' : 'latin';
    const strings = STRINGS[lang];

    const content = `
<h2>${strings.settings_title}</h2>

<form method="get" action="index.cgi" id="settingsForm">
    <input type="hidden" name="word" value="${document.getElementById('searchInput')?.value || ''}">

    <div class="setting-group">
        <h3>${strings.dialect_heading}</h3>
        <p>${strings.dialect_prompt}</p>
        <label>
            <input type="radio" name="dialect" value="gb" ${settings.dialect === 'gb' ? 'checked' : ''}>
            ${strings.dialect_gb}
        </label>
        <label>
            <input type="radio" name="dialect" value="us" ${settings.dialect === 'us' ? 'checked' : ''}>
            ${strings.dialect_us}
        </label>
    </div>

    <div class="setting-group">
        <h3>${strings.shavian_defs_heading}</h3>
        <p>${strings.shavian_defs_prompt}</p>
        <label>
            <input type="radio" name="shavianDefs" value="english" ${settings.shavianDefs === 'english' ? 'checked' : ''}>
            ${strings.shavian_defs_english}
        </label>
        <label>
            <input type="radio" name="shavianDefs" value="shavian" ${settings.shavianDefs === 'shavian' ? 'checked' : ''}>
            ${strings.shavian_defs_shavian}
        </label>
    </div>

    <div class="setting-actions">
        <button type="submit" class="btn-primary">${strings.save_button}</button>
        <button type="button" onclick="closeModal()" class="btn-secondary">${strings.cancel_button}</button>
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

// Fill burger-menu labels from STRINGS, respelling in immersive mode.
function initBurgerLabels() {
    const settings = window.SETTINGS || {dialect: 'gb', shavianDefs: 'english'};
    const lang = settings.shavianDefs === 'shavian' ? 'shavian' : 'latin';
    const strings = STRINGS[lang];
    const map = {
        'menu-label-about': strings.menu_about,
        'menu-label-settings': strings.menu_settings,
        'menu-label-show-keyboard': strings.menu_show_keyboard,
        'menu-label-keyboard-layout': strings.menu_keyboard_layout
    };
    for (const id in map) {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = map[id];
        }
    }
}

// Close modal when clicking overlay
document.addEventListener('DOMContentLoaded', function() {
    initBurgerLabels();

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
