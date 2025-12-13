/*
 * ShavianSpellChecker - Implementation
 */

#import "ShavianSpellChecker.h"
#import <AppKit/AppKit.h>
#import "hunspell.h"

// Shavian Unicode range: U+10450 to U+1047F
#define SHAVIAN_START 0x10450
#define SHAVIAN_END   0x1047F

@implementation ShavianSpellChecker {
    Hunhandle *_shavianHandle;
    Hunhandle *_englishHandle;
}

- (instancetype)init {
    self = [super init];
    if (self) {
        // Initialize Hunspell with Shavian dictionary
        NSString *shawDicPath = [@"~/Library/Spelling/shaw.dic" stringByExpandingTildeInPath];
        NSString *shawAffPath = [@"~/Library/Spelling/shaw.aff" stringByExpandingTildeInPath];

        if ([[NSFileManager defaultManager] fileExistsAtPath:shawDicPath] &&
            [[NSFileManager defaultManager] fileExistsAtPath:shawAffPath]) {
            _shavianHandle = Hunspell_create([shawAffPath UTF8String], [shawDicPath UTF8String]);
            if (_shavianHandle) {
                NSLog(@"ShavianSpellChecker: Loaded Shavian dictionary from %@", shawDicPath);
            } else {
                NSLog(@"ShavianSpellChecker: Failed to load Shavian dictionary");
            }
        } else {
            NSLog(@"ShavianSpellChecker: Shavian dictionary files not found at %@", shawDicPath);
        }

        // Initialize Hunspell with English dictionary
        NSString *enDicPath = [@"~/Library/Spelling/en_GB.dic" stringByExpandingTildeInPath];
        NSString *enAffPath = [@"~/Library/Spelling/en_GB.aff" stringByExpandingTildeInPath];

        if ([[NSFileManager defaultManager] fileExistsAtPath:enDicPath] &&
            [[NSFileManager defaultManager] fileExistsAtPath:enAffPath]) {
            _englishHandle = Hunspell_create([enAffPath UTF8String], [enDicPath UTF8String]);
            if (_englishHandle) {
                NSLog(@"ShavianSpellChecker: Loaded English dictionary from %@", enDicPath);
            } else {
                NSLog(@"ShavianSpellChecker: Failed to load English dictionary");
            }
        } else {
            NSLog(@"ShavianSpellChecker: English dictionary files not found at %@", enDicPath);
        }

        NSLog(@"ShavianSpellChecker: Initialized");
    }
    return self;
}

- (void)dealloc {
    if (_shavianHandle) {
        Hunspell_destroy(_shavianHandle);
    }
    if (_englishHandle) {
        Hunspell_destroy(_englishHandle);
    }
}

#pragma mark - Script Detection

- (BOOL)containsShavianScript:(NSString *)string {
    // Shavian is in the supplementary plane (U+10450-1047F)
    // We need to check UTF-32 codepoints, not 16-bit unichars
    __block BOOL hasShavian = NO;

    [string enumerateSubstringsInRange:NSMakeRange(0, string.length)
                               options:NSStringEnumerationByComposedCharacterSequences
                            usingBlock:^(NSString *substring, NSRange subRange __unused, NSRange enclosingRange __unused, BOOL *stop) {
        // Get the Unicode scalar value (UTF-32)
        UTF32Char codepoint;
        [substring getBytes:&codepoint
                  maxLength:sizeof(codepoint)
                 usedLength:NULL
                   encoding:NSUTF32LittleEndianStringEncoding
                    options:0
                      range:NSMakeRange(0, substring.length)
             remainingRange:NULL];

        // Check if it's in the Shavian range
        if (codepoint >= SHAVIAN_START && codepoint <= SHAVIAN_END) {
            hasShavian = YES;
            *stop = YES;
        }
    }];

    return hasShavian;
}

#pragma mark - Word Boundary Detection

- (BOOL)isShavianOrLatinLetter:(UTF32Char)codepoint {
    // Latin letters (a-z, A-Z)
    if ((codepoint >= 0x0041 && codepoint <= 0x005A) ||  // A-Z
        (codepoint >= 0x0061 && codepoint <= 0x007A)) {  // a-z
        return YES;
    }
    // Shavian letters (𐑐-𐑿)
    if (codepoint >= SHAVIAN_START && codepoint <= SHAVIAN_END) {
        return YES;
    }
    return NO;
}

