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

// MARK: - False-positive heuristics
//
// These run ONLY on tokens Hunspell has already rejected, so clean prose pays
// nothing. Each rule is an independent pattern; we compose them with `|` and
// compile once. A token matching any branch is treated as correctly spelled.
//
// Rules (in order of the union):
//   1. All non-letter junk: no Latin, no Shavian letters. Catches "42",
//      "---", "(&*)!", "3.14", etc. — stray punctuation / number tokens
//      that Hunspell would otherwise reject.
//   2. Acronyms: 2–6 uppercase ASCII letters, optional plural `s`. "URL",
//      "NASA", "PhDs", "URLs". We cap at 6 to avoid accepting e.g.
//      all-caps shouting of real misspellings.
//   3. Alphanumeric identifiers: contains at least one letter AND one
//      digit. Catches "H2O", "CO2", "iPhone15", "foo_bar2", variable
//      names, chemical formulas, SKU codes.
private let tokenAcceptPatterns: [String] = [
    // 1. Contains no Latin (A-Z/a-z) and no Shavian letter.
    "^[^A-Za-z\u{10450}-\u{1047F}]+$",
    // 2. Acronym, possibly pluralised.
    "^[A-Z]{2,6}s?$",
    // 3. Alphanumeric mix (letter + digit, any order).
    #"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_]+$"#,
]

private let tokenAcceptRegex: NSRegularExpression = {
    let combined = tokenAcceptPatterns.map { "(?:\($0))" }.joined(separator: "|")
    return try! NSRegularExpression(pattern: combined, options: [])
}()

// Full-string scan for spans that should never be spell-checked as words.
// CFStringTokenizer splits "https://example.com" into ["https", "example",
// "com"] before we see them, so a per-token regex can't catch URIs. We scan
// the whole input once and remember the ranges; any token overlapping a
// skip-range is accepted on the failure path.
//
// Rough-and-ready — aims for ~95% recall on real-world URIs/emails without
// trying to be an RFC-conformant parser.
private let skipSpanPatterns: [String] = [
    // Email: anything@anything.anything (one dot minimum after @).
    #"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"#,
    // URI with explicit scheme (http, https, ftp, mailto, file, etc.)
    // or a leading www. — eat everything up to whitespace.
    #"(?:[a-zA-Z][a-zA-Z0-9+\-.]*://|www\.)\S+"#,
    // Bare domain: at least one dot, ends in a known-ish TLD. This is the
    // sloppy one — covers foo.com, example.co.uk, news.bbc.co.uk, etc.
    // Case-insensitive via (?i).
    #"(?i)\b(?:[a-z0-9\-]+\.)+(?:com|org|net|edu|gov|mil|io|co|uk|us|de|fr|jp|cn|ru|br|in|au|ca|nz|ch|nl|se|no|dk|fi|es|it|pl|be|at|ie|info|biz|name|pro|dev|app|ai|xyz|co\.uk|co\.nz|co\.jp|ac\.uk|gov\.uk|org\.uk|com\.au)\b(?:/\S*)?"#,
]

