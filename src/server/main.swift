//
//  main.swift
//  Shavian Spell Server
//
//  NSSpellServer service for English with Shavian support.
//
//  This service handles spell-checking for all English text, supporting both:
//  - Shavian script (𐑐-𐑿): Uses Hunspell dictionary with Shavian wordlist
//  - Latin script (a-z): Delegates to system English spell checker
//
//  Users don't need to switch languages - the service automatically detects
//  the script and routes appropriately.
//

import Foundation

autoreleasepool {
    let server = NSSpellServer()
    let delegate = ShavianSpellChecker()

    // Register all English variants we support
    // Each handles both Latin (delegated to system) and Shavian (our dictionary)
    let languages = [
        "English",
        "en_US",  // US English
        "en_GB"   // UK English (RP)
    ]

    var registered = false
    for lang in languages {
        if server.registerLanguage(lang, byVendor: "Shaw-Spell") {
            NSLog("ShavianSpellServer: Registered \(lang) spell checker")
            registered = true
        } else {
            NSLog("ShavianSpellServer: Failed to register \(lang) spell checker")
        }
    }

    if registered {
        // Set up our delegate to handle spell-checking requests for all variants
        server.delegate = delegate

        // Run the spell server (this blocks)
        NSLog("ShavianSpellServer: Starting service...")
        server.run()

        NSLog("ShavianSpellServer: Service stopped")
        exit(0)
    } else {
        NSLog("ShavianSpellServer: Failed to register any spell checkers")
        exit(1)
    }
}