- (NSRange)findNextWordInString:(NSString *)string startingAt:(NSUInteger)start {
    NSLog(@"ShavianSpellChecker: findNextWord starting at %lu in string length %lu",
          (unsigned long)start, (unsigned long)string.length);

    if (start >= string.length) {
        return NSMakeRange(NSNotFound, 0);
    }

    // Manual word boundary detection for Shavian text
    // NSLinguisticTagger doesn't recognize Shavian as letters
    NSUInteger pos = start;
    NSUInteger wordStart = NSNotFound;

    // Skip non-letters to find word start
    while (pos < string.length) {
        NSRange range = [string rangeOfComposedCharacterSequenceAtIndex:pos];
        NSString *character = [string substringWithRange:range];

        UTF32Char codepoint = 0;
        [character getBytes:&codepoint
                  maxLength:sizeof(codepoint)
                 usedLength:NULL
                   encoding:NSUTF32LittleEndianStringEncoding
                    options:0
                      range:NSMakeRange(0, character.length)
             remainingRange:NULL];

        NSLog(@"ShavianSpellChecker: Checking character at pos %lu, codepoint=0x%X, isLetter=%d",
              (unsigned long)pos, codepoint, [self isShavianOrLatinLetter:codepoint]);

        if ([self isShavianOrLatinLetter:codepoint]) {
            wordStart = pos;
            NSLog(@"ShavianSpellChecker: Found word start at %lu", (unsigned long)pos);
            break;
        }

        pos = NSMaxRange(range);
    }

    if (wordStart == NSNotFound) {
        NSLog(@"ShavianSpellChecker: No word found");
        return NSMakeRange(NSNotFound, 0);
    }

    // Find word end
    pos = wordStart;
    NSUInteger wordEnd = wordStart;

    while (pos < string.length) {
        NSRange range = [string rangeOfComposedCharacterSequenceAtIndex:pos];
        NSString *character = [string substringWithRange:range];

        UTF32Char codepoint = 0;
        [character getBytes:&codepoint
                  maxLength:sizeof(codepoint)
                 usedLength:NULL
                   encoding:NSUTF32LittleEndianStringEncoding
                    options:0
                      range:NSMakeRange(0, character.length)
             remainingRange:NULL];

        if (![self isShavianOrLatinLetter:codepoint]) {
            break;
        }

        wordEnd = NSMaxRange(range);
        pos = wordEnd;
    }

    NSRange result = NSMakeRange(wordStart, wordEnd - wordStart);
    NSLog(@"ShavianSpellChecker: Found word at range (%lu, %lu): %@",
          (unsigned long)result.location, (unsigned long)result.length,
          [string substringWithRange:result]);
    return result;
}

#pragma mark - Spell Checking

- (BOOL)checkWord:(NSString *)word {
    // Determine which dictionary to use based on script
    BOOL isShavian = [self containsShavianScript:word];
    Hunhandle *handle = isShavian ? _shavianHandle : _englishHandle;

    if (!handle) {
        return YES; // No dictionary loaded for this script, assume correct
    }

    const char *utf8Word = [word UTF8String];
    int result = Hunspell_spell(handle, utf8Word);
    return result != 0; // Non-zero means correctly spelled
}

#pragma mark - NSSpellServerDelegate

- (NSRange)spellServer:(NSSpellServer *)sender
  findMisspelledWordInString:(NSString *)stringToCheck
                    language:(NSString *)language
                   wordCount:(NSInteger *)wordCount
                   countOnly:(BOOL)countOnly {

    NSLog(@"ShavianSpellChecker: findMisspelledWord called for language=%@, countOnly=%d, string length=%lu",
          language, countOnly, (unsigned long)stringToCheck.length);

    // Iterate through all words, checking both Shavian and Latin
    NSUInteger position = 0;
    NSInteger count = 0;

    while (position < stringToCheck.length) {
        NSRange wordRange = [self findNextWordInString:stringToCheck startingAt:position];

        if (wordRange.location == NSNotFound) {
            break; // No more words
        }

        count++;

        if (!countOnly) {
            NSString *word = [stringToCheck substringWithRange:wordRange];
            BOOL isShavian = [self containsShavianScript:word];

            NSLog(@"ShavianSpellChecker: Checking %@ word: %@",
                  isShavian ? @"Shavian" : @"Latin", word);

            if (![self checkWord:word]) {
                // Found misspelled word
                NSLog(@"ShavianSpellChecker: MISSPELLED: %@", word);
                if (wordCount) {
                    *wordCount = count;
                }
                return wordRange;
            } else {
                NSLog(@"ShavianSpellChecker: Word is correct");
            }
        }

        // Move to next word
        position = NSMaxRange(wordRange);
    }

    if (wordCount) {
        *wordCount = count;
    }

    return NSMakeRange(NSNotFound, 0); // No misspelled words found
}

- (NSArray<NSString *> *)spellServer:(NSSpellServer *)sender
            suggestGuessesForWord:(NSString *)word
                       inLanguage:(NSString *)language {

    NSLog(@"ShavianSpellChecker: suggestGuesses called for word: %@", word);

    // Determine which dictionary to use based on script
    BOOL isShavian = [self containsShavianScript:word];
    Hunhandle *handle = isShavian ? _shavianHandle : _englishHandle;

    if (!handle) {
        NSLog(@"ShavianSpellChecker: No dictionary loaded for this script");
        return @[];
    }

    NSLog(@"ShavianSpellChecker: Getting suggestions from %@ dictionary", isShavian ? @"Shavian" : @"English");

    char **suggestions = NULL;
    int count = Hunspell_suggest(handle, &suggestions, [word UTF8String]);

    NSMutableArray *results = [NSMutableArray array];
    for (int i = 0; i < count && i < 10; i++) { // Limit to 10 suggestions
        NSString *suggestion = [NSString stringWithUTF8String:suggestions[i]];
        if (suggestion) {
            [results addObject:suggestion];
        }
    }

    // Free Hunspell suggestions
    Hunspell_free_list(handle, &suggestions, count);

    NSLog(@"ShavianSpellChecker: Returning %lu suggestions", (unsigned long)results.count);
    return results;
}

@end
