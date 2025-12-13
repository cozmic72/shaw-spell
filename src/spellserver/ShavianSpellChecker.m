/*
 * ShavianSpellChecker - Implementation
 */

#import "ShavianSpellChecker.h"
#import <AppKit/AppKit.h>
#import "hunspell/hunspell.h"

// Shavian Unicode range: U+10450 to U+1047F
#define SHAVIAN_START 0x10450
#define SHAVIAN_END   0x1047F

@implementation ShavianSpellChecker {
    Hunhandle *_hunspellHandle;
    NSSpellChecker *_systemChecker;
}

- (instancetype)init {
    self = [super init];
    if (self) {
        // Initialize Hunspell with our Shavian dictionary
        NSString *dicPath = [@"~/Library/Spelling/shaw.dic" stringByExpandingTildeInPath];
        NSString *affPath = [@"~/Library/Spelling/shaw.aff" stringByExpandingTildeInPath];

        if ([[NSFileManager defaultManager] fileExistsAtPath:dicPath] &&
            [[NSFileManager defaultManager] fileExistsAtPath:affPath]) {
            _hunspellHandle = Hunspell_create([affPath UTF8String], [dicPath UTF8String]);
            if (_hunspellHandle) {
                NSLog(@"ShavianSpellChecker: Loaded Hunspell dictionary from %@", dicPath);
            } else {
                NSLog(@"ShavianSpellChecker: Failed to load Hunspell dictionary");
            }
        } else {
            NSLog(@"ShavianSpellChecker: Dictionary files not found at %@", dicPath);
        }

        // Get system spell checker for delegating Latin text
        _systemChecker = [NSSpellChecker sharedSpellChecker];
        NSLog(@"ShavianSpellChecker: Initialized");
    }
    return self;
}

- (void)dealloc {
    if (_hunspellHandle) {
        Hunspell_destroy(_hunspellHandle);
    }
}

#pragma mark - Script Detection

- (BOOL)isShavianCharacter:(unichar)character {
    return (character >= SHAVIAN_START && character <= SHAVIAN_END);
}

- (BOOL)containsShavianScript:(NSString *)string {
    __block BOOL hasShavian = NO;
    [string enumerateSubstringsInRange:NSMakeRange(0, string.length)
                               options:NSStringEnumerationByComposedCharacterSequences
                            usingBlock:^(NSString *substring, NSRange range, NSRange enclosingRange, BOOL *stop) {
        UTF32Char character = [substring characterAtIndex:0];
        if ([self isShavianCharacter:character]) {
            hasShavian = YES;
            *stop = YES;
        }
    }];
    return hasShavian;
}

#pragma mark - Word Extraction

- (NSArray<NSValue *> *)wordRangesInString:(NSString *)string {
    NSMutableArray *ranges = [NSMutableArray array];
    NSRange searchRange = NSMakeRange(0, string.length);

    while (searchRange.location < string.length) {
        NSRange wordRange = [string rangeOfCharacterFromSet:[NSCharacterSet letterCharacterSet]
                                                     options:0
                                                       range:searchRange];
        if (wordRange.location == NSNotFound) {
            break;
        }

        // Extend to full word
        NSRange fullWordRange = wordRange;
        while (fullWordRange.location > 0) {
            unichar prev = [string characterAtIndex:fullWordRange.location - 1];
            if (![[NSCharacterSet letterCharacterSet] characterIsMember:prev]) {
                break;
            }
            fullWordRange.location--;
            fullWordRange.length++;
        }

        while (NSMaxRange(fullWordRange) < string.length) {
            unichar next = [string characterAtIndex:NSMaxRange(fullWordRange)];
            if (![[NSCharacterSet letterCharacterSet] characterIsMember:next]) {
                break;
            }
            fullWordRange.length++;
        }

        [ranges addObject:[NSValue valueWithRange:fullWordRange]];

        searchRange.location = NSMaxRange(fullWordRange);
        searchRange.length = string.length - searchRange.location;
    }

    return ranges;
}

#pragma mark - Spell Checking

- (BOOL)checkShavianWord:(NSString *)word {
    if (!_hunspellHandle) {
        return YES; // No dictionary loaded, assume correct
    }

    const char *utf8Word = [word UTF8String];
    int result = Hunspell_spell(_hunspellHandle, utf8Word);
    return result != 0; // Non-zero means correctly spelled
}

- (BOOL)checkLatinWord:(NSString *)word language:(NSString *)language {
    // Delegate to system spell checker
    NSRange misspelledRange = [_systemChecker checkSpellingOfString:word
                                                         startingAt:0
                                                           language:language
                                                               wrap:NO
                                             inSpellDocumentWithTag:0
                                                          wordCount:NULL];
    return misspelledRange.location == NSNotFound;
}

#pragma mark - NSSpellServerDelegate

- (NSRange)spellServer:(NSSpellServer *)sender
  findMisspelledWordInString:(NSString *)stringToCheck
                    language:(NSString *)language
                   wordCount:(NSInteger *)wordCount
                   countOnly:(BOOL)countOnly {

    // Get all word ranges
    NSArray<NSValue *> *wordRanges = [self wordRangesInString:stringToCheck];

    if (wordCount) {
        *wordCount = wordRanges.count;
    }

    if (countOnly) {
        return NSMakeRange(NSNotFound, 0);
    }

    // Check each word
    for (NSValue *rangeValue in wordRanges) {
        NSRange wordRange = [rangeValue rangeValue];
        NSString *word = [stringToCheck substringWithRange:wordRange];

        BOOL isCorrect;
        if ([self containsShavianScript:word]) {
            // Shavian word - use Hunspell
            isCorrect = [self checkShavianWord:word];
        } else {
            // Latin word - delegate to system
            isCorrect = [self checkLatinWord:word language:language];
        }

        if (!isCorrect) {
            return wordRange; // Return first misspelled word
        }
    }

    return NSMakeRange(NSNotFound, 0); // No misspelled words
}

- (NSArray<NSString *> *)spellServer:(NSSpellServer *)sender
            suggestGuessesForWord:(NSString *)word
                       inLanguage:(NSString *)language {

    if ([self containsShavianScript:word]) {
        // Shavian word - use Hunspell suggestions
        if (!_hunspellHandle) {
            return @[];
        }

        char **suggestions = NULL;
        int count = Hunspell_suggest(_hunspellHandle, &suggestions, [word UTF8String]);

        NSMutableArray *results = [NSMutableArray array];
        for (int i = 0; i < count && i < 10; i++) { // Limit to 10 suggestions
            NSString *suggestion = [NSString stringWithUTF8String:suggestions[i]];
            if (suggestion) {
                [results addObject:suggestion];
            }
        }

        // Free Hunspell suggestions
        Hunspell_free_list(_hunspellHandle, &suggestions, count);

        return results;
    } else {
        // Latin word - delegate to system
        NSArray *guesses = [_systemChecker guessesForWordRange:NSMakeRange(0, word.length)
                                                       inString:word
                                                       language:language
                                         inSpellDocumentWithTag:0];
        return guesses ?: @[];
    }
}

@end