private let skipSpanRegex: NSRegularExpression = {
    let combined = skipSpanPatterns.map { "(?:\($0))" }.joined(separator: "|")
    return try! NSRegularExpression(pattern: combined, options: [])
}()

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

        guard let scalar = nextChar.unicodeScalars.first else {
            return false
        }
        let codepoint = scalar.value

        // Mid-typing email: 'joro@' should not be flagged before the user
        // finishes typing the domain (otherwise autocorrect kicks in on @
        // and rewrites the local part to a real word — e.g. joro→jorum).
        if codepoint == 0x40 {  // @
            return false
        }

        // Mid-typing bare URL: 'example.c' (period followed by a letter
        // with no whitespace) probably means the user is in the middle of
        // typing example.com. Hold off until they finish; the URI/email
        // pre-scan will then accept the whole span. We only fire this
        // when a letter follows the dot, so sentence-ending periods like
        // 'fine.' or 'fine. Next' still complete normally.
        if codepoint == 0x2E && wordEnd + nextCharRange.length < nsString.length {  // .
            let afterDotIdx = wordEnd + nextCharRange.length
            let afterDotRange = nsString.rangeOfComposedCharacterSequence(at: afterDotIdx)
            let afterDot = nsString.substring(with: afterDotRange)
            if let nextScalar = afterDot.unicodeScalars.first,
               isShavianOrLatinLetter(nextScalar.value) {
                return false
            }
        }

        // Otherwise: not-a-letter means word boundary (complete word).
        return !isShavianOrLatinLetter(codepoint)
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
        // Strip soft hyphens (invisible formatting) and fold curly apostrophe
        // to ASCII. The dictionaries store contractions with U+0027, but macOS
        // smart-quotes substitutes U+2019 as the user types.
        return word
            .replacingOccurrences(of: "\u{00AD}", with: "")
            .replacingOccurrences(of: "\u{2019}", with: "'")
    }

    private func checkWord(_ word: String,
                           at position: Int,
                           in fullString: String,
                           tokenRange: NSRange,
                           skipRanges: [NSRange]) -> Bool {
        totalChecks += 1

        // Normalize word (remove soft hyphens, etc.)
        let normalizedWord = normalizeWord(word)

        // Cache stores the raw Hunspell verdict only. Heuristic accepts
        // are context-dependent (a token may be inside a URI here and
        // standalone elsewhere) so they run fresh every time.
        os_signpost(.begin, log: performanceLog, name: "Cache Lookup", signpostID: signpostCacheLookup)
        let cachedHunspell = spellCheckCache.get(normalizedWord)
        if cachedHunspell == true {
            cacheHits += 1
            os_signpost(.end, log: performanceLog, name: "Cache Lookup", signpostID: signpostCacheLookup, "Hit")
            return true
        }
        if cachedHunspell == nil {
            cacheMisses += 1
            os_signpost(.end, log: performanceLog, name: "Cache Lookup", signpostID: signpostCacheLookup, "Miss")
        } else {
            cacheHits += 1
            os_signpost(.end, log: performanceLog, name: "Cache Lookup", signpostID: signpostCacheLookup, "Hit")
        }

        var isCorrect: Bool
        if let cached = cachedHunspell {
            isCorrect = cached
        } else {
            os_signpost(.begin, log: performanceLog, name: "Hunspell Lookup", signpostID: signpostHunspellLookup)
            defer {
                os_signpost(.end, log: performanceLog, name: "Hunspell Lookup", signpostID: signpostHunspellLookup)
            }

            let isShavian = containsShavianScript(normalizedWord)
            let handle = isShavian ? shavianHandle : englishHandle

            guard let hunspellHandle = handle else {
                return true  // No dictionary loaded for this script, assume correct
            }

            var result = Hunspell_spell(hunspellHandle, normalizedWord)
            isCorrect = result != 0

            // Shavian namer dot is optional — retry with/without.
            if !isCorrect && isShavian {
                if normalizedWord.hasPrefix("·") {
                    let withoutDot = String(normalizedWord.dropFirst())
                    result = Hunspell_spell(hunspellHandle, withoutDot)
                    isCorrect = result != 0
                } else {
                    let withDot = "·" + normalizedWord
                    result = Hunspell_spell(hunspellHandle, withDot)
                    isCorrect = result != 0
                }
            }

            spellCheckCache.set(normalizedWord, isCorrect)
        }

        // Failure-path heuristics. Run every time (not cached) because
        // skipRanges depends on the containing string.
        if !isCorrect && isAcceptableFalsePositive(normalizedWord,
                                                   tokenRange: tokenRange,
                                                   skipRanges: skipRanges) {
            return true
        }

        return isCorrect
    }

    // Full-string pass to locate URI/email spans. Returns the ranges we
    // treat as off-limits for per-token spell-checking.
    private func nonSpellcheckableRanges(in string: String) -> [NSRange] {
        let ns = string as NSString
        let full = NSRange(location: 0, length: ns.length)
        let matches = skipSpanRegex.matches(in: string, options: [], range: full)
        return matches.map { $0.range }
    }

    // Decide whether a Hunspell-rejected token should be accepted anyway.
    // See tokenAcceptPatterns / skipSpanPatterns at top of file for rules.
    private func isAcceptableFalsePositive(_ word: String,
                                           tokenRange: NSRange,
                                           skipRanges: [NSRange]) -> Bool {
        // Inside a URI/email span? Accept.
        for span in skipRanges {
            if NSIntersectionRange(span, tokenRange).length > 0 {
                return true
            }
        }

        // Per-token pattern union (no-letters / acronym / alphanumeric).
        let ns = word as NSString
        let full = NSRange(location: 0, length: ns.length)
        if tokenAcceptRegex.firstMatch(in: word, options: [], range: full) != nil {
            return true
        }

        return false
    }

    // MARK: - NSSpellServerDelegate

    func spellServer(_ sender: NSSpellServer,
                    findMisspelledWordIn stringToCheck: String,
                    language: String,
                    wordCount: UnsafeMutablePointer<Int>,
                    countOnly: Bool) -> NSRange {

        // One scan per request to find URI/email spans we should never
        // flag. Cheap on clean text (no matches) and lets checkWord skip
        // tokens that CFStringTokenizer has already split out of a URI.
        let skipRanges = countOnly ? [] : nonSpellcheckableRanges(in: stringToCheck)

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

                if !checkWord(word,
                              at: wordRange.location,
                              in: stringToCheck,
                              tokenRange: wordRange,
                              skipRanges: skipRanges) {
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
