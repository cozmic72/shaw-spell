//
//  AppDelegate.swift
//  Shaw Spell Installer
//
//  Main application delegate for the installer.
//

import Cocoa
import WebKit

class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var installButton: NSButton!
    var progressIndicator: NSProgressIndicator!
    var statusLabel: NSTextField!
    var dialectGBCheckbox: NSButton!
    var dialectUSCheckbox: NSButton!
    var systemWideCheckbox: NSButton!
    var instructionsView: WKWebView!

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Create the main window
        let windowRect = NSRect(x: 0, y: 0, width: 600, height: 500)
        window = NSWindow(contentRect: windowRect,
                         styleMask: [.titled, .closable, .miniaturizable],
                         backing: .buffered,
                         defer: false)
        window.title = "Install Shaw Spell"
        window.center()

        guard let contentView = window.contentView else { return }

        // Title label
        let titleLabel = NSTextField(frame: NSRect(x: 20, y: 440, width: 560, height: 40))
        titleLabel.stringValue = "Shaw Spell Installer"
        titleLabel.isBezeled = false
        titleLabel.drawsBackground = false
        titleLabel.isEditable = false
        titleLabel.isSelectable = false
        titleLabel.font = NSFont.boldSystemFont(ofSize: 24)
        titleLabel.alignment = .center
        contentView.addSubview(titleLabel)

        // Subtitle
        let subtitleLabel = NSTextField(frame: NSRect(x: 20, y: 410, width: 560, height: 20))
        subtitleLabel.stringValue = "Shavian Dictionaries & Spell Checker for macOS"
        subtitleLabel.isBezeled = false
        subtitleLabel.drawsBackground = false
        subtitleLabel.isEditable = false
        subtitleLabel.isSelectable = false
        subtitleLabel.font = NSFont.systemFont(ofSize: 12)
        subtitleLabel.alignment = .center
        subtitleLabel.textColor = .secondaryLabelColor
        contentView.addSubview(subtitleLabel)

        // Options section
        let optionsLabel = NSTextField(frame: NSRect(x: 20, y: 370, width: 200, height: 20))
        optionsLabel.stringValue = "Installation Options:"
        optionsLabel.isBezeled = false
        optionsLabel.drawsBackground = false
        optionsLabel.isEditable = false
        optionsLabel.isSelectable = false
        optionsLabel.font = NSFont.boldSystemFont(ofSize: 14)
        contentView.addSubview(optionsLabel)

        // Dialect checkboxes
        dialectGBCheckbox = NSButton(frame: NSRect(x: 40, y: 340, width: 250, height: 20))
        dialectGBCheckbox.setButtonType(.switch)
        dialectGBCheckbox.title = "British English (GB)"
        dialectGBCheckbox.state = .on
        contentView.addSubview(dialectGBCheckbox)

        dialectUSCheckbox = NSButton(frame: NSRect(x: 40, y: 315, width: 250, height: 20))
        dialectUSCheckbox.setButtonType(.switch)
        dialectUSCheckbox.title = "American English (US)"
        dialectUSCheckbox.state = .off
        contentView.addSubview(dialectUSCheckbox)

        // System-wide checkbox
        systemWideCheckbox = NSButton(frame: NSRect(x: 40, y: 285, width: 520, height: 20))
        systemWideCheckbox.setButtonType(.switch)
        systemWideCheckbox.title = "Install system-wide (requires admin password)"
        systemWideCheckbox.state = .off
        contentView.addSubview(systemWideCheckbox)

        // Instructions section
        let instructionsLabel = NSTextField(frame: NSRect(x: 20, y: 255, width: 200, height: 20))
        instructionsLabel.stringValue = "What will be installed:"
        instructionsLabel.isBezeled = false
        instructionsLabel.drawsBackground = false
        instructionsLabel.isEditable = false
        instructionsLabel.isSelectable = false
        instructionsLabel.font = NSFont.boldSystemFont(ofSize: 14)
        contentView.addSubview(instructionsLabel)

        // Instructions web view
        instructionsView = WKWebView(frame: NSRect(x: 20, y: 100, width: 560, height: 145))

        // Load HTML from resources
        if let htmlPath = Bundle.main.path(forResource: "installation-info", ofType: "html"),
           let htmlContent = try? String(contentsOfFile: htmlPath, encoding: .utf8) {
            instructionsView.loadHTMLString(htmlContent, baseURL: nil)
        }

        contentView.addSubview(instructionsView)

        // Status label
        statusLabel = NSTextField(frame: NSRect(x: 20, y: 65, width: 560, height: 20))
        statusLabel.stringValue = "Ready to install"
        statusLabel.isBezeled = false
        statusLabel.drawsBackground = false
        statusLabel.isEditable = false
        statusLabel.isSelectable = false
        statusLabel.alignment = .center
        statusLabel.textColor = .secondaryLabelColor
        contentView.addSubview(statusLabel)

        // Progress indicator
        progressIndicator = NSProgressIndicator(frame: NSRect(x: 200, y: 40, width: 200, height: 20))
        progressIndicator.style = .bar
        progressIndicator.isIndeterminate = true
        progressIndicator.isHidden = true
        contentView.addSubview(progressIndicator)

        // Install button
        installButton = NSButton(frame: NSRect(x: 240, y: 10, width: 120, height: 30))
        installButton.title = "Install"
        installButton.bezelStyle = .rounded
        installButton.keyEquivalent = "\r"
        installButton.target = self
        installButton.action = #selector(installButtonClicked)
        contentView.addSubview(installButton)

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc func installButtonClicked() {
        // Validate selection
        let installGB = dialectGBCheckbox.state == .on
        let installUS = dialectUSCheckbox.state == .on

        guard installGB || installUS else {
            let alert = NSAlert()
            alert.messageText = "No dialect selected"
            alert.informativeText = "Please select at least one dialect to install (British or American English)."
            alert.alertStyle = .warning
            alert.addButton(withTitle: "OK")
            alert.runModal()
            return
        }

        // Disable button and show progress
        installButton.isEnabled = false
        progressIndicator.isHidden = false
        progressIndicator.startAnimation(nil)
        statusLabel.stringValue = "Installing..."

        // Perform installation in background
        DispatchQueue.global(qos: .default).async { [weak self] in
            self?.performInstallation()
        }
    }

    func performInstallation() {
        let installGB = dialectGBCheckbox.state == .on
        let installUS = dialectUSCheckbox.state == .on
        let systemWide = systemWideCheckbox.state == .on

        // Get the project root (installer is in build/)
        let installerPath = Bundle.main.bundlePath
        let projectRoot = (installerPath as NSString).deletingLastPathComponent

        // Build installation script
        var script = """
        #!/bin/bash
        set -e

        """

        // Determine installation directories
        let homeDir = NSHomeDirectory()
        let dictDir = systemWide ? "/Library/Dictionaries" : homeDir + "/Library/Dictionaries"
        let spellingDir = systemWide ? "/Library/Spelling" : homeDir + "/Library/Spelling"
        let servicesDir = systemWide ? "/Library/Services" : homeDir + "/Library/Services"
        let launchAgentDir = homeDir + "/Library/LaunchAgents"
        let logsDir = homeDir + "/Library/Logs"

        script += """
        PROJECT_ROOT='\(projectRoot)'
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

        // Install dictionaries
        if installGB {
            script += """
            echo 'Installing British English dictionaries...'
            cp -R "$PROJECT_ROOT/build/dictionaries/Shavian-English-gb.dictionary" "$DICT_DIR/" 2>/dev/null || true
            cp -R "$PROJECT_ROOT/build/dictionaries/English-Shavian-gb.dictionary" "$DICT_DIR/" 2>/dev/null || true
            cp -R "$PROJECT_ROOT/build/dictionaries/Shavian-gb.dictionary" "$DICT_DIR/" 2>/dev/null || true
            cp "$PROJECT_ROOT/build/shaw-gb.dic" "$SPELLING_DIR/" 2>/dev/null || true
            cp "$PROJECT_ROOT/build/shaw-gb.aff" "$SPELLING_DIR/" 2>/dev/null || true

            """
        }

        if installUS {
            script += """
            echo 'Installing American English dictionaries...'
            cp -R "$PROJECT_ROOT/build/dictionaries/Shavian-English-us.dictionary" "$DICT_DIR/" 2>/dev/null || true
            cp -R "$PROJECT_ROOT/build/dictionaries/English-Shavian-us.dictionary" "$DICT_DIR/" 2>/dev/null || true
            cp -R "$PROJECT_ROOT/build/dictionaries/Shavian-us.dictionary" "$DICT_DIR/" 2>/dev/null || true
            cp "$PROJECT_ROOT/build/shaw-us.dic" "$SPELLING_DIR/" 2>/dev/null || true
            cp "$PROJECT_ROOT/build/shaw-us.aff" "$SPELLING_DIR/" 2>/dev/null || true

            """
        }

        // Install spell server
        script += """
        echo 'Installing spell server...'
        cp -R "$PROJECT_ROOT/build/ShavianSpellServer.service" "$SERVICES_DIR/"

        """

        // Install LaunchAgent
        script += """
        echo 'Installing LaunchAgent...'
        sed 's|__HOME__|\(homeDir)|g' "$PROJECT_ROOT/src/spellserver/io.joro.shaw-spell.spellserver.plist" > "$LAUNCH_AGENT_DIR/io.joro.shaw-spell.spellserver.plist"

        """

        // Load LaunchAgent
        script += """
        echo 'Starting spell server...'
        launchctl unload "$LAUNCH_AGENT_DIR/io.joro.shaw-spell.spellserver.plist" 2>/dev/null || true
        launchctl load "$LAUNCH_AGENT_DIR/io.joro.shaw-spell.spellserver.plist"

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

        // Execute installation script
        if systemWide {
            // Use AppleScript for sudo
            let appleScript = NSAppleScript(source: "do shell script \"/bin/bash \(scriptPath)\" with administrator privileges")
            var errorDict: NSDictionary?
            appleScript?.executeAndReturnError(&errorDict)

            if errorDict != nil {
                DispatchQueue.main.async { [weak self] in
                    self?.showError("Installation cancelled or failed. Please try again.")
                }
                return
            }
        } else {
            let task = Process()
            task.launchPath = "/bin/bash"
            task.arguments = [scriptPath]

            let pipe = Pipe()
            task.standardOutput = pipe
            task.standardError = pipe

            task.launch()
            task.waitUntilExit()

            if task.terminationStatus != 0 {
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                let output = String(data: data, encoding: .utf8) ?? ""

                DispatchQueue.main.async { [weak self] in
                    self?.showError("Installation failed:\n\(output)")
                }
                return
            }
        }

        // Success!
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }

            self.progressIndicator.stopAnimation(nil)
            self.progressIndicator.isHidden = true
            self.statusLabel.stringValue = "Installation complete!"
            self.statusLabel.textColor = .systemGreen

            let alert = NSAlert()
            alert.messageText = "Installation Complete"
            alert.informativeText = """
            Shaw Spell has been installed successfully!

            Next steps:
            1. Restart Dictionary.app to use the dictionaries
            2. The spell server is now running
            3. Configure spell-checking in:
               System Settings > Keyboard > Text Input > Edit...
               Look for 'ShawDict' in the spell checker list
            """
            alert.alertStyle = .informational
            alert.addButton(withTitle: "OK")
            alert.runModal()

            NSApp.terminate(nil)
        }
    }

    func showError(_ message: String) {
        progressIndicator.stopAnimation(nil)
        progressIndicator.isHidden = true
        statusLabel.stringValue = "Installation failed"
        statusLabel.textColor = .systemRed
        installButton.isEnabled = true

        let alert = NSAlert()
        alert.messageText = "Installation Error"
        alert.informativeText = message
        alert.alertStyle = .critical
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }
}
