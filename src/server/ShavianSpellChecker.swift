//
//  ShavianSpellChecker.swift
//  Shavian Spell Server
//
//  Implements spell-checking for English with both Latin and Shavian scripts.
//

import Foundation
import os.log

private let logger = OSLog(subsystem: "io.joro.Shaw-Spell", category: "SpellChecker")
private let performanceLog = OSLog(subsystem: "io.joro.Shaw-Spell", category: "Performance")

// Performance instrumentation signpost IDs
private let signpostWordExtraction = OSSignpostID(log: performanceLog)
private let signpostHunspellLookup = OSSignpostID(log: performanceLog)
private let signpostCacheLookup = OSSignpostID(log: performanceLog)

// Shavian Unicode range: U+10450 to U+1047F
private let shavianStart: UInt32 = 0x10450
private let shavianEnd: UInt32 = 0x1047F

// LRU Cache for spell-check results
private class SpellCheckCache {
    private let capacity: Int
    private var cache: [String: Bool] = [:]
    private var accessOrder: [String] = []

    init(capacity: Int = 2000) {
        self.capacity = capacity
    }

    func get(_ word: String) -> Bool? {
        guard let result = cache[word] else {
            return nil
        }

        // Update LRU order
        if let index = accessOrder.firstIndex(of: word) {
            accessOrder.remove(at: index)
        }
        accessOrder.append(word)

        return result
    }

    func set(_ word: String, _ isCorrect: Bool) {
        // If already exists, update access order
        if cache[word] != nil {
            if let index = accessOrder.firstIndex(of: word) {
                accessOrder.remove(at: index)
            }
        } else if cache.count >= capacity {
            // Evict oldest entry
            if let oldest = accessOrder.first {
                cache.removeValue(forKey: oldest)
                accessOrder.removeFirst()
            }
        }

        cache[word] = isCorrect
        accessOrder.append(word)
    }

    func clear() {
        cache.removeAll()
        accessOrder.removeAll()
    }

    var hitCount: Int {
        return cache.count
    }
}

class ShavianSpellChecker: NSObject, NSSpellServerDelegate {
    private var shavianHandle: OpaquePointer?
    private var englishHandle: OpaquePointer?
    private var spellCheckCache = SpellCheckCache(capacity: 2000)

    // Performance statistics
    private var cacheHits: Int = 0
    private var cacheMisses: Int = 0
    private var totalChecks: Int = 0

    // Cache the last string we checked to avoid re-tokenizing on repeated calls
    private var lastCheckedString: String?
    private var lastTokenizer: CFStringTokenizer?

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

        // Load dialect-specific dictionary
        let shawDicPath = (spellingDir as NSString).appendingPathComponent("io.joro.shaw-spell.shavian-\(dialect!).dic")
        let shawAffPath = (spellingDir as NSString).appendingPathComponent("io.joro.shaw-spell.shavian-\(dialect!).aff")

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
        let enDicPath = (NSHomeDirectory() as NSString).appendingPathComponent("Library/Spelling/io.joro.shaw-spell.en_GB.dic")
        let enAffPath = (NSHomeDirectory() as NSString).appendingPathComponent("Library/Spelling/io.joro.shaw-spell.en_GB.aff")

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

    // Optimized word extraction using CFStringTokenizer - incremental
    private func findNextWord(in string: String, startingAt start: Int) -> NSRange {
        os_signpost(.begin, log: performanceLog, name: "Word Extraction", signpostID: signpostWordExtraction)
        defer {
            os_signpost(.end, log: performanceLog, name: "Word Extraction", signpostID: signpostWordExtraction)
        }

        guard start < string.count else {
            return NSRange(location: NSNotFound, length: 0)
        }

        let nsString = string as NSString
        let stringRange = CFRange(location: start, length: nsString.length - start)

        // Create tokenizer starting from the given position
        guard let tokenizer = CFStringTokenizerCreate(
            kCFAllocatorDefault,
            nsString as CFString,
            stringRange,
            kCFStringTokenizerUnitWordBoundary,
            nil
        ) else {
            return NSRange(location: NSNotFound, length: 0)
        }

        // Get the first word token at or after start position
        var tokenType = CFStringTokenizerAdvanceToNextToken(tokenizer)
        while tokenType != CFStringTokenizerTokenType(rawValue: 0) {
            let tokenRange = CFStringTokenizerGetCurrentTokenRange(tokenizer)
            let range = NSRange(location: tokenRange.location, length: tokenRange.length)
            let word = nsString.substring(with: range)

            // Only return words that contain Shavian or Latin letters
            var containsLetter = false
            for scalar in word.unicodeScalars {
                if isShavianOrLatinLetter(scalar.value) {
                    containsLetter = true
                    break
                }
            }

            if containsLetter {
                return range
            }

            tokenType = CFStringTokenizerAdvanceToNextToken(tokenizer)
        }

        return NSRange(location: NSNotFound, length: 0)
    }

    // MARK: - Spell Checking

    private func checkWord(_ word: String) -> Bool {
        totalChecks += 1

        // Check cache first
        os_signpost(.begin, log: performanceLog, name: "Cache Lookup", signpostID: signpostCacheLookup)
        if let cached = spellCheckCache.get(word) {
            cacheHits += 1
            os_signpost(.end, log: performanceLog, name: "Cache Lookup", signpostID: signpostCacheLookup, "Hit")
            return cached
        }
        cacheMisses += 1
        os_signpost(.end, log: performanceLog, name: "Cache Lookup", signpostID: signpostCacheLookup, "Miss")

        // Cache miss - check with Hunspell
        os_signpost(.begin, log: performanceLog, name: "Hunspell Lookup", signpostID: signpostHunspellLookup)
        defer {
            os_signpost(.end, log: performanceLog, name: "Hunspell Lookup", signpostID: signpostHunspellLookup)
        }

        // Determine which dictionary to use based on script
        let isShavian = containsShavianScript(word)
        let handle = isShavian ? shavianHandle : englishHandle

        guard let hunspellHandle = handle else {
            return true  // No dictionary loaded for this script, assume correct
        }

        let result = Hunspell_spell(hunspellHandle, word)
        let isCorrect = result != 0  // Non-zero means correctly spelled

        // Store in cache
        spellCheckCache.set(word, isCorrect)

        return isCorrect
    }

    // MARK: - NSSpellServerDelegate

    func spellServer(_ sender: NSSpellServer,
                    findMisspelledWordIn stringToCheck: String,
                    language: String,
                    wordCount: UnsafeMutablePointer<Int>,
                    countOnly: Bool) -> NSRange {

        // Incremental word-by-word checking - only check from current position forward
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

        // Invalidate cache for this word
        spellCheckCache.set(word, true)
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

        // Invalidate cache for this word
        spellCheckCache.set(word, false)
    }
}
