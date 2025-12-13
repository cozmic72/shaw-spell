/*
 * Test spell checking through NSTextView (closer to real app usage)
 */

#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        [NSApplication sharedApplication];

        // Create a text view
        NSTextView *textView = [[NSTextView alloc] initWithFrame:NSMakeRect(0, 0, 400, 300)];
        [textView setContinuousSpellCheckingEnabled:YES];

        // Set the language
        [textView setSpellingState:NSSpellingStateSpellingFlag range:NSMakeRange(0, 0)];

        // Test string with intentional misspelling: 𐑖𐑱𐑝𐑾𐑯𐑟𐑟𐑟
        NSString *testString = @"𐑖𐑱𐑝𐑾𐑯𐑟𐑟𐑟";
        [textView setString:testString];

        printf("Testing with NSTextView\n");
        printf("String: %s\n", [testString UTF8String]);
        printf("Length: %lu\n", (unsigned long)testString.length);

        // Trigger spell checking
        [[NSSpellChecker sharedSpellChecker] setLanguage:@"en_GB"];

        // Check spelling directly
        NSRange misspelledRange = [[NSSpellChecker sharedSpellChecker]
            checkSpellingOfString:testString
            startingAt:0
            language:@"en_GB"
            wrap:NO
            inSpellDocumentWithTag:[textView spellCheckerDocumentTag]
            wordCount:NULL];

        if (misspelledRange.location != NSNotFound) {
            NSString *misspelled = [testString substringWithRange:misspelledRange];
            printf("\nFound misspelling at (%lu, %lu): %s\n",
                   (unsigned long)misspelledRange.location,
                   (unsigned long)misspelledRange.length,
                   [misspelled UTF8String]);
        } else {
            printf("\nNo misspellings found\n");
        }

        // Try checking the whole text storage
        [textView checkTextInDocument:nil];

        // Small delay to let spell server respond
        [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:2.0]];

        printf("Done\n");
    }
    return 0;
}
