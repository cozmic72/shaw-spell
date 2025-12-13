//
//  AppDelegate.swift
//  Shaw-Spell Installer
//
//  Wizard-style installer for Shaw-Spell
//

import Cocoa
import WebKit

class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var contentView: WKWebView!
    var buttonContainer: NSView!
    var currentPage = 0

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Create the main window
        let windowRect = NSRect(x: 0, y: 0, width: 700, height: 640)
        window = NSWindow(contentRect: windowRect,
                         styleMask: [.titled, .closable, .miniaturizable],
                         backing: .buffered,
                         defer: false)
        window.title = "Shaw-Spell Installer"
        window.center()

        guard let mainContentView = window.contentView else { return }

        // Create WebView for content
        contentView = WKWebView(frame: NSRect(x: 20, y: 60, width: 660, height: 530))
        contentView.navigationDelegate = self

        // Add rounded corners to content view
        contentView.wantsLayer = true
        contentView.layer?.cornerRadius = 8
        contentView.layer?.masksToBounds = true

        mainContentView.addSubview(contentView)

        // Create button container
        buttonContainer = NSView(frame: NSRect(x: 0, y: 0, width: 700, height: 60))
        mainContentView.addSubview(buttonContainer)

        // Show first page
        showWelcomePage()

        window.makeKeyAndOrderFront(nil)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }

    // MARK: - Pages

    func showWelcomePage() {
        currentPage = 0
        loadHTMLResource("welcome")

        // Clear button container
        buttonContainer.subviews.forEach { $0.removeFromSuperview() }

        // Next button
        let nextButton = NSButton(frame: NSRect(x: 570, y: 14, width: 110, height: 32))
        nextButton.title = "Next"
        nextButton.bezelStyle = .rounded
        nextButton.keyEquivalent = "\r"
        nextButton.target = self
        nextButton.action = #selector(nextButtonClicked)
        buttonContainer.addSubview(nextButton)
    }

    func showDictionaryPage() {
        currentPage = 1
        loadHTMLResource("dictionary")

        // Clear button container
        buttonContainer.subviews.forEach { $0.removeFromSuperview() }

        // Open Dictionary.app button
        let dictionaryButton = NSButton(frame: NSRect(x: 20, y: 14, width: 160, height: 32))
        dictionaryButton.title = "Open Dictionary.app"
        dictionaryButton.bezelStyle = .rounded
        dictionaryButton.target = self
        dictionaryButton.action = #selector(openDictionaryApp)
        buttonContainer.addSubview(dictionaryButton)

        // Next button
        let nextButton = NSButton(frame: NSRect(x: 570, y: 14, width: 110, height: 32))
        nextButton.title = "Next"
        nextButton.bezelStyle = .rounded
        nextButton.keyEquivalent = "\r"
        nextButton.target = self
        nextButton.action = #selector(nextFromDictionaryClicked)
        buttonContainer.addSubview(nextButton)
    }

    func showSpellCheckerPage() {
        currentPage = 2
        loadHTMLResource("complete")

        // Clear button container
        buttonContainer.subviews.forEach { $0.removeFromSuperview() }

        // Open System Settings button
        let settingsButton = NSButton(frame: NSRect(x: 20, y: 14, width: 180, height: 32))
        settingsButton.title = "Open System Settings"
        settingsButton.bezelStyle = .rounded
        settingsButton.target = self
        settingsButton.action = #selector(openSystemSettings)
        buttonContainer.addSubview(settingsButton)

        // Done button
        let doneButton = NSButton(frame: NSRect(x: 570, y: 14, width: 110, height: 32))
        doneButton.title = "Done"
        doneButton.bezelStyle = .rounded
        doneButton.keyEquivalent = "\r"
        doneButton.target = self
        doneButton.action = #selector(doneButtonClicked)
        buttonContainer.addSubview(doneButton)
    }

    // MARK: - Button Actions

    @objc func nextButtonClicked() {
        // Skip the installing page - installation is fast enough to just do it and show dictionary page
        performInstallation()
    }

    @objc func nextFromDictionaryClicked() {
        showSpellCheckerPage()
    }

    @objc func openDictionaryApp() {
        let url = URL(fileURLWithPath: "/System/Applications/Dictionary.app")
        NSWorkspace.shared.open(url)
    }

    @objc func openSystemSettings() {
        // Open directly to Input Sources settings within Keyboard
        if let url = URL(string: "x-apple.systempreferences:com.apple.Keyboard?InputSources") {
            NSWorkspace.shared.open(url)
        } else {
            // Fallback: open Keyboard settings
            if let url = URL(string: "x-apple.systempreferences:com.apple.Keyboard") {
                NSWorkspace.shared.open(url)
            }
        }
    }

    @objc func doneButtonClicked() {
        NSApplication.shared.terminate(nil)
    }

    // MARK: - Installation

    func performInstallation() {
        // Get the Resources directory where bundled files are stored
        guard let resourcesPath = Bundle.main.resourcePath else {
            showError("Failed to locate installer resources")
            return
        }

        // Build installation script
        var script = """
        #!/bin/bash
        set -e

        """

        // Determine installation directories (always user, both dialects)
        let homeDir = NSHomeDirectory()
        let dictDir = homeDir + "/Library/Dictionaries"
        let spellingDir = homeDir + "/Library/Spelling"
        let servicesDir = homeDir + "/Library/Services"
        let launchAgentDir = homeDir + "/Library/LaunchAgents"
        let logsDir = homeDir + "/Library/Logs"

        script += """
        RESOURCES_DIR='\(resourcesPath)'
        DICT_DIR='\(dictDir)'
        SPELLING_DIR='\(spellingDir)'
        SERVICES_DIR='\(servicesDir)'
        LAUNCH_AGENT_DIR='\(launchAgentDir)'
        LOGS_DIR='\(logsDir)'

        """

        // Create directories
        script += """
        echo 'Creating directories...'
        mkdir -p "$DICT_DIR"
        mkdir -p "$SPELLING_DIR"
        mkdir -p "$SERVICES_DIR"
        mkdir -p "$LAUNCH_AGENT_DIR"
        mkdir -p "$LOGS_DIR"

        """

        // Install both GB and US dictionaries
        script += """
        echo 'Installing dictionaries...'
        cp -R "$RESOURCES_DIR/dictionaries/Shaw-Spell-Shavian-English-gb.dictionary" "$DICT_DIR/" 2>/dev/null || true
        cp -R "$RESOURCES_DIR/dictionaries/Shaw-Spell-English-Shavian-gb.dictionary" "$DICT_DIR/" 2>/dev/null || true
        cp -R "$RESOURCES_DIR/dictionaries/Shaw-Spell-Shavian-gb.dictionary" "$DICT_DIR/" 2>/dev/null || true
        cp -R "$RESOURCES_DIR/dictionaries/Shaw-Spell-Shavian-English-us.dictionary" "$DICT_DIR/" 2>/dev/null || true
        cp -R "$RESOURCES_DIR/dictionaries/Shaw-Spell-English-Shavian-us.dictionary" "$DICT_DIR/" 2>/dev/null || true
        cp -R "$RESOURCES_DIR/dictionaries/Shaw-Spell-Shavian-us.dictionary" "$DICT_DIR/" 2>/dev/null || true

        echo 'Installing spell checking dictionaries...'
        cp "$RESOURCES_DIR/hunspell/io.joro.shaw-spell.shavian-gb.dic" "$SPELLING_DIR/" 2>/dev/null || true
        cp "$RESOURCES_DIR/hunspell/io.joro.shaw-spell.shavian-gb.aff" "$SPELLING_DIR/" 2>/dev/null || true
        cp "$RESOURCES_DIR/hunspell/io.joro.shaw-spell.shavian-us.dic" "$SPELLING_DIR/" 2>/dev/null || true
        cp "$RESOURCES_DIR/hunspell/io.joro.shaw-spell.shavian-us.aff" "$SPELLING_DIR/" 2>/dev/null || true
        cp "$RESOURCES_DIR/hunspell/io.joro.shaw-spell.en_GB.dic" "$SPELLING_DIR/" 2>/dev/null || true
        cp "$RESOURCES_DIR/hunspell/io.joro.shaw-spell.en_GB.aff" "$SPELLING_DIR/" 2>/dev/null || true
        cp "$RESOURCES_DIR/hunspell/io.joro.shaw-spell.en_US.dic" "$SPELLING_DIR/" 2>/dev/null || true
        cp "$RESOURCES_DIR/hunspell/io.joro.shaw-spell.en_US.aff" "$SPELLING_DIR/" 2>/dev/null || true

        """

        // Install spell server
        script += """
        echo 'Installing spell server...'
        cp -R "$RESOURCES_DIR/Shaw-Spell.service" "$SERVICES_DIR/"

        """

        // Install LaunchAgent
        script += """
        echo 'Installing LaunchAgent...'
        sed 's|__HOME__|\(homeDir)|g' "$RESOURCES_DIR/io.joro.Shaw-Spell.plist" > "$LAUNCH_AGENT_DIR/io.joro.Shaw-Spell.plist"

        """

        // Load LaunchAgent
        script += """
        echo 'Starting spell server...'
        launchctl unload "$LAUNCH_AGENT_DIR/io.joro.Shaw-Spell.plist" 2>/dev/null || true
        launchctl load "$LAUNCH_AGENT_DIR/io.joro.Shaw-Spell.plist"

        """

        // Update services
        script += """
        echo 'Updating system services...'
        /System/Library/CoreServices/pbs -update 2>/dev/null || true

        echo 'Installation complete!'
        """

        // Write script to temporary file
        let scriptPath = "/tmp/shaw-spell-install.sh"

        do {
            try script.write(toFile: scriptPath, atomically: true, encoding: .utf8)
        } catch {
            DispatchQueue.main.async { [weak self] in
                self?.showError("Failed to create installation script: \(error.localizedDescription)")
            }
            return
        }

        // Make script executable
        chmod(scriptPath, 0o755)

        // Execute installation script in background
        DispatchQueue.global(qos: .default).async { [weak self] in
            let task = Process()
            task.launchPath = "/bin/bash"
            task.arguments = [scriptPath]

            task.launch()
            task.waitUntilExit()

            DispatchQueue.main.async {
                if task.terminationStatus == 0 {
                    self?.showDictionaryPage()
                } else {
                    self?.showError("Installation failed. Please check the logs and try again.")
                }
            }
        }
    }

    // MARK: - Utilities

    func loadHTMLResource(_ name: String) {
        if let resourcePath = Bundle.main.path(forResource: name, ofType: "html"),
           let htmlString = try? String(contentsOfFile: resourcePath, encoding: .utf8) {
            contentView.loadHTMLString(htmlString, baseURL: nil)
        }
    }

    func showError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Installation Error"
        alert.informativeText = message
        alert.alertStyle = .critical
        alert.addButton(withTitle: "OK")
        alert.runModal()

        // Go back to welcome page
        showWelcomePage()
    }

    // MARK: - WKNavigationDelegate

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        // Allow initial page loads and loadHTMLString calls
        if navigationAction.navigationType == .other {
            decisionHandler(.allow)
            return
        }

        // For link clicks, open in default browser
        if navigationAction.navigationType == .linkActivated {
            if let url = navigationAction.request.url {
                NSWorkspace.shared.open(url)
            }
            decisionHandler(.cancel)
            return
        }

        decisionHandler(.allow)
    }
}
