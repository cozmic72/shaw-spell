//
//  ShavianSpellChecker.swift
//  Shavian Spell Server
//
//  Implements spell-checking for English with both Latin and Shavian scripts.
//

import Foundation
import os.log

private let logger = OSLog(subsystem: "io.joro.Shaw-Spell", category: "SpellChecker")

// Shavian Unicode range: U+10450 to U+1047F
private let shavianStart: UInt32 = 0x10450
private let shavianEnd: UInt32 = 0x1047F

class ShavianSpellChecker: NSObject, NSSpellServerDelegate {
    private var shavianHandle: OpaquePointer?
    private var englishHandle: OpaquePointer?

    override init() {
        super.init()

        // Determine which Shavian dialect dictionary to load
        var dialect = ProcessInfo.processInfo.environment["SHAVIAN_DIALECT"]
        if dialect == nil {
            dialect = UserDefaults.standard.string(forKey: "ShavianDialect")
        }
        if dialect == nil {
            dialect = "gb"  // Default to British
        }

        let spellingDir = (NSHomeDirectory() as NSString).appendingPathComponent("Library/Spelling")

        // Try dialect-specific dictionary first (shaw-gb.dic or shaw-us.dic)
        var shawDicPath = (spellingDir as NSString).appendingPathComponent("shaw-\(dialect!).dic")
        var shawAffPath = (spellingDir as NSString).appendingPathComponent("shaw-\(dialect!).aff")

        // Fall back to generic shaw.dic if dialect-specific not found
        if !FileManager.default.fileExists(atPath: shawDicPath) {
            shawDicPath = (spellingDir as NSString).appendingPathComponent("shaw.dic")
            shawAffPath = (spellingDir as NSString).appendingPathComponent("shaw.aff")
        }

        if FileManager.default.fileExists(atPath: shawDicPath) &&
           FileManager.default.fileExists(atPath: shawAffPath) {
            shavianHandle = Hunspell_create(shawAffPath, shawDicPath)
            if shavianHandle != nil {
                NSLog("ShavianSpellChecker: Loaded Shavian dictionary (\(dialect!)) from \(shawDicPath)")
                os_log("Loaded Shavian dictionary", log: logger, type: .info)
            } else {
                NSLog("ShavianSpellChecker: Failed to load Shavian dictionary")
            }
        } else {
            NSLog("ShavianSpellChecker: Shavian dictionary files not found at \(shawDicPath)")
        }

        // Initialize Hunspell with English dictionary
        let enDicPath = (NSHomeDirectory() as NSString).appendingPathComponent("Library/Spelling/en_GB.dic")
        let enAffPath = (NSHomeDirectory() as NSString).appendingPathComponent("Library/Spelling/en_GB.aff")

        if FileManager.default.fileExists(atPath: enDicPath) &&
           FileManager.default.fileExists(atPath: enAffPath) {
            englishHandle = Hunspell_create(enAffPath, enDicPath)
            if englishHandle != nil {
                NSLog("ShavianSpellChecker: Loaded English dictionary from \(enDicPath)")
            } else {
                NSLog("ShavianSpellChecker: Failed to load English dictionary")
            }
        } else {
            NSLog("ShavianSpellChecker: English dictionary files not found at \(enDicPath)")
        }

        NSLog("ShavianSpellChecker: Initialized")
    }

    deinit {
        if let handle = shavianHandle {
            Hunspell_destroy(handle)
        }
        if let handle = englishHandle {
            Hunspell_destroy(handle)
        }
    }

    // MARK: - Script Detection

    private func containsShavianScript(_ string: String) -> Bool {
        for scalar in string.unicodeScalars {
            let value = scalar.value
            if value >= shavianStart && value <= shavianEnd {
                return true
            }
        }
        return false
    }

    // MARK: - Word Boundary Detection

    private func isShavianOrLatinLetter(_ codepoint: UInt32) -> Bool {
        // Latin letters (a-z, A-Z)
        if (codepoint >= 0x0041 && codepoint <= 0x005A) ||  // A-Z
           (codepoint >= 0x0061 && codepoint <= 0x007A) {   // a-z
            return true
        }
        // Shavian letters (𐑐-𐑿)
        if codepoint >= shavianStart && codepoint <= shavianEnd {
            return true
        }
        // Hyphen (part of compound words like colour-bar)
        if codepoint == 0x002D {  // HYPHEN-MINUS
            return true
        }
        // Namer dot (· U+00B7) - marks proper nouns in Shavian
        if codepoint == 0x00B7 {  // MIDDLE DOT
            return true
        }
        return false
    }

