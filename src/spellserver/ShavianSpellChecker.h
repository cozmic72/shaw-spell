/*
 * ShavianSpellChecker - Delegate for NSSpellServer
 *
 * Implements spell-checking for English with both Latin and Shavian scripts:
 * - Detects which script is being used (Unicode ranges)
 * - Routes Shavian text to Hunspell dictionary
 * - Delegates Latin text to system spell checker
 */

#import <Foundation/Foundation.h>

@interface ShavianSpellChecker : NSObject <NSSpellServerDelegate>

// Initialization
- (instancetype)init;

// NSSpellServerDelegate required methods
- (NSRange)spellServer:(NSSpellServer *)sender
  findMisspelledWordInString:(NSString *)stringToCheck
                    language:(NSString *)language
                   wordCount:(NSInteger *)wordCount
                   countOnly:(BOOL)countOnly;

// NSSpellServerDelegate optional methods
- (NSArray<NSString *> *)spellServer:(NSSpellServer *)sender
            suggestGuessesForWord:(NSString *)word
                       inLanguage:(NSString *)language;

@end
