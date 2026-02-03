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

        // Load user's personal dictionary (learned words)
        loadPersonalDictionary()

        NSLog("ShavianSpellChecker: Initialized")
    }

    private func loadPersonalDictionary() {
        let spellingDir = (NSHomeDirectory() as NSString).appendingPathComponent("Library/Spelling")

        // Load words from both en_GB and en_US personal dictionaries
        for langCode in ["en_GB", "en_US", "English"] {
            let personalDictPath = (spellingDir as NSString).appendingPathComponent(langCode)

            guard FileManager.default.fileExists(atPath: personalDictPath),
                  let contents = try? String(contentsOfFile: personalDictPath, encoding: .utf8) else {
                continue
            }

            var learnedCount = 0
            for word in contents.components(separatedBy: .newlines) {
                let trimmed = word.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !trimmed.isEmpty else { continue }

                // Determine which dictionary this word belongs to
                let isShavian = containsShavianScript(trimmed)
                guard let handle = isShavian ? shavianHandle : englishHandle else {
                    continue
                }

                // Add to Hunspell runtime dictionary
                _ = trimmed.withCString { cWord in
                    Hunspell_add(handle, cWord)
                }

                // Add to cache
                spellCheckCache.set(trimmed, true)
                learnedCount += 1
            }

            if learnedCount > 0 {
                NSLog("ShavianSpellChecker: Loaded %d learned words from %@", learnedCount, langCode)
            }
        }
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

    // Check if a word is complete (followed by whitespace/punctuation, not at end of string)
    private func isWordComplete(at range: NSRange, in string: String) -> Bool {
        let nsString = string as NSString
        let wordEnd = NSMaxRange(range)

        // Word at the very end of the string is incomplete (user might still be typing)
        if wordEnd >= nsString.length {
            return false
        }

        // Check the character immediately after the word
        let nextCharRange = nsString.rangeOfComposedCharacterSequence(at: wordEnd)
        let nextChar = nsString.substring(with: nextCharRange)

        // Word is complete if followed by whitespace, punctuation, or other non-letter
        if let scalar = nextChar.unicodeScalars.first {
            let codepoint = scalar.value
            // Not a letter = word boundary = complete word
            return !isShavianOrLatinLetter(codepoint)
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
                // Only return complete words (not currently being typed)
                if isWordComplete(at: range, in: string) {
                    // Check if word is preceded by namer dot (·)
                    var finalRange = range
                    if range.location > 0 {
                        let beforeRange = NSRange(location: range.location - 1, length: 1)
                        let charBefore = nsString.substring(with: beforeRange)
                        if charBefore == "·" {  // U+00B7 MIDDLE DOT
                            // Include the namer dot in the word
                            finalRange = NSRange(location: range.location - 1, length: range.length + 1)
                        }
                    }
                    return finalRange
                }
            }

            tokenType = CFStringTokenizerAdvanceToNextToken(tokenizer)
        }

        return NSRange(location: NSNotFound, length: 0)
    }

    // MARK: - Spell Checking

    private func normalizeWord(_ word: String) -> String {
        // Remove soft hyphens (U+00AD) which are invisible formatting characters
        // that shouldn't affect spell-checking
        return word.replacingOccurrences(of: "\u{00AD}", with: "")
    }

    // Check if we're in a proper noun context (after namer dot, before sentence boundary)
    private func isInProperNounContext(at position: Int, in string: String) -> Bool {
        let nsString = string as NSString

        // Look backwards from position to find either a namer dot or sentence boundary
        var searchPos = position - 1
        while searchPos >= 0 {
            let charRange = nsString.rangeOfComposedCharacterSequence(at: searchPos)
            let char = nsString.substring(with: charRange)

            if char == "·" {  // Found namer dot - we're in proper noun context
                return true
            }

            // Check for sentence boundaries
            if char == "." || char == "!" || char == "?" || char == "\n" {
                return false  // Found sentence boundary before namer dot
            }

            searchPos = charRange.location - 1
        }

        return false  // Reached start of string without finding namer dot
    }

    private func checkWord(_ word: String, at position: Int, in fullString: String) -> Bool {
        totalChecks += 1

        // Normalize word (remove soft hyphens, etc.)
        let normalizedWord = normalizeWord(word)

        // Check cache first
        os_signpost(.begin, log: performanceLog, name: "Cache Lookup", signpostID: signpostCacheLookup)
        if let cached = spellCheckCache.get(normalizedWord) {
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
        let isShavian = containsShavianScript(normalizedWord)
        let handle = isShavian ? shavianHandle : englishHandle

        guard let hunspellHandle = handle else {
            return true  // No dictionary loaded for this script, assume correct
        }

        var result = Hunspell_spell(hunspellHandle, normalizedWord)
        var isCorrect = result != 0  // Non-zero means correctly spelled

        // If word starts with namer dot, also check without it (for proper noun context)
        // If word doesn't start with namer dot but is in proper noun context, also check with it
        if !isCorrect && isShavian {
            if normalizedWord.hasPrefix("·") {
                // Word has namer dot but failed - try without it
                let withoutDot = String(normalizedWord.dropFirst())
                result = Hunspell_spell(hunspellHandle, withoutDot)
                isCorrect = result != 0
            } else if isInProperNounContext(at: position, in: fullString) {
                // Word doesn't have namer dot but we're in proper noun context - try with it
                let withDot = "·" + normalizedWord
                result = Hunspell_spell(hunspellHandle, withDot)
                isCorrect = result != 0
            }
        }

        // Store in cache
        spellCheckCache.set(normalizedWord, isCorrect)

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

                if !checkWord(word, at: wordRange.location, in: stringToCheck) {
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
        // Normalize word (strip soft hyphens) before learning
        let normalizedWord = normalizeWord(word)

        let isShavian = containsShavianScript(normalizedWord)
        NSLog("ShavianSpellChecker: didLearnWord called (language: %@, script: %@)",
              language, isShavian ? "Shavian" : "Latin")

        // Determine which dictionary this word belongs to based on script
        guard let handle = isShavian ? shavianHandle : englishHandle else {
            NSLog("ShavianSpellChecker: No dictionary handle available for learned word")
            return
        }

        // Add to Hunspell runtime dictionary
        _ = normalizedWord.withCString { cWord in
            Hunspell_add(handle, cWord)
        }

        // Update cache for this word
        spellCheckCache.set(normalizedWord, true)

        // Persist to user's personal dictionary file
        saveWordToPersonalDictionary(normalizedWord, language: language)

        NSLog("ShavianSpellChecker: Word learned successfully")
    }

    private func saveWordToPersonalDictionary(_ word: String, language: String) {
        let spellingDir = (NSHomeDirectory() as NSString).appendingPathComponent("Library/Spelling")

        // Map language codes to file names
        var langCode = language
        if langCode == "English" || langCode.isEmpty {
            langCode = "en_GB"  // Default to GB
        }

        let personalDictPath = (spellingDir as NSString).appendingPathComponent(langCode)

        // Read existing words
        var words: Set<String> = []
        if FileManager.default.fileExists(atPath: personalDictPath),
           let contents = try? String(contentsOfFile: personalDictPath, encoding: .utf8) {
            words = Set(contents.components(separatedBy: .newlines).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) })
        }

        // Add new word
        words.insert(word)
        words.remove("")  // Remove empty lines

        // Write back to file
        let sortedWords = words.sorted().joined(separator: "\n")
        do {
            try sortedWords.write(toFile: personalDictPath, atomically: true, encoding: .utf8)
            NSLog("ShavianSpellChecker: Saved learned word '%@' to %@", word, langCode)
        } catch {
            NSLog("ShavianSpellChecker: Failed to save word to %@: %@", langCode, error.localizedDescription)
        }
    }

    @objc func spellServer(_ sender: NSSpellServer,
                    didForgetWord word: String,
                    inLanguage language: String) {
        // Normalize word (strip soft hyphens) before forgetting
        let normalizedWord = normalizeWord(word)

        let isShavian = containsShavianScript(normalizedWord)
        NSLog("ShavianSpellChecker: didForgetWord called (language: %@, script: %@)",
              language, isShavian ? "Shavian" : "Latin")

        // Determine which dictionary this word belongs to based on script
        guard let handle = isShavian ? shavianHandle : englishHandle else {
            NSLog("ShavianSpellChecker: No dictionary handle available for forgotten word")
            return
        }

        // Remove from Hunspell runtime dictionary
        _ = normalizedWord.withCString { cWord in
            Hunspell_remove(handle, cWord)
        }

        // Invalidate cache for this word (mark as incorrect)
        spellCheckCache.set(normalizedWord, false)

        // Remove from user's personal dictionary file
        removeWordFromPersonalDictionary(normalizedWord, language: language)

        NSLog("ShavianSpellChecker: Word forgotten successfully")
    }

    private func removeWordFromPersonalDictionary(_ word: String, language: String) {
        let spellingDir = (NSHomeDirectory() as NSString).appendingPathComponent("Library/Spelling")

        // Map language codes to file names
        var langCode = language
        if langCode == "English" || langCode.isEmpty {
            langCode = "en_GB"  // Default to GB
        }

        let personalDictPath = (spellingDir as NSString).appendingPathComponent(langCode)

        guard FileManager.default.fileExists(atPath: personalDictPath),
              let contents = try? String(contentsOfFile: personalDictPath, encoding: .utf8) else {
            return
        }

        // Read existing words and remove the specified word
        var words = Set(contents.components(separatedBy: .newlines).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) })
        words.remove(word)
        words.remove("")  // Remove empty lines

        // Write back to file
        let sortedWords = words.sorted().joined(separator: "\n")
        do {
            try sortedWords.write(toFile: personalDictPath, atomically: true, encoding: .utf8)
            NSLog("ShavianSpellChecker: Removed word '%@' from %@", word, langCode)
        } catch {
            NSLog("ShavianSpellChecker: Failed to remove word from %@: %@", langCode, error.localizedDescription)
        }
    }
}