    private func findNextWord(in string: String, startingAt start: Int) -> NSRange {
        guard start < string.count else {
            return NSRange(location: NSNotFound, length: 0)
        }

        let nsString = string as NSString
        var pos = start
        var wordStart: Int?

        // Skip non-letters to find word start
        while pos < nsString.length {
            let range = nsString.rangeOfComposedCharacterSequence(at: pos)
            let character = nsString.substring(with: range)

            if let scalar = character.unicodeScalars.first {
                let codepoint = scalar.value

                if isShavianOrLatinLetter(codepoint) {
                    wordStart = pos
                    break
                }
            }

            pos = NSMaxRange(range)
        }

        guard let start = wordStart else {
            return NSRange(location: NSNotFound, length: 0)
        }

        // Find word end
        pos = start
        var wordEnd = start

        while pos < nsString.length {
            let range = nsString.rangeOfComposedCharacterSequence(at: pos)
            let character = nsString.substring(with: range)

            if let scalar = character.unicodeScalars.first {
                let codepoint = scalar.value

                if !isShavianOrLatinLetter(codepoint) {
                    break
                }

                wordEnd = NSMaxRange(range)
                pos = wordEnd
            } else {
                break
            }
        }

        return NSRange(location: start, length: wordEnd - start)
    }

    // MARK: - Spell Checking

    private func checkWord(_ word: String) -> Bool {
        // Determine which dictionary to use based on script
        let isShavian = containsShavianScript(word)
        let handle = isShavian ? shavianHandle : englishHandle

        guard let hunspellHandle = handle else {
            return true  // No dictionary loaded for this script, assume correct
        }

        let result = Hunspell_spell(hunspellHandle, word)
        return result != 0  // Non-zero means correctly spelled
    }

    // MARK: - NSSpellServerDelegate

    func spellServer(_ sender: NSSpellServer,
                    findMisspelledWordIn stringToCheck: String,
                    language: String,
                    wordCount: UnsafeMutablePointer<Int>,
                    countOnly: Bool) -> NSRange {

        // Iterate through all words, checking both Shavian and Latin
        var position = 0
        var count = 0

        while position < stringToCheck.count {
            let wordRange = findNextWord(in: stringToCheck, startingAt: position)

            if wordRange.location == NSNotFound {
                break  // No more words
            }

            count += 1

            if !countOnly {
                let word = (stringToCheck as NSString).substring(with: wordRange)

                if !checkWord(word) {
                    // Found misspelled word
                    wordCount.pointee = count
                    return wordRange
                }
            }

            // Move to next word
            position = NSMaxRange(wordRange)
        }

        wordCount.pointee = count
        return NSRange(location: NSNotFound, length: 0)  // No misspelled words found
    }

    func spellServer(_ sender: NSSpellServer,
                    suggestGuessesForWord word: String,
                    inLanguage language: String) -> [String]? {

        // Determine which dictionary to use based on script
        let isShavian = containsShavianScript(word)
        guard let handle = isShavian ? shavianHandle : englishHandle else {
            return []
        }

        var suggestions: UnsafeMutablePointer<UnsafeMutablePointer<CChar>?>?
        let count = Hunspell_suggest(handle, &suggestions, word)

        var results: [String] = []
        if let suggestionList = suggestions {
            let maxSuggestions = min(Int(count), 10)  // Limit to 10 suggestions
            for i in 0..<maxSuggestions {
                if let cString = suggestionList[i] {
                    if let suggestion = String(utf8String: cString) {
                        results.append(suggestion)
                    }
                }
            }

            // Free Hunspell suggestions
            Hunspell_free_list(handle, &suggestions, count)
        }

        return results
    }

    @objc func spellServer(_ sender: NSSpellServer,
                    didLearnWord word: String,
                    inLanguage language: String) {
        // Determine which dictionary this word belongs to based on script
        let isShavian = containsShavianScript(word)
        guard let handle = isShavian ? shavianHandle : englishHandle else {
            return
        }

        // Add to Hunspell runtime dictionary
        _ = word.withCString { cWord in
            Hunspell_add(handle, cWord)
        }
    }

    @objc func spellServer(_ sender: NSSpellServer,
                    didForgetWord word: String,
                    inLanguage language: String) {
        // Determine which dictionary this word belongs to based on script
        let isShavian = containsShavianScript(word)
        guard let handle = isShavian ? shavianHandle : englishHandle else {
            return
        }

        // Remove from Hunspell runtime dictionary
        _ = word.withCString { cWord in
            Hunspell_remove(handle, cWord)
        }
    }
}
