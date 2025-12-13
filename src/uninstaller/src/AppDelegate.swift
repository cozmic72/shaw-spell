//
//  AppDelegate.swift
//  Shaw-Spell Uninstaller
//
//  Main application delegate for the uninstaller.
//

import Cocoa

class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var uninstallButton: NSButton!
    var progressIndicator: NSProgressIndicator!
    var statusLabel: NSTextField!
    var componentsTextView: NSTextView!

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Create the main window
        let windowRect = NSRect(x: 0, y: 0, width: 600, height: 450)
        window = NSWindow(contentRect: windowRect,
                         styleMask: [.titled, .closable, .miniaturizable],
                         backing: .buffered,
                         defer: false)
        window.title = "Uninstall Shaw-Spell"
        window.center()

        guard let contentView = window.contentView else { return }

        // Title label
        let titleLabel = NSTextField(frame: NSRect(x: 20, y: 390, width: 560, height: 40))
        titleLabel.stringValue = "Shaw-Spell Uninstaller"
        titleLabel.isBezeled = false
        titleLabel.drawsBackground = false
        titleLabel.isEditable = false
        titleLabel.isSelectable = false
        titleLabel.font = NSFont.boldSystemFont(ofSize: 24)
        titleLabel.alignment = .center
        contentView.addSubview(titleLabel)

        // Subtitle
        let subtitleLabel = NSTextField(frame: NSRect(x: 20, y: 360, width: 560, height: 20))
        subtitleLabel.stringValue = "Remove all Shaw-Spell components from your system"
        subtitleLabel.isBezeled = false
        subtitleLabel.drawsBackground = false
        subtitleLabel.isEditable = false
        subtitleLabel.isSelectable = false
        subtitleLabel.font = NSFont.systemFont(ofSize: 12)
        subtitleLabel.alignment = .center
        subtitleLabel.textColor = .secondaryLabelColor
        contentView.addSubview(subtitleLabel)

        // Info label
        let infoLabel = NSTextField(frame: NSRect(x: 20, y: 330, width: 560, height: 20))
        infoLabel.stringValue = "The following components will be removed:"
        infoLabel.isBezeled = false
        infoLabel.drawsBackground = false
        infoLabel.isEditable = false
        infoLabel.isSelectable = false
        infoLabel.font = NSFont.boldSystemFont(ofSize: 14)
        contentView.addSubview(infoLabel)

        // Components text view (scrollable)
        let scrollView = NSScrollView(frame: NSRect(x: 20, y: 120, width: 560, height: 200))
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = false
        scrollView.autohidesScrollers = true
        scrollView.borderType = .bezelBorder

        componentsTextView = NSTextView(frame: NSRect(x: 0, y: 0, width: 545, height: 200))
        componentsTextView.isEditable = false
        componentsTextView.isSelectable = true
        componentsTextView.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
        componentsTextView.textContainerInset = NSSize(width: 5, height: 5)

        // Scan for installed components
        let components = scanInstalledComponents()
        componentsTextView.string = components

        scrollView.documentView = componentsTextView
        contentView.addSubview(scrollView)

        // Status label
        statusLabel = NSTextField(frame: NSRect(x: 20, y: 80, width: 560, height: 20))
        statusLabel.stringValue = "Ready to uninstall"
        statusLabel.isBezeled = false
        statusLabel.drawsBackground = false
        statusLabel.isEditable = false
        statusLabel.isSelectable = false
        statusLabel.alignment = .center
        statusLabel.textColor = .secondaryLabelColor
        contentView.addSubview(statusLabel)

        // Progress indicator
        progressIndicator = NSProgressIndicator(frame: NSRect(x: 200, y: 50, width: 200, height: 20))
        progressIndicator.style = .bar
        progressIndicator.isIndeterminate = true
        progressIndicator.isHidden = true
        contentView.addSubview(progressIndicator)

        // Uninstall button
        uninstallButton = NSButton(frame: NSRect(x: 240, y: 10, width: 120, height: 30))
        uninstallButton.title = "Uninstall"
        uninstallButton.bezelStyle = .rounded
        uninstallButton.keyEquivalent = "\r"
        uninstallButton.target = self
        uninstallButton.action = #selector(uninstallButtonClicked)
        contentView.addSubview(uninstallButton)

        // Check if anything is installed
        if components.contains("Nothing found") {
            uninstallButton.isEnabled = false
            statusLabel.stringValue = "Shaw-Spell is not installed"
        }

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func scanInstalledComponents() -> String {
        var output = ""
        var foundAnything = false

        let homeDir = NSHomeDirectory()

        // Check dictionaries
        let userDictDir = (homeDir as NSString).appendingPathComponent("Library/Dictionaries")
        if let dictFiles = try? FileManager.default.contentsOfDirectory(atPath: userDictDir) {
            let shavianDicts = dictFiles.filter { $0.contains("Shavian") || $0.contains("shavian") || $0.contains("Shaw") || $0.contains("shaw") }
            if !shavianDicts.isEmpty {
                foundAnything = true
                output += "Dictionaries:\n"
                for dict in shavianDicts.sorted() {
                    output += "  • \(dict)\n"
                }
                output += "\n"
            }
        }

        // Check Hunspell dictionaries
        let userSpellingDir = (homeDir as NSString).appendingPathComponent("Library/Spelling")
        if let spellingFiles = try? FileManager.default.contentsOfDirectory(atPath: userSpellingDir) {
            let shawFiles = spellingFiles.filter { $0.hasPrefix("io.joro.shaw-spell.") }
            if !shawFiles.isEmpty {
                foundAnything = true
                output += "Hunspell Dictionaries:\n"
                for file in shawFiles.sorted() {
                    output += "  • \(file)\n"
                }
                output += "\n"
            }
        }

        // Check spell server
        let userServicePath = (homeDir as NSString).appendingPathComponent("Library/Services/Shaw-Spell.service")
        if FileManager.default.fileExists(atPath: userServicePath) {
            foundAnything = true
            output += "Spell Server:\n"
            output += "  • Shaw-Spell.service\n\n"
        }

        // Check LaunchAgent
        let launchAgentPath = (homeDir as NSString).appendingPathComponent("Library/LaunchAgents/io.joro.Shaw-Spell.plist")
        if FileManager.default.fileExists(atPath: launchAgentPath) {
            foundAnything = true
            output += "LaunchAgent:\n"
            output += "  • io.joro.Shaw-Spell.plist\n\n"
        }

        if !foundAnything {
            output = "Nothing found - Shaw-Spell does not appear to be installed.\n"
        } else {
            output += "Note: Log files and preferences will not be removed.\n"
            output += "See the completion message for optional cleanup."
        }

        return output
    }

    @objc func uninstallButtonClicked() {
        // Confirm uninstallation
        let alert = NSAlert()
        alert.messageText = "Confirm Uninstallation"
        alert.informativeText = "Are you sure you want to remove Shaw-Spell from your system? This cannot be undone."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Uninstall")
        alert.addButton(withTitle: "Cancel")

        if alert.runModal() != .alertFirstButtonReturn {
            return
        }

        // Disable button and show progress
        uninstallButton.isEnabled = false
        progressIndicator.isHidden = false
        progressIndicator.startAnimation(nil)
        statusLabel.stringValue = "Uninstalling..."

        // Perform uninstallation in background
        DispatchQueue.global(qos: .default).async { [weak self] in
            self?.performUninstallation()
        }
    }

    func performUninstallation() {
        let homeDir = NSHomeDirectory()

        // Build uninstallation script
        var script = """
        #!/bin/bash
        set -e

        """

        // Stop LaunchAgent
        script += """
        echo 'Stopping spell server...'
        launchctl unload "\(homeDir)/Library/LaunchAgents/io.joro.Shaw-Spell.plist" 2>/dev/null || true
        rm -f "\(homeDir)/Library/LaunchAgents/io.joro.Shaw-Spell.plist"

        """

        // Remove components
        script += """
        echo 'Removing dictionaries...'
        rm -rf "\(homeDir)/Library/Dictionaries/"*Shavian* 2>/dev/null || true
        rm -rf "\(homeDir)/Library/Dictionaries/"*shavian* 2>/dev/null || true
        rm -rf "\(homeDir)/Library/Dictionaries/"*Shaw* 2>/dev/null || true
        rm -rf "\(homeDir)/Library/Dictionaries/"*shaw* 2>/dev/null || true
        touch "\(homeDir)/Library/Dictionaries"

        echo 'Removing Hunspell dictionaries...'
        rm -f "\(homeDir)/Library/Spelling/io.joro.shaw-spell."* 2>/dev/null || true

        echo 'Removing spell server...'
        rm -rf "\(homeDir)/Library/Services/Shaw-Spell.service" 2>/dev/null || true

        """

        // Update services
        script += """
        echo 'Updating system services...'
        /System/Library/CoreServices/pbs -update 2>/dev/null || true

        echo 'Uninstallation complete!'
        """

        // Write script to temporary file
        let scriptPath = "/tmp/shaw-spell-uninstall.sh"

        do {
            try script.write(toFile: scriptPath, atomically: true, encoding: .utf8)
        } catch {
            DispatchQueue.main.async { [weak self] in
                self?.showError("Failed to create uninstallation script: \(error.localizedDescription)")
            }
            return
        }

        // Make script executable
        chmod(scriptPath, 0o755)

        // Execute uninstallation script
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
                self?.showError("Uninstallation failed:\n\(output)")
            }
            return
        }

        // Success!
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }

            self.progressIndicator.stopAnimation(nil)
            self.progressIndicator.isHidden = true
            self.statusLabel.stringValue = "Uninstallation complete!"
            self.statusLabel.textColor = .systemGreen

            let alert = NSAlert()
            alert.messageText = "Uninstallation Complete"
            alert.informativeText = """
            Shaw-Spell has been removed from your system.

            Optional cleanup:
            • Log file: ~/Library/Logs/Shaw-Spell.log
            • Preference: defaults delete ShavianDialect

            Please restart Dictionary.app if it's running.
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
        statusLabel.stringValue = "Uninstallation failed"
        statusLabel.textColor = .systemRed
        uninstallButton.isEnabled = true

        let alert = NSAlert()
        alert.messageText = "Uninstallation Error"
        alert.informativeText = message
        alert.alertStyle = .critical
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }
}
