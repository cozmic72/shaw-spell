/*
 * Direct test of ShavianSpellChecker delegate methods
 */

#import <Foundation/Foundation.h>
#import "ShavianSpellChecker.h"

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        ShavianSpellChecker *checker = [[ShavianSpellChecker alloc] init];

        // Test strings
        NSArray *testStrings = @[
            @"𐑖𐑱𐑝𐑾𐑯",           // shavian (correct)
            @"𐑖𐑱𐑝𐑾𐑯𐑟𐑟𐑟",       // shavianzzz (misspelled)
            @"hello 𐑖𐑱𐑝𐑾𐑯 world",  // mixed Latin and Shavian (all correct)
            @"hello world",           // pure Latin (all correct)
            @"helo wrld",             // Latin misspellings
            @"The qwick brown fox"    // Latin misspelling (qwick)
        ];

        for (NSString *testString in testStrings) {
            printf("\n========================================\n");
            printf("Testing: %s\n", [testString UTF8String]);
            printf("Length: %lu\n", (unsigned long)testString.length);

            NSInteger wordCount = 0;
            NSRange misspelled = [checker spellServer:nil
                                findMisspelledWordInString:testString
                                                  language:@"en_GB"
                                                 wordCount:&wordCount
                                                 countOnly:NO];

            printf("Word count: %ld\n", (long)wordCount);

            if (misspelled.location != NSNotFound) {
                NSString *word = [testString substringWithRange:misspelled];
                printf("Misspelled word at (%lu, %lu): %s\n",
                       (unsigned long)misspelled.location,
                       (unsigned long)misspelled.length,
                       [word UTF8String]);

                // Get suggestions
                NSArray *suggestions = [checker spellServer:nil
                                    suggestGuessesForWord:word
                                               inLanguage:@"en_GB"];

                if (suggestions.count > 0) {
                    printf("Suggestions:\n");
                    for (NSString *suggestion in suggestions) {
                        printf("  - %s\n", [suggestion UTF8String]);
                    }
                } else {
                    printf("No suggestions\n");
                }
            } else {
                printf("No misspellings found\n");
            }
        }

        printf("\n========================================\n");
    }
    return 0;
}
