/*
 * Test program to invoke the spell checker programmatically
 */

#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSSpellChecker *checker = [NSSpellChecker sharedSpellChecker];

        // List available spell servers
        printf("Available spell checkers:\n");
        NSArray *availableLanguages = [checker availableLanguages];
        for (NSString *lang in availableLanguages) {
            printf("  - %s\n", [lang UTF8String]);
        }
        printf("\n");

        // Test string with intentional misspelling: 𐑖𐑱𐑝𐑾𐑯𐑟𐑟𐑟
        NSString *testString = @"𐑖𐑱𐑝𐑾𐑯𐑟𐑟𐑟";

        printf("Testing spell checking for: %s\n", [testString UTF8String]);
        printf("String length: %lu\n", (unsigned long)testString.length);

        // Set language to British English (ShawDict)
        NSString *language = @"en_GB";

        // Try to set the language explicitly
        [checker setLanguage:language];
        printf("Current language: %s\n", [[checker language] UTF8String]);
        printf("\n");

        // Check spelling
        NSRange misspelledRange = [checker checkSpellingOfString:testString
                                                   startingAt:0
                                                     language:language
                                                         wrap:NO
                                       inSpellDocumentWithTag:0
                                                    wordCount:NULL];

        if (misspelledRange.location != NSNotFound) {
            NSString *misspelledWord = [testString substringWithRange:misspelledRange];
            printf("Found misspelled word at range (%lu, %lu): %s\n",
                   (unsigned long)misspelledRange.location,
                   (unsigned long)misspelledRange.length,
                   [misspelledWord UTF8String]);

            // Get suggestions
            NSArray *suggestions = [checker guessesForWordRange:misspelledRange
                                                       inString:testString
                                                       language:language
                                         inSpellDocumentWithTag:0];
            if (suggestions.count > 0) {
                printf("Suggestions:\n");
                for (NSString *suggestion in suggestions) {
                    printf("  - %s\n", [suggestion UTF8String]);
                }
            } else {
                printf("No suggestions available.\n");
            }
        } else {
            printf("No misspelled words found.\n");
        }
    }
    return 0;
}
